"""Orchestrator / flow-builder layer — LangGraph StateGraphs driving the
qualification conversation.

v1's main `graph` is deliberately minimal: a single `chatbot` node wrapping
the existing grounded (Gemini File Search) reply-generation call, no
conditional routing yet. Guard-clause logic that never touches the LLM
prompt (invalid-pincode retries, dealer-card stitching, brochure gating,
CRM dispose) stays in client_processing.py for now — see the migration
plan for the full phase-by-phase rollout. This module is the seam later
phases will extend with conditional edges as that logic moves in.

`still_interested_graph` is the first classification step wired into the
live client_processing.py path — it only decides `declining: bool`; all
session/dispose/reply-text side effects stay in
client_processing._apply_still_interested, same discipline as everything
else in this file.

Compiled with no checkpointer: RQ workers are stateless per job, and
session persistence already lives in RedisClientState (see bot/state.py).
"""
import logging
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from bot.llm import get_llm
from bot.state import BotState

log = logging.getLogger(__name__)


def chatbot(state: BotState) -> dict:
    from conversation_engine import build_contents, build_system_instruction, parse_profile_json

    system_instruction = build_system_instruction(
        state["config"],
        state["language"],
        product_hint=state.get("product_hint", ""),
        confirm_crm_dealer=state.get("confirm_crm_dealer", False),
    )
    contents = build_contents(state["history"], state["user_text"])
    result = get_llm("smart").generate(system_instruction=system_instruction, contents=contents)
    reply_text, profile = parse_profile_json(result.text or "")
    return {
        "reply_text": reply_text,
        "lead_profile": profile,
        "captured": profile is not None,
        "citations": list(result.citations),
    }


builder = StateGraph(BotState)
builder.add_node("chatbot", chatbot)
builder.add_edge(START, "chatbot")
builder.add_edge("chatbot", END)

graph = builder.compile()


class StillInterestedState(TypedDict):
    user_message: str
    declining: bool


class StillInterestedClassification(BaseModel):
    declining: bool = Field(
        description=(
            "True only if the customer is clearly declining / no longer interested "
            "in purchasing. False for everything else — undecided, asking about a "
            "different product, asking an unrelated question, off-topic, or any "
            "reply that doesn't explicitly decline — all of those should continue "
            "into normal qualification rather than closing the lead."
        )
    )


def _route_still_interested_reply(state: StillInterestedState) -> str:
    # Deferred import: client_processing imports classify_still_interested_reply
    # from this module, so a top-level import here would be circular.
    from client_processing import _is_still_interested_no, _is_still_interested_yes

    if _is_still_interested_no(state["user_message"]):
        return "declining"
    if _is_still_interested_yes(state["user_message"]):
        return "proceeding"
    return "classify"


def _declining(state: StillInterestedState) -> dict:
    return {"declining": True}


def _proceeding(state: StillInterestedState) -> dict:
    return {"declining": False}


def _classify_still_interested(state: StillInterestedState) -> dict:
    # Any classifier failure (quota, network, missing key in a non-prod
    # profile) defaults to "not declining" — same safe default as an
    # ambiguous reply, never silently drops the customer's message.
    try:
        classifier = get_llm("fast").with_structured_output(StillInterestedClassification)
        result = classifier.invoke(
            "The customer was asked whether they are still planning to purchase a "
            "vehicle they previously enquired about. They replied: "
            f"{state['user_message']!r}. Decide whether this is a clear decline."
        )
        return {"declining": result.declining}
    except Exception:
        log.exception("still-interested classifier call failed; defaulting to proceed")
        return {"declining": False}


still_interested_builder = StateGraph(StillInterestedState)
still_interested_builder.add_node("declining", _declining)
still_interested_builder.add_node("proceeding", _proceeding)
still_interested_builder.add_node("classify", _classify_still_interested)
still_interested_builder.add_conditional_edges(
    START, _route_still_interested_reply, ["declining", "proceeding", "classify"]
)
still_interested_builder.add_edge("declining", END)
still_interested_builder.add_edge("proceeding", END)
still_interested_builder.add_edge("classify", END)

still_interested_graph = still_interested_builder.compile()


def classify_still_interested_reply(user_message: str) -> bool:
    """True if the customer clearly declined; False otherwise (proceed to
    qualification) — regex fast path first, LLM fallback only when
    genuinely ambiguous."""
    result = still_interested_graph.invoke({"user_message": user_message})
    return result["declining"]

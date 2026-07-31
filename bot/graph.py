"""Orchestrator / flow-builder layer — a LangGraph StateGraph driving the
qualification conversation.

v1 is deliberately minimal: a single `chatbot` node wrapping the existing
grounded (Gemini File Search) reply-generation call, no conditional
routing yet. Guard-clause logic that never touches the LLM prompt
(still-interested checks, invalid-pincode retries, dealer-card stitching,
brochure gating, CRM dispose) stays in client_processing.py for now — see
the migration plan for the full phase-by-phase rollout. This module is the
seam later phases will extend with conditional edges as that logic moves
in.

Compiled with no checkpointer: RQ workers are stateless per job, and
session persistence already lives in RedisClientState (see bot/state.py).
"""
from langgraph.graph import END, START, StateGraph

from bot.llm import get_llm
from bot.state import BotState


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

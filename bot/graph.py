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
import re
from typing import Literal, TypedDict

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


class DealerConfirmState(TypedDict):
    user_message: str
    result: str  # "yes" | "no" | "unclear"


class DealerConfirmClassification(BaseModel):
    result: Literal["yes", "no", "unclear"] = Field(
        description=(
            "'yes' if the customer is confirming/accepting the suggested "
            "dealership (even loosely phrased, e.g. 'haan ye mera dealer hai', "
            "'yes I have this one', 'ha ye dealership mere pass hai'). 'no' if "
            "they're rejecting/correcting it (e.g. 'nahi ye galat hai', 'not "
            "this one'). 'unclear' if the reply doesn't address the dealership "
            "at all (a question, an unrelated message, a fresh pincode) — do "
            "not guess in that case."
        )
    )


def _route_dealer_confirm_reply(state: DealerConfirmState) -> str:
    # Deferred import: circular with client_processing, same reason as
    # _route_still_interested_reply above.
    from client_processing import _is_affirmative, _is_negative

    if _is_negative(state["user_message"]):
        return "no"
    if _is_affirmative(state["user_message"]):
        return "yes"
    return "classify"


def _dealer_confirm_yes(state: DealerConfirmState) -> dict:
    return {"result": "yes"}


def _dealer_confirm_no(state: DealerConfirmState) -> dict:
    return {"result": "no"}


def _classify_dealer_confirm(state: DealerConfirmState) -> dict:
    # Any classifier failure defaults to "unclear" — same safe fallback the
    # existing code already has for a reply that doesn't resolve cleanly
    # (re-attach the card, answer the customer's message, ask again).
    try:
        classifier = get_llm("fast").with_structured_output(DealerConfirmClassification)
        result = classifier.invoke(
            "The customer was shown a suggested dealership and asked to "
            "confirm whether it's OK / near them (Yes or No). They replied: "
            f"{state['user_message']!r}. Classify their reply."
        )
        return {"result": result.result}
    except Exception:
        log.exception("dealer-confirm classifier call failed; defaulting to unclear")
        return {"result": "unclear"}


dealer_confirm_builder = StateGraph(DealerConfirmState)
dealer_confirm_builder.add_node("yes", _dealer_confirm_yes)
dealer_confirm_builder.add_node("no", _dealer_confirm_no)
dealer_confirm_builder.add_node("classify", _classify_dealer_confirm)
dealer_confirm_builder.add_conditional_edges(
    START, _route_dealer_confirm_reply, ["yes", "no", "classify"]
)
dealer_confirm_builder.add_edge("yes", END)
dealer_confirm_builder.add_edge("no", END)
dealer_confirm_builder.add_edge("classify", END)

dealer_confirm_graph = dealer_confirm_builder.compile()


def classify_dealer_confirm_reply(user_message: str) -> str:
    """Returns "yes" | "no" | "unclear" — regex fast path first, LLM
    fallback only when genuinely ambiguous."""
    result = dealer_confirm_graph.invoke({"user_message": user_message})
    return result["result"]


class BrochureOfferState(TypedDict):
    user_message: str
    result: str  # "yes" | "no" | "unclear"


class BrochureOfferClassification(BaseModel):
    result: Literal["yes", "no", "unclear"] = Field(
        description=(
            "'yes' only if the customer wants the brochure/PDF/catalog "
            "sent now — in any language or spelling (e.g. 'bhejo', "
            "'haan bhej do', 'send it', 'भेजो', 'पाठवा', 'ok send brochure'). "
            "'no' if they decline the file (e.g. 'nahi', 'no need', "
            "'mat bhejo'). 'unclear' for acknowledgements or unrelated "
            "replies that do not ask for the document ('ok noted', "
            "'thanks', a price question, a pincode) — do NOT treat bare "
            "'ok'/'thanks' as yes unless they clearly want the file sent."
        )
    )


def _route_brochure_offer_reply(state: BrochureOfferState) -> str:
    from client_processing import (
        _is_brochure_offer_accept,
        _is_negative,
    )

    if _is_negative(state["user_message"]):
        return "no"
    if _is_brochure_offer_accept(state["user_message"]):
        return "yes"
    return "classify"


def _brochure_offer_yes(state: BrochureOfferState) -> dict:
    return {"result": "yes"}


def _brochure_offer_no(state: BrochureOfferState) -> dict:
    return {"result": "no"}


def _classify_brochure_offer(state: BrochureOfferState) -> dict:
    try:
        classifier = get_llm("fast").with_structured_output(
            BrochureOfferClassification
        )
        result = classifier.invoke(
            "The bot just answered a product question and asked whether "
            "to send the product brochure/PDF. The customer replied (any "
            "language): "
            f"{state['user_message']!r}. "
            "Classify whether they want the document sent now."
        )
        return {"result": result.result}
    except Exception:
        log.exception(
            "brochure-offer classifier call failed; defaulting to unclear"
        )
        return {"result": "unclear"}


brochure_offer_builder = StateGraph(BrochureOfferState)
brochure_offer_builder.add_node("yes", _brochure_offer_yes)
brochure_offer_builder.add_node("no", _brochure_offer_no)
brochure_offer_builder.add_node("classify", _classify_brochure_offer)
brochure_offer_builder.add_conditional_edges(
    START, _route_brochure_offer_reply, ["yes", "no", "classify"]
)
brochure_offer_builder.add_edge("yes", END)
brochure_offer_builder.add_edge("no", END)
brochure_offer_builder.add_edge("classify", END)

brochure_offer_graph = brochure_offer_builder.compile()


def classify_brochure_offer_reply(user_message: str) -> str:
    """Returns "yes" | "no" | "unclear" for a pending brochure offer —
    regex fast path first, LLM for any-language phrasing."""
    result = brochure_offer_graph.invoke({"user_message": user_message})
    return result["result"]


class BrochureRequestState(TypedDict):
    user_message: str
    wants_brochure: bool


class BrochureRequestClassification(BaseModel):
    wants_brochure: bool = Field(
        description=(
            "True only if the customer is asking the bot to send a "
            "product brochure, PDF, catalog, pamphlet, or similar "
            "document now — in any language or misspelling. False for "
            "general product questions, greetings, pincodes, dealer "
            "talk, or anything that is not a document-send request."
        )
    )


# Soft gate so we don't call the LLM on every turn — only when the
# message might be a document-send ask the regex missed.
_BROCHURE_REQUEST_SOFT_RE = re.compile(
    r"(?i)("
    r"bhej|send|share|pdf|brochure|brocher|catalog|catalogue|"
    r"document|pamphlet|leaflet|file|"
    r"भेज|ब्रोशर|ब्रॉशर|पीडीएफ|कैटलॉग|कॅटलॉग|पाठव|"
    r"బ్రోచర్|பிரோஷர்|ಬ್ರೋಷರ್|ബ്രോഷർ"
    r")"
)


def _route_brochure_request(state: BrochureRequestState) -> str:
    from client_media_assets import wants_product_brochure

    msg = state["user_message"]
    if wants_product_brochure(msg):
        return "yes"
    if not _BROCHURE_REQUEST_SOFT_RE.search(msg or ""):
        return "no"
    return "classify"


def _brochure_request_yes(state: BrochureRequestState) -> dict:
    return {"wants_brochure": True}


def _brochure_request_no(state: BrochureRequestState) -> dict:
    return {"wants_brochure": False}


def _classify_brochure_request(state: BrochureRequestState) -> dict:
    try:
        classifier = get_llm("fast").with_structured_output(
            BrochureRequestClassification
        )
        result = classifier.invoke(
            "In a TVS three-wheeler sales WhatsApp chat, the customer "
            "said (any language): "
            f"{state['user_message']!r}. "
            "Are they asking you to send a brochure/PDF/catalog document?"
        )
        return {"wants_brochure": bool(result.wants_brochure)}
    except Exception:
        log.exception(
            "brochure-request classifier call failed; defaulting to False"
        )
        return {"wants_brochure": False}


brochure_request_builder = StateGraph(BrochureRequestState)
brochure_request_builder.add_node("yes", _brochure_request_yes)
brochure_request_builder.add_node("no", _brochure_request_no)
brochure_request_builder.add_node("classify", _classify_brochure_request)
brochure_request_builder.add_conditional_edges(
    START, _route_brochure_request, ["yes", "no", "classify"]
)
brochure_request_builder.add_edge("yes", END)
brochure_request_builder.add_edge("no", END)
brochure_request_builder.add_edge("classify", END)

brochure_request_graph = brochure_request_builder.compile()


def classify_brochure_request(user_message: str) -> bool:
    """True if the customer is asking for a brochure/PDF — regex fast
    path, then soft-signal + LLM for other languages/phrasing."""
    result = brochure_request_graph.invoke({"user_message": user_message})
    return bool(result["wants_brochure"])

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
    contents = build_contents(
        state["history"], state["user_text"], state.get("known_state", "")
    )
    result = get_llm("smart").generate(system_instruction=system_instruction, contents=contents)
    reply_text, profile = parse_profile_json(result.text or "")
    return {
        "reply_text": reply_text,
        "lead_profile": profile,
        "captured": profile is not None,
        "citations": list(result.citations),
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
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
    r"bhej|behj|send|share|pdf|brochure|brocher|catalog|catalogue|"
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


class ShareConsentState(TypedDict):
    user_message: str
    result: str  # "yes" | "no" | "unclear"


class ShareConsentClassification(BaseModel):
    result: Literal["yes", "no", "unclear"] = Field(
        description=(
            "The bot asked whether it may share the customer's nearest "
            "dealership details. 'yes' if they want them (any language: "
            "'haan', 'ok show', 'दाखवा', 'भेजो'). 'no' if they decline "
            "('nahi', 'not now', 'later'). 'unclear' if the reply is about "
            "something else entirely — a question, a product name, a "
            "pincode — in which case do not assume consent."
        )
    )


def _route_share_consent(state: ShareConsentState) -> str:
    from client_processing import _is_affirmative, _is_negative

    if _is_negative(state["user_message"]):
        return "no"
    if _is_affirmative(state["user_message"]):
        return "yes"
    return "classify"


def _share_consent_yes(state: ShareConsentState) -> dict:
    return {"result": "yes"}


def _share_consent_no(state: ShareConsentState) -> dict:
    return {"result": "no"}


def _classify_share_consent(state: ShareConsentState) -> dict:
    # Failure defaults to "unclear" — never share contact details on a guess.
    try:
        classifier = get_llm("fast").with_structured_output(
            ShareConsentClassification
        )
        result = classifier.invoke(
            "The bot asked the customer whether it should share their "
            "nearest TVS dealership details. They replied (any language): "
            f"{state['user_message']!r}. Classify their reply."
        )
        return {"result": result.result}
    except Exception:
        log.exception("share-consent classifier call failed; defaulting to unclear")
        return {"result": "unclear"}


share_consent_builder = StateGraph(ShareConsentState)
share_consent_builder.add_node("yes", _share_consent_yes)
share_consent_builder.add_node("no", _share_consent_no)
share_consent_builder.add_node("classify", _classify_share_consent)
share_consent_builder.add_conditional_edges(
    START, _route_share_consent, ["yes", "no", "classify"]
)
share_consent_builder.add_edge("yes", END)
share_consent_builder.add_edge("no", END)
share_consent_builder.add_edge("classify", END)

share_consent_graph = share_consent_builder.compile()


def classify_share_consent_reply(user_message: str) -> str:
    """Returns "yes" | "no" | "unclear" for a pending "may I share the
    dealership details?" question — regex fast path, then LLM."""
    result = share_consent_graph.invoke(
        {"user_message": user_message, "result": "unclear"}
    )
    return result["result"]


class LanguageSwitchState(TypedDict):
    user_message: str
    language: str  # a supported language name, or "" for no switch


class LanguageSwitchClassification(BaseModel):
    language: Literal[
        "English",
        "Hindi",
        "Marathi",
        "Telugu",
        "Tamil",
        "Kannada",
        "Malayalam",
        "none",
    ] = Field(
        description=(
            "The language the customer is ASKING TO BE REPLIED IN, if they "
            "asked to switch at all — e.g. 'can you talk in English', "
            "'हिंदी में बात करो', 'मराठीत बोला', 'speak english please'. "
            "Answer 'none' if they are not requesting a language change: "
            "merely writing in a language is NOT a request, and neither is "
            "mentioning a language in passing."
        )
    )


# Soft gate: only spend a call when the message plausibly asks for a switch.
_LANGUAGE_SWITCH_SOFT_RE = re.compile(
    r"(?i)("
    r"english|hindi|marathi|telugu|tamil|kannada|malayalam|malyalam|"
    r"हिंदी|हिन्दी|मराठी|తెలుగు|தமிழ்|ಕನ್ನಡ|മലയാളം|"
    r"\b(speak|talk|語|language|bhasha|bhaasha)\b|"
    r"भाषा|भाषेत|बोल|बात\s*कर"
    r")"
)


def _route_language_switch(state: LanguageSwitchState) -> str:
    from client_language import parse_language_choice

    message = state["user_message"] or ""
    # Menu-style replies ("2", "Hindi", "मराठी") are unambiguous.
    choice = parse_language_choice(message)
    if choice and len(message.strip()) <= 24:
        return "explicit"
    if not _LANGUAGE_SWITCH_SOFT_RE.search(message):
        return "none"
    return "classify"


def _language_switch_explicit(state: LanguageSwitchState) -> dict:
    from client_language import parse_language_choice

    return {"language": parse_language_choice(state["user_message"] or "")}


def _language_switch_none(state: LanguageSwitchState) -> dict:
    return {"language": ""}


def _classify_language_switch(state: LanguageSwitchState) -> dict:
    # Failure means "no switch" — keep replying in the language already in
    # use rather than guessing a new one.
    try:
        classifier = get_llm("fast").with_structured_output(
            LanguageSwitchClassification
        )
        result = classifier.invoke(
            "In a TVS three-wheeler sales WhatsApp chat the customer said: "
            f"{state['user_message']!r}. Are they asking the bot to reply in "
            "a different language, and which one?"
        )
        language = result.language
        return {"language": "" if language == "none" else language}
    except Exception:
        log.exception("language-switch classifier call failed; defaulting to none")
        return {"language": ""}


language_switch_builder = StateGraph(LanguageSwitchState)
language_switch_builder.add_node("explicit", _language_switch_explicit)
language_switch_builder.add_node("none", _language_switch_none)
language_switch_builder.add_node("classify", _classify_language_switch)
language_switch_builder.add_conditional_edges(
    START, _route_language_switch, ["explicit", "none", "classify"]
)
language_switch_builder.add_edge("explicit", END)
language_switch_builder.add_edge("none", END)
language_switch_builder.add_edge("classify", END)

language_switch_graph = language_switch_builder.compile()


def classify_language_switch(user_message: str) -> str:
    """The language the customer asked to be answered in, or "".

    The old check required the whole message to parse as a language name and
    be under 24 characters, so "can you please speak in english" was ignored
    — and it never ran on voice notes at all (bug 010802 / 230701).
    """
    result = language_switch_graph.invoke(
        {"user_message": user_message, "language": ""}
    )
    return result["language"] or ""


class LocationReplyState(TypedDict):
    last_bot_message: str
    user_message: str
    result: str  # "place_name" | "bad_pincode" | "other"


class LocationReplyClassification(BaseModel):
    result: Literal["place_name", "bad_pincode", "other"] = Field(
        description=(
            "Classify ONLY how the customer answered a request for their "
            "location. 'place_name' if they named a city, town, area, "
            "locality or district instead of giving a pincode (e.g. "
            "'Parbhani', 'Andheri west', 'मी नाशिकहून आहे'). "
            "'bad_pincode' if they clearly meant to give a pincode but it "
            "is not a valid 6-digit Indian pin (e.g. '41103', '4110355'). "
            "'other' for EVERYTHING else — acknowledgements ('ok', 'okk', "
            "'thik hai', 'haa', 'hmm', 'done'), thanks, questions, "
            "product talk, a budget or a year that happens to be numeric, "
            "or any message that is not them stating where they are. When "
            "in doubt answer 'other' — the normal conversation handles it."
        )
    )


# High-precision fast path: the customer names the field themselves, so
# "pincode 41103" needs no LLM. A bare number does NOT qualify — "50000"
# is a budget as often as a typo'd pin, and only the last bot message
# tells them apart.
_EXPLICIT_PIN_RE = re.compile(
    r"(?i)\b(pin|pin\s*code|pincode|postal\s*code|पिनकोड|पिन\s*कोड)\b"
)


def _route_location_reply(state: LocationReplyState) -> str:
    # A valid pincode needs no classification — the caller handles it.
    from dealers import extract_pincode

    message = state["user_message"] or ""
    if extract_pincode(message):
        return "other"
    if not message.strip():
        return "other"
    if _EXPLICIT_PIN_RE.search(message) and re.search(r"\d{3,8}", message):
        return "bad_pincode"
    return "classify"


def _location_reply_bad_pincode(state: LocationReplyState) -> dict:
    return {"result": "bad_pincode"}


def _location_reply_other(state: LocationReplyState) -> dict:
    return {"result": "other"}


def _classify_location_reply(state: LocationReplyState) -> dict:
    # Failure defaults to "other" so the turn falls through to normal
    # qualification rather than being hijacked by a canned location reply.
    try:
        classifier = get_llm("fast").with_structured_output(
            LocationReplyClassification
        )
        result = classifier.invoke(
            "In a TVS three-wheeler sales WhatsApp chat, the bot's last "
            f"message was: {state['last_bot_message']!r}. The customer "
            f"replied (any language): {state['user_message']!r}. "
            "Did they answer with a place name, a malformed pincode, or "
            "something else entirely?"
        )
        return {"result": result.result}
    except Exception:
        log.exception("location-reply classifier call failed; defaulting to other")
        return {"result": "other"}


location_reply_builder = StateGraph(LocationReplyState)
location_reply_builder.add_node("other", _location_reply_other)
location_reply_builder.add_node("bad_pincode", _location_reply_bad_pincode)
location_reply_builder.add_node("classify", _classify_location_reply)
location_reply_builder.add_conditional_edges(
    START, _route_location_reply, ["other", "bad_pincode", "classify"]
)
location_reply_builder.add_edge("other", END)
location_reply_builder.add_edge("bad_pincode", END)
location_reply_builder.add_edge("classify", END)

location_reply_graph = location_reply_builder.compile()


def classify_location_reply(user_message: str, last_bot_message: str = "") -> str:
    """Returns "place_name" | "bad_pincode" | "other".

    Replaces the old deny-list regexes (``looks_like_place_name`` /
    ``looks_like_invalid_pincode`` as *gates*): a deny-list treats every
    unlisted word as a city, so ordinary chat filler ("okk", "thik hai",
    "hmm") was answered with the share-location card. The LLM sees what the
    bot actually just asked, so it can tell "Parbhani" from "okay".
    """
    result = location_reply_graph.invoke(
        {
            "user_message": user_message,
            "last_bot_message": last_bot_message,
            "result": "other",
        }
    )
    return result["result"]

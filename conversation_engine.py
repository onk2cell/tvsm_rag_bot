"""Channel-agnostic qualification conversation engine."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from admin_config import AdminConfigStore, active_campaign_text
from leads import LeadWriter

PROFILE_JSON_RE = re.compile(
    r"PROFILE_JSON:\s*(?:```(?:json)?\s*)?(\{.*\})", re.DOTALL
)

# Fallback: the model has been observed on production dropping the
# PROFILE_JSON: prefix entirely and just fencing the object instead —
# silently leaking the raw lead profile (product, pincode, documents,
# lead_quality...) straight into a WhatsApp reply, since the pattern above
# never matched without the literal prefix.
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*\})", re.DOTALL)

# Last-resort cleanup: the model has also been observed opening a code
# fence around ordinary reply text with no JSON inside, sometimes never
# closing it. WhatsApp does not render markdown fences, so raw ``` markers
# must never reach the customer even when nothing above matched.
_STRAY_FENCE_RE = re.compile(r"```(?:json)?")

LANGUAGE_SELECTED_TRIGGER = (
    "(The customer has selected their language. Greet briefly and ask the "
    "first qualification question.)"
)

FLOW_STEP_GUIDANCE: dict[str, str] = {
    "intro": "Greet briefly, then begin qualification.",
    "model_interest": (
        "Ask which TVS passenger model they want "
        "(King EV MAX, King Deluxe, or King Duramax Plus)."
    ),
    "campaign_awareness": (
        "Proactively mention the current campaign in 1-2 lines "
        "(CAMPAIGN section only)."
    ),
    "timeline": (
        "Ask when they want to buy or take delivery. Prefer a concrete date "
        "(DD/MM/YYYY) but do not force it. "
        "If they say something like 'in the next 10 days' / within ~10 days, ask for an exact date. "
        "If they say 'next month', accept it — the system will use the 7th of next month. "
        "If they give a farther range (e.g. in 20 days), accept it."
    ),
    "location": (
        "Ask for their 6-digit pincode to route to the nearest dealership. "
        "It may arrive across several messages. "
        "If they do not know the pincode, ask them to share WhatsApp current/live location only. "
        "Do NOT ask for city, area, town, or district. "
        "If they are out of town, still use pincode or live location for routing — do not ask city names. "
        "After a valid pincode or location is shared, the system attaches nearest-dealer details "
        "(name, address, phone, map) — do NOT invent dealer names, addresses, or phone numbers "
        "yourself. Never claim a dealership exists unless the system attached it."
    ),
    "feature_awareness": (
        "Ask if they already know the vehicle features. If not, give a SHORT accurate "
        "pitch from the KNOWLEDGE BASE only (max ~5 points)."
    ),
    "documents": (
        "Ask whether they have a driving LICENCE, a PERMIT, and a commercial BADGE."
    ),
    "wrap_up": (
        "Confirm what you captured, say the nearest dealership will contact them, "
        "and thank them."
    ),
}


@dataclass
class TurnInput:
    session_id: str
    language: str
    message: str | None = None
    channel: str = "web"
    source: str = "web"
    history: list[dict[str, str]] = field(default_factory=list)
    product_hint: str = ""
    confirm_crm_dealer: bool = False
    known_state: str = ""


@dataclass
class TurnOutput:
    reply_text: str
    captured: bool = False
    profile: dict[str, Any] | None = None
    citations: list[str] = field(default_factory=list)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass
class GenerateResult:
    text: str
    citations: list[str] = field(default_factory=list)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMPort(Protocol):
    def generate(self, *, system_instruction: str, contents: list[dict]) -> GenerateResult: ...


def build_contents(
    history: list[dict[str, str]],
    user_text: str,
    known_state: str = "",
) -> list[dict]:
    """Assemble the Gemini `contents` list for one turn.

    ``known_state`` is a compact snapshot of what has already been captured.
    It rides on the CURRENT user turn rather than the system instruction so
    the system prompt plus prior history stay byte-identical between turns —
    that prefix is what a context cache can reuse, and moving a per-turn
    string into it would invalidate the cache on every message.
    """
    contents: list[dict] = []
    first_user = next(
        (index for index, turn in enumerate(history) if turn.get("role") != "model"),
        len(history),
    )
    for turn in history[first_user:]:
        role = "model" if turn.get("role") == "model" else "user"
        contents.append({"role": role, "parts": [{"text": turn["text"]}]})
    final = f"{known_state}\n\n{user_text}" if known_state.strip() else user_text
    contents.append({"role": "user", "parts": [{"text": final}]})
    return contents


def capture_field_ids(config: dict[str, Any]) -> list[str]:
    return [f["id"] for f in config["capture_fields"]]


def configured_products(config: dict[str, Any]) -> list[str]:
    """Product names the admin has configured, in configured order."""
    documents = config.get("documents") if isinstance(config, dict) else None
    if not isinstance(documents, dict):
        return []
    return [name for name in documents if isinstance(name, str) and name.strip()]


def _product_menu(products: list[str] | None, conjunction: str = "") -> str:
    """The model list as the bot should say it: "A, B, or C"."""
    items = [p for p in (products or []) if isinstance(p, str) and p.strip()]
    if not items:
        return ""
    if len(items) == 1 or not conjunction:
        return ", ".join(items)
    return f"{', '.join(items[:-1])}, {conjunction} {items[-1]}"


def _step_guidance(
    step: str,
    *,
    product_hint: str = "",
    confirm_crm_dealer: bool = False,
    products: list[str] | None = None,
) -> str:
    # The model menu comes from configured documents so a vehicle added through
    # the admin API is actually offered. With nothing configured the built-in
    # wording stands, so an unreadable config cannot leave the bot mute.
    menu = _product_menu(products, "or")
    if step == "model_interest" and product_hint:
        ask = (
            f"If they say no or name another model, ask which of {menu} they want."
            if menu
            else "If they say no or name another model, ask which one they want."
        )
        example = (products or [product_hint])[0]
        return (
            f'Soft-ask naturally whether they are interested in the {product_hint} '
            f'(e.g. "Are you interested in the {example}?"). '
            "Do NOT mention CRM, records, or any system. " + ask
        )
    if step == "model_interest" and menu:
        return f"Ask which TVS passenger model they want ({menu})."
    if step == "location" and confirm_crm_dealer:
        return (
            "At the location step, briefly say you will share dealership details "
            "for them to confirm. Do NOT ask for a pincode yet — the system attaches "
            "the confirmation ask. If they already rejected that dealership, ask for "
            "their 6-digit pincode OR WhatsApp current/live location only. "
            "Do NOT ask for city, area, town, or district. "
            "Do not invent dealer names yourself."
        )
    return FLOW_STEP_GUIDANCE.get(step, step.replace("_", " "))


def _campaign_goal(campaign_text: str) -> str:
    """Only tell the bot to pitch a campaign when one is actually live."""
    return "make them aware of the active campaign, " if campaign_text.strip() else ""


def _campaign_shown_hint(campaign_text: str) -> str:
    """Naming a past scheme here is enough for the model to mention it, even
    with no CAMPAIGN section — so the example goes when the campaign does."""
    if campaign_text.strip():
        return 'the campaign NAME you mentioned (e.g. "Vaada"), or "" if none.'
    return 'always "" — no campaign is running, so do not mention one.'


def _campaign_block(campaign_text: str) -> str:
    """The CAMPAIGN section, or nothing at all when no campaign is live.

    Omitted rather than left empty: a bare "CAMPAIGN:" heading invites the
    model to invent an offer to put under it.
    """
    if not campaign_text.strip():
        return ""
    return f"\nCAMPAIGN:\n{campaign_text}\n"


def build_system_instruction(
    config: dict[str, Any],
    language: str,
    *,
    product_hint: str = "",
    confirm_crm_dealer: bool = False,
) -> str:
    """Assemble the qualification system prompt from admin config."""
    profile_keys = capture_field_ids(config)
    campaign = active_campaign_text(config)
    products = configured_products(config)
    flow_lines = []
    step_number = 0
    for step in config["flow_steps"]:
        # With no live campaign there is nothing to be aware of: keeping the
        # step would have the bot announce a scheme that has expired.
        if step == "campaign_awareness" and not campaign:
            continue
        step_number += 1
        guidance = _step_guidance(
            step,
            product_hint=product_hint,
            confirm_crm_dealer=confirm_crm_dealer,
            products=products,
        )
        flow_lines.append(f"   {step_number}. {guidance}")

    line_up = _product_menu(products) or "King EV MAX, King Deluxe, King Duramax Plus"
    return f"""You are {config["bot_name"]} for TVS PASSENGER three-wheelers \
({line_up}).

YOUR GOAL is NOT to answer every question in depth. Your goal is to QUALIFY and PROFILE \
the lead in a short, friendly chat, {_campaign_goal(campaign)}then hand \
them to the dealership.

RULES
1. Conduct the ENTIRE conversation in this language: {language}.
2. Qualify the lead by asking, ONE QUESTION AT A TIME, acknowledging each answer first:
   {chr(10).join(flow_lines)}
3. Keep every reply short and clear (chat / WhatsApp style). Ask only ONE thing per message.
4. If the customer asks a product question mid-flow (e.g. CNG vs petrol vs electric), \
answer in at most TWO sentences using ONLY the KNOWLEDGE BASE, then resume qualification.
5. Do NOT quote down payment, EMI, or on-road price — say the dealership shares exact \
figures. Give a range only if it appears in the KNOWLEDGE BASE or CAMPAIGN.
6. Never invent specifications. Use ONLY retrieved KNOWLEDGE BASE documents. If a detail \
is missing, say so and offer dealership follow-up.
7. Do not over-promise: a commercial BADGE is RTO-issued; the dealership GUIDES, it \
cannot complete it for the customer.
8. If the user goes off-topic (not about TVS passenger three-wheelers or related info), \
gently redirect back to qualification.
9. When you have enough info (or the user wants to stop), WRAP UP per step above.
10. Brochures/PDFs: you never attach files yourself — the system does. Say you are \
sending one ONLY when a system note in the message tells you it is being sent; then use \
present/future tense ("Sure, sending you the brochure"). Without that note, do NOT say you \
are sending, have sent, or will send any file — offer it instead ("Would you like me to \
send the brochure?") and wait for their answer. NEVER claim in past tense that a file was \
delivered, since you cannot see whether the send succeeded. Never say you are unable to \
send a brochure.

Never use markdown code fences (```) anywhere in your reply — WhatsApp shows the raw \
backtick characters to the customer, it does not render them. This applies to every reply, \
not only the wrap-up.

After the customer-facing wrap-up message ONLY (not before), output on a NEW final line a \
single JSON object prefixed exactly with `PROFILE_JSON:` with these keys, no code fence, no \
extra text after it:
{json.dumps(profile_keys)}
Field formats:
- timeline_bucket: one of immediate, <=30d, 30-90d, exploring.
- feature_awareness: "high" if they already knew the features, else "low".
- doc_license / doc_permit / doc_badge: "yes", "no", or "unknown".
- campaign_shown: {_campaign_shown_hint(campaign)}
- lead_quality: HOT (near-term timeline + location + >=2/3 docs yes), WARM, or COLD.
- disposition: one of interested, not_interested, already_purchased_tvs_motor, not_enquired. \
If they named any TVS passenger model they want, use interested. Ask briefly if unclear \
(e.g. already purchased / not interested / just browsing).
- blockers: short list of strings; next_step / notes: short strings.
- delivery_location: where they want the vehicle if out of town, else "".
- purchase_timeline: keep their words; include a DD/MM/YYYY when they gave one.
Do not output PROFILE_JSON until you are wrapping up.
{_campaign_block(campaign)}"""


def _extract_usage(response: Any) -> tuple[int | None, int | None]:
    """Pull (prompt, completion) token counts off a Gemini response.

    Never raise: usage is instrumentation, and a shape change in the SDK
    must not cost the customer their reply.
    """
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return None, None

    def count(*names: str) -> int | None:
        for name in names:
            value = getattr(usage, name, None)
            if isinstance(value, int):
                return value
        return None

    return (
        count("prompt_token_count", "input_token_count"),
        count("candidates_token_count", "output_token_count"),
    )


def parse_profile_json(text: str) -> tuple[str, dict[str, Any] | None]:
    """Strip any PROFILE_JSON payload from customer-visible text.

    Stripping always wins over parsing: once a JSON-shaped tail is
    detected (with or without the PROFILE_JSON: prefix, fenced or not),
    it is removed from what the customer sees even if it fails to parse —
    a malformed payload is still never customer-facing content. See the
    module-level regex comments for the two production-observed formats
    this now catches that a strict prefix-only match missed.
    """
    match = PROFILE_JSON_RE.search(text) or _FENCED_JSON_RE.search(text)
    if match is None:
        return _STRAY_FENCE_RE.sub("", text).strip(), None
    customer_text = _STRAY_FENCE_RE.sub("", text[: match.start()]).strip()
    try:
        profile = json.loads(match.group(1))
    except json.JSONDecodeError:
        return customer_text, None
    if not isinstance(profile, dict):
        return customer_text, None
    return customer_text, profile


class ConversationEngine:
    """Qualification-first conversation module — single seam for all channels."""

    def __init__(
        self,
        *,
        config_store: AdminConfigStore,
        llm: LLMPort,
        lead_writer: LeadWriter | None = None,
    ):
        self._config_store = config_store
        self._llm = llm
        self._lead_writer = lead_writer

    def handle_turn(self, turn: TurnInput) -> TurnOutput:
        config = self._config_store.get()
        user_text = (turn.message or "").strip()
        if not user_text:
            user_text = LANGUAGE_SELECTED_TRIGGER

        system = build_system_instruction(
            config,
            turn.language,
            product_hint=turn.product_hint,
            confirm_crm_dealer=turn.confirm_crm_dealer,
        )
        contents = build_contents(turn.history, user_text, turn.known_state)
        result = self._llm.generate(system_instruction=system, contents=contents)

        reply_text, profile = parse_profile_json(result.text or "")
        captured = False
        if profile and self._lead_writer is not None:
            self._lead_writer.append(
                channel=turn.channel,
                source=turn.source,
                session=turn.session_id,
                language=turn.language,
                profile=profile,
            )
            captured = True

        return TurnOutput(
            reply_text=reply_text,
            captured=captured,
            profile=profile,
            citations=list(result.citations),
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )


class GeminiLLMAdapter:
    """Production LLM adapter — Gemini with File Search grounding."""

    def __init__(self, model: str, file_search_store: str):
        self._model = model
        self._store = file_search_store

    def generate(self, *, system_instruction: str, contents: list[dict]) -> GenerateResult:
        from rag import _extract_citations, get_client

        client = get_client()
        resp = client.models.generate_content(
            model=self._model,
            contents=contents,
            config={
                "system_instruction": system_instruction,
                "tools": [{"file_search": {"file_search_store_names": [self._store]}}],
                "temperature": 0.3,
            },
        )
        text = resp.text or ""
        prompt_tokens, completion_tokens = _extract_usage(resp)
        return GenerateResult(
            text=text,
            citations=_extract_citations(resp),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )


def make_engine(
    *,
    config_store: AdminConfigStore | None = None,
    leads_path: str | None = None,
) -> ConversationEngine:
    """Build a production engine wired to admin config, Gemini, and CSV leads."""
    from pathlib import Path

    import config as app_config

    store = config_store or __import__("admin_config").get_store()
    writer = LeadWriter(Path(leads_path or app_config.LEADS_CSV_PATH), store)
    llm = GeminiLLMAdapter(app_config.MODEL, app_config.FILE_SEARCH_STORE)
    return ConversationEngine(config_store=store, llm=llm, lead_writer=writer)

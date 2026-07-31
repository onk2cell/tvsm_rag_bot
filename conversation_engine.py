"""Channel-agnostic qualification conversation engine."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from admin_config import AdminConfigStore
from leads import LeadWriter

PROFILE_JSON_RE = re.compile(r"PROFILE_JSON:\s*(\{.*\})", re.DOTALL)

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


@dataclass
class TurnOutput:
    reply_text: str
    captured: bool = False
    profile: dict[str, Any] | None = None
    citations: list[str] = field(default_factory=list)


@dataclass
class GenerateResult:
    text: str
    citations: list[str] = field(default_factory=list)


class LLMPort(Protocol):
    def generate(self, *, system_instruction: str, contents: list[dict]) -> GenerateResult: ...


def build_contents(history: list[dict[str, str]], user_text: str) -> list[dict]:
    contents: list[dict] = []
    first_user = next(
        (index for index, turn in enumerate(history) if turn.get("role") != "model"),
        len(history),
    )
    for turn in history[first_user:]:
        role = "model" if turn.get("role") == "model" else "user"
        contents.append({"role": role, "parts": [{"text": turn["text"]}]})
    contents.append({"role": "user", "parts": [{"text": user_text}]})
    return contents


def capture_field_ids(config: dict[str, Any]) -> list[str]:
    return [f["id"] for f in config["capture_fields"]]


def _step_guidance(
    step: str,
    *,
    product_hint: str = "",
    confirm_crm_dealer: bool = False,
) -> str:
    if step == "model_interest" and product_hint:
        return (
            f'Soft-ask naturally whether they are interested in the {product_hint} '
            '(e.g. "Are you interested in the King EV MAX?"). '
            "Do NOT mention CRM, records, or any system. "
            "If they say no or name another model, ask which of "
            "King EV MAX, King Deluxe, or King Duramax Plus they want."
        )
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


def build_system_instruction(
    config: dict[str, Any],
    language: str,
    *,
    product_hint: str = "",
    confirm_crm_dealer: bool = False,
) -> str:
    """Assemble the qualification system prompt from admin config."""
    profile_keys = capture_field_ids(config)
    flow_lines = []
    for i, step in enumerate(config["flow_steps"], start=1):
        guidance = _step_guidance(
            step,
            product_hint=product_hint,
            confirm_crm_dealer=confirm_crm_dealer,
        )
        flow_lines.append(f"   {i}. {guidance}")

    return f"""You are {config["bot_name"]} for TVS PASSENGER three-wheelers \
(King EV MAX, King Deluxe, King Duramax Plus).

YOUR GOAL is NOT to answer every question in depth. Your goal is to QUALIFY and PROFILE \
the lead in a short, friendly chat, make them aware of the active campaign, then hand \
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
10. Brochures/PDFs: you never attach files yourself, but the SYSTEM automatically sends \
the brochure/PDF when the customer explicitly asks for one, and offers to send it after \
you answer a product question. Never say you can't send a brochure, and never say the \
dealership will provide one — just answer naturally and let the system handle delivery.

After the customer-facing wrap-up message ONLY (not before), output on a NEW final line a \
single JSON object prefixed exactly with `PROFILE_JSON:` with these keys:
{json.dumps(profile_keys)}
Field formats:
- timeline_bucket: one of immediate, <=30d, 30-90d, exploring.
- feature_awareness: "high" if they already knew the features, else "low".
- doc_license / doc_permit / doc_badge: "yes", "no", or "unknown".
- campaign_shown: the campaign NAME you mentioned (e.g. "Vaada"), or "" if none.
- lead_quality: HOT (near-term timeline + location + >=2/3 docs yes), WARM, or COLD.
- disposition: one of interested, not_interested, already_purchased_tvs_motor, not_enquired. \
If they named any TVS passenger model they want, use interested. Ask briefly if unclear \
(e.g. already purchased / not interested / just browsing).
- blockers: short list of strings; next_step / notes: short strings.
- delivery_location: where they want the vehicle if out of town, else "".
- purchase_timeline: keep their words; include a DD/MM/YYYY when they gave one.
Do not output PROFILE_JSON until you are wrapping up.

CAMPAIGN:
{config["campaign_text"]}
"""


def parse_profile_json(text: str) -> tuple[str, dict[str, Any] | None]:
    """Strip PROFILE_JSON line from customer-visible text; return profile if valid."""
    match = PROFILE_JSON_RE.search(text)
    if not match:
        return text, None
    customer_text = text[: match.start()].strip()
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
        contents = build_contents(turn.history, user_text)
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
        return GenerateResult(text=text, citations=_extract_citations(resp))


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

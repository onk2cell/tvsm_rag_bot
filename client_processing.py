"""Channel orchestration for client-app messages."""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field, replace
from time import perf_counter
from typing import Callable, Protocol, TypeVar

import config
from bot.graph import (
    classify_brochure_offer_reply,
    classify_brochure_request,
    classify_dealer_confirm_reply,
    classify_language_switch,
    classify_location_reply,
    classify_product_info_request,
    classify_share_consent_reply,
    classify_still_interested_reply,
)
from client_flow_intent import FLOW_PGM, FLOW_VEHICLE, parse_flow_intent
from client_language import (
    LANGUAGE_PROMPT,
    SUPPORTED_LANGUAGES,
    detect_script_language,
    is_language_only_reply,
    parse_language_choice,
)
from conversation_engine import ConversationEngine, TurnInput
from dealers import (
    DealerDirectory,
    extract_coordinates,
    extract_pincode,
    format_dealer_confirm_ask,
    format_dealer_confirm_ask_from_dealer,
)
from dispose import (
    build_dispose_payload,
    normalize_product_name,
    resolve_purchase_date,
    wants_callback,
)
from client_media_assets import (
    brochure_product_from_text,
    doesnt_know_pincode,
    is_bare_dont_know,
    product_document_pack,
    share_location_caption,
    share_location_image_url,
    wants_product_brochure,
    wants_product_info,
    wants_support_documents,
)
from client_static_messages import (
    acknowledgement_fallback,
    brochure_offer_ask,
    brochure_which_product_ask,
    dealer_share_ask,
    flow_intent_ask,
    invalid_pincode_ask,
    invalid_pincode_location_fallback,
    location_need_pincode,
    location_no_dealer,
    location_thanks,
    location_unreadable,
    pgm_flow_intro,
    place_redirect_message,
    product_doc_caption,
    share_location_ask,
    still_interested_no_thanks,
    welcome_back_still_interested,
    wrap_up_dealer_confirm_intro,
)

log = logging.getLogger(__name__)

# Written into lead_profile when a returning customer declines the vehicle
# they enquired about last time. Matched exactly by _clear_welcome_back_decline
# so a genuine later decline is never mistaken for this one.
WELCOME_BACK_DECLINE_NOTE = "not interested on welcome-back"

_AFFIRMATIVE_RE = re.compile(
    r"(?i)^\s*(yes|y|yeah|yep|ok|okay|sure|haan|han|ha|ji|bilkul|"
    r"howdu|haudu|avunu|sari|aama?m|athe|"
    r"होय|हो|हाँ|हां|ठीक|सही|"
    r"ಹೌದು|ಸರಿ|అవును|సరే|ஆம்|ஆமாம்|சரி|അതെ|ശരി)\s*[!.।]*\s*$"
)
_NEGATIVE_RE = re.compile(
    r"(?i)^\s*(no|n|nope|nah|nahi|nahin|wrong|"
    r"illa|illai|ledu|beda|nako|naka|vendam|"
    r"नाही|नहीं|नही|नको|"
    r"ಇಲ್ಲ|ಬೇಡ|లేదు|వద్దు|இல்லை|வேண்டாம்|ഇല്ല|വേണ്ട)\s*[!.।]*\s*$"
)


def _is_affirmative(text: str | None) -> bool:
    return bool(_AFFIRMATIVE_RE.match((text or "").strip()))


def _is_negative(text: str | None) -> bool:
    return bool(_NEGATIVE_RE.match((text or "").strip()))


# Accepts for a pending "shall I send the brochure?" offer — includes
# Hinglish/Hindi send verbs that are NOT general yes (so dealer-confirm
# stays on _is_affirmative only).
_BROCHURE_OFFER_ACCEPT_RE = re.compile(
    r"(?i)^\s*"
    r"(?:(?:ha[an]?|haan|ji|yes|ok|okay|sure|हो|हाँ|हां|जी)\s*[,\-]?\s*)?"
    r"(?:"
    r"bhejo|bhej\s*do|bhej\s*dena|bhej\s*dijiye|bhej\s*diye|"
    r"send(?:\s+it)?|"
    r"send\s+(?:me\s+)?(?:the\s+)?(?:brochure|brocher|pdf)|"
    r"भेजो|भेज\s*दो|भेज\s*दीजिए|"
    r"पाठवा|पाठवून?\s*द्या|हो\s*भेजो|जी\s*भेजो"
    r")"
    r"\s*[!.।]*\s*$"
)


def _is_brochure_offer_accept(text: str | None) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if _is_affirmative(raw):
        return True
    if wants_product_brochure(raw):
        return True
    return bool(_BROCHURE_OFFER_ACCEPT_RE.match(raw))


_STILL_YES_FREE_RE = re.compile(
    r"(?i)("
    r"\b(yes|yeah|yep)\b|"
    r"(?<!not\s)(?<!not)\bsure\b|"
    r"\bstill\s+(want|interested|planning|looking)\b|"
    r"\b(want|planning)\s+to\s+(buy|purchase)\b|"
    r"\binterested\b|"
    r"हाँ|हां|होय|हो\b|"
    r"अजूनही|अभी\s*भी|खरीद"
    r")"
)
_STILL_NO_FREE_RE = re.compile(
    r"(?i)("
    r"\b(no|nope|nah)\b|"
    r"\bnot\s+interested\b|"
    r"\bdon'?t\s+want\b|"
    r"\bdo\s+not\s+want\b|"
    r"\bnot\s+(buying|purchase|purchasing)\b|"
    r"\b(cancel|drop)\b|"
    r"नाही|नहीं|नही|नको|"
    r"नहीं\s*चाहि|नको\s*आहे|खरेदी\s*नको"
    r")"
)


def _is_still_interested_yes(text: str | None) -> bool:
    """Yes for still-interested: 1, short yes, or free-text confirmation."""
    raw = (text or "").strip()
    if not raw:
        return False
    if re.fullmatch(r"1", raw):
        return True
    if _is_affirmative(raw):
        return True
    if _STILL_NO_FREE_RE.search(raw) and not re.search(r"(?i)\byes\b|हाँ|हां|होय", raw):
        return False
    return bool(_STILL_YES_FREE_RE.search(raw))


def _is_still_interested_no(text: str | None) -> bool:
    """No for still-interested: 2, short no, or free-text rejection."""
    raw = (text or "").strip()
    if not raw:
        return False
    if re.fullmatch(r"2", raw):
        return True
    if _is_negative(raw):
        return True
    if _STILL_YES_FREE_RE.search(raw) and not _STILL_NO_FREE_RE.search(raw):
        return False
    return bool(_STILL_NO_FREE_RE.search(raw))


def _crm_dealer_available(customer: Customer | None) -> bool:
    if customer is None:
        return False
    return bool(customer.dealership_id or customer.dealership_name)


def _product_hint_for(customer: Customer | None) -> str:
    if customer is None:
        return ""
    return normalize_product_name(customer.product_enquired)


def _is_unknown_crm_customer(customer: Customer | None) -> bool:
    """True when JAM customer lookup returned a stub (number not in CRM)."""
    if customer is None:
        return True
    if (customer.customer_id or "").startswith("unknown-"):
        return True
    name = (customer.name or "").strip().lower()
    return bool(re.fullmatch(r"customer\s+\d+", name))


def _history_is_language_menu_only(history: list[dict[str, str]]) -> bool:
    """True when the only bot turn so far was the language menu prompt."""
    if not history or len(history) > 2:
        return False
    model_turns = [t for t in history if t.get("role") == "model"]
    if len(model_turns) != 1:
        return False
    text = str(model_turns[0].get("text") or "")
    return "Which language do you prefer?" in text


@dataclass(frozen=True)
class Customer:
    customer_id: str
    name: str
    preferred_language: str = ""
    product_enquired: str = ""
    dealership_id: str = ""
    dealership_name: str = ""
    city: str = ""
    state: str = ""
    last_remark: str = ""
    last_status: str = ""


@dataclass
class ClientSession:
    conversation_id: str
    mobile: str
    customer: Customer | None = None
    history: list[dict[str, str]] = field(default_factory=list)
    unclear_document_count: int = 0
    pending_replies: dict[str, dict] = field(default_factory=dict)
    language: str = ""
    awaiting_language_selection: bool = False
    dealer_shared_for_pincode: str = ""
    last_dealer_code: str = ""
    dispose_sent: bool = False
    last_dispose_fingerprint: str = ""
    lead_profile: dict = field(default_factory=dict)
    brochures_sent: list[str] = field(default_factory=list)
    share_location_guide_sent: bool = False
    invalid_pincode_attempts: int = 0
    awaiting_dealer_confirm: bool = False
    dealer_confirm_deferred: bool = False
    crm_dealer_offered: bool = False
    dealer_confirmed: bool = False
    # Dealership details are never volunteered: we ask first, and only send
    # the name/address/phone/map card once the customer says yes.
    awaiting_dealer_share_consent: bool = False
    dealer_share_asked: bool = False
    dealer_share_declined: bool = False
    pending_dealer_share_code: str = ""
    # A dealer resolved from a pincode but not yet offered, because the
    # model's reply that turn asked its own question. Unlike the CRM-dealer
    # offer (which re-checks a durable CRM fact every turn), a pincode only
    # ever appears once in the message stream, so the resolved dealer must
    # be remembered here to retry on a later, question-free turn.
    pending_nearest_dealer_code: str = ""
    pending_nearest_dealer_pincode: str = ""
    callback_requested: bool = False
    welcome_back_sent: bool = False
    awaiting_still_interested: bool = False
    still_interested_asked: bool = False
    awaiting_brochure_offer: bool = False
    pending_brochure_product: str = ""
    # True after customer asked for a brochure/PDF but no product was known yet.
    awaiting_brochure_product_choice: bool = False
    qualification_started: bool = False
    # Vehicle-or-PGM routing, asked once right after the language menu.
    # ``flow`` is "" until answered, then FLOW_VEHICLE or FLOW_PGM; the PGM
    # value keeps every later turn out of the LLM qualification path.
    awaiting_flow_intent: bool = False
    flow: str = ""


@dataclass(frozen=True)
class DocumentRecognition:
    document_types: list[str]
    status: str


class ClientState(Protocol):
    def load_or_start(self, mobile: str) -> ClientSession: ...

    def save(self, session: ClientSession) -> None: ...


class CustomerDirectory(Protocol):
    def lookup(self, mobile: str) -> Customer: ...


class ReplySender(Protocol):
    def send(self, *, mobile: str, in_reply_to: str, text: str) -> None: ...

    def send_image(self, *, mobile: str, link: str, caption: str = "") -> None: ...

    def send_document(self, *, mobile: str, link: str, caption: str = "") -> None: ...


class DisposeClient(Protocol):
    def dispose(self, payload: dict) -> dict: ...


class ClientLeadStore(Protocol):
    def upsert_client_identity(self, **values) -> None: ...

    def add_documents(self, **values) -> None: ...


class MediaFetcher(Protocol):
    def fetch(
        self, url: str, mime_type: str | None = None, *, message_type: str | None = None
    ) -> tuple[bytes, str]: ...


class AudioTranscriber(Protocol):
    def transcribe(self, data: bytes, mime_type: str, language: str) -> str: ...


class DocumentRecognizer(Protocol):
    def recognize(self, data: bytes, mime_type: str) -> DocumentRecognition: ...


class ClientMessageProcessor:
    """Process one accepted event and deliver its customer-facing reply."""

    def __init__(
        self,
        *,
        state: ClientState,
        directory: CustomerDirectory,
        engine: ConversationEngine,
        reply_sender: ReplySender,
        lead_store: ClientLeadStore,
        interaction_store,
        media_fetcher: MediaFetcher,
        transcriber: AudioTranscriber,
        document_recognizer: DocumentRecognizer,
        dealer_directory: DealerDirectory | None = None,
        dispose_client: DisposeClient | None = None,
        sleep: Callable[[float], None] = time.sleep,
        retry_wait: float = 30,
    ):
        self._state = state
        self._directory = directory
        self._engine = engine
        self._reply_sender = reply_sender
        self._lead_store = lead_store
        self._interactions = interaction_store
        self._media_fetcher = media_fetcher
        self._transcriber = transcriber
        self._document_recognizer = document_recognizer
        self._dealer_directory = dealer_directory
        self._dispose_client = dispose_client
        self._sleep = sleep
        self._retry_wait = retry_wait

    def process(self, event: dict) -> None:
        started = perf_counter()
        session = self._state.load_or_start(event["mobile"])
        pending = session.pending_replies.get(event["message_id"])
        if pending:
            self._reply_and_record(
                event,
                session=session,
                language=pending["language"],
                user_message=pending["user_message"],
                reply=pending["reply"],
                started=started,
                citations=pending.get("citations"),
            )
            self._complete_turn(
                session,
                event["message_id"],
                pending["user_message"],
                pending["reply"],
            )
            return
        if session.customer is None:
            try:
                session.customer = self._directory.lookup(event["mobile"])
            except Exception as error:
                language = detect_script_language(event.get("content") or "")
                self._reply_and_record(
                    event,
                    session=session,
                    language=language,
                    user_message=event.get("content") or event["type"],
                    reply=(
                        "The customer service is temporarily unavailable. "
                        "Please try again shortly."
                    ),
                    started=started,
                    status="error",
                    error=str(error),
                    needs_review=True,
                )
                self._state.save(session)
                return

        customer = session.customer
        choice_event = event
        if session.awaiting_language_selection and event.get("type") == "audio":
            try:
                data, mime_type = self._media_fetcher.fetch(
                    event["media_url"],
                    event.get("mime_type"),
                    message_type="audio",
                )
                transcript = self._attempt(
                    lambda: self._transcriber.transcribe(data, mime_type, "English")
                )
                choice_event = {**event, "type": "text", "content": transcript or ""}
            except Exception as error:
                self._reply_and_record(
                    event,
                    session=session,
                    language="English",
                    user_message=event.get("content") or event["type"],
                    reply="I could not hear that audio. Please reply with 1–7.",
                    started=started,
                    status="error",
                    error=str(error),
                )
                self._state.save(session)
                return

        was_awaiting_language = session.awaiting_language_selection
        language = self._resolve_language(session, choice_event)
        if language is None:
            # Language menu sent; wait for the customer's choice.
            self._lead_store.upsert_client_identity(
                session=session.conversation_id,
                mobile=session.mobile,
                customer_id=customer.customer_id,
                customer_name=customer.name,
                language="",
                message_id=event["message_id"],
                client_timestamp=event["timestamp"],
                received_at=event.get("received_at", ""),
            )
            self._reply_and_record(
                event,
                session=session,
                language="English",
                user_message=choice_event.get("content") or event.get("content") or event["type"],
                reply=LANGUAGE_PROMPT,
                started=started,
            )
            self._state.save(session)
            return

        # Persist the chosen language so dispose remarks carry it into CRM
        # for the next visit (not state/region defaults).
        session.lead_profile["preferred_language"] = language
        if session.customer is not None:
            session.customer = Customer(
                customer_id=session.customer.customer_id,
                name=session.customer.name,
                preferred_language=language,
                product_enquired=session.customer.product_enquired,
                dealership_id=session.customer.dealership_id,
                dealership_name=session.customer.dealership_name,
                city=session.customer.city,
                state=session.customer.state,
                last_remark=session.customer.last_remark,
                last_status=session.customer.last_status,
            )

        self._lead_store.upsert_client_identity(
            session=session.conversation_id,
            mobile=session.mobile,
            customer_id=customer.customer_id,
            customer_name=customer.name,
            language=language,
            message_id=event["message_id"],
            client_timestamp=event["timestamp"],
            received_at=event.get("received_at", ""),
        )

        choice_text = str(
            choice_event.get("content") or event.get("content") or event["type"]
        )
        if was_awaiting_language:
            # The language was just chosen: before anything else, ask whether
            # they want the vehicle flow or the nearest PGM. Nothing the
            # customer typed alongside the choice reaches the LLM — the same
            # trade the language menu itself makes.
            self._ask_flow_intent(
                event,
                session=session,
                language=language,
                user_message=choice_text,
                started=started,
            )
            return

        if session.flow == FLOW_PGM:
            self._handle_pgm_turn(
                event,
                session=session,
                language=language,
                started=started,
            )
            return

        # A location pin while the routing ask is pending is not an answer to
        # it; let it fall through to the re-ask instead of the dealer lookup.
        if event.get("type") == "location" and not session.awaiting_flow_intent:
            self._handle_location_event(
                event,
                session=session,
                language=language,
                started=started,
            )
            return

        try:
            message, immediate_reply = self._message_for_event(
                event,
                session=session,
                language=language,
            )
        except Exception as error:
            self._reply_and_record(
                event,
                session=session,
                language=language,
                user_message=event.get("content") or event["type"],
                reply="I could not open that file. Please resend it.",
                started=started,
                status="error",
                error=str(error),
            )
            self._state.save(session)
            return

        # A voice note is only transcribed above, so the language check has
        # to run again here — otherwise "please speak in English" spoken
        # aloud is never applied and the next reply reverts (bug 010802).
        if (
            event.get("type") == "audio"
            and immediate_reply is None
            and not session.awaiting_flow_intent
        ):
            language = self._maybe_switch_language(session, message) or language

        if session.awaiting_flow_intent and immediate_reply is None:
            routed = self._apply_flow_intent(
                event,
                session=session,
                language=language,
                user_message=message,
                started=started,
            )
            if routed is None:
                return
            message = routed

        # After a pure language-menu reply, start qualification instead of
        # treating "2" / "Hindi" as the customer's product message. In
        # production the routing ask now sits between the two and seeds this
        # message itself (session.flow is set); this remains for sessions that
        # were never routed.
        if (
            is_language_only_reply(choice_text, language)
            and not session.history
            and not session.flow
        ):
            message = self._qualification_start_message(customer, language)

        # Returning customer after idle expiry / fresh session: mandatory
        # name+product still-interested Yes/No in the language just chosen.
        still_prompt = self._maybe_offer_still_interested(session, language=language)
        if still_prompt is not None:
            user_text = choice_text
            self._reply_and_record(
                event,
                session=session,
                language=language,
                user_message=user_text,
                reply=still_prompt,
                started=started,
            )
            self._complete_turn(session, event["message_id"], user_text, still_prompt)
            return

        still_handled = self._apply_still_interested(
            session,
            user_message=str(event.get("content") or "").strip(),
            language=language,
        )
        if still_handled is not None:
            enriched, immediate = still_handled
            if immediate is not None:
                self._reply_and_record(
                    event,
                    session=session,
                    language=language,
                    user_message=str(event.get("content") or ""),
                    reply=immediate,
                    started=started,
                )
                self._complete_turn(
                    session,
                    event["message_id"],
                    str(event.get("content") or ""),
                    immediate,
                )
                return
            message = enriched

        raw_place_text = str(event.get("content") or "").strip()
        if event.get("type") == "text" and raw_place_text:
            # One classification per turn, shared by the pincode and
            # place-name handlers below.
            location_kind = self._classify_location(session, raw_place_text)
            pin_reply = self._maybe_handle_invalid_pincode(
                session,
                user_message=raw_place_text,
                language=language,
                classification=location_kind,
            )
            if pin_reply is not None:
                self._reply_and_record(
                    event,
                    session=session,
                    language=language,
                    user_message=raw_place_text,
                    reply=pin_reply,
                    started=started,
                )
                self._complete_turn(
                    session, event["message_id"], raw_place_text, pin_reply
                )
                return

            no_pincode_yet = not (
                session.dealer_shared_for_pincode
                or str(session.lead_profile.get("pincode") or "").strip()
            )
            if (
                (
                    doesnt_know_pincode(raw_place_text)
                    or (is_bare_dont_know(raw_place_text) and no_pincode_yet)
                )
                and not session.dealer_confirmed
                and not session.awaiting_dealer_confirm
                and not extract_pincode(raw_place_text)
            ):
                # One image (no caption) + one static text — avoid LLM duplicate.
                self._send_share_location_guide(session, with_caption=False)
                location_reply = share_location_ask(
                    language or self._session_language(session)
                )
                self._reply_and_record(
                    event,
                    session=session,
                    language=language,
                    user_message=raw_place_text,
                    reply=location_reply,
                    started=started,
                )
                self._complete_turn(
                    session, event["message_id"], raw_place_text, location_reply
                )
                return

            place_reply = self._maybe_handle_place_name(
                session,
                user_message=raw_place_text,
                language=language,
                classification=location_kind,
            )
            if place_reply is not None:
                self._reply_and_record(
                    event,
                    session=session,
                    language=language,
                    user_message=raw_place_text,
                    reply=place_reply,
                    started=started,
                )
                self._complete_turn(
                    session, event["message_id"], raw_place_text, place_reply
                )
                return

        raw_user_text = (message or "").strip()
        if extract_pincode(raw_user_text or raw_place_text):
            session.invalid_pincode_attempts = 0
        message = self._maybe_welcome_back(session, message)

        if immediate_reply is not None:
            self._reply_and_record(
                event,
                session=session,
                language=language,
                user_message=message or event.get("content") or event["type"],
                reply=immediate_reply,
                started=started,
                status=(
                    "error"
                    if session.unclear_document_count >= 2
                    else "ok"
                ),
                error=(
                    "Repeated unclear document"
                    if session.unclear_document_count >= 2
                    else ""
                ),
                needs_review=session.unclear_document_count >= 2,
            )
            self._state.save(session)
            return

        share_consent = self._apply_dealer_share_consent(session, message)
        if share_consent is not None:
            message, immediate_share = share_consent
            if immediate_share is not None:
                self._reply_and_record(
                    event,
                    session=session,
                    language=language,
                    user_message=message,
                    reply=immediate_share,
                    started=started,
                )
                self._complete_turn(
                    session, event["message_id"], message, immediate_share
                )
                return

        confirm_immediate = self._apply_dealer_confirm(session, message)
        if confirm_immediate is not None:
            message, immediate_confirm = confirm_immediate
            if immediate_confirm is not None:
                self._reply_and_record(
                    event,
                    session=session,
                    language=language,
                    user_message=message,
                    reply=immediate_confirm,
                    started=started,
                )
                self._complete_turn(
                    session, event["message_id"], message, immediate_confirm
                )
                return

        brochure_offer_applied = self._apply_brochure_offer(session, message)
        if brochure_offer_applied is not None:
            message, _ = brochure_offer_applied

        if wants_callback(message):
            session.callback_requested = True
            message = (
                f"{message}\n\n(Customer asked to be called back. "
                "Reply briefly that the dealership will call them soon, "
                "thank them, and wrap up. Do not ask more qualification questions.)"
            )

        message, brochure_offer_product = self._prepare_brochure_info_context(
            session, message, user_message=raw_user_text
        )
        brochure_requested = classify_brochure_request(raw_user_text)
        message, brochure_needs_product = self._prepare_brochure_request_context(
            session,
            message,
            user_message=raw_user_text,
            requested=brochure_requested,
        )

        confirm_was_pending = session.awaiting_dealer_confirm
        product_hint = _product_hint_for(customer)
        confirm_crm = (
            _crm_dealer_available(customer)
            and not session.dealer_confirmed
            and not session.crm_dealer_offered
        )
        is_first_qualification_reply = not session.qualification_started
        # _maybe_offer_crm_dealer (post-reply) will attach a mandatory
        # dealer-confirm question under these same conditions, except it
        # additionally defers on a bare first reply (see its docstring —
        # that keeps natural flow order on turn 1). Whenever it WILL attach
        # this turn, tell the LLM up front not to ask its own question —
        # otherwise its reply plus the deterministic dealer-confirm ask
        # stack two questions in one message, regardless of which
        # qualification step the LLM happens to be on.
        #
        # The same applies to the pincode path: _attach_nearest_dealer
        # appends a card with its own Yes/No question. Resolve that dealer
        # up front so the guard covers it too — without this the customer
        # got the campaign blurb, a purchase-date question AND the dealer
        # card in one bubble (bug 010801).
        crm_card_will_attach = confirm_crm and (
            not is_first_qualification_reply or bool(extract_pincode(raw_user_text))
        )
        # _maybe_offer_crm_dealer runs first and sets awaiting_dealer_confirm,
        # which short-circuits _attach_nearest_dealer — so when the CRM card
        # wins, skip the nearest lookup entirely rather than spending a
        # geocode on a dealer that will never be attached.
        nearest_dealer = (
            None
            if crm_card_will_attach
            else self._pending_nearest_dealer(session, raw_user_text)
        )
        dealer_card_will_attach = crm_card_will_attach or nearest_dealer is not None
        if dealer_card_will_attach:
            message = (
                f"{message}\n\n(Do NOT ask any question of your own in this "
                "reply — just briefly acknowledge/transition. The system "
                "will attach a mandatory dealership confirmation question "
                "after your reply.)"
            )
        # Any turn that reaches the qualification engine after a
        # welcome-back decline is the customer re-engaging.
        self._clear_welcome_back_decline(session)
        turn = TurnInput(
            session_id=session.conversation_id,
            language=language,
            message=message,
            channel="client_app",
            source="client_app",
            history=list(session.history),
            product_hint=product_hint,
            confirm_crm_dealer=confirm_crm,
            known_state=self._known_state_block(session),
        )
        try:
            output = self._attempt(lambda: self._engine.handle_turn(turn))
            session.qualification_started = True
        except Exception as error:
            self._reply_and_record(
                event,
                session=session,
                language=language,
                user_message=message,
                reply=(
                    "The assistant is temporarily unavailable. "
                    "Please try again shortly."
                ),
                started=started,
                status="error",
                error=str(error),
                needs_review=True,
            )
            self._state.save(session)
            return
        output = self._retry_empty_reply(turn, output)
        reply_text = self._maybe_offer_crm_dealer(
            session,
            user_message=raw_user_text,
            reply=output.reply_text,
            is_first_reply=is_first_qualification_reply,
        )
        reply_text = self._attach_nearest_dealer(
            session,
            user_message=message,
            reply=reply_text,
            dealer=nearest_dealer,
        )
        reply_text = self._maybe_offer_brochure(
            session,
            reply=reply_text,
            product=brochure_offer_product,
        )
        if brochure_needs_product:
            ask = brochure_which_product_ask(self._session_language(session))
            reply_text = "\n\n".join(
                part for part in (reply_text.rstrip(), ask) if part
            )
        if (
            output.profile is not None
            and session.dealer_confirm_deferred
            and not session.dealer_confirmed
        ):
            session.dealer_confirm_deferred = False
            session.awaiting_dealer_confirm = True
            intro = wrap_up_dealer_confirm_intro(self._session_language(session))
            nudge = self._dealer_confirm_ask_for_session(session)
            reply_text = "\n\n".join(
                part for part in (reply_text.rstrip(), intro, nudge) if part
            )
        history_reply = reply_text
        if confirm_was_pending and session.awaiting_dealer_confirm:
            # Re-attach the pending dealer card after answering the customer,
            # unless the model already repeated the dealership itself. Keep the
            # mechanical card out of history so the model does not imitate it.
            dealer_name = self._pending_dealer_name(session)
            if not (dealer_name and dealer_name.lower() in reply_text.lower()):
                ask = self._dealer_confirm_ask_for_session(session)
                reply_text = "\n\n".join(
                    part for part in (reply_text.rstrip(), ask) if part
                )
        self._maybe_send_product_brochure(
            session,
            user_message=raw_user_text,
            profile=output.profile,
            requested=brochure_requested,
        )
        self._capture_purchase_date(session, user_message=raw_user_text)
        self._capture_lead_name(session, user_message=raw_user_text)
        self._capture_pincode(session, user_message=raw_user_text)
        self._maybe_dispose(session, profile=output.profile)
        session.pending_replies[event["message_id"]] = {
            "language": language,
            "user_message": message,
            "reply": reply_text,
            "citations": output.citations,
        }
        self._state.save(session)
        self._reply_and_record(
            event,
            session=session,
            language=language,
            user_message=message,
            reply=reply_text,
            started=started,
            citations=output.citations,
            prompt_tokens=output.prompt_tokens,
            completion_tokens=output.completion_tokens,
        )
        self._complete_turn(
            session,
            event["message_id"],
            message,
            history_reply,
        )

    def _resolve_brochure_product(
        self,
        session: ClientSession,
        user_message: str,
        profile: dict | None = None,
    ) -> tuple[str, tuple[str, ...]]:
        """Resolve which product a brochure request/offer refers to.

        The triggering message often doesn't repeat the product name ("send
        me the brochure for this") — product_interest is only captured in
        lead_profile at LLM wrap-up, so fall back to scanning recent
        conversation turns (most recent first) for a named model.

        Deliberately does NOT persist what it resolves. Seeding
        lead_profile here looks like it would help a new customer (no CRM
        product_enquired to fall back on), but history already covers that
        case — and because the lead_profile hint outranks history below, a
        sticky value shadows a later product switch: customer says King EV
        MAX, switches to King Deluxe, then asks for "the brochure" and gets
        the EV MAX one.
        """
        history_hints = tuple(
            str(turn.get("text") or "")
            for turn in reversed(session.history)
            if turn.get("role") != "model"
        )
        hints = (
            user_message,
            str((profile or {}).get("product_interest") or ""),
            str(session.lead_profile.get("product_interest") or ""),
            _product_hint_for(session.customer),
            *history_hints,
        )
        return brochure_product_from_text(*hints), hints

    def _send_brochure_pack(
        self,
        session: ClientSession,
        product: str,
        hints: tuple[str, ...] = (),
        *,
        include_support_docs: bool = False,
    ) -> bool:
        """Send the brochure for `product` — plus the warranty/PMS PDFs only
        when they asked about those. Returns True if anything was sent."""
        if not product or product in session.brochures_sent:
            return False
        pack = product_document_pack(
            product, *hints, include_support_docs=include_support_docs
        )
        if not pack:
            return False
        language = self._session_language(session)
        sent_any = False
        for link, kind in pack:
            try:
                self._reply_sender.send_document(
                    mobile=session.mobile,
                    link=link,
                    caption=product_doc_caption(product, kind, language),
                )
                sent_any = True
            except Exception:
                log.exception(
                    "product doc send failed mobile=%s product=%s kind=%s",
                    session.mobile,
                    product,
                    kind,
                )
        if sent_any:
            session.brochures_sent.append(product)
            session.lead_profile.setdefault("product_interest", product)
        return sent_any

    def _prepare_brochure_request_context(
        self,
        session: ClientSession,
        message: str,
        *,
        user_message: str,
        requested: bool,
    ) -> tuple[str, bool]:
        """Steer the LLM when the customer asks for a brochure/PDF.

        Returns ``(message, needs_product_ask)``. When no product is known yet,
        the caller should append a deterministic which-model ask after the reply.
        ``requested`` is precomputed once per turn (regex + optional LLM).
        """
        if not requested:
            return message, False
        product, hints = self._resolve_brochure_product(session, user_message)
        if product:
            # Decide the send BEFORE the prompt is built, so the reply can
            # never promise a document the send path will skip. Getting this
            # backwards is what made the bot repeat "I'm sending you the
            # brochure" without ever sending one.
            if product in session.brochures_sent:
                return (
                    f"{message}\n\n(The {product} brochure was ALREADY sent "
                    "earlier in this chat and will NOT be sent again. Do NOT "
                    "say you are sending it. Tell them to check the PDF sent "
                    "earlier in this chat, then continue with the next "
                    "qualification step.)"
                ), False
            if not product_document_pack(product, *hints):
                return (
                    f"{message}\n\n(No brochure file is available for "
                    f"{product}. Do NOT say you are sending one. Say the "
                    "dealership will share it, then continue.)"
                ), False
            return (
                f"{message}\n\n(Customer asked for a brochure/PDF. The system "
                "will send the document(s) separately after your reply. "
                "Acknowledge briefly that you are sending it. "
                "Do not invent download links.)"
            ), False
        session.awaiting_brochure_product_choice = True
        return (
            f"{message}\n\n(Customer asked for a brochure/PDF but no product "
            "is known yet. Do NOT say you are sending or have sent a brochure. "
            "Do NOT ask any other question — the system will ask which model.)"
        ), True

    def _maybe_send_product_brochure(
        self,
        session: ClientSession,
        *,
        user_message: str,
        profile: dict | None = None,
        requested: bool = False,
    ) -> None:
        """Send the brochure once the customer explicitly asks for the
        document itself (e.g. "send brochure", "share the pdf",
        "share catalog"). The warranty/PMS PDFs ride along only when they
        asked about warranty or servicing — one request, one file otherwise.

        We never push PDFs/images just because a model name was mentioned,
        and a general info question ("tell me about X") gets an offer
        instead of an automatic send — see _prepare_brochure_info_context /
        _maybe_offer_brochure / _apply_brochure_offer.

        If they asked earlier without naming a product, naming a model on a
        later turn completes the pending request and sends the pack.

        Detection: regex fast path, then soft-signal + LLM so any-language
        phrasing still works (``requested`` is precomputed once per turn).
        """
        product, hints = self._resolve_brochure_product(
            session, user_message, profile
        )
        support = wants_support_documents(user_message)
        asked = requested
        if asked:
            if not product:
                session.awaiting_brochure_product_choice = True
                return
            if self._send_brochure_pack(
                session, product, hints, include_support_docs=support
            ):
                session.awaiting_brochure_product_choice = False
            return
        if session.awaiting_brochure_product_choice and product:
            if self._send_brochure_pack(
                session, product, hints, include_support_docs=support
            ):
                session.awaiting_brochure_product_choice = False

    def _prepare_brochure_info_context(
        self,
        session: ClientSession,
        message: str,
        *,
        user_message: str,
    ) -> tuple[str, str]:
        """If `user_message` is a general product-info question (not a
        literal document request) and we can resolve an unsent product, tag
        `message` so the LLM answers ONLY the question — no extra question
        of its own — and return the product to offer the brochure for
        afterward (post-reply, deterministically, so the offer is the one
        question this turn, not a second one stacked on the LLM's own).
        """
        if session.awaiting_brochure_offer:
            return message, ""
        if wants_product_brochure(user_message) or not classify_product_info_request(
            user_message
        ):
            return message, ""
        product, _ = self._resolve_brochure_product(session, user_message)
        if not product or product in session.brochures_sent:
            return message, ""
        enriched = (
            f"{message}\n\n(Answer this product question in at most TWO "
            "sentences using ONLY the KNOWLEDGE BASE. Do NOT ask a "
            "qualification question or anything else in this reply — the "
            "system will separately ask if they want the brochure.)"
        )
        return enriched, product

    def _maybe_offer_brochure(
        self,
        session: ClientSession,
        *,
        reply: str,
        product: str,
    ) -> str:
        """Append a deterministic "want the brochure too?" ask after an
        info-question reply, and arm _apply_brochure_offer for the next turn."""
        if not product:
            return reply
        session.awaiting_brochure_offer = True
        session.pending_brochure_product = product
        ask = brochure_offer_ask(self._session_language(session))
        return "\n\n".join(part for part in (reply.rstrip(), ask) if part)

    def _apply_brochure_offer(
        self,
        session: ClientSession,
        message: str,
    ) -> tuple[str, str | None] | None:
        """Handle the reply to a pending brochure offer. Always hands off
        to the chat LLM (never an immediate canned reply) — a "no" or an
        unrelated reply just continues qualification normally.

        Accept/decline uses regex fast path + LLM classifier so customers
        can reply in any language/phrasing.
        """
        if not session.awaiting_brochure_offer:
            return None
        session.awaiting_brochure_offer = False
        product = session.pending_brochure_product
        session.pending_brochure_product = ""
        decision = classify_brochure_offer_reply(message)
        if decision == "yes":
            _, hints = self._resolve_brochure_product(session, message)
            sent = self._send_brochure_pack(
                session,
                product,
                hints,
                include_support_docs=wants_support_documents(message),
            )
            if sent:
                enriched = (
                    f"{message}\n\n(Brochure for {product} has been sent. "
                    "Acknowledge briefly, then continue with the next "
                    "qualification step.)"
                )
                return enriched, None
            return message, None
        if decision == "no":
            enriched = (
                f"{message}\n\n(Customer did not want the brochure sent. "
                "Acknowledge briefly, then continue with the next "
                "qualification step.)"
            )
            return enriched, None
        return message, None

    # --- vehicle-or-PGM routing -------------------------------------------
    #
    # Asked once, on the turn the language is chosen, before still-interested
    # or any LLM turn. Like the language menu, the ask and its re-asks are
    # recorded as interactions but kept out of session.history: the model
    # never needs to see menu exchanges, and _maybe_offer_still_interested
    # relies on an empty history to fire on the first real turn.

    def _ask_flow_intent(
        self,
        event: dict,
        *,
        session: ClientSession,
        language: str,
        user_message: str,
        started: float,
    ) -> None:
        session.awaiting_flow_intent = True
        session.flow = ""
        self._reply_and_record(
            event,
            session=session,
            language=language,
            user_message=user_message,
            reply=flow_intent_ask(language or self._session_language(session)),
            started=started,
        )
        self._state.save(session)

    def _apply_flow_intent(
        self,
        event: dict,
        *,
        session: ClientSession,
        language: str,
        user_message: str,
        started: float,
    ) -> str | None:
        """Route the reply to the vehicle-or-PGM ask.

        Returns the message to seed the vehicle flow with, or None when this
        turn is finished here: the customer chose the PGM flow (intro sent,
        session.flow set) or gave no clear choice (re-asked). Deterministic
        by design — an unclear reply is re-asked, not classified.
        """
        lang = language or self._session_language(session)
        intent = parse_flow_intent(user_message)
        if intent == FLOW_VEHICLE:
            session.awaiting_flow_intent = False
            session.flow = FLOW_VEHICLE
            return self._qualification_start_message(session.customer, lang)
        if intent == FLOW_PGM:
            session.awaiting_flow_intent = False
            session.flow = FLOW_PGM
            # One image (no caption) + one text, as the vehicle flow does.
            self._send_share_location_guide(session, with_caption=False)
            reply = f"{pgm_flow_intro(lang)}\n\n{share_location_ask(lang)}"
            self._reply_and_record(
                event,
                session=session,
                language=lang,
                user_message=user_message,
                reply=reply,
                started=started,
            )
            self._complete_turn(session, event["message_id"], user_message, reply)
            return None
        self._ask_flow_intent(
            event,
            session=session,
            language=lang,
            user_message=user_message,
            started=started,
        )
        return None

    def _qualification_start_message(
        self, customer: Customer | None, language: str
    ) -> str:
        """The first engine message once the customer is in the vehicle flow."""
        if _is_unknown_crm_customer(customer):
            return (
                f"(The customer selected {language}. Their number is NOT in CRM yet. "
                "Greet briefly, ask their name first (we need it for CRM customername), "
                "then ask the first qualification question. Capture the name in lead_name.)"
            )
        return (
            f"(The customer selected {language}. "
            "Greet briefly and ask the first qualification question.)"
        )

    def _handle_pgm_turn(
        self,
        event: dict,
        *,
        session: ClientSession,
        language: str,
        started: float,
    ) -> None:
        """One turn of the locate-nearest-PGM flow. Deterministic — the LLM
        qualification path is never entered while session.flow is PGM, so a
        customer who said "not the vehicle" is not asked vehicle questions.

        Only the entry is settled so far: ask where the customer is. A typed
        pincode is kept in lead_profile["pincode"]; a shared pin is
        acknowledged, its coordinates left for the lookup to consume. What a
        PGM is, how the nearest one is found and what is sent back are a
        separate requirement and slot in after the location capture below.
        """
        lang = language or self._session_language(session)
        text = str(event.get("content") or "").strip()
        if event.get("type") == "location":
            user_label = "shared location"
            located = extract_coordinates(event) is not None
        else:
            user_label = text or str(event["type"])
            self._capture_pincode(session, user_message=text)
            located = bool(extract_pincode(text))
        reply = location_thanks(lang) if located else share_location_ask(lang)
        self._reply_and_record(
            event,
            session=session,
            language=lang,
            user_message=user_label,
            reply=reply,
            started=started,
        )
        self._complete_turn(session, event["message_id"], user_label, reply)

    def _returning_product(self, customer: Customer | None) -> str:
        """Best-known prior product for the still-interested ask."""
        product = _product_hint_for(customer)
        if product:
            return product
        if customer is None:
            return ""
        return normalize_product_name(customer.last_remark or "")

    def _display_customer_name(self, customer: Customer | None) -> str:
        if customer is None or _is_unknown_crm_customer(customer):
            return ""
        name = (customer.name or "").strip()
        if not name or re.fullmatch(r"(?i)customer\s+\d+", name):
            return ""
        return name

    def _is_returning_customer(self, customer: Customer | None) -> bool:
        if customer is None or _is_unknown_crm_customer(customer):
            return False
        remark = (customer.last_remark or "").strip()
        status = (customer.last_status or "").strip()
        empty_status = status.lower() in {"", "no response", "null", "none"}
        product = self._returning_product(customer)
        dealership = (customer.dealership_name or "").strip()
        return bool(remark or (status and not empty_status) or product or dealership)

    def _maybe_offer_still_interested(
        self,
        session: ClientSession,
        *,
        language: str,
    ) -> str | None:
        """Send mandatory still-interested Yes/No for returning customers."""
        if session.still_interested_asked or session.awaiting_still_interested:
            return None
        customer = session.customer
        if not self._is_returning_customer(customer):
            return None
        product = self._returning_product(customer)
        if not product:
            return None
        # Only on a fresh conversation (no qualification history yet), or right
        # after the language menu which is the first bot turn.
        if session.history and not _history_is_language_menu_only(session.history):
            return None
        session.awaiting_still_interested = True
        session.still_interested_asked = True
        session.welcome_back_sent = True
        if product:
            session.lead_profile.setdefault("product_interest", product)
        return welcome_back_still_interested(
            name=self._display_customer_name(customer),
            product=product,
            language=language or self._session_language(session),
        )

    def _apply_still_interested(
        self,
        session: ClientSession,
        *,
        user_message: str,
        language: str,
    ) -> tuple[str, str | None] | None:
        """Handle the reply while awaiting the still-interested confirm.

        A clear Yes/No is resolved by regex without any LLM call. Anything
        else (undecided, asking about another product, an unrelated
        question, off-topic — including cases where a customer's decline
        doesn't match the regex) is classified by
        bot.graph.classify_still_interested_reply: a confident decline
        still closes the lead, but everything else hands off to normal
        qualification instead of re-asking the same static question
        forever — the qualification engine already knows how to handle a
        product switch, a mid-flow question, or an off-topic message.
        """
        if not session.awaiting_still_interested:
            return None
        lang = language or self._session_language(session)
        product = (
            str(session.lead_profile.get("product_interest") or "").strip()
            or self._returning_product(session.customer)
            or "TVS King"
        )
        if not classify_still_interested_reply(user_message):
            session.awaiting_still_interested = False
            if _is_still_interested_yes(user_message):
                note = f"Customer confirmed they are still interested in {product}."
            else:
                note = (
                    f"The customer's continued interest in {product} is not "
                    "confirmed, but they did not decline either. Do not claim "
                    "they confirmed interest."
                )
            enriched = (
                f"{user_message}\n\n({note} Address anything they asked/said, in "
                f"{lang}, then continue toward the next qualification step. Do "
                "not re-ask whether they are still interested.)"
            )
            return enriched, None
        session.awaiting_still_interested = False
        session.lead_profile["disposition"] = "not_interested"
        session.lead_profile["notes"] = WELCOME_BACK_DECLINE_NOTE
        session.lead_profile.setdefault("product_interest", product)
        self._maybe_dispose(session, profile=session.lead_profile)
        # The reply now offers the rest of the range; if they take it up,
        # _clear_welcome_back_decline reopens the lead on the next turn.
        return user_message, still_interested_no_thanks(lang)

    def _clear_welcome_back_decline(self, session: ClientSession) -> None:
        """Reopen a lead that declined on welcome-back and then kept talking.

        The decline wrote disposition/notes straight into lead_profile and
        nothing ever removed them. Dispose needs a pincode, which usually
        arrives several turns later — by which time the customer had picked a
        different model, yet CRM still received status not_interested and,
        once they qualified, an "interested" record whose remark read
        "notes: not interested on welcome-back".
        """
        profile = session.lead_profile
        if profile.get("disposition") != "not_interested":
            return
        if str(profile.get("notes") or "") != WELCOME_BACK_DECLINE_NOTE:
            return  # a genuine later decline — leave it alone
        profile.pop("disposition", None)
        profile.pop("notes", None)

    def _maybe_welcome_back(self, session: ClientSession, message: str) -> str:
        """Seed the first turn with CRM context when still-interested ask was skipped.

        Returning customers with a known product already got the mandatory static
        Yes/No ask — do not also send an LLM welcome-back.
        """
        if session.history or session.welcome_back_sent:
            return message
        customer = session.customer
        if customer is None:
            return message
        # Product-known returning customers use the static still-interested path.
        if self._is_returning_customer(customer) and self._returning_product(customer):
            return message
        remark = (customer.last_remark or "").strip()
        status = (customer.last_status or "").strip()
        preferred = (
            (session.language or "").strip()
            or (customer.preferred_language or "").strip()
        )
        product = _product_hint_for(customer)
        dealership = (customer.dealership_name or "").strip()

        # Brand-new / untouched leads often only say "No Response" with no note.
        empty_status = status.lower() in {"", "no response", "null", "none"}
        has_prior_chat = bool(
            remark or (status and not empty_status) or product or dealership
        )
        unknown = _is_unknown_crm_customer(customer)
        if not has_prior_chat and not preferred and not unknown:
            return message

        session.welcome_back_sent = True
        bits: list[str] = []
        if preferred:
            bits.append(f"preferred language: {preferred}")
        if status and not empty_status:
            bits.append(f"last CRM status was '{status}'")
        if remark:
            bits.append(f"previous remarks/notes: {remark}")
        if product:
            bits.append(f"earlier product interest: {product}")
        if dealership:
            bits.append(f"assigned dealership: {dealership}")
        if unknown:
            bits.append(
                "number not found in CRM — ask their name early and store it as lead_name "
                "so dispose can send customername"
            )

        if has_prior_chat:
            return (
                f"{message}\n\n(Returning customer — mandatory first reply. "
                "Use this prior context only — do not invent facts. "
                f"{'; '.join(bits)}. "
                "Reply in the preferred language when known. "
                "Briefly summarize what they were interested in last time "
                "(product, timing, dealership if known), then ask clearly whether "
                "they are still interested. Do not skip the still-interested question. "
                "Do not re-ask facts already clear from context; only fill gaps.)"
            )
        if not bits:
            return message
        return (
            f"{message}\n\n(Customer context for this first reply. "
            "Use this prior context only — do not invent facts. "
            f"{'; '.join(bits)}. "
            "Reply in the preferred language when known. "
            "Do not re-ask facts already clear from context; only fill gaps.)"
        )

    def _known_state_block(self, session: ClientSession) -> str:
        """A one-line snapshot of everything already captured this session.

        The transcript alone is not enough: even at 40 turns the model has to
        re-derive the pincode from message four to avoid re-asking it, and it
        does that unreliably — which is how the bot ended up asking the same
        feature question four times in a row (bug 010805). These facts are
        already tracked for dispose; stating them plainly costs ~40 tokens
        and removes the guesswork.
        """
        profile = session.lead_profile
        bits: list[str] = []

        name = str(profile.get("lead_name") or "").strip() or self._display_customer_name(
            session.customer
        )
        if name:
            bits.append(f"name: {name}")

        product = normalize_product_name(
            str(profile.get("product_interest") or "")
        ) or _product_hint_for(session.customer)
        if product:
            bits.append(f"product: {product}")

        timeline = str(profile.get("purchase_timeline") or "").strip()
        if timeline:
            bits.append(f"purchase timeline: {timeline}")

        pincode = (session.dealer_shared_for_pincode or "").strip() or str(
            profile.get("pincode") or ""
        ).strip()
        if pincode:
            bits.append(f"pincode: {pincode}")

        dealer = self._pending_dealer_name(session)
        if dealer:
            if session.dealer_confirmed:
                bits.append(f"dealer: {dealer} (confirmed by customer)")
            else:
                bits.append(f"dealer: {dealer} (not yet confirmed)")

        if session.brochures_sent:
            bits.append("brochure already sent: " + ", ".join(session.brochures_sent))

        docs = [
            label
            for key, label in (
                ("doc_license", "licence"),
                ("doc_permit", "permit"),
                ("doc_badge", "badge"),
            )
            if str(profile.get(key) or "").strip().lower() == "yes"
        ]
        if docs:
            bits.append("documents confirmed: " + ", ".join(docs))

        if session.callback_requested:
            bits.append("callback requested")

        if not bits:
            return ""
        return (
            "KNOWN SO FAR — " + " · ".join(bits) + "\n"
            "(Already captured. Do NOT ask for any of these again. "
            "Do not repeat a question you have already asked in this chat.)"
        )

    def _session_language(self, session: ClientSession) -> str:
        return (session.language or "English").strip() or "English"

    def _dealer_confirm_ask(self, customer: Customer, *, language: str = "English") -> str:
        dealer = self._resolve_crm_dealer(customer)
        if dealer is not None:
            return format_dealer_confirm_ask_from_dealer(dealer, language=language)
        return format_dealer_confirm_ask(
            name=customer.dealership_name or "TVS dealership",
            city=customer.city,
            language=language,
        )

    def _resolve_crm_dealer(self, customer: Customer):
        """Find the CRM-assigned dealer in the directory by code, then name."""
        if self._dealer_directory is None:
            return None
        dealer = None
        if customer.dealership_id:
            dealer = self._dealer_directory.get_by_code(customer.dealership_id)
        if dealer is None and customer.dealership_name:
            lookup = getattr(self._dealer_directory, "get_by_name", None)
            if lookup is not None:
                dealer = lookup(customer.dealership_name)
        return dealer

    def _pending_dealer_name(self, session: ClientSession) -> str:
        """Name of the dealership currently pending Yes/No confirmation."""
        code = (session.last_dealer_code or "").strip()
        if code and self._dealer_directory is not None:
            dealer = self._dealer_directory.get_by_code(code)
            if dealer is not None:
                return dealer.name
        customer = session.customer
        if customer and customer.dealership_name:
            return customer.dealership_name
        return ""

    def _dealer_confirm_ask_for_session(self, session: ClientSession) -> str:
        """Re-prompt with the dealer currently pending confirmation."""
        language = self._session_language(session)
        code = (session.last_dealer_code or "").strip()
        if code and self._dealer_directory is not None:
            dealer = self._dealer_directory.get_by_code(code)
            if dealer is not None:
                return format_dealer_confirm_ask_from_dealer(
                    dealer, language=language
                )
        customer = session.customer
        if customer and _crm_dealer_available(customer):
            return self._dealer_confirm_ask(customer, language=language)
        return format_dealer_confirm_ask(
            name="TVS dealership",
            language=language,
        )

    def _apply_dealer_confirm(
        self,
        session: ClientSession,
        message: str,
    ) -> tuple[str, str | None] | None:
        """Handle dealer yes/no. Returns None when not awaiting confirm.

        Otherwise returns ``(engine_message, immediate_reply_or_None)``.
        """
        if not session.awaiting_dealer_confirm:
            return None
        customer = session.customer
        confirm_result = classify_dealer_confirm_reply(message)
        if confirm_result == "yes":
            session.awaiting_dealer_confirm = False
            session.dealer_confirmed = True
            if not session.last_dealer_code and customer and customer.dealership_id:
                session.last_dealer_code = customer.dealership_id
            if (
                not session.dealer_shared_for_pincode
                and self._dealer_directory is not None
                and session.last_dealer_code
            ):
                dealer = self._dealer_directory.get_by_code(session.last_dealer_code)
                if dealer and dealer.pincode:
                    session.dealer_shared_for_pincode = dealer.pincode
            enriched = (
                f"{message}\n\n(Customer confirmed the suggested dealership is OK. "
                "Acknowledge briefly and continue the next qualification step. "
                "Do not ask for a pincode.)"
            )
            return enriched, None
        if confirm_result == "no":
            session.awaiting_dealer_confirm = False
            session.dealer_confirmed = False
            session.last_dealer_code = ""
            session.dealer_shared_for_pincode = ""
            # Image without caption + one static text (skip LLM duplicate ask).
            self._send_share_location_guide(session, with_caption=False)
            ask = share_location_ask(self._session_language(session))
            return message, ask
        # Unclear: don't drown the customer's actual message.
        pincode = extract_pincode(message)
        if pincode and pincode != session.dealer_shared_for_pincode:
            # A fresh pincode wins — drop the pending dealer and redo the lookup.
            session.awaiting_dealer_confirm = False
            session.dealer_confirmed = False
            session.last_dealer_code = ""
            session.dealer_shared_for_pincode = ""
            session.invalid_pincode_attempts = 0
            return message, None
        # Truly unclear — don't nag every turn. Remember it's unresolved and
        # defer to a single ask at wrap-up instead of re-attaching the card here.
        session.awaiting_dealer_confirm = False
        session.dealer_confirm_deferred = True
        return message, None

    def _last_bot_message(self, session: ClientSession) -> str:
        for turn in reversed(session.history):
            if turn.get("role") == "model":
                return str(turn.get("text") or "")
        return ""

    def _classify_location(self, session: ClientSession, user_message: str) -> str:
        """Decide once per turn how the customer answered about location.

        Returns "place_name", "bad_pincode" or "other". The old deny-list
        regexes decided this without knowing what the bot had just asked,
        so chat filler ("okk", "thik hai", "hmm") was read as a city name
        and a budget ("50000") as a malformed pin. Skip the call entirely
        once a dealership is settled — nothing here can apply then.
        """
        if session.dealer_confirmed or session.awaiting_dealer_confirm:
            return "other"
        return classify_location_reply(
            user_message, self._last_bot_message(session)
        )

    def _maybe_handle_invalid_pincode(
        self,
        session: ClientSession,
        *,
        user_message: str,
        language: str,
        classification: str = "",
    ) -> str | None:
        """Correct a wrong-length pin once; then fall back to live location."""
        if session.dealer_confirmed:
            return None
        if classification != "bad_pincode":
            return None
        session.invalid_pincode_attempts += 1
        lang = language or self._session_language(session)
        if session.invalid_pincode_attempts == 1:
            return invalid_pincode_ask(lang)
        self._send_share_location_guide(session, with_caption=False)
        return invalid_pincode_location_fallback(lang)

    def _send_share_location_guide(
        self,
        session: ClientSession,
        *,
        with_caption: bool = True,
    ) -> bool:
        """Send the Android/iOS how-to image asking for current location.

        Retries briefly on send failure. Returns True when the image was sent.
        Use ``with_caption=False`` when a separate text reply will carry the ask,
        so WhatsApp does not show the same instruction twice.
        """
        language = session.language or "English"
        image_url = share_location_image_url(language)
        if not image_url:
            log.warning(
                "share-location image skipped (no CLIENT_MEDIA_BASE_URL) mobile=%s",
                session.mobile,
            )
            return False
        caption = share_location_caption(language) if with_caption else ""
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                self._reply_sender.send_image(
                    mobile=session.mobile,
                    link=image_url,
                    caption=caption,
                )
                session.share_location_guide_sent = True
                return True
            except Exception as error:
                last_error = error
                if attempt < 2:
                    # Quick retry — do not use the long Gemini backoff.
                    self._sleep(0)
        log.error(
            "share-location image send failed mobile=%s url=%s",
            session.mobile,
            image_url,
            exc_info=last_error,
        )
        return False

    @staticmethod
    def _asks_a_question(text: str) -> bool:
        """True when the model's reply already puts a question to the customer.

        Nothing deterministic may append a second question to such a reply.
        The prompt already says "do NOT ask any question of your own" when a
        card is coming, and the model ignores it — a customer asked "which
        model do you want?" AND "is this dealership OK?" in one message has
        no idea which to answer. Checking the actual output makes the stack
        impossible instead of merely discouraged.
        """
        return any(mark in (text or "") for mark in ("?", "？", "﻿?"))

    def _dealer_share_ask_for_session(
        self, session: ClientSession, dealer_code: str
    ) -> str:
        """Arm the consent question for `dealer_code` and return its text.

        ``last_dealer_code`` is set here, not on consent: which dealer the
        lead is routed to is a CRM fact that dispose needs regardless of
        whether the customer wanted to see the contact card. Only the
        name/address/phone/map going out to the customer is consent-gated.
        """
        session.awaiting_dealer_share_consent = True
        session.dealer_share_asked = True
        session.pending_dealer_share_code = dealer_code
        if dealer_code:
            session.last_dealer_code = dealer_code
        return dealer_share_ask(self._session_language(session))

    def _apply_dealer_share_consent(
        self,
        session: ClientSession,
        message: str,
    ) -> tuple[str, str | None] | None:
        """Handle the reply to "may I share the dealership details?".

        Returns None when no consent is pending, otherwise
        ``(engine_message, immediate_reply_or_None)``. Only a clear yes
        releases the contact details; anything else continues the
        conversation without them.
        """
        if not session.awaiting_dealer_share_consent:
            return None
        session.awaiting_dealer_share_consent = False
        code = session.pending_dealer_share_code
        session.pending_dealer_share_code = ""
        decision = classify_share_consent_reply(message)
        if decision == "yes":
            session.last_dealer_code = code or session.last_dealer_code
            session.awaiting_dealer_confirm = True
            return message, self._dealer_confirm_ask_for_session(session)
        if decision == "no":
            session.dealer_share_declined = True
            return (
                f"{message}\n\n(Customer does not want the dealership details "
                "right now. Acknowledge briefly, do NOT send dealership "
                "details, and continue with the next qualification step.)"
            ), None
        # Unclear — they were talking about something else. Don't assume
        # consent, and don't nag: the ask can come round again later.
        session.dealer_share_asked = False
        return message, None

    def _maybe_offer_crm_dealer(
        self,
        session: ClientSession,
        *,
        user_message: str,
        reply: str,
        is_first_reply: bool = False,
    ) -> str:
        # offer is mandatory once CRM has a dealer, but never stack it onto
        # the very first REAL qualification reply (from the engine) unless
        # the customer's own message already signals they're at the
        # location step (e.g. they led with a pincode). Checking
        # session.history isn't enough: a returning customer's
        # still-interested exchange already writes to history before the
        # engine is ever called, so "first reply" must track actual engine
        # calls (session.qualification_started), not turn count.
        if is_first_reply and not extract_pincode(user_message):
            return reply
        if session.crm_dealer_offered or session.dealer_confirmed:
            return reply
        if session.awaiting_dealer_confirm or session.awaiting_dealer_share_consent:
            return reply
        if session.dealer_share_declined:
            return reply
        customer = session.customer
        if not _crm_dealer_available(customer):
            return reply
        # The model already asked something. Appending the consent question
        # here would put two questions in one message — the exact complaint
        # from the 02/08 transcript. Wait for a turn we can have to ourselves.
        if self._asks_a_question(reply):
            return reply
        assert customer is not None
        session.crm_dealer_offered = True
        resolved = self._resolve_crm_dealer(customer)
        code = ""
        if resolved is not None and resolved.dealer_code:
            code = resolved.dealer_code
        elif customer.dealership_id:
            code = customer.dealership_id
        ask = self._dealer_share_ask_for_session(session, code)
        return f"{reply.rstrip()}\n\n{ask}"

    def _retry_empty_reply(self, turn: TurnInput, output):
        """Ask again when the model returns nothing.

        Gemini occasionally answers a closer like "ok" or "thik hai" with an
        empty string. That used to be dropped silently, so the customer got
        no reply at all and had to send "hello" to get the bot talking again
        (bug 240711). Re-ask with an explicit instruction rather than sending
        a canned line, so the reply stays in the flow of the conversation.
        """
        if (output.reply_text or "").strip():
            return output
        nudged = TurnInput(
            session_id=turn.session_id,
            language=turn.language,
            message=(
                f"{turn.message}\n\n(The customer sent a short "
                "acknowledgement. Reply with one short line in "
                f"{turn.language}: acknowledge them and ask the next "
                "qualification question, or thank them and close if "
                "everything is already captured. Never reply with nothing.)"
            ),
            channel=turn.channel,
            source=turn.source,
            history=turn.history,
            product_hint=turn.product_hint,
            confirm_crm_dealer=turn.confirm_crm_dealer,
        )
        try:
            retried = self._engine.handle_turn(nudged)
        except Exception:
            log.exception("empty-reply retry failed")
            return output
        if (retried.reply_text or "").strip():
            return retried
        # Twice empty — going silent is the one thing we must not do.
        return replace(
            output, reply_text=acknowledgement_fallback(turn.language)
        )

    def _pending_nearest_dealer(self, session: ClientSession, user_message: str):
        """The dealer ``_attach_nearest_dealer`` would append this turn, or None.

        Resolved before the LLM call so the prompt can suppress the model's
        own question whenever a dealer-confirm card is going to follow it.
        Read-only — the session is mutated by _attach_nearest_dealer.

        Falls back to a dealer resolved on an earlier turn and persisted in
        ``pending_nearest_dealer_code`` when this turn's message carries no
        pincode of its own — see _attach_nearest_dealer for why that persist
        step exists.
        """
        if self._dealer_directory is None:
            return None
        if session.dealer_confirmed or session.awaiting_dealer_confirm:
            return None
        if session.awaiting_dealer_share_consent or session.dealer_share_declined:
            return None
        pincode = extract_pincode(user_message)
        if pincode and pincode != session.dealer_shared_for_pincode:
            try:
                return self._dealer_directory.find_nearest_by_pincode(pincode)
            except Exception:
                return None
        if (
            session.pending_nearest_dealer_code
            and session.pending_nearest_dealer_pincode
            != session.dealer_shared_for_pincode
        ):
            # Must never raise: process() calls this outside any try, so an
            # exception here costs the customer their whole reply.
            try:
                return self._dealer_directory.get_by_code(
                    session.pending_nearest_dealer_code
                )
            except Exception:
                return None
        return None

    def _attach_nearest_dealer(
        self,
        session: ClientSession,
        *,
        user_message: str,
        reply: str,
        dealer=None,
    ) -> str:
        if self._dealer_directory is None:
            return reply
        if session.dealer_confirmed or session.awaiting_dealer_confirm:
            return reply
        if session.awaiting_dealer_share_consent or session.dealer_share_declined:
            return reply
        pincode = extract_pincode(user_message)
        if pincode and pincode != session.dealer_shared_for_pincode:
            target_pincode = pincode
        elif (
            session.pending_nearest_dealer_code
            and session.pending_nearest_dealer_pincode
            != session.dealer_shared_for_pincode
        ):
            target_pincode = session.pending_nearest_dealer_pincode
        else:
            return reply
        if dealer is None:
            try:
                dealer = self._dealer_directory.find_nearest_by_pincode(
                    target_pincode
                )
            except Exception:
                return reply
        if dealer is None:
            return reply
        # Never append to a reply that already asks something (see
        # _asks_a_question) — the consent question must stand alone. Unlike
        # a pincode, which only ever appears once in the message stream, the
        # resolved dealer is persisted here so a later, question-free turn
        # can still offer it instead of losing the chance for good (mirrors
        # _maybe_offer_crm_dealer's every-turn retry for the CRM-dealer case).
        if self._asks_a_question(reply):
            session.pending_nearest_dealer_code = dealer.dealer_code
            session.pending_nearest_dealer_pincode = target_pincode
            return reply
        session.pending_nearest_dealer_code = ""
        session.pending_nearest_dealer_pincode = ""
        session.dealer_shared_for_pincode = target_pincode
        ask = self._dealer_share_ask_for_session(session, dealer.dealer_code)
        return f"{reply.rstrip()}\n\n{ask}"

    def _maybe_handle_place_name(
        self,
        session: ClientSession,
        *,
        user_message: str,
        language: str,
        classification: str = "",
    ) -> str | None:
        """If the customer sends a city/area name, redirect to pin or live location."""
        if session.dealer_confirmed or session.awaiting_dealer_confirm:
            return None
        if wants_callback(user_message):
            return None
        if (
            session.awaiting_brochure_offer
            or session.awaiting_brochure_product_choice
            or wants_product_brochure(user_message)
            or wants_product_info(user_message)
            or _is_brochure_offer_accept(user_message)
        ):
            return None
        if doesnt_know_pincode(user_message) or is_bare_dont_know(user_message):
            return None
        if extract_pincode(user_message) or classification != "place_name":
            return None
        # Caption off — place_redirect_message is the single text ask.
        self._send_share_location_guide(session, with_caption=False)
        return place_redirect_message(
            language or self._session_language(session)
        )

    def _capture_purchase_date(
        self,
        session: ClientSession,
        *,
        user_message: str,
    ) -> None:
        """Keep explicit dates the customer typed (e.g. 12-12-26) in the profile.

        The LLM profile sometimes reports purchase_timeline as "unknown" even
        after the customer sent a concrete date; capture it at the seam so
        dispose never falls back when a real date was given.
        """
        result = resolve_purchase_date(user_message)
        if result.value and result.rule in {"explicit_dmy", "month_name"}:
            session.lead_profile["purchase_timeline"] = result.value

    def _capture_pincode(
        self,
        session: ClientSession,
        *,
        user_message: str,
    ) -> None:
        """Persist a typed 6-digit pincode for dispose, independent of dealer card.

        Dealer consent attach may be deferred when the LLM asks its own question;
        dispose still needs the pin on that same turn (Option A).
        """
        pin = extract_pincode(user_message)
        if pin:
            session.lead_profile["pincode"] = pin

    def _capture_lead_name(
        self,
        session: ClientSession,
        *,
        user_message: str,
    ) -> None:
        """For numbers not in CRM, keep the customer's spoken name for dispose.customername.

        PROFILE_JSON only arrives at wrap-up, but dispose may fire earlier (pincode /
        product). Capture a short name reply when we just asked for their name.
        """
        if not _is_unknown_crm_customer(session.customer):
            return
        if str(session.lead_profile.get("lead_name") or "").strip():
            return
        raw = " ".join((user_message or "").strip().split())
        if not raw or len(raw) > 60:
            return
        if extract_pincode(raw) or resolve_purchase_date(raw).value:
            return
        if _is_affirmative(raw) or _is_negative(raw) or wants_callback(raw):
            return
        if brochure_product_from_text(raw):
            return
        if len(raw.split()) > 5:
            return
        # Only capture right after we asked for a name.
        last_bot = ""
        for turn in reversed(session.history):
            if turn.get("role") == "model":
                last_bot = str(turn.get("text") or "")
                break
        ask_markers = (
            "name",
            "नाव",
            "नाम",
            "పేరు",
            "பெயர்",
            "ಹೆಸರು",
            "പേര്",
        )
        lowered = last_bot.lower()
        if not any(marker in last_bot or marker in lowered for marker in ask_markers):
            return
        session.lead_profile["lead_name"] = raw

    def _maybe_dispose(self, session: ClientSession, *, profile: dict | None) -> None:
        """Sync lead snapshot to JAM dispose whenever fields change (MCP-style)."""
        if self._dispose_client is None:
            return
        if profile:
            merged = dict(session.lead_profile)
            incoming = dict(profile)
            # Never let an unparseable timeline (e.g. "unknown") overwrite a real date.
            old_timeline = str(merged.get("purchase_timeline") or "")
            new_timeline = str(incoming.get("purchase_timeline") or "")
            if (
                old_timeline
                and resolve_purchase_date(old_timeline).value
                and not resolve_purchase_date(new_timeline).value
            ):
                incoming.pop("purchase_timeline", None)
            merged.update(incoming)
            session.lead_profile = merged

        enriched = dict(session.lead_profile)
        if session.callback_requested:
            enriched["callback_requested"] = True
            enriched.setdefault("disposition", "interested")
        preferred = (
            (session.language or "").strip()
            or (
                (session.customer.preferred_language or "").strip()
                if session.customer
                else ""
            )
        )
        if preferred:
            enriched.setdefault("preferred_language", preferred)
        if not normalize_product_name(str(enriched.get("product_interest") or "")):
            hint = _product_hint_for(session.customer)
            if hint:
                enriched["product_interest"] = hint
        # New CRM field customername — required when the mobile is not already in CRM.
        if not str(enriched.get("lead_name") or "").strip():
            if session.customer and not _is_unknown_crm_customer(session.customer):
                crm_name = (session.customer.name or "").strip()
                if crm_name:
                    enriched.setdefault("lead_name", crm_name)
        dealer_code = (session.last_dealer_code or "").strip()
        if not dealer_code and session.customer and session.customer.dealership_id:
            dealer_code = session.customer.dealership_id.strip()

        pincode = (session.dealer_shared_for_pincode or "").strip()
        if not pincode:
            pincode = str(enriched.get("pincode") or enriched.get("pin_code") or "").strip()

        # Nothing useful to sync yet (avoid dispose on bare "hi")
        has_signal = bool(
            normalize_product_name(str(enriched.get("product_interest") or ""))
            or dealer_code
            or session.callback_requested
            or enriched.get("disposition")
            or enriched.get("purchase_timeline")
            or enriched.get("notes")
            or pincode
            or (
                _is_unknown_crm_customer(session.customer)
                and str(enriched.get("lead_name") or "").strip()
            )
        )
        if not has_signal:
            return

        payload = build_dispose_payload(
            mobile=session.mobile,
            profile=enriched,
            dealer_code=dealer_code,
            pincode=pincode,
        )
        if payload is None:
            return
        fingerprint = json.dumps(payload.body, sort_keys=True, ensure_ascii=False)
        if fingerprint == session.last_dispose_fingerprint:
            return
        try:
            self._dispose_client.dispose(payload.body)
            session.last_dispose_fingerprint = fingerprint
            session.dispose_sent = True
            log.info(
                "dispose ok mobile=%s status=%s pincode=%s",
                session.mobile,
                payload.status,
                payload.body.get("pincode", ""),
            )
        except Exception:
            log.exception(
                "dispose failed mobile=%s status=%s",
                session.mobile,
                payload.status,
            )
            # Still mark fingerprint so we do not hammer the API on the same body.
            session.last_dispose_fingerprint = fingerprint
            session.dispose_sent = True

    def _handle_location_event(
        self,
        event: dict,
        *,
        session: ClientSession,
        language: str,
        started: float,
    ) -> None:
        """Resolve nearest dealer from shared coordinates; skip the LLM."""
        coords = extract_coordinates(event)
        user_label = "shared location"
        reply_language = language or session.language or "English"
        if coords is None:
            reply = location_unreadable(reply_language)
            self._reply_and_record(
                event,
                session=session,
                language=reply_language,
                user_message=user_label,
                reply=reply,
                started=started,
            )
            self._complete_turn(session, event["message_id"], user_label, reply)
            return

        latitude, longitude = coords
        session.awaiting_dealer_confirm = False
        if self._dealer_directory is None:
            reply = location_need_pincode(reply_language)
            self._reply_and_record(
                event,
                session=session,
                language=reply_language,
                user_message=user_label,
                reply=reply,
                started=started,
            )
            self._complete_turn(session, event["message_id"], user_label, reply)
            return

        try:
            dealer = self._dealer_directory.find_nearest_by_coords(
                latitude, longitude
            )
        except Exception:
            log.exception(
                "nearest dealer by coords failed mobile=%s",
                session.mobile,
            )
            dealer = None

        if dealer is None:
            reply = location_no_dealer(reply_language)
            self._reply_and_record(
                event,
                session=session,
                language=reply_language,
                user_message=user_label,
                reply=reply,
                started=started,
            )
            self._complete_turn(session, event["message_id"], user_label, reply)
            return

        session.dealer_confirmed = False
        if dealer.pincode and not session.dealer_shared_for_pincode:
            session.dealer_shared_for_pincode = dealer.pincode
        # Even here the details are not volunteered: a shared pin tells us
        # WHERE they are, not that they want a dealership's phone number.
        ask = self._dealer_share_ask_for_session(session, dealer.dealer_code)
        reply = f"{location_thanks(reply_language)}\n\n{ask}"
        self._maybe_dispose(session, profile=None)
        self._reply_and_record(
            event,
            session=session,
            language=reply_language,
            user_message=user_label,
            reply=reply,
            started=started,
        )
        self._complete_turn(session, event["message_id"], user_label, reply)

    def _message_for_event(
        self,
        event: dict,
        *,
        session: ClientSession,
        language: str,
    ) -> tuple[str, str | None]:
        if event["type"] == "text":
            return (event.get("content") or "").strip(), None
        if event["type"] == "location":
            return "shared location", None

        data, mime_type = self._media_fetcher.fetch(
            event["media_url"],
            event.get("mime_type"),
            message_type=event["type"],
        )
        if event["type"] == "audio":
            transcript = self._attempt(
                lambda: self._transcriber.transcribe(
                    data,
                    mime_type,
                    language,
                )
            )
            if not transcript:
                return "audio", "I could not hear that audio. Please resend it clearly."
            return transcript, None

        result = self._attempt(
            lambda: self._document_recognizer.recognize(data, mime_type)
        )
        if result.status == "not_document":
            return (
                "non-document image",
                "I can currently process document images only. "
                "Please send a relevant document or describe your question as text.",
            )

        document_types = result.document_types or ["unknown"]
        self._lead_store.add_documents(
            session=session.conversation_id,
            document_types=document_types,
            url=event["media_url"],
            status=result.status,
        )
        if result.status == "unknown":
            session.unclear_document_count += 1
            return (
                "unclear document image",
                "I could not identify that document. Please send a clearer image.",
            )
        names = ", ".join(document_types)
        return (
            f"The customer uploaded these documents: {names}. "
            "Acknowledge them and continue with the next qualification step.",
            None,
        )

    def _maybe_switch_language(self, session: ClientSession, text: str) -> str:
        """Apply a mid-chat language change the customer asked for.

        Returns the session language after the check. Works on transcribed
        voice notes too — a customer who said "I want to speak in English"
        in a voice note got one English reply and then Marathi again,
        because only typed text ever reached this path (bug 010802).
        """
        switched = classify_language_switch(text or "")
        if (
            switched
            and switched in SUPPORTED_LANGUAGES
            and switched != session.language
        ):
            session.language = switched
        return session.language

    def _resolve_language(self, session: ClientSession, event: dict) -> str | None:
        """Return session language, or None when the language menu was just sent."""
        content = (event.get("content") or "").strip()

        if session.awaiting_language_selection:
            choice = parse_language_choice(content)
            if choice:
                session.language = choice
                session.awaiting_language_selection = False
                return choice
            # Re-prompt; stay in English for the menu.
            return None

        if session.language in SUPPORTED_LANGUAGES:
            # Mid-chat switch via explicit language name / number / script label.
            # Skip while the still-interested or vehicle-vs-PGM prompt is
            # pending — their "Press 1 / Press 2" reuse the same digits 1-7
            # that _NAME_TO_LANGUAGE maps to language-menu choices, so a bare
            # "1" meant as "yes" / "vehicle" would otherwise get misread as
            # "switch to English" (1 = English in the language menu).
            if (
                event.get("type") == "text"
                and not session.awaiting_still_interested
                and not session.awaiting_flow_intent
            ):
                self._maybe_switch_language(session, content)
            return session.language

        # Fresh session (including after the idle Redis TTL expires): always show the
        # language menu. Do not auto-apply CRM preferred_language — the customer
        # must choose again for the new conversation.
        session.awaiting_language_selection = True
        return None

    def _reply_and_record(
        self,
        event: dict,
        *,
        session: ClientSession,
        language: str,
        user_message: str,
        reply: str,
        started: float,
        citations: list[str] | None = None,
        status: str = "ok",
        error: str = "",
        needs_review: bool = False,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> None:
        if not reply.strip():
            # The model occasionally returns an empty reply on closers like
            # "Ok"; stay silent instead of sending a blank WhatsApp message.
            return
        try:
            self._reply_sender.send(
                mobile=session.mobile,
                in_reply_to=event["message_id"],
                text=reply,
            )
        except Exception as delivery_error:
            self._interactions.record_exchange(
                session=session.conversation_id,
                mobile=session.mobile,
                channel="client_app",
                source="client_app",
                language=language,
                user_message=user_message,
                assistant_message=reply,
                latency_ms=round((perf_counter() - started) * 1000),
                status="delivery_failed",
                error=str(delivery_error),
                model=config.MODEL,
                citations=citations,
                needs_review=True,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            raise
        self._interactions.record_exchange(
            session=session.conversation_id,
            mobile=session.mobile,
            channel="client_app",
            source="client_app",
            language=language,
            user_message=user_message,
            assistant_message=reply,
            latency_ms=round((perf_counter() - started) * 1000),
            status=status,
            error=error,
            model=config.MODEL,
            citations=citations,
            needs_review=needs_review,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def _attempt(self, operation: Callable[[], "_T"]) -> "_T":
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return operation()
            except Exception as error:
                last_error = error
                if attempt < 2:
                    self._sleep(self._retry_wait)
        assert last_error is not None
        raise last_error

    def _complete_turn(
        self,
        session: ClientSession,
        message_id: str,
        user_message: str,
        reply: str,
    ) -> None:
        session.pending_replies.pop(message_id, None)
        session.history.extend(
            [
                {"role": "user", "text": user_message},
                {"role": "model", "text": reply},
            ]
        )
        session.history = session.history[-(config.MAX_HISTORY_TURNS * 2) :]
        self._state.save(session)


_T = TypeVar("_T")

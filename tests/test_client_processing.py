"""Client-app worker behavior at the message-processor seam."""
from __future__ import annotations

import pytest

from conversation_engine import TurnOutput
from client_processing import (
    ClientMessageProcessor,
    ClientSession,
    Customer,
    DocumentRecognition,
)
from client_static_messages import dealer_share_ask, flow_intent_ask
from dealers import Dealer, DealerDirectory
from dispose import resolve_purchase_date


class FakeDisposeClient:
    def __init__(self):
        self.calls: list[dict] = []
        self.error: Exception | None = None

    def dispose(self, payload: dict) -> dict:
        self.calls.append(payload)
        if self.error is not None:
            raise self.error
        return {"status": "success"}



class FakeDealerDirectory:
    def __init__(self, dealer: Dealer | None, *, by_code: dict[str, Dealer] | None = None):
        self.dealer = dealer
        self.by_code = dict(by_code or {})
        if dealer is not None and dealer.dealer_code:
            self.by_code.setdefault(dealer.dealer_code, dealer)
        self.calls: list[str] = []
        self.coord_calls: list[tuple[float, float]] = []
        self.place_calls: list[str] = []

    def find_nearest_by_pincode(self, pincode: str) -> Dealer | None:
        self.calls.append(pincode)
        return self.dealer

    def find_nearest_by_place(self, place: str, *, max_km: float = 120.0) -> Dealer | None:
        del max_km
        self.place_calls.append(place)
        return self.dealer

    def find_nearest_by_coords(
        self, latitude: float, longitude: float
    ) -> Dealer | None:
        self.coord_calls.append((latitude, longitude))
        return self.dealer

    def get_by_code(self, dealer_code: str) -> Dealer | None:
        return self.by_code.get((dealer_code or "").strip())


class FakeState:
    def __init__(self):
        self.sessions: dict[str, ClientSession] = {}

    def load_or_start(self, mobile: str) -> ClientSession:
        if mobile not in self.sessions:
            self.sessions[mobile] = ClientSession(
                conversation_id=f"client-{mobile[-4:]}-1",
                mobile=mobile,
            )
        return self.sessions[mobile]

    def save(self, session: ClientSession) -> None:
        self.sessions[session.mobile] = session


class FakeDirectory:
    def __init__(self):
        self.calls: list[str] = []
        # Default English so static-message assertions stay stable; set Marathi
        # explicitly in language-specific tests.
        self.customer = Customer("crm-1", "Asha", "English")

    def lookup(self, mobile: str) -> Customer:
        self.calls.append(mobile)
        return self.customer


class FailingDirectory(FakeDirectory):
    def lookup(self, mobile: str) -> Customer:
        self.calls.append(mobile)
        raise RuntimeError("CRM unavailable")


class FakeEngine:
    """Stands in for Gemini, and — like the real prompt expects — obeys the
    "do NOT ask any question of your own" instruction the processor injects
    when it is about to append a dealership question. Without that, the fake
    would ask something every turn and the processor would (correctly) keep
    deferring its own ask forever to avoid stacking two questions."""

    SUPPRESS_QUESTION = "Do NOT ask any question of your own"

    def __init__(self):
        self.turns = []
        self.reply = "तुम्हाला कोणते TVS मॉडेल आवडते?"
        self.acknowledgement = "ठीक आहे."
        self.profile = None

    def handle_turn(self, turn):
        self.turns.append(turn)
        reply = self.reply
        if self.SUPPRESS_QUESTION in (turn.message or ""):
            reply = self.acknowledgement
        return TurnOutput(reply_text=reply, profile=self.profile, captured=bool(self.profile))


class FakeReplySender:
    def __init__(self):
        self.calls: list[dict] = []
        self.image_calls: list[dict] = []
        self.document_calls: list[dict] = []

    def send(self, *, mobile: str, in_reply_to: str, text: str) -> None:
        self.calls.append(
            {"mobile": mobile, "in_reply_to": in_reply_to, "text": text}
        )

    def send_image(self, *, mobile: str, link: str, caption: str = "") -> None:
        self.image_calls.append(
            {"mobile": mobile, "link": link, "caption": caption}
        )

    def send_document(self, *, mobile: str, link: str, caption: str = "") -> None:
        self.document_calls.append(
            {"mobile": mobile, "link": link, "caption": caption}
        )


class FailOnceReplySender(FakeReplySender):
    def __init__(self):
        super().__init__()
        self.failed = False

    def send(self, *, mobile: str, in_reply_to: str, text: str) -> None:
        super().send(mobile=mobile, in_reply_to=in_reply_to, text=text)
        if not self.failed:
            self.failed = True
            raise RuntimeError("callback unavailable")


class FakeLeadStore:
    def __init__(self):
        self.identities: list[dict] = []
        self.documents: list[dict] = []

    def upsert_client_identity(self, **values) -> None:
        self.identities.append(values)

    def add_documents(self, **values) -> None:
        self.documents.append(values)


class FakeInteractionStore:
    def __init__(self):
        self.exchanges: list[dict] = []

    def record_exchange(self, **values):
        self.exchanges.append(values)


class FakeMediaFetcher:
    def fetch(
        self, url: str, mime_type: str | None = None, *, message_type: str | None = None
    ) -> tuple[bytes, str]:
        resolved = mime_type or f"resolved/{message_type or 'media'}"
        return f"bytes:{url}:{resolved}".encode(), resolved


class FailingMediaFetcher:
    def fetch(
        self, url: str, mime_type: str | None = None, *, message_type: str | None = None
    ) -> tuple[bytes, str]:
        raise ValueError("media unavailable")


class FakeTranscriber:
    def transcribe(self, data: bytes, mime_type: str, language: str) -> str:
        return "मला ईव्ही मॅक्स पाहिजे"


class FakeDocumentRecognizer:
    def __init__(self, result=None):
        self.result = result or DocumentRecognition(["driving_licence"], "recognized")

    def recognize(self, data: bytes, mime_type: str) -> DocumentRecognition:
        return self.result


def _processor(**overrides):
    preselect_language = overrides.pop("preselect_language", "English")
    # Qualification tests are not about welcome-back; opt in with False.
    skip_still_interested = overrides.pop("skip_still_interested", True)
    dependencies = {
        "state": FakeState(),
        "directory": FakeDirectory(),
        "engine": FakeEngine(),
        "reply_sender": FakeReplySender(),
        "lead_store": FakeLeadStore(),
        "interaction_store": FakeInteractionStore(),
        "media_fetcher": FakeMediaFetcher(),
        "transcriber": FakeTranscriber(),
        "document_recognizer": FakeDocumentRecognizer(),
    }
    dependencies.update(overrides)
    # Most tests exercise qualification, not the language menu. Fresh sessions
    # always prompt for language in production; pre-select here unless disabled.
    if preselect_language or skip_still_interested:
        session = dependencies["state"].load_or_start("+918286871533")
        if preselect_language:
            session.language = preselect_language
            session.awaiting_language_selection = False
        if skip_still_interested:
            session.still_interested_asked = True
        dependencies["state"].save(session)
    return ClientMessageProcessor(**dependencies), dependencies


def _event(**overrides):
    event = {
        "message_id": "incoming-1",
        "type": "text",
        "mobile": "+918286871533",
        "timestamp": "client-time",
        "content": "नमस्कार",
    }
    event.update(overrides)
    return event


def test_text_message_uses_crm_identity_engine_and_callback():
    processor, deps = _processor()

    processor.process(_event())

    assert deps["directory"].calls == ["+918286871533"]
    turn = deps["engine"].turns[0]
    assert turn.session_id == "client-1533-1"
    assert turn.language == "English"
    assert turn.channel == "client_app"
    assert turn.source == "client_app"
    # First turn carries the CRM context (preferred language) after the message.
    assert turn.message.startswith("नमस्कार")
    assert "preferred language: English" in turn.message
    assert deps["reply_sender"].calls == [
        {
            "mobile": "+918286871533",
            "in_reply_to": "incoming-1",
            "text": "तुम्हाला कोणते TVS मॉडेल आवडते?",
        }
    ]
    assert deps["lead_store"].identities[0]["customer_name"] == "Asha"
    assert deps["lead_store"].identities[0]["message_id"] == "incoming-1"
    assert deps["lead_store"].identities[0]["client_timestamp"] == "client-time"
    assert deps["interaction_store"].exchanges[0]["channel"] == "client_app"


def test_customer_lookup_is_cached_for_the_conversation():
    processor, deps = _processor()

    processor.process(_event())
    processor.process(_event(message_id="incoming-2", content="EV MAX"))

    assert deps["directory"].calls == ["+918286871533"]
    assert len(deps["engine"].turns[1].history) == 2


def test_naming_product_alone_does_not_send_brochure(monkeypatch):
    """Naming a model is not enough — the customer must explicitly ask."""
    del monkeypatch  # CDN URLs are absolute; no media-base stub needed
    processor, deps = _processor()
    deps["engine"].reply = "Great choice — King Deluxe."

    processor.process(_event(message_id="m1", content="King deluxe"))

    assert deps["reply_sender"].document_calls == []
    assert deps["state"].sessions["+918286871533"].brochures_sent == []


def test_brochure_ask_without_product_asks_which_model(monkeypatch):
    """Brochure ask with no known product must not send a PDF or claim one."""
    del monkeypatch
    processor, deps = _processor()
    deps["engine"].reply = "Sure — which model do you want?"

    processor.process(
        _event(message_id="m1", content="Kya muje brocher meliega")
    )

    assert deps["reply_sender"].document_calls == []
    session = deps["state"].sessions["+918286871533"]
    assert session.brochures_sent == []
    assert session.awaiting_brochure_product_choice is True
    reply = deps["reply_sender"].calls[-1]["text"]
    assert "King EV MAX" in reply
    assert "King Deluxe" in reply
    # LLM prompt must forbid a false "I'm sending it" claim
    assert any(
        "Do NOT say you are sending" in turn.message
        for turn in deps["engine"].turns
    )


def test_brochure_ask_then_product_name_sends_pdf(monkeypatch):
    """After a product-less brochure ask, naming a model sends the pack."""
    del monkeypatch
    processor, deps = _processor()
    deps["engine"].reply = "Which model?"
    processor.process(
        _event(message_id="m1", content="Kya muje brocher meliega")
    )
    assert deps["reply_sender"].document_calls == []

    deps["engine"].reply = "Great — King EV MAX."
    processor.process(
        _event(message_id="m2", content="TVS EV KING MAX MAI")
    )

    links = [call["link"] for call in deps["reply_sender"].document_calls]
    assert links == [
        "https://1.jamoutsourcing.com/f/King_EV_MAX-English.pdf",
    ]
    session = deps["state"].sessions["+918286871533"]
    assert session.brochures_sent == ["King EV MAX"]
    assert session.awaiting_brochure_product_choice is False


def test_explicit_brochure_request_sends_pdf_once(monkeypatch):
    """An explicit "send brochure" request sends the brochure once —
    just the brochure, not the PMS/warranty pack (bug 010804)."""
    del monkeypatch  # CDN URLs are absolute; no media-base stub needed
    processor, deps = _processor()
    deps["engine"].reply = "Great choice — King Deluxe."

    processor.process(
        _event(message_id="m1", content="Please send me the King Deluxe brochure")
    )

    assert deps["reply_sender"].document_calls == [
        {
            "mobile": "+918286871533",
            "link": "https://1.jamoutsourcing.com/f/King_Deluxe_Petrol-English.pdf",
            "caption": "King Deluxe brochure",
        },
    ]
    assert deps["state"].sessions["+918286871533"].brochures_sent == ["King Deluxe"]

    deps["engine"].reply = "Noted."
    processor.process(_event(message_id="m2", content="Ok"))
    processor.process(
        _event(message_id="m3", content="Send me the King Deluxe brochure again")
    )
    # Sent once per product per session, and the repeat ask adds nothing.
    assert len(deps["reply_sender"].document_calls) == 1
    # ...and the repeat ask must not have the model claim a second send.
    assert "ALREADY sent" in deps["engine"].turns[-1].message


def test_brochure_request_resolves_product_from_earlier_history(monkeypatch):
    """"Send me the brochure for this" doesn't repeat the product name — it
    must be resolved from what the customer said a few turns earlier, since
    lead_profile.product_interest isn't captured until LLM wrap-up."""
    del monkeypatch  # CDN URLs are absolute; no media-base stub needed
    processor, deps = _processor()
    deps["engine"].reply = "Great choice — King EV MAX. When are you looking to buy?"
    processor.process(_event(message_id="m1", content="King EV MAX"))
    assert deps["reply_sender"].document_calls == []  # no product-name-only send

    deps["engine"].reply = "Sure, here's more info."
    processor.process(
        _event(message_id="m2", content="send me the brochure for this")
    )

    links = [call["link"] for call in deps["reply_sender"].document_calls]
    assert links == [
        "https://1.jamoutsourcing.com/f/King_EV_MAX-English.pdf",
    ]


def test_info_question_offers_brochure_instead_of_auto_sending(monkeypatch):
    """A general info question ("what are the features") gets a text answer
    plus a deterministic offer — not an automatic document send."""
    del monkeypatch
    processor, deps = _processor()
    deps["engine"].reply = "Great choice — King EV MAX. When are you looking to buy?"
    processor.process(_event(message_id="m1", content="King EV MAX"))

    deps["engine"].reply = "It has a 100km range and fast charging."
    processor.process(
        _event(message_id="m2", content="What are the features of this?")
    )

    assert deps["reply_sender"].document_calls == []
    reply_text = deps["reply_sender"].calls[-1]["text"]
    assert "brochure" in reply_text.lower()
    session = deps["state"].sessions["+918286871533"]
    assert session.awaiting_brochure_offer is True
    assert session.pending_brochure_product == "King EV MAX"


def test_info_question_tells_llm_to_answer_only(monkeypatch):
    """The LLM is told not to ask its own follow-up this turn — the
    brochure offer is the one question, appended deterministically."""
    del monkeypatch
    processor, deps = _processor()
    deps["engine"].reply = "Great choice — King EV MAX. When are you looking to buy?"
    processor.process(_event(message_id="m1", content="King EV MAX"))

    deps["engine"].reply = "It has a 100km range."
    processor.process(
        _event(message_id="m2", content="What are the features of this?")
    )

    enriched = deps["engine"].turns[-1].message
    assert "at most TWO sentences" in enriched
    assert "Do NOT ask a qualification question" in enriched


def test_brochure_offer_accepted_sends_pack(monkeypatch):
    del monkeypatch
    processor, deps = _processor()
    deps["engine"].reply = "Great choice — King EV MAX. When are you looking to buy?"
    processor.process(_event(message_id="m1", content="King EV MAX"))
    deps["engine"].reply = "It has a 100km range."
    processor.process(
        _event(message_id="m2", content="What are the features of this?")
    )
    assert deps["reply_sender"].document_calls == []

    deps["engine"].reply = "Great, noted."
    processor.process(_event(message_id="m3", content="yes"))

    links = [call["link"] for call in deps["reply_sender"].document_calls]
    assert links == [
        "https://1.jamoutsourcing.com/f/King_EV_MAX-English.pdf",
    ]
    session = deps["state"].sessions["+918286871533"]
    assert session.awaiting_brochure_offer is False
    enriched = deps["engine"].turns[-1].message
    assert "has been sent" in enriched


def test_brochure_offer_accepted_with_bhejo_sends_pack(monkeypatch):
    """Hindi/Hinglish 'bhejo' must accept the brochure offer (not place routing)."""
    del monkeypatch
    processor, deps = _processor()
    deps["engine"].reply = "Great choice — King EV MAX."
    processor.process(_event(message_id="m1", content="King EV MAX"))
    deps["engine"].reply = "It has a 100km range."
    processor.process(
        _event(message_id="m2", content="What are the features of this?")
    )
    assert deps["state"].sessions["+918286871533"].awaiting_brochure_offer is True

    deps["engine"].reply = "Sending it now."
    processor.process(_event(message_id="m3", content="bhejo"))

    links = [call["link"] for call in deps["reply_sender"].document_calls]
    assert links == [
        "https://1.jamoutsourcing.com/f/King_EV_MAX-English.pdf",
    ]
    # Must not have fallen into the share-location place-name path.
    texts = " ".join(c.get("text") or "" for c in deps["reply_sender"].calls)
    assert "pincode" not in texts.lower()
    assert "लोकेशन" not in texts and "location" not in texts.lower()


def test_product_switch_wins_over_earlier_named_model(monkeypatch):
    """A vague brochure request after a product switch must resolve the
    NEW model. Persisting the first resolved product into lead_profile
    makes it sticky — and since the lead_profile hint outranks history,
    the customer would get the brochure for the model they moved off.
    """
    del monkeypatch
    processor, deps = _processor()
    deps["engine"].reply = "Great choice."
    processor.process(_event(message_id="m1", content="I want King EV MAX"))
    deps["engine"].reply = "Sure, noted."
    processor.process(
        _event(message_id="m2", content="actually I want King Deluxe instead")
    )

    session = deps["state"].sessions["+918286871533"]
    product, _ = processor._resolve_brochure_product(session, "send me the brochure")
    assert product == "King Deluxe"


def test_romanized_hindi_info_request_offers_and_sends_brochure(monkeypatch):
    """Real transcript: 'muje aur jankari chaiye' (Romanized Hindi) never
    matched PRODUCT_INFO_ASK_RE (Devanagari/English only), so the
    deterministic offer never armed — the LLM was left to freelance and,
    on a later "ha", claimed to send a brochure it never actually sent
    (brochures_sent stayed empty, no send in the logs). The classifier is
    LLM-backed now; the fast regex path is bypassed here via monkeypatch
    to keep the test deterministic and offline, but the soft-signal gate
    (jankari/jaankari) that routes to the classifier is exercised for real.
    """
    monkeypatch.setattr(
        "client_processing.classify_product_info_request",
        lambda msg: "jankari" in (msg or "").lower(),
    )
    processor, deps = _processor(preselect_language="Hindi")
    deps["engine"].reply = "बढ़िया चुनाव — King EV MAX."
    processor.process(_event(message_id="m1", content="TVS King EV max"))

    deps["engine"].reply = "इसमें 179 km की रेंज मिलती है।"
    processor.process(_event(message_id="m2", content="muje aur jankari chaiye"))

    reply_text = deps["reply_sender"].calls[-1]["text"]
    assert "brochure" in reply_text.lower() or "ब्रोशर" in reply_text
    session = deps["state"].sessions["+918286871533"]
    assert session.awaiting_brochure_offer is True
    assert deps["reply_sender"].document_calls == []  # not sent yet, only offered

    deps["engine"].reply = "ठीक है।"
    processor.process(_event(message_id="m3", content="ha"))

    links = [call["link"] for call in deps["reply_sender"].document_calls]
    assert links == ["https://1.jamoutsourcing.com/f/King_EV_MAX-English.pdf"]
    assert session.brochures_sent == ["King EV MAX"]


def test_brochure_offer_declined_does_not_send(monkeypatch):
    del monkeypatch
    processor, deps = _processor()
    deps["engine"].reply = "Great choice — King EV MAX. When are you looking to buy?"
    processor.process(_event(message_id="m1", content="King EV MAX"))
    deps["engine"].reply = "It has a 100km range."
    processor.process(
        _event(message_id="m2", content="What are the features of this?")
    )

    deps["engine"].reply = "No problem, when are you looking to buy?"
    processor.process(_event(message_id="m3", content="no"))

    assert deps["reply_sender"].document_calls == []
    session = deps["state"].sessions["+918286871533"]
    assert session.awaiting_brochure_offer is False
    enriched = deps["engine"].turns[-1].message
    assert "did not want the brochure" in enriched


def test_brochure_offer_ambiguous_reply_passes_through_unchanged(monkeypatch):
    """Neither yes nor no just continues qualification normally — no loop,
    no forced interpretation, matching the still-interested classifier's
    "don't force a rigid gate" principle."""
    monkeypatch.setattr(
        "client_processing.classify_brochure_offer_reply",
        lambda _msg: "unclear",
    )
    processor, deps = _processor()
    deps["engine"].reply = "Great choice — King EV MAX. When are you looking to buy?"
    processor.process(_event(message_id="m1", content="King EV MAX"))
    deps["engine"].reply = "It has a 100km range."
    processor.process(
        _event(message_id="m2", content="What are the features of this?")
    )

    deps["engine"].reply = "Sure, when are you looking to buy?"
    processor.process(_event(message_id="m3", content="ok noted"))

    assert deps["reply_sender"].document_calls == []
    session = deps["state"].sessions["+918286871533"]
    assert session.awaiting_brochure_offer is False
    enriched = deps["engine"].turns[-1].message
    assert enriched == "ok noted"


def test_brochure_offer_llm_accept_in_any_language_sends_pack(monkeypatch):
    """Ambiguous any-language accept is classified by LLM → PDF sent."""
    monkeypatch.setattr(
        "client_processing.classify_brochure_offer_reply",
        lambda _msg: "yes",
    )
    processor, deps = _processor()
    deps["engine"].reply = "Great choice — King EV MAX."
    processor.process(_event(message_id="m1", content="King EV MAX"))
    deps["engine"].reply = "It has a 100km range."
    processor.process(
        _event(message_id="m2", content="What are the features of this?")
    )

    deps["engine"].reply = "Sending now."
    processor.process(
        _event(message_id="m3", content="हो नक्की पाठवा ना")
    )

    links = [call["link"] for call in deps["reply_sender"].document_calls]
    assert "https://1.jamoutsourcing.com/f/King_EV_MAX-English.pdf" in links


def test_brochure_not_sent_without_product(monkeypatch):
    monkeypatch.setattr(
        "client_media_assets.media_base_url",
        lambda: "https://example.com/media",
    )
    processor, deps = _processor()
    processor.process(_event(message_id="m1", content="Hi"))
    processor.process(_event(message_id="m2", content="Yes"))
    assert deps["reply_sender"].document_calls == []


def test_engine_profile_product_without_request_does_not_send_brochure(monkeypatch):
    """Even once the engine captures product_interest, wait for an explicit ask."""
    del monkeypatch
    processor, deps = _processor()
    deps["engine"].reply = "EV MAX is a good fit."
    deps["engine"].profile = {"product_interest": "King EV MAX"}

    processor.process(_event(message_id="m1", content="मुझे इलेक्ट्रिक वाली चाहिए"))

    assert deps["reply_sender"].document_calls == []


def test_engine_profile_product_sends_brochure_when_requested(monkeypatch):
    del monkeypatch
    processor, deps = _processor()
    deps["engine"].reply = "EV MAX is a good fit."
    deps["engine"].profile = {"product_interest": "King EV MAX"}

    processor.process(_event(message_id="m1", content="मुझे ब्रोशर भेजो"))

    links = [call["link"] for call in deps["reply_sender"].document_calls]
    assert links == [
        "https://1.jamoutsourcing.com/f/King_EV_MAX-English.pdf",
    ]


def test_crm_product_enquired_without_request_does_not_send_brochure(monkeypatch):
    """CRM already knows the product, but a plain "Hi" is not an explicit ask."""
    del monkeypatch
    processor, deps = _processor()
    deps["directory"].customer = Customer(
        "1",
        "Asha",
        "Marathi",
        product_enquired="TVS KING EV MAX",
    )

    processor.process(_event(message_id="m1", content="Hi"))

    assert deps["reply_sender"].document_calls == []


def test_crm_product_enquired_sends_brochure_when_requested(monkeypatch):
    del monkeypatch
    processor, deps = _processor()
    deps["directory"].customer = Customer(
        "1",
        "Asha",
        "Marathi",
        product_enquired="TVS KING EV MAX",
    )

    processor.process(_event(message_id="m1", content="Send me the brochure"))

    links = [call["link"] for call in deps["reply_sender"].document_calls]
    assert links == [
        "https://1.jamoutsourcing.com/f/King_EV_MAX-English.pdf",
    ]


def test_marathi_product_name_without_request_does_not_send_brochure(monkeypatch):
    del monkeypatch
    processor, deps = _processor()
    deps["engine"].reply = "छान निवड!"

    processor.process(_event(message_id="m1", content="मला ईव्ही मॅक्स पाहिजे"))

    assert deps["reply_sender"].document_calls == []


def test_marathi_explicit_brochure_request_sends_pdf(monkeypatch):
    del monkeypatch
    processor, deps = _processor()
    deps["engine"].reply = "छान निवड!"

    processor.process(
        _event(message_id="m1", content="मला ईव्ही मॅक्सचा ब्रोशर पाठवा")
    )

    links = [call["link"] for call in deps["reply_sender"].document_calls]
    assert links == [
        "https://1.jamoutsourcing.com/f/King_EV_MAX-English.pdf",
    ]


def test_bare_dont_know_reply_sends_share_location_image(monkeypatch):
    """After the bot asks for a pincode, "nahi pata" should get the how-to image."""
    monkeypatch.setattr(
        "client_media_assets.media_base_url",
        lambda: "https://example.com/media",
    )
    processor, deps = _processor()
    deps["engine"].reply = "Please share your current location."

    processor.process(_event(message_id="m1", content="nahi pata"))

    assert deps["engine"].turns == []  # static path — no LLM duplicate ask
    assert deps["reply_sender"].image_calls
    image = deps["reply_sender"].image_calls[0]
    assert image["link"].endswith("/share_location/how_to.jpg")
    assert image["caption"] == ""  # text reply carries the ask once
    assert "6-digit pincode" in deps["reply_sender"].calls[-1]["text"]
    assert deps["state"].sessions["+918286871533"].share_location_guide_sent is True


def test_invalid_pincode_asks_once_then_offers_location(monkeypatch):
    monkeypatch.setattr(
        "client_media_assets.media_base_url",
        lambda: "https://example.com/media",
    )
    monkeypatch.setattr(
        "client_processing.classify_location_reply",
        lambda _msg, _last="": "bad_pincode",
    )
    processor, deps = _processor()

    processor.process(_event(message_id="m1", content="41100"))
    assert deps["engine"].turns == []
    assert not deps["reply_sender"].image_calls
    first = deps["reply_sender"].calls[-1]["text"]
    assert "valid 6-digit pincode" in first.lower()
    assert deps["state"].sessions["+918286871533"].invalid_pincode_attempts == 1

    processor.process(_event(message_id="m2", content="4110011"))
    assert deps["reply_sender"].image_calls
    assert deps["reply_sender"].image_calls[0]["caption"] == ""
    second = deps["reply_sender"].calls[-1]["text"]
    assert "location" in second.lower()
    assert "6-digit" in second.lower()
    # One text + one image — not a duplicated caption+text pair
    assert len(deps["reply_sender"].calls) == 2
    assert len(deps["reply_sender"].image_calls) == 1


def test_share_location_image_retries_on_transient_failure(monkeypatch):
    monkeypatch.setattr(
        "client_media_assets.media_base_url",
        lambda: "https://example.com/media",
    )

    class FlakyImageSender(FakeReplySender):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        def send_image(self, *, mobile: str, link: str, caption: str = "") -> None:
            self.attempts += 1
            if self.attempts < 2:
                raise RuntimeError("transient send failure")
            super().send_image(mobile=mobile, link=link, caption=caption)

    sender = FlakyImageSender()
    processor, deps = _processor(reply_sender=sender, sleep=lambda _s: None)

    processor.process(_event(message_id="m1", content="nahi pata"))

    assert sender.attempts == 2
    assert deps["state"].sessions["+918286871533"].share_location_guide_sent is True
    assert sender.image_calls


def test_unsupported_crm_language_prompts_for_language_choice():
    directory = FakeDirectory()
    directory.customer = Customer("crm-1", "Asha", "Unsupported")
    processor, deps = _processor(directory=directory, preselect_language=None)

    processor.process(_event(content="Hello"))

    assert deps["engine"].turns == []
    assert "Which language do you prefer?" in deps["reply_sender"].calls[0]["text"]


def test_missing_language_menu_then_choice_starts_qualification():
    directory = FakeDirectory()
    directory.customer = Customer("crm-1", "Asha", "")
    processor, deps = _processor(directory=directory, preselect_language=None)

    processor.process(_event(message_id="incoming-1", content="hi"))
    processor.process(_event(message_id="incoming-2", content="2"))  # Hindi
    processor.process(_event(message_id="incoming-3", content="1"))  # vehicle

    assert "Which language do you prefer?" in deps["reply_sender"].calls[0]["text"]
    assert deps["reply_sender"].calls[1]["text"] == flow_intent_ask("Hindi")
    assert deps["engine"].turns[0].language == "Hindi"
    assert "selected Hindi" in deps["engine"].turns[0].message


def test_crm_preferred_language_still_shows_menu_on_fresh_session():
    """After the idle TTL / new session, always ask language even if CRM has one."""
    directory = FakeDirectory()
    directory.customer = Customer("crm-1", "Asha", "Tamil")
    processor, deps = _processor(directory=directory, preselect_language=None)

    processor.process(_event(content="Hello"))

    assert deps["engine"].turns == []
    assert "Which language do you prefer?" in deps["reply_sender"].calls[0]["text"]
    assert deps["state"].sessions["+918286871533"].awaiting_language_selection is True


def test_returning_customer_chooses_language_then_gets_welcome_back():
    """Fresh session: language menu first, then static still-interested in chosen lang."""
    directory = FakeDirectory()
    directory.customer = Customer(
        "crm-1",
        "Asha",
        "Tamil",
        product_enquired="TVS KING EV MAX",
        last_remark="Interested in EV MAX",
        last_status="Interested",
    )
    processor, deps = _processor(directory=directory, preselect_language=None)

    processor.process(_event(message_id="m1", content="Hi"))
    assert "Which language do you prefer?" in deps["reply_sender"].calls[0]["text"]

    # Language chosen — still-interested must fire (do not skip).
    session = deps["state"].sessions["+918286871533"]
    session.welcome_back_sent = False
    session.still_interested_asked = False
    deps["state"].save(session)

    processor.process(_event(message_id="m2", content="1"))  # English
    assert deps["reply_sender"].calls[-1]["text"] == flow_intent_ask("English")
    processor.process(_event(message_id="m3", content="1"))  # vehicle
    assert deps["engine"].turns == []  # static ask, not LLM
    ask = deps["reply_sender"].calls[-1]["text"]
    assert ask.startswith("Asha.")
    assert "King EV MAX" in ask
    assert "still planning to purchase" in ask.lower()
    assert "Press 1 for Yes" in ask
    assert "Press 2 for No" in ask
    session = deps["state"].sessions["+918286871533"]
    assert session.awaiting_still_interested is True
    assert session.language == "English"


def test_unknown_crm_name_reply_is_captured_before_wrap_up():
    """Name must reach dispose.customername even before PROFILE_JSON wrap-up."""
    dispose = FakeDisposeClient()
    dealer = Dealer(
        dealer_code="11689",
        name="Shah Auto",
        address="Pune",
        pincode="411048",
        phone="9000000001",
        map_url="https://maps.example/11689",
        latitude=18.52,
        longitude=73.85,
    )
    processor, deps = _processor(
        dispose_client=dispose,
        dealer_directory=FakeDealerDirectory(dealer),
    )
    deps["directory"].customer = Customer(
        "unknown-918459522206",
        "Customer 8459522206",
        "",
    )

    # Language menu → Marathi
    processor.process(_event(message_id="n1", content="Hi"))
    deps["engine"].reply = "नमस्ते! तुमचे नाव सांगू शकाल का?"
    processor.process(_event(message_id="n2", content="3"))

    # Name reply (no PROFILE_JSON yet)
    deps["engine"].reply = "धन्यवाद!"
    deps["engine"].profile = None
    processor.process(_event(message_id="n3", content="राहुल पाटील"))
    assert (
        deps["state"].sessions["+918286871533"].lead_profile["lead_name"]
        == "राहुल पाटील"
    )

    # Later pincode should dispose with customername
    deps["engine"].reply = "Noted."
    deps["engine"].profile = {"product_interest": "King EV MAX"}
    processor.process(_event(message_id="n4", content="411057"))
    assert dispose.calls
    assert dispose.calls[-1].get("customername") == "राहुल पाटील"


def test_unknown_crm_customer_dispose_sends_customername():
    dispose = FakeDisposeClient()
    dealer = Dealer(
        dealer_code="11689",
        name="Shah Auto",
        address="Pune",
        pincode="411048",
        phone="9000000001",
        map_url="https://maps.example/11689",
        latitude=18.52,
        longitude=73.85,
    )
    processor, deps = _processor(
        dispose_client=dispose,
        dealer_directory=FakeDealerDirectory(dealer),
    )
    deps["directory"].customer = Customer(
        "unknown-918459522206",
        "Customer 8459522206",
        "English",
    )
    deps["engine"].reply = "Thanks Ravi."
    deps["engine"].profile = {
        "lead_name": "Ravi Kumar",
        "product_interest": "King Deluxe",
        "purchase_timeline": "15/08/2026",
        "pincode": "411001",
    }

    processor.process(_event(message_id="u1", content="My name is Ravi Kumar"))

    assert dispose.calls
    assert dispose.calls[-1]["customername"] == "Ravi Kumar"


def test_empty_crm_language_shows_menu_even_when_state_known():
    directory = FakeDirectory()
    directory.customer = Customer(
        "crm-1",
        "Asha",
        "",
        state="Maharashtra",
    )
    processor, deps = _processor(directory=directory, preselect_language=None)

    processor.process(_event(content="Hello"))

    assert deps["engine"].turns == []
    assert "Which language do you prefer?" in deps["reply_sender"].calls[0]["text"]


def test_audio_is_transcribed_before_engine_turn():
    processor, deps = _processor()

    processor.process(
        _event(
            type="audio",
            content=None,
            media_url="https://client.example/audio.mp3",
            mime_type="audio/mpeg",
        )
    )

    assert deps["engine"].turns[0].message.startswith("मला ईव्ही मॅक्स पाहिजे")


def test_document_is_added_to_lead_and_continues_conversation():
    processor, deps = _processor()

    processor.process(
        _event(
            type="image",
            content=None,
            media_url="https://client.example/licence.jpg",
            mime_type="image/jpeg",
        )
    )

    assert deps["lead_store"].documents == [
        {
            "session": "client-1533-1",
            "document_types": ["driving_licence"],
            "url": "https://client.example/licence.jpg",
            "status": "recognized",
        }
    ]
    assert "driving_licence" in deps["engine"].turns[0].message


def test_unknown_document_asks_for_clearer_image_without_calling_engine():
    recognizer = FakeDocumentRecognizer(DocumentRecognition(["unknown"], "unknown"))
    processor, deps = _processor(document_recognizer=recognizer)

    processor.process(
        _event(
            type="image",
            content=None,
            media_url="https://client.example/blur.jpg",
            mime_type="image/jpeg",
        )
    )

    assert deps["engine"].turns == []
    assert "clearer" in deps["reply_sender"].calls[0]["text"].lower()
    assert deps["lead_store"].documents[0]["status"] == "unknown"


def test_repeated_unclear_documents_are_flagged_for_review():
    recognizer = FakeDocumentRecognizer(DocumentRecognition(["unknown"], "unknown"))
    processor, deps = _processor(document_recognizer=recognizer)
    event = _event(
        type="image",
        content=None,
        media_url="https://client.example/blur.jpg",
        mime_type="image/jpeg",
    )

    processor.process(event)
    processor.process({**event, "message_id": "incoming-2"})

    assert deps["interaction_store"].exchanges[-1]["needs_review"] is True


def test_non_document_image_explains_supported_use():
    recognizer = FakeDocumentRecognizer(DocumentRecognition([], "not_document"))
    processor, deps = _processor(document_recognizer=recognizer)

    processor.process(
        _event(
            type="image",
            content=None,
            media_url="https://client.example/vehicle.jpg",
            mime_type="image/jpeg",
        )
    )

    assert deps["engine"].turns == []
    assert "document" in deps["reply_sender"].calls[0]["text"].lower()


def test_customer_lookup_failure_sends_fallback_and_flags_review():
    processor, deps = _processor(directory=FailingDirectory())

    processor.process(_event())

    assert deps["engine"].turns == []
    assert "temporarily unavailable" in deps["reply_sender"].calls[0]["text"].lower()
    assert deps["interaction_store"].exchanges[0]["needs_review"] is True


def test_bad_media_asks_customer_to_resend():
    processor, deps = _processor(media_fetcher=FailingMediaFetcher())

    processor.process(
        _event(
            type="audio",
            content=None,
            media_url="https://client.example/audio.mp3",
            mime_type="audio/mpeg",
        )
    )

    assert deps["engine"].turns == []
    assert "resend" in deps["reply_sender"].calls[0]["text"].lower()


def test_callback_retry_reuses_pending_reply_without_regenerating():
    sender = FailOnceReplySender()
    processor, deps = _processor(reply_sender=sender)
    event = _event()

    with pytest.raises(RuntimeError, match="callback unavailable"):
        processor.process(event)
    processor.process(event)

    assert len(deps["engine"].turns) == 1
    assert sender.calls[0]["text"] == sender.calls[1]["text"]


def test_pincode_message_asks_nearest_dealer_confirm_once():
    dealer = Dealer(
        dealer_code="11689",
        name="Shah Auto",
        address="Pune, Maharashtra, 411048",
        pincode="411048",
        phone="9000000001",
        map_url="https://www.google.com/maps?q=18.52,73.85",
        latitude=18.52,
        longitude=73.85,
        spoc_name="Ravi",
        distance_km=2.5,
    )
    directory = FakeDealerDirectory(dealer)
    processor, deps = _processor(dealer_directory=directory)
    deps["engine"].reply = "Thanks, we noted your pincode."

    processor.process(_event(content="My pincode is 411001"))

    # Details are never volunteered — a pincode gets a consent question,
    # and no name/address/phone until the customer says yes.
    first = deps["reply_sender"].calls[0]["text"]
    assert dealer_share_ask("English") in first
    assert "Shah Auto" not in first
    assert "9000000001" not in first
    session = deps["state"].sessions["+918286871533"]
    assert session.awaiting_dealer_share_consent is True
    assert session.awaiting_dealer_confirm is False
    # ...but the lead is already routed to that dealer for dispose.
    assert session.last_dealer_code == "11689"

    processor.process(_event(message_id="incoming-2", content="yes please"))

    card = deps["reply_sender"].calls[1]["text"]
    assert "Name: Shah Auto" in card
    assert "Address: Pune, Maharashtra, 411048" in card
    assert "Reply Yes or No" in card
    assert session.awaiting_dealer_confirm is True
    assert session.dealer_confirmed is False

    processor.process(
        _event(message_id="incoming-3", content="Still around 411001 area")
    )

    # An unclear follow-up isn't nagged with the card again — it's deferred
    # to a single ask at wrap-up instead.
    third = deps["reply_sender"].calls[2]["text"]
    assert "Name: Shah Auto" not in third
    assert directory.calls == ["411001"]
    assert session.dealer_shared_for_pincode == "411001"
    assert session.awaiting_dealer_confirm is False
    assert session.dealer_confirm_deferred is True


def test_new_customer_dealer_ask_survives_deferred_turns():
    """Real transcript (unknown/new number, Hindi): customer gives pincode
    161226, but the engine's next two replies each end in their own
    question ("do you know the features?", "do you have a licence?"), so
    the dealer consent ask gets deferred both times. Before the fix, the
    resolved dealer was dropped the instant the first turn was deferred —
    the pincode never reappears in a later message, so nothing could ever
    retry it, and the customer reached wrap-up with no dealer ask at all.
    """

    class ScriptedEngine:
        def __init__(self, replies):
            self.replies = list(replies)
            self.turns = []
            self.profile = None

        def handle_turn(self, turn):
            self.turns.append(turn)
            return TurnOutput(
                reply_text=self.replies.pop(0),
                profile=self.profile,
                captured=bool(self.profile),
            )

    dealer = Dealer(
        dealer_code="99001",
        name="Test TVS Dealership",
        address="Sirsa Road, 161226",
        pincode="161226",
        phone="9000000002",
        map_url="https://maps.example/99001",
        latitude=29.9,
        longitude=75.8,
        spoc_name="Ramesh",
    )
    directory = FakeDealerDirectory(dealer)
    engine = ScriptedEngine(
        [
            "पिनकोड 161226 के लिए धन्यवाद! क्या आप फीचर्स के बारे में जानते हैं?",
            "ठीक है! फीचर्स ये हैं... क्या आपके पास लाइसेंस उपलब्ध है?",
            "बहुत बढ़िया! हमने आपकी जानकारी दर्ज कर ली है, डीलरशिप जल्द संपर्क करेगी।",
        ]
    )
    processor, deps = _processor(
        dealer_directory=directory, engine=engine, preselect_language="Hindi"
    )
    deps["directory"].customer = Customer(
        customer_id="unknown-8286871533",
        name="Customer 8286871533",
        preferred_language="Hindi",
    )

    processor.process(_event(message_id="m1", content="161226"))
    processor.process(_event(message_id="m2", content="nahi"))
    processor.process(_event(message_id="m3", content="hai"))

    replies = [call["text"] for call in deps["reply_sender"].calls]
    assert any(dealer_share_ask("Hindi") in text for text in replies), (
        "dealer consent ask was never sent — new customer got no dealer "
        f"info after sharing a pincode: {replies}"
    )
    session = deps["state"].sessions["+918286871533"]
    assert session.awaiting_dealer_share_consent is True
    assert session.pending_nearest_dealer_code == ""


def test_dealership_details_are_never_sent_without_consent():
    """The 02/08 transcript: 'I want a different vehicle' came back with
    'which model?' AND an unrequested dealer card AND 'is this OK?'."""
    dealer = Dealer(
        dealer_code="11689",
        name="Rhythm Auto",
        address="Hinjewadi Road, 411057",
        pincode="411057",
        phone="9021853812",
        map_url="https://maps.example/11689",
        latitude=18.60,
        longitude=73.73,
        spoc_name="Neha Pagar",
    )
    processor, deps = _processor(dealer_directory=FakeDealerDirectory(dealer))
    deps["directory"].customer = Customer(
        "crm-1", "Asha", "English", dealership_id="11689", dealership_name="Rhythm Auto"
    )
    deps["engine"].reply = "We also have King Deluxe and King Duramax Plus."

    processor.process(_event(message_id="m1", content="hi"))
    processor.process(_event(message_id="m2", content="I want a different vehicle"))

    for call in deps["reply_sender"].calls:
        assert "9021853812" not in call["text"], "phone number sent unrequested"
        assert "Hinjewadi Road" not in call["text"], "address sent unrequested"
        assert call["text"].count("?") <= 1, f"two questions:\n{call['text']}"


def test_consent_question_is_not_stacked_on_the_models_own_question():
    """Belt and braces: even if the model ignores the do-not-ask
    instruction, nothing may append a second question to its reply."""
    dealer = Dealer(
        dealer_code="11689",
        name="Rhythm Auto",
        address="Hinjewadi",
        pincode="411057",
        phone="9021853812",
        map_url="https://maps.example/11689",
        latitude=18.60,
        longitude=73.73,
    )
    processor, deps = _processor(dealer_directory=FakeDealerDirectory(dealer))
    deps["directory"].customer = Customer(
        "crm-1", "Asha", "English", dealership_id="11689", dealership_name="Rhythm Auto"
    )
    # Disobedient model: asks a question no matter what it is told.
    deps["engine"].acknowledgement = "Which model would you like?"
    deps["engine"].reply = "Which model would you like?"

    processor.process(_event(message_id="m1", content="hi"))
    processor.process(_event(message_id="m2", content="I want a different vehicle"))

    for call in deps["reply_sender"].calls:
        assert call["text"].count("?") <= 1, f"two questions:\n{call['text']}"
    session = deps["state"].sessions["+918286871533"]
    assert session.awaiting_dealer_share_consent is False


def test_real_dealer_directory_with_fake_geocoder_resolves_pune():
    dealers = [
        {
            "dealer_code": "11689",
            "name": "Shah Auto",
            "address": "Pune",
            "pincode": "411048",
            "phone": "9000000001",
            "map_url": "https://maps.example/11689",
            "latitude": 18.5204,
            "longitude": 73.8567,
        },
        {
            "dealer_code": "10824",
            "name": "Kanchana Motors",
            "address": "Mangalore",
            "pincode": "575006",
            "phone": "7353767891",
            "map_url": "https://maps.example/10824",
            "latitude": 12.8708,
            "longitude": 74.8819,
        },
    ]

    class _Geo:
        def geocode(self, pincode: str):
            return {"411001": (18.53, 73.85)}.get(pincode)

    directory = DealerDirectory(dealers, geocoder=_Geo())
    processor, deps = _processor(dealer_directory=directory)
    deps["engine"].reply = "Got it."

    processor.process(_event(content="411001"))

    assert dealer_share_ask("English") in deps["reply_sender"].calls[0]["text"]
    processor.process(_event(message_id="incoming-2", content="yes"))
    assert "Shah Auto" in deps["reply_sender"].calls[1]["text"]


def test_pincode_triggers_dispose_even_when_llm_asks_a_question():
    """Option A: pin must sync to JAM even if dealer consent is deferred."""
    dispose = FakeDisposeClient()
    dealer = Dealer(
        dealer_code="11689",
        name="Shah Auto",
        address="Pune",
        pincode="411048",
        phone="9000000001",
        map_url="https://maps.example/11689",
        latitude=18.52,
        longitude=73.85,
    )
    processor, deps = _processor(
        dispose_client=dispose,
        dealer_directory=FakeDealerDirectory(dealer),
    )
    session = deps["state"].sessions["+918286871533"]
    session.lead_profile = {
        "lead_name": "Vijay Dhaware",
        "purchase_timeline": "20/08/2026",
        "preferred_language": "English",
    }
    deps["state"].save(session)
    # Disobedient model: asks a question even when told not to → consent deferred.
    deps["engine"].acknowledgement = (
        "Do you already know the key features of the TVS King Deluxe?"
    )
    deps["engine"].reply = (
        "Do you already know the key features of the TVS King Deluxe?"
    )

    processor.process(_event(message_id="pin-1", content="400102"))

    session = deps["state"].sessions["+918286871533"]
    assert session.lead_profile.get("pincode") == "400102"
    assert dispose.calls, "dispose must fire as soon as pincode is known"
    assert dispose.calls[0]["pincode"] == "400102"
    assert dispose.calls[0]["status"] == "not_enquired"
    assert dispose.calls[0]["customername"] == "Vijay Dhaware"
    # Dealer consent must not stack onto the model's own question.
    assert dealer_share_ask("English") not in deps["reply_sender"].calls[0]["text"]


def test_wrap_up_profile_calls_dispose_once_with_dealer_code():
    dispose = FakeDisposeClient()
    dealer = Dealer(
        dealer_code="11689",
        name="Shah Auto",
        address="Pune",
        pincode="411048",
        phone="9000000001",
        map_url="https://maps.example/11689",
        latitude=18.52,
        longitude=73.85,
    )
    processor, deps = _processor(
        dispose_client=dispose,
        dealer_directory=FakeDealerDirectory(dealer),
    )
    deps["engine"].profile = {
        "product_interest": "King Deluxe",
        "purchase_timeline": "next month",
        "notes": "qualified on WhatsApp",
    }
    deps["engine"].reply = "Thanks, dealer will contact you."

    processor.process(_event(message_id="incoming-1", content="My pincode is 411001"))
    processor.process(_event(message_id="incoming-2", content="ok"))

    # Same lead snapshot twice → only one dispose (no duplicate spam)
    assert len(dispose.calls) == 1
    assert dispose.calls[0]["status"] == "interested"
    assert dispose.calls[0]["pincode"] == "411001"
    assert dispose.calls[0]["dealer_code"] == "11689"
    assert dispose.calls[0]["product_name"] == "King Deluxe"
    assert "preferred_language: English" in dispose.calls[0]["remark"]
    assert deps["state"].sessions["+918286871533"].dispose_sent is True


def test_dispose_re_fires_when_lead_fields_change():
    dispose = FakeDisposeClient()
    dealer = Dealer(
        dealer_code="11689",
        name="Shah Auto",
        address="Pune",
        pincode="411048",
        phone="9000000001",
        map_url="https://maps.example/11689",
        latitude=18.52,
        longitude=73.85,
    )
    processor, deps = _processor(
        dispose_client=dispose,
        dealer_directory=FakeDealerDirectory(dealer),
    )
    deps["directory"].customer = Customer(
        "1",
        "Asha",
        "English",
        product_enquired="TVS KING PASSENGER DELUXE",
    )
    deps["engine"].profile = {
        "product_interest": "King Deluxe",
        "purchase_timeline": "15/08/2026",
    }
    deps["engine"].reply = "Noted."

    processor.process(_event(message_id="d1", content="My pincode is 411001"))
    assert len(dispose.calls) == 1
    assert dispose.calls[0]["dealer_code"] == "11689"
    assert dispose.calls[0]["pincode"] == "411001"

    deps["engine"].reply = "Thanks for confirming."
    # First Yes releases the details, second Yes confirms the dealership.
    processor.process(_event(message_id="d1b", content="Yes"))
    processor.process(_event(message_id="d1c", content="Yes"))
    assert deps["state"].sessions["+918286871533"].dealer_confirmed is True

    deps["engine"].profile = {
        "product_interest": "King Deluxe",
        "purchase_timeline": "20/09/2026",
        "notes": "changed date",
    }
    processor.process(_event(message_id="d2", content="actually 20/09/2026"))
    assert len(dispose.calls) == 2
    assert dispose.calls[1]["expected_purchased_date"] == "20/09/2026"


def test_typed_date_survives_llm_unknown_timeline():
    dispose = FakeDisposeClient()
    dealer = Dealer(
        dealer_code="11689",
        name="Shah Auto",
        address="Pune",
        pincode="411048",
        phone="9000000001",
        map_url="https://maps.example/11689",
        latitude=18.52,
        longitude=73.85,
    )
    processor, deps = _processor(
        dispose_client=dispose,
        dealer_directory=FakeDealerDirectory(dealer),
    )
    deps["engine"].reply = "Noted."
    deps["engine"].profile = {
        "product_interest": "King Deluxe",
        "purchase_timeline": "12-12-26",
        "pincode": "411001",
    }

    processor.process(_event(message_id="d1", content="12-12-26"))
    assert dispose.calls
    assert dispose.calls[-1]["expected_purchased_date"] == "12/12/2026"

    # A later turn where the LLM says "unknown" must not clobber the real date.
    deps["engine"].profile = {
        "product_interest": "King Deluxe",
        "purchase_timeline": "unknown",
        "notes": "wrap up",
        "pincode": "411001",
    }
    processor.process(_event(message_id="d2", content="Ok"))
    assert dispose.calls[-1]["expected_purchased_date"] == "12/12/2026"
    session = deps["state"].sessions["+918286871533"]
    stored = resolve_purchase_date(session.lead_profile["purchase_timeline"])
    assert stored.value == "12/12/2026"


def test_location_sets_dealer_and_syncs_dispose():
    dispose = FakeDisposeClient()
    nearest = Dealer(
        dealer_code="11689",
        name="Shah Auto",
        address="Pune",
        pincode="411048",
        phone="9000000001",
        map_url="https://maps.example/11689",
        latitude=18.52,
        longitude=73.85,
    )
    processor, deps = _processor(
        dispose_client=dispose,
        dealer_directory=FakeDealerDirectory(nearest),
    )
    deps["directory"].customer = Customer(
        "1",
        "Asha",
        "English",
        product_enquired="TVS KING EV MAX",
    )

    processor.process(
        _event(
            message_id="loc-d1",
            type="location",
            content="18.52,73.85",
            latitude=18.52,
            longitude=73.85,
        )
    )

    assert deps["engine"].turns == []
    assert len(dispose.calls) == 1
    assert dispose.calls[0]["dealer_code"] == "11689"
    assert dispose.calls[0]["pincode"] == "411048"
    assert dispose.calls[0]["product_name"] == "King EV MAX"


def test_crm_dealer_confirm_yes_sets_last_dealer_code_and_skips_nearest():
    crm_dealer = Dealer(
        dealer_code="11982",
        name="Sarthak Auto",
        address="Chinchwad, Pune, 411019",
        pincode="411019",
        phone="9623457273",
        map_url="https://maps.example/11982",
        latitude=18.65,
        longitude=73.81,
        spoc_name="Ashwini",
    )
    nearest = Dealer(
        dealer_code="11689",
        name="Shah Auto",
        address="Pune",
        pincode="411048",
        phone="9000000001",
        map_url="https://maps.example/11689",
        latitude=18.52,
        longitude=73.85,
    )
    directory = FakeDealerDirectory(nearest, by_code={"11982": crm_dealer})
    processor, deps = _processor(dealer_directory=directory)
    deps["directory"].customer = Customer(
        "307569",
        "Ajit",
        "Marathi",
        product_enquired="TVS KING PASSENGER DELUXE",
        dealership_id="11982",
        dealership_name="Sarthak Auto",
        city="Pune",
        state="MAHARASHTRA",
    )
    deps["engine"].reply = "Please share your pincode."

    processor.process(_event(message_id="m1", content="I live at pin 41 10 35"))
    session = deps["state"].sessions["+918286871533"]
    # Details are consent-gated: ask first, card only after a yes.
    assert session.awaiting_dealer_share_consent is True
    assert "Sarthak Auto" not in deps["reply_sender"].calls[0]["text"]
    # The lead is routed to the CRM dealer regardless, for dispose.
    assert session.last_dealer_code == "11982"

    processor.process(_event(message_id="m1b", content="हो, दाखवा"))
    session = deps["state"].sessions["+918286871533"]
    assert session.awaiting_dealer_confirm is True
    reply0 = deps["reply_sender"].calls[1]["text"]
    assert "Sarthak Auto" in reply0
    assert "Chinchwad" in reply0
    # Marathi CRM preferred language → localized dealer card.
    assert "नाव:" in reply0 or "Name:" in reply0
    assert "पत्ता:" in reply0 or "Address:" in reply0
    assert "होय किंवा नाही" in reply0 or "Reply Yes or No" in reply0
    assert directory.calls == []  # nearest not used yet

    deps["engine"].reply = "Great, continuing."
    processor.process(_event(message_id="m2", content="होय"))
    session = deps["state"].sessions["+918286871533"]
    assert session.dealer_confirmed is True
    assert session.last_dealer_code == "11982"
    assert directory.calls == []


def test_dealer_confirm_natural_phrasing_resolves_via_classifier(monkeypatch):
    """Regression for the reported bug: "ha ye dealrshime mere pass hai"
    (Hinglish "yes, I have this dealership") doesn't match the strict
    single-word _is_affirmative regex, so it used to re-attach the same
    dealer card forever instead of resolving as a confirmation."""
    from bot.graph import DealerConfirmClassification

    class _FakeYesLLM:
        def with_structured_output(self, schema):
            return self

        def invoke(self, prompt):
            return DealerConfirmClassification(result="yes")

    monkeypatch.setattr("bot.graph.get_llm", lambda tier="smart": _FakeYesLLM())

    crm_dealer = Dealer(
        dealer_code="15188",
        name="A G Malwade Wheels",
        address="Vapi, Valsad",
        pincode="396191",
        phone="9213008340",
        map_url="https://maps.example/15188",
        latitude=18.41,
        longitude=76.54,
    )
    directory = FakeDealerDirectory(None, by_code={"15188": crm_dealer})
    processor, deps = _processor(dealer_directory=directory)
    deps["directory"].customer = Customer(
        "1",
        "Asha",
        "Hindi",
        dealership_id="15188",
        dealership_name="A G Malwade Wheels",
    )
    deps["engine"].reply = "Please share your pincode."
    processor.process(_event(message_id="m1", content="431401"))
    session = deps["state"].sessions["+918286871533"]
    assert session.awaiting_dealer_share_consent is True
    processor.process(_event(message_id="m1b", content="yes"))
    session = deps["state"].sessions["+918286871533"]
    assert session.awaiting_dealer_confirm is True

    deps["engine"].reply = "Great, continuing."
    processor.process(
        _event(message_id="m2", content="ha ye dealrshime mere pass hai")
    )

    session = deps["state"].sessions["+918286871533"]
    assert session.dealer_confirmed is True
    assert session.awaiting_dealer_confirm is False
    # Doesn't loop — the dealer card isn't re-attached to this reply.
    last_reply = deps["reply_sender"].calls[-1]["text"]
    assert "A G Malwade" not in last_reply


def test_city_name_redirects_to_pincode_or_location_only(monkeypatch):
    monkeypatch.setattr(
        "client_media_assets.media_base_url",
        lambda: "https://example.com/media",
    )
    monkeypatch.setattr(
        "client_processing.classify_location_reply",
        lambda _msg, _last="": "place_name",
    )
    directory = FakeDealerDirectory(
        Dealer(
            dealer_code="11689",
            name="Shah Auto",
            address="Pune",
            pincode="411048",
            phone="9000000001",
            map_url="https://maps.example/11689",
            latitude=18.52,
            longitude=73.85,
        )
    )
    processor, deps = _processor(dealer_directory=directory)
    deps["engine"].reply = "should not be used"

    processor.process(_event(message_id="m1", content="Parbhani"))

    assert deps["engine"].turns == []
    assert directory.place_calls == []
    reply = deps["reply_sender"].calls[-1]["text"]
    assert "6-digit pincode" in reply
    assert "current WhatsApp location" in reply
    assert "city/area" in reply.lower() or "do not use city" in reply.lower()
    assert "Jagdamba" not in reply
    assert "Shah Auto" not in reply
    assert deps["reply_sender"].image_calls
    assert deps["state"].sessions["+918286871533"].awaiting_dealer_confirm is False


def test_unknown_pincode_sends_share_location_how_to_image(monkeypatch):
    monkeypatch.setattr(
        "client_media_assets.media_base_url",
        lambda: "https://example.com/media",
    )
    processor, deps = _processor()
    deps["engine"].reply = "Please share your current location."

    processor.process(_event(message_id="m1", content="I don't know my pincode"))

    assert deps["engine"].turns == []
    assert deps["reply_sender"].image_calls
    image = deps["reply_sender"].image_calls[0]
    assert image["link"].endswith("/share_location/how_to.jpg")
    assert image["caption"] == ""
    assert "location" in deps["reply_sender"].calls[-1]["text"].lower()
    assert deps["state"].sessions["+918286871533"].share_location_guide_sent is True


def test_crm_dealer_name_without_id_resolves_address_from_directory():
    """CRM often sends only the dealership name; resolve the card by name."""
    dealer = Dealer(
        dealer_code="15140",
        name="Gk Motors",
        address="Bangalore, Karnataka",
        pincode="560001",
        phone="9000000005",
        map_url="https://maps.example/15140",
        latitude=12.97,
        longitude=77.59,
    )

    class NameDirectory(FakeDealerDirectory):
        def get_by_name(self, name: str) -> Dealer | None:
            return dealer if name.lower() == "gk motors" else None

    directory = NameDirectory(None)
    processor, deps = _processor(dealer_directory=directory)
    deps["directory"].customer = Customer(
        "1",
        "Asha",
        "English",
        dealership_name="Gk Motors",
    )

    # Dealer-confirm never stacks onto the very first reply — warm up first.
    processor.process(_event(message_id="m0", content="Hi"))
    processor.process(_event(message_id="m1", content="King EV MAX"))
    assert dealer_share_ask("English") in deps["reply_sender"].calls[-1]["text"]
    processor.process(_event(message_id="m1b", content="yes"))

    reply = deps["reply_sender"].calls[-1]["text"]
    assert "Name: Gk Motors" in reply
    assert "Bangalore, Karnataka" in reply
    session = deps["state"].sessions["+918286871533"]
    assert session.last_dealer_code == "15140"


def test_unclear_reply_during_dealer_confirm_answers_without_reattaching_card():
    directory = FakeDealerDirectory(None)
    processor, deps = _processor(dealer_directory=directory)
    deps["directory"].customer = Customer(
        "1",
        "Asha",
        "English",
        dealership_id="11982",
        dealership_name="Sarthak Auto",
        city="Pune",
    )
    # Dealer-confirm never stacks onto the very first reply — warm up first.
    processor.process(_event(message_id="m0", content="Hi"))
    processor.process(_event(message_id="m1", content="King EV MAX"))
    processor.process(_event(message_id="m1b", content="yes"))
    assert deps["state"].sessions["+918286871533"].awaiting_dealer_confirm

    deps["engine"].reply = "The dealership will share downpayment details."
    processor.process(_event(message_id="m2", content="What is the downpayment?"))

    reply = deps["reply_sender"].calls[-1]["text"]
    # The question is answered plainly — no card nagged back onto the reply.
    assert reply.strip() == "The dealership will share downpayment details."
    session = deps["state"].sessions["+918286871533"]
    assert session.awaiting_dealer_confirm is False
    assert session.dealer_confirm_deferred is True

    # Conversation keeps flowing normally; the card stays gone on later turns too.
    deps["engine"].reply = "Sure, I can help with that."
    processor.process(_event(message_id="m3", content="What documents do I need?"))
    reply = deps["reply_sender"].calls[-1]["text"]
    assert reply.strip() == "Sure, I can help with that."
    session = deps["state"].sessions["+918286871533"]
    assert session.awaiting_dealer_confirm is False
    assert session.dealer_confirm_deferred is True


def test_wrap_up_nudges_deferred_dealer_confirm_once():
    directory = FakeDealerDirectory(None)
    processor, deps = _processor(dealer_directory=directory)
    deps["directory"].customer = Customer(
        "1",
        "Asha",
        "English",
        dealership_id="11982",
        dealership_name="Sarthak Auto",
        city="Pune",
    )
    processor.process(_event(message_id="m0", content="Hi"))
    processor.process(_event(message_id="m1", content="King EV MAX"))
    processor.process(_event(message_id="m1b", content="yes"))
    deps["engine"].reply = "Noted, thanks."
    processor.process(_event(message_id="m2", content="What is the downpayment?"))
    session = deps["state"].sessions["+918286871533"]
    assert session.dealer_confirm_deferred is True
    assert session.awaiting_dealer_confirm is False

    deps["engine"].reply = "Thanks for your time!"
    deps["engine"].profile = {"product_interest": "King EV MAX"}
    processor.process(_event(message_id="m3", content="Ok bye"))

    reply = deps["reply_sender"].calls[-1]["text"]
    assert reply.startswith("Thanks for your time!")
    assert "one more thing" in reply
    assert "Reply Yes or No" in reply
    session = deps["state"].sessions["+918286871533"]
    assert session.dealer_confirm_deferred is False
    assert session.awaiting_dealer_confirm is True


def test_wrap_up_dealer_confirm_nudge_resolves_on_yes():
    directory = FakeDealerDirectory(None)
    processor, deps = _processor(dealer_directory=directory)
    deps["directory"].customer = Customer(
        "1",
        "Asha",
        "English",
        dealership_id="11982",
        dealership_name="Sarthak Auto",
        city="Pune",
    )
    processor.process(_event(message_id="m0", content="Hi"))
    processor.process(_event(message_id="m1", content="King EV MAX"))
    processor.process(_event(message_id="m1b", content="yes"))
    deps["engine"].reply = "Noted, thanks."
    processor.process(_event(message_id="m2", content="What is the downpayment?"))
    deps["engine"].reply = "Thanks for your time!"
    deps["engine"].profile = {"product_interest": "King EV MAX"}
    processor.process(_event(message_id="m3", content="Ok bye"))
    assert deps["state"].sessions["+918286871533"].awaiting_dealer_confirm is True

    deps["engine"].profile = None
    deps["engine"].reply = "Great, thank you!"
    processor.process(_event(message_id="m4", content="Yes"))

    session = deps["state"].sessions["+918286871533"]
    assert session.dealer_confirmed is True
    assert session.awaiting_dealer_confirm is False


def test_pincode_during_dealer_confirm_redoes_nearest_lookup():
    nearest = Dealer(
        dealer_code="11689",
        name="Shah Auto",
        address="Pune",
        pincode="411048",
        phone="9000000001",
        map_url="https://maps.example/11689",
        latitude=18.52,
        longitude=73.85,
    )
    directory = FakeDealerDirectory(nearest)
    processor, deps = _processor(dealer_directory=directory)
    deps["directory"].customer = Customer(
        "1",
        "Asha",
        "English",
        dealership_id="11982",
        dealership_name="Sarthak Auto",
        city="Pune",
    )
    # Dealer-confirm never stacks onto the very first reply — warm up first.
    processor.process(_event(message_id="m0", content="Hi"))
    processor.process(_event(message_id="m1", content="King EV MAX"))
    processor.process(_event(message_id="m1b", content="yes"))
    assert deps["state"].sessions["+918286871533"].awaiting_dealer_confirm

    deps["engine"].reply = "Let me check."
    processor.process(_event(message_id="m2", content="411048"))

    assert directory.calls == ["411048"]
    # The new pincode drops the pending dealer and re-asks consent.
    assert dealer_share_ask("English") in deps["reply_sender"].calls[-1]["text"]
    processor.process(_event(message_id="m3", content="yes"))

    reply = deps["reply_sender"].calls[-1]["text"]
    assert "Shah Auto" in reply
    session = deps["state"].sessions["+918286871533"]
    assert session.last_dealer_code == "11689"
    assert session.awaiting_dealer_confirm is True


def test_crm_dealer_confirm_no_then_nearest_from_spaced_pincode():
    nearest = Dealer(
        dealer_code="11689",
        name="Shah Auto",
        address="Pune",
        pincode="411048",
        phone="9000000001",
        map_url="https://maps.example/11689",
        latitude=18.52,
        longitude=73.85,
    )
    directory = FakeDealerDirectory(nearest)
    processor, deps = _processor(dealer_directory=directory)
    deps["directory"].customer = Customer(
        "1",
        "Asha",
        "Marathi",
        dealership_id="11982",
        dealership_name="Sarthak Auto",
        city="Pune",
    )
    deps["engine"].reply = "Share your area pin please."

    # Dealer-confirm never stacks onto the very first reply — warm up first.
    processor.process(_event(message_id="m0", content="hello"))
    processor.process(_event(message_id="m1", content="King EV MAX"))
    processor.process(_event(message_id="m1b", content="हो"))
    assert deps["state"].sessions["+918286871533"].awaiting_dealer_confirm

    deps["engine"].reply = "Please share pincode."
    processor.process(_event(message_id="m2", content="नाही"))
    assert deps["state"].sessions["+918286871533"].dealer_confirmed is False
    assert deps["reply_sender"].image_calls
    image = deps["reply_sender"].image_calls[0]
    assert image["link"].endswith("/share_location/how_to.jpg")
    assert image["caption"] == ""
    no_reply = deps["reply_sender"].calls[-1]["text"]
    assert "location" in no_reply.lower() or "लोकेशन" in no_reply
    # Dealer-no uses static ask — engine should not run an extra turn for "नाही"
    # (2 turns so far: the m0 warm-up and m1's "King EV MAX", nothing for m2).
    assert len(deps["engine"].turns) == 2

    deps["engine"].reply = "Noted."
    processor.process(_event(message_id="m3", content="41 10 35"))
    assert directory.calls == ["411035"]
    assert dealer_share_ask("English") in deps["reply_sender"].calls[-1]["text"]
    processor.process(_event(message_id="m4", content="हो"))
    assert "Shah Auto" in deps["reply_sender"].calls[-1]["text"]
    assert deps["state"].sessions["+918286871533"].last_dealer_code == "11689"


def test_product_hint_passed_to_engine_from_crm_product_enquired():
    processor, deps = _processor()
    deps["directory"].customer = Customer(
        "1",
        "Asha",
        "English",
        product_enquired="TVS KING EV MAX",
    )
    processor.process(_event(content="Hi"))
    assert deps["engine"].turns[0].product_hint == "King EV MAX"


def test_call_me_disposes_interested_with_callback_using_crm_fields():
    dispose = FakeDisposeClient()
    processor, deps = _processor(dispose_client=dispose)
    deps["directory"].customer = Customer(
        "307569",
        "Ajit",
        "Marathi",
        product_enquired="TVS KING PASSENGER DELUXE",
        dealership_id="11982",
        dealership_name="Sarthak Auto",
        city="Pune",
    )
    deps["engine"].reply = "ठीक आहे, डीलरशिप लवकरच कॉल करेल."
    # JAM dispose v1.1 requires pincode on every call
    session = deps["state"].load_or_start("+918286871533")
    session.dealer_shared_for_pincode = "411019"
    deps["state"].save(session)

    processor.process(_event(content="Please call me"))

    assert len(dispose.calls) == 1
    assert dispose.calls[0]["status"] == "interested"
    assert dispose.calls[0]["pincode"] == "411019"
    assert dispose.calls[0]["dealer_code"] == "11982"
    assert dispose.calls[0]["product_name"] == "King Deluxe"
    assert "callback" in dispose.calls[0]["remark"].lower()
    assert deps["state"].sessions["+918286871533"].dispose_sent is True
    assert "call them soon" in deps["engine"].turns[0].message.lower()


def test_dealer_confirm_not_stacked_on_organic_second_reply():
    """Regression: a customer with a CRM-assigned dealer but no known
    product doesn't get the static still-interested gate (it needs a known
    product) — instead _maybe_welcome_back seeds LLM context and the model
    generates its own natural greeting/question as the first REAL engine
    reply. The customer's answer to THAT triggers a second engine reply,
    which is where the dealer-confirm card used to silently stack onto
    whatever the model asked next. The system message enrichment must
    suppress the model's own question on that second turn instead."""
    processor, deps = _processor(
        preselect_language="Marathi",
        skip_still_interested=False,
    )
    deps["directory"].customer = Customer(
        "1",
        "Neha",
        "Marathi",
        dealership_id="11982",
        dealership_name="Rhythm Auto",
    )
    deps["engine"].reply = "छान! तुम्ही अजूनही स्वारस्य दाखवत आहात का?"

    processor.process(_event(message_id="m1", content="Hi"))
    first_reply = deps["reply_sender"].calls[-1]["text"]
    assert "Rhythm Auto" not in first_reply  # not stacked on the first reply
    assert deps["state"].sessions["+918286871533"].awaiting_dealer_confirm is False
    assert "Do NOT ask any question" not in deps["engine"].turns[-1].message

    deps["engine"].reply = "उत्तम! तुम्हाला कोणत्या मॉडेलमध्ये स्वारस्य आहे?"
    processor.process(_event(message_id="m2", content="होय"))

    # The model was told not to ask its own question this turn...
    assert "Do NOT ask any question" in deps["engine"].turns[-1].message
    # ...and the dealer-confirm ask is the one question actually sent.
    second_reply = deps["reply_sender"].calls[-1]["text"]
    processor.process(_event(message_id="m2b", content="yes"))
    second_reply = deps["reply_sender"].calls[-1]["text"]
    assert "Rhythm Auto" in second_reply
    assert deps["state"].sessions["+918286871533"].awaiting_dealer_confirm is True


def test_welcome_back_uses_crm_remarks_on_fresh_session():
    processor, deps = _processor(
        preselect_language="English",
        skip_still_interested=False,
    )
    deps["directory"].customer = Customer(
        "1",
        "Asha",
        "English",
        product_enquired="TVS KING EV MAX",
        last_remark="Interested in EV MAX, asked price",
        last_status="Interested",
    )

    processor.process(_event(content="Hi"))

    ask = deps["reply_sender"].calls[-1]["text"]
    assert "Asha." in ask
    assert "King EV MAX" in ask
    assert "still planning to purchase" in ask.lower()
    assert "Press 1 for Yes" in ask
    assert deps["engine"].turns == []
    assert deps["state"].sessions["+918286871533"].awaiting_still_interested is True
    assert deps["state"].sessions["+918286871533"].welcome_back_sent is True


def test_still_interested_yes_continues_qualification():
    processor, deps = _processor(
        preselect_language="Hindi",
        skip_still_interested=False,
    )
    deps["directory"].customer = Customer(
        "1",
        "Asha",
        "Hindi",
        product_enquired="King Deluxe",
        last_status="Interested",
    )
    deps["engine"].reply = "आगे बढ़ते हैं।"

    processor.process(_event(message_id="m1", content="Hi"))
    ask = deps["reply_sender"].calls[-1]["text"]
    assert "Asha." in ask
    assert "King Deluxe" in ask
    assert "1 दबाएँ" in ask or "1" in ask

    processor.process(_event(message_id="m2", content="1"))
    assert deps["engine"].turns
    assert "still interested" in deps["engine"].turns[0].message.lower()
    assert deps["state"].sessions["+918286871533"].awaiting_still_interested is False
    # Regression: "1" here means "yes" (still-interested's own numbered
    # prompt), not "switch to English" (1 = English in the language menu).
    assert deps["state"].sessions["+918286871533"].language == "Hindi"


def test_still_interested_digit_reply_does_not_flip_language_choice():
    """Reported bug: fresh customer picks Marathi via the language menu
    ("3"), confirms still-interested with "1" (its own "Press 1 for Yes"),
    and the reply comes back in English — because bare "1" also means
    "English" in the language menu's own numbering."""
    processor, deps = _processor(preselect_language=None, skip_still_interested=False)
    deps["directory"].customer = Customer(
        "lead-9876543210",
        "Ravi Kumar",
        "",
        product_enquired="King Deluxe",
        last_status="No Response",
    )
    deps["engine"].reply = "पुढे चालू ठेवूया."

    processor.process(_event(message_id="m1", content="Hi"))  # language menu
    processor.process(_event(message_id="m2", content="3"))  # picks Marathi
    session = deps["state"].sessions["+918286871533"]
    assert session.language == "Marathi"
    assert session.awaiting_flow_intent is True

    # Same digit trap one step earlier: "1" here means "vehicle", not English.
    processor.process(_event(message_id="m3", content="1"))  # vehicle flow
    session = deps["state"].sessions["+918286871533"]
    assert session.language == "Marathi"
    assert session.awaiting_still_interested is True

    processor.process(_event(message_id="m4", content="1"))  # "yes" to still-interested
    session = deps["state"].sessions["+918286871533"]
    assert session.language == "Marathi"
    assert session.awaiting_still_interested is False


def test_still_interested_accepts_free_text_no():
    dispose = FakeDisposeClient()
    processor, deps = _processor(
        preselect_language="English",
        skip_still_interested=False,
        dispose_client=dispose,
    )
    deps["directory"].customer = Customer(
        "1",
        "Asha",
        "English",
        product_enquired="King EV MAX",
        last_status="Interested",
    )
    session = deps["state"].load_or_start("+918286871533")
    session.dealer_shared_for_pincode = "411001"
    deps["state"].save(session)

    processor.process(_event(message_id="m1", content="Hi"))
    processor.process(
        _event(message_id="m2", content="no i dont want to buy this vehicle")
    )

    thanks = deps["reply_sender"].calls[-1]["text"]
    assert "Thank you" in thanks
    assert dispose.calls[-1]["status"] == "not_interested"


def test_still_interested_no_thanks_in_selected_language():
    dispose = FakeDisposeClient()
    processor, deps = _processor(
        preselect_language="Marathi",
        skip_still_interested=False,
        dispose_client=dispose,
    )
    deps["directory"].customer = Customer(
        "1",
        "Asha",
        "Marathi",
        product_enquired="King EV MAX",
        last_status="Interested",
    )
    session = deps["state"].load_or_start("+918286871533")
    session.dealer_shared_for_pincode = "411001"
    deps["state"].save(session)

    processor.process(_event(message_id="m1", content="Hi"))
    processor.process(_event(message_id="m2", content="2"))

    thanks = deps["reply_sender"].calls[-1]["text"]
    assert "धन्यवाद" in thanks
    assert deps["engine"].turns == []
    assert deps["state"].sessions["+918286871533"].awaiting_still_interested is False
    assert dispose.calls
    assert dispose.calls[-1]["status"] == "not_interested"


class _FakeClassifierLLM:
    """Stands in for bot.llm.get_llm("fast") in the still-interested classifier."""

    def __init__(self, declining: bool):
        self._declining = declining

    def with_structured_output(self, schema):
        return self

    def invoke(self, prompt: str):
        from bot.graph import StillInterestedClassification

        return StillInterestedClassification(declining=self._declining)


def test_still_interested_ambiguous_reply_proceeds_to_qualification(monkeypatch):
    """Neither yes nor no ("not sure, tell me about the Duramax") should hand
    off to qualification instead of re-asking the same static question."""
    monkeypatch.setattr(
        "bot.graph.get_llm", lambda tier="smart": _FakeClassifierLLM(declining=False)
    )
    processor, deps = _processor(preselect_language="English", skip_still_interested=False)
    deps["directory"].customer = Customer(
        "1",
        "Asha",
        "English",
        product_enquired="King EV MAX",
        last_status="Interested",
    )
    deps["engine"].reply = "Sure, here's a bit about the Duramax Plus."

    processor.process(_event(message_id="m1", content="Hi"))
    processor.process(
        _event(message_id="m2", content="not sure, tell me about the Duramax")
    )

    assert deps["engine"].turns
    message = deps["engine"].turns[-1].message
    assert "not confirmed" in message.lower()
    assert "did not decline" in message.lower()
    assert deps["state"].sessions["+918286871533"].awaiting_still_interested is False
    assert deps["state"].sessions["+918286871533"].lead_profile.get("disposition") != "not_interested"


def test_still_interested_ambiguous_reply_llm_classifies_as_declining(monkeypatch):
    """A loosely-phrased decline the regex would miss should still close the lead."""
    monkeypatch.setattr(
        "bot.graph.get_llm", lambda tier="smart": _FakeClassifierLLM(declining=True)
    )
    dispose = FakeDisposeClient()
    processor, deps = _processor(
        preselect_language="English",
        skip_still_interested=False,
        dispose_client=dispose,
    )
    deps["directory"].customer = Customer(
        "1",
        "Asha",
        "English",
        product_enquired="King EV MAX",
        last_status="Interested",
    )
    session = deps["state"].load_or_start("+918286871533")
    session.dealer_shared_for_pincode = "411001"
    deps["state"].save(session)

    processor.process(_event(message_id="m1", content="Hi"))
    processor.process(
        _event(message_id="m2", content="nah, already got a different bike")
    )

    thanks = deps["reply_sender"].calls[-1]["text"]
    assert "Thank you" in thanks
    assert deps["engine"].turns == []
    assert deps["state"].sessions["+918286871533"].awaiting_still_interested is False
    assert dispose.calls
    assert dispose.calls[-1]["status"] == "not_interested"


def test_first_message_context_includes_preferred_language_without_remarks():
    processor, deps = _processor(preselect_language="Marathi")
    deps["directory"].customer = Customer(
        "1",
        "Asha",
        "Marathi",
        last_status="No Response",
    )
    deps["engine"].reply = "नमस्कार!"

    processor.process(_event(content="Hi"))

    turn_message = deps["engine"].turns[0].message
    assert "preferred language: Marathi" in turn_message
    assert deps["state"].sessions["+918286871533"].welcome_back_sent is True


def test_location_event_sets_nearest_dealer_without_llm():
    nearest = Dealer(
        dealer_code="11689",
        name="Shah Auto",
        address="Pune",
        pincode="411048",
        phone="9000000001",
        map_url="https://maps.example/11689",
        latitude=18.52,
        longitude=73.85,
    )
    directory = FakeDealerDirectory(nearest)
    processor, deps = _processor(dealer_directory=directory)

    processor.process(
        _event(
            message_id="loc-1",
            type="location",
            content="",
            latitude=18.5204,
            longitude=73.8567,
        )
    )

    assert deps["engine"].turns == []
    assert directory.coord_calls == [(18.5204, 73.8567)]
    session = deps["state"].sessions["+918286871533"]
    # Routed for dispose, but the contact card still needs a yes: a shared
    # pin says WHERE they are, not that they want a phone number.
    assert session.last_dealer_code == "11689"
    assert session.awaiting_dealer_share_consent is True
    assert session.awaiting_dealer_confirm is False
    assert "9000000001" not in deps["reply_sender"].calls[-1]["text"]

    processor.process(_event(message_id="loc-2", content="yes"))
    session = deps["state"].sessions["+918286871533"]
    assert session.dealer_confirmed is False
    assert session.awaiting_dealer_confirm is True
    assert "Shah Auto" in deps["reply_sender"].calls[-1]["text"]
    reply = deps["reply_sender"].calls[-1]["text"]
    assert "Name: Shah Auto" in reply
    assert "Address:" in reply
    assert "Reply Yes or No" in reply


def test_location_event_without_coords_asks_for_pincode():
    processor, deps = _processor(dealer_directory=FakeDealerDirectory(None))

    processor.process(
        _event(message_id="loc-2", type="location", content="")
    )

    assert deps["engine"].turns == []
    assert "pincode" in deps["reply_sender"].calls[-1]["text"].lower()


# --- vehicle-or-nearest-PGM routing after the language menu -----------------


def _fresh_new_lead(**overrides):
    """A number not in CRM, walked to the routing ask in Marathi."""
    directory = FakeDirectory()
    directory.customer = Customer("unknown-1", "Customer 1", "")
    processor, deps = _processor(
        directory=directory, preselect_language=None, **overrides
    )
    processor.process(_event(message_id="m1", content="Hi"))
    processor.process(_event(message_id="m2", content="3"))  # Marathi
    return processor, deps


def test_language_choice_is_followed_by_routing_ask_in_that_language():
    processor, deps = _fresh_new_lead()

    session = deps["state"].sessions["+918286871533"]
    assert session.language == "Marathi"
    assert session.awaiting_flow_intent is True
    assert session.flow == ""
    assert deps["reply_sender"].calls[-1]["text"] == flow_intent_ask("Marathi")
    assert "PGM" in deps["reply_sender"].calls[-1]["text"]
    # Deterministic: no engine turn, and menu exchanges stay out of history.
    assert deps["engine"].turns == []
    assert session.history == []


def test_vehicle_choice_continues_into_qualification():
    processor, deps = _fresh_new_lead()

    processor.process(_event(message_id="m3", content="1"))

    session = deps["state"].sessions["+918286871533"]
    assert session.awaiting_flow_intent is False
    assert session.flow == "vehicle"
    assert session.language == "Marathi"  # bare "1" did not flip to English
    turn = deps["engine"].turns[0]
    assert turn.language == "Marathi"
    assert "selected Marathi" in turn.message
    assert "NOT in CRM" in turn.message  # unknown number: ask the name first


def test_pgm_choice_enters_pgm_flow_without_the_engine(monkeypatch):
    monkeypatch.setattr(
        "client_processing.share_location_image_url",
        lambda language: "https://media.example.com/share.png",
    )
    processor, deps = _fresh_new_lead()

    processor.process(_event(message_id="m3", content="2"))

    session = deps["state"].sessions["+918286871533"]
    assert session.awaiting_flow_intent is False
    assert session.flow == "pgm"
    assert deps["engine"].turns == []
    reply = deps["reply_sender"].calls[-1]["text"]
    assert "PGM" in reply
    assert "पिनकोड" in reply  # Marathi location ask follows the intro
    # The how-to image goes with it, caption-less so the ask is not doubled.
    assert deps["reply_sender"].image_calls[-1]["caption"] == ""
    assert session.history[-1]["text"] == reply


def test_unclear_routing_reply_is_asked_again():
    processor, deps = _fresh_new_lead()

    processor.process(_event(message_id="m3", content="hello?"))

    session = deps["state"].sessions["+918286871533"]
    assert session.awaiting_flow_intent is True
    assert session.flow == ""
    assert deps["reply_sender"].calls[-1]["text"] == flow_intent_ask("Marathi")
    assert deps["engine"].turns == []


def test_location_pin_while_routing_ask_pending_is_re_asked_not_looked_up():
    """A shared pin is not an answer to 'vehicle or PGM?', and must not start
    the dealer lookup that belongs to the vehicle flow."""
    directory = FakeDealerDirectory(
        Dealer(
            dealer_code="11689",
            name="Shah Auto",
            address="Pune",
            pincode="411048",
            phone="9000000001",
            map_url="https://maps.example/11689",
            latitude=18.52,
            longitude=73.85,
        )
    )
    processor, deps = _fresh_new_lead(dealer_directory=directory)

    processor.process(
        _event(message_id="m3", type="location", content="",
               latitude=18.52, longitude=73.85)
    )

    assert directory.coord_calls == []
    assert deps["reply_sender"].calls[-1]["text"] == flow_intent_ask("Marathi")
    assert deps["state"].sessions["+918286871533"].awaiting_flow_intent is True


def test_pgm_flow_turns_stay_deterministic():
    """Once in the PGM flow, later turns never reach the LLM or the
    still-interested ask; a pincode is captured and acknowledged."""
    directory = FakeDirectory()
    directory.customer = Customer(
        "crm-1", "Asha", "", product_enquired="King EV MAX", last_status="Interested"
    )
    processor, deps = _processor(
        directory=directory, preselect_language=None, skip_still_interested=False
    )
    processor.process(_event(message_id="m1", content="Hi"))
    processor.process(_event(message_id="m2", content="1"))  # English
    processor.process(_event(message_id="m3", content="2"))  # PGM

    processor.process(_event(message_id="m4", content="what now"))
    assert "pincode" in deps["reply_sender"].calls[-1]["text"].lower()

    processor.process(_event(message_id="m5", content="411001"))
    session = deps["state"].sessions["+918286871533"]
    assert session.lead_profile["pincode"] == "411001"
    assert "Thanks for sharing your location" in deps["reply_sender"].calls[-1]["text"]

    assert deps["engine"].turns == []
    assert session.awaiting_still_interested is False
    assert session.flow == "pgm"


def test_returning_customer_vehicle_choice_then_still_interested():
    """The routing ask sits before still-interested, not instead of it."""
    directory = FakeDirectory()
    directory.customer = Customer(
        "crm-1", "Asha", "", product_enquired="King EV MAX", last_status="Interested"
    )
    processor, deps = _processor(
        directory=directory, preselect_language=None, skip_still_interested=False
    )
    processor.process(_event(message_id="m1", content="Hi"))
    processor.process(_event(message_id="m2", content="2"))  # Hindi
    assert deps["reply_sender"].calls[-1]["text"] == flow_intent_ask("Hindi")

    processor.process(_event(message_id="m3", content="1"))  # vehicle

    ask = deps["reply_sender"].calls[-1]["text"]
    assert "King EV MAX" in ask
    assert "1 दबाएँ" in ask
    session = deps["state"].sessions["+918286871533"]
    assert session.flow == "vehicle"
    assert session.awaiting_still_interested is True
    assert session.language == "Hindi"
    assert deps["engine"].turns == []


def test_routing_ask_survives_a_redis_round_trip():
    """Flags are hand-listed in RedisClientState; a missing one would reset
    the routing mid-conversation and re-ask forever."""
    from dataclasses import fields

    names = {f.name for f in fields(ClientSession)}
    assert {"awaiting_flow_intent", "flow"} <= names

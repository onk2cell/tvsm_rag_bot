"""Failing repros for the TVSM chatbot bug sheet (01-08 round).

Each test encodes the behaviour the bug sheet asks for. They are expected to
FAIL against the current code — that is the proof the bug is still live.
Delete nothing here when fixing; make them pass.

The still-failing ones are marked ``xfail(strict=True)`` so the suite is green
and CI can gate on it. Strict is the point: the moment a bug is actually fixed
the test XPASSes and the build FAILS, telling you to drop the marker. The
marker records a live bug; it never hides one.
"""
from __future__ import annotations

import pytest

from client_static_messages import (
    dealer_confirm_ask,
    place_redirect_message,
    share_location_ask,
)
from dealers import Dealer

from tests.test_client_processing import (
    FakeDealerDirectory,
    _event,
    _processor,
)


DEALER = Dealer(
    dealer_code="D1",
    name="Arc Andheri",
    address="Oshiwara, Jogeshwari",
    pincode="400064",
    phone="9152216478",
    map_url="https://maps.example/1",
    latitude=19.15,
    longitude=72.83,
    spoc_name="Anjali Mishra",
    distance_km=4.2,
)


# --- 010801: one question per message ------------------------------------


class CompliantEngine:
    """Stands in for a model that follows the prompt: when the system says a
    dealer card will be attached, it acknowledges without asking anything."""

    SUPPRESS = "Do NOT ask any question of your own"

    def __init__(self):
        self.turns = []
        self.reply = "Thanks! When are you planning to purchase?"
        self.profile = None

    def handle_turn(self, turn):
        from conversation_engine import TurnOutput

        self.turns.append(turn)
        reply = "Thanks!" if self.SUPPRESS in (turn.message or "") else self.reply
        return TurnOutput(
            reply_text=reply, profile=self.profile, captured=bool(self.profile)
        )


def test_010801_pincode_reply_does_not_stack_two_questions():
    """Sheet 010801 + BOT Behaviour #3/#6: after a pincode the customer got
    the campaign blurb, a purchase-date question AND the dealer card's own
    Yes/No question in one bubble. The guard existed for the CRM-dealer path
    but not for the pincode path."""
    processor, deps = _processor(
        dealer_directory=FakeDealerDirectory(DEALER),
        engine=CompliantEngine(),
    )

    processor.process(_event(message_id="m1", content="110001"))

    # The model must be told to stay quiet before anything is appended...
    assert CompliantEngine.SUPPRESS in deps["engine"].turns[-1].message
    # ...and the delivered message must carry exactly one question.
    sent = deps["reply_sender"].calls[-1]["text"]
    assert sent.count("?") <= 1, f"two questions stacked:\n{sent}"

    # Details are consent-gated, so the card arrives on the next turn —
    # still as the single question of that message.
    processor.process(_event(message_id="m2", content="yes"))
    card = deps["reply_sender"].calls[-1]["text"]
    assert "Arc Andheri" in card
    assert card.count("?") <= 1, f"two questions stacked:\n{card}"


# --- 010802 / 230701: language switch spoken in a voice note --------------


class EnglishRequestTranscriber:
    def transcribe(self, data: bytes, mime_type: str, language: str) -> str:
        return "I want to speak in English"


def test_010802_free_form_switch_request_reaches_the_classifier():
    """The old gate needed the WHOLE message to parse as a language name and
    be under 24 chars, so a real sentence was silently ignored."""
    from bot.graph import _route_language_switch

    def route(message: str) -> str:
        return _route_language_switch({"user_message": message, "language": ""})

    assert route("I want to speak in English") == "classify"
    assert route("can you please speak in english") == "classify"
    # Menu-style answers stay deterministic — no call needed.
    assert route("2") == "explicit"
    assert route("english") == "explicit"
    assert route("tell me the price") == "none"


def test_010802_audio_language_switch_is_applied(monkeypatch):
    """Sheet 010802/230701: customer asks in a voice note to switch to
    English; the bot obliges once then reverts, because the transcript never
    reaches the language switcher."""
    monkeypatch.setattr(
        "client_processing.classify_language_switch", lambda _msg: "English"
    )
    processor, deps = _processor(
        preselect_language="Marathi",
        transcriber=EnglishRequestTranscriber(),
    )

    processor.process(
        _event(
            message_id="m1",
            type="audio",
            content="",
            media_url="https://media.example/a.ogg",
        )
    )

    session = deps["state"].sessions["+918286871533"]
    assert session.language == "English"


# --- 010803: chat filler misread as a city name ---------------------------


@pytest.mark.parametrize(
    "filler", ["okk", "thik hai", "haa", "hmm", "sahi", "achha", "theek", "done"]
)
def test_010803_chat_filler_is_never_decided_by_regex(filler):
    """Sheet 010803: 'okk' after wrap-up triggered the share-location card
    because the place-name blocklist only matched whole words ('ok'), so
    every unlisted token became a city. Nothing may resolve these without
    the LLM seeing what the bot actually asked."""
    from bot.graph import _route_location_reply

    assert (
        _route_location_reply(
            {"user_message": filler, "last_bot_message": "", "result": "other"}
        )
        == "classify"
    )


def test_010803_classifier_failure_never_hijacks_the_turn(monkeypatch):
    """Safe default: if the classifier errors, the turn continues as normal
    conversation instead of falling back to a canned location reply."""
    from bot import graph

    monkeypatch.setattr(
        graph, "get_llm", lambda _tier: (_ for _ in ()).throw(RuntimeError("no key"))
    )
    assert graph.classify_location_reply("okk", "Thanks for your time!") == "other"


def test_010803_okk_does_not_trigger_location_card(monkeypatch):
    monkeypatch.setattr(
        "client_processing.classify_location_reply",
        lambda _msg, _last="": "other",
    )
    processor, deps = _processor()
    deps["engine"].reply = "Thanks!"

    processor.process(_event(message_id="m1", content="okk"))

    assert deps["reply_sender"].image_calls == []
    sent = deps["reply_sender"].calls[-1]["text"]
    assert sent != place_redirect_message("English")
    assert sent != share_location_ask("English")


def test_010803_budget_number_is_not_treated_as_a_bad_pincode(monkeypatch):
    """'50000' after a price question used to get 'You entered an invalid
    PIN code' because the gate ran step-blind on any 3-5 digit number."""
    monkeypatch.setattr(
        "client_processing.classify_location_reply",
        lambda _msg, _last="": "other",
    )
    processor, deps = _processor()
    deps["engine"].reply = "The dealership will share exact figures."

    processor.process(_event(message_id="m1", content="50000"))

    sent = deps["reply_sender"].calls[-1]["text"]
    assert "PIN code" not in sent, sent


# --- 010804: brochure request sends the whole pack -----------------------


def test_010804_brochure_request_sends_only_the_brochure():
    """Sheet 010804 + BOT Behaviour #2/#7: 'Yes send brochure' delivered the
    brochure, the PMS schedule and the warranty policy."""
    processor, deps = _processor()
    deps["engine"].reply = "Sure, sending the King Duramax Plus brochure."

    processor.process(
        _event(message_id="m1", content="send me the King Duramax Plus brochure")
    )

    kinds = [call["caption"] for call in deps["reply_sender"].document_calls]
    assert len(deps["reply_sender"].document_calls) == 1, kinds


# --- 010805: promises a brochure it never sends --------------------------


def test_010805_repeat_brochure_request_is_not_promised_twice():
    """Sheet 010805: the bot said 'I'm sending you the brochure' over and
    over. Once a product is in brochures_sent the send is skipped, but the
    LLM is still told to say it is sending — so it promises forever."""
    processor, deps = _processor()
    deps["engine"].reply = "Sending it now."
    processor.process(_event(message_id="m1", content="send King EV MAX brochure"))
    first_sends = len(deps["reply_sender"].document_calls)
    assert first_sends >= 1

    processor.process(_event(message_id="m2", content="send brochure"))

    resent = len(deps["reply_sender"].document_calls) > first_sends
    told_to_promise = "will send the document" in deps["engine"].turns[-1].message
    assert not (told_to_promise and not resent), (
        "LLM told to claim it is sending, but nothing was sent:\n"
        f"{deps['engine'].turns[-1].message}"
    )


# --- 240711: silent drop on "ok" -----------------------------------------


def test_240711_ok_always_gets_a_reply():
    """Sheet 240711: customer typed 'ok' and got nothing back; they had to
    send 'hello' to restart. Empty model replies are dropped silently."""
    processor, deps = _processor()
    deps["engine"].reply = ""

    processor.process(_event(message_id="m1", content="ok"))

    assert deps["reply_sender"].calls, "bot sent nothing at all"


# --- 230707: English strings inside a non-English chat -------------------


@pytest.mark.parametrize("language", ["Telugu", "Tamil", "Kannada", "Malayalam"])
@pytest.mark.xfail(
    strict=True,
    reason="bug 230707 live: static tables cover English/Hindi/Marathi only",
)
def test_230707_static_messages_are_translated(language):
    """Sheet 230707: half-English messages. Every static table only covers
    English/Hindi/Marathi and silently falls back to English for the other
    four languages offered in the 1-7 menu."""
    assert place_redirect_message(language) != place_redirect_message("English")
    assert share_location_ask(language) != share_location_ask("English")


@pytest.mark.xfail(
    strict=True,
    reason="bug 230707 live: media-error string is hardcoded English inline",
)
def test_230707_media_errors_are_translated():
    """The 'I can currently process document images only' string is
    hardcoded English inline in client_processing._message_for_event."""
    from client_processing import DocumentRecognition

    class NotADocument:
        def recognize(self, data: bytes, mime_type: str) -> DocumentRecognition:
            return DocumentRecognition([], "not_document")

    processor, deps = _processor(
        preselect_language="Marathi",
        document_recognizer=NotADocument(),
    )

    processor.process(
        _event(
            message_id="m1",
            type="image",
            content="",
            media_url="https://media.example/photo.jpg",
        )
    )

    sent = deps["reply_sender"].calls[-1]["text"]
    assert "document images only" not in sent, sent


# --- Grid last row: distance between customer and dealership -------------


@pytest.mark.xfail(
    strict=True,
    reason="bug live: localisation rewrite dropped the approx-distance line",
)
def test_distance_is_shown_on_the_dealer_card():
    """Grid last row: 'Distance Between Customer and Dealership'. The
    localisation rewrite dropped the 'Approx. distance' line."""
    card = dealer_confirm_ask(
        name=DEALER.name,
        address=DEALER.address,
        phone=DEALER.phone,
        spoc_name=DEALER.spoc_name,
        map_url=DEALER.map_url,
        language="English",
        distance_km=DEALER.distance_km,
    )
    assert "4.2" in card


# --- 250703 / BOT Behaviour #1: fresh start after wrap-up ----------------


@pytest.mark.xfail(
    strict=True,
    reason="bug 250703 live: only the idle Redis TTL resets a completed chat",
)
def test_250703_conversation_restarts_after_wrap_up():
    """Sheet 250703 + BOT Behaviour #1: once the chat is completed and the
    customer says thank you, the next message should start a new flow with
    the language menu. Today only the idle Redis TTL resets anything."""
    processor, deps = _processor()
    deps["engine"].reply = "The dealership will contact you. Thank you!"
    deps["engine"].profile = {
        "product_interest": "King EV MAX",
        "disposition": "interested",
    }
    processor.process(_event(message_id="m1", content="yes I have all documents"))

    deps["engine"].profile = None
    deps["engine"].reply = "You're welcome!"
    processor.process(_event(message_id="m2", content="thank you"))

    session = deps["state"].sessions["+918286871533"]
    assert session.awaiting_language_selection is True


# --- context + instrumentation (full-history plan) ----------------------


def test_history_cap_is_high_enough_to_stop_repeat_questions():
    """MAX_HISTORY_TURNS was 6, so the model saw only the last 12 messages
    and re-asked questions it had already asked (bug 010805)."""
    import config

    assert config.MAX_HISTORY_TURNS >= 30


def test_known_state_block_lists_captured_facts():
    processor, deps = _processor(dealer_directory=FakeDealerDirectory(DEALER))
    session = deps["state"].sessions["+918286871533"]
    session.lead_profile.update(
        {
            "product_interest": "King EV MAX",
            "purchase_timeline": "30/07/2026",
            "doc_license": "yes",
            "doc_permit": "yes",
            "doc_badge": "unknown",
        }
    )
    session.dealer_shared_for_pincode = "400064"
    session.last_dealer_code = "D1"
    session.dealer_confirmed = True
    session.brochures_sent = ["King EV MAX"]

    block = processor._known_state_block(session)

    assert "product: King EV MAX" in block
    assert "purchase timeline: 30/07/2026" in block
    assert "pincode: 400064" in block
    assert "dealer: Arc Andheri (confirmed by customer)" in block
    assert "brochure already sent: King EV MAX" in block
    assert "documents confirmed: licence, permit" in block
    assert "badge" not in block  # unknown must not be claimed as captured
    assert "Do NOT ask for any of these again" in block


def test_known_state_block_is_empty_on_a_fresh_session():
    processor, deps = _processor()
    session = deps["state"].sessions["+918286871533"]
    session.customer = None
    assert processor._known_state_block(session) == ""


def test_known_state_rides_on_the_user_turn_not_the_system_prompt():
    """Keeping the system instruction byte-identical between turns is what
    makes the prefix cacheable — a per-turn string must not go in it."""
    from conversation_engine import build_contents

    contents = build_contents(
        [{"role": "user", "text": "hi"}, {"role": "model", "text": "hello"}],
        "411001",
        "KNOWN SO FAR — product: King EV MAX",
    )
    assert contents[-1]["role"] == "user"
    assert "KNOWN SO FAR" in contents[-1]["parts"][0]["text"]
    assert "411001" in contents[-1]["parts"][0]["text"]
    # Earlier turns must be untouched.
    assert contents[0]["parts"][0]["text"] == "hi"


def test_turn_tokens_are_recorded_for_cost_tracking():
    from conversation_engine import TurnOutput

    class UsageEngine:
        def __init__(self):
            self.turns = []
            self.reply = "Which model are you interested in?"
            self.profile = None

        def handle_turn(self, turn):
            self.turns.append(turn)
            return TurnOutput(
                reply_text=self.reply,
                profile=self.profile,
                prompt_tokens=5820,
                completion_tokens=64,
            )

    processor, deps = _processor(engine=UsageEngine())
    processor.process(_event(message_id="m1", content="hello"))

    recorded = deps["interaction_store"].exchanges[-1]
    assert recorded["prompt_tokens"] == 5820
    assert recorded["completion_tokens"] == 64


def test_usage_extraction_survives_a_missing_or_odd_response_shape():
    from conversation_engine import _extract_usage

    class Usage:
        prompt_token_count = 1200
        candidates_token_count = 40

    class Resp:
        usage_metadata = Usage()

    assert _extract_usage(Resp()) == (1200, 40)
    assert _extract_usage(object()) == (None, None)


# --- dispose: stale decline data reaching CRM ---------------------------


def test_welcome_back_decline_does_not_stick_to_a_reengaged_lead(monkeypatch):
    """02/08 transcript: customer answered "Nahi" to the welcome-back
    question, then two minutes later asked to see a different model and
    qualified fully. Dispose needs a pincode, which only arrived later, so
    CRM received status not_interested and then an "interested" record whose
    remark still read "notes: not interested on welcome-back"."""
    monkeypatch.setattr(
        "client_processing.classify_location_reply", lambda _m, _l="": "other"
    )
    from client_processing import Customer
    from tests.test_client_processing import FakeDisposeClient

    dispose = FakeDisposeClient()
    processor, deps = _processor(
        dispose_client=dispose,
        dealer_directory=FakeDealerDirectory(DEALER),
        skip_still_interested=False,
        preselect_language="English",
    )
    deps["directory"].customer = Customer(
        "307569",
        "Onkar Game",
        "English",
        product_enquired="King EV MAX",
        last_status="No Response",
    )

    # Language is preselected here, so the still-interested prompt is the
    # first thing the customer sees.
    processor.process(_event(message_id="m1", content="Hello"))
    assert "still planning to purchase" in deps["reply_sender"].calls[-1]["text"]

    # Declines the vehicle from last time...
    processor.process(_event(message_id="m2", content="No"))
    offer = deps["reply_sender"].calls[-1]["text"]
    assert "different TVS passenger model" in offer, offer

    # ...then re-engages and qualifies.
    deps["engine"].reply = "Great choice."
    processor.process(_event(message_id="m4", content="I want to see something else"))
    processor.process(_event(message_id="m5", content="King Deluxe"))
    processor.process(_event(message_id="m6", content="411001"))

    assert dispose.calls, "lead never reached CRM"
    for call in dispose.calls:
        assert call["status"] != "not_interested", call
        assert "not interested on welcome-back" not in call.get("remark", ""), call


def test_a_genuine_later_decline_is_still_reported(monkeypatch):
    """The cleanup must only drop the welcome-back marker, never a real
    not_interested the model captured during qualification."""
    from client_processing import ClientSession

    processor, _ = _processor()
    session = ClientSession(conversation_id="c1", mobile="+910000000000")
    session.lead_profile = {"disposition": "not_interested", "notes": "found a competitor"}

    processor._clear_welcome_back_decline(session)

    assert session.lead_profile["disposition"] == "not_interested"
    assert session.lead_profile["notes"] == "found a competitor"

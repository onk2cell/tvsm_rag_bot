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
        self.customer = Customer("crm-1", "Asha", "Marathi")

    def lookup(self, mobile: str) -> Customer:
        self.calls.append(mobile)
        return self.customer


class FailingDirectory(FakeDirectory):
    def lookup(self, mobile: str) -> Customer:
        self.calls.append(mobile)
        raise RuntimeError("CRM unavailable")


class FakeEngine:
    def __init__(self):
        self.turns = []
        self.reply = "तुम्हाला कोणते TVS मॉडेल आवडते?"

    def handle_turn(self, turn):
        self.turns.append(turn)
        return TurnOutput(reply_text=self.reply)


class FakeReplySender:
    def __init__(self):
        self.calls: list[dict] = []

    def send(self, *, mobile: str, in_reply_to: str, text: str) -> None:
        self.calls.append(
            {"mobile": mobile, "in_reply_to": in_reply_to, "text": text}
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
    assert turn.language == "Marathi"
    assert turn.channel == "client_app"
    assert turn.source == "client_app"
    assert turn.message == "नमस्कार"
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


def test_unsupported_crm_language_falls_back_to_message_detection():
    directory = FakeDirectory()
    directory.customer = Customer("crm-1", "Asha", "Unsupported")
    processor, deps = _processor(directory=directory)

    processor.process(_event(content="Hello"))

    assert deps["engine"].turns[0].language == "English"


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

    assert deps["engine"].turns[0].message == "मला ईव्ही मॅक्स पाहिजे"


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

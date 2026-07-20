"""Channel orchestration for client-app messages."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from time import perf_counter
from typing import Callable, Protocol, TypeVar

import config
from conversation_engine import ConversationEngine, TurnInput


@dataclass(frozen=True)
class Customer:
    customer_id: str
    name: str
    preferred_language: str = ""


@dataclass
class ClientSession:
    conversation_id: str
    mobile: str
    customer: Customer | None = None
    history: list[dict[str, str]] = field(default_factory=list)
    unclear_document_count: int = 0
    pending_replies: dict[str, dict] = field(default_factory=dict)


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
                language = _detect_language(event.get("content") or "")
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
        language = (
            customer.preferred_language
            if customer.preferred_language in {"English", "Hindi", "Marathi", "Tamil"}
            else _detect_language(event.get("content") or "")
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

        turn = TurnInput(
            session_id=session.conversation_id,
            language=language,
            message=message,
            channel="client_app",
            source="client_app",
            history=list(session.history),
        )
        try:
            output = self._attempt(lambda: self._engine.handle_turn(turn))
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
        session.pending_replies[event["message_id"]] = {
            "language": language,
            "user_message": message,
            "reply": output.reply_text,
            "citations": output.citations,
        }
        self._state.save(session)
        self._reply_and_record(
            event,
            session=session,
            language=language,
            user_message=message,
            reply=output.reply_text,
            started=started,
            citations=output.citations,
        )
        self._complete_turn(
            session,
            event["message_id"],
            message,
            output.reply_text,
        )

    def _message_for_event(
        self,
        event: dict,
        *,
        session: ClientSession,
        language: str,
    ) -> tuple[str, str | None]:
        if event["type"] == "text":
            return (event.get("content") or "").strip(), None

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
    ) -> None:
        try:
            self._reply_sender.send(
                mobile=session.mobile,
                in_reply_to=event["message_id"],
                text=reply,
            )
        except Exception as delivery_error:
            self._interactions.record_exchange(
                session=session.conversation_id,
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
            )
            raise
        self._interactions.record_exchange(
            session=session.conversation_id,
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


def _detect_language(text: str) -> str:
    if any("\u0b80" <= char <= "\u0bff" for char in text):
        return "Tamil"
    if any("\u0900" <= char <= "\u097f" for char in text):
        return "Marathi"
    return "English"


_T = TypeVar("_T")

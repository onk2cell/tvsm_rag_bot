"""The background job run by the worker: rate-limit -> ask -> reply -> remember."""
import logging
from time import perf_counter

import config
import interactions
import memory
from rag import ask
from whatsapp import mark_read, send_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")


def handle_message(sender: str, question: str, message_id: str) -> None:
    started = perf_counter()
    mark_read(message_id)

    if memory.over_rate_limit(sender):
        reply = "You're sending messages very quickly — please wait a moment."
        send_text(sender, reply)
        _record_exchange(
            sender,
            question,
            reply,
            started=started,
            status="rate_limited",
        )
        return

    history = memory.get_history(sender)
    try:
        answer, citations = ask(question, history)
    except Exception as error:
        log.exception("ask() failed for sender=%s", sender)
        reply = "Sorry, something went wrong. Please try again in a moment."
        send_text(sender, reply)
        _record_exchange(
            sender,
            question,
            reply,
            started=started,
            status="error",
            error=str(error),
            needs_review=True,
        )
        return

    send_text(sender, answer)
    _record_exchange(
        sender,
        question,
        answer,
        started=started,
        citations=citations,
    )
    memory.append_turn(sender, "user", question)
    memory.append_turn(sender, "model", answer)
    log.info("sender=%s q=%r cites=%s", sender, question[:80], citations)


def _record_exchange(
    sender: str,
    question: str,
    answer: str,
    *,
    started: float,
    status: str = "ok",
    error: str = "",
    needs_review: bool = False,
    citations: list[str] | None = None,
) -> None:
    try:
        interactions.get_store().record_exchange(
            session=sender,
            channel="whatsapp",
            source="whatsapp",
            language="",
            user_message=question,
            assistant_message=answer,
            latency_ms=round((perf_counter() - started) * 1000),
            status=status,
            error=error,
            model=config.MODEL,
            citations=citations,
            needs_review=needs_review,
        )
    except Exception:
        log.exception("Could not persist WhatsApp interaction sender=%s", sender)

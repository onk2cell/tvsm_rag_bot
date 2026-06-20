"""The background job run by the worker: rate-limit -> ask -> reply -> remember."""
import logging

import memory
from rag import ask
from whatsapp import mark_read, send_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")


def handle_message(sender: str, question: str, message_id: str) -> None:
    mark_read(message_id)

    if memory.over_rate_limit(sender):
        send_text(sender, "You're sending messages very quickly — please wait a moment.")
        return

    history = memory.get_history(sender)
    try:
        answer, citations = ask(question, history)
    except Exception:
        log.exception("ask() failed for sender=%s", sender)
        send_text(sender, "Sorry, something went wrong. Please try again in a moment.")
        return

    send_text(sender, answer)
    memory.append_turn(sender, "user", question)
    memory.append_turn(sender, "model", answer)
    log.info("sender=%s q=%r cites=%s", sender, question[:80], citations)

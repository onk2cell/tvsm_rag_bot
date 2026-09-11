"""Replay a past customer conversation against the current bot code.

Runs the real conversation engine + dealer directory, but with in-memory
state and a printing reply sender — nothing is sent to WhatsApp, no Redis,
CSV, SQLite, or dispose writes happen.

Usage (inside the client-worker container):
    python3 scripts/replay_conversation.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/app")

import admin_config
from client_processing import ClientMessageProcessor, ClientSession, Customer
from conversation_engine import make_engine
from dealers import DealerDirectory
from pgms import PgmDirectory

MOBILE = "+910000099999"

# CRM context of the replayed customer (from the original chat's first turn).
CUSTOMER = Customer(
    customer_id="replay-1",
    name="Customer",
    preferred_language="Kannada",
    product_enquired="TVS KING DELUXE",
    dealership_name="Gk Motors",
    last_remark="Customer will purchased in this month",
    last_status="Interested",
)

MESSAGES = [
    "Namadhu Andhra Pradesh proff sir",
    "August thingalu thaganthivi sir nema contact number kodi",
    "Dounpement estu sir",
    "Driving licence ayithe",
    "Namadhu Andhra Pradesh proff ,ya parmit",
    "Kamarshiyal andre",
    "Kamarshiyal ela",
    "Ela",
    "Auto rickshaw licence ayithe",
]


class MemoryState:
    def __init__(self):
        self.sessions: dict[str, ClientSession] = {}

    def load_or_start(self, mobile: str) -> ClientSession:
        if mobile not in self.sessions:
            self.sessions[mobile] = ClientSession(
                conversation_id="replay-session",
                mobile=mobile,
            )
        return self.sessions[mobile]

    def save(self, session: ClientSession) -> None:
        self.sessions[session.mobile] = session


class ReplayDirectory:
    def lookup(self, mobile: str) -> Customer:
        return CUSTOMER


class PrintingSender:
    def send(self, *, mobile: str, in_reply_to: str, text: str) -> None:
        print(f"BOT TEXT:\n{text}\n{'-' * 60}")

    def send_image(self, *, mobile: str, link: str, caption: str = "") -> None:
        print(f"BOT IMAGE: {link}\n  caption: {caption}\n{'-' * 60}")

    def send_document(self, *, mobile: str, link: str, caption: str = "") -> None:
        print(f"BOT DOCUMENT: {link}\n  caption: {caption}\n{'-' * 60}")


class NoopLeadStore:
    def upsert_client_identity(self, **values) -> None:
        pass

    def add_documents(self, **values) -> None:
        pass


class NoopInteractionStore:
    def record_exchange(self, **values) -> None:
        pass


class NoopMediaFetcher:
    def fetch(self, url, mime_type=None, *, message_type=None):
        raise RuntimeError("no media in replay")


class NoopTranscriber:
    def transcribe(self, data, mime_type, language) -> str:
        return ""


class NoopRecognizer:
    def recognize(self, data, mime_type):
        raise RuntimeError("no documents in replay")


def main() -> None:
    config_store = admin_config.get_store()
    config_store.ensure_seeded()
    processor = ClientMessageProcessor(
        state=MemoryState(),
        directory=ReplayDirectory(),
        engine=make_engine(config_store=config_store),
        reply_sender=PrintingSender(),
        lead_store=NoopLeadStore(),
        interaction_store=NoopInteractionStore(),
        media_fetcher=NoopMediaFetcher(),
        transcriber=NoopTranscriber(),
        document_recognizer=NoopRecognizer(),
        dealer_directory=DealerDirectory(),
        pgm_directory=PgmDirectory(),
        dispose_client=None,
    )
    for index, text in enumerate(MESSAGES):
        print(f"CUSTOMER: {text}")
        print("-" * 60)
        processor.process(
            {
                "message_id": f"replay-{index}",
                "type": "text",
                "mobile": MOBILE,
                "timestamp": "replay",
                "content": text,
            }
        )


if __name__ == "__main__":
    main()

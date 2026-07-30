"""Interactive local test for post-4h returning-customer still-interested flow.

Assumes CRM already knows the customer (name + product). Simulates a fresh
session after idle expiry: language menu → still-interested ask → your replies.

Nothing is sent to WhatsApp / Redis / dispose.

Usage (from repo root):
    .venv/bin/python scripts/replay_still_interested.py

Type customer messages and press Enter. Empty line or Ctrl-D to quit.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import admin_config
from client_processing import ClientMessageProcessor, ClientSession, Customer
from conversation_engine import make_engine
from dealers import DealerDirectory

MOBILE = "+918459522206"

# Assumed CRM data for a returning customer after 4h idle.
CUSTOMER = Customer(
    customer_id="313784",
    name="Onkar Game",
    preferred_language="English",  # ignored on fresh session — menu always shows
    product_enquired="King EV MAX",
    dealership_id="14302",
    dealership_name="JAM Research Services",
    city="Test City",
    state="Test State",
    last_remark="preferred_language: English | product_interest: King EV MAX",
    last_status="Interested",
)


class MemoryState:
    def __init__(self):
        self.sessions: dict[str, ClientSession] = {}

    def load_or_start(self, mobile: str) -> ClientSession:
        if mobile not in self.sessions:
            self.sessions[mobile] = ClientSession(
                conversation_id="replay-still-interested",
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
        print(f"\nBOT:\n{text}\n{'-' * 60}")

    def send_image(self, *, mobile: str, link: str, caption: str = "") -> None:
        print(f"\nBOT IMAGE: {link}\n  caption: {caption}\n{'-' * 60}")

    def send_document(self, *, mobile: str, link: str, caption: str = "") -> None:
        print(f"\nBOT PDF: {link}\n  caption: {caption}\n{'-' * 60}")


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
        raise RuntimeError("no media in this replay")


class NoopTranscriber:
    def transcribe(self, data, mime_type, language) -> str:
        return ""


class NoopRecognizer:
    def recognize(self, data, mime_type):
        raise RuntimeError("no documents in this replay")


class PrintingDispose:
    def dispose(self, payload: dict) -> dict:
        print(f"\nDISPOSE → {payload}\n{'-' * 60}")
        return {"status": "success"}


def main() -> None:
    config_store = admin_config.get_store()
    config_store.ensure_seeded()
    state = MemoryState()
    processor = ClientMessageProcessor(
        state=state,
        directory=ReplayDirectory(),
        engine=make_engine(config_store=config_store),
        reply_sender=PrintingSender(),
        lead_store=NoopLeadStore(),
        interaction_store=NoopInteractionStore(),
        media_fetcher=NoopMediaFetcher(),
        transcriber=NoopTranscriber(),
        document_recognizer=NoopRecognizer(),
        dealer_directory=DealerDirectory(),
        dispose_client=PrintingDispose(),
        sleep=lambda _s: None,
        retry_wait=0,
    )

    print("Returning-customer still-interested local replay")
    print(f"CRM: {CUSTOMER.name} | {CUSTOMER.product_enquired} | {CUSTOMER.last_status}")
    print("Fresh session (as after 4h idle). Type messages; empty line to quit.\n")
    print("Suggested path: Hi → 1 (English) → then 1 / 2 / yes / no / free text\n")

    n = 0
    while True:
        try:
            text = input("YOU> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            break
        n += 1
        processor.process(
            {
                "message_id": f"local-{n}",
                "type": "text",
                "mobile": MOBILE,
                "timestamp": "local",
                "content": text,
            }
        )
        session = state.sessions.get(MOBILE)
        if session:
            print(
                f"[session] lang={session.language!r} "
                f"awaiting_still={session.awaiting_still_interested} "
                f"awaiting_lang={session.awaiting_language_selection}"
            )


if __name__ == "__main__":
    main()

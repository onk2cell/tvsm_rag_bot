"""Replay an unknown-CRM customer chat against the real Gemini engine.

Nothing is sent to WhatsApp or JAM dispose — replies and dispose bodies are printed.
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "/app")

import admin_config
from client_processing import ClientMessageProcessor, ClientSession, Customer
from conversation_engine import make_engine
from dealers import DealerDirectory
from pgms import PgmDirectory

MOBILE = "+910000088888"

CUSTOMER = Customer(
    customer_id="unknown-910000088888",
    name="Customer 0000088888",
    preferred_language="",  # force language menu
)

MESSAGES = [
    "Hi",
    "3",  # Marathi
    "राहुल पाटील",
    "मला King EV MAX हवी",
    "411057",
    "होय",
    "15/12/2026",
    "लायसन्स आहे, परमिट नाही",
]


class MemoryState:
    def __init__(self):
        self.sessions: dict[str, ClientSession] = {}

    def load_or_start(self, mobile: str) -> ClientSession:
        if mobile not in self.sessions:
            self.sessions[mobile] = ClientSession(
                conversation_id="replay-unknown",
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


class PrintingDispose:
    def __init__(self):
        self.calls: list[dict] = []

    def dispose(self, payload: dict) -> dict:
        self.calls.append(payload)
        print("DISPOSE PAYLOAD:")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print("-" * 60)
        return {"status": "success"}


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
    dispose = PrintingDispose()
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
        dispose_client=dispose,
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

    print("=== SUMMARY ===")
    print(f"dispose_calls: {len(dispose.calls)}")
    if dispose.calls:
        last = dispose.calls[-1]
        print(f"customername: {last.get('customername')!r}")
        print(f"status: {last.get('status')!r}")
        print(f"product_name: {last.get('product_name')!r}")
        print(f"pincode: {last.get('pincode')!r}")
        print(f"dealer_code: {last.get('dealer_code')!r}")
        print(f"remark: {last.get('remark')!r}")
    else:
        print("NO DISPOSE CALLS")


if __name__ == "__main__":
    main()

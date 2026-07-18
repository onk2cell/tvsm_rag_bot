"""Behavioural tests for SQLite-backed interaction storage."""
from __future__ import annotations

import csv
import io
import sqlite3
from datetime import datetime, timedelta, timezone

from interactions import InteractionStore


def test_record_exchange_saves_user_and_assistant_turns(tmp_path):
    store = InteractionStore(tmp_path / "interactions.db", retention_days=90)

    store.record_exchange(
        session="web-1",
        channel="web",
        source="ricshow",
        language="Hindi",
        user_message="रेंज कितनी है?",
        assistant_message="यह मॉडल 179 किमी तक चलता है।",
        latency_ms=1250,
        model="gemini-test",
        citations=["TVS brochure"],
    )

    result = store.list_interactions(session="web-1")
    assert result["count"] == 2
    user, assistant = result["items"]
    assert user["role"] == "user"
    assert user["message"] == "रेंज कितनी है?"
    assert assistant["role"] == "assistant"
    assert assistant["latency_ms"] == 1250
    assert assistant["citations"] == ["TVS brochure"]
    assert assistant["needs_review"] is False


def test_failed_exchange_can_be_reviewed_with_note(tmp_path):
    store = InteractionStore(tmp_path / "interactions.db", retention_days=90)
    store.record_exchange(
        session="web-2",
        channel="web",
        source="web",
        language="English",
        user_message="What is the price?",
        assistant_message="Sorry, I could not answer that right now.",
        status="error",
        error="Gemini unavailable",
        needs_review=True,
    )

    flagged = store.list_interactions(needs_review=True)
    assert flagged["count"] == 1
    interaction_id = flagged["items"][0]["id"]

    assert store.mark_reviewed(interaction_id, note="Transient provider outage")
    assert store.list_interactions(needs_review=True)["count"] == 0
    reviewed = store.list_interactions(status="error")["items"][0]
    assert reviewed["review_note"] == "Transient provider outage"
    assert reviewed["reviewed_at"]


def test_filters_and_csv_export_preserve_multilingual_text(tmp_path):
    store = InteractionStore(tmp_path / "interactions.db", retention_days=90)
    store.record_turn(
        session="wa-1",
        channel="whatsapp",
        source="whatsapp",
        language="Marathi",
        role="user",
        message="मला इलेक्ट्रिक वाहन पाहिजे",
    )
    store.record_turn(
        session="web-3",
        channel="web",
        source="web",
        language="English",
        role="user",
        message="Show me CNG vehicles",
    )

    result = store.list_interactions(channel="whatsapp", language="Marathi")
    assert result["count"] == 1
    assert result["items"][0]["session"] == "wa-1"

    rows = list(csv.DictReader(io.StringIO(store.export_csv(channel="whatsapp"))))
    assert len(rows) == 1
    assert rows[0]["message"] == "मला इलेक्ट्रिक वाहन पाहिजे"


def test_cleanup_removes_only_records_older_than_retention(tmp_path):
    path = tmp_path / "interactions.db"
    store = InteractionStore(path, retention_days=90)
    store.record_turn(
        session="current",
        channel="web",
        source="web",
        language="English",
        role="user",
        message="Current",
    )

    old = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO interactions
                (timestamp, session, channel, source, language, role, message)
            VALUES (?, 'old', 'web', 'web', 'English', 'user', 'Old')
            """,
            (old,),
        )

    assert store.cleanup_expired() == 1
    assert store.list_interactions()["count"] == 1
    assert store.list_interactions()["items"][0]["session"] == "current"

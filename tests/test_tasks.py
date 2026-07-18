"""WhatsApp worker interaction-persistence tests."""
from __future__ import annotations

import config
import interactions
import tasks


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(
        config, "INTERACTIONS_DB_PATH", str(tmp_path / "interactions.db")
    )
    monkeypatch.setattr(config, "INTERACTION_RETENTION_DAYS", 90)
    interactions.reset_stores_for_tests()
    monkeypatch.setattr(tasks, "mark_read", lambda _: None)
    monkeypatch.setattr(tasks.memory, "over_rate_limit", lambda _: False)
    monkeypatch.setattr(tasks.memory, "get_history", lambda _: [])
    monkeypatch.setattr(tasks.memory, "append_turn", lambda *_: None)


def test_whatsapp_worker_records_successful_exchange(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(tasks, "ask", lambda *_: ("EV MAX range is 179 km.", ["KB"]))
    monkeypatch.setattr(tasks, "send_text", lambda to, text: sent.append((to, text)))

    tasks.handle_message("919999999999", "What is the range?", "wamid-1")

    assert sent == [("919999999999", "EV MAX range is 179 km.")]
    result = interactions.get_store().list_interactions(session="919999999999")
    assert [item["role"] for item in result["items"]] == ["user", "assistant"]
    assert result["items"][1]["citations"] == ["KB"]
    assert result["items"][1]["channel"] == "whatsapp"


def test_whatsapp_worker_flags_provider_error_for_review(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    sent: list[str] = []

    def fail(*_):
        raise RuntimeError("Gemini timeout")

    monkeypatch.setattr(tasks, "ask", fail)
    monkeypatch.setattr(tasks, "send_text", lambda _, text: sent.append(text))

    tasks.handle_message("918888888888", "Tell me about CNG", "wamid-2")

    assert "went wrong" in sent[0].lower()
    flagged = interactions.get_store().list_interactions(needs_review=True)
    assert flagged["count"] == 1
    assert flagged["items"][0]["error"] == "Gemini timeout"

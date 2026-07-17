"""Tests for public web qualification chat API."""
from __future__ import annotations

import admin_config
import qualify_web
from admin_config import AdminConfigStore
from conversation_engine import ConversationEngine, GenerateResult, TurnInput
from fastapi.testclient import TestClient
from leads import LeadWriter


class FakeLLM:
    def __init__(self, text: str):
        self.text = text
        self.last_turn: TurnInput | None = None

    def generate(self, *, system_instruction: str, contents: list[dict]) -> GenerateResult:
        return GenerateResult(text=self.text)


def _setup(tmp_path, monkeypatch, response: str):
    admin_config.reset_store_for_tests()
    monkeypatch.setenv("ADMIN_CONFIG_PATH", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("LEADS_CSV_PATH", str(tmp_path / "leads.csv"))
    cfg_store = AdminConfigStore(tmp_path / "cfg.json")
    cfg_store.ensure_seeded()
    writer = LeadWriter(tmp_path / "leads.csv", cfg_store)
    qualify_web.set_engine(
        ConversationEngine(config_store=cfg_store, llm=FakeLLM(response), lead_writer=writer)
    )
    from web import app

    return TestClient(app)


def test_qualify_languages_includes_config(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, "Hi")
    r = client.get("/api/qualify/languages?source=ricshow")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "ricshow"
    assert len(body["languages"]) == 4
    assert body["bot_name"]


def test_qualify_chat_requires_language(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, "Hello")
    r = client.post("/api/qualify/chat", json={"message": "hi"})
    assert r.status_code == 400


def test_qualify_chat_uses_engine(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, "Which TVS model interests you?")
    r = client.post(
        "/api/qualify/chat",
        json={
            "language": "English",
            "session_id": "web-test-1",
            "source": "ricshow",
            "message": "",
            "history": [],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "Which TVS model interests you?"
    assert body["session_id"] == "web-test-1"
    assert body["captured"] is False


def test_qualify_index_page(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, "Hi")
    r = client.get("/")
    assert r.status_code == 200
    assert "qualify/chat" in r.text or "/api/qualify/chat" in r.text


def test_admin_test_chat_page(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, "Hi")
    r = client.get("/admin/test-chat")
    assert r.status_code == 200
    assert "Admin test mode" in r.text

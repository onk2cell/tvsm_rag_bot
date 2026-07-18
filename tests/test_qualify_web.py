"""Tests for public web qualification chat API."""
from __future__ import annotations

import admin_config
import config
import interactions
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
    interactions.reset_stores_for_tests()
    monkeypatch.setenv("ADMIN_CONFIG_PATH", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("LEADS_CSV_PATH", str(tmp_path / "leads.csv"))
    monkeypatch.setattr(
        config, "INTERACTIONS_DB_PATH", str(tmp_path / "interactions.db"), raising=False
    )
    monkeypatch.setattr(
        config,
        "LOAD_TEST_INTERACTIONS_DB_PATH",
        str(tmp_path / "load_test_interactions.db"),
        raising=False,
    )
    monkeypatch.setattr(config, "LOAD_TEST_TOKEN", "load-secret", raising=False)
    monkeypatch.setattr(config, "INTERACTION_RETENTION_DAYS", 90, raising=False)
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

    records = interactions.InteractionStore(
        tmp_path / "interactions.db"
    ).list_interactions(session="web-test-1")
    assert [item["role"] for item in records["items"]] == ["assistant"]
    assert records["items"][0]["message"] == "Which TVS model interests you?"


def test_qualify_chat_routes_authenticated_load_test_to_separate_database(
    tmp_path, monkeypatch
):
    client = _setup(tmp_path, monkeypatch, "Which model interests you?")
    response = client.post(
        "/api/qualify/chat",
        headers={"X-Load-Test-Token": "load-secret"},
        json={
            "language": "Tamil",
            "session_id": "load-1",
            "message": "எந்த மாடல்கள் உள்ளன?",
        },
    )

    assert response.status_code == 200
    production = interactions.InteractionStore(tmp_path / "interactions.db")
    load_test = interactions.InteractionStore(tmp_path / "load_test_interactions.db")
    assert production.list_interactions()["count"] == 0
    assert load_test.list_interactions(session="load-1")["count"] == 2


def test_qualify_chat_rejects_invalid_load_test_token(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, "Hello")
    response = client.post(
        "/api/qualify/chat",
        headers={"X-Load-Test-Token": "wrong"},
        json={"language": "English", "message": "Hello"},
    )
    assert response.status_code == 403


def test_qualify_chat_records_provider_errors_for_review(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, "unused")

    class RaisingLLM:
        def generate(self, **_):
            raise RuntimeError("provider unavailable")

    cfg_store = AdminConfigStore(tmp_path / "cfg.json")
    qualify_web.set_engine(ConversationEngine(config_store=cfg_store, llm=RaisingLLM()))
    response = client.post(
        "/api/qualify/chat",
        json={
            "language": "English",
            "session_id": "web-error",
            "message": "What is the range?",
        },
    )

    assert response.status_code == 503
    assert "try again" in response.json()["detail"].lower()
    flagged = interactions.InteractionStore(
        tmp_path / "interactions.db"
    ).list_interactions(needs_review=True)
    assert flagged["count"] == 1
    assert flagged["items"][0]["error"] == "provider unavailable"


def test_playground_websocket_records_exchange(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, "unused")
    monkeypatch.setattr("web.ask", lambda *_args, **_kwargs: ("Answer", ["KB"]))

    with client.websocket_connect("/ws/chat") as websocket:
        websocket.send_json(
            {
                "message": "Question",
                "model": "gemini-test",
                "store": "fileSearchStores/test",
                "history": [],
            }
        )
        assert websocket.receive_json()["answer"] == "Answer"

    records = interactions.InteractionStore(
        tmp_path / "interactions.db"
    ).list_interactions()
    assert records["count"] == 2
    assert records["items"][1]["source"] == "playground"


def test_qualify_chat_includes_tts_on_intro(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, "Welcome! Which model interests you?")
    monkeypatch.setattr(
        "qualify_web.voice.synthesize_speech",
        lambda text, language=None: b"RIFFfake-wav",
    )

    r = client.post(
        "/api/qualify/chat",
        json={
            "language": "English",
            "session_id": "web-test-tts",
            "message": "",
            "history": [],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["audio_base64"]
    assert body["audio_mime"] == "audio/wav"


def test_qualify_chat_skips_tts_after_intro(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, "Great choice.")
    monkeypatch.setattr(
        "qualify_web.voice.synthesize_speech",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not TTS")),
    )

    r = client.post(
        "/api/qualify/chat",
        json={
            "language": "English",
            "session_id": "web-test-tts2",
            "message": "King EV MAX",
            "history": [
                {"role": "model", "text": "Which model?"},
                {"role": "user", "text": "hi"},
            ],
        },
    )
    assert r.status_code == 200
    assert "audio_base64" not in r.json()


def test_qualify_index_page(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, "Hi")
    r = client.get("/")
    assert r.status_code == 200
    assert "qualify/chat" in r.text or "/api/qualify/chat" in r.text
    assert "conversation is stored" in r.text


def test_admin_test_chat_page(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, "Hi")
    r = client.get("/admin/test-chat")
    assert r.status_code == 200
    assert "Admin test mode" in r.text


def test_qualify_index_includes_mic_button(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, "Hi")
    r = client.get("/")
    assert r.status_code == 200
    assert "micBtn" in r.text
    assert "/api/qualify/transcribe" in r.text


def test_qualify_transcribe_requires_audio(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, "Hi")
    r = client.post("/api/qualify/transcribe", data={"language": "English"})
    assert r.status_code == 422


def test_qualify_transcribe_returns_transcript(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, "Which model?")

    def fake_transcribe(raw, mime, *, language_hint=None):
        assert raw == b"audio-bytes"
        assert mime.startswith("audio/")
        assert language_hint == "English"
        return "King EV MAX"

    monkeypatch.setattr("qualify_web.voice.transcribe_audio", fake_transcribe)
    monkeypatch.setattr("rag.has_client", lambda: True)

    r = client.post(
        "/api/qualify/transcribe",
        files={"audio": ("clip.webm", b"audio-bytes", "audio/webm")},
        data={"language": "English"},
    )
    assert r.status_code == 200
    assert r.json()["transcript"] == "King EV MAX"


def test_qualify_transcribe_empty_transcript_is_400(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, "Hi")
    monkeypatch.setattr(
        "qualify_web.voice.transcribe_audio",
        lambda *a, **k: "",
    )
    monkeypatch.setattr("rag.has_client", lambda: True)

    r = client.post(
        "/api/qualify/transcribe",
        files={"audio": ("clip.webm", b"audio-bytes", "audio/webm")},
        data={"language": "English"},
    )
    assert r.status_code == 400

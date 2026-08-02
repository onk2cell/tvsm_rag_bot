"""Admin panel (web.py) endpoint contract tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from admin_config import AdminConfigStore
from web import create_admin_app

TOKEN = "s3cret-admin"


class FakeKeyManager:
    """Stand-in for the rag module's key API — no real Gemini calls."""

    def __init__(self, *, source=None, configured=False):
        self._source = source
        self._configured = configured
        self.reject = False
        self.saved_key = None
        self.cleared = False

    def runtime_key_active(self):
        return self._source == "runtime"

    def has_client(self):
        return self._configured

    def persist_api_key(self, api_key, validate=True):
        if self.reject:
            raise RuntimeError("invalid key")
        self.saved_key = api_key
        self._source = "runtime"
        self._configured = True

    def clear_persisted_key(self):
        self.cleared = True
        self._source = None
        self._configured = False


def _app(tmp_path, *, token=TOKEN, keys=None):
    store = AdminConfigStore(tmp_path / "admin_config.json")
    store.ensure_seeded()
    return create_admin_app(
        admin_token=token,
        config_store=store,
        key_manager=keys or FakeKeyManager(),
    )


def _client(tmp_path, **kw):
    return TestClient(_app(tmp_path, **kw)), tmp_path


def _auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def test_page_served_without_auth(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "Control Panel" in resp.text


def test_config_requires_token(tmp_path):
    client, _ = _client(tmp_path)
    assert client.get("/admin/api/config").status_code == 401
    assert client.get(
        "/admin/api/config", headers={"Authorization": "Bearer wrong"}
    ).status_code == 401


def test_read_config_returns_seeded_defaults(tmp_path):
    client, _ = _client(tmp_path)
    cfg = client.get("/admin/api/config", headers=_auth()).json()
    assert cfg["bot_name"] == "TVS Passenger 3W Assistant"
    assert cfg["voice_policy"] == "intro_only"


def test_update_config_roundtrips_and_persists(tmp_path):
    client, path = _client(tmp_path)
    cfg = client.get("/admin/api/config", headers=_auth()).json()
    cfg["bot_name"] = "Renamed Bot"
    resp = client.put("/admin/api/config", json=cfg, headers=_auth())
    assert resp.status_code == 200
    assert resp.json()["bot_name"] == "Renamed Bot"
    # persisted to disk, so the worker process reloads it
    again = client.get("/admin/api/config", headers=_auth()).json()
    assert again["bot_name"] == "Renamed Bot"


def test_update_config_rejects_invalid(tmp_path):
    client, _ = _client(tmp_path)
    cfg = client.get("/admin/api/config", headers=_auth()).json()
    cfg["voice_policy"] = "shout"
    resp = client.put("/admin/api/config", json=cfg, headers=_auth())
    assert resp.status_code == 400
    assert "voice_policy" in resp.json()["detail"]


def test_disabled_when_token_empty(tmp_path):
    client, _ = _client(tmp_path, token="")
    assert client.get("/admin/api/config", headers=_auth()).status_code == 503


def test_meta_exposes_voice_policies_and_gemini(tmp_path):
    keys = FakeKeyManager(source="env", configured=True)
    client = TestClient(_app(tmp_path, keys=keys))
    meta = client.get("/admin/api/meta", headers=_auth()).json()
    assert "intro_only" in meta["voice_policies"]
    assert meta["gemini"]["source"] == "env"
    assert meta["gemini"]["configured"] is True


def test_set_gemini_key_validates_and_saves(tmp_path):
    keys = FakeKeyManager()
    client = TestClient(_app(tmp_path, keys=keys))
    resp = client.post(
        "/admin/api/gemini", json={"api_key": "AIza-good"}, headers=_auth()
    )
    assert resp.status_code == 200
    assert keys.saved_key == "AIza-good"
    assert resp.json()["source"] == "runtime"


def test_set_gemini_key_rejects_bad_key(tmp_path):
    keys = FakeKeyManager()
    keys.reject = True
    client = TestClient(_app(tmp_path, keys=keys))
    resp = client.post(
        "/admin/api/gemini", json={"api_key": "AIza-bad"}, headers=_auth()
    )
    assert resp.status_code == 400
    assert "rejected" in resp.json()["detail"].lower()


def test_set_gemini_key_requires_value(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.post("/admin/api/gemini", json={"api_key": "  "}, headers=_auth())
    assert resp.status_code == 400


def test_clear_gemini_key(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "GEMINI_API_KEY", "")  # no env fallback
    keys = FakeKeyManager(source="runtime", configured=True)
    client = TestClient(_app(tmp_path, keys=keys))
    resp = client.delete("/admin/api/gemini", headers=_auth())
    assert resp.status_code == 200
    assert keys.cleared is True
    assert resp.json()["source"] is None

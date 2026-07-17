"""Admin bot-config HTTP API."""
from __future__ import annotations

import admin_config
from fastapi.testclient import TestClient


def test_get_bot_config_requires_admin_token(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_CONFIG_PATH", str(tmp_path / "bot_config.json"))
    admin_config.reset_store_for_tests()

    from web import app

    client = TestClient(app)
    assert client.get("/admin/bot-config").status_code == 401

    r = client.get("/admin/bot-config", headers={"X-Admin-Token": "admin-test-token"})
    assert r.status_code == 200
    body = r.json()
    assert body["bot_name"] == "TVS Passenger 3W Assistant"
    assert len(body["languages"]) == 4


def test_put_bot_config_updates_and_rejects_invalid(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_CONFIG_PATH", str(tmp_path / "bot_config.json"))
    admin_config.reset_store_for_tests()

    from web import app

    client = TestClient(app)
    headers = {"X-Admin-Token": "admin-test-token"}

    cfg = client.get("/admin/bot-config", headers=headers).json()
    cfg["bot_name"] = "API Updated Bot"
    r = client.put("/admin/bot-config", headers=headers, json=cfg)
    assert r.status_code == 200
    assert r.json()["bot_name"] == "API Updated Bot"

    bad = client.get("/admin/bot-config", headers=headers).json()
    bad["voice_policy"] = "invalid"
    r = client.put("/admin/bot-config", headers=headers, json=bad)
    assert r.status_code == 400
    assert "voice_policy" in r.json()["detail"]

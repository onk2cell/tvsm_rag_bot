"""Admin leads CSV download API."""
from __future__ import annotations

import csv

import admin_config
from fastapi.testclient import TestClient
from leads import LeadWriter


def test_admin_leads_requires_token(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_CONFIG_PATH", str(tmp_path / "bot_config.json"))
    monkeypatch.setenv("LEADS_CSV_PATH", str(tmp_path / "leads.csv"))
    admin_config.reset_store_for_tests()

    from web import app

    client = TestClient(app)
    assert client.get("/admin/leads").status_code == 401
    assert client.get("/admin/leads.csv").status_code == 401


def test_admin_leads_summary_and_download(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_CONFIG_PATH", str(tmp_path / "bot_config.json"))
    monkeypatch.setenv("LEADS_CSV_PATH", str(tmp_path / "leads.csv"))
    admin_config.reset_store_for_tests()

    store = admin_config.AdminConfigStore(tmp_path / "bot_config.json")
    store.ensure_seeded()
    writer = LeadWriter(tmp_path / "leads.csv", store)
    writer.append(
        channel="web",
        source="ricshow",
        session="web-abc",
        language="English",
        profile={"product_interest": "King EV MAX", "lead_quality": "HOT"},
    )

    import config
    from web import app

    monkeypatch.setattr(config, "LEADS_CSV_PATH", str(tmp_path / "leads.csv"))

    client = TestClient(app)
    headers = {"X-Admin-Token": "admin-test-token"}

    info = client.get("/admin/leads", headers=headers)
    assert info.status_code == 200
    body = info.json()
    assert body["count"] == 1
    assert "timestamp" in body["columns"]
    assert "product_interest" in body["columns"]

    dl = client.get("/admin/leads.csv", headers=headers)
    assert dl.status_code == 200
    assert "text/csv" in dl.headers["content-type"]
    rows = list(csv.DictReader(dl.text.splitlines()))
    assert len(rows) == 1
    assert rows[0]["session"] == "web-abc"
    assert rows[0]["product_interest"] == "King EV MAX"


def test_admin_leads_download_404_when_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_CONFIG_PATH", str(tmp_path / "bot_config.json"))
    monkeypatch.setenv("LEADS_CSV_PATH", str(tmp_path / "missing.csv"))
    admin_config.reset_store_for_tests()

    import config
    from web import app

    monkeypatch.setattr(config, "LEADS_CSV_PATH", str(tmp_path / "missing.csv"))

    client = TestClient(app)
    r = client.get("/admin/leads.csv", headers={"X-Admin-Token": "admin-test-token"})
    assert r.status_code == 404

"""Admin interaction history, export, and review API tests."""
from __future__ import annotations

import csv

import config
import interactions
from fastapi.testclient import TestClient


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(
        config, "INTERACTIONS_DB_PATH", str(tmp_path / "interactions.db")
    )
    monkeypatch.setattr(
        config,
        "LOAD_TEST_INTERACTIONS_DB_PATH",
        str(tmp_path / "load_test_interactions.db"),
    )
    monkeypatch.setattr(config, "INTERACTION_RETENTION_DAYS", 90)
    interactions.reset_stores_for_tests()
    from web import app

    return TestClient(app), {"X-Admin-Token": "admin-test-token"}


def test_interaction_admin_endpoints_require_token(tmp_path, monkeypatch):
    client, _ = _setup(tmp_path, monkeypatch)
    assert client.get("/admin/interactions").status_code == 401
    assert client.get("/admin/interactions.csv").status_code == 401
    assert client.patch("/admin/interactions/1/review", json={}).status_code == 401


def test_admin_filters_exports_and_reviews_flagged_interactions(
    tmp_path, monkeypatch
):
    client, headers = _setup(tmp_path, monkeypatch)
    store = interactions.get_store()
    store.record_exchange(
        session="web-error",
        channel="web",
        source="web",
        language="Hindi",
        user_message="सवाल",
        assistant_message="कृपया फिर कोशिश करें",
        status="error",
        error="provider timeout",
        needs_review=True,
    )
    store.record_turn(
        session="wa-ok",
        channel="whatsapp",
        source="whatsapp",
        language="",
        role="user",
        message="hello",
    )

    response = client.get(
        "/admin/interactions?channel=web&needs_review=true",
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    interaction_id = body["items"][0]["id"]

    export = client.get("/admin/interactions.csv?channel=web", headers=headers)
    rows = list(csv.DictReader(export.text.splitlines()))
    assert export.status_code == 200
    assert len(rows) == 2

    reviewed = client.patch(
        f"/admin/interactions/{interaction_id}/review",
        headers=headers,
        json={"note": "Known provider outage"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["reviewed"] is True
    assert client.get(
        "/admin/interactions?needs_review=true", headers=headers
    ).json()["count"] == 0


def test_admin_can_query_separate_load_test_database(tmp_path, monkeypatch):
    client, headers = _setup(tmp_path, monkeypatch)
    interactions.get_store(load_test=True).record_turn(
        session="load-1",
        channel="web",
        source="web",
        language="Tamil",
        role="user",
        message="வணக்கம்",
    )

    assert client.get("/admin/interactions", headers=headers).json()["count"] == 0
    load_result = client.get(
        "/admin/interactions?load_test=true", headers=headers
    )
    assert load_result.json()["count"] == 1

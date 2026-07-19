"""Mock CRM/customer-app service contract tests."""
from __future__ import annotations

from fastapi.testclient import TestClient

from mock_client import create_mock_client


def _client():
    return TestClient(create_mock_client(username="api", password="secret"))


def test_mock_customer_api_returns_seeded_customer():
    client = _client()

    response = client.get(
        "/mock/customers",
        params={"mobile": "+918286871533"},
        auth=("api", "secret"),
    )

    assert response.status_code == 200
    assert response.json()["customers"][0] == {
        "customer_id": "mock-customer-1",
        "name": "Asha",
        "preferred_language": "Marathi",
    }


def test_mock_callback_records_reply_for_assertions():
    client = _client()
    payload = {
        "message_id": "reply-1",
        "in_reply_to": "incoming-1",
        "type": "text",
        "mobile": "+918286871533",
        "content": "Hello",
        "timestamp": "2026-07-19T10:00:00+00:00",
        "part_number": 1,
        "part_count": 1,
    }

    response = client.post("/mock/replies", auth=("api", "secret"), json=payload)

    assert response.status_code == 204
    state = client.get("/mock/state", auth=("api", "secret")).json()
    assert state["replies"] == [payload]


def test_mock_callback_can_inject_failure_sequence():
    client = _client()
    client.post(
        "/mock/control/reply-statuses",
        auth=("api", "secret"),
        json={"statuses": [500, 502, 204]},
    )
    payload = {
        "message_id": "reply-1",
        "in_reply_to": "incoming-1",
        "type": "text",
        "mobile": "+918286871533",
        "content": "Hello",
        "timestamp": "2026-07-19T10:00:00+00:00",
        "part_number": 1,
        "part_count": 1,
    }

    statuses = [
        client.post("/mock/replies", auth=("api", "secret"), json=payload).status_code
        for _ in range(3)
    ]

    assert statuses == [500, 502, 204]
    state = client.get("/mock/state", auth=("api", "secret")).json()
    assert len(state["replies"]) == 3


def test_mock_customer_lookup_can_inject_records_and_failures():
    client = _client()
    client.post(
        "/mock/control/customer",
        auth=("api", "secret"),
        json={
            "mobile": "+919999999999",
            "customers": [
                {
                    "customer_id": "first",
                    "name": "First",
                    "preferred_language": "English",
                },
                {
                    "customer_id": "second",
                    "name": "Second",
                    "preferred_language": "Hindi",
                },
            ],
        },
    )
    client.post(
        "/mock/control/lookup",
        auth=("api", "secret"),
        json={"statuses": [503, 200], "delay_seconds": 0},
    )

    first = client.get(
        "/mock/customers",
        params={"mobile": "+919999999999"},
        auth=("api", "secret"),
    )
    second = client.get(
        "/mock/customers",
        params={"mobile": "+919999999999"},
        auth=("api", "secret"),
    )

    assert first.status_code == 503
    assert len(second.json()["customers"]) == 2
    lookups = client.get("/mock/state", auth=("api", "secret")).json()["lookups"]
    assert len(lookups) == 2
    assert all("timestamp" in lookup for lookup in lookups)


def test_mock_media_fixtures_are_available():
    client = _client()

    audio = client.get("/mock/media/audio.mp3")
    image = client.get("/mock/media/document.jpg")

    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/mpeg"
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/jpeg"
    assert client.get("/mock/media/unclear.jpg").status_code == 200
    assert client.get("/mock/media/non-document.jpg").status_code == 200
    assert client.get("/mock/media/multiple.jpg").status_code == 200

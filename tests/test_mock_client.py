"""Mock CRM/customer-app service contract tests."""
from __future__ import annotations

from fastapi.testclient import TestClient

from mock_client import create_mock_client


class FakeResponse:
    status_code = 202

    @staticmethod
    def json():
        return {"status": "accepted", "message_id": "server-id", "duplicate": False}


class FakeHttp:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return FakeResponse()


def _client(*, http=None):
    return TestClient(
        create_mock_client(
            username="api",
            password="secret",
            bot_webhook_url="http://bot/client/webhook/messages",
            bot_webhook_user="bot-user",
            bot_webhook_password="bot-secret",
            http=http or FakeHttp(),
        )
    )


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


def test_webhook_chat_page_is_available():
    client = _client()

    response = client.get("/mock/chat")

    assert response.status_code == 200
    assert "Webhook Test Chat" in response.text
    assert "/mock/chat/send" in response.text


def test_webhook_chat_sends_unique_event_to_bot():
    http = FakeHttp()
    client = _client(http=http)

    response = client.post(
        "/mock/chat/send",
        json={"mobile": "+918286871533", "content": "Hi"},
    )

    assert response.status_code == 202
    call = http.calls[0]
    assert call["url"] == "http://bot/client/webhook/messages"
    assert call["auth"] == ("bot-user", "bot-secret")
    assert call["json"]["mobile"] == "+918286871533"
    assert call["json"]["content"] == "Hi"
    assert call["json"]["type"] == "text"
    assert call["json"]["message_id"].startswith("manual-")


def test_webhook_chat_lists_only_selected_mobile_replies():
    client = _client()
    base = {
        "message_id": "reply-1",
        "in_reply_to": "incoming-1",
        "type": "text",
        "content": "Hello",
        "timestamp": "2026-07-19T10:00:00+00:00",
    }
    client.post(
        "/mock/replies",
        auth=("api", "secret"),
        json={**base, "mobile": "+918286871533"},
    )
    client.post(
        "/mock/replies",
        auth=("api", "secret"),
        json={**base, "message_id": "reply-2", "mobile": "+919999999999"},
    )

    response = client.get(
        "/mock/chat/replies",
        params={"mobile": "+918286871533"},
    )

    assert response.status_code == 200
    assert [item["message_id"] for item in response.json()["replies"]] == ["reply-1"]

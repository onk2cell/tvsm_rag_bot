"""Client-app inbound webhook contract tests."""
from __future__ import annotations

from fastapi.testclient import TestClient

from client_webhook import create_app


class FakeDeduplicator:
    def __init__(self):
        self.seen: set[str] = set()

    def claim(self, message_id: str) -> bool:
        if message_id in self.seen:
            return False
        self.seen.add(message_id)
        return True

    def release(self, message_id: str) -> None:
        self.seen.discard(message_id)


class FakePublisher:
    def __init__(self):
        self.events: list[dict] = []
        self.error: Exception | None = None

    def publish(self, event: dict) -> None:
        if self.error:
            raise self.error
        self.events.append(event)


class FakeRateLimiter:
    def __init__(self, allowed: bool = True):
        self.allowed = allowed

    def allow(self, mobile: str) -> bool:
        return self.allowed


def _client(*, rate_limiter=None):
    deduplicator = FakeDeduplicator()
    publisher = FakePublisher()
    app = create_app(
        username="client",
        password="secret",
        deduplicator=deduplicator,
        publisher=publisher,
        rate_limiter=rate_limiter or FakeRateLimiter(),
    )
    return TestClient(app), deduplicator, publisher


def _text_event(**overrides):
    event = {
        "message_id": "client-message-1",
        "type": "text",
        "mobile": "+918286871533",
        "timestamp": "19/07/2026 14:00",
        "content": "hi",
    }
    event.update(overrides)
    return event


def test_valid_message_is_accepted_and_published():
    client, _, publisher = _client()

    response = client.post(
        "/client/webhook/messages",
        auth=("client", "secret"),
        json=_text_event(),
    )

    assert response.status_code == 202
    assert response.json() == {
        "status": "accepted",
        "message_id": "client-message-1",
        "duplicate": False,
    }
    assert len(publisher.events) == 1
    assert {
        key: value
        for key, value in publisher.events[0].items()
        if key != "received_at"
    } == _text_event()
    assert publisher.events[0]["received_at"].endswith("+00:00")


def test_duplicate_message_is_acknowledged_without_republishing():
    client, _, publisher = _client()
    payload = _text_event()

    first = client.post("/client/webhook/messages", auth=("client", "secret"), json=payload)
    duplicate = client.post(
        "/client/webhook/messages", auth=("client", "secret"), json=payload
    )

    assert first.status_code == 202
    assert duplicate.status_code == 202
    assert duplicate.json() == {
        "status": "duplicate",
        "message_id": "client-message-1",
        "duplicate": True,
    }
    assert len(publisher.events) == 1
    assert publisher.events[0]["message_id"] == payload["message_id"]


def test_unsupported_type_is_explicitly_ignored():
    client, _, publisher = _client()

    response = client.post(
        "/client/webhook/messages",
        auth=("client", "secret"),
        json=_text_event(type="video"),
    )

    assert response.status_code == 202
    assert response.json() == {
        "status": "ignored",
        "message_id": "client-message-1",
        "duplicate": False,
        "reason": "unsupported_type",
    }
    assert publisher.events == []


def test_invalid_payload_returns_field_errors():
    client, _, publisher = _client()

    response = client.post(
        "/client/webhook/messages",
        auth=("client", "secret"),
        json=_text_event(mobile="8286871533", content=None),
    )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "invalid_payload"
    assert {error["field"] for error in body["errors"]} == {"mobile"}
    assert publisher.events == []


def test_text_requires_content():
    client, _, publisher = _client()

    response = client.post(
        "/client/webhook/messages",
        auth=("client", "secret"),
        json=_text_event(content=None),
    )

    assert response.status_code == 400
    assert {error["field"] for error in response.json()["errors"]} == {"content"}
    assert publisher.events == []


def test_media_requires_url_and_mime_type():
    client, _, _ = _client()

    response = client.post(
        "/client/webhook/messages",
        auth=("client", "secret"),
        json=_text_event(type="audio", content=None),
    )

    assert response.status_code == 400
    assert {error["field"] for error in response.json()["errors"]} >= {
        "media_url",
        "mime_type",
    }


def test_media_mime_must_match_message_type():
    client, _, publisher = _client()

    response = client.post(
        "/client/webhook/messages",
        auth=("client", "secret"),
        json=_text_event(
            type="audio",
            content=None,
            media_url="https://client.example/file.jpg",
            mime_type="image/jpeg",
        ),
    )

    assert response.status_code == 400
    assert {error["field"] for error in response.json()["errors"]} == {"mime_type"}
    assert publisher.events == []


def test_bad_credentials_are_rejected():
    client, _, publisher = _client()

    response = client.post(
        "/client/webhook/messages",
        auth=("client", "wrong"),
        json=_text_event(),
    )

    assert response.status_code == 401
    assert publisher.events == []


def test_publish_failure_releases_message_for_client_retry():
    client, deduplicator, publisher = _client()
    publisher.error = RuntimeError("queue unavailable")

    response = client.post(
        "/client/webhook/messages",
        auth=("client", "secret"),
        json=_text_event(),
    )

    assert response.status_code == 503
    assert "client-message-1" not in deduplicator.seen


def test_rate_limited_mobile_is_not_published():
    client, _, publisher = _client(rate_limiter=FakeRateLimiter(allowed=False))

    response = client.post(
        "/client/webhook/messages",
        auth=("client", "secret"),
        json=_text_event(),
    )

    assert response.status_code == 429
    assert response.json()["code"] == "rate_limited"
    assert publisher.events == []

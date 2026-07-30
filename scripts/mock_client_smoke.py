"""Exercise the built mock stack from inbound webhook to reply callback."""
from __future__ import annotations

import base64
import json
import sqlite3
import time
import urllib.error
import urllib.request
import uuid


def request(url: str, *, auth: tuple[str, str], payload: dict | None = None):
    headers = {
        "Authorization": "Basic "
        + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
    }
    data = None
    method = "GET"
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
        method = "POST"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as response:
        raw = response.read()
        return response.status, json.loads(raw) if raw else {}


def wait_for_health(url: str) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {url}")


def main() -> None:
    mock_auth = ("mock-client", "mock-secret")
    webhook_auth = ("mock-app", "mock-app-secret")
    wait_for_health("http://127.0.0.1:8003/health")
    wait_for_health("http://127.0.0.1:8005/health")
    request(
        "http://127.0.0.1:8003/mock/control/reset",
        auth=mock_auth,
        payload={},
    )
    message_id = f"smoke-{uuid.uuid4()}"
    message_text = f"smoke message {message_id}"
    status, acknowledgement = request(
        "http://127.0.0.1:8005/client/webhook/messages",
        auth=webhook_auth,
        payload={
            "message_id": message_id,
            "type": "text",
            "mobile": "+918286871533",
            "timestamp": "mock-client-time",
            "content": message_text,
        },
    )
    if status != 202 or acknowledgement.get("status") != "accepted":
        raise RuntimeError(f"Unexpected acknowledgement: {status} {acknowledgement}")

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        _, state = request("http://127.0.0.1:8003/mock/state", auth=mock_auth)
        matches = [
            reply
            for reply in state.get("replies", [])
            if reply.get("in_reply_to") == message_id
        ]
        if matches:
            with sqlite3.connect("data/mock/interactions.db") as database:
                persisted = database.execute(
                    """
                    SELECT COUNT(*) FROM interactions
                    WHERE channel = 'client_app' AND role = 'user' AND message = ?
                    """,
                    (message_text,),
                ).fetchone()[0]
            if persisted != 1:
                raise RuntimeError("Reply arrived but interaction was not persisted")
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "message_id": message_id,
                        "reply": matches[0]["content"],
                    }
                )
            )
            return
        time.sleep(0.5)
    raise RuntimeError("Timed out waiting for mock reply callback")


if __name__ == "__main__":
    main()

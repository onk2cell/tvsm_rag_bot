"""Local/CI simulator for the client CRM and reply webhook."""
from __future__ import annotations

import os
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone

import requests
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials


DEFAULT_CUSTOMERS = {
    "+918286871533": [
        {
            "customer_id": "mock-customer-1",
            "name": "Asha",
            "preferred_language": "Marathi",
        }
    ]
}


def create_mock_client(
    *,
    username: str,
    password: str,
    bot_webhook_url: str = "",
    bot_webhook_user: str = "",
    bot_webhook_password: str = "",
    http=requests,
) -> FastAPI:
    app = FastAPI(title="Mock Client CRM")
    security = HTTPBasic()
    lock = threading.Lock()
    state = {
        "customers": {key: list(value) for key, value in DEFAULT_CUSTOMERS.items()},
        "lookups": [],
        "replies": [],
        "reply_statuses": [],
        "lookup_statuses": [],
        "lookup_delay_seconds": 0.0,
    }

    def authenticate(credentials: HTTPBasicCredentials = Depends(security)) -> None:
        valid = secrets.compare_digest(credentials.username, username)
        valid = valid and secrets.compare_digest(credentials.password, password)
        if not valid:
            raise HTTPException(status_code=401, detail="Invalid mock client credentials")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/mock/chat", response_class=HTMLResponse)
    def webhook_chat():
        return _chat_page()

    @app.post("/mock/chat/send", status_code=202)
    def send_chat_message(payload: dict):
        mobile = str(payload.get("mobile") or "").strip()
        content = str(payload.get("content") or "").strip()
        if (
            len(mobile) != 13
            or not mobile.startswith("+91")
            or not mobile[3:].isdigit()
        ):
            raise HTTPException(
                status_code=400,
                detail="mobile must be an Indian E.164 number such as +918286871533",
            )
        if not content or len(content) > 4096:
            raise HTTPException(
                status_code=400,
                detail="content must contain 1 to 4096 characters",
            )
        if not bot_webhook_url:
            raise HTTPException(
                status_code=503,
                detail="Mock chat has no bot webhook configured",
            )
        event = {
            "message_id": f"manual-{uuid.uuid4()}",
            "type": "text",
            "mobile": mobile,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "content": content,
        }
        try:
            result = http.post(
                bot_webhook_url,
                auth=(bot_webhook_user, bot_webhook_password),
                json=event,
                timeout=10,
            )
            body = result.json()
        except (requests.RequestException, ValueError) as error:
            raise HTTPException(
                status_code=502,
                detail=f"Could not call bot webhook: {error}",
            ) from error
        if not 200 <= result.status_code < 300:
            return JSONResponse(status_code=result.status_code, content=body)
        return {
            "status": body.get("status", "accepted"),
            "message_id": event["message_id"],
            "duplicate": bool(body.get("duplicate", False)),
        }

    @app.get("/mock/chat/replies")
    def chat_replies(mobile: str):
        with lock:
            replies = [
                item for item in state["replies"] if item.get("mobile") == mobile
            ]
        return {"replies": replies}

    @app.post("/mock/chat/clear")
    def clear_chat(payload: dict):
        mobile = str(payload.get("mobile") or "").strip()
        with lock:
            state["replies"] = [
                item for item in state["replies"] if item.get("mobile") != mobile
            ]
        return {"status": "ok"}

    @app.get("/mock/customers")
    def customers(mobile: str, _: None = Depends(authenticate)):
        with lock:
            delay = state["lookup_delay_seconds"]
        if delay:
            time.sleep(delay)
        with lock:
            state["lookups"].append(
                {
                    "mobile": mobile,
                    "timestamp": datetime.now(timezone.utc).isoformat(
                        timespec="milliseconds"
                    ),
                }
            )
            status_code = (
                state["lookup_statuses"].pop(0)
                if state["lookup_statuses"]
                else 200
            )
            matches = list(state["customers"].get(mobile) or [])
        if not 200 <= status_code < 300:
            return JSONResponse(
                status_code=status_code,
                content={"error": "configured lookup response"},
            )
        if not matches:
            return JSONResponse(status_code=404, content={"customers": []})
        return {"customers": matches}

    @app.post("/mock/replies")
    def replies(payload: dict, _: None = Depends(authenticate)):
        with lock:
            state["replies"].append(payload)
            status_code = (
                state["reply_statuses"].pop(0)
                if state["reply_statuses"]
                else 204
            )
        return Response(status_code=status_code)

    @app.get("/mock/state")
    def inspect_state(_: None = Depends(authenticate)):
        with lock:
            return {
                "lookups": list(state["lookups"]),
                "replies": list(state["replies"]),
            }

    @app.post("/mock/control/reply-statuses")
    def set_reply_statuses(payload: dict, _: None = Depends(authenticate)):
        statuses = payload.get("statuses")
        if not isinstance(statuses, list) or not all(
            isinstance(item, int) and 100 <= item <= 599 for item in statuses
        ):
            raise HTTPException(status_code=400, detail="statuses must be HTTP integers")
        with lock:
            state["reply_statuses"] = list(statuses)
        return {"status": "ok"}

    @app.post("/mock/control/customer")
    def set_customer(payload: dict, _: None = Depends(authenticate)):
        mobile = str(payload.get("mobile") or "")
        customers = payload.get("customers")
        if not mobile or not isinstance(customers, list):
            raise HTTPException(
                status_code=400,
                detail="mobile and customers list are required",
            )
        with lock:
            state["customers"][mobile] = list(customers)
        return {"status": "ok"}

    @app.post("/mock/control/lookup")
    def configure_lookup(payload: dict, _: None = Depends(authenticate)):
        statuses = payload.get("statuses") or []
        delay = payload.get("delay_seconds", 0)
        if not isinstance(statuses, list) or not all(
            isinstance(item, int) and 100 <= item <= 599 for item in statuses
        ):
            raise HTTPException(status_code=400, detail="statuses must be HTTP integers")
        if not isinstance(delay, (int, float)) or delay < 0:
            raise HTTPException(status_code=400, detail="delay_seconds must be positive")
        with lock:
            state["lookup_statuses"] = list(statuses)
            state["lookup_delay_seconds"] = float(delay)
        return {"status": "ok"}

    @app.post("/mock/control/reset")
    def reset(_: None = Depends(authenticate)):
        with lock:
            state["lookups"] = []
            state["replies"] = []
            state["reply_statuses"] = []
            state["lookup_statuses"] = []
            state["lookup_delay_seconds"] = 0.0
            state["customers"] = {
                key: list(value) for key, value in DEFAULT_CUSTOMERS.items()
            }
        return {"status": "ok"}

    @app.get("/mock/media/audio.mp3")
    def audio_fixture():
        return Response(content=b"ID3mock-audio", media_type="audio/mpeg")

    @app.get("/mock/media/document.jpg")
    def image_fixture():
        return Response(
            content=b"\xff\xd8\xff\xe0mock-document\xff\xd9",
            media_type="image/jpeg",
        )

    @app.get("/mock/media/{case}.jpg")
    def image_case_fixture(case: str):
        allowed = {"document", "unclear", "non-document", "multiple"}
        if case not in allowed:
            raise HTTPException(status_code=404, detail="Unknown fixture")
        return Response(
            content=b"\xff\xd8\xff\xe0" + case.encode() + b"\xff\xd9",
            media_type="image/jpeg",
        )

    return app


app = create_mock_client(
    username=os.environ.get("MOCK_CLIENT_USER", "mock-client"),
    password=os.environ.get("MOCK_CLIENT_PASSWORD", "mock-secret"),
    bot_webhook_url=os.environ.get("MOCK_BOT_WEBHOOK_URL", ""),
    bot_webhook_user=os.environ.get("CLIENT_WEBHOOK_USER", ""),
    bot_webhook_password=os.environ.get("CLIENT_WEBHOOK_PASSWORD", ""),
)


def _chat_page() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Webhook Test Chat</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: system-ui, sans-serif; background: #eef2f5; color: #182026; }
    .shell { max-width: 760px; height: 100vh; margin: auto; display: flex; flex-direction: column;
      background: white; box-shadow: 0 0 20px #0002; }
    header { padding: 14px 18px; background: #075e54; color: white; }
    header h1 { margin: 0; font-size: 18px; }
    header p { margin: 4px 0 0; opacity: .8; font-size: 12px; }
    .controls { display: flex; gap: 8px; padding: 10px; border-bottom: 1px solid #ddd; }
    .controls input { flex: 1; padding: 9px; }
    #messages { flex: 1; overflow-y: auto; padding: 18px; background: #efeae2;
      display: flex; flex-direction: column; gap: 9px; }
    .message { max-width: 78%; padding: 9px 12px; border-radius: 9px;
      white-space: pre-wrap; overflow-wrap: anywhere; }
    .user { align-self: flex-end; background: #d9fdd3; }
    .bot { align-self: flex-start; background: white; }
    .system { align-self: center; color: #666; font-size: 12px; background: #fff9; }
    form { display: flex; gap: 8px; padding: 12px; background: #f7f7f7; }
    form input { flex: 1; padding: 11px; border: 1px solid #bbb; border-radius: 20px; }
    button { border: 0; border-radius: 18px; padding: 9px 15px; cursor: pointer; }
    form button { background: #128c7e; color: white; }
  </style>
</head>
<body>
<main class="shell">
  <header>
    <h1>Webhook Test Chat</h1>
    <p>Mock client UI → real webhook → Redis worker → callback</p>
  </header>
  <section class="controls">
    <input id="mobile" value="+918286871533" aria-label="Test mobile">
    <button id="clear" type="button">Clear display</button>
  </section>
  <section id="messages">
    <div class="message system">Type below to send a webhook message.</div>
  </section>
  <form id="form">
    <input id="content" autocomplete="off" maxlength="4096" placeholder="Type a message…">
    <button type="submit">Send</button>
  </form>
</main>
<script>
const messages = document.getElementById('messages');
const mobile = document.getElementById('mobile');
const content = document.getElementById('content');
const seen = new Set();

function render(text, kind) {
  const item = document.createElement('div');
  item.className = 'message ' + kind;
  item.textContent = text;
  messages.appendChild(item);
  messages.scrollTop = messages.scrollHeight;
}

document.getElementById('form').addEventListener('submit', async event => {
  event.preventDefault();
  const text = content.value.trim();
  if (!text) return;
  render(text, 'user');
  content.value = '';
  const response = await fetch('/mock/chat/send', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({mobile: mobile.value.trim(), content: text}),
  });
  const body = await response.json();
  if (!response.ok) render('Error: ' + (body.detail || response.status), 'system');
});

async function poll() {
  try {
    const response = await fetch('/mock/chat/replies?mobile=' + encodeURIComponent(mobile.value.trim()));
    const body = await response.json();
    for (const reply of body.replies || []) {
      if (!seen.has(reply.message_id)) {
        seen.add(reply.message_id);
        render(reply.content, 'bot');
      }
    }
  } catch (_) {}
}
setInterval(poll, 750);
poll();

document.getElementById('clear').addEventListener('click', async () => {
  await fetch('/mock/chat/clear', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({mobile: mobile.value.trim()}),
  });
  seen.clear();
  messages.innerHTML = '<div class="message system">Display cleared. Server conversation memory remains active.</div>';
});
</script>
</body>
</html>"""

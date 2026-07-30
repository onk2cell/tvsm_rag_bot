"""Local/CI simulator for the client CRM and reply webhook (mock lab)."""
from __future__ import annotations

import os
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import requests
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

# Seeded CRM fixtures for the lab chat UI (mobile → customer list).
CRM_PRESETS: dict[str, dict[str, Any]] = {
    "returning_ev_max": {
        "label": "Returning — Onkar / King EV MAX",
        "mobile": "+918459522206",
        "customers": [
            {
                "customer_id": "313784",
                "name": "Onkar Game",
                "preferred_language": "English",
                "product_enquired": "King EV MAX",
                "dealership_id": "14302",
                "dealership_name": "JAM Research Services",
                "city": "Test City",
                "state": "Test State",
                "last_status": "Interested",
                "last_remark": (
                    "preferred_language: English | product_interest: King EV MAX"
                ),
            }
        ],
    },
    "asha_marathi": {
        "label": "Asha — Marathi preferred (no product)",
        "mobile": "+918286871533",
        "customers": [
            {
                "customer_id": "mock-customer-1",
                "name": "Asha",
                "preferred_language": "Marathi",
            }
        ],
    },
    "empty_language": {
        "label": "New lead — empty language + Deluxe",
        "mobile": "+919876543210",
        "customers": [
            {
                "customer_id": "lead-9876543210",
                "name": "Ravi Kumar",
                "preferred_language": "",
                "product_enquired": "King Deluxe",
                "last_status": "No Response",
                "last_remark": "",
            }
        ],
    },
    "dealer_assigned": {
        "label": "Dealer assigned — Interested",
        "mobile": "+917718904468",
        "customers": [
            {
                "customer_id": "307569",
                "name": "Ajit",
                "preferred_language": "Hindi",
                "product_enquired": "King Deluxe",
                "dealership_id": "11982",
                "dealership_name": "Sarthak Auto",
                "city": "Pune",
                "last_status": "Interested",
                "last_remark": "Asked for price",
            }
        ],
    },
    "unknown_number": {
        "label": "Unknown number (404 — not in CRM)",
        "mobile": "+919999000111",
        "customers": [],
    },
}

DEFAULT_CUSTOMERS = {
    preset["mobile"]: list(preset["customers"])
    for preset in CRM_PRESETS.values()
    if preset["customers"]
}


def create_mock_client(
    *,
    username: str,
    password: str,
    bot_webhook_url: str = "",
    bot_webhook_user: str = "",
    bot_webhook_password: str = "",
    redis_url: str = "",
    http=requests,
) -> FastAPI:
    app = FastAPI(title="Mock Client CRM Lab")
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
    redis_client = None
    if redis_url:
        try:
            from redis import Redis

            redis_client = Redis.from_url(redis_url, decode_responses=True)
        except Exception:
            redis_client = None

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

    @app.get("/mock/presets")
    def list_presets():
        return {
            "presets": [
                {
                    "id": key,
                    "label": value["label"],
                    "mobile": value["mobile"],
                    "customers": value["customers"],
                }
                for key, value in CRM_PRESETS.items()
            ]
        }

    @app.get("/mock/chat/crm")
    def get_crm(mobile: str):
        mobile = mobile.strip()
        with lock:
            customers = list(state["customers"].get(mobile) or [])
        return {"mobile": mobile, "customers": customers}

    @app.put("/mock/chat/crm")
    def put_crm(payload: dict):
        """Upsert CRM fixture for a mobile (lab UI — no auth for local convenience)."""
        mobile = str(payload.get("mobile") or "").strip()
        customers = payload.get("customers")
        if (
            len(mobile) != 13
            or not mobile.startswith("+91")
            or not mobile[3:].isdigit()
        ):
            raise HTTPException(
                status_code=400,
                detail="mobile must be an Indian E.164 number such as +918286871533",
            )
        if not isinstance(customers, list):
            raise HTTPException(status_code=400, detail="customers must be a list")
        cleaned = []
        for item in customers:
            if not isinstance(item, dict):
                raise HTTPException(status_code=400, detail="each customer must be an object")
            cleaned.append(dict(item))
        with lock:
            if cleaned:
                state["customers"][mobile] = cleaned
            else:
                state["customers"].pop(mobile, None)
        return {"status": "ok", "mobile": mobile, "customers": cleaned}

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

    @app.post("/mock/chat/reset")
    def reset_chat(payload: dict):
        """Clear replies + Redis bot session for this mobile (fresh 4h-idle start)."""
        mobile = str(payload.get("mobile") or "").strip()
        with lock:
            state["replies"] = [
                item for item in state["replies"] if item.get("mobile") != mobile
            ]
        deleted = 0
        if redis_client is not None and mobile:
            try:
                deleted = int(redis_client.delete(f"client:session:{mobile}") or 0)
            except Exception as error:
                raise HTTPException(
                    status_code=502,
                    detail=f"Could not clear Redis session: {error}",
                ) from error
        return {"status": "ok", "session_deleted": bool(deleted)}

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
    bot_webhook_user=os.environ.get(
        "MOCK_BOT_WEBHOOK_USER", os.environ.get("CLIENT_WEBHOOK_USER", "")
    ),
    bot_webhook_password=os.environ.get(
        "MOCK_BOT_WEBHOOK_PASSWORD", os.environ.get("CLIENT_WEBHOOK_PASSWORD", "")
    ),
    redis_url=os.environ.get("REDIS_URL", ""),
)


def _chat_page() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>WhatsApp Bot Lab</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: system-ui, sans-serif; background: #eef2f5; color: #182026; }
    .shell { max-width: 920px; height: 100vh; margin: auto; display: flex; flex-direction: column;
      background: white; box-shadow: 0 0 20px #0002; }
    header { padding: 14px 18px; background: #075e54; color: white; }
    header h1 { margin: 0; font-size: 18px; }
    header p { margin: 4px 0 0; opacity: .85; font-size: 12px; }
    .crm { padding: 12px; border-bottom: 1px solid #ddd; background: #f7faf9;
      display: grid; gap: 8px; grid-template-columns: 1fr 1fr; }
    .crm label { font-size: 12px; color: #445; display: flex; flex-direction: column; gap: 4px; }
    .crm .full { grid-column: 1 / -1; }
    .crm input, .crm select, .crm textarea {
      padding: 8px; border: 1px solid #bbb; border-radius: 8px; font: inherit; }
    .crm textarea { min-height: 110px; font-family: ui-monospace, monospace; font-size: 12px; }
    .crm .row { display: flex; gap: 8px; flex-wrap: wrap; }
    .crm button { border: 0; border-radius: 14px; padding: 8px 12px; cursor: pointer;
      background: #128c7e; color: white; }
    .crm button.secondary { background: #546e7a; }
    .controls { display: flex; gap: 8px; padding: 10px; border-bottom: 1px solid #ddd; }
    .controls input { flex: 1; padding: 9px; }
    #messages { flex: 1; overflow-y: auto; padding: 18px; background: #efeae2;
      display: flex; flex-direction: column; gap: 9px; }
    .message { max-width: 78%; padding: 9px 12px; border-radius: 9px;
      white-space: pre-wrap; overflow-wrap: anywhere; }
    .user { align-self: flex-end; background: #d9fdd3; }
    .bot { align-self: flex-start; background: white; }
    .system { align-self: center; color: #666; font-size: 12px; background: #fff9; }
    form.send { display: flex; gap: 8px; padding: 12px; background: #f7f7f7; }
    form.send input { flex: 1; padding: 11px; border: 1px solid #bbb; border-radius: 20px; }
    form.send button { border: 0; border-radius: 18px; padding: 9px 15px; cursor: pointer;
      background: #128c7e; color: white; }
  </style>
</head>
<body>
<main class="shell">
  <header>
    <h1>WhatsApp Bot Lab</h1>
    <p>Pick mobile + CRM data → real webhook → Redis worker → mock replies</p>
  </header>
  <section class="crm">
    <label>Preset
      <select id="preset"><option value="">Custom…</option></select>
    </label>
    <label>Mobile (+91…)
      <input id="mobile" value="+918459522206">
    </label>
    <label class="full">CRM customer JSON (array of one object)
      <textarea id="crmJson" spellcheck="false"></textarea>
    </label>
    <div class="full row">
      <button id="saveCrm" type="button">Save CRM for this mobile</button>
      <button id="resetSession" class="secondary" type="button">Reset session (fresh chat)</button>
      <button id="clear" class="secondary" type="button">Clear display</button>
    </div>
  </section>
  <section id="messages">
    <div class="message system">Save CRM, then type below. Use Reset session to simulate 4h idle expiry.</div>
  </section>
  <form class="send" id="form">
    <input id="content" autocomplete="off" maxlength="4096" placeholder="Type a WhatsApp message…">
    <button type="submit">Send</button>
  </form>
</main>
<script>
const messages = document.getElementById('messages');
const mobile = document.getElementById('mobile');
const content = document.getElementById('content');
const crmJson = document.getElementById('crmJson');
const preset = document.getElementById('preset');
const seen = new Set();
let presets = {};

function render(text, kind) {
  const item = document.createElement('div');
  item.className = 'message ' + kind;
  item.textContent = text;
  messages.appendChild(item);
  messages.scrollTop = messages.scrollHeight;
}

function defaultCustomer() {
  return [{
    customer_id: 'lab-1',
    name: 'Test User',
    preferred_language: '',
    product_enquired: '',
    dealership_id: '',
    dealership_name: '',
    city: '',
    state: '',
    last_status: '',
    last_remark: ''
  }];
}

async function loadPresets() {
  const response = await fetch('/mock/presets');
  const body = await response.json();
  presets = {};
  for (const item of body.presets || []) {
    presets[item.id] = item;
    const opt = document.createElement('option');
    opt.value = item.id;
    opt.textContent = item.label;
    preset.appendChild(opt);
  }
  const first = body.presets && body.presets[0];
  if (first) {
    preset.value = first.id;
    applyPreset(first.id);
  } else {
    crmJson.value = JSON.stringify(defaultCustomer(), null, 2);
  }
}

function applyPreset(id) {
  const item = presets[id];
  if (!item) return;
  mobile.value = item.mobile;
  crmJson.value = JSON.stringify(item.customers, null, 2);
}

preset.addEventListener('change', () => {
  if (preset.value) applyPreset(preset.value);
});

document.getElementById('saveCrm').addEventListener('click', async () => {
  let customers;
  try {
    customers = JSON.parse(crmJson.value);
  } catch (error) {
    render('CRM JSON invalid: ' + error, 'system');
    return;
  }
  const response = await fetch('/mock/chat/crm', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({mobile: mobile.value.trim(), customers}),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    render('Save failed: ' + (body.detail || response.status), 'system');
    return;
  }
  render('CRM saved for ' + mobile.value.trim(), 'system');
});

document.getElementById('resetSession').addEventListener('click', async () => {
  await fetch('/mock/chat/reset', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({mobile: mobile.value.trim()}),
  });
  seen.clear();
  messages.innerHTML = '';
  render('Session + replies cleared for ' + mobile.value.trim() + '. Fresh conversation.', 'system');
});

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
  const body = await response.json().catch(() => ({}));
  if (!response.ok) render('Error: ' + (body.detail || response.status), 'system');
});

async function poll() {
  try {
    const response = await fetch('/mock/chat/replies?mobile=' + encodeURIComponent(mobile.value.trim()));
    const body = await response.json();
    for (const reply of body.replies || []) {
      const key = reply.message_id || JSON.stringify(reply);
      if (!seen.has(key)) {
        seen.add(key);
        let text = reply.content || reply.message || '';
        const media = reply.media_url || reply.url || reply.document_url || reply.image_url;
        if (media) text = (text ? text + '\\n' : '') + '[' + (reply.type || 'media') + '] ' + media;
        if (!text) text = JSON.stringify(reply);
        render(text, 'bot');
      }
    }
  } catch (_) {}
}
setInterval(poll, 750);

document.getElementById('clear').addEventListener('click', async () => {
  await fetch('/mock/chat/clear', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({mobile: mobile.value.trim()}),
  });
  seen.clear();
  messages.innerHTML = '<div class="message system">Display cleared. Use Reset session to wipe bot memory.</div>';
});

loadPresets();
poll();
</script>
</body>
</html>"""

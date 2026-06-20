"""WhatsApp Cloud API helpers: send text, mark read, verify webhook signature.

If you use a BSP (AiSensy / Gupshup / etc.), replace the body of `_post` and the
URL with their send endpoint. The rest of the app does not change.
"""
import hashlib
import hmac

import requests

import config

BASE = f"https://graph.facebook.com/{config.GRAPH_VERSION}/{config.PHONE_NUMBER_ID}/messages"
HEADERS = {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"}


def send_text(to: str, text: str) -> None:
    # WhatsApp caps a text body at 4096 chars; split long answers into parts.
    for part in _split(text, 4096):
        _post({
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": part},
        })


def mark_read(message_id: str) -> None:
    _post({
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    })


def verify_signature(raw_body: bytes, signature_header: str) -> bool:
    """Validate Meta's X-Hub-Signature-256 header.

    Returns True (skips the check) if APP_SECRET is unset — fine for local testing,
    but set APP_SECRET in production so others can't POST fake messages to you.
    """
    if not config.APP_SECRET:
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(config.APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.split("=", 1)[1])


def _post(payload: dict):
    for attempt in range(3):
        try:
            resp = requests.post(BASE, headers=HEADERS, json=payload, timeout=20)
            if resp.status_code < 500:        # retry only on server-side failures
                return resp
        except requests.RequestException:
            pass
    return None


def _split(text: str, n: int) -> list:
    return [text[i:i + n] for i in range(0, len(text), n)] or [""]

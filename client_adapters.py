"""Production adapters for client CRM lookup, callbacks, and Redis state."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Callable

import requests

from client_processing import ClientSession, Customer


class CustomerLookupError(RuntimeError):
    pass


class ReplyDeliveryError(RuntimeError):
    pass


class HttpCustomerDirectory:
    def __init__(
        self,
        url: str,
        *,
        username: str = "",
        password: str = "",
        timeout: float = 30,
        retry_wait: float = 30,
        http=requests,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._url = url
        self._auth = (username, password) if username or password else None
        self._timeout = timeout
        self._retry_wait = retry_wait
        self._http = http
        self._sleep = sleep

    def lookup(self, mobile: str) -> Customer:
        last_error = "customer lookup failed"
        for attempt in range(3):
            try:
                response = self._http.get(
                    self._url,
                    params={"mobile": mobile},
                    auth=self._auth,
                    timeout=self._timeout,
                )
                if 200 <= response.status_code < 300:
                    return _customer_from_response(response.json())
                last_error = f"customer API returned HTTP {response.status_code}"
                if response.status_code < 500:
                    break
            except (requests.RequestException, ValueError, KeyError, TypeError) as error:
                last_error = str(error)
            if attempt < 2:
                self._sleep(self._retry_wait)
        raise CustomerLookupError(last_error)


def _customer_from_response(payload) -> Customer:
    if isinstance(payload, list):
        matches = payload
    elif isinstance(payload, dict) and isinstance(payload.get("customers"), list):
        matches = payload["customers"]
    elif isinstance(payload, dict):
        matches = [payload]
    else:
        matches = []
    if not matches:
        raise CustomerLookupError("customer API returned no customer")
    first = matches[0]
    customer_id = str(first.get("customer_id") or first.get("id") or "").strip()
    name = str(first.get("name") or first.get("customer_name") or "").strip()
    if not customer_id or not name:
        raise CustomerLookupError("customer API response is missing id or name")
    return Customer(
        customer_id=customer_id,
        name=name,
        preferred_language=str(first.get("preferred_language") or "").strip(),
    )


class HttpReplySender:
    def __init__(
        self,
        url: str,
        *,
        username: str = "",
        password: str = "",
        timeout: float = 30,
        retry_wait: float = 30,
        http=requests,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._url = url
        self._auth = (username, password) if username or password else None
        self._timeout = timeout
        self._retry_wait = retry_wait
        self._http = http
        self._sleep = sleep

    def send(self, *, mobile: str, in_reply_to: str, text: str) -> None:
        parts = _split_text(text, 4096)
        for index, part in enumerate(parts, start=1):
            payload = {
                "message_id": str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"tvsm-client-reply:{in_reply_to}:{index}",
                    )
                ),
                "in_reply_to": in_reply_to,
                "type": "text",
                "mobile": mobile,
                "content": part,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "part_number": index,
                "part_count": len(parts),
            }
            self._deliver(payload)

    def _deliver(self, payload: dict) -> None:
        last_error = "reply callback failed"
        for attempt in range(3):
            try:
                response = self._http.post(
                    self._url,
                    json=payload,
                    auth=self._auth,
                    timeout=self._timeout,
                )
                if 200 <= response.status_code < 300:
                    return
                last_error = f"reply webhook returned HTTP {response.status_code}"
            except requests.RequestException as error:
                last_error = str(error)
            if attempt < 2:
                self._sleep(self._retry_wait)
        raise ReplyDeliveryError(last_error)


def _split_text(text: str, limit: int) -> list[str]:
    return [text[index : index + limit] for index in range(0, len(text), limit)] or [""]


class RedisClientState:
    def __init__(
        self,
        redis,
        *,
        ttl_seconds: int = 3600,
        id_factory: Callable[[], str] | None = None,
    ):
        self._redis = redis
        self._ttl_seconds = ttl_seconds
        self._id_factory = id_factory or (lambda: f"client-{uuid.uuid4().hex}")

    def load_or_start(self, mobile: str) -> ClientSession:
        raw = self._redis.get(self._key(mobile))
        if raw:
            if isinstance(raw, bytes):
                raw = raw.decode()
            data = json.loads(raw)
            customer_data = data.get("customer")
            customer = Customer(**customer_data) if customer_data else None
            return ClientSession(
                conversation_id=data["conversation_id"],
                mobile=data["mobile"],
                customer=customer,
                history=list(data.get("history") or []),
                unclear_document_count=int(
                    data.get("unclear_document_count") or 0
                ),
                pending_replies=dict(data.get("pending_replies") or {}),
            )
        return ClientSession(
            conversation_id=self._id_factory(),
            mobile=mobile,
        )

    def save(self, session: ClientSession) -> None:
        payload = {
            "conversation_id": session.conversation_id,
            "mobile": session.mobile,
            "customer": asdict(session.customer) if session.customer else None,
            "history": session.history,
            "unclear_document_count": session.unclear_document_count,
            "pending_replies": session.pending_replies,
        }
        self._redis.set(
            self._key(session.mobile),
            json.dumps(payload, ensure_ascii=False),
            ex=self._ttl_seconds,
        )

    @staticmethod
    def _key(mobile: str) -> str:
        return f"client:session:{mobile}"

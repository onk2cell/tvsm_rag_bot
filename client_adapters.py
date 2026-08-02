"""Production adapters for client CRM lookup, callbacks, and Redis state."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, fields
from datetime import datetime, timezone
from typing import Callable

import requests

from client_language import (
    extract_customer_name,
    extract_preferred_language,
    extract_state,
    language_from_remark,
)
from client_processing import ClientSession, Customer


class CustomerLookupError(RuntimeError):
    pass


class ReplyDeliveryError(RuntimeError):
    pass


class DisposeDeliveryError(RuntimeError):
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
    if not isinstance(first, dict):
        raise CustomerLookupError("customer API response is missing id or name")
    customer_id = str(first.get("customer_id") or first.get("id") or "").strip()
    name = str(first.get("name") or first.get("customer_name") or "").strip()
    if not customer_id or not name:
        raise CustomerLookupError("customer API response is missing id or name")
    last_remark = str(
        first.get("last_remark")
        or first.get("fldt_last_comment")
        or first.get("remark")
        or ""
    ).strip()
    preferred = (
        str(first.get("preferred_language") or "").strip()
        or language_from_remark(last_remark)
    )
    return Customer(
        customer_id=customer_id,
        name=name,
        preferred_language=preferred,
        product_enquired=str(first.get("product_enquired") or "").strip(),
        dealership_id=str(first.get("dealership_id") or "").strip(),
        dealership_name=str(first.get("dealership_name") or "").strip(),
        city=str(first.get("city") or "").strip(),
        state=str(first.get("state") or "").strip(),
        last_remark=last_remark,
        last_status=str(
            first.get("last_status") or first.get("fldv_last_status") or ""
        ).strip(),
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

    def send_image(self, *, mobile: str, link: str, caption: str = "") -> None:
        # Legacy callback path has no image contract; fall back to caption/link text.
        text = caption.strip() if caption else f"Please open this link: {link}"
        self.send(mobile=mobile, in_reply_to="image", text=text)

    def send_document(self, *, mobile: str, link: str, caption: str = "") -> None:
        text = caption.strip() if caption else f"Please open this document: {link}"
        self.send(mobile=mobile, in_reply_to="document", text=text)

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


class JamWhatsAppReplySender:
    """Outbound sender for JAM WhatsApp Bot send API (X-API-KEY)."""

    def __init__(
        self,
        url: str,
        *,
        api_key: str,
        timeout: float = 30,
        retry_wait: float = 30,
        http=requests,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._url = url
        self._api_key = api_key
        self._timeout = timeout
        self._retry_wait = retry_wait
        self._http = http
        self._sleep = sleep

    def send(self, *, mobile: str, in_reply_to: str, text: str) -> None:
        del in_reply_to  # JAM send API correlates by mobile only
        for part in _split_text(text, 4096):
            self._deliver(
                {
                    "mobile": _jam_mobile(mobile),
                    "type": "text",
                    "message": part,
                }
            )

    def send_image(self, *, mobile: str, link: str, caption: str = "") -> None:
        payload = {
            "mobile": _jam_mobile(mobile),
            "type": "image",
            "link": link,
        }
        if caption.strip():
            payload["message"] = caption.strip()
        self._deliver(payload)

    def send_document(self, *, mobile: str, link: str, caption: str = "") -> None:
        payload = {
            "mobile": _jam_mobile(mobile),
            "type": "document",
            "link": link,
        }
        if caption.strip():
            payload["message"] = caption.strip()
        self._deliver(payload)

    def _deliver(self, payload: dict) -> None:
        last_error = "JAM WhatsApp send failed"
        for attempt in range(3):
            try:
                response = self._http.post(
                    self._url,
                    json=payload,
                    headers={
                        "X-API-KEY": self._api_key,
                        "Content-Type": "application/json",
                    },
                    timeout=self._timeout,
                )
                if response.status_code == 200:
                    body = _safe_json(response)
                    if isinstance(body, dict) and body.get("status") == "success":
                        return
                    last_error = f"JAM send rejected payload: {body}"
                else:
                    last_error = f"JAM send returned HTTP {response.status_code}"
            except (requests.RequestException, ValueError, TypeError) as error:
                last_error = str(error)
            if attempt < 2:
                self._sleep(self._retry_wait)
        raise ReplyDeliveryError(last_error)


class JamDisposeClient:
    """Outbound client for JAM WhatsApp Bot dispose API (X-API-KEY)."""

    def __init__(
        self,
        url: str,
        *,
        api_key: str,
        timeout: float = 30,
        retry_wait: float = 30,
        http=requests,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._url = url
        self._api_key = api_key
        self._timeout = timeout
        self._retry_wait = retry_wait
        self._http = http
        self._sleep = sleep

    def dispose(self, payload: dict) -> dict:
        body = dict(payload)
        if "mobile" in body:
            body["mobile"] = _jam_mobile(str(body["mobile"]))
        last_error = "JAM dispose failed"
        for attempt in range(3):
            try:
                response = self._http.post(
                    self._url,
                    json=body,
                    headers={
                        "X-API-KEY": self._api_key,
                        "Content-Type": "application/json",
                    },
                    timeout=self._timeout,
                )
                parsed = _safe_json(response)
                if response.status_code == 200:
                    if isinstance(parsed, dict) and parsed.get("status") == "success":
                        return parsed if isinstance(parsed, dict) else {"status": "success"}
                    last_error = f"JAM dispose rejected payload: {parsed}"
                elif response.status_code == 404:
                    # Still attempted — caller may treat as soft failure.
                    raise DisposeDeliveryError(
                        f"JAM dispose returned HTTP 404: {parsed}"
                    )
                else:
                    last_error = f"JAM dispose returned HTTP {response.status_code}"
                    if response.status_code < 500 and response.status_code != 429:
                        break
            except DisposeDeliveryError:
                raise
            except (requests.RequestException, ValueError, TypeError) as error:
                last_error = str(error)
            if attempt < 2:
                self._sleep(self._retry_wait)
        raise DisposeDeliveryError(last_error)


class StubCustomerDirectory:
    """Temporary identity when client CRM lookup API is not ready yet."""

    def lookup(self, mobile: str) -> Customer:
        digits = "".join(ch for ch in mobile if ch.isdigit())
        display = digits[2:] if digits.startswith("91") and len(digits) > 2 else digits
        return Customer(
            customer_id=f"stub-{digits or 'unknown'}",
            name=f"Customer {display or mobile}",
            preferred_language="English",
        )


class JamCustomerDirectory:
    """JAM WhatsApp Bot Get Customer Details (`POST /whatsapp_bot/customer`)."""

    def __init__(
        self,
        url: str,
        *,
        api_key: str,
        timeout: float = 30,
        retry_wait: float = 30,
        http=requests,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._url = url
        self._api_key = api_key
        self._timeout = timeout
        self._retry_wait = retry_wait
        self._http = http
        self._sleep = sleep

    def lookup(self, mobile: str) -> Customer:
        last_error = "customer lookup failed"
        for attempt in range(3):
            try:
                response = self._http.post(
                    self._url,
                    json={"mobile": _jam_mobile(mobile)},
                    headers={
                        "X-API-KEY": self._api_key,
                        "Content-Type": "application/json",
                    },
                    timeout=self._timeout,
                )
                if response.status_code == 404:
                    return _stub_customer(mobile, preferred_language="")
                if response.status_code == 200:
                    body = _safe_json(response)
                    if not isinstance(body, dict):
                        raise CustomerLookupError("customer API returned invalid JSON")
                    if body.get("status") == "fail":
                        return _stub_customer(mobile, preferred_language="")
                    data = body.get("data") if isinstance(body.get("data"), dict) else body
                    return _customer_from_jam_data(data, mobile=mobile)
                last_error = f"customer API returned HTTP {response.status_code}"
                if response.status_code < 500:
                    break
            except (requests.RequestException, ValueError, TypeError, KeyError) as error:
                last_error = str(error)
            if attempt < 2:
                self._sleep(self._retry_wait)
        raise CustomerLookupError(last_error)


def _stub_customer(mobile: str, *, preferred_language: str) -> Customer:
    digits = "".join(ch for ch in mobile if ch.isdigit())
    display = digits[2:] if digits.startswith("91") and len(digits) > 2 else digits
    return Customer(
        customer_id=f"unknown-{digits or 'unknown'}",
        name=f"Customer {display or mobile}",
        preferred_language=preferred_language,
    )


def _jam_field(data: dict, *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() not in {"null", "none", "n/a"}:
            return text
    return ""


def _customer_from_jam_data(data: dict, *, mobile: str) -> Customer:
    lead_id = data.get("fldi_lead_id") or data.get("customer_id") or data.get("id")
    name = extract_customer_name(data)
    if not name:
        name = _stub_customer(mobile, preferred_language="").name
    customer_id = str(lead_id or "").strip() or f"lead-{_jam_mobile(mobile)}"

    last_remark = _jam_field(
        data,
        "fldt_last_comment",
        "remark",
        "Remark",
        "last_comment",
        "Last Comment",
        "Last Remark",
    )
    # Prefer an explicit CRM language field; else recover what we last wrote
    # into dispose remarks. Never invent language from State (Maharashtra≠Marathi).
    preferred = extract_preferred_language(data) or language_from_remark(last_remark)
    return Customer(
        customer_id=customer_id,
        name=name,
        preferred_language=preferred,
        product_enquired=_jam_field(data, "Product Enquired", "product_enquired"),
        dealership_id=_jam_field(
            data, "Dealership Id", "Dealership ID", "dealership_id", "dealer_code"
        ),
        dealership_name=_jam_field(data, "Dealership Name", "dealership_name"),
        city=_jam_field(data, "City", "city"),
        state=_jam_field(data, "State", "state") or extract_state(data),
        last_remark=last_remark,
        last_status=_jam_field(
            data,
            "fldv_last_status",
            "last_status",
            "Last Status",
            "status",
        ),
    )


def _jam_mobile(mobile: str) -> str:
    digits = "".join(ch for ch in mobile if ch.isdigit())
    if digits.startswith("91") and len(digits) == 12:
        return digits
    if len(digits) == 10:
        return "91" + digits
    return digits


def _safe_json(response):
    try:
        return response.json()
    except ValueError:
        return None


def _split_text(text: str, limit: int) -> list[str]:
    return [text[index : index + limit] for index in range(0, len(text), limit)] or [""]


class RedisClientState:
    def __init__(
        self,
        redis,
        *,
        ttl_seconds: int = 14400,
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
            customer = None
            if customer_data:
                allowed = {item.name for item in fields(Customer)}
                customer = Customer(
                    **{key: value for key, value in customer_data.items() if key in allowed}
                )
            return ClientSession(
                conversation_id=data["conversation_id"],
                mobile=data["mobile"],
                customer=customer,
                history=list(data.get("history") or []),
                unclear_document_count=int(
                    data.get("unclear_document_count") or 0
                ),
                pending_replies=dict(data.get("pending_replies") or {}),
                language=str(data.get("language") or ""),
                awaiting_language_selection=bool(
                    data.get("awaiting_language_selection") or False
                ),
                dealer_shared_for_pincode=str(
                    data.get("dealer_shared_for_pincode") or ""
                ),
                last_dealer_code=str(data.get("last_dealer_code") or ""),
                dispose_sent=bool(data.get("dispose_sent") or False),
                last_dispose_fingerprint=str(
                    data.get("last_dispose_fingerprint") or ""
                ),
                lead_profile=dict(data.get("lead_profile") or {}),
                brochures_sent=list(data.get("brochures_sent") or []),
                share_location_guide_sent=bool(
                    data.get("share_location_guide_sent") or False
                ),
                invalid_pincode_attempts=int(
                    data.get("invalid_pincode_attempts") or 0
                ),
                awaiting_dealer_confirm=bool(
                    data.get("awaiting_dealer_confirm") or False
                ),
                dealer_confirm_deferred=bool(
                    data.get("dealer_confirm_deferred") or False
                ),
                crm_dealer_offered=bool(data.get("crm_dealer_offered") or False),
                awaiting_dealer_share_consent=bool(
                    data.get("awaiting_dealer_share_consent") or False
                ),
                dealer_share_asked=bool(data.get("dealer_share_asked") or False),
                dealer_share_declined=bool(
                    data.get("dealer_share_declined") or False
                ),
                pending_dealer_share_code=str(
                    data.get("pending_dealer_share_code") or ""
                ),
                dealer_confirmed=bool(data.get("dealer_confirmed") or False),
                callback_requested=bool(data.get("callback_requested") or False),
                welcome_back_sent=bool(data.get("welcome_back_sent") or False),
                awaiting_still_interested=bool(
                    data.get("awaiting_still_interested") or False
                ),
                still_interested_asked=bool(
                    data.get("still_interested_asked") or False
                ),
                awaiting_brochure_offer=bool(
                    data.get("awaiting_brochure_offer") or False
                ),
                pending_brochure_product=str(
                    data.get("pending_brochure_product") or ""
                ),
                awaiting_brochure_product_choice=bool(
                    data.get("awaiting_brochure_product_choice") or False
                ),
                qualification_started=bool(
                    data.get("qualification_started") or False
                ),
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
            "language": session.language,
            "awaiting_language_selection": session.awaiting_language_selection,
            "dealer_shared_for_pincode": session.dealer_shared_for_pincode,
            "last_dealer_code": session.last_dealer_code,
            "dispose_sent": session.dispose_sent,
            "last_dispose_fingerprint": session.last_dispose_fingerprint,
            "lead_profile": session.lead_profile,
            "brochures_sent": session.brochures_sent,
            "share_location_guide_sent": session.share_location_guide_sent,
            "invalid_pincode_attempts": session.invalid_pincode_attempts,
            "awaiting_dealer_confirm": session.awaiting_dealer_confirm,
            "dealer_confirm_deferred": session.dealer_confirm_deferred,
            "crm_dealer_offered": session.crm_dealer_offered,
            "awaiting_dealer_share_consent": session.awaiting_dealer_share_consent,
            "dealer_share_asked": session.dealer_share_asked,
            "dealer_share_declined": session.dealer_share_declined,
            "pending_dealer_share_code": session.pending_dealer_share_code,
            "dealer_confirmed": session.dealer_confirmed,
            "callback_requested": session.callback_requested,
            "welcome_back_sent": session.welcome_back_sent,
            "awaiting_still_interested": session.awaiting_still_interested,
            "still_interested_asked": session.still_interested_asked,
            "awaiting_brochure_offer": session.awaiting_brochure_offer,
            "pending_brochure_product": session.pending_brochure_product,
            "awaiting_brochure_product_choice": (
                session.awaiting_brochure_product_choice
            ),
            "qualification_started": session.qualification_started,
        }
        self._redis.set(
            self._key(session.mobile),
            json.dumps(payload, ensure_ascii=False),
            ex=self._ttl_seconds,
        )

    @staticmethod
    def _key(mobile: str) -> str:
        return f"client:session:{mobile}"

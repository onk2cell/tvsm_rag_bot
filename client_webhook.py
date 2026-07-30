"""Inbound webhook for messages sent by the client's app/CRM."""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timezone
from typing import Protocol

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict, Field, field_validator

from client_media import ALLOWED_AUDIO_MIME_TYPES, ALLOWED_IMAGE_MIME_TYPES


SUPPORTED_MESSAGE_TYPES = frozenset({"text", "image", "audio", "location"})
INDIAN_E164_PATTERN = r"^\+91[6-9][0-9]{9}$"


class InboundMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    message_id: str = Field(min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=32)
    mobile: str = Field(pattern=INDIAN_E164_PATTERN)
    timestamp: str = Field(min_length=1, max_length=128)
    content: str | None = Field(default=None, max_length=4096)
    media_url: str | None = Field(default=None, max_length=2048)
    mime_type: str | None = Field(default=None, max_length=128)
    latitude: float | None = None
    longitude: float | None = None
    lat: float | None = None
    lng: float | None = None

    @field_validator("type")
    @classmethod
    def normalize_type(cls, value: str) -> str:
        return value.strip().lower()


class Deduplicator(Protocol):
    def claim(self, message_id: str) -> bool: ...

    def release(self, message_id: str) -> None: ...


class EventPublisher(Protocol):
    def publish(self, event: dict) -> None: ...


class RateLimiter(Protocol):
    def allow(self, mobile: str) -> bool: ...


class RedisDeduplicator:
    def __init__(
        self,
        redis,
        *,
        ttl_seconds: int = 7 * 24 * 3600,
        processing_ttl_seconds: int = 10 * 60,
    ):
        self._redis = redis
        self._ttl_seconds = ttl_seconds
        self._processing_ttl_seconds = processing_ttl_seconds

    def claim(self, message_id: str) -> bool:
        return bool(
            self._redis.set(
                f"client:seen:{message_id}",
                "processing",
                nx=True,
                ex=min(self._ttl_seconds, self._processing_ttl_seconds),
            )
        )

    def release(self, message_id: str) -> None:
        self._redis.delete(f"client:seen:{message_id}")


class RqEventPublisher:
    def __init__(self, queue):
        self._queue = queue

    def publish(self, event: dict) -> None:
        from rq import Retry

        self._queue.enqueue(
            "client_tasks.handle_client_message",
            event,
            retry=Retry(max=2, interval=[30, 30]),
        )


class RedisRateLimiter:
    def __init__(self, redis, *, limit: int = 12):
        self._redis = redis
        self._limit = limit

    def allow(self, mobile: str) -> bool:
        key = f"client:rate:{mobile}:{int(time.time() // 60)}"
        count = self._redis.incr(key)
        if count == 1:
            self._redis.expire(key, 60)
        return count <= self._limit


def _payload_errors(event: InboundMessage) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if event.type == "text" and not (event.content or "").strip():
        errors.append({"field": "content", "message": "content is required for text"})
    if event.type in {"image", "audio"}:
        if not (event.media_url or "").strip():
            errors.append(
                {"field": "media_url", "message": "media_url is required for media"}
            )
        if (event.mime_type or "").strip():
            normalized_mime = event.mime_type.split(";", 1)[0].strip().lower()
            allowed = (
                ALLOWED_IMAGE_MIME_TYPES
                if event.type == "image"
                else ALLOWED_AUDIO_MIME_TYPES
            )
            if normalized_mime not in allowed:
                errors.append(
                    {
                        "field": "mime_type",
                        "message": f"mime_type is not supported for {event.type}",
                    }
                )
    # Location: accept even without coords (JAM may omit them); processor asks for pincode.
    if event.type == "location":
        for field_name in ("latitude", "longitude", "lat", "lng"):
            value = getattr(event, field_name, None)
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                errors.append(
                    {"field": field_name, "message": f"{field_name} must be a number"}
                )
                continue
            if field_name in {"latitude", "lat"} and not (-90.0 <= number <= 90.0):
                errors.append(
                    {"field": field_name, "message": "latitude must be between -90 and 90"}
                )
            if field_name in {"longitude", "lng"} and not (-180.0 <= number <= 180.0):
                errors.append(
                    {
                        "field": field_name,
                        "message": "longitude must be between -180 and 180",
                    }
                )
    return errors


def create_app(
    *,
    username: str,
    password: str,
    deduplicator: Deduplicator,
    publisher: EventPublisher,
    rate_limiter: RateLimiter,
) -> FastAPI:
    app = FastAPI(title="TVS Client App Webhook")
    security = HTTPBasic(auto_error=True)

    def authenticate(
        credentials: HTTPBasicCredentials = Depends(security),
    ) -> None:
        valid = bool(username and password)
        valid = valid and secrets.compare_digest(credentials.username, username)
        valid = valid and secrets.compare_digest(credentials.password, password)
        if not valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid client webhook credentials",
                headers={"WWW-Authenticate": 'Basic realm="client-webhook"'},
            )

    @app.exception_handler(RequestValidationError)
    async def invalid_payload(request: Request, error: RequestValidationError):
        # #region agent log
        try:
            import json as _json
            from pathlib import Path as _Path

            raw_body = await request.body()
            preview = raw_body[:2000].decode("utf-8", errors="replace")
            _payload = {
                "sessionId": "dealers-grill",
                "location": "client_webhook.py:validation_error",
                "message": "inbound validation failed",
                "data": {
                    "errors": [
                        {
                            "field": ".".join(str(p) for p in item.get("loc", ())),
                            "msg": item.get("msg"),
                        }
                        for item in error.errors()[:12]
                    ],
                    "body_preview": preview,
                },
            }
            for _p in (
                _Path("data/debug-inbound-location.log"),
                _Path("/app/data/debug-inbound-location.log"),
            ):
                try:
                    _p.parent.mkdir(parents=True, exist_ok=True)
                    with _p.open("a", encoding="utf-8") as _f:
                        _f.write(_json.dumps(_payload, ensure_ascii=False) + "\n")
                except Exception:
                    pass
        except Exception:
            pass
        # #endregion
        errors = []
        for item in error.errors():
            location = [str(part) for part in item.get("loc", ()) if part != "body"]
            errors.append(
                {
                    "field": ".".join(location) or "body",
                    "message": item.get("msg", "Invalid value"),
                }
            )
        return JSONResponse(
            status_code=400,
            content={"code": "invalid_payload", "errors": errors},
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/client/webhook/messages", status_code=202)
    def receive_message(
        event: InboundMessage,
        _: None = Depends(authenticate),
    ):
        # #region agent log
        try:
            import json as _json
            from pathlib import Path as _Path

            dumped = event.model_dump(exclude_none=False)
            safe = {
                k: (
                    "<redacted>"
                    if k in {"mobile", "content"} and dumped.get(k)
                    else dumped.get(k)
                )
                for k in dumped
            }
            # keep mobile last4 for correlation only
            mobile = str(dumped.get("mobile") or "")
            safe["mobile_suffix"] = mobile[-4:] if mobile else ""
            _payload = {
                "sessionId": "dealers-grill",
                "location": "client_webhook.py:receive_message",
                "message": "inbound webhook event",
                "data": {
                    "type": dumped.get("type"),
                    "keys": sorted(dumped.keys()),
                    "supported": dumped.get("type") in SUPPORTED_MESSAGE_TYPES,
                    "payload": safe,
                },
            }
            for _p in (
                _Path("data/debug-inbound-location.log"),
                _Path("/app/data/debug-inbound-location.log"),
            ):
                try:
                    _p.parent.mkdir(parents=True, exist_ok=True)
                    with _p.open("a", encoding="utf-8") as _f:
                        _f.write(_json.dumps(_payload, ensure_ascii=False) + "\n")
                except Exception:
                    pass
        except Exception:
            pass
        # #endregion
        if event.type not in SUPPORTED_MESSAGE_TYPES:
            return {
                "status": "ignored",
                "message_id": event.message_id,
                "duplicate": False,
                "reason": "unsupported_type",
            }

        errors = _payload_errors(event)
        if errors:
            return JSONResponse(
                status_code=400,
                content={"code": "invalid_payload", "errors": errors},
            )

        if not deduplicator.claim(event.message_id):
            return {
                "status": "duplicate",
                "message_id": event.message_id,
                "duplicate": True,
            }

        if not rate_limiter.allow(event.mobile):
            deduplicator.release(event.message_id)
            return JSONResponse(
                status_code=429,
                content={
                    "code": "rate_limited",
                    "message": "Too many messages for this mobile",
                },
            )

        payload = event.model_dump(exclude_none=True)
        payload["received_at"] = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        try:
            publisher.publish(payload)
        except Exception as error:
            deduplicator.release(event.message_id)
            raise HTTPException(
                status_code=503,
                detail="Message queue is temporarily unavailable",
            ) from error
        return {
            "status": "accepted",
            "message_id": event.message_id,
            "duplicate": False,
        }

    return app


def _production_app() -> FastAPI:
    from redis import Redis
    from rq import Queue

    import config

    if config.CLIENT_VALIDATE_CONFIG:
        missing = [
            name
            for name, value in (
                ("CLIENT_WEBHOOK_USER", config.CLIENT_WEBHOOK_USER),
                ("CLIENT_WEBHOOK_PASSWORD", config.CLIENT_WEBHOOK_PASSWORD),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Missing required client webhook settings: " + ", ".join(missing)
            )
    redis = Redis.from_url(config.REDIS_URL)
    return create_app(
        username=config.CLIENT_WEBHOOK_USER,
        password=config.CLIENT_WEBHOOK_PASSWORD,
        deduplicator=RedisDeduplicator(
            redis,
            ttl_seconds=config.CLIENT_DEDUP_TTL_SEC,
        ),
        publisher=RqEventPublisher(
            Queue(name=config.CLIENT_QUEUE_NAME, connection=redis)
        ),
        rate_limiter=RedisRateLimiter(
            redis,
            limit=config.RATE_LIMIT_PER_MIN,
        ),
    )


app = _production_app()

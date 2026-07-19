"""Inbound webhook for messages sent by the client's app/CRM."""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timezone
from typing import Protocol

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field, field_validator


SUPPORTED_MESSAGE_TYPES = frozenset({"text", "image", "audio"})
INDIAN_E164_PATTERN = r"^\+91[6-9][0-9]{9}$"
ALLOWED_IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
ALLOWED_AUDIO_MIME_TYPES = frozenset(
    {
        "audio/webm",
        "audio/ogg",
        "audio/mp4",
        "audio/mpeg",
        "audio/wav",
        "audio/x-wav",
        "audio/mp3",
    }
)


class InboundMessage(BaseModel):
    message_id: str = Field(min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=32)
    mobile: str = Field(pattern=INDIAN_E164_PATTERN)
    timestamp: str = Field(min_length=1, max_length=128)
    content: str | None = Field(default=None, max_length=4096)
    media_url: str | None = Field(default=None, max_length=2048)
    mime_type: str | None = Field(default=None, max_length=128)

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
        if not (event.mime_type or "").strip():
            errors.append(
                {"field": "mime_type", "message": "mime_type is required for media"}
            )
        else:
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
    async def invalid_payload(_, error: RequestValidationError):
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

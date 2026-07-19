"""RQ jobs for client-app messages."""
from __future__ import annotations

import logging
from pathlib import Path

from redis import Redis
from rq import get_current_job

import admin_config
import config
import interactions
from client_adapters import HttpCustomerDirectory, HttpReplySender, RedisClientState
from client_media import (
    DeterministicAudioTranscriber,
    DeterministicDocumentRecognizer,
    GeminiAudioTranscriber,
    GeminiDocumentRecognizer,
    SafeMediaFetcher,
)
from client_processing import ClientMessageProcessor
from conversation_engine import ConversationEngine, GenerateResult, make_engine
from leads import LeadWriter


log = logging.getLogger(__name__)


class DeterministicClientLLM:
    """Predictable model used only by the isolated mock deployment profile."""

    def generate(self, *, system_instruction: str, contents: list[dict]) -> GenerateResult:
        last = contents[-1]["parts"][0]["text"]
        return GenerateResult(text=f"Mock bot reply received: {last[:200]}")


def validate_worker_config() -> None:
    if config.CLIENT_ENV == "production" and config.CLIENT_TEST_MODE:
        raise RuntimeError("CLIENT_TEST_MODE cannot be enabled in production")
    if not config.CLIENT_VALIDATE_CONFIG:
        return
    missing = [
        name
        for name, value in (
            ("CLIENT_CRM_CUSTOMER_URL", config.CLIENT_CRM_CUSTOMER_URL),
            ("CLIENT_REPLY_WEBHOOK_URL", config.CLIENT_REPLY_WEBHOOK_URL),
            ("CLIENT_API_USER", config.CLIENT_API_USER),
            ("CLIENT_API_PASSWORD", config.CLIENT_API_PASSWORD),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing required client worker settings: " + ", ".join(missing)
        )


def build_processor(redis: Redis | None = None) -> ClientMessageProcessor:
    validate_worker_config()
    redis = redis or Redis.from_url(config.REDIS_URL, decode_responses=True)
    config_store = admin_config.get_store()
    config_store.ensure_seeded()
    lead_writer = LeadWriter(Path(config.LEADS_CSV_PATH), config_store)

    if config.CLIENT_TEST_MODE:
        engine = ConversationEngine(
            config_store=config_store,
            llm=DeterministicClientLLM(),
            lead_writer=lead_writer,
        )
        transcriber = DeterministicAudioTranscriber()
        recognizer = DeterministicDocumentRecognizer()
    else:
        engine = make_engine(config_store=config_store)
        transcriber = GeminiAudioTranscriber()
        recognizer = GeminiDocumentRecognizer()

    return ClientMessageProcessor(
        state=RedisClientState(
            redis,
            ttl_seconds=config.CLIENT_HISTORY_TTL_SEC,
        ),
        directory=HttpCustomerDirectory(
            config.CLIENT_CRM_CUSTOMER_URL,
            username=config.CLIENT_API_USER,
            password=config.CLIENT_API_PASSWORD,
            timeout=config.CLIENT_HTTP_TIMEOUT_SEC,
            retry_wait=config.CLIENT_RETRY_WAIT_SEC,
        ),
        engine=engine,
        reply_sender=HttpReplySender(
            config.CLIENT_REPLY_WEBHOOK_URL,
            username=config.CLIENT_API_USER,
            password=config.CLIENT_API_PASSWORD,
            timeout=config.CLIENT_HTTP_TIMEOUT_SEC,
            retry_wait=config.CLIENT_RETRY_WAIT_SEC,
        ),
        lead_store=lead_writer,
        interaction_store=interactions.get_store(),
        media_fetcher=SafeMediaFetcher(
            timeout=config.CLIENT_HTTP_TIMEOUT_SEC,
            max_bytes=config.CLIENT_MAX_MEDIA_BYTES,
            trusted_test_hosts=config.CLIENT_TEST_MEDIA_HOSTS,
        ),
        transcriber=transcriber,
        document_recognizer=recognizer,
        retry_wait=config.CLIENT_RETRY_WAIT_SEC,
    )


def handle_client_message(event: dict) -> None:
    """Serialize processing for one mobile while allowing other mobiles to proceed."""
    redis = Redis.from_url(config.REDIS_URL, decode_responses=True)
    lock = redis.lock(
        f"client:processing:{event['mobile']}",
        timeout=10 * 60,
        blocking_timeout=5 * 60,
    )
    try:
        with lock:
            build_processor(redis).process(event)
    except Exception:
        job = get_current_job()
        retries_left = getattr(job, "retries_left", 0) if job else 0
        if not retries_left:
            redis.delete(f"client:seen:{event['message_id']}")
        raise
    redis.set(
        f"client:seen:{event['message_id']}",
        "completed",
        ex=config.CLIENT_DEDUP_TTL_SEC,
    )
    log.info(
        "processed client message id=%s mobile=%s",
        event.get("message_id"),
        event.get("mobile"),
    )

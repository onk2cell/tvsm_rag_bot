"""RQ jobs for client-app messages."""
from __future__ import annotations

import logging
from pathlib import Path

from redis import Redis
from rq import get_current_job

import admin_config
import config
import interactions
from client_adapters import (
    HttpCustomerDirectory,
    HttpReplySender,
    JamCustomerDirectory,
    JamDisposeClient,
    JamWhatsAppReplySender,
    RedisClientState,
    StubCustomerDirectory,
)
from client_media import (
    DeterministicAudioTranscriber,
    DeterministicDocumentRecognizer,
    GeminiAudioTranscriber,
    GeminiDocumentRecognizer,
    SafeMediaFetcher,
)
from client_processing import ClientMessageProcessor
from conversation_engine import ConversationEngine, GenerateResult, make_engine
from dealers import DealerDirectory, NominatimPincodeGeocoder
from leads import LeadWriter
from pgms import PgmDirectory


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
    missing = []
    if not config.CLIENT_STUB_CUSTOMER and not (
        config.CLIENT_CRM_CUSTOMER_URL or _default_jam_customer_url()
    ):
        missing.append("CLIENT_CRM_CUSTOMER_URL")
    if not config.CLIENT_REPLY_WEBHOOK_URL:
        missing.append("CLIENT_REPLY_WEBHOOK_URL")
    if config.CLIENT_REPLY_AUTH_MODE == "api_key":
        if not config.CLIENT_REPLY_API_KEY:
            missing.append("CLIENT_REPLY_API_KEY")
    else:
        if not config.CLIENT_API_USER:
            missing.append("CLIENT_API_USER")
        if not config.CLIENT_API_PASSWORD:
            missing.append("CLIENT_API_PASSWORD")
        if not config.CLIENT_STUB_CUSTOMER and (
            not config.CLIENT_API_USER or not config.CLIENT_API_PASSWORD
        ):
            # CRM basic auth uses the same outbound credentials in basic mode.
            pass
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

    if config.CLIENT_STUB_CUSTOMER:
        directory = StubCustomerDirectory()
    elif config.CLIENT_REPLY_AUTH_MODE == "api_key":
        directory = JamCustomerDirectory(
            _jam_customer_url(),
            api_key=config.CLIENT_REPLY_API_KEY,
            timeout=config.CLIENT_HTTP_TIMEOUT_SEC,
            retry_wait=config.CLIENT_RETRY_WAIT_SEC,
        )
    else:
        directory = HttpCustomerDirectory(
            config.CLIENT_CRM_CUSTOMER_URL,
            username=config.CLIENT_API_USER,
            password=config.CLIENT_API_PASSWORD,
            timeout=config.CLIENT_HTTP_TIMEOUT_SEC,
            retry_wait=config.CLIENT_RETRY_WAIT_SEC,
        )

    if config.CLIENT_REPLY_AUTH_MODE == "api_key":
        reply_sender = JamWhatsAppReplySender(
            config.CLIENT_REPLY_WEBHOOK_URL,
            api_key=config.CLIENT_REPLY_API_KEY,
            timeout=config.CLIENT_HTTP_TIMEOUT_SEC,
            retry_wait=config.CLIENT_RETRY_WAIT_SEC,
        )
    else:
        reply_sender = HttpReplySender(
            config.CLIENT_REPLY_WEBHOOK_URL,
            username=config.CLIENT_API_USER,
            password=config.CLIENT_API_PASSWORD,
            timeout=config.CLIENT_HTTP_TIMEOUT_SEC,
            retry_wait=config.CLIENT_RETRY_WAIT_SEC,
        )

    # One geocoder for both directories: each instance owns the pincode
    # cache file, and two writers would overwrite each other's entries.
    geocoder = NominatimPincodeGeocoder()
    dealer_directory = None
    try:
        dealer_directory = DealerDirectory(geocoder=geocoder)
    except Exception:
        log.exception("Dealer directory unavailable; pincode routing disabled")
    pgm_directory = None
    try:
        pgm_directory = PgmDirectory(geocoder=geocoder)
    except Exception:
        log.exception("PGM directory unavailable; nearest-PGM search disabled")

    # Dispose always uses JAM X-API-KEY auth. Wire it whenever URL + key are
    # present — including lab (basic mock replies) so dispose can still hit
    # real CRM with CLIENT_DISPOSE_URL + CLIENT_REPLY_API_KEY from .env.
    dispose_client = None
    dispose_url = _jam_dispose_url()
    if dispose_url and config.CLIENT_REPLY_API_KEY:
        dispose_client = JamDisposeClient(
            dispose_url,
            api_key=config.CLIENT_REPLY_API_KEY,
            timeout=config.CLIENT_HTTP_TIMEOUT_SEC,
            retry_wait=config.CLIENT_RETRY_WAIT_SEC,
        )

    return ClientMessageProcessor(
        state=RedisClientState(
            redis,
            ttl_seconds=config.CLIENT_HISTORY_TTL_SEC,
        ),
        directory=directory,
        engine=engine,
        reply_sender=reply_sender,
        lead_store=lead_writer,
        interaction_store=interactions.get_store(),
        media_fetcher=SafeMediaFetcher(
            timeout=config.CLIENT_HTTP_TIMEOUT_SEC,
            max_bytes=config.CLIENT_MAX_MEDIA_BYTES,
            trusted_test_hosts=config.CLIENT_TEST_MEDIA_HOSTS,
        ),
        transcriber=transcriber,
        document_recognizer=recognizer,
        dealer_directory=dealer_directory,
        pgm_directory=pgm_directory,
        dispose_client=dispose_client,
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


def _default_jam_customer_url() -> str:
    send_url = (config.CLIENT_REPLY_WEBHOOK_URL or "").rstrip("/")
    if send_url.endswith("/send"):
        return send_url[: -len("/send")] + "/customer"
    return ""


def _jam_customer_url() -> str:
    return (config.CLIENT_CRM_CUSTOMER_URL or "").strip() or _default_jam_customer_url()


def _default_jam_dispose_url() -> str:
    send_url = (config.CLIENT_REPLY_WEBHOOK_URL or "").rstrip("/")
    if send_url.endswith("/send"):
        return send_url[: -len("/send")] + "/dispose"
    return ""


def _jam_dispose_url() -> str:
    return (config.CLIENT_DISPOSE_URL or "").strip() or _default_jam_dispose_url()

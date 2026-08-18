"""Central configuration, loaded from environment / .env."""
import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


# --- Gemini ---
# Optional: if empty, an admin can supply the key at runtime on the admin page.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Where a key set on the admin page is persisted. Lives under data/ (gitignored,
# mounted into the worker) so the runtime key survives restarts and reaches the
# separate worker process. rag.get_client() reloads it when the file changes.
GEMINI_KEY_RUNTIME_PATH = os.environ.get(
    "GEMINI_KEY_RUNTIME_PATH", "data/gemini_key.txt"
)
FILE_SEARCH_STORE = os.environ.get("FILE_SEARCH_STORE", "")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
GEMINI_TTS_MODEL = os.environ.get("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
GEMINI_TTS_VOICE = os.environ.get("GEMINI_TTS_VOICE", "Kore")
MAX_TTS_CHARS = int(os.environ.get("MAX_TTS_CHARS", "1500"))

# --- Client app / CRM integration (JAM WhatsApp) ---
CLIENT_WEBHOOK_USER = os.environ.get("CLIENT_WEBHOOK_USER", "")
CLIENT_WEBHOOK_PASSWORD = os.environ.get("CLIENT_WEBHOOK_PASSWORD", "")
CLIENT_CRM_CUSTOMER_URL = os.environ.get("CLIENT_CRM_CUSTOMER_URL", "")
CLIENT_REPLY_WEBHOOK_URL = os.environ.get("CLIENT_REPLY_WEBHOOK_URL", "")
CLIENT_API_USER = os.environ.get("CLIENT_API_USER", "")
CLIENT_API_PASSWORD = os.environ.get("CLIENT_API_PASSWORD", "")
CLIENT_REPLY_AUTH_MODE = os.environ.get("CLIENT_REPLY_AUTH_MODE", "basic").strip().lower()
CLIENT_REPLY_API_KEY = os.environ.get("CLIENT_REPLY_API_KEY", "")
CLIENT_DISPOSE_URL = os.environ.get("CLIENT_DISPOSE_URL", "")
CLIENT_STUB_CUSTOMER = os.environ.get("CLIENT_STUB_CUSTOMER", "").lower() in {
    "1",
    "true",
    "yes",
}
CLIENT_HTTP_TIMEOUT_SEC = float(os.environ.get("CLIENT_HTTP_TIMEOUT_SEC", "30"))
CLIENT_RETRY_WAIT_SEC = float(os.environ.get("CLIENT_RETRY_WAIT_SEC", "30"))
CLIENT_HISTORY_TTL_SEC = int(os.environ.get("CLIENT_HISTORY_TTL_SEC", "3600"))
CLIENT_DEDUP_TTL_SEC = int(os.environ.get("CLIENT_DEDUP_TTL_SEC", str(7 * 24 * 3600)))
CLIENT_MAX_MEDIA_BYTES = int(
    os.environ.get("CLIENT_MAX_MEDIA_BYTES", str(10 * 1024 * 1024))
)
CLIENT_TEST_MODE = os.environ.get("CLIENT_TEST_MODE", "").lower() in {"1", "true", "yes"}
CLIENT_ENV = os.environ.get("CLIENT_ENV", "development").strip().lower()
CLIENT_VALIDATE_CONFIG = os.environ.get(
    "CLIENT_VALIDATE_CONFIG", ""
).lower() in {"1", "true", "yes"}
CLIENT_TEST_MEDIA_HOSTS = {
    host.strip()
    for host in os.environ.get("CLIENT_TEST_MEDIA_HOSTS", "").split(",")
    if host.strip()
}
CLIENT_QUEUE_NAME = os.environ.get("CLIENT_QUEUE_NAME", "default")
CLIENT_MEDIA_BASE_URL = os.environ.get(
    "CLIENT_MEDIA_BASE_URL",
    "https://aichatbot.jamoutsourcing.com/media",
).strip()

# --- Admin ---
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")    # empty = admin endpoints disabled
ADMIN_CONFIG_PATH = os.environ.get("ADMIN_CONFIG_PATH", "data/admin_config.json")
# Queue depth above which /admin/api/status reports "degraded". Tune this once
# real peak volume is known — a threshold guessed too low turns the status page
# permanently amber, which is how status pages get ignored.
ADMIN_QUEUE_WARN_DEPTH = int(os.environ.get("ADMIN_QUEUE_WARN_DEPTH", "20"))
# How long a live JAM probe result is reused, so polling the status endpoint
# cannot become standing traffic against the client's production CRM.
ADMIN_PROBE_CACHE_SEC = int(os.environ.get("ADMIN_PROBE_CACHE_SEC", "60"))

# --- Redis / behaviour ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
# Turns kept in the prompt. 6 meant the model saw only the last 12 messages
# and re-asked questions it had already asked. 40 is far past any real lead
# conversation while still capping a pathological session; the KNOWN SO FAR
# block (see client_processing._known_state_block) carries the captured
# facts forward regardless, so truncation is no longer lossy.
MAX_HISTORY_TURNS = int(os.environ.get("MAX_HISTORY_TURNS", "40"))
HISTORY_TTL_SEC = int(os.environ.get("HISTORY_TTL_SEC", str(24 * 3600)))
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "12"))
MAX_AUDIO_BYTES = int(os.environ.get("MAX_AUDIO_BYTES", str(5 * 1024 * 1024)))
MAX_AUDIO_RECORD_SEC = int(os.environ.get("MAX_AUDIO_RECORD_SEC", "60"))

# --- Leads export ---
LEADS_CSV_PATH = os.environ.get("LEADS_CSV_PATH", "data/leads.csv")

# --- Interaction history ---
INTERACTIONS_DB_PATH = os.environ.get(
    "INTERACTIONS_DB_PATH", "data/interactions.db"
)
LOAD_TEST_INTERACTIONS_DB_PATH = os.environ.get(
    "LOAD_TEST_INTERACTIONS_DB_PATH", "data/load_test_interactions.db"
)
LOAD_TEST_TOKEN = os.environ.get("LOAD_TEST_TOKEN", "")
INTERACTION_RETENTION_DAYS = int(
    os.environ.get("INTERACTION_RETENTION_DAYS", "90")
)

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
FILE_SEARCH_STORE = _require("FILE_SEARCH_STORE")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_TTS_MODEL = os.environ.get("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
GEMINI_TTS_VOICE = os.environ.get("GEMINI_TTS_VOICE", "Kore")
MAX_TTS_CHARS = int(os.environ.get("MAX_TTS_CHARS", "1500"))

# --- WhatsApp (Meta Cloud API) ---
WHATSAPP_TOKEN = _require("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = _require("PHONE_NUMBER_ID")
VERIFY_TOKEN = _require("VERIFY_TOKEN")
APP_SECRET = os.environ.get("APP_SECRET", "")      # empty = signature check skipped
GRAPH_VERSION = os.environ.get("GRAPH_VERSION", "v21.0")

# --- Admin ---
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")    # empty = admin endpoints disabled
ADMIN_CONFIG_PATH = os.environ.get("ADMIN_CONFIG_PATH", "data/admin_config.json")

# --- Web playground access (HTTP Basic Auth) ---
APP_USER = os.environ.get("APP_USER", "team")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")  # empty = no login required (open)

# --- Redis / behaviour ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
MAX_HISTORY_TURNS = int(os.environ.get("MAX_HISTORY_TURNS", "6"))
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

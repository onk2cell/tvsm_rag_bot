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

# --- WhatsApp (Meta Cloud API) ---
WHATSAPP_TOKEN = _require("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = _require("PHONE_NUMBER_ID")
VERIFY_TOKEN = _require("VERIFY_TOKEN")
APP_SECRET = os.environ.get("APP_SECRET", "")      # empty = signature check skipped
GRAPH_VERSION = os.environ.get("GRAPH_VERSION", "v21.0")

# --- Admin ---
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")    # empty = admin endpoints disabled

# --- Web playground access (HTTP Basic Auth) ---
APP_USER = os.environ.get("APP_USER", "team")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")  # empty = no login required (open)

# --- Redis / behaviour ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
MAX_HISTORY_TURNS = int(os.environ.get("MAX_HISTORY_TURNS", "6"))
HISTORY_TTL_SEC = int(os.environ.get("HISTORY_TTL_SEC", str(24 * 3600)))
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "12"))

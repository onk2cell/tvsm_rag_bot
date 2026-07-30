"""Admin-managed bot configuration: load, validate, persist, seed defaults.

The conversation engine and CSV writer read from this store — not hardcoded prompts.
Each ``get()`` reloads from disk so updates apply on the next turn without restart.
"""
from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

VOICE_POLICIES = frozenset({"always", "intro_only", "never", "mirror_user"})

DEFAULT_LANGUAGES = [
    {"code": "English", "label": "English"},
    {"code": "Hindi", "label": "हिंदी (Hindi)"},
    {"code": "Marathi", "label": "मराठी (Marathi)"},
    {"code": "Telugu", "label": "తెలుగు (Telugu)"},
    {"code": "Tamil", "label": "தமிழ் (Tamil)"},
    {"code": "Kannada", "label": "ಕನ್ನಡ (Kannada)"},
    {"code": "Malayalam", "label": "മലയാളം (Malayalam)"},
]

DEFAULT_CAPTURE_FIELDS = [
    {"id": "lead_name", "label": "Lead name", "required": False},
    {"id": "product_interest", "label": "Product interest", "required": True},
    {"id": "purchase_timeline", "label": "Purchase timeline", "required": True},
    {"id": "timeline_bucket", "label": "Timeline bucket", "required": False},
    {"id": "pincode", "label": "Pincode", "required": True},
    {"id": "area", "label": "Area", "required": False},
    {"id": "district", "label": "District", "required": False},
    {"id": "delivery_location", "label": "Delivery location", "required": False},
    {"id": "feature_awareness", "label": "Feature awareness", "required": False},
    {"id": "doc_license", "label": "Driving licence", "required": False},
    {"id": "doc_permit", "label": "Permit", "required": False},
    {"id": "doc_badge", "label": "Commercial badge", "required": False},
    {"id": "campaign_shown", "label": "Campaign shown", "required": False},
    {"id": "lead_quality", "label": "Lead quality", "required": False},
    {"id": "disposition", "label": "Disposition", "required": False},
    {"id": "blockers", "label": "Blockers", "required": False},
    {"id": "next_step", "label": "Next step", "required": False},
    {"id": "notes", "label": "Notes", "required": False},
]

DEFAULT_FLOW_STEPS = [
    "intro",
    "model_interest",
    "campaign_awareness",
    "timeline",
    "location",
    "feature_awareness",
    "documents",
    "wrap_up",
]

DEFAULT_CAMPAIGN_TEXT = """\
ACTIVE CAMPAIGN — "Vaada" scheme (mention proactively, briefly):
- 2-year warranty + 3 free maintenance services
- 1 year free RSA (roadside assistance, towing to showroom)
- Accident coverage package up to Rs 10 lakh
- Education benefit up to Rs 1 lakh per child (max 2 children)
- Hospitalization cash Rs 4,000/day up to 30 days
- Ambulance coverage up to Rs 5,000
"""

DEFAULT_INTRO_TEXT = (
    "Hi! I'm TVS Motor's assistant for passenger three-wheelers. "
    "I'll ask a few quick questions and share accurate product information "
    "and connect you with your nearest dealership."
)

# Written to CSV by adapters/the engine — not asked as chat questions.
SYSTEM_CSV_COLUMNS = [
    "timestamp",
    "channel",
    "source",
    "session",
    "language",
    "mobile",
    "crm_customer_id",
    "customer_name",
    "last_message_id",
    "client_timestamp",
    "received_at",
    "documents",
]


def default_config() -> dict[str, Any]:
    """Return a fresh copy of the TVS passenger 3W default configuration."""
    intro = {lang["code"]: {"text": DEFAULT_INTRO_TEXT, "audio_url": None} for lang in DEFAULT_LANGUAGES}
    return {
        "bot_name": "TVS Passenger 3W Assistant",
        "welcome_text": (
            "Welcome! Choose your language to start — we'll help you explore "
            "TVS King passenger three-wheelers and capture your details for the dealership."
        ),
        "languages": deepcopy(DEFAULT_LANGUAGES),
        "capture_fields": deepcopy(DEFAULT_CAPTURE_FIELDS),
        "flow_steps": list(DEFAULT_FLOW_STEPS),
        "voice_policy": "intro_only",
        "campaign_text": DEFAULT_CAMPAIGN_TEXT.strip(),
        "intro": intro,
        "entry_sources": {
            "web": {"welcome_override": None},
            "whatsapp": {"welcome_override": None},
            "ricshow": {"welcome_override": None},
            "client_app": {"welcome_override": None},
        },
    }


def validate_config(config: dict[str, Any]) -> None:
    """Raise ValueError with a clear message when config is invalid."""
    if not isinstance(config, dict):
        raise ValueError("Config must be a JSON object")

    for key in (
        "bot_name",
        "welcome_text",
        "languages",
        "capture_fields",
        "flow_steps",
        "voice_policy",
        "campaign_text",
        "intro",
    ):
        if key not in config:
            raise ValueError(f"Missing required field: {key}")

    if not isinstance(config["bot_name"], str) or not config["bot_name"].strip():
        raise ValueError("bot_name must be a non-empty string")
    if not isinstance(config["welcome_text"], str):
        raise ValueError("welcome_text must be a string")
    if not isinstance(config["campaign_text"], str):
        raise ValueError("campaign_text must be a string")

    if not isinstance(config["languages"], list) or not config["languages"]:
        raise ValueError("languages must be a non-empty list")
    lang_codes: set[str] = set()
    for i, lang in enumerate(config["languages"]):
        if not isinstance(lang, dict):
            raise ValueError(f"languages[{i}] must be an object")
        code = lang.get("code")
        label = lang.get("label")
        if not isinstance(code, str) or not code.strip():
            raise ValueError(f"languages[{i}].code must be a non-empty string")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"languages[{i}].label must be a non-empty string")
        if code in lang_codes:
            raise ValueError(f"Duplicate language code: {code}")
        lang_codes.add(code)

    if not isinstance(config["capture_fields"], list) or not config["capture_fields"]:
        raise ValueError("capture_fields must be a non-empty list")
    field_ids: set[str] = set()
    for i, field in enumerate(config["capture_fields"]):
        if not isinstance(field, dict):
            raise ValueError(f"capture_fields[{i}] must be an object")
        fid = field.get("id")
        if not isinstance(fid, str) or not fid.strip():
            raise ValueError(f"capture_fields[{i}].id must be a non-empty string")
        if fid in field_ids:
            raise ValueError(f"Duplicate capture field id: {fid}")
        field_ids.add(fid)
        if "required" in field and not isinstance(field["required"], bool):
            raise ValueError(f"capture_fields[{i}].required must be a boolean")

    if not isinstance(config["flow_steps"], list) or not config["flow_steps"]:
        raise ValueError("flow_steps must be a non-empty list")
    for i, step in enumerate(config["flow_steps"]):
        if not isinstance(step, str) or not step.strip():
            raise ValueError(f"flow_steps[{i}] must be a non-empty string")

    if config["voice_policy"] not in VOICE_POLICIES:
        raise ValueError(
            f"voice_policy must be one of: {', '.join(sorted(VOICE_POLICIES))}"
        )

    if not isinstance(config["intro"], dict):
        raise ValueError("intro must be an object keyed by language code")
    for code in lang_codes:
        if code not in config["intro"]:
            raise ValueError(f"intro missing entry for language: {code}")
        entry = config["intro"][code]
        if not isinstance(entry, dict):
            raise ValueError(f"intro[{code}] must be an object")
        if not isinstance(entry.get("text", ""), str):
            raise ValueError(f"intro[{code}].text must be a string")
        audio = entry.get("audio_url")
        if audio is not None and not isinstance(audio, str):
            raise ValueError(f"intro[{code}].audio_url must be a string or null")

    entry_sources = config.get("entry_sources")
    if entry_sources is not None:
        if not isinstance(entry_sources, dict):
            raise ValueError("entry_sources must be an object")
        for source, meta in entry_sources.items():
            if not isinstance(meta, dict):
                raise ValueError(f"entry_sources[{source}] must be an object")


def csv_columns(config: dict[str, Any]) -> list[str]:
    """CSV header: system columns followed by configured capture field ids."""
    return SYSTEM_CSV_COLUMNS + [f["id"] for f in config["capture_fields"]]


class AdminConfigStore:
    """JSON file-backed admin config with reload-on-read."""

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    def ensure_seeded(self) -> dict[str, Any]:
        """Create default config file if missing; return current config."""
        with self._lock:
            if not self._path.exists():
                cfg = default_config()
                self._write(cfg)
                return deepcopy(cfg)
            return self.load()

    def load(self) -> dict[str, Any]:
        """Read and validate config from disk."""
        with self._lock:
            if not self._path.exists():
                return self.ensure_seeded()
            raw = self._path.read_text(encoding="utf-8")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in config file: {e}") from e
            validate_config(data)
            return deepcopy(data)

    def get(self) -> dict[str, Any]:
        """Return current config (reloads from disk every call)."""
        return self.load()

    def update(self, config: dict[str, Any]) -> dict[str, Any]:
        """Validate and persist a full config document."""
        validate_config(config)
        with self._lock:
            self._write(config)
        return deepcopy(config)

    def _write(self, config: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
        self._path.write_text(text, encoding="utf-8")


_default_store: AdminConfigStore | None = None
_store_lock = threading.Lock()


def config_path() -> Path:
    raw = os.environ.get("ADMIN_CONFIG_PATH", "data/admin_config.json")
    return Path(raw)


def get_store(path: Path | None = None) -> AdminConfigStore:
    """Return the process-wide AdminConfigStore (lazy singleton)."""
    global _default_store
    with _store_lock:
        if _default_store is None:
            _default_store = AdminConfigStore(path or config_path())
        return _default_store


def reset_store_for_tests() -> None:
    """Clear the singleton — for tests only."""
    global _default_store
    with _store_lock:
        _default_store = None

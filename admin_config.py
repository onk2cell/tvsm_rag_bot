"""Admin-managed bot configuration: load, validate, persist, seed defaults.

The conversation engine and CSV writer read from this store — not hardcoded prompts.
Each ``get()`` reloads from disk so updates apply on the next turn without restart.
"""
from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
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

# Neutral placeholders. A client's real name, welcome, campaign, products and
# documents live in a seed file under seeds/ — see seed_config(). Nothing here
# names a client, so a stack that has not been configured yet cannot pass
# itself off as one.
DEFAULT_BOT_NAME = "Qualification Assistant"

DEFAULT_WELCOME_TEXT = "Welcome! Choose your language to get started."

DEFAULT_INTRO_TEXT = (
    "Hi! I'll ask a few quick questions, share the information you need, "
    "and connect you with the right team."
)

SUPPORT_DOC_KINDS = frozenset({"warranty", "pms"})
FUEL_KINDS = frozenset({"cng", "lpg", "petrol"})

# The how-to card shown to customers who do not know their pincode.
#
# `url` empty means "derive it from CLIENT_MEDIA_BASE_URL", which is today's
# behaviour and points at our own media host. Set it to an absolute URL to
# serve the card from somewhere stable instead — JAM's CDN, for example — and
# the ephemeral media tunnel stops mattering for customer-facing traffic.
#
# `by_language` overrides `url` per language code. Localized cards for all
# seven languages already exist in data/media/share_location/, unused: the bot
# currently sends one bilingual Android/iOS card to everybody.
DEFAULT_SHARE_LOCATION_IMAGE: dict[str, Any] = {"url": "", "by_language": {}}


def validate_share_location_image(image: Any) -> None:
    if not isinstance(image, dict):
        raise ValueError("share_location_image must be an object")
    url = image.get("url", "")
    if not isinstance(url, str):
        raise ValueError("share_location_image.url must be a string")
    by_language = image.get("by_language", {})
    if not isinstance(by_language, dict):
        raise ValueError("share_location_image.by_language must be an object")
    for code, value in by_language.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"share_location_image.by_language[{code}] must be a non-empty URL"
            )


def validate_documents(documents: Any) -> None:
    """Raise ValueError with a message naming the offending product."""
    if not isinstance(documents, dict):
        raise ValueError("documents must be an object keyed by product name")
    for product, entry in documents.items():
        where = f"documents[{product!r}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} must be an object")
        brochure = entry.get("brochure")
        if not isinstance(brochure, str) or not brochure.strip():
            raise ValueError(f"{where}.brochure must be a non-empty URL")
        fuel = entry.get("fuel", {})
        if not isinstance(fuel, dict):
            raise ValueError(f"{where}.fuel must be an object")
        for kind, url in fuel.items():
            if kind not in FUEL_KINDS:
                raise ValueError(
                    f"{where}.fuel has unknown fuel {kind!r}; "
                    f"expected one of {', '.join(sorted(FUEL_KINDS))}"
                )
            if not isinstance(url, str) or not url.strip():
                raise ValueError(f"{where}.fuel[{kind}] must be a non-empty URL")
        support = entry.get("support", [])
        if not isinstance(support, list):
            raise ValueError(f"{where}.support must be a list")
        for i, doc in enumerate(support):
            if not isinstance(doc, dict):
                raise ValueError(f"{where}.support[{i}] must be an object")
            if not isinstance(doc.get("url"), str) or not doc["url"].strip():
                raise ValueError(f"{where}.support[{i}].url must be a non-empty URL")
            if doc.get("kind") not in SUPPORT_DOC_KINDS:
                raise ValueError(
                    f"{where}.support[{i}].kind must be one of "
                    f"{', '.join(sorted(SUPPORT_DOC_KINDS))}"
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


# Campaign windows are inclusive calendar dates read in India time. Evaluating
# them in UTC would start and end a campaign 5h30m off the day the business
# means, which around a launch or expiry is a whole evening of wrong pitches.
IST = timezone(timedelta(hours=5, minutes=30))


def today_ist() -> date:
    return datetime.now(IST).date()


def _parse_campaign_date(value: Any, field: str) -> date | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a YYYY-MM-DD string or null")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a YYYY-MM-DD date, got {value!r}") from exc


def campaign_window(config: dict[str, Any]) -> tuple[date | None, date | None]:
    return (
        _parse_campaign_date(config.get("campaign_starts_on"), "campaign_starts_on"),
        _parse_campaign_date(config.get("campaign_ends_on"), "campaign_ends_on"),
    )


def campaign_is_active(config: dict[str, Any], on: date | None = None) -> bool:
    """Is the campaign live on this date? Both bounds are inclusive.

    An unset bound means open-ended, so a config with neither set behaves
    exactly as it did before scheduling existed: always on.
    """
    starts, ends = campaign_window(config)
    day = on or today_ist()
    if starts and day < starts:
        return False
    if ends and day > ends:
        return False
    return True


def active_campaign_text(config: dict[str, Any], on: date | None = None) -> str:
    """The campaign copy if it is live today, otherwise empty.

    Empty means the prompt omits the CAMPAIGN section entirely, so the bot
    stops pitching a scheme that has expired instead of announcing benefits
    the dealership will not honour.
    """
    if not campaign_is_active(config, on):
        return ""
    return config.get("campaign_text") or ""


def default_config() -> dict[str, Any]:
    """A neutral, client-agnostic configuration.

    This used to return the TVS configuration, which meant a freshly deployed
    stack for any other client *was* a TVS bot until somebody edited it: TVS
    name, TVS welcome text, TVS products, TVS campaign — and TVS brochure PDFs
    sent to that client's customers.

    Real client configurations are seed files under seeds/, selected per
    deployment with ADMIN_CONFIG_SEED. See seed_config().
    """
    intro = {
        lang["code"]: {"text": DEFAULT_INTRO_TEXT, "audio_url": None}
        for lang in DEFAULT_LANGUAGES
    }
    return {
        "bot_name": DEFAULT_BOT_NAME,
        "welcome_text": DEFAULT_WELCOME_TEXT,
        "languages": deepcopy(DEFAULT_LANGUAGES),
        "capture_fields": deepcopy(DEFAULT_CAPTURE_FIELDS),
        "flow_steps": list(DEFAULT_FLOW_STEPS),
        "voice_policy": "intro_only",
        "campaign_text": "",          # no campaign until one is configured
        "campaign_starts_on": None,   # null = no start bound
        "campaign_ends_on": None,     # null = never expires
        "documents": {},              # no products until they are configured
        "share_location_image": deepcopy(DEFAULT_SHARE_LOCATION_IMAGE),
        "intro": intro,
        "entry_sources": {
            "web": {"welcome_override": None},
            "whatsapp": {"welcome_override": None},
            "ricshow": {"welcome_override": None},
            "client_app": {"welcome_override": None},
        },
    }


def seed_path() -> Path | None:
    """The seed file a brand-new stack should start from, if one is named."""
    raw = os.environ.get("ADMIN_CONFIG_SEED", "").strip()
    return Path(raw) if raw else None


def seed_config() -> dict[str, Any]:
    """The configuration used when a stack has no config file yet.

    ADMIN_CONFIG_SEED names a JSON file (seeds/tvs.json, seeds/acme.json), so
    standing up a client is a deployment setting rather than a code change.
    With no seed named, a stack starts neutral instead of as somebody else's
    bot.

    A named-but-unusable seed raises: a deployment that says which client it
    is and then cannot load it should fail loudly, not quietly serve
    placeholders to that client's customers.
    """
    path = seed_path()
    if path is None:
        return default_config()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ValueError(f"ADMIN_CONFIG_SEED points at a missing file: {path}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in seed file {path}: {e}") from e
    data = fill_missing_defaults(data)
    validate_config(data)
    return data


def fill_missing_defaults(config: dict[str, Any]) -> dict[str, Any]:
    """Add top-level keys introduced after this config file was written.

    ``default_config()`` only seeds a *new* file, so a config saved before a
    feature existed never gains its key — the field would stay invisible to
    the admin API and therefore uneditable, even though the bot honours it.
    Existing values are never touched, so this only ever adds.
    """
    if not isinstance(config, dict):
        return config
    filled = deepcopy(config)
    for key, value in default_config().items():
        if key not in filled:
            filled[key] = deepcopy(value)
    return filled


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
    step_ids: set[str] = set()
    for i, step in enumerate(config["flow_steps"]):
        if isinstance(step, str):
            step_id, guidance = step, ""
        elif isinstance(step, dict):
            step_id = step.get("id")
            guidance = step.get("guidance", "")
            if not isinstance(guidance, str):
                raise ValueError(f"flow_steps[{i}].guidance must be a string")
        else:
            raise ValueError(
                f"flow_steps[{i}] must be a string or an object with an id"
            )
        if not isinstance(step_id, str) or not step_id.strip():
            raise ValueError(f"flow_steps[{i}] must have a non-empty id")
        if step_id in step_ids:
            raise ValueError(f"Duplicate flow step id: {step_id}")
        step_ids.add(step_id)

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

    starts, ends = campaign_window(config)
    if starts and ends and ends < starts:
        raise ValueError(
            f"campaign_ends_on ({ends}) is before campaign_starts_on ({starts})"
        )

    if "documents" in config:
        validate_documents(config["documents"])

    if "share_location_image" in config:
        validate_share_location_image(config["share_location_image"])

    entry_sources = config.get("entry_sources")
    if entry_sources is not None:
        if not isinstance(entry_sources, dict):
            raise ValueError("entry_sources must be an object")
        for source, meta in entry_sources.items():
            if not isinstance(meta, dict):
                raise ValueError(f"entry_sources[{source}] must be an object")


def flow_steps(config: dict[str, Any]) -> list[tuple[str, str]]:
    """The configured steps as (id, guidance) pairs.

    Steps used to be bare id strings, with the wording for each held in a
    hardcoded dict in conversation_engine. That meant an admin could add a step
    through the panel and it would reach the model as a bare label with no
    instruction — looking configured while doing almost nothing. A step can now
    carry its own guidance.

    Plain strings are still accepted, and still resolve to the built-in wording
    for the steps that have it, so a config written before this change keeps
    working untouched.
    """
    pairs: list[tuple[str, str]] = []
    for step in config.get("flow_steps") or []:
        if isinstance(step, str):
            pairs.append((step, ""))
        elif isinstance(step, dict) and isinstance(step.get("id"), str):
            pairs.append((step["id"], str(step.get("guidance") or "")))
    return pairs


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
                cfg = seed_config()
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
            data = fill_missing_defaults(data)
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

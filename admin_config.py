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

# Product documents sent over WhatsApp. These live on JAM's own CDN, not the
# media host — CLIENT_MEDIA_BASE_URL serves only the share-location card.
#
# Admin-editable so a new model year is a config edit, not a redeploy:
#   brochure — the default PDF for the product
#   fuel     — overrides when the customer names CNG / LPG / petrol
#   support  — warranty and PMS schedules, sent only when they ask about
#              servicing or warranty (one request must not deliver three files)
JAM_PDF_BASE = "https://1.jamoutsourcing.com/f"

DEFAULT_PRODUCT_DOCUMENTS = {
    "King EV MAX": {
        "brochure": f"{JAM_PDF_BASE}/King_EV_MAX-English.pdf",
        "fuel": {},
        "support": [
            {"url": f"{JAM_PDF_BASE}/TVS_King_EV_MAX_Warranty_Policy.pdf",
             "kind": "warranty"},
        ],
    },
    "King Deluxe": {
        "brochure": f"{JAM_PDF_BASE}/King_Deluxe_Petrol-English.pdf",
        "fuel": {
            "cng": f"{JAM_PDF_BASE}/King_Deluxe_CNG-English.pdf",
            "lpg": f"{JAM_PDF_BASE}/King_Deluxe_LPG-English.pdf",
            "petrol": f"{JAM_PDF_BASE}/King_Deluxe_Petrol-English.pdf",
        },
        "support": [
            {"url": f"{JAM_PDF_BASE}/Deluxe-PMS-Schedule.pdf", "kind": "pms"},
            {"url": f"{JAM_PDF_BASE}/Deluxe-Warranty-Policy-new.pdf",
             "kind": "warranty"},
        ],
    },
    "King Duramax Plus": {
        "brochure": f"{JAM_PDF_BASE}/King_Duramax_Plus_Petrol-English.pdf",
        "fuel": {
            "cng": f"{JAM_PDF_BASE}/King_Duramax_Plus_CNG-English.pdf",
            "petrol": f"{JAM_PDF_BASE}/King_Duramax_Plus_Petrol-English.pdf",
        },
        "support": [
            {"url": f"{JAM_PDF_BASE}/Duramaxplus-PMS-Schedule.pdf", "kind": "pms"},
            {"url": f"{JAM_PDF_BASE}/Duramaxplus-Warranty-Policy.pdf",
             "kind": "warranty"},
        ],
    },
}

def validate_messages(messages: Any) -> None:
    """Raise ValueError naming the message, language and offending placeholder.

    Imported here rather than at module scope: client_static_messages reads
    config, so a top-level import would be circular. By the time this runs,
    admin_config is loaded and the import is free.
    """
    from string import Formatter

    from client_static_messages import MESSAGE_DEFAULTS, placeholders_for

    if not isinstance(messages, dict):
        raise ValueError("messages must be an object keyed by message name")
    for key, per_language in messages.items():
        where = f"messages[{key!r}]"
        if key not in MESSAGE_DEFAULTS:
            raise ValueError(
                f"{where} is not a known message; GET /admin/api/messages lists them"
            )
        if not isinstance(per_language, dict):
            raise ValueError(f"{where} must be an object keyed by language")
        allowed = placeholders_for(key)
        for language, text in per_language.items():
            spot = f"{where}[{language!r}]"
            if not isinstance(language, str) or not language.strip():
                raise ValueError(f"{where} has an empty language name")
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"{spot} must be a non-empty string")
            try:
                fields = [name for _, name, _, _ in Formatter().parse(text) if name]
            except ValueError as exc:
                raise ValueError(f"{spot} is not a valid template: {exc}") from exc
            unknown = sorted(
                {
                    name.split(".")[0].split("[")[0]
                    for name in fields
                    if name.split(".")[0].split("[")[0] not in allowed
                }
            )
            if unknown:
                listed = ", ".join(sorted(allowed)) or "none"
                raise ValueError(
                    f"{spot} uses unknown placeholder(s) "
                    f"{', '.join(repr(u) for u in unknown)}; allowed here: {listed}"
                )
            # Catches what name-checking cannot: bare "{}", "{0}", bad specs.
            try:
                text.format(**{name: "x" for name in allowed})
            except (KeyError, IndexError, ValueError) as exc:
                raise ValueError(f"{spot} could not be rendered: {exc}") from exc


def derive_aliases(name: str, other_products: Any = ()) -> list[str]:
    """Latin spellings an operator should not have to type by hand.

    The whole lower-cased name, plus each distinctive word in it. A word shared
    with another product -- "king" across three King models -- is skipped: it
    cannot say which product is meant, and matching only ever returns one.
    """
    cleaned = " ".join(str(name or "").lower().split())
    if not cleaned:
        return []
    shared: set[str] = set()
    for other in other_products or ():
        if other and str(other) != str(name):
            shared.update(" ".join(str(other).lower().split()).split())
    derived = [cleaned]
    for word in cleaned.split():
        if len(word) > 2 and word not in shared and word not in derived:
            derived.append(word)
    return derived


def product_alias_pairs(
    documents: dict[str, Any],
    builtin_for: Any = None,
) -> list[tuple[str, str]]:
    """(spelling, product) pairs for matching, from configured documents.

    A product whose entry has no ``aliases`` key has never been edited through
    the vehicle API, so it keeps the spellings this build ships -- upgrading
    must not quietly cost a product its sixteen Devanagari variants. An empty
    list is a deliberate choice by an operator and is honoured as-is.
    """
    pairs: list[tuple[str, str]] = []
    for product, entry in (documents or {}).items():
        if not isinstance(product, str) or not product.strip():
            continue
        pairs.append((product.lower(), product))
        aliases = (entry or {}).get("aliases") if isinstance(entry, dict) else None
        if aliases is None and builtin_for is not None:
            aliases = builtin_for(product)
        for alias in aliases or ():
            if isinstance(alias, str) and alias.strip():
                pairs.append((alias.lower(), product))
    return pairs


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
        aliases = entry.get("aliases")
        if aliases is not None:
            if not isinstance(aliases, list):
                raise ValueError(f"{where}.aliases must be a list of strings")
            for i, alias in enumerate(aliases):
                if not isinstance(alias, str) or not alias.strip():
                    raise ValueError(
                        f"{where}.aliases[{i}] must be a non-empty string"
                    )

    # Two products answering to one spelling is not a preference, it is a bug:
    # matching returns the first hit, so the loser silently stops being
    # recognised and its customers get the other product's brochure.
    claimed: dict[str, str] = {}
    for product, entry in documents.items():
        spellings = [product, *(entry.get("aliases") or [])]
        for alias in spellings:
            key = " ".join(str(alias).lower().split())
            owner = claimed.setdefault(key, product)
            if owner != product:
                raise ValueError(
                    f"alias {alias!r} is claimed by both {owner!r} and "
                    f"{product!r}; a spelling can only mean one product"
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
        "campaign_starts_on": None,   # null = no start bound
        "campaign_ends_on": None,     # null = never expires
        "documents": deepcopy(DEFAULT_PRODUCT_DOCUMENTS),
        # Sparse: only what an operator has actually reworded lives here, so a
        # message added to client_static_messages later needs no migration.
        "messages": {},
        "share_location_image": deepcopy(DEFAULT_SHARE_LOCATION_IMAGE),
        "intro": intro,
        "entry_sources": {
            "web": {"welcome_override": None},
            "whatsapp": {"welcome_override": None},
            "ricshow": {"welcome_override": None},
            "client_app": {"welcome_override": None},
        },
    }


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

    starts, ends = campaign_window(config)
    if starts and ends and ends < starts:
        raise ValueError(
            f"campaign_ends_on ({ends}) is before campaign_starts_on ({starts})"
        )

    if "documents" in config:
        validate_documents(config["documents"])

    if "messages" in config:
        validate_messages(config["messages"])

    if "share_location_image" in config:
        validate_share_location_image(config["share_location_image"])

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

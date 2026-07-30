"""Session language selection from CRM state or a text menu."""
from __future__ import annotations

import re

SUPPORTED_LANGUAGES = frozenset(
    {
        "English",
        "Hindi",
        "Marathi",
        "Telugu",
        "Tamil",
        "Kannada",
        "Malayalam",
    }
)

LANGUAGE_PROMPT = (
    "Welcome to the TVS Passenger 3W Assistant.\n\n"
    "Which language do you prefer?\n"
    "1. English\n"
    "2. हिंदी (Hindi)\n"
    "3. मराठी (Marathi)\n"
    "4. తెలుగు (Telugu)\n"
    "5. தமிழ் (Tamil)\n"
    "6. ಕನ್ನಡ (Kannada)\n"
    "7. മലയാളം (Malayalam)\n\n"
    "Reply with 1–7."
)

# Normalized state/UT name → language (languages we support end-to-end).
_STATE_LANGUAGE = {
    "maharashtra": "Marathi",
    "goa": "Marathi",
    "tamil nadu": "Tamil",
    "tamilnadu": "Tamil",
    "puducherry": "Tamil",
    "pondicherry": "Tamil",
    "andhra pradesh": "Telugu",
    "andhra": "Telugu",
    "telangana": "Telugu",
    "karnataka": "Kannada",
    "kerala": "Malayalam",
    "lakshadweep": "Malayalam",
    "uttar pradesh": "Hindi",
    "up": "Hindi",
    "bihar": "Hindi",
    "madhya pradesh": "Hindi",
    "mp": "Hindi",
    "rajasthan": "Hindi",
    "delhi": "Hindi",
    "nct of delhi": "Hindi",
    "new delhi": "Hindi",
    "haryana": "Hindi",
    "jharkhand": "Hindi",
    "chhattisgarh": "Hindi",
    "chattisgarh": "Hindi",
    "uttarakhand": "Hindi",
    "uttaranchal": "Hindi",
    "himachal pradesh": "Hindi",
    "himachal": "Hindi",
    "chandigarh": "Hindi",
}

_NAME_TO_LANGUAGE = {
    "1": "English",
    "english": "English",
    "eng": "English",
    "2": "Hindi",
    "hindi": "Hindi",
    "hin": "Hindi",
    "हिंदी": "Hindi",
    "हिन्दी": "Hindi",
    "3": "Marathi",
    "marathi": "Marathi",
    "mar": "Marathi",
    "मराठी": "Marathi",
    "4": "Telugu",
    "telugu": "Telugu",
    "tel": "Telugu",
    "తెలుగు": "Telugu",
    "5": "Tamil",
    "tamil": "Tamil",
    "tam": "Tamil",
    "தமிழ்": "Tamil",
    "6": "Kannada",
    "kannada": "Kannada",
    "kan": "Kannada",
    "ಕನ್ನಡ": "Kannada",
    "7": "Malayalam",
    "malayalam": "Malayalam",
    "malyalam": "Malayalam",
    "mal": "Malayalam",
    "മലയാളം": "Malayalam",
}

_NATIVE_SCRIPT_TOKENS = (
    "हिंदी",
    "हिन्दी",
    "मराठी",
    "తెలుగు",
    "தமிழ்",
    "ಕನ್ನಡ",
    "മലയാളം",
)


def normalize_state(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def language_from_state(state: str | None) -> str:
    """Map an Indian state/UT to a supported language; English if unknown."""
    key = normalize_state(state)
    if not key:
        return ""
    if key in _STATE_LANGUAGE:
        return _STATE_LANGUAGE[key]
    # Allow compact forms like "tamilnadu"
    compact = key.replace(" ", "")
    for name, language in _STATE_LANGUAGE.items():
        if name.replace(" ", "") == compact:
            return language
    return "English"


def _field(payload: dict, *names: str) -> str:
    """Read the first non-empty field, matching keys case-insensitively."""
    if not isinstance(payload, dict):
        return ""
    lowered = {str(key).strip().lower(): value for key, value in payload.items()}
    for name in names:
        if name in payload:
            value = payload.get(name)
        else:
            value = lowered.get(name.lower())
        text = str(value).strip() if value is not None else ""
        if text and text.lower() not in {"none", "null", "n/a", "-"}:
            return text
    return ""


def extract_state(payload: dict) -> str:
    """Pull state from JAM customer `data` using known aliases."""
    return _field(
        payload,
        "State",
        "state",
        "fldv_state",
        "fldv_State",
        "fldv_lead_state",
        "lead_state",
    )


def extract_preferred_language(payload: dict) -> str:
    """Explicit CRM language only — never invent from state/region."""
    value = _field(
        payload,
        "preferred_language",
        "language",
        "fldv_language",
        "fldv_preferred_language",
    )
    if value in SUPPORTED_LANGUAGES:
        return value
    mapped = _NAME_TO_LANGUAGE.get(value.lower())
    return mapped or ""


def language_from_remark(remark: str | None) -> str:
    """Recover preferred language we previously wrote into dispose remarks."""
    text = (remark or "").strip()
    if not text:
        return ""
    match = re.search(
        r"(?i)\bpreferred_language\s*:\s*([A-Za-z]+)",
        text,
    )
    if not match:
        return ""
    value = match.group(1).strip()
    if value in SUPPORTED_LANGUAGES:
        return value
    return _NAME_TO_LANGUAGE.get(value.lower()) or ""


def extract_customer_name(payload: dict) -> str:
    return _field(
        payload,
        "Customer Name",
        "customer_name",
        "name",
        "fldv_name",
        "fldv_customer_name",
    )


def parse_language_choice(text: str | None) -> str:
    """Accept 1-7 or language names/scripts. Empty if not a clear choice."""
    raw = (text or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    # Whole-message number / name
    if lowered in _NAME_TO_LANGUAGE:
        return _NAME_TO_LANGUAGE[lowered]
    if raw in _NAME_TO_LANGUAGE:
        return _NAME_TO_LANGUAGE[raw]
    # "2." / "2)" / "option 2"
    match = re.match(r"^\s*(?:option\s*)?([1-7])[\).:\-]?\s*$", lowered)
    if match:
        return _NAME_TO_LANGUAGE[match.group(1)]
    # Explicit native-script labels
    for token in _NATIVE_SCRIPT_TOKENS:
        if token in raw:
            return _NAME_TO_LANGUAGE[token]
    # Mid-chat English/name words with boundaries (avoid "eng" in "challenge")
    for pattern, language in (
        (r"\benglish\b", "English"),
        (r"\bhindi\b", "Hindi"),
        (r"\bmarathi\b", "Marathi"),
        (r"\btelugu\b", "Telugu"),
        (r"\btamil\b", "Tamil"),
        (r"\bkannada\b", "Kannada"),
        (r"\bmalayalam\b", "Malayalam"),
        (r"\bmalyalam\b", "Malayalam"),
    ):
        if re.search(pattern, lowered):
            return language
    return ""


def detect_script_language(text: str) -> str:
    if any("\u0d00" <= char <= "\u0d7f" for char in text):
        return "Malayalam"
    if any("\u0c80" <= char <= "\u0cff" for char in text):
        return "Kannada"
    if any("\u0c00" <= char <= "\u0c7f" for char in text):
        return "Telugu"
    if any("\u0b80" <= char <= "\u0bff" for char in text):
        return "Tamil"
    if any("\u0900" <= char <= "\u097f" for char in text):
        return "Hindi"
    return "English"


def is_language_only_reply(text: str | None, language: str) -> bool:
    """True when the user only picked a language, not a product message."""
    raw = (text or "").strip()
    if not raw:
        return False
    if parse_language_choice(raw) == language and len(raw) <= 24:
        return True
    return False

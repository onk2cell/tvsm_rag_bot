"""Deterministic routing after the language menu: vehicle flow or nearest PGM.

Answered by regex only — the same discipline as the language menu. A reply
that is not a clear choice is re-asked, never guessed by a model.
"""
from __future__ import annotations

import re

FLOW_VEHICLE = "vehicle"
FLOW_PGM = "pgm"

# "1" / "2." / "option 2" — the numbered options in the ask.
_OPTION_RE = re.compile(r"(?i)^\s*(?:option\s*)?([12])\s*[\).:\-]?\s*$")

_PGM_RE = re.compile(r"(?i)\bp\.?\s?g\.?\s?m\b|पीजीएम|పీజీఎం|பிஜிஎம்|ಪಿಜಿಎಂ|പിജിഎം")

_VEHICLE_RE = re.compile(
    r"(?i)\b("
    r"vehicle|vehical|gaadi|gadi|gaari|gaddi|vahan|"
    r"three\s*wheeler|3\s*w(?:heeler)?|auto|rickshaw|rikshaw|riksha|"
    r"king|ev\s*max|deluxe|duramax"
    r")\b|"
    r"वाहन|गाड़ी|गाडी|ऑटो|रिक्षा|रिक्शा|"
    r"వాహనం|ఆటో|రిక్షా|"
    r"வாகனம்|ஆட்டோ|"
    r"ವಾಹನ|ಆಟೋ|ರಿಕ್ಷಾ|"
    r"വാഹനം|ഓട്ടോ|റിക്ഷ"
)


def parse_flow_intent(text: str | None) -> str:
    """FLOW_VEHICLE, FLOW_PGM, or "" when the reply is not a clear choice.

    A numbered option decides outright. Otherwise a message naming only one
    side wins; naming both ("vehicle and PGM") is not a choice.
    """
    raw = (text or "").strip()
    if not raw:
        return ""
    match = _OPTION_RE.match(raw)
    if match:
        return FLOW_VEHICLE if match.group(1) == "1" else FLOW_PGM
    wants_pgm = bool(_PGM_RE.search(raw))
    wants_vehicle = bool(_VEHICLE_RE.search(raw))
    if wants_pgm and not wants_vehicle:
        return FLOW_PGM
    if wants_vehicle and not wants_pgm:
        return FLOW_VEHICLE
    return ""


# "2" / "2." / "option 2" / "no. 2" — a pick from the numbered PGM list.
_PICK_RE = re.compile(r"(?i)^\s*(?:option|no\.?|number)?\s*([1-9])\s*[\).:\-]?\s*$")


def parse_list_pick(text: str | None, count: int) -> int:
    """1-based index picked from a numbered list of ``count`` items, or 0.

    Only a bare number counts: "2 more" or a pincode is not a pick, and a
    number past the end of the list is nothing rather than clamped.
    """
    match = _PICK_RE.match(text or "")
    if not match:
        return 0
    number = int(match.group(1))
    return number if 1 <= number <= count else 0

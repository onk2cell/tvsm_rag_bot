"""Build JAM Dispose API payloads from qualification profiles."""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

DISPOSE_STATUSES = frozenset(
    {
        "interested",
        "not_interested",
        "already_purchased_tvs_motor",
        "not_enquired",
    }
)

PRODUCT_ALIASES: tuple[tuple[str, str], ...] = (
    ("duramax plus", "King Duramax Plus"),
    ("duramax", "King Duramax Plus"),
    ("dura max", "King Duramax Plus"),
    ("ड्यूरामैक्स", "King Duramax Plus"),
    ("ड्युरॅमॅक्स", "King Duramax Plus"),
    ("ड्युरामॅक्स", "King Duramax Plus"),
    ("ड्युरामैक्स", "King Duramax Plus"),
    ("डुरामॅक्स", "King Duramax Plus"),
    ("ड्यूरामॅक्स", "King Duramax Plus"),
    ("ev king max", "King EV MAX"),
    ("king max", "King EV MAX"),
    ("ev max", "King EV MAX"),
    ("king ev", "King EV MAX"),
    ("electric", "King EV MAX"),
    ("इलेक्ट्रिक", "King EV MAX"),
    ("इलेक्ट्रीक", "King EV MAX"),
    ("ईवी", "King EV MAX"),
    ("ईव्ही", "King EV MAX"),
    ("इव्ही", "King EV MAX"),
    ("ई व्ही", "King EV MAX"),
    ("ई-व्ही", "King EV MAX"),
    ("deluxe", "King Deluxe"),
    ("delux", "King Deluxe"),
    ("डीलक्स", "King Deluxe"),
    ("डिलक्स", "King Deluxe"),
    ("डीलक्ष", "King Deluxe"),
    ("डिलक्ष", "King Deluxe"),
)

DATE_DMY_RE = re.compile(
    r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b"
)
DATE_ORDINAL_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\b",
    re.I,
)
DATE_MONTH_NAME_RE = re.compile(
    r"\b(?P<month>"
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?"
    r")\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(?P<year>\d{2,4}))?\b"
    r"|"
    r"\b(?P<day2>\d{1,2})(?:st|nd|rd|th)?\s+(?P<month2>"
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?"
    r")(?:,?\s+(?P<year2>\d{2,4}))?\b",
    re.I,
)
_MONTH_NAME_TO_NUM = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
IN_DAYS_RE = re.compile(
    r"\b(?:in|within|after|next)\s+(\d{1,3})\s*days?\b",
    re.I,
)
NEXT_WEEK_RE = re.compile(r"\bnext\s+week\b", re.I)
THIS_MONTH_RE = re.compile(r"\bthis\s+month\b", re.I)
NEXT_MONTH_RE = re.compile(r"\bnext\s+month\b", re.I)
ASK_NEAR_TERM_DAYS = 10
CALLBACK_RE = re.compile(
    r"(?i)("
    r"\bcall\s*(?:me|back|karo|kara|please)\b|"
    r"\bcallback\b|"
    r"\bring\s*me\b|"
    r"\bphone\s*me\b|"
    r"कॉल\s*कर|"
    r"फोन\s*कर|"
    r"कॉल\s*करा|"
    r"फोन\s*करा"
    r")"
)


def wants_callback(text: str | None) -> bool:
    """True when the customer asks to be called back."""
    return bool(CALLBACK_RE.search((text or "").strip()))


@dataclass(frozen=True)
class PurchaseDateResult:
    value: str | None
    needs_exact_date: bool = False
    rule: str = ""


@dataclass(frozen=True)
class DisposePayload:
    body: dict[str, str]
    status: str


def normalize_product_name(text: str | None) -> str:
    raw = " ".join((text or "").lower().split())
    if not raw:
        return ""
    for needle, canonical in PRODUCT_ALIASES:
        if needle in raw:
            return canonical
    for canonical in ("King EV MAX", "King Deluxe", "King Duramax Plus"):
        if canonical.lower() in raw:
            return canonical
    return (text or "").strip()


def infer_dispose_status(profile: dict[str, Any] | None) -> str:
    profile = profile or {}
    explicit = str(profile.get("disposition") or "").strip().lower()
    if explicit in DISPOSE_STATUSES:
        return explicit
    if profile.get("callback_requested") or wants_callback(
        " ".join(
            str(profile.get(key) or "")
            for key in ("notes", "next_step", "blockers")
        )
    ):
        return "interested"
    if normalize_product_name(str(profile.get("product_interest") or "")):
        return "interested"
    notes = " ".join(
        str(profile.get(key) or "")
        for key in ("notes", "next_step", "blockers")
    ).lower()
    if "already purchased" in notes or "already bought" in notes:
        return "already_purchased_tvs_motor"
    if "not interested" in notes or "no interest" in notes:
        return "not_interested"
    return "not_enquired"


def format_dmy(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def resolve_purchase_date(
    text: str | None,
    *,
    today: date | None = None,
) -> PurchaseDateResult:
    """Map free-text purchase timing to DD/MM/YYYY.

    - Explicit calendar dates are accepted.
    - \"next month\" → 7th of next month.
    - \"in N days\" with N ≤ 10 → ask for an exact date (do not invent).
    - \"in N days\" with N > 10 → today + N.
    """
    today = today or date.today()
    raw = " ".join((text or "").split())
    if not raw:
        return PurchaseDateResult(None, needs_exact_date=True, rule="empty")

    dmy = DATE_DMY_RE.search(raw)
    if dmy:
        day, month, year = int(dmy.group(1)), int(dmy.group(2)), int(dmy.group(3))
        if year < 100:
            year += 2000
        try:
            return PurchaseDateResult(
                format_dmy(date(year, month, day)),
                rule="explicit_dmy",
            )
        except ValueError:
            pass

    month_name = DATE_MONTH_NAME_RE.search(raw)
    if month_name:
        month_raw = (month_name.group("month") or month_name.group("month2") or "").lower()
        day_raw = month_name.group("day") or month_name.group("day2")
        year_raw = month_name.group("year") or month_name.group("year2")
        month = _MONTH_NAME_TO_NUM.get(month_raw, 0)
        day = int(day_raw or 0)
        year = int(year_raw) if year_raw else today.year
        if year < 100:
            year += 2000
        if month and day:
            try:
                target = date(year, month, day)
                if year_raw is None and target < today:
                    target = date(today.year + 1, month, day)
                return PurchaseDateResult(
                    format_dmy(target),
                    rule="month_name",
                )
            except ValueError:
                pass

    lower = raw.lower()
    if NEXT_MONTH_RE.search(lower):
        year = today.year + (1 if today.month == 12 else 0)
        month = 1 if today.month == 12 else today.month + 1
        return PurchaseDateResult(
            format_dmy(date(year, month, 7)),
            rule="next_month_7th",
        )

    if THIS_MONTH_RE.search(lower):
        day = 7 if today.day < 7 else min(15, calendar.monthrange(today.year, today.month)[1])
        if day <= today.day:
            day = min(today.day + 1, calendar.monthrange(today.year, today.month)[1])
        return PurchaseDateResult(
            format_dmy(date(today.year, today.month, day)),
            rule="this_month",
        )

    if NEXT_WEEK_RE.search(lower):
        return PurchaseDateResult(
            format_dmy(today + timedelta(days=7)),
            rule="next_week",
        )

    days_match = IN_DAYS_RE.search(lower)
    if days_match:
        days = int(days_match.group(1))
        if days <= ASK_NEAR_TERM_DAYS:
            return PurchaseDateResult(
                None,
                needs_exact_date=True,
                rule="near_term_ask",
            )
        return PurchaseDateResult(
            format_dmy(today + timedelta(days=days)),
            rule="in_n_days",
        )

    # \"22nd this month\" / \"22nd\"
    if "month" in lower or "today" in lower or "tomorrow" in lower:
        if "tomorrow" in lower:
            return PurchaseDateResult(format_dmy(today + timedelta(days=1)), rule="tomorrow")
        if "today" in lower:
            return PurchaseDateResult(format_dmy(today), rule="today")
        ordinal = DATE_ORDINAL_RE.search(lower)
        if ordinal and "month" in lower:
            day = int(ordinal.group(1))
            last = calendar.monthrange(today.year, today.month)[1]
            day = min(max(day, 1), last)
            target = date(today.year, today.month, day)
            if target < today:
                year = today.year + (1 if today.month == 12 else 0)
                month = 1 if today.month == 12 else today.month + 1
                last = calendar.monthrange(year, month)[1]
                target = date(year, month, min(day, last))
            return PurchaseDateResult(format_dmy(target), rule="ordinal_month")

    return PurchaseDateResult(None, needs_exact_date=True, rule="unparsed")


def build_remark(profile: dict[str, Any] | None, *, extra: str = "") -> str:
    profile = profile or {}
    parts: list[str] = []
    if profile.get("callback_requested"):
        parts.append("callback")
    for key in (
        "preferred_language",
        "language",
        "notes",
        "next_step",
        "blockers",
        "purchase_timeline",
        "product_interest",
    ):
        value = profile.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value if item)
        text = str(value).strip()
        if not text:
            continue
        # Prefer a single language label in the remark.
        if key == "language" and profile.get("preferred_language"):
            continue
        label = "preferred_language" if key in {"preferred_language", "language"} else key
        if label == "preferred_language" and any(
            part.startswith("preferred_language:") for part in parts
        ):
            continue
        parts.append(f"{label}: {text}")
    if extra:
        parts.append(extra)
    remark = " | ".join(parts).strip()
    return remark or "WhatsApp qualification completed"


def resolve_dispose_customer_name(profile: dict[str, Any] | None) -> str:
    """Pick a real customer name for dispose ``customername`` (not stub labels)."""
    profile = profile or {}
    for key in ("customername", "customer_name", "lead_name", "name"):
        value = str(profile.get(key) or "").strip()
        if not value:
            continue
        lowered = value.lower()
        if lowered in {"none", "null", "n/a", "-", "unknown"}:
            continue
        # Stub identity from missing CRM lookup — never push that into CRM.
        if re.fullmatch(r"customer\s+\d+", lowered):
            continue
        return value
    return ""


def build_dispose_payload(
    *,
    mobile: str,
    profile: dict[str, Any] | None,
    dealer_code: str = "",
    pincode: str = "",
    today: date | None = None,
) -> DisposePayload | None:
    """Return dispose body, or None when required fields are still missing.

    JAM dispose v1.1 requires ``pincode`` (6-digit) for every status.
    New leads (number not in CRM) should also send ``customername``.
    """
    profile = dict(profile or {})
    if profile.get("callback_requested"):
        profile.setdefault("disposition", "interested")
        notes = str(profile.get("notes") or "").strip()
        if "callback" not in notes.lower():
            profile["notes"] = f"{notes} | callback".strip(" |")

    pin = _normalize_dispose_pincode(
        pincode
        or profile.get("pincode")
        or profile.get("pin_code")
        or ""
    )
    if not pin:
        return None

    status = infer_dispose_status(profile)
    remark = build_remark(profile)
    body: dict[str, str] = {
        "mobile": mobile,
        "pincode": pin,
        "status": status,
        "remark": remark,
    }
    customer_name = resolve_dispose_customer_name(profile)
    if customer_name:
        body["customername"] = customer_name
    if status != "interested":
        return DisposePayload(body=body, status=status)

    product = normalize_product_name(str(profile.get("product_interest") or ""))
    purchase = resolve_purchase_date(
        str(profile.get("purchase_timeline") or ""),
        today=today,
    )
    if purchase.needs_exact_date and not purchase.value:
        # Soft fallback after wrap-up: use +14 days so dispose can still push.
        fallback = format_dmy((today or date.today()) + timedelta(days=14))
        purchase = PurchaseDateResult(fallback, rule="fallback_14d")
        remark = build_remark(
            profile,
            extra=f"purchase_date_rule={purchase.rule}",
        )
        body["remark"] = remark

    code = (dealer_code or "").strip()
    if not product or not code or not purchase.value:
        # Still push a non-interested shape is wrong; push interested with what we have
        # only when required fields exist. Otherwise mark not_enquired so CRM gets a result.
        if not product or not code:
            body["status"] = "not_enquired"
            body["remark"] = build_remark(
                profile,
                extra="dispose_incomplete: missing product or dealer_code",
            )
            return DisposePayload(body=body, status="not_enquired")

    body.update(
        {
            "dealer_code": code,
            "expected_purchased_date": purchase.value or "",
            "product_name": product,
            "remark": body["remark"],
        }
    )
    return DisposePayload(body=body, status="interested")


def _normalize_dispose_pincode(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    # Prefer shared extract_pincode when available (spaced pins, etc.)
    try:
        from dealers import extract_pincode

        found = extract_pincode(text)
        if found:
            return found
    except Exception:
        pass
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 6 and digits[0] != "0":
        return digits
    return ""

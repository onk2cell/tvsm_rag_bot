"""Callable tool layer — dealer lookup, brochure send, CRM dispose, and
language switching.

Each tool wraps a plain "resolve_*" function that does the real work,
kept separate from the @tool wrapper so it's unit-testable without an LLM
(mirroring the reference boilerplate's resolve_dealer_location split).

Nothing in v1 binds these to the LLM (see bot/graph.py) — they're invoked
by deterministic Python, the same decision guarantees the current
guard-clause flow in client_processing.py already provides for dealer
lookup, brochure gating, and CRM dispose. Defining them as real @tools now
costs nothing and leaves the door open for LLM-driven tool-calling in a
later phase, once that's been proven safe against the regression suite.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from langchain_core.tools import tool

from client_language import parse_language_choice
from client_media_assets import (
    brochure_product_from_text,
    product_document_pack,
    wants_product_brochure,
)
from dealers import (
    DealerDirectory,
    extract_coordinates,
    extract_pincode,
    format_dealer_reply,
)
from dispose import DisposePayload, build_dispose_payload


@lru_cache
def _dealer_directory() -> DealerDirectory:
    return DealerDirectory()


def resolve_dealer_location(location: str, directory: DealerDirectory | None = None) -> str:
    """Resolve free-text pincode/place-name/coordinates to a dealer reply.

    Kept separate from the @tool wrapper so a fake directory can be
    injected in tests instead of hitting the real dataset + geocoder.
    """
    directory = directory or _dealer_directory()
    coords = extract_coordinates({"content": location})
    if coords is not None:
        dealer = directory.find_nearest_by_coords(*coords)
        if dealer is None:
            return "I couldn't find a nearby TVS dealer for that location."
        return format_dealer_reply(dealer)

    pincode = extract_pincode(location)
    if pincode:
        dealer = directory.find_nearest_by_pincode(pincode)
        if dealer is None:
            return f"I couldn't find a TVS dealer near pincode {pincode}."
        return format_dealer_reply(dealer, customer_pincode=pincode)

    # Unlike the webhook path, this runs only after the model decided the
    # text IS a location, so no place-name deny-list is needed here — a
    # bare number that isn't a valid pin is a typo, anything else is a
    # place the directory can accept or reject on its own.
    if re.fullmatch(r"[\d\s.\-]+", location.strip() or " "):
        return "That doesn't look like a valid 6-digit pincode. Please share your pincode."

    dealer = directory.find_nearest_by_place(location)
    if dealer is None:
        return (
            "I couldn't find a TVS dealer for that. Please share your 6-digit "
            "pincode or your WhatsApp current location."
        )
    return format_dealer_reply(dealer)


@tool
def find_nearest_dealer(location: str) -> str:
    """Find the nearest TVS dealer for the customer. `location` is normally
    a 6-digit Indian pincode, but also accepts a city/area name or
    coordinates typed as text (e.g. "18.52, 73.85")."""
    return resolve_dealer_location(location)


def resolve_brochure_pack(message: str, *hint_texts: str) -> list[tuple[str, str]]:
    """Return (url, kind) docs to send, or [] when this isn't an explicit
    request. `message` must contain an explicit ask (send/brochure/pdf/
    catalog/details/etc, any supported language) — naming a model alone is
    not enough, per the "share only on request" behavior spec."""
    if not wants_product_brochure(message):
        return []
    product = brochure_product_from_text(message, *hint_texts)
    if not product:
        return []
    return product_document_pack(product, message, *hint_texts)


@tool
def send_brochure(message: str, product_hint: str = "") -> list[tuple[str, str]]:
    """Return the brochure/warranty/PMS document pack for a product, but
    only when the customer explicitly asked for one (e.g. "send brochure",
    "share catalog", "pdf details") — never on a bare product mention."""
    return resolve_brochure_pack(message, product_hint)


def resolve_dispose_payload(
    *,
    mobile: str,
    profile: dict[str, Any] | None,
    dealer_code: str = "",
    pincode: str = "",
) -> DisposePayload | None:
    return build_dispose_payload(
        mobile=mobile, profile=profile, dealer_code=dealer_code, pincode=pincode
    )


@tool
def dispose_lead(
    mobile: str, profile: dict[str, Any], dealer_code: str = "", pincode: str = ""
) -> dict[str, str] | None:
    """Build the JAM CRM dispose payload for a lead, or None when a
    required field (pincode) is still missing."""
    payload = resolve_dispose_payload(
        mobile=mobile, profile=profile, dealer_code=dealer_code, pincode=pincode
    )
    return payload.body if payload else None


def resolve_language_switch(text: str) -> str:
    """Parse an explicit language choice/name from free text, or ''."""
    return parse_language_choice(text)


@tool
def switch_language(text: str) -> str:
    """Return the supported language explicitly named/selected in `text`
    (e.g. "switch to Hindi", "2", "मराठी"), or "" if none was named."""
    return resolve_language_switch(text)


tools = [find_nearest_dealer, send_brochure, dispose_lead, switch_language]

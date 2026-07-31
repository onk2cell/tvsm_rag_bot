"""Tests for the bot/tools.py tool layer — resolver functions exercised
directly (no LLM), plus a couple of @tool wrapper smoke tests."""
from __future__ import annotations

from bot.tools import (
    dispose_lead,
    find_nearest_dealer,
    resolve_brochure_pack,
    resolve_dealer_location,
    resolve_dispose_payload,
    resolve_language_switch,
    send_brochure,
    switch_language,
)
from dealers import DealerDirectory

SAMPLE_DEALERS = [
    {
        "dealer_code": "11689",
        "name": "Shah Auto",
        "address": "Pune, Maharashtra, 411048",
        "pincode": "411048",
        "phone": "9000000001",
        "spoc_name": "Ravi",
        "map_url": "https://www.google.com/maps?q=18.52,73.85",
        "latitude": 18.5204,
        "longitude": 73.8567,
        "state_name": "MAHARASHTRA",
        "town_name": "Pune",
    },
]


class FakeGeocoder:
    def __init__(self, mapping: dict[str, tuple[float, float] | None]):
        self.mapping = mapping

    def geocode(self, pincode: str) -> tuple[float, float] | None:
        return self.mapping.get(pincode)


def test_resolve_dealer_location_by_pincode():
    directory = DealerDirectory(
        SAMPLE_DEALERS, geocoder=FakeGeocoder({"411001": (18.53, 73.85)})
    )
    reply = resolve_dealer_location("411001", directory)
    assert "Shah Auto" in reply
    assert "Pune, Maharashtra, 411048" in reply


def test_resolve_dealer_location_by_coordinates():
    directory = DealerDirectory(SAMPLE_DEALERS, geocoder=FakeGeocoder({}))
    reply = resolve_dealer_location("18.52, 73.85", directory)
    assert "Shah Auto" in reply


def test_resolve_dealer_location_invalid_pincode_asks_again():
    directory = DealerDirectory(SAMPLE_DEALERS, geocoder=FakeGeocoder({}))
    reply = resolve_dealer_location("41100", directory)
    assert "valid 6-digit pincode" in reply


def test_resolve_dealer_location_no_signal_asks_for_pincode():
    directory = DealerDirectory(SAMPLE_DEALERS, geocoder=FakeGeocoder({}))
    reply = resolve_dealer_location("hello there", directory)
    assert "pincode" in reply.lower()


def test_find_nearest_dealer_tool_invokes_resolver(monkeypatch):
    directory = DealerDirectory(
        SAMPLE_DEALERS, geocoder=FakeGeocoder({"411001": (18.53, 73.85)})
    )
    monkeypatch.setattr("bot.tools._dealer_directory", lambda: directory)
    result = find_nearest_dealer.invoke({"location": "411001"})
    assert "Shah Auto" in result


def test_resolve_brochure_pack_requires_explicit_request():
    assert resolve_brochure_pack("King deluxe") == []


def test_resolve_brochure_pack_on_explicit_ask():
    pack = resolve_brochure_pack("Please send me the King Deluxe brochure")
    kinds = [kind for _, kind in pack]
    assert "brochure" in kinds
    assert len(pack) >= 1


def test_resolve_brochure_pack_no_product_returns_empty():
    assert resolve_brochure_pack("Please send me the brochure") == []


def test_send_brochure_tool_gated_same_as_resolver():
    assert send_brochure.invoke({"message": "King deluxe", "product_hint": ""}) == []
    pack = send_brochure.invoke(
        {"message": "send me the king deluxe brochure", "product_hint": ""}
    )
    assert pack


def test_resolve_dispose_payload_none_without_pincode():
    assert resolve_dispose_payload(mobile="+911234567890", profile={}) is None


def test_resolve_dispose_payload_builds_body_with_pincode():
    payload = resolve_dispose_payload(
        mobile="+911234567890", profile={"disposition": "not_interested"}, pincode="411001"
    )
    assert payload is not None
    assert payload.body["pincode"] == "411001"
    assert payload.body["mobile"] == "+911234567890"


def test_dispose_lead_tool_matches_resolver():
    assert dispose_lead.invoke(
        {"mobile": "+911234567890", "profile": {}, "dealer_code": "", "pincode": ""}
    ) is None
    body = dispose_lead.invoke(
        {
            "mobile": "+911234567890",
            "profile": {"disposition": "not_interested"},
            "dealer_code": "",
            "pincode": "411001",
        }
    )
    assert body["pincode"] == "411001"


def test_resolve_language_switch_parses_explicit_choice():
    assert resolve_language_switch("switch to Hindi") == "Hindi"
    assert resolve_language_switch("2") == "Hindi"
    assert resolve_language_switch("just chatting") == ""


def test_switch_language_tool_matches_resolver():
    assert switch_language.invoke({"text": "मराठी"}) == "Marathi"

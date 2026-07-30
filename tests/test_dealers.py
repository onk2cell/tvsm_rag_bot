"""Nearest-dealer matching from customer pincode."""
from __future__ import annotations

from dealers import (
    DealerDirectory,
    extract_coordinates,
    extract_pincode,
    format_dealer_confirm_ask,
    format_dealer_reply,
    haversine_km,
)


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
    {
        "dealer_code": "10824",
        "name": "Kanchana Motors",
        "address": "Mangalore, Karnataka, 575006",
        "pincode": "575006",
        "phone": "7353767891",
        "spoc_name": "Rachana",
        "map_url": "https://www.google.com/maps?q=12.87,74.88",
        "latitude": 12.8708,
        "longitude": 74.8819,
        "state_name": "KARNATAKA",
        "town_name": "Mangalore",
    },
]


class FakeGeocoder:
    def __init__(self, mapping: dict[str, tuple[float, float] | None]):
        self.mapping = mapping
        self.calls: list[str] = []

    def geocode(self, pincode: str) -> tuple[float, float] | None:
        self.calls.append(pincode)
        return self.mapping.get(pincode)


def test_extract_pincode_from_mixed_text():
    assert extract_pincode("My pin is 411001 thanks") == "411001"
    assert extract_pincode("call 9000000001") == ""
    assert extract_pincode("pin 041100") == ""


def test_looks_like_invalid_pincode_wrong_length():
    from dealers import looks_like_invalid_pincode

    assert looks_like_invalid_pincode("41100")  # 5 digits
    assert looks_like_invalid_pincode("4110011")  # 7 digits
    assert looks_like_invalid_pincode("041100")  # leading zero
    assert looks_like_invalid_pincode("pin 41100")
    assert not looks_like_invalid_pincode("411001")
    assert not looks_like_invalid_pincode("8459522206")  # mobile
    assert not looks_like_invalid_pincode("Parbhani")
    assert not looks_like_invalid_pincode("Yes")


def test_looks_like_place_name():
    from dealers import looks_like_place_name

    assert looks_like_place_name("Parbhani")
    assert looks_like_place_name("Pune")
    assert not looks_like_place_name("King deluxe")
    assert not looks_like_place_name("I don't know my pincode")
    assert not looks_like_place_name("Yes")


def test_extract_pincode_collapses_spaced_and_dashed_digits():
    assert extract_pincode("41 10 35") == "411035"
    assert extract_pincode("पुणे 41 10 35 येथे") == "411035"
    assert extract_pincode("44-11-33") == "441133"
    assert extract_pincode("411.035") == "411035"


def test_haversine_same_point_is_zero():
    assert haversine_km(18.5, 73.8, 18.5, 73.8) == 0.0


def test_find_nearest_by_pincode_picks_closest_dealer():
    directory = DealerDirectory(
        SAMPLE_DEALERS,
        geocoder=FakeGeocoder({"411001": (18.53, 73.85)}),
    )

    dealer = directory.find_nearest_by_pincode("411001")

    assert dealer is not None
    assert dealer.dealer_code == "11689"
    assert dealer.name == "Shah Auto"
    assert dealer.distance_km is not None
    assert dealer.distance_km < 5


def test_find_nearest_returns_none_when_pincode_unknown():
    directory = DealerDirectory(
        SAMPLE_DEALERS,
        geocoder=FakeGeocoder({"999999": None}),
    )

    assert directory.find_nearest_by_pincode("999999") is None


def test_find_nearest_by_coords_picks_closest_dealer():
    directory = DealerDirectory(SAMPLE_DEALERS, geocoder=FakeGeocoder({}))

    dealer = directory.find_nearest_by_coords(18.52, 73.85)

    assert dealer is not None
    assert dealer.dealer_code == "11689"
    assert dealer.distance_km is not None
    assert dealer.distance_km < 2


def test_extract_coordinates_from_top_level_and_content():
    assert extract_coordinates(
        {"latitude": 18.52, "longitude": 73.85}
    ) == (18.52, 73.85)
    assert extract_coordinates({"lat": "12.87", "lng": "74.88"}) == (12.87, 74.88)
    assert extract_coordinates(
        {"content": "https://www.google.com/maps?q=18.52,73.85"}
    ) == (18.52, 73.85)
    assert extract_coordinates({"type": "location", "content": ""}) is None


def test_format_dealer_reply_includes_contact_and_map():
    directory = DealerDirectory(
        SAMPLE_DEALERS,
        geocoder=FakeGeocoder({"411001": (18.53, 73.85)}),
    )
    dealer = directory.find_nearest_by_pincode("411001")
    assert dealer is not None

    text = format_dealer_reply(dealer, customer_pincode="411001")

    assert "411001" in text
    assert "Shah Auto" in text
    assert "Phone: Ravi - 9000000001" in text
    assert "Map:" in text


def test_get_by_code_and_confirm_ask():
    directory = DealerDirectory(SAMPLE_DEALERS, geocoder=FakeGeocoder({}))
    dealer = directory.get_by_code("11689")
    assert dealer is not None
    assert dealer.name == "Shah Auto"

    ask = format_dealer_confirm_ask(
        name=dealer.name,
        address=dealer.address,
        phone=dealer.phone,
        spoc_name=dealer.spoc_name,
        map_url=dealer.map_url,
    )
    assert "Name: Shah Auto" in ask
    assert "Address:" in ask
    assert "Reply Yes or No" in ask
    assert directory.get_by_code("missing") is None


def test_confirm_ask_falls_back_to_city_without_address():
    ask = format_dealer_confirm_ask(name="Sarthak Auto", city="Pune")
    assert "Name: Sarthak Auto" in ask
    assert "Address: Pune" in ask


def test_built_dealers_keep_maharashtra_towns_in_maharashtra():
    import json
    from pathlib import Path

    path = Path("data/dealers.json")
    if not path.exists():
        return
    dealers = json.loads(path.read_text(encoding="utf-8"))
    mh = [
        item
        for item in dealers
        if item.get("state_name") == "MAHARASHTRA" and item.get("latitude") is not None
    ]
    assert mh
    for item in mh:
        # Maharashtra roughly 15.5–22.1N, 72.6–80.9E
        assert 15.0 <= float(item["latitude"]) <= 22.5, item
        assert 72.0 <= float(item["longitude"]) <= 81.5, item

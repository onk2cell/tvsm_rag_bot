"""Nearest-PGM lookup and the workbook build behind it."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pgms import PgmDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_pgms import build_pgms, parse_coordinate  # noqa: E402

# Around MG Road, Bengaluru (12.975, 77.606).
PGMS = [
    {"dms_id": "1", "name": "Near One", "latitude": 12.976, "longitude": 77.607, "phone": "1"},
    {"dms_id": "2", "name": "Near Two", "latitude": 12.985, "longitude": 77.610, "phone": "2"},
    {"dms_id": "3", "name": "Near Three", "latitude": 13.000, "longitude": 77.620, "phone": "3"},
    {"dms_id": "4", "name": "Near Four", "latitude": 13.020, "longitude": 77.640, "phone": "4"},
    {"dms_id": "5", "name": "Tumkur", "latitude": 13.340, "longitude": 77.100, "phone": "5"},
    {"dms_id": "6", "name": "Pune", "latitude": 18.520, "longitude": 73.856, "phone": "6"},
    {"dms_id": "7", "name": "No coords", "latitude": None, "longitude": None},
]


class FakeGeocoder:
    def __init__(self, coords):
        self.coords = coords
        self.calls = []

    def geocode(self, pincode):
        self.calls.append(pincode)
        return self.coords


def test_nearest_by_coords_is_ranked_and_capped_at_the_limit():
    directory = PgmDirectory(PGMS, geocoder=FakeGeocoder(None))

    nearest = directory.find_nearest_by_coords(12.975, 77.606)

    assert [pgm.dms_id for pgm in nearest] == ["1", "2", "3"]
    assert nearest[0].distance_km < nearest[1].distance_km < nearest[2].distance_km
    assert nearest[0].distance_km < 0.5


def test_nearest_by_coords_drops_everything_past_the_radius():
    directory = PgmDirectory(PGMS, geocoder=FakeGeocoder(None), max_km=50)

    # Mysuru: Tumkur is ~110 km, Bengaluru ~140 km, Pune far away.
    assert directory.find_nearest_by_coords(12.295, 76.639) == []
    # Nelamangala: Bengaluru garages are inside 50 km, Tumkur is not.
    near = directory.find_nearest_by_coords(13.10, 77.39)
    assert {pgm.dms_id for pgm in near} <= {"1", "2", "3", "4"}
    assert all(pgm.distance_km <= 50 for pgm in near)


def test_nearest_by_pincode_distinguishes_no_geocode_from_none_in_range():
    unresolved = PgmDirectory(PGMS, geocoder=FakeGeocoder(None))
    assert unresolved.find_nearest_by_pincode("560001") is None

    geocoder = FakeGeocoder((12.975, 77.606))
    resolved = PgmDirectory(PGMS, geocoder=geocoder, limit=2)
    nearest = resolved.find_nearest_by_pincode("560001")
    assert geocoder.calls == ["560001"]
    assert [pgm.dms_id for pgm in nearest] == ["1", "2"]

    far = PgmDirectory(PGMS, geocoder=FakeGeocoder((28.61, 77.21)))  # Delhi
    assert far.find_nearest_by_pincode("110001") == []


def test_get_by_id_and_rows_without_coordinates():
    directory = PgmDirectory(PGMS, geocoder=FakeGeocoder(None))

    assert directory.get_by_id("4").name == "Near Four"
    assert directory.get_by_id("4").distance_km is None
    assert directory.get_by_id("7") is None
    assert directory.get_by_id("") is None


# --- scripts/build_pgms.py ---------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        (12.958952, 12.958952),
        ("\xa013.038776  ", 13.038776),
        ("  12.903125,  ", 12.903125),
        (13, 13.0),
        ("x", None),
        (" ", None),
        (None, None),
        (77569063, None),   # decimal point lost in the sheet
        (True, None),
    ],
)
def test_parse_coordinate(raw, expected):
    assert parse_coordinate(raw, (6.0, 38.0)) == expected


def test_build_pgms_cleans_rows_and_reports_the_dropped_ones():
    rows = [
        {
            "dms_id": 58724079, "name": "Anees Auto Works", "owner_name": "Ajaz",
            "phone": 8722574132, "address": " VIDYARANYAPURA\xa0 BANGALORE ",
            "area": "VIDYARANYAPURA", "zone": "North", "division": "Blr 1",
            "latitude": "\xa013.083038", "longitude": 77.5506637,
            "map_url": "https://maps.app.goo.gl/abc",
        },
        {
            "dms_id": 2, "name": "SADIK PASHA", "owner_name": "Sadik Pasha",
            "phone": "97389 67863", "address": "Austin Town", "area": "Austin Town",
            "latitude": 12.95, "longitude": 77.61, "map_url": None,
        },
        {"dms_id": 3, "name": "RM AUTO", "latitude": "x", "longitude": " "},
        {"dms_id": 4, "name": "", "owner_name": "", "latitude": 12.9, "longitude": 77.6},
    ]

    pgms, dropped = build_pgms(rows)

    assert [p["dms_id"] for p in pgms] == ["58724079", "2"]
    first, second = pgms
    assert first["name"] == "Anees Auto Works"
    assert first["owner_name"] == "Ajaz"
    assert first["phone"] == "8722574132"
    assert first["address"] == "VIDYARANYAPURA BANGALORE"
    assert first["latitude"] == 13.083038
    assert first["map_url"] == "https://maps.app.goo.gl/abc"
    # Owner repeated as the garage name is dropped; the map link is derived.
    assert second["owner_name"] == ""
    assert second["phone"] == "9738967863"
    assert second["map_url"] == "https://maps.google.com/?q=12.95,77.61"
    assert len(dropped) == 2
    assert "RM AUTO" in dropped[0] and "coordinates" in dropped[0]
    assert "no garage or owner name" in dropped[1]

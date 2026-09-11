"""Nearest-PGM lookup: customer coordinates (or a geocoded pincode) against
the garages in data/pgms.json, built by scripts/build_pgms.py.

Unlike dealers.DealerDirectory this returns a ranked list, not one hit —
the customer picks from the closest few — and applies a hard radius: the
dataset covers one city, and the nearest garage to a customer 300 km away
is not an answer.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from dealers import NominatimPincodeGeocoder, haversine_km

DEFAULT_PGMS_PATH = Path("data/pgms.json")
DEFAULT_LIMIT = 3
DEFAULT_MAX_KM = 50.0


@dataclass(frozen=True)
class Pgm:
    dms_id: str
    name: str
    phone: str
    address: str
    area: str
    map_url: str
    latitude: float
    longitude: float
    owner_name: str = ""
    distance_km: float | None = None


class PgmDirectory:
    def __init__(
        self,
        pgms: list[dict] | None = None,
        *,
        pgms_path: Path = DEFAULT_PGMS_PATH,
        geocoder: NominatimPincodeGeocoder | None = None,
        limit: int = DEFAULT_LIMIT,
        max_km: float = DEFAULT_MAX_KM,
    ):
        raw = pgms
        if raw is None:
            raw = json.loads(pgms_path.read_text(encoding="utf-8"))
        self._pgms = [
            item
            for item in raw
            if item.get("latitude") is not None and item.get("longitude") is not None
        ]
        self._by_id = {
            str(item.get("dms_id") or ""): item
            for item in self._pgms
            if str(item.get("dms_id") or "")
        }
        self._geocoder = geocoder or NominatimPincodeGeocoder()
        self._limit = limit
        self._max_km = max_km

    @property
    def max_km(self) -> float:
        return self._max_km

    def get_by_id(self, dms_id: str) -> Pgm | None:
        item = self._by_id.get((dms_id or "").strip())
        return self._to_pgm(item) if item else None

    def find_nearest_by_pincode(self, pincode: str) -> list[Pgm] | None:
        """Closest PGMs to a pincode; None when the pincode cannot be
        geocoded (as opposed to an empty list: geocoded, none in range)."""
        coords = self._geocoder.geocode(pincode)
        if coords is None:
            return None
        return self.find_nearest_by_coords(coords[0], coords[1])

    def find_nearest_by_coords(self, latitude: float, longitude: float) -> list[Pgm]:
        ranked = sorted(
            (
                (
                    haversine_km(
                        latitude,
                        longitude,
                        float(item["latitude"]),
                        float(item["longitude"]),
                    ),
                    index,
                    item,
                )
                for index, item in enumerate(self._pgms)
            ),
            key=lambda entry: entry[:2],
        )
        return [
            self._to_pgm(item, distance_km=distance)
            for distance, _, item in ranked[: self._limit]
            if distance <= self._max_km
        ]

    @staticmethod
    def _to_pgm(item: dict, *, distance_km: float | None = None) -> Pgm:
        return Pgm(
            dms_id=str(item.get("dms_id") or ""),
            name=str(item.get("name") or ""),
            phone=str(item.get("phone") or ""),
            address=str(item.get("address") or ""),
            area=str(item.get("area") or ""),
            map_url=str(item.get("map_url") or ""),
            latitude=float(item["latitude"]),
            longitude=float(item["longitude"]),
            owner_name=str(item.get("owner_name") or ""),
            distance_km=distance_km,
        )

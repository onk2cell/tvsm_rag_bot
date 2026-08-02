"""Nearest-dealership lookup from customer pincode (geocoded) to dealer lat/lng."""
from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PINCODE_RE = re.compile(r"(?<!\d)([1-9]\d{5})(?!\d)")
DEFAULT_DEALERS_PATH = Path("data/dealers.json")
DEFAULT_GEOCODE_CACHE_PATH = Path("data/pincode_geocode_cache.json")
# Reject city/area routing when nearest listed dealer is farther than this.
MAX_PLACE_DEALER_KM = 120.0


@dataclass(frozen=True)
class Dealer:
    dealer_code: str
    name: str
    address: str
    pincode: str
    phone: str
    map_url: str
    latitude: float
    longitude: float
    spoc_name: str = ""
    state_name: str = ""
    town_name: str = ""
    distance_km: float | None = None


def extract_pincode(text: str | None) -> str:
    """Return a 6-digit Indian pincode from free text.

    Accepts continuous pins and spaced/dashed forms such as ``41 10 35``
    or ``44-11-33`` by collapsing digit separators first.
    """
    if not text:
        return ""
    match = PINCODE_RE.search(text)
    if match:
        return match.group(1)
    collapsed = re.sub(r"(?<=\d)[\s.\-](?=\d)", "", text)
    match = PINCODE_RE.search(collapsed)
    return match.group(1) if match else ""


# NOTE: ``looks_like_invalid_pincode`` and ``looks_like_place_name`` used to
# live here and gated the share-location replies. Both were deny-lists, so
# every unlisted word became a city name ("okk", "thik hai", "hmm") and every
# short number became a typo'd pin (a budget of "50000", a year "2025") — and
# neither knew what the bot had just asked. bot.graph.classify_location_reply
# makes that call now, with the last bot message as context.


def haversine_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


_MAPS_COORDS_RE = re.compile(
    r"(?:maps\?q=|@)(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)",
    re.I,
)


def extract_coordinates(payload: dict) -> tuple[float, float] | None:
    """Pull lat/lng from a location webhook event (several JAM shapes)."""
    if not isinstance(payload, dict):
        return None

    nested = payload.get("location")
    sources = [payload]
    if isinstance(nested, dict):
        sources.append(nested)

    for source in sources:
        lat = _as_float(
            source.get("latitude", source.get("lat", source.get("Latitude")))
        )
        lng = _as_float(
            source.get(
                "longitude",
                source.get("lng", source.get("long", source.get("Longitude"))),
            )
        )
        if lat is not None and lng is not None and _valid_coords(lat, lng):
            return lat, lng

    content = payload.get("content")
    if isinstance(content, str) and content.strip():
        text = content.strip()
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict):
            nested_coords = extract_coordinates(parsed)
            if nested_coords is not None:
                return nested_coords
        match = _MAPS_COORDS_RE.search(text)
        if match:
            lat, lng = float(match.group(1)), float(match.group(2))
            if _valid_coords(lat, lng):
                return lat, lng
        parts = re.split(r"[\s,;]+", text)
        if len(parts) >= 2:
            lat, lng = _as_float(parts[0]), _as_float(parts[1])
            if lat is not None and lng is not None and _valid_coords(lat, lng):
                return lat, lng
    return None


def _as_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _valid_coords(lat: float, lng: float) -> bool:
    return -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0


def format_dealer_reply(dealer: Dealer, *, customer_pincode: str = "") -> str:
    if customer_pincode:
        header = f"Nearest TVS dealer for pincode {customer_pincode}:"
    else:
        header = "Nearest TVS dealer for your shared location:"
    lines = [
        header,
        "",
        dealer.name,
    ]
    if dealer.address:
        lines.append(dealer.address)
    if dealer.phone:
        contact = dealer.phone
        if dealer.spoc_name:
            contact = f"{dealer.spoc_name} - {dealer.phone}"
        lines.append(f"Phone: {contact}")
    if dealer.map_url:
        lines.append(f"Map: {dealer.map_url}")
    if dealer.distance_km is not None:
        lines.append(f"Approx. distance: {dealer.distance_km:.1f} km")
    return "\n".join(lines)


def format_dealer_confirm_ask(
    *,
    name: str,
    address: str = "",
    phone: str = "",
    spoc_name: str = "",
    map_url: str = "",
    city: str = "",
    language: str = "English",
) -> str:
    """Ask whether this dealership (name + address mandatory) is OK."""
    from client_static_messages import dealer_confirm_ask

    return dealer_confirm_ask(
        name=name,
        address=address,
        phone=phone,
        spoc_name=spoc_name,
        map_url=map_url,
        city=city,
        language=language,
    )


def format_dealer_confirm_ask_from_dealer(
    dealer: Dealer,
    *,
    language: str = "English",
) -> str:
    return format_dealer_confirm_ask(
        name=dealer.name,
        address=dealer.address,
        phone=dealer.phone,
        spoc_name=dealer.spoc_name,
        map_url=dealer.map_url,
        city=dealer.town_name,
        language=language,
    )


class NominatimPincodeGeocoder:
    """Resolve Indian pincodes to lat/lng via OpenStreetMap Nominatim."""

    def __init__(
        self,
        *,
        cache_path: Path = DEFAULT_GEOCODE_CACHE_PATH,
        user_agent: str = "tvsm-rag-bot/1.0 (dealer-routing)",
        timeout: float = 20,
        min_interval_sec: float = 1.1,
        sleeper: Callable[[float], None] = time.sleep,
        opener=urlopen,
    ):
        self._cache_path = cache_path
        self._user_agent = user_agent
        self._timeout = timeout
        self._min_interval_sec = min_interval_sec
        self._sleep = sleeper
        self._opener = opener
        self._cache = self._load_cache()
        self._last_request_at = 0.0

    def geocode(self, pincode: str) -> tuple[float, float] | None:
        key = (pincode or "").strip()
        if not re.fullmatch(r"[1-9]\d{5}", key):
            return None
        cached = self._cache.get(key)
        if isinstance(cached, dict) and "lat" in cached and "lon" in cached:
            return float(cached["lat"]), float(cached["lon"])
        if cached is None and key in self._cache:
            return None

        self._throttle()
        query = urlencode(
            {
                "postalcode": key,
                "country": "India",
                "format": "json",
                "limit": 1,
            }
        )
        request = Request(
            f"https://nominatim.openstreetmap.org/search?{query}",
            headers={"User-Agent": self._user_agent},
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return None
        if not payload:
            self._cache[key] = None
            self._save_cache()
            return None
        lat = float(payload[0]["lat"])
        lon = float(payload[0]["lon"])
        self._cache[key] = {"lat": lat, "lon": lon}
        self._save_cache()
        return lat, lon

    def geocode_place(self, place: str) -> tuple[float, float] | None:
        """Resolve a city/area name in India to lat/lng."""
        label = " ".join((place or "").strip().split())
        if not label:
            return None
        cache_key = f"place:{label.lower()}"
        cached = self._cache.get(cache_key)
        if isinstance(cached, dict) and "lat" in cached and "lon" in cached:
            return float(cached["lat"]), float(cached["lon"])
        if cached is None and cache_key in self._cache:
            return None

        self._throttle()
        query = urlencode(
            {
                "q": f"{label}, India",
                "countrycodes": "in",
                "format": "json",
                "limit": 1,
            }
        )
        request = Request(
            f"https://nominatim.openstreetmap.org/search?{query}",
            headers={"User-Agent": self._user_agent},
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return None
        if not payload:
            self._cache[cache_key] = None
            self._save_cache()
            return None
        lat = float(payload[0]["lat"])
        lon = float(payload[0]["lon"])
        self._cache[cache_key] = {"lat": lat, "lon": lon}
        self._save_cache()
        return lat, lon

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._min_interval_sec:
            self._sleep(self._min_interval_sec - elapsed)
        self._last_request_at = time.monotonic()

    def _load_cache(self) -> dict:
        if not self._cache_path.exists():
            return {}
        try:
            return json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return {}

    def _save_cache(self) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps(self._cache, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass


class DealerDirectory:
    def __init__(
        self,
        dealers: list[dict] | None = None,
        *,
        dealers_path: Path = DEFAULT_DEALERS_PATH,
        geocoder: NominatimPincodeGeocoder | None = None,
    ):
        raw = dealers
        if raw is None:
            raw = json.loads(dealers_path.read_text(encoding="utf-8"))
        self._all = list(raw)
        self._dealers = [
            item
            for item in raw
            if item.get("latitude") is not None and item.get("longitude") is not None
        ]
        self._by_code = {
            str(item.get("dealer_code") or "").strip(): item
            for item in raw
            if str(item.get("dealer_code") or "").strip()
        }
        self._geocoder = geocoder or NominatimPincodeGeocoder()

    def get_by_code(self, dealer_code: str) -> Dealer | None:
        item = self._by_code.get((dealer_code or "").strip())
        if not item:
            return None
        return self._to_dealer(item)

    def get_by_name(self, name: str) -> Dealer | None:
        """Case-insensitive dealership name lookup (CRM often omits the code)."""
        needle = " ".join((name or "").lower().split())
        if not needle:
            return None
        for item in self._all:
            if " ".join(str(item.get("name") or "").lower().split()) == needle:
                return self._to_dealer(item)
        return None

    @staticmethod
    def _to_dealer(item: dict) -> Dealer:
        lat = item.get("latitude")
        lon = item.get("longitude")
        return Dealer(
            dealer_code=str(item.get("dealer_code") or ""),
            name=str(item.get("name") or ""),
            address=str(item.get("address") or ""),
            pincode=str(item.get("pincode") or ""),
            phone=str(item.get("phone") or ""),
            map_url=str(item.get("map_url") or ""),
            latitude=float(lat) if lat is not None else 0.0,
            longitude=float(lon) if lon is not None else 0.0,
            spoc_name=str(item.get("spoc_name") or ""),
            state_name=str(item.get("state_name") or ""),
            town_name=str(item.get("town_name") or ""),
        )

    def find_nearest_by_pincode(self, pincode: str) -> Dealer | None:
        coords = self._geocoder.geocode(pincode)
        if coords is None:
            return None
        return self.find_nearest_by_coords(coords[0], coords[1])

    def find_nearest_by_place(
        self,
        place: str,
        *,
        max_km: float = MAX_PLACE_DEALER_KM,
    ) -> Dealer | None:
        """Nearest listed dealer for a city/area name, or None if too far/unknown."""
        geocode_place = getattr(self._geocoder, "geocode_place", None)
        if not callable(geocode_place):
            return None
        coords = geocode_place(place)
        if coords is None:
            return None
        dealer = self.find_nearest_by_coords(coords[0], coords[1])
        if dealer is None:
            return None
        if dealer.distance_km is not None and dealer.distance_km > max_km:
            return None
        return dealer

    def find_nearest_by_coords(
        self,
        latitude: float,
        longitude: float,
    ) -> Dealer | None:
        if not self._dealers:
            return None
        best: dict | None = None
        best_distance = float("inf")
        for item in self._dealers:
            distance = haversine_km(
                latitude,
                longitude,
                float(item["latitude"]),
                float(item["longitude"]),
            )
            if distance < best_distance:
                best_distance = distance
                best = item
        if best is None:
            return None
        return Dealer(
            dealer_code=str(best.get("dealer_code") or ""),
            name=str(best.get("name") or ""),
            address=str(best.get("address") or ""),
            pincode=str(best.get("pincode") or ""),
            phone=str(best.get("phone") or ""),
            map_url=str(best.get("map_url") or ""),
            latitude=float(best["latitude"]),
            longitude=float(best["longitude"]),
            spoc_name=str(best.get("spoc_name") or ""),
            state_name=str(best.get("state_name") or ""),
            town_name=str(best.get("town_name") or ""),
            distance_km=best_distance,
        )

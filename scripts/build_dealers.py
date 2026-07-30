#!/usr/bin/env python3
"""Build data/dealers.json from the client CSV + CMB dealer PDF.

Coordinates are resolved by geocoding town/state (and valid pincodes).
PDF map annotations are attached only when they fall near that location —
never by row index (annotation order does not match text order).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pypdf import PdfReader

MAP_RE = re.compile(r"maps\?q=([-0-9.]+),([-0-9.]+)", re.I)
PIN_RE = re.compile(r"\b([1-9]\d{5})\b")
PHONE_RE = re.compile(r"([6-9]\d{9})\b")
HEADER_RE = re.compile(r"^TVS CMB Dealer.*?Details\s*", re.I)

# First digit of Indian PIN → expected state/UT name fragments.
PIN_ZONE_STATES: dict[str, tuple[str, ...]] = {
    "1": ("DELHI", "HARYANA", "PUNJAB", "HIMACHAL", "JAMMU", "CHANDIGARH", "LADAKH"),
    "2": ("UTTAR PRADESH", "UTTARAKHAND"),
    "3": ("RAJASTHAN", "GUJARAT", "DADRA", "DAMAN", "DIU"),
    "4": ("MAHARASHTRA", "GOA", "MADHYA PRADESH", "CHHATTISGARH"),
    "5": ("ANDHRA", "TELANGANA", "KARNATAKA"),
    "6": ("TAMIL", "KERALA", "PUDUCHERRY", "LAKSHADWEEP", "ANDAMAN"),
    "7": ("WEST BENGAL", "ODISHA", "SIKKIM", "ASSAM", "ARUNACHAL", "MANIPUR", "MEGHALAYA", "MIZORAM", "NAGALAND", "TRIPURA"),
    "8": ("BIHAR", "JHARKHAND"),
    "9": ("ASSAM", "ARUNACHAL", "MANIPUR", "MEGHALAYA", "MIZORAM", "NAGALAND", "TRIPURA"),
}

MAP_MATCH_MAX_KM = 50.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def pincode_matches_state(pincode: str, state_name: str) -> bool:
    if not re.fullmatch(r"[1-9]\d{5}", pincode or ""):
        return False
    state = (state_name or "").upper()
    if not state:
        return True
    zone = PIN_ZONE_STATES.get(pincode[0], ())
    return any(fragment in state for fragment in zone)


def pdf_map_points(path: Path) -> list[tuple[float, float, str]]:
    reader = PdfReader(str(path))
    points: list[tuple[float, float, str]] = []
    for page in reader.pages:
        for annot in page.get("/Annots") or []:
            obj = annot.get_object()
            action = obj.get("/A")
            if not action or not action.get("/URI"):
                continue
            uri = str(action["/URI"])
            match = MAP_RE.search(uri)
            if match:
                points.append((float(match.group(1)), float(match.group(2)), uri))
    return points


def _clean_address(text: str) -> str:
    cleaned = HEADER_RE.sub("", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ;,-")
    cleaned = re.sub(r"^[6-9]\d{9}\s+", "", cleaned)
    return cleaned.strip(" ;,-")


def pdf_dealers(path: Path) -> list[dict]:
    text = subprocess.check_output(
        ["pdftotext", "-layout", str(path), "-"],
        text=True,
        errors="replace",
    )
    lines = [line.rstrip() for line in text.splitlines()]
    dealers: list[dict] = []
    buffer: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or "Dealer Code" in stripped or "Map Link" in stripped:
            continue
        match = re.match(r"^(\d{4,6})(?:\s+(.*))?$", stripped)
        if match:
            code = match.group(1)
            rest = (match.group(2) or "").replace("Open Map", "").strip()
            if rest and len(rest) > 24:
                parts = [rest]
            else:
                parts = list(buffer)
                if rest:
                    parts.append(rest)
            buffer = []
            address = _clean_address(" ".join(parts))
            pins = PIN_RE.findall(address)
            phone_match = PHONE_RE.search(address)
            name = address.split(",")[0].strip() if address else ""
            dealers.append(
                {
                    "dealer_code": code,
                    "address": address,
                    "pincode": pins[-1] if pins else "",
                    "pdf_phone": phone_match.group(1) if phone_match else "",
                    "pdf_name": name,
                }
            )
            continue
        if "Open Map" in stripped:
            cleaned = stripped.replace("Open Map", "").strip()
            if cleaned:
                buffer.append(cleaned)
            continue
        buffer.append(stripped)
    return dealers


def load_csv(path: Path) -> dict[str, dict]:
    by_code: dict[str, dict] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = (row.get("dealer_code") or "").strip()
            if code:
                by_code[code] = row
    return by_code


class NominatimGeocoder:
    def __init__(
        self,
        *,
        cache_path: Path,
        user_agent: str = "tvsm-rag-bot/1.0 (dealer-build)",
        timeout: float = 20,
        min_interval_sec: float = 1.1,
    ):
        self._cache_path = cache_path
        self._user_agent = user_agent
        self._timeout = timeout
        self._min_interval_sec = min_interval_sec
        self._cache = self._load_cache()
        self._last_request_at = 0.0

    def geocode_pincode(self, pincode: str) -> tuple[float, float] | None:
        return self._lookup(
            f"pin:{pincode}",
            {"postalcode": pincode, "country": "India", "format": "json", "limit": "1"},
        )

    def geocode_place(self, query: str) -> tuple[float, float] | None:
        cleaned = " ".join((query or "").split())
        if not cleaned:
            return None
        return self._lookup(
            f"place:{cleaned.lower()}",
            {
                "q": cleaned,
                "countrycodes": "in",
                "format": "json",
                "limit": "1",
            },
        )

    def _lookup(self, key: str, params: dict) -> tuple[float, float] | None:
        cached = self._cache.get(key)
        if isinstance(cached, dict) and "lat" in cached and "lon" in cached:
            return float(cached["lat"]), float(cached["lon"])
        if key in self._cache and cached is None:
            return None

        self._throttle()
        request = Request(
            f"https://nominatim.openstreetmap.org/search?{urlencode(params)}",
            headers={"User-Agent": self._user_agent},
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
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

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._min_interval_sec:
            time.sleep(self._min_interval_sec - elapsed)
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


def resolve_coords(
    dealer: dict,
    *,
    geocoder: NominatimGeocoder,
) -> tuple[float, float] | None:
    pin = (dealer.get("pincode") or "").strip()
    state = (dealer.get("state_name") or "").strip()
    town = (dealer.get("town_name") or "").strip()
    if pin and pincode_matches_state(pin, state):
        coords = geocoder.geocode_pincode(pin)
        if coords:
            return coords
    if town and state:
        coords = geocoder.geocode_place(f"{town}, {state}, India")
        if coords:
            return coords
    if town:
        return geocoder.geocode_place(f"{town}, India")
    if pin:
        return geocoder.geocode_pincode(pin)
    return None


def attach_nearby_map(
    dealers: list[dict],
    map_points: list[tuple[float, float, str]],
) -> None:
    unused = list(map_points)
    for dealer in dealers:
        lat = dealer.get("latitude")
        lon = dealer.get("longitude")
        if lat is None or lon is None or not unused:
            continue
        best_i = None
        best_dist = MAP_MATCH_MAX_KM
        for index, (mlat, mlon, _url) in enumerate(unused):
            dist = haversine_km(float(lat), float(lon), mlat, mlon)
            if dist < best_dist:
                best_dist = dist
                best_i = index
        if best_i is None:
            dealer["map_url"] = (
                f"https://www.google.com/maps?q={lat},{lon}"
            )
            continue
        mlat, mlon, url = unused.pop(best_i)
        dealer["latitude"] = mlat
        dealer["longitude"] = mlon
        dealer["map_url"] = url


def build_dealers(
    *,
    csv_path: Path,
    pdf_path: Path,
    geocoder: NominatimGeocoder | None = None,
) -> list[dict]:
    map_points = pdf_map_points(pdf_path)
    blocks = {item["dealer_code"]: item for item in pdf_dealers(pdf_path)}
    csv_rows = load_csv(csv_path)
    codes = list(dict.fromkeys([*csv_rows.keys(), *blocks.keys()]))
    dealers: list[dict] = []
    for code in codes:
        row = csv_rows.get(code) or {}
        block = blocks.get(code) or {}
        state = (row.get("state_name") or "").strip()
        raw_pin = (block.get("pincode") or "").strip()
        pincode = raw_pin if pincode_matches_state(raw_pin, state) else ""
        if not pincode and raw_pin and not state:
            pincode = raw_pin
        phone = (
            (row.get("spoc_contact_no") or "").strip()
            or (block.get("pdf_phone") or "")
            or (row.get("dealer_contact_number") or "").strip()
        )
        name = (row.get("dealer_name") or "").strip() or (block.get("pdf_name") or "")
        dealers.append(
            {
                "dealer_code": code,
                "dealer_id": (row.get("dealer_id") or "").strip(),
                "name": name,
                "address": block.get("address") or "",
                "pincode": pincode,
                "phone": phone,
                "spoc_name": (row.get("spoc_name") or "").strip(),
                "state_name": state,
                "town_name": (row.get("town_name") or "").strip(),
                "latitude": None,
                "longitude": None,
                "map_url": "",
                "language_name": (row.get("language_name") or "").strip(),
            }
        )

    if geocoder is not None:
        for dealer in dealers:
            coords = resolve_coords(dealer, geocoder=geocoder)
            if coords:
                dealer["latitude"], dealer["longitude"] = coords
                dealer["map_url"] = (
                    f"https://www.google.com/maps?q={coords[0]},{coords[1]}"
                )
        attach_nearby_map(dealers, map_points)
    return dealers


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=Path("data/tbl_dealers_details.csv"))
    parser.add_argument(
        "--pdf", type=Path, default=Path("data/TVS_CMB_Dealer_Details.pdf")
    )
    parser.add_argument("--out", type=Path, default=Path("data/dealers.json"))
    parser.add_argument(
        "--geocode-cache",
        type=Path,
        default=Path("data/dealer_geocode_cache.json"),
    )
    parser.add_argument(
        "--skip-geocode",
        action="store_true",
        help="Build without Nominatim (coords stay empty)",
    )
    args = parser.parse_args()
    geocoder = None
    if not args.skip_geocode:
        geocoder = NominatimGeocoder(cache_path=args.geocode_cache)
    dealers = build_dealers(
        csv_path=args.csv,
        pdf_path=args.pdf,
        geocoder=geocoder,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(dealers, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with_coords = sum(1 for item in dealers if item["latitude"] is not None)
    with_pin = sum(1 for item in dealers if item["pincode"])
    print(
        f"Wrote {args.out} dealers={len(dealers)} "
        f"with_coords={with_coords} with_pincode={with_pin}"
    )


if __name__ == "__main__":
    main()

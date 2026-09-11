#!/usr/bin/env python3
"""Build data/pgms.json from the client's network workbook.

Only the ``Overall PGMs BNLR`` sheet is read — the dealer service centre,
DASC, IASC and APS sheets are a different kind of outlet and are not what a
customer asking for "the nearest PGM" wants. The sheet is hand-maintained,
so coordinates arrive as numbers, as numbers-in-strings with stray commas
and non-breaking spaces, as ``x``, or with the decimal point missing; rows
whose coordinates cannot be read, or fall outside India, are dropped and
listed on stderr so the client can fix them at source.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dealers import haversine_km  # noqa: E402

SHEET_NAME = "Overall PGMs BNLR"

# Header cell text (lower-cased, whitespace collapsed) -> field name.
COLUMNS = {
    "dms customer id": "dms_id",
    "name": "owner_name",
    "mobile no": "phone",
    "garage name": "name",
    "address": "address",
    "lat": "latitude",
    "long": "longitude",
    "current location": "area",
    "zone": "zone",
    "division": "division",
    "location": "map_url",
}

# Coordinates outside India can only be a data-entry slip.
INDIA_LAT = (6.0, 38.0)
INDIA_LON = (68.0, 98.0)

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _clean(value) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\xa0", " ").split())


def parse_coordinate(value, bounds: tuple[float, float]) -> float | None:
    """A float within ``bounds`` from whatever the cell holds, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        match = _NUMBER_RE.search(_clean(value))
        if not match:
            return None
        number = float(match.group(0))
    low, high = bounds
    return number if low <= number <= high else None


def map_url_for(row: dict, latitude: float, longitude: float) -> str:
    """The sheet's own Google Maps link when present, else one from coords."""
    link = _clean(row.get("map_url"))
    if link.startswith("http"):
        return link
    return f"https://maps.google.com/?q={latitude},{longitude}"


def read_sheet(path: Path, sheet_name: str = SHEET_NAME) -> list[dict]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = workbook[sheet_name]
    rows = sheet.iter_rows(values_only=True)
    header = [_clean(cell).lower() for cell in next(rows)]
    fields = [COLUMNS.get(name) for name in header]
    missing = set(COLUMNS.values()) - set(fields)
    if missing:
        raise SystemExit(f"{sheet_name!r} is missing columns for {sorted(missing)}")
    records = []
    for cells in rows:
        row = {field: cell for field, cell in zip(fields, cells) if field}
        if not any(_clean(v) for v in row.values()):
            continue
        records.append(row)
    return records


def build_pgms(rows: list[dict]) -> tuple[list[dict], list[str]]:
    pgms: list[dict] = []
    dropped: list[str] = []
    for row in rows:
        dms_id = _clean(row.get("dms_id"))
        name = _clean(row.get("name")) or _clean(row.get("owner_name"))
        label = f"{dms_id or '?'} {name or '(no name)'}"
        latitude = parse_coordinate(row.get("latitude"), INDIA_LAT)
        longitude = parse_coordinate(row.get("longitude"), INDIA_LON)
        if latitude is None or longitude is None:
            dropped.append(
                f"{label}: unreadable coordinates "
                f"lat={row.get('latitude')!r} long={row.get('longitude')!r}"
            )
            continue
        if not name:
            dropped.append(f"{label}: no garage or owner name")
            continue
        phone = re.sub(r"\D", "", _clean(row.get("phone")))
        owner = _clean(row.get("owner_name"))
        pgms.append(
            {
                "dms_id": dms_id,
                "name": name,
                "owner_name": "" if owner.lower() == name.lower() else owner,
                "phone": phone,
                "address": _clean(row.get("address")),
                "area": _clean(row.get("area")),
                "zone": _clean(row.get("zone")),
                "division": _clean(row.get("division")),
                "latitude": latitude,
                "longitude": longitude,
                "map_url": map_url_for(row, latitude, longitude),
            }
        )
    return pgms, dropped


def far_from_the_rest(pgms: list[dict], *, km: float) -> list[str]:
    """Rows more than ``km`` from the median garage. A Bengaluru network with
    one garage in Pune is a swapped or mistyped coordinate, not a garage in
    Pune — but that is the client's call, so these are reported, not dropped."""
    if not pgms:
        return []
    lats = sorted(item["latitude"] for item in pgms)
    lons = sorted(item["longitude"] for item in pgms)
    centre = (lats[len(lats) // 2], lons[len(lons) // 2])
    flagged = []
    for item in pgms:
        distance = haversine_km(*centre, item["latitude"], item["longitude"])
        if distance > km:
            flagged.append(
                f"{item['dms_id']} {item['name']} ({item['area']}): "
                f"{distance:.0f} km from the rest at "
                f"{item['latitude']},{item['longitude']}"
            )
    return flagged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--xlsx", type=Path, default=Path("data/pgm_network_bnlr.xlsx")
    )
    parser.add_argument("--sheet", default=SHEET_NAME)
    parser.add_argument("--out", type=Path, default=Path("data/pgms.json"))
    parser.add_argument(
        "--far-km",
        type=float,
        default=100.0,
        help="Report (keep) garages farther than this from the median one",
    )
    args = parser.parse_args()

    pgms, dropped = build_pgms(read_sheet(args.xlsx, args.sheet))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(pgms, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for line in dropped:
        print(f"dropped {line}", file=sys.stderr)
    suspicious = far_from_the_rest(pgms, km=args.far_km)
    for line in suspicious:
        print(f"check {line}", file=sys.stderr)
    print(
        f"Wrote {args.out} pgms={len(pgms)} dropped={len(dropped)} "
        f"check={len(suspicious)}"
    )


if __name__ == "__main__":
    main()

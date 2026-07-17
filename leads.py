"""Append qualified lead profiles to a server-side CSV."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from admin_config import AdminConfigStore, csv_columns


def _serialize(value: Any) -> str:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    return str(value)


class LeadWriter:
    """Write lead rows using columns from the current admin config."""

    def __init__(self, path: Path, config_store: AdminConfigStore):
        self._path = path
        self._config_store = config_store

    @property
    def path(self) -> Path:
        return self._path

    def append(
        self,
        *,
        channel: str,
        source: str,
        session: str,
        language: str,
        profile: dict[str, Any],
    ) -> None:
        config = self._config_store.get()
        columns = csv_columns(config)
        row = {col: "" for col in columns}
        row["timestamp"] = datetime.now().isoformat(timespec="seconds")
        row["channel"] = channel
        row["source"] = source
        row["session"] = session
        row["language"] = language
        for key, value in profile.items():
            if key in row:
                row[key] = _serialize(value)

        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            self._ensure_header(columns)
            with self._path.open("a", newline="", encoding="utf-8-sig") as f:
                csv.DictWriter(f, fieldnames=columns, extrasaction="ignore").writerow(row)
        else:
            with self._path.open("w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=columns)
                w.writeheader()
                w.writerow(row)

    def _ensure_header(self, columns: list[str]) -> None:
        with self._path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            try:
                existing = next(reader)
            except StopIteration:
                existing = []
        if existing == columns:
            return
        rows: list[dict[str, str]] = []
        if existing:
            with self._path.open(newline="", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
        with self._path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            w.writeheader()
            for old in rows:
                w.writerow({col: old.get(col, "") for col in columns})

"""Append qualified lead profiles to a server-side CSV."""
from __future__ import annotations

import csv
import fcntl
import json
import threading
from contextlib import contextmanager
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
        self._lock = threading.RLock()

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
        values = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "channel": channel,
            "source": source,
            "session": session,
            "language": language,
            **profile,
        }
        self._upsert(session, values)

    def upsert_client_identity(
        self,
        *,
        session: str,
        mobile: str,
        customer_id: str,
        customer_name: str,
        language: str,
        message_id: str = "",
        client_timestamp: str = "",
        received_at: str = "",
    ) -> None:
        self._upsert(
            session,
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "channel": "client_app",
                "source": "client_app",
                "session": session,
                "language": language,
                "mobile": mobile,
                "crm_customer_id": customer_id,
                "customer_name": customer_name,
                "last_message_id": message_id,
                "client_timestamp": client_timestamp,
                "received_at": received_at,
            },
        )

    def add_documents(
        self,
        *,
        session: str,
        document_types: list[str],
        url: str,
        status: str,
    ) -> None:
        with self._lock:
            with self._exclusive_file_lock():
                columns, rows = self._read_rows()
                row = next(
                    (item for item in rows if item.get("session") == session),
                    None,
                )
                if row is None:
                    row = {column: "" for column in columns}
                    row["session"] = session
                    rows.append(row)
                try:
                    documents = json.loads(row.get("documents") or "[]")
                except (TypeError, json.JSONDecodeError):
                    documents = []
                if not any(item.get("url") == url for item in documents):
                    documents.append(
                        {
                            "types": list(document_types),
                            "url": url,
                            "status": status,
                        }
                    )
                row["documents"] = _serialize(documents)
                self._write_rows(columns, rows)

    def _upsert(self, session: str, values: dict[str, Any]) -> None:
        with self._lock:
            with self._exclusive_file_lock():
                columns, rows = self._read_rows()
                row = next(
                    (item for item in rows if item.get("session") == session),
                    None,
                )
                if row is None:
                    row = {column: "" for column in columns}
                    rows.append(row)
                for key, value in values.items():
                    if key in row:
                        row[key] = _serialize(value)
                self._write_rows(columns, rows)

    @contextmanager
    def _exclusive_file_lock(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        with lock_path.open("a", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _read_rows(self) -> tuple[list[str], list[dict[str, str]]]:
        columns = csv_columns(self._config_store.get())
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            return columns, []
        self._ensure_header(columns)
        with self._path.open(newline="", encoding="utf-8-sig") as file:
            return columns, list(csv.DictReader(file))

    def _write_rows(self, columns: list[str], rows: list[dict[str, str]]) -> None:
        with self._path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

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


def leads_summary(path: Path, config_store: AdminConfigStore) -> dict[str, Any]:
    """Row count and column list for admin UI."""
    config = config_store.get()
    columns = csv_columns(config)
    if not path.exists():
        return {"count": 0, "columns": columns, "path": str(path)}
    with path.open(newline="", encoding="utf-8-sig") as f:
        count = sum(1 for _ in csv.DictReader(f))
    return {"count": count, "columns": columns, "path": str(path)}

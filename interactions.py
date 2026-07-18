"""SQLite persistence for web and WhatsApp conversation turns."""
from __future__ import annotations

import csv
import io
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


CSV_COLUMNS = [
    "id",
    "timestamp",
    "session",
    "channel",
    "source",
    "language",
    "role",
    "message",
    "latency_ms",
    "status",
    "error",
    "model",
    "citations",
    "needs_review",
    "reviewed_at",
    "review_note",
]

_stores: dict[tuple[str, int], "InteractionStore"] = {}
_stores_lock = threading.Lock()


def get_store(*, load_test: bool = False) -> "InteractionStore":
    """Return the configured production or load-test store."""
    import config

    path = (
        config.LOAD_TEST_INTERACTIONS_DB_PATH
        if load_test
        else config.INTERACTIONS_DB_PATH
    )
    key = (str(path), config.INTERACTION_RETENTION_DAYS)
    with _stores_lock:
        if key not in _stores:
            _stores[key] = InteractionStore(
                path, retention_days=config.INTERACTION_RETENTION_DAYS
            )
        return _stores[key]


def store_for_load_test_token(token: str) -> "InteractionStore":
    """Route authenticated load traffic separately; reject a bad supplied token."""
    import config

    if not token:
        return get_store()
    if not config.LOAD_TEST_TOKEN or not secrets.compare_digest(
        token, config.LOAD_TEST_TOKEN
    ):
        raise PermissionError("Invalid load-test token")
    return get_store(load_test=True)


def reset_stores_for_tests() -> None:
    with _stores_lock:
        _stores.clear()


class InteractionStore:
    """Persist, query, review, export, and expire interaction records."""

    def __init__(self, path: Path | str, *, retention_days: int = 90):
        self.path = Path(path)
        self.retention_days = retention_days
        self._init_lock = threading.Lock()
        self._initialized = False
        self._ensure_initialized()

    def record_turn(
        self,
        *,
        session: str,
        channel: str,
        source: str,
        language: str,
        role: str,
        message: str,
        latency_ms: int | None = None,
        status: str = "ok",
        error: str = "",
        model: str = "",
        citations: list[str] | None = None,
        needs_review: bool = False,
    ) -> int:
        if role not in {"user", "assistant"}:
            raise ValueError("role must be 'user' or 'assistant'")
        with self._connect() as connection:
            cursor = self._insert(
                connection,
                session=session,
                channel=channel,
                source=source,
                language=language,
                role=role,
                message=message,
                latency_ms=latency_ms,
                status=status,
                error=error,
                model=model,
                citations=citations,
                needs_review=needs_review,
            )
            return int(cursor.lastrowid)

    def record_exchange(
        self,
        *,
        session: str,
        channel: str,
        source: str,
        language: str,
        user_message: str | None,
        assistant_message: str,
        latency_ms: int | None = None,
        status: str = "ok",
        error: str = "",
        model: str = "",
        citations: list[str] | None = None,
        needs_review: bool = False,
    ) -> tuple[int | None, int]:
        """Atomically save a user turn, when present, and its assistant response."""
        with self._connect() as connection:
            user_id = None
            if user_message:
                cursor = self._insert(
                    connection,
                    session=session,
                    channel=channel,
                    source=source,
                    language=language,
                    role="user",
                    message=user_message,
                )
                user_id = int(cursor.lastrowid)
            cursor = self._insert(
                connection,
                session=session,
                channel=channel,
                source=source,
                language=language,
                role="assistant",
                message=assistant_message,
                latency_ms=latency_ms,
                status=status,
                error=error,
                model=model,
                citations=citations,
                needs_review=needs_review,
            )
            return user_id, int(cursor.lastrowid)

    def list_interactions(
        self,
        *,
        channel: str | None = None,
        language: str | None = None,
        status: str | None = None,
        session: str | None = None,
        needs_review: bool | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        where, values = self._filters(
            channel=channel,
            language=language,
            status=status,
            session=session,
            needs_review=needs_review,
            search=search,
        )
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        with self._connect() as connection:
            count = connection.execute(
                f"SELECT COUNT(*) FROM interactions {where}", values
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT * FROM (
                    SELECT * FROM interactions {where}
                    ORDER BY id DESC LIMIT ? OFFSET ?
                ) ORDER BY id ASC
                """,
                [*values, limit, offset],
            ).fetchall()
        return {"count": count, "items": [self._row_to_dict(row) for row in rows]}

    def mark_reviewed(self, interaction_id: int, *, note: str = "") -> bool:
        reviewed_at = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE interactions
                SET reviewed_at = ?, review_note = ?
                WHERE id = ? AND needs_review = 1 AND reviewed_at IS NULL
                """,
                (reviewed_at, note.strip(), interaction_id),
            )
            return cursor.rowcount == 1

    def export_csv(self, **filters: Any) -> str:
        where, values = self._filters(**filters)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM interactions {where} ORDER BY id ASC", values
            ).fetchall()
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            item = self._row_to_dict(row)
            item["citations"] = json.dumps(item["citations"], ensure_ascii=False)
            writer.writerow({column: item[column] for column in CSV_COLUMNS})
        return output.getvalue()

    def cleanup_expired(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM interactions WHERE timestamp < ?", (cutoff.isoformat(),)
            )
            return cursor.rowcount

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect(initialize=False) as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS interactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        session TEXT NOT NULL,
                        channel TEXT NOT NULL,
                        source TEXT NOT NULL,
                        language TEXT NOT NULL,
                        role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                        message TEXT NOT NULL,
                        latency_ms INTEGER,
                        status TEXT NOT NULL DEFAULT 'ok',
                        error TEXT NOT NULL DEFAULT '',
                        model TEXT NOT NULL DEFAULT '',
                        citations TEXT NOT NULL DEFAULT '[]',
                        needs_review INTEGER NOT NULL DEFAULT 0,
                        reviewed_at TEXT,
                        review_note TEXT NOT NULL DEFAULT ''
                    );
                    CREATE INDEX IF NOT EXISTS idx_interactions_session
                        ON interactions(session, id);
                    CREATE INDEX IF NOT EXISTS idx_interactions_filters
                        ON interactions(channel, language, status);
                    CREATE INDEX IF NOT EXISTS idx_interactions_review
                        ON interactions(needs_review, reviewed_at);
                    CREATE INDEX IF NOT EXISTS idx_interactions_timestamp
                        ON interactions(timestamp);
                    """
                )
            self._initialized = True
            self.cleanup_expired()

    def _connect(self, *, initialize: bool = True) -> sqlite3.Connection:
        if initialize:
            self._ensure_initialized()
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _insert(self, connection: sqlite3.Connection, **values: Any):
        return connection.execute(
            """
            INSERT INTO interactions (
                timestamp, session, channel, source, language, role, message,
                latency_ms, status, error, model, citations, needs_review
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self._now(),
                values["session"],
                values["channel"],
                values["source"],
                values["language"],
                values["role"],
                values["message"],
                values.get("latency_ms"),
                values.get("status", "ok"),
                values.get("error", ""),
                values.get("model", ""),
                json.dumps(values.get("citations") or [], ensure_ascii=False),
                int(values.get("needs_review", False)),
            ),
        )

    @staticmethod
    def _filters(
        *,
        channel: str | None = None,
        language: str | None = None,
        status: str | None = None,
        session: str | None = None,
        needs_review: bool | None = None,
        search: str | None = None,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        for column, value in (
            ("channel", channel),
            ("language", language),
            ("status", status),
            ("session", session),
        ):
            if value:
                clauses.append(f"{column} = ?")
                values.append(value)
        if needs_review is True:
            clauses.append("needs_review = 1 AND reviewed_at IS NULL")
        elif needs_review is False:
            clauses.append("(needs_review = 0 OR reviewed_at IS NOT NULL)")
        if search:
            clauses.append("(message LIKE ? OR error LIKE ? OR session LIKE ?)")
            pattern = f"%{search}%"
            values.extend([pattern, pattern, pattern])
        return (f"WHERE {' AND '.join(clauses)}" if clauses else ""), values

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        try:
            item["citations"] = json.loads(item["citations"])
        except (TypeError, json.JSONDecodeError):
            item["citations"] = []
        item["needs_review"] = bool(item["needs_review"])
        return item

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

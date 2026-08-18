"""Admin panel (web.py) endpoint contract tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from admin_config import AdminConfigStore
from admin_status import DEGRADED, DOWN, OK, StatusReporter, WorkerInfo
from web import create_admin_app

TOKEN = "s3cret-admin"


class FakeKeyManager:
    """Stand-in for the rag module's key API — no real Gemini calls."""

    def __init__(self, *, source=None, configured=False):
        self._source = source
        self._configured = configured
        self.reject = False
        self.saved_key = None
        self.cleared = False

    def runtime_key_active(self):
        return self._source == "runtime"

    def has_client(self):
        return self._configured

    def persist_api_key(self, api_key, validate=True):
        if self.reject:
            raise RuntimeError("invalid key")
        self.saved_key = api_key
        self._source = "runtime"
        self._configured = True

    def clear_persisted_key(self):
        self.cleared = True
        self._source = None
        self._configured = False


class FakeRedis:
    """Only the two operations the admin app performs."""

    def __init__(self, *, keys=None, fail=False):
        self.keys = set(keys or [])
        self.fail = fail

    def _guard(self):
        if self.fail:
            raise ConnectionError("connection refused")

    def ping(self):
        self._guard()
        return True

    def delete(self, key):
        self._guard()
        if key in self.keys:
            self.keys.discard(key)
            return 1
        return 0


def _reporter(**overrides):
    """A StatusReporter whose every collaborator is a stub — no Redis, no net."""
    redis = overrides.pop("redis", FakeRedis())
    settings = {
        "redis_factory": lambda: redis,
        "key_manager": FakeKeyManager(source="env", configured=True),
        "queue_name": "client",
        "warn_depth": 20,
        "workers_reader": lambda _redis: [
            WorkerInfo("worker-1", datetime.now(timezone.utc))
        ],
        "queue_reader": lambda _redis, _name: (0, 0),
        "probe": lambda _url: (OK, "Reachable (10 ms)"),
        "cache_seconds": 60,
    }
    settings.update(overrides)
    return StatusReporter(**settings)


def _check(body, name):
    return next(item for item in body["checks"] if item["name"] == name)


def _app(
    tmp_path,
    *,
    token=TOKEN,
    keys=None,
    redis=None,
    reporter=None,
    interaction_store=None,
    leads_path=None,
    media_library=None,
    knowledge_base=None,
):
    store = AdminConfigStore(tmp_path / "admin_config.json")
    store.ensure_seeded()
    return create_admin_app(
        admin_token=token,
        config_store=store,
        key_manager=keys or FakeKeyManager(),
        redis_factory=(lambda: redis) if redis is not None else (lambda: FakeRedis()),
        status_reporter=reporter or _reporter(),
        interaction_store=interaction_store,
        leads_path=leads_path,
        media_library=media_library,
        knowledge_base=knowledge_base,
    )


def _client(tmp_path, **kw):
    return TestClient(_app(tmp_path, **kw)), tmp_path


def _auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def test_page_served_without_auth(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "Control Panel" in resp.text


def test_docs_index_lists_every_page(tmp_path):
    """The slugs are not guessable, so the index is the only way in."""
    from web import DOC_PAGES

    client, _ = _client(tmp_path)
    resp = client.get("/admin/docs")
    assert resp.status_code == 200
    for slug in DOC_PAGES:
        assert f"/admin/docs/{slug}" in resp.text


def test_docs_pages_are_served_without_auth(tmp_path):
    """They carry no customer data, and the whole point is handing out a link."""
    from web import DOC_PAGES

    client, _ = _client(tmp_path)
    for slug in DOC_PAGES:
        resp = client.get(f"/admin/docs/{slug}")
        assert resp.status_code == 200, slug
        assert resp.headers["content-type"].startswith("text/html")
        assert "<title>" in resp.text


def test_an_unknown_doc_slug_is_404(tmp_path):
    client, _ = _client(tmp_path)
    assert client.get("/admin/docs/nope").status_code == 404


def test_a_doc_slug_cannot_escape_the_docs_directory(tmp_path):
    """A fixed slug map means a traversal attempt never reaches the filesystem."""
    client, _ = _client(tmp_path)
    for attempt in ("../.env", "..%2f.env", "../../etc/passwd"):
        assert client.get(f"/admin/docs/{attempt}").status_code == 404, attempt


def test_every_doc_page_is_actually_shipped(tmp_path):
    """A page listed in DOC_PAGES but missing from the repo would 404 in
    production while passing every other test here."""
    from web import DOC_PAGES, _DOCS_DIR

    for slug, (filename, _title) in DOC_PAGES.items():
        assert (_DOCS_DIR / filename).is_file(), f"{slug} -> docs/{filename}"


def test_config_requires_token(tmp_path):
    client, _ = _client(tmp_path)
    assert client.get("/admin/api/config").status_code == 401
    assert client.get(
        "/admin/api/config", headers={"Authorization": "Bearer wrong"}
    ).status_code == 401


def test_read_config_returns_seeded_defaults(tmp_path):
    client, _ = _client(tmp_path)
    cfg = client.get("/admin/api/config", headers=_auth()).json()
    assert cfg["bot_name"] == "TVS Passenger 3W Assistant"
    assert cfg["voice_policy"] == "intro_only"


def test_update_config_roundtrips_and_persists(tmp_path):
    client, path = _client(tmp_path)
    cfg = client.get("/admin/api/config", headers=_auth()).json()
    cfg["bot_name"] = "Renamed Bot"
    resp = client.put("/admin/api/config", json=cfg, headers=_auth())
    assert resp.status_code == 200
    assert resp.json()["bot_name"] == "Renamed Bot"
    # persisted to disk, so the worker process reloads it
    again = client.get("/admin/api/config", headers=_auth()).json()
    assert again["bot_name"] == "Renamed Bot"


def test_update_config_rejects_invalid(tmp_path):
    client, _ = _client(tmp_path)
    cfg = client.get("/admin/api/config", headers=_auth()).json()
    cfg["voice_policy"] = "shout"
    resp = client.put("/admin/api/config", json=cfg, headers=_auth())
    assert resp.status_code == 400
    assert "voice_policy" in resp.json()["detail"]


def test_disabled_when_token_empty(tmp_path):
    client, _ = _client(tmp_path, token="")
    assert client.get("/admin/api/config", headers=_auth()).status_code == 503


def test_meta_exposes_voice_policies_and_gemini(tmp_path):
    keys = FakeKeyManager(source="env", configured=True)
    client = TestClient(_app(tmp_path, keys=keys))
    meta = client.get("/admin/api/meta", headers=_auth()).json()
    assert "intro_only" in meta["voice_policies"]
    assert meta["gemini"]["source"] == "env"
    assert meta["gemini"]["configured"] is True


def test_set_gemini_key_validates_and_saves(tmp_path):
    keys = FakeKeyManager()
    client = TestClient(_app(tmp_path, keys=keys))
    resp = client.post(
        "/admin/api/gemini", json={"api_key": "AIza-good"}, headers=_auth()
    )
    assert resp.status_code == 200
    assert keys.saved_key == "AIza-good"
    assert resp.json()["source"] == "runtime"


def test_set_gemini_key_rejects_bad_key(tmp_path):
    keys = FakeKeyManager()
    keys.reject = True
    client = TestClient(_app(tmp_path, keys=keys))
    resp = client.post(
        "/admin/api/gemini", json={"api_key": "AIza-bad"}, headers=_auth()
    )
    assert resp.status_code == 400
    assert "rejected" in resp.json()["detail"].lower()


def test_set_gemini_key_requires_value(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.post("/admin/api/gemini", json={"api_key": "  "}, headers=_auth())
    assert resp.status_code == 400


def test_clear_gemini_key(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "GEMINI_API_KEY", "")  # no env fallback
    keys = FakeKeyManager(source="runtime", configured=True)
    client = TestClient(_app(tmp_path, keys=keys))
    resp = client.delete("/admin/api/gemini", headers=_auth())
    assert resp.status_code == 200
    assert keys.cleared is True
    assert resp.json()["source"] is None


# --- Slice A: operational status -------------------------------------------


def test_status_requires_token(tmp_path):
    client, _ = _client(tmp_path)
    assert client.get("/admin/api/status").status_code == 401


def test_status_disabled_when_token_empty(tmp_path):
    client, _ = _client(tmp_path, token="")
    assert client.get("/admin/api/status", headers=_auth()).status_code == 503


def test_status_all_green(tmp_path):
    client = TestClient(_app(tmp_path, reporter=_reporter()))
    body = client.get("/admin/api/status", headers=_auth()).json()
    assert body["status"] == OK
    assert body["checked_at"].endswith("Z")
    assert [item["name"] for item in body["checks"]] == [
        "Redis",
        "Worker",
        "Queue",
        "Gemini key",
        "JAM CRM",
        "JAM dispose",
    ]


def test_status_down_when_redis_unreachable(tmp_path):
    reporter = _reporter(redis=FakeRedis(fail=True))
    client = TestClient(_app(tmp_path, reporter=reporter))
    body = client.get("/admin/api/status", headers=_auth()).json()
    assert body["status"] == DOWN
    assert _check(body, "Redis")["status"] == DOWN
    assert "Unreachable" in _check(body, "Redis")["detail"]
    # Worker and queue are read out of Redis, so they must not read as healthy.
    assert _check(body, "Worker")["status"] == DOWN
    assert _check(body, "Queue")["status"] == DOWN


def test_status_down_when_no_worker_registered(tmp_path):
    reporter = _reporter(workers_reader=lambda _redis: [])
    client = TestClient(_app(tmp_path, reporter=reporter))
    body = client.get("/admin/api/status", headers=_auth()).json()
    assert body["status"] == DOWN
    assert _check(body, "Worker")["detail"] == "No worker registered"


def test_idle_worker_is_not_reported_dead(tmp_path):
    """A healthy idle worker goes minutes between heartbeats — measured at 369s
    against the live worker, with RQ's worker_ttl at 420s. Flagging that as
    down would make the page cry wolf every few minutes."""
    idle = datetime.now(timezone.utc) - timedelta(seconds=369)
    reporter = _reporter(workers_reader=lambda _redis: [WorkerInfo("w", idle)])
    client = TestClient(_app(tmp_path, reporter=reporter))
    body = client.get("/admin/api/status", headers=_auth()).json()
    assert body["status"] == OK
    assert _check(body, "Worker")["status"] == OK


def test_worker_silent_past_its_ttl_is_amber(tmp_path):
    stale = datetime.now(timezone.utc) - timedelta(seconds=600)
    reporter = _reporter(workers_reader=lambda _redis: [WorkerInfo("w", stale)])
    client = TestClient(_app(tmp_path, reporter=reporter))
    body = client.get("/admin/api/status", headers=_auth()).json()
    # Registry presence is the liveness signal, so this is a warning, not death.
    assert body["status"] == DEGRADED
    assert "silent for" in _check(body, "Worker")["detail"]


def test_deep_queue_is_amber_not_red(tmp_path):
    reporter = _reporter(queue_reader=lambda _redis, _name: (47, 3))
    client = TestClient(_app(tmp_path, reporter=reporter))
    body = client.get("/admin/api/status", headers=_auth()).json()
    assert body["status"] == DEGRADED
    assert _check(body, "Queue")["detail"] == "47 messages waiting, 3 failed"


def test_queue_at_threshold_stays_green(tmp_path):
    reporter = _reporter(queue_reader=lambda _redis, _name: (20, 0))
    client = TestClient(_app(tmp_path, reporter=reporter))
    body = client.get("/admin/api/status", headers=_auth()).json()
    assert _check(body, "Queue")["status"] == OK
    assert body["status"] == OK


def test_missing_gemini_key_is_amber(tmp_path):
    reporter = _reporter(key_manager=FakeKeyManager(configured=False))
    client = TestClient(_app(tmp_path, reporter=reporter))
    body = client.get("/admin/api/status", headers=_auth()).json()
    assert body["status"] == DEGRADED
    assert _check(body, "Gemini key")["status"] == DEGRADED


def test_unconfigured_dependency_is_not_a_fault(tmp_path):
    # Default reporter leaves crm_url and dispose_url empty, as in lab.
    client = TestClient(_app(tmp_path, reporter=_reporter()))
    body = client.get("/admin/api/status", headers=_auth()).json()
    assert _check(body, "JAM CRM") == {
        "name": "JAM CRM",
        "status": OK,
        "detail": "Not configured",
    }


def test_unreachable_dependency_is_amber(tmp_path):
    reporter = _reporter(
        crm_url="https://crm.example",
        probe=lambda _url: (DEGRADED, "Unreachable: ConnectionError"),
    )
    client = TestClient(_app(tmp_path, reporter=reporter))
    body = client.get("/admin/api/status", headers=_auth()).json()
    assert body["status"] == DEGRADED
    assert _check(body, "JAM CRM")["status"] == DEGRADED


def test_live_probe_is_cached_between_requests(tmp_path):
    """Polling this endpoint must not become traffic against the client's CRM."""
    calls = []

    def counting_probe(url):
        calls.append(url)
        return OK, "Reachable (10 ms)"

    reporter = _reporter(crm_url="https://crm.example", probe=counting_probe)
    client = TestClient(_app(tmp_path, reporter=reporter))

    first = client.get("/admin/api/status", headers=_auth()).json()
    second = client.get("/admin/api/status", headers=_auth()).json()

    assert len(calls) == 1
    assert "cached" not in _check(first, "JAM CRM")["detail"]
    assert "cached" in _check(second, "JAM CRM")["detail"]


def test_probe_cache_expires(tmp_path):
    calls = []
    # One probe per request (dispose_url is unset), so one clock read each.
    ticks = iter([0.0, 999.0])

    def counting_probe(url):
        calls.append(url)
        return OK, "Reachable (10 ms)"

    reporter = _reporter(
        crm_url="https://crm.example",
        probe=counting_probe,
        cache_seconds=60,
        clock=lambda: next(ticks),
    )
    client = TestClient(_app(tmp_path, reporter=reporter))
    client.get("/admin/api/status", headers=_auth())
    client.get("/admin/api/status", headers=_auth())
    assert len(calls) == 2


# --- Slice A: session reset -------------------------------------------------


def test_reset_session_clears_then_reports_absent(tmp_path):
    redis = FakeRedis(keys={"client:session:+919371062202"})
    client = TestClient(_app(tmp_path, redis=redis))

    first = client.post(
        "/admin/api/session/reset",
        json={"mobile": "+919371062202"},
        headers=_auth(),
    )
    assert first.status_code == 200
    assert first.json() == {"mobile": "+919371062202", "cleared": True}
    assert redis.keys == set()

    second = client.post(
        "/admin/api/session/reset",
        json={"mobile": "+919371062202"},
        headers=_auth(),
    )
    assert second.json()["cleared"] is False


def test_reset_session_uses_the_same_key_the_worker_writes(tmp_path):
    from client_adapters import RedisClientState

    redis = FakeRedis(keys={RedisClientState._key("+919371062202")})
    client = TestClient(_app(tmp_path, redis=redis))
    resp = client.post(
        "/admin/api/session/reset",
        json={"mobile": "+919371062202"},
        headers=_auth(),
    )
    assert resp.json()["cleared"] is True


def test_reset_session_requires_a_mobile(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.post("/admin/api/session/reset", json={"mobile": " "}, headers=_auth())
    assert resp.status_code == 400
    assert "mobile" in resp.json()["detail"]


def test_reset_session_requires_token(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.post("/admin/api/session/reset", json={"mobile": "+91937"})
    assert resp.status_code == 401


def test_reset_session_reports_redis_failure(tmp_path):
    client = TestClient(_app(tmp_path, redis=FakeRedis(fail=True)))
    resp = client.post(
        "/admin/api/session/reset", json={"mobile": "+91937"}, headers=_auth()
    )
    assert resp.status_code == 503


# --- Slice B: conversations -------------------------------------------------


def _store(tmp_path):
    from interactions import InteractionStore

    return InteractionStore(tmp_path / "interactions.db")


def _conversation(store, *, mobile, session, turns=1, needs_review=False):
    for i in range(turns):
        store.record_exchange(
            session=session,
            mobile=mobile,
            channel="client_app",
            source="client_app",
            language="Hindi",
            user_message=f"question {i}",
            assistant_message=f"answer {i}",
            needs_review=needs_review,
        )


def test_find_a_conversation_by_phone_number(tmp_path):
    """The support use case the whole schema change exists for."""
    store = _store(tmp_path)
    _conversation(store, mobile="+919371062202", session="client-aaa")
    _conversation(store, mobile="+919822041558", session="client-bbb")

    client = TestClient(_app(tmp_path, interaction_store=store))
    body = client.get(
        "/admin/api/interactions", params={"mobile": "+919371062202"}, headers=_auth()
    ).json()

    assert body["count"] == 2  # one user turn + one assistant turn
    assert {item["mobile"] for item in body["items"]} == {"+919371062202"}
    assert [item["role"] for item in body["items"]] == ["user", "assistant"]


def test_one_customer_several_sessions_group_under_their_number(tmp_path):
    """conversation_id rotates when the Redis session lapses; mobile is what
    holds a returning customer's history together."""
    store = _store(tmp_path)
    _conversation(store, mobile="+919371062202", session="client-day1")
    _conversation(store, mobile="+919371062202", session="client-day2")

    client = TestClient(_app(tmp_path, interaction_store=store))
    body = client.get(
        "/admin/api/interactions", params={"mobile": "+919371062202"}, headers=_auth()
    ).json()

    assert {item["session"] for item in body["items"]} == {
        "client-day1",
        "client-day2",
    }


def test_existing_database_gains_mobile_without_losing_rows(tmp_path):
    """Production has 3,692 rows written before `mobile` existed."""
    import sqlite3

    from interactions import InteractionStore

    path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(path)
    legacy.executescript(
        """
        CREATE TABLE interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL, session TEXT NOT NULL,
            channel TEXT NOT NULL, source TEXT NOT NULL, language TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('user','assistant')),
            message TEXT NOT NULL, latency_ms INTEGER,
            status TEXT NOT NULL DEFAULT 'ok', error TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '', citations TEXT NOT NULL DEFAULT '[]',
            needs_review INTEGER NOT NULL DEFAULT 0, reviewed_at TEXT,
            review_note TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO interactions (timestamp, session, channel, source, language,
                                  role, message)
        VALUES ('2026-08-01T10:00:00+00:00', 'client-old', 'client_app',
                'client_app', 'Hindi', 'user', 'old message');
        """
    )
    legacy.commit()
    legacy.close()

    store = InteractionStore(path)  # migrates on open
    result = store.list_interactions()

    assert result["count"] == 1
    assert result["items"][0]["message"] == "old message"
    assert result["items"][0]["mobile"] == ""  # no backfill possible


def test_read_one_full_conversation(tmp_path):
    store = _store(tmp_path)
    _conversation(store, mobile="+919371062202", session="client-aaa", turns=3)
    client = TestClient(_app(tmp_path, interaction_store=store))

    body = client.get("/admin/api/interactions/client-aaa", headers=_auth()).json()
    assert body["session"] == "client-aaa"
    assert body["count"] == 6
    ids = [item["id"] for item in body["items"]]
    assert ids == sorted(ids)  # oldest first, so it reads as a transcript


def test_unknown_conversation_is_404(tmp_path):
    client = TestClient(_app(tmp_path, interaction_store=_store(tmp_path)))
    resp = client.get("/admin/api/interactions/client-nope", headers=_auth())
    assert resp.status_code == 404


def test_export_csv_route_is_not_shadowed_by_the_session_route(tmp_path):
    """/interactions/export.csv must not be read as session id 'export.csv'."""
    store = _store(tmp_path)
    _conversation(store, mobile="+919371062202", session="client-aaa")
    client = TestClient(_app(tmp_path, interaction_store=store))

    resp = client.get("/admin/api/interactions/export.csv", headers=_auth())
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.text.splitlines()[0].startswith("id,timestamp,session,mobile,")
    assert "+919371062202" in resp.text


def test_export_honours_the_mobile_filter(tmp_path):
    store = _store(tmp_path)
    _conversation(store, mobile="+919371062202", session="client-aaa")
    _conversation(store, mobile="+919822041558", session="client-bbb")
    client = TestClient(_app(tmp_path, interaction_store=store))

    text = client.get(
        "/admin/api/interactions/export.csv",
        params={"mobile": "+919371062202"},
        headers=_auth(),
    ).text
    assert "+919371062202" in text
    assert "+919822041558" not in text


def test_pagination_and_limit_cap(tmp_path):
    store = _store(tmp_path)
    _conversation(store, mobile="+91937", session="client-aaa", turns=5)
    client = TestClient(_app(tmp_path, interaction_store=store))

    page = client.get(
        "/admin/api/interactions", params={"limit": 3, "offset": 0}, headers=_auth()
    ).json()
    assert page["count"] == 10 and len(page["items"]) == 3

    capped = client.get(
        "/admin/api/interactions", params={"limit": 9999}, headers=_auth()
    ).json()
    assert len(capped["items"]) == 10  # cap is 500, we only have 10


def test_mark_reviewed_then_reject_a_second_attempt(tmp_path):
    store = _store(tmp_path)
    _conversation(store, mobile="+91937", session="client-aaa", needs_review=True)
    client = TestClient(_app(tmp_path, interaction_store=store))

    flagged = client.get(
        "/admin/api/interactions", params={"needs_review": True}, headers=_auth()
    ).json()["items"]
    assert flagged, "expected a flagged turn"
    target = flagged[0]["id"]

    first = client.post(
        f"/admin/api/interactions/{target}/review",
        json={"note": "checked, dealer followed up"},
        headers=_auth(),
    )
    assert first.status_code == 200
    assert first.json()["reviewed"] is True

    second = client.post(
        f"/admin/api/interactions/{target}/review", json={}, headers=_auth()
    )
    assert second.status_code == 404


def test_interactions_require_a_token(tmp_path):
    client = TestClient(_app(tmp_path, interaction_store=_store(tmp_path)))
    assert client.get("/admin/api/interactions").status_code == 401
    assert client.get("/admin/api/leads").status_code == 401


# --- Slice B: leads ---------------------------------------------------------


def _lead_writer(tmp_path):
    from leads import LeadWriter

    store = AdminConfigStore(tmp_path / "admin_config.json")
    store.ensure_seeded()
    return LeadWriter(tmp_path / "leads.csv", store), tmp_path / "leads.csv"


def test_leads_are_listed_newest_first(tmp_path):
    writer, path = _lead_writer(tmp_path)
    for i in range(3):
        writer.append(
            channel="client_app",
            source="client_app",
            session=f"client-{i}",
            language="Hindi",
            profile={"lead_name": f"Customer {i}", "pincode": f"41100{i}"},
        )

    client = TestClient(_app(tmp_path, leads_path=path))
    body = client.get("/admin/api/leads", headers=_auth()).json()

    assert body["count"] == 3
    assert body["items"][0]["lead_name"] == "Customer 2"
    assert "pincode" in body["columns"]


def test_leads_search_matches_any_column(tmp_path):
    writer, path = _lead_writer(tmp_path)
    writer.append(
        channel="client_app", source="client_app", session="client-a",
        language="Hindi", profile={"lead_name": "Ramesh", "pincode": "411001"},
    )
    writer.append(
        channel="client_app", source="client_app", session="client-b",
        language="Tamil", profile={"lead_name": "Suresh", "pincode": "600001"},
    )

    client = TestClient(_app(tmp_path, leads_path=path))
    hits = client.get(
        "/admin/api/leads", params={"search": "411001"}, headers=_auth()
    ).json()
    assert hits["count"] == 1
    assert hits["items"][0]["lead_name"] == "Ramesh"


def test_leads_stay_intact_while_the_worker_writes(tmp_path):
    """_write_rows truncates and rewrites the whole file per lead. Without a
    shared lock the reader catches it mid-rewrite."""
    import threading

    writer, path = _lead_writer(tmp_path)
    writer.append(
        channel="client_app", source="client_app", session="seed",
        language="Hindi", profile={"lead_name": "Seed"},
    )
    client = TestClient(_app(tmp_path, leads_path=path))

    stop = threading.Event()

    def keep_writing():
        i = 0
        while not stop.is_set() and i < 40:
            writer.append(
                channel="client_app", source="client_app", session=f"c-{i}",
                language="Hindi", profile={"lead_name": f"Name {i}"},
            )
            i += 1

    scribe = threading.Thread(target=keep_writing)
    scribe.start()
    try:
        for _ in range(25):
            body = client.get("/admin/api/leads", headers=_auth()).json()
            assert body["count"] >= 1
            for row in body["items"]:
                # A torn read yields rows missing columns entirely.
                assert set(body["columns"]).issuperset(row.keys())
                assert row.get("session")
    finally:
        stop.set()
        scribe.join()


def test_leads_export_is_csv(tmp_path):
    writer, path = _lead_writer(tmp_path)
    writer.append(
        channel="client_app", source="client_app", session="client-a",
        language="Hindi", profile={"lead_name": "Ramesh"},
    )
    client = TestClient(_app(tmp_path, leads_path=path))
    resp = client.get("/admin/api/leads/export.csv", headers=_auth())

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "Ramesh" in resp.text


def test_leads_endpoint_handles_a_missing_file(tmp_path):
    client = TestClient(_app(tmp_path, leads_path=tmp_path / "nope.csv"))
    body = client.get("/admin/api/leads", headers=_auth()).json()
    assert body == {"count": 0, "columns": body["columns"], "items": []}


# --- OpenAPI contract -------------------------------------------------------


def test_spec_declares_bearer_auth_so_swagger_can_authorize(tmp_path):
    spec = _app(tmp_path).openapi()
    assert "HTTPBearer" in spec["components"]["securitySchemes"]
    assert spec["info"]["title"] == "TVS Bot Admin"
    assert {t["name"] for t in spec["tags"]} == {
        "operations",
        "conversations",
        "leads",
        "configuration",
        "credentials",
        "media",
        "knowledge base",
    }


def test_spec_marks_health_public_and_everything_else_protected(tmp_path):
    paths = _app(tmp_path).openapi()["paths"]
    for path, operations in paths.items():
        for method, operation in operations.items():
            secured = bool(operation.get("security"))
            if path == "/admin/health":
                assert not secured, "health must stay probe-friendly"
            else:
                assert secured, f"{method.upper()} {path} is missing auth in the spec"


def test_committed_openapi_json_matches_the_code(tmp_path):
    """docs/openapi.json is the published contract — re-export it when routes
    change: ./venv/bin/python scripts/export_openapi.py"""
    import json
    import pathlib

    committed = pathlib.Path(__file__).resolve().parent.parent / "docs" / "openapi.json"
    assert committed.exists(), "run scripts/export_openapi.py"

    from scripts.export_openapi import build_spec

    assert json.loads(committed.read_text(encoding="utf-8")) == build_spec(), (
        "docs/openapi.json is stale — re-run scripts/export_openapi.py"
    )


# --- media library endpoints ------------------------------------------------


def _media_app(tmp_path):
    from media_library import MediaLibrary

    library = MediaLibrary(tmp_path / "media", base_url="https://media.example.com/media")
    return TestClient(_app(tmp_path, media_library=library)), library


def test_upload_a_brochure_and_get_its_public_url(tmp_path):
    client, _ = _media_app(tmp_path)
    resp = client.post(
        "/admin/api/media/brochures",
        files={"file": ("King_EV_MAX_2027.pdf", b"%PDF-1.4\nbody\n", "application/pdf")},
        headers=_auth(),
    )
    assert resp.status_code == 200
    assert resp.json()["url"] == (
        "https://media.example.com/media/brochures/King_EV_MAX_2027.pdf"
    )


def test_uploading_does_not_change_what_the_bot_sends(tmp_path):
    """Publishing a draft must never start sending it — the admin still has to
    point documents.<product>.brochure at the new URL."""
    client, _ = _media_app(tmp_path)
    before = client.get("/admin/api/config", headers=_auth()).json()["documents"]
    client.post(
        "/admin/api/media/brochures",
        files={"file": ("draft.pdf", b"%PDF-1.4\nx\n", "application/pdf")},
        headers=_auth(),
    )
    after = client.get("/admin/api/config", headers=_auth()).json()["documents"]
    assert before == after


def test_upload_rejects_a_non_pdf(tmp_path):
    client, _ = _media_app(tmp_path)
    resp = client.post(
        "/admin/api/media/brochures",
        files={"file": ("evil.pdf", b"<html>nope</html>", "application/pdf")},
        headers=_auth(),
    )
    assert resp.status_code == 400
    assert "not a valid brochure" in resp.json()["detail"]


def test_upload_refuses_to_silently_replace(tmp_path):
    client, _ = _media_app(tmp_path)
    payload = {"file": ("king.pdf", b"%PDF-1.4\na\n", "application/pdf")}
    assert client.post(
        "/admin/api/media/brochures", files=payload, headers=_auth()
    ).status_code == 200

    clash = client.post(
        "/admin/api/media/brochures",
        files={"file": ("king.pdf", b"%PDF-1.4\nb\n", "application/pdf")},
        headers=_auth(),
    )
    assert clash.status_code == 400
    assert "already exists" in clash.json()["detail"]

    ok = client.post(
        "/admin/api/media/brochures",
        files={"file": ("king.pdf", b"%PDF-1.4\nb\n", "application/pdf")},
        data={"overwrite": "true"},
        headers=_auth(),
    )
    assert ok.status_code == 200


def test_list_and_delete_brochures(tmp_path):
    client, _ = _media_app(tmp_path)
    client.post(
        "/admin/api/media/brochures",
        files={"file": ("a.pdf", b"%PDF-1.4\na\n", "application/pdf")},
        headers=_auth(),
    )
    listing = client.get("/admin/api/media/brochures", headers=_auth()).json()
    assert [i["filename"] for i in listing["items"]] == ["a.pdf"]
    assert listing["max_upload_bytes"] > 0

    assert client.delete(
        "/admin/api/media/brochures/a.pdf", headers=_auth()
    ).status_code == 200
    assert client.delete(
        "/admin/api/media/brochures/a.pdf", headers=_auth()
    ).status_code == 404


def test_media_endpoints_require_a_token(tmp_path):
    client, _ = _media_app(tmp_path)
    assert client.get("/admin/api/media/brochures").status_code == 401
    assert client.post("/admin/api/media/brochures").status_code == 401


def test_upload_a_share_location_image(tmp_path):
    client, _ = _media_app(tmp_path)
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 32
    resp = client.post(
        "/admin/api/media/images",
        files={"file": ("how_to.jpg", jpeg, "image/jpeg")},
        headers=_auth(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "images"
    assert body["url"] == (
        "https://media.example.com/media/share_location/how_to.jpg"
    )


def test_image_and_brochure_listings_are_separate(tmp_path):
    client, _ = _media_app(tmp_path)
    client.post(
        "/admin/api/media/brochures",
        files={"file": ("king.pdf", b"%PDF-1.4\nx\n", "application/pdf")},
        headers=_auth(),
    )
    client.post(
        "/admin/api/media/images",
        files={"file": ("how_to.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 8, "image/jpeg")},
        headers=_auth(),
    )
    brochures = client.get("/admin/api/media/brochures", headers=_auth()).json()
    images = client.get("/admin/api/media/images", headers=_auth()).json()

    assert [i["filename"] for i in brochures["items"]] == ["king.pdf"]
    assert [i["filename"] for i in images["items"]] == ["how_to.jpg"]
    assert images["allowed_suffixes"] == [".jpeg", ".jpg", ".png"]
    assert images["max_upload_bytes"] < brochures["max_upload_bytes"]


def test_an_unknown_media_kind_is_404(tmp_path):
    client, _ = _media_app(tmp_path)
    resp = client.get("/admin/api/media/videos", headers=_auth())
    assert resp.status_code == 404
    assert "brochures" in resp.json()["detail"]


# --- knowledge base ---------------------------------------------------------


class FakeKb:
    def __init__(self, *, documents=None, error=None):
        self._documents = documents if documents is not None else []
        self._error = error
        self.deleted = []

    def summary(self):
        if self._error:
            raise self._error
        return {
            "store": "fileSearchStores/test",
            "document_count": len(self._documents),
            "duplicate_display_names": ["price_list.pdf"],
            "total_size_bytes": 4096,
            "documents": self._documents,
        }

    def delete(self, document_id):
        if self._error:
            raise self._error
        if document_id not in [d["document_id"] for d in self._documents]:
            return False
        self.deleted.append(document_id)
        return True


def test_kb_lists_documents_and_flags_duplicates(tmp_path):
    kb = FakeKb(documents=[{"document_id": "a1", "display_name": "price_list.pdf"}])
    client = TestClient(_app(tmp_path, knowledge_base=kb))
    body = client.get("/admin/api/kb", headers=_auth()).json()
    assert body["document_count"] == 1
    assert body["duplicate_display_names"] == ["price_list.pdf"]


def test_kb_delete_removes_a_stale_document(tmp_path):
    kb = FakeKb(documents=[{"document_id": "a1", "display_name": "old.pdf"}])
    client = TestClient(_app(tmp_path, knowledge_base=kb))
    resp = client.delete("/admin/api/kb/a1", headers=_auth())
    assert resp.status_code == 200
    assert resp.json() == {"document_id": "a1", "deleted": True}
    assert kb.deleted == ["a1"]


def test_kb_delete_of_an_unknown_document_is_404(tmp_path):
    client = TestClient(_app(tmp_path, knowledge_base=FakeKb()))
    assert client.delete("/admin/api/kb/nope", headers=_auth()).status_code == 404


def test_kb_reports_an_upstream_failure_as_502_not_500(tmp_path):
    from knowledge_base import KnowledgeBaseError

    kb = FakeKb(error=KnowledgeBaseError("No Gemini API key is configured"))
    client = TestClient(_app(tmp_path, knowledge_base=kb))
    resp = client.get("/admin/api/kb", headers=_auth())
    assert resp.status_code == 502
    assert "Gemini API key" in resp.json()["detail"]


def test_kb_requires_a_token(tmp_path):
    client = TestClient(_app(tmp_path, knowledge_base=FakeKb()))
    assert client.get("/admin/api/kb").status_code == 401
    assert client.delete("/admin/api/kb/a1").status_code == 401


def test_kb_upload_returns_before_indexing_finishes(tmp_path):
    class UploadKb(FakeKb):
        def add(self, filename, content, *, display_name="", replace=False):
            self.added = (filename, len(content), display_name, replace)
            return {
                "display_name": display_name or filename,
                "size_bytes": len(content),
                "state": "STATE_PENDING",
                "indexing": True,
                "replaced_document_ids": [],
            }

    kb = UploadKb()
    client = TestClient(_app(tmp_path, knowledge_base=kb))
    resp = client.post(
        "/admin/api/kb",
        files={"file": ("specs.pdf", b"%PDF-1.4\nx\n", "application/pdf")},
        data={"replace": "true"},
        headers=_auth(),
    )
    assert resp.status_code == 200
    assert resp.json()["indexing"] is True
    assert resp.json()["state"] == "STATE_PENDING"
    assert kb.added[0] == "specs.pdf" and kb.added[3] is True


def test_kb_upload_rejects_bad_input_as_400_not_502(tmp_path):
    from knowledge_base import KnowledgeBaseError

    class RejectingKb(FakeKb):
        def add(self, *a, **kw):
            raise KnowledgeBaseError("File is 40.0 MB; the limit is 30 MB.")

    client = TestClient(_app(tmp_path, knowledge_base=RejectingKb()))
    resp = client.post(
        "/admin/api/kb",
        files={"file": ("big.pdf", b"%PDF-x", "application/pdf")},
        headers=_auth(),
    )
    assert resp.status_code == 400


def test_kb_upload_requires_a_token(tmp_path):
    client = TestClient(_app(tmp_path, knowledge_base=FakeKb()))
    assert client.post("/admin/api/kb").status_code == 401

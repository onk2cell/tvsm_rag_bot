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


def _app(tmp_path, *, token=TOKEN, keys=None, redis=None, reporter=None):
    store = AdminConfigStore(tmp_path / "admin_config.json")
    store.ensure_seeded()
    return create_admin_app(
        admin_token=token,
        config_store=store,
        key_manager=keys or FakeKeyManager(),
        redis_factory=(lambda: redis) if redis is not None else (lambda: FakeRedis()),
        status_reporter=reporter or _reporter(),
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

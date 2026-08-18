"""Operational status for the admin panel: Redis, worker, queue, Gemini, JAM.

The admin app runs in its own container. It can reach Redis and the shared
``./data`` volume, but it cannot see the worker process at all — so worker
liveness is read from RQ's own registry in Redis, which the worker maintains
without any code of ours.

The two live dependency probes are cached. A status endpoint invites polling,
and an uncached probe would turn our own monitoring into standing traffic
against the client's production CRM.

Every collaborator is injectable so the endpoint can be tested without Redis,
RQ, or the network.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import requests

OK = "ok"
DEGRADED = "degraded"
DOWN = "down"

_SEVERITY = {OK: 0, DEGRADED: 1, DOWN: 2}

# Registry presence — not heartbeat age — is the liveness signal. RQ expires a
# dead worker's key on its own, so a worker that stops appearing in Worker.all()
# is genuinely gone, and it clears within ~90s.
#
# Heartbeat age is a much weaker signal and must not be read as death: an idle
# worker blocking on the queue legitimately goes minutes between heartbeats
# (measured against the live worker: 369s idle, with worker_ttl at RQ's default
# 420s). Only flag it past that ttl, and only as "degraded" — the registry
# already covers the case that matters.
WORKER_TTL_SEC = 420
WORKER_SILENT_AFTER_SEC = WORKER_TTL_SEC + 60

# Deliberately short: an operator is waiting on this request, unlike the
# customer-facing timeouts which are tuned for CRM slowness.
PROBE_TIMEOUT_SEC = 5.0


def worst(statuses: list[str]) -> str:
    """The most severe status in the list — the page's overall verdict."""
    return max(statuses, key=lambda status: _SEVERITY[status], default=OK)


def _aware(value: datetime) -> datetime:
    """RQ has returned both naive and aware heartbeats across versions."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass(frozen=True)
class WorkerInfo:
    name: str
    last_heartbeat: datetime | None


def read_workers(redis: Any) -> list[WorkerInfo]:
    """Workers registered against this Redis, per RQ's own registry."""
    from rq import Worker

    return [
        WorkerInfo(worker.name, worker.last_heartbeat)
        for worker in Worker.all(connection=redis)
    ]


def read_queue(redis: Any, queue_name: str) -> tuple[int, int]:
    """(messages waiting, jobs failed) for the worker's queue."""
    from rq import Queue

    queue = Queue(queue_name, connection=redis)
    return queue.count, queue.failed_job_registry.count


def http_probe(url: str) -> tuple[str, str]:
    """Is this dependency answering at all?

    A 4xx counts as reachable: we probe without credentials or query
    parameters, so anything that answers proves the far side is up. Only a
    connection failure or a 5xx means the dependency itself is broken —
    treating 4xx as a fault would leave the page permanently amber, which is
    how status pages get ignored.
    """
    started = time.perf_counter()
    try:
        response = requests.get(url, timeout=PROBE_TIMEOUT_SEC)
    except requests.RequestException as exc:
        return DEGRADED, f"Unreachable: {type(exc).__name__}"
    elapsed = round((time.perf_counter() - started) * 1000)
    if response.status_code >= 500:
        return DEGRADED, f"HTTP {response.status_code} ({elapsed} ms)"
    return OK, f"Reachable ({elapsed} ms)"


class _ProbeCache:
    """Reuse a probe result for a while, and say so when we do."""

    def __init__(self, ttl_seconds: float, clock: Callable[[], float]):
        self._ttl = max(0.0, float(ttl_seconds))
        self._clock = clock
        self._entries: dict[str, tuple[float, tuple[str, str]]] = {}

    def get_or_call(
        self, url: str, call: Callable[[str], tuple[str, str]]
    ) -> tuple[str, str]:
        now = self._clock()
        cached = self._entries.get(url)
        if cached and self._ttl and now - cached[0] < self._ttl:
            status, detail = cached[1]
            return status, f"{detail} (cached {int(now - cached[0])}s ago)"
        result = call(url)
        self._entries[url] = (now, result)
        return result


class StatusReporter:
    """Assemble the six checks behind ``GET /admin/api/status``."""

    def __init__(
        self,
        *,
        redis_factory: Callable[[], Any],
        key_manager: Any,
        queue_name: str,
        warn_depth: int,
        crm_url: str = "",
        dispose_url: str = "",
        probe: Callable[[str], tuple[str, str]] = http_probe,
        workers_reader: Callable[[Any], list[WorkerInfo]] = read_workers,
        queue_reader: Callable[[Any, str], tuple[int, int]] = read_queue,
        cache_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None,
    ):
        self._redis_factory = redis_factory
        self._key_manager = key_manager
        self._queue_name = queue_name
        self._warn_depth = warn_depth
        self._crm_url = crm_url
        self._dispose_url = dispose_url
        self._probe = probe
        self._workers_reader = workers_reader
        self._queue_reader = queue_reader
        self._cache = _ProbeCache(cache_seconds, clock)
        self._now = now or (lambda: datetime.now(timezone.utc))

    def snapshot(self) -> dict[str, Any]:
        redis, redis_check = self._redis_check()
        checks = [
            redis_check,
            *self._worker_and_queue_checks(redis),
            self._gemini_check(),
            self._probe_check("JAM CRM", self._crm_url),
            self._probe_check("JAM dispose", self._dispose_url),
        ]
        return {
            "status": worst([check.status for check in checks]),
            "checked_at": self._timestamp(),
            "checks": [check.as_dict() for check in checks],
        }

    def _timestamp(self) -> str:
        return (
            self._now()
            .astimezone(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )

    def _redis_check(self) -> tuple[Any, Check]:
        started = time.perf_counter()
        try:
            redis = self._redis_factory()
            redis.ping()
        except Exception as exc:
            return None, Check("Redis", DOWN, f"Unreachable: {exc}")
        elapsed = round((time.perf_counter() - started) * 1000)
        return redis, Check("Redis", OK, f"Connected ({elapsed} ms)")

    def _worker_and_queue_checks(self, redis: Any) -> list[Check]:
        if redis is None:
            # Both are read out of Redis, so with Redis gone we genuinely do
            # not know. Report the worst case: the overall verdict is already
            # down, and "unknown" must never read as healthy.
            unknown = "Unknown — Redis unreachable"
            return [Check("Worker", DOWN, unknown), Check("Queue", DOWN, unknown)]
        return [self._worker_check(redis), self._queue_check(redis)]

    def _worker_check(self, redis: Any) -> Check:
        try:
            workers = self._workers_reader(redis)
        except Exception as exc:
            return Check("Worker", DOWN, f"Cannot read worker registry: {exc}")
        if not workers:
            return Check("Worker", DOWN, "No worker registered")

        label = _plural(len(workers), "worker")
        heartbeats = [w.last_heartbeat for w in workers if w.last_heartbeat]
        if not heartbeats:
            return Check("Worker", OK, f"{label} registered")

        age = int((self._now() - _aware(max(heartbeats))).total_seconds())
        if age > WORKER_SILENT_AFTER_SEC:
            return Check("Worker", DEGRADED, f"{label}, silent for {age}s")
        return Check("Worker", OK, f"{label}, last seen {age}s ago")

    def _queue_check(self, redis: Any) -> Check:
        try:
            depth, failed = self._queue_reader(redis, self._queue_name)
        except Exception as exc:
            return Check("Queue", DEGRADED, f"Cannot read queue: {exc}")
        detail = f"{_plural(depth, 'message')} waiting"
        if failed:
            detail += f", {failed} failed"
        if depth > self._warn_depth or failed:
            return Check("Queue", DEGRADED, detail)
        return Check("Queue", OK, detail)

    def _gemini_check(self) -> Check:
        try:
            configured = self._key_manager.has_client()
        except Exception as exc:
            return Check("Gemini key", DEGRADED, f"Cannot check: {exc}")
        if not configured:
            return Check(
                "Gemini key", DEGRADED, "Not configured — the bot cannot answer"
            )
        if self._key_manager.runtime_key_active():
            return Check("Gemini key", OK, "Runtime key active")
        return Check("Gemini key", OK, "Environment key active")

    def _probe_check(self, name: str, url: str) -> Check:
        if not url:
            # An unconfigured dependency is not a fault. Reporting it as one
            # would leave lab and partial deployments permanently amber.
            return Check(name, OK, "Not configured")
        status, detail = self._cache.get_or_call(url, self._probe)
        return Check(name, status, detail)

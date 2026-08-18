# Admin Panel Tier 1 — Operational Visibility PRD

**Status:** Ready for implementation
**Scope:** API only — no UI. Endpoints land first; the panel is wired up in a later pass.
**Source:** Design session against the live codebase (`web.py`, `admin_config.py`, `interactions.py`, `leads.py`, `client_processing.py`, `client_adapters.py`)
**Depends on:** existing admin app (`web.py`), `ADMIN_TOKEN` auth, the shared `./data` volume

---

## Problem Statement

The admin panel can edit what the bot *says* but can see nothing about what it *does*.

There is no way to answer the three questions that actually generate escalations:

1. **"Is it working?"** — `/admin/health` returns a hardcoded `{"status":"ok"}` and has no callers. It cannot distinguish a healthy idle bot from a webhook silently dropping every message. The `admin` service in `compose.yaml` has no healthcheck at all.
2. **"What did the bot say to this customer?"** — `interactions.py` is a complete SQLite conversation log with query, review, export, and retention support, and **zero endpoints**. Reading a conversation today requires SSH plus `sqlite3`.
3. **"This customer is stuck — unstick them."** — a wedged session clears only when its 1-hour Redis TTL lapses. Nobody can intervene.

Compounding (2): the conversation log stores `session=session.conversation_id` — a random `client-<uuid>` minted fresh whenever the Redis session lapses. **The customer's phone number is never recorded**, so there is no path from a phone number to a conversation, and one customer over several days appears as several unrelated sessions.

---

## Solution

Expose the operational data that already exists, plus the one schema addition needed to make it usable, as authenticated JSON endpoints on the existing admin app.

Delivered as two independent slices:

- **Slice A — "is it working?"** — a real status endpoint and a session reset. No schema change, no new dependencies. Ships first.
- **Slice B — "what happened?"** — conversation and lead browsing, plus the `mobile` column that makes conversations findable.

---

## Decisions

Settled during design. Recorded so they are not relitigated mid-build.

| # | Decision | Rationale |
|---|---|---|
| D1 | Two slices, A then B | Slice A has no design forks and no schema risk; holding it behind Slice B's debate costs working tools for nothing |
| D2 | API only, no UI this pass | UI wiring is decided separately once the endpoints are real |
| D3 | Status endpoint probes live dependencies (JAM CRM, dispose) | A status page that only reads Redis cannot tell "healthy and idle" from "silently broken" |
| D4 | Live probes cached 60s server-side | A polled endpoint that calls JAM on every request turns our monitoring into standing traffic against the client's production CRM |
| D5 | Three states only — `ok` / `degraded` / `down` | Maps to one green/amber/red dot with no interpretation required |
| D6 | Queue warning depth is configurable, default 20 | Real peak volume is unknown; a threshold tuned blind produces amber noise people learn to ignore |
| D7 | Session reset is a **hard** reset | Soft reset preserves half the old state — often including whatever wedged the customer. Hard reset always works; the cost is the customer repeats a few answers |
| D8 | Add `mobile` to the interactions table | Search-by-phone is the primary support use case, and it is impossible without it. The `_add_missing_columns` migration hook already exists |
| D9 | Leads read live from CSV, under a shared lock | The file is 6 rows and grows one row per qualified lead; a SQLite mirror is over-engineering. The lock is mandatory — see R2 |
| D10 | One `ADMIN_TOKEN`, full data, no masking | Keeps this build to its scope. Roles and audit are Tier 4, revisited when the client's team gets access |

---

## Slice A — Operational status

### A1. `GET /admin/health` — unchanged

No auth, returns `{"status": "ok"}`. Reserved for liveness probes. Left as-is deliberately so a future compose healthcheck has a dependency-free target.

### A2. `GET /admin/api/status` — authenticated

Returns one rolled-up verdict plus a flat list of named checks, each with its own status and a human-readable detail line.

```json
{
  "status": "degraded",
  "checked_at": "2026-08-18T09:14:02Z",
  "checks": [
    {"name": "Redis",       "status": "ok",       "detail": "Connected (2 ms)"},
    {"name": "Worker",      "status": "ok",       "detail": "1 worker, last seen 4s ago"},
    {"name": "Queue",       "status": "degraded", "detail": "47 messages waiting, 3 failed"},
    {"name": "Gemini key",  "status": "ok",       "detail": "Runtime key active"},
    {"name": "JAM CRM",     "status": "ok",       "detail": "Reachable (310 ms)"},
    {"name": "JAM dispose", "status": "down",     "detail": "HTTP 502 (cached 12s ago)"}
  ]
}
```

**Check definitions**

| Check | Source | `down` when | `degraded` when |
|---|---|---|---|
| Redis | `PING` + round-trip | unreachable | — |
| Worker | `rq.Worker.all(connection=redis)` | none registered | newest `last_heartbeat` older than 480s |
| Queue | RQ queue + failed registry | — | depth > `ADMIN_QUEUE_WARN_DEPTH`, or any failed jobs |
| Gemini key | `rag.has_client()` | — | not configured |
| JAM CRM | live `GET` against `CLIENT_CRM_CUSTOMER_URL` | — | connection failure or 5xx |
| JAM dispose | live probe against `CLIENT_DISPOSE_URL` | — | connection failure or 5xx |

Overall `status` is the worst individual check. Worker liveness comes free from the RQ registry — **no worker-side code change**. `rq==2.9.1` is already installed and the `admin` service already has `REDIS_URL`.

**Worker liveness is registry presence, not heartbeat age.** Measured against the live worker: a healthy *idle* worker's last heartbeat was **369 seconds** old, with RQ's `worker_ttl` at its default 420s. A 60s threshold — the obvious first guess — would report a perfectly healthy bot as down every few minutes. RQ expires a dead worker's registry key on its own within ~90s, so disappearing from `Worker.all()` is the reliable death signal. Heartbeat age is kept only as a `degraded` hint past `worker_ttl + 60`.

**A 4xx from a probe counts as reachable.** Probes carry no credentials or query parameters, so anything that answers proves the far side is up. Only a connection failure or a 5xx is a fault — treating 4xx as one would leave the page permanently amber, which is how status pages get ignored.

The two live probes are cached for `ADMIN_PROBE_CACHE_SEC`; a cached result reports its age in `detail`.

Where a dependency is not configured at all (e.g. `CLIENT_DISPOSE_URL` empty), the check reports `ok` with detail `Not configured` rather than failing the whole page.

When Redis is unreachable, Worker and Queue report `down` with `Unknown — Redis unreachable`. Both are read out of Redis, so their true state is unknown, and unknown must never render as healthy.

### A3. `POST /admin/api/session/reset` — authenticated

```json
// request
{"mobile": "+919371062202"}

// response
{"mobile": "+919371062202", "cleared": true}
```

Deletes the Redis key `client:session:{mobile}` (format per `client_adapters.py:_key`). `cleared` reports whether a session actually existed, so the caller can tell "reset done" from "nothing there".

Hard reset per **D7**: language choice, captured answers, confirmed dealer, brochures sent — all gone. The customer's next message starts at language selection.

Deduplication keys are **not** touched: they are `client:seen:{message_id}`, keyed per message rather than per customer, and any new inbound message carries a fresh id.

### A4. New settings

| Variable | Default | Purpose |
|---|---|---|
| `ADMIN_QUEUE_WARN_DEPTH` | `20` | Queue depth above which Queue reports `degraded` |
| `ADMIN_PROBE_CACHE_SEC` | `60` | How long a live dependency probe result is reused |

Added to `config.py` and `.env.example`.

---

## Slice B — Conversations and leads

### B1. Schema change — `mobile` on interactions

Per **D8**:

- Add `mobile TEXT NOT NULL DEFAULT ''` via the existing `_add_missing_columns` hook (`interactions.py:289`).
- Add an index on `(mobile, id)`.
- Thread `mobile` through `record_exchange` / `record_turn` and pass it at both call sites in `client_processing.py` (≈ lines 2271 and 2288).
- Add `mobile` to `CSV_COLUMNS` and to `_filters`.

> **Conversations already recorded in production will have `mobile` empty.** The number was never stored, so no backfill is possible. Only conversations recorded after deployment are findable by phone.

### B2. `GET /admin/api/interactions`

Paginated list. Filters: `mobile`, `session`, `channel`, `language`, `status`, `needs_review`, `search`, `limit`, `offset`. Returns `{"count": N, "items": [...]}`.

`list_interactions()` (`interactions.py:171`) already implements all of this bar `mobile` — it caps `limit` at 500 and clamps `offset`. The endpoint is a thin pass-through.

### B3. `GET /admin/api/interactions/{session}`

Full ordered transcript for one conversation. Convenience over B2's `session` filter, so a caller rendering a thread does not have to paginate.

### B4. `POST /admin/api/interactions/{id}/review`

Body `{"note": "..."}`. Delegates to `mark_reviewed()` (`interactions.py:208`), which only succeeds on a row that is `needs_review = 1` and not yet reviewed. Returns 404 when the row does not qualify, so the caller can tell "marked" from "already handled".

### B5. `GET /admin/api/interactions/export.csv`

CSV download over the same filters as B2, via `export_csv()`. `text/csv` with a `Content-Disposition` filename.

### B6. `GET /admin/api/leads`

Paginated rows from `data/leads.csv`, plus the existing count and column list from `leads_summary()` (`leads.py:180`).

Read under a **shared `flock`** on the same lock file `LeadWriter` uses (`leads.py:135`). This is not optional — see R2.

### B7. `GET /admin/api/leads/export.csv`

Whole file, same lock discipline.

---

## Non-goals

Explicitly out of scope for Tier 1, to keep the slice shippable:

- Any UI. Nothing in `assets/admin.html` changes.
- Roles, read-only tokens, or an audit trail (**D10** — Tier 4).
- Config versioning and rollback (Tier 4).
- Business metrics — messages/hour, error rate, dispose success counts. These want the same `interactions.db` queries Slice B builds, so they are cheap to add afterwards and wasteful to build twice.
- Dealer, brochure, and knowledge-base management (Tier 2).
- Wiring the dead config sections — `voice_policy`, `welcome_text`, `intro`, `languages`, `entry_sources` (Tier 3).

---

## Constraints and risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | A polled status endpoint hammering the client's production CRM | 60s server-side cache on live probes (**D4**) |
| R2 | `leads.py:_write_rows` opens the file `"w"` — it truncates and rewrites the **whole** file per lead. An unlocked reader catches a half-written file and returns a truncated list or raises mid-parse | Take a shared `flock` on read (**D9**) |
| R3 | Historical conversations unfindable by phone | Accepted and documented (B1). No backfill exists |
| R4 | `conversation_id` rotates on session expiry, so one customer spans several sessions | Solved by B1 — `mobile` groups them |
| R5 | Full PII behind a single static shared token | Accepted for this pass (**D10**); Tier 4 addresses it |
| R6 | Admin cannot observe the worker process directly (separate container) | Everything is inferred through Redis and the shared `./data` volume; RQ's registry covers worker liveness |

**Compose change required** (this corrects an earlier claim that none was). The `admin` service sets only `REDIS_URL` and `CLIENT_ENV`; `CLIENT_QUEUE_NAME` and `CLIENT_CRM_CUSTOMER_URL` are set on `client-worker` via compose `environment:` and are **not** in `.env`. Without adding them to `admin`, the status page would inspect an empty `default` queue while the worker consumes `client`, and would report JAM CRM as "Not configured" in production. Both are now set on the `admin` service and must be kept in step with `client-worker`.

The `./data` mount is already in place and holds both `interactions.db` and `leads.csv`, so Slice B needs no further compose work.

---

## Acceptance criteria

**Slice A**

1. `GET /admin/api/status` without a token returns 401; with `ADMIN_TOKEN` empty returns 503, matching the existing contract in `web.py`.
2. With Redis down, overall status is `down` and the Redis check names it.
3. With no RQ worker registered, overall status is `down`.
4. A healthy idle worker (heartbeat ~369s old) stays `ok`; only past 480s does it go `degraded`, never `down`.
5. Queue depth above `ADMIN_QUEUE_WARN_DEPTH` yields `degraded`, not `down`; depth exactly at the threshold stays `ok`.
6. An unconfigured dependency reports `ok` / `Not configured`, never a failure.
7. Two calls inside `ADMIN_PROBE_CACHE_SEC` issue **one** outbound request per live probe, and the second reports its cached age.
8. `POST /admin/api/session/reset` removes `client:session:{mobile}` and reports `cleared: true`; a second call reports `cleared: false`. The key format is asserted against `RedisClientState._key`, so the two cannot drift apart.
9. Reset returns 503, not 500, when Redis is unavailable.

**Slice B**

8. A conversation recorded after the migration is retrievable by `mobile`.
9. An existing database gains the `mobile` column on open without data loss (`_add_missing_columns` path).
10. Filters, `limit`, and `offset` behave as `list_interactions()` defines, including the 500 cap.
11. `POST /admin/api/interactions/{id}/review` returns 404 for an already-reviewed row.
12. `GET /admin/api/leads` returns complete, well-formed rows while `LeadWriter` is concurrently appending.
13. Both CSV exports return `text/csv` with a filename and headers matching `CSV_COLUMNS`.

Tests extend `tests/test_web_admin.py`, following the existing `create_admin_app(...)` injection pattern so no global state is required.

# Admin API Reference

Complete request and response shapes for every endpoint served by `web.py`.

**Base URL** — set once, then every example below works as written:

```bash
BASE=https://<your-admin-host>        # e.g. the Cloudflare tunnel hostname
AUTH="Authorization: Bearer $ADMIN_TOKEN"
```

**Authentication** — every endpoint except the three marked *public* requires the header:

```
Authorization: Bearer <ADMIN_TOKEN>
```

| Condition | Response |
|---|---|
| Header missing or wrong | `401` `{"detail": "Invalid or missing admin token."}` |
| `ADMIN_TOKEN` unset on the server | `503` `{"detail": "Admin panel is disabled (ADMIN_TOKEN is not set)."}` — the whole panel is off, not open |
| Validation failure | `400` `{"detail": "<what was wrong>"}` |
| Record not found / not applicable | `404` `{"detail": "..."}` |
| Redis unavailable (reset only) | `503` `{"detail": "Redis unavailable: ..."}` |

There is one shared token. No roles, no per-user access.

---

## Index

| # | Method | Path | Purpose |
|---|---|---|---|
| 1 | `GET` | `/admin/health` | Liveness probe *(public)* |
| 2 | `GET` | `/admin` | The panel HTML *(public)* |
| 3 | `GET` | `/` | Redirect to `/admin` *(public)* |
| 4 | `GET` | `/admin/api/status` | Is the bot working? |
| 5 | `POST` | `/admin/api/session/reset` | Unstick one customer |
| 6 | `GET` | `/admin/api/interactions` | Search conversations |
| 7 | `GET` | `/admin/api/interactions/export.csv` | Conversations as CSV |
| 8 | `GET` | `/admin/api/interactions/{session}` | One full transcript |
| 9 | `POST` | `/admin/api/interactions/{id}/review` | Mark a turn reviewed |
| 10 | `GET` | `/admin/api/leads` | Captured leads |
| 11 | `GET` | `/admin/api/leads/export.csv` | Leads as CSV |
| 12 | `GET` | `/admin/api/media/{kind}` | List uploaded media |
| 13 | `POST` | `/admin/api/media/{kind}` | Upload a brochure or image |
| 14 | `DELETE` | `/admin/api/media/{kind}/{filename}` | Delete one |
| 15 | `GET` | `/admin/api/config` | Read live bot config |
| 16 | `PUT` | `/admin/api/config` | Replace bot config |
| 17 | `GET` | `/admin/api/meta` | Defaults and allowed values |
| 18 | `GET` | `/admin/api/gemini` | Gemini key state |
| 19 | `POST` | `/admin/api/gemini` | Set / rotate the key |
| 20 | `DELETE` | `/admin/api/gemini` | Clear the runtime key |

### Machine-readable spec

The OpenAPI 3.1 document is committed at [`docs/openapi.json`](openapi.json) — generated from the routes themselves, so it cannot drift from the code. A test fails if it goes stale.

```bash
./venv/bin/python scripts/export_openapi.py   # regenerate after changing a route
```

Import that file straight into Postman, Insomnia, or a client generator. The same spec is served live at `$BASE/openapi.json`, with interactive views at `$BASE/docs` (Swagger) and `$BASE/redoc`.

Swagger's **Authorize** button works: the spec declares an `HTTPBearer` scheme, so paste the `ADMIN_TOKEN` once and every "Try it out" carries it.

---

## 1. `GET /admin/health` — public

Liveness only. Deliberately dependency-free, so it answers even when Redis and JAM are down. Use #4 for real health.

```bash
curl -s "$BASE/admin/health"
```
```json
{"status": "ok"}
```

## 2. `GET /admin` — public

Returns the panel's HTML. Carries no secrets; the browser prompts for the token and sends it on subsequent API calls.

## 3. `GET /` — public

`307` redirect to `/admin`.

---

## 4. `GET /admin/api/status`

One rolled-up verdict over six checks. No request body, no parameters.

```bash
curl -s -H "$AUTH" "$BASE/admin/api/status"
```
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

| Field | Meaning |
|---|---|
| `status` | `ok` / `degraded` / `down` — the worst individual check |
| `checked_at` | UTC, ISO 8601, `Z` suffix |
| `checks[].name` | Fixed set, always these six, always this order |
| `checks[].status` | Same three values |
| `checks[].detail` | Human-readable. Live probes append `(cached Ns ago)` when reused |

**When each check goes red or amber**

| Check | `down` | `degraded` |
|---|---|---|
| Redis | unreachable | — |
| Worker | none registered | heartbeat older than 480s |
| Queue | — | depth > `ADMIN_QUEUE_WARN_DEPTH` (default 20), or any failed jobs |
| Gemini key | — | not configured |
| JAM CRM / dispose | — | connection failure or 5xx |

A dependency that is not configured reports `ok` / `"Not configured"` — absence is not a fault. When Redis is down, Worker and Queue report `down` / `"Unknown — Redis unreachable"`, because their true state cannot be known.

---

## 5. `POST /admin/api/session/reset`

Hard-resets one customer. Their next WhatsApp message starts from language selection — language, captured answers, confirmed dealer and brochures-sent are all cleared.

**Request body**

```json
{"mobile": "+919371062202"}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `mobile` | string | yes | Must be non-blank. Whitespace is trimmed. Use the same format the CRM sends, normally `+91…` |

**Response `200`**

```json
{"mobile": "+919371062202", "cleared": true}
```

`cleared` is `true` if a session existed, `false` if there was nothing to clear — both are success.

```bash
curl -s -X POST -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"mobile":"+919371062202"}' "$BASE/admin/api/session/reset"
```

Deduplication keys are untouched: they are keyed per message, not per customer.

**Errors** — `400` blank or missing `mobile`; `503` Redis unavailable.

---

## 6. `GET /admin/api/interactions`

Search conversation turns. Each row is **one turn** — a customer message or a bot reply, not a whole conversation.

**Query parameters** — all optional, combined with AND

| Name | Type | Default | Notes |
|---|---|---|---|
| `mobile` | string | — | Exact match. URL-encode `+` as `%2B` |
| `session` | string | — | Exact conversation id |
| `channel` | string | — | e.g. `client_app` |
| `language` | string | — | e.g. `Hindi` |
| `status` | string | — | `ok`, `delivery_failed`, … |
| `needs_review` | bool | — | `true` = flagged and not yet reviewed; `false` = everything else |
| `search` | string | — | Substring across `message`, `error`, `session` |
| `limit` | int | `100` | Clamped to 1–500 |
| `offset` | int | `0` | Negative values clamp to 0 |

**Response `200`**

```json
{
  "count": 3692,
  "items": [
    {
      "id": 4101,
      "timestamp": "2026-08-18T09:14:02+00:00",
      "session": "client-e622c23876cc45a",
      "mobile": "+919371062202",
      "channel": "client_app",
      "source": "client_app",
      "language": "Hindi",
      "role": "user",
      "message": "price kya hai",
      "latency_ms": null,
      "status": "ok",
      "error": "",
      "model": "",
      "citations": [],
      "needs_review": false,
      "reviewed_at": null,
      "review_note": "",
      "prompt_tokens": null,
      "completion_tokens": null
    }
  ]
}
```

`count` is the total matching the filter, not the page size. `items` is one page, ordered **oldest first within the page**, while pages walk backwards from the newest — so `offset=0` is the most recent page and reads top-to-bottom like a transcript.

`role` is `user` or `assistant`. On a user turn, `latency_ms`, `model`, `citations` and the token counts are empty — they belong to the assistant turn.

```bash
# everything this customer ever said
curl -s -H "$AUTH" "$BASE/admin/api/interactions?mobile=%2B919371062202"

# what still needs a human
curl -s -H "$AUTH" "$BASE/admin/api/interactions?needs_review=true&limit=50"

# find a phrase
curl -s -H "$AUTH" "$BASE/admin/api/interactions?search=EMI"
```

> Turns recorded before the `mobile` column shipped have `mobile: ""` and cannot be found by number. There is no backfill.

---

## 7. `GET /admin/api/interactions/export.csv`

Same filters as #6 — `mobile`, `session`, `channel`, `language`, `status`, `needs_review`, `search` — with no pagination. Returns every match.

`Content-Type: text/csv`, `Content-Disposition: attachment; filename="interactions.csv"`.

Header row:

```
id,timestamp,session,mobile,channel,source,language,role,message,latency_ms,status,error,model,citations,needs_review,reviewed_at,review_note
```

`citations` is a JSON array encoded as a string.

```bash
curl -s -H "$AUTH" -o interactions.csv \
  "$BASE/admin/api/interactions/export.csv?mobile=%2B919371062202"
```

---

## 8. `GET /admin/api/interactions/{session}`

One conversation in full, oldest turn first, up to 500 turns.

```bash
curl -s -H "$AUTH" "$BASE/admin/api/interactions/client-e622c23876cc45a"
```
```json
{
  "session": "client-e622c23876cc45a",
  "count": 12,
  "items": [ { "...same shape as #6..." } ]
}
```

**`404`** when the session has no turns.

> A customer who returns after their 1-hour session lapses gets a **new** `session` id. To see everything one person ever said, query #6 by `mobile` instead.

---

## 9. `POST /admin/api/interactions/{id}/review`

Mark one flagged turn as handled. `{id}` is the numeric `id` from #6.

**Request body** — optional; `{}` is valid

```json
{"note": "checked, dealer followed up"}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `note` | string | no | Trimmed. Defaults to `""` |

**Response `200`**

```json
{"id": 4101, "reviewed": true, "note": "checked, dealer followed up"}
```

**`404`** when the turn is not awaiting review — either never flagged, or already reviewed. This is deliberate, so two people cannot both claim the same item.

```bash
curl -s -X POST -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"note":"dealer called back"}' "$BASE/admin/api/interactions/4101/review"
```

---

## 10. `GET /admin/api/leads`

Captured lead rows, newest first.

| Name | Type | Default | Notes |
|---|---|---|---|
| `search` | string | `""` | Case-insensitive substring across **every** column — one box covers mobile, name, pincode |
| `limit` | int | `100` | Clamped to 1–500 |
| `offset` | int | `0` | |

**Response `200`**

```json
{
  "count": 359,
  "columns": ["timestamp", "channel", "source", "session", "language", "mobile", "..."],
  "items": [
    {
      "timestamp": "2026-08-17T15:15:43",
      "channel": "client_app",
      "source": "client_app",
      "session": "client-e622c23876cc45a",
      "language": "Hindi",
      "mobile": "+919371062202",
      "crm_customer_id": "",
      "customer_name": "Ramesh",
      "product_interest": "King EV MAX",
      "purchase_timeline": "next month",
      "pincode": "411001",
      "lead_quality": "hot",
      "disposition": "interested"
    }
  ]
}
```

`columns` is the authoritative order, taken from the live admin config — **it changes when capture fields are edited**, so render from `columns` rather than hard-coding. Every value is a string; empty means not captured. `count` is the number matching `search`, before paging.

```bash
curl -s -H "$AUTH" "$BASE/admin/api/leads?search=411001"
```

Read under a shared file lock, so a page is never a half-written file.

---

## 11. `GET /admin/api/leads/export.csv`

The whole leads file, same lock discipline. `text/csv`, `filename="leads.csv"`.

---

## Media uploads

`data/media` is a shared volume: the admin container writes to it and the media
host serves the same directory read-only at `/media/`. Publishing is therefore a
file write — no CDN account, no third party, no long-running job.

`{kind}` is one of:

| kind | Directory | Accepts | Limit | Used for |
|---|---|---|---|---|
| `brochures` | `data/media/brochures` | `.pdf` | 25 MB | Product brochures, warranty and PMS PDFs |
| `images` | `data/media/share_location` | `.jpg` `.jpeg` `.png` | 5 MB | The how-to share-location cards |

Any other kind returns `404`.

**Uploading does not change what the bot sends.** An admin still points
`documents.<product>.brochure` or `share_location_image.url` at the returned
URL. Publishing a draft must never start sending it.

### `GET /admin/api/media/{kind}`

```json
{
  "kind": "brochures",
  "base_url": "https://media.example.com/media/brochures",
  "max_upload_bytes": 26214400,
  "allowed_suffixes": [".pdf"],
  "items": [
    {"filename": "King_EV_MAX_2027.pdf", "size_bytes": 3215592,
     "url": "https://media.example.com/media/brochures/King_EV_MAX_2027.pdf"}
  ]
}
```

### `POST /admin/api/media/{kind}`

`multipart/form-data`:

| Field | Type | Required | Notes |
|---|---|---|---|
| `file` | file | yes | The PDF |
| `overwrite` | bool | no | Defaults `false`; replacing an existing name must be deliberate |

```bash
curl -s -H "$AUTH" -F "file=@King_EV_MAX_2027.pdf" \
  "$BASE/admin/api/media/brochures"

curl -s -H "$AUTH" -F "file=@how_to.jpg" \
  "$BASE/admin/api/media/images"
```

Returns `{"kind", "filename", "size_bytes", "url"}`.

Rejected with `400` when the extension is wrong for the kind, the file is empty
or over the limit, the content does not match its type (the leading bytes are
checked, so a PDF renamed `.jpg` is refused), or the name already exists without
`overwrite=true`. Filenames are sanitised to a single path component and the
resolved parent is asserted, so an upload cannot write outside its directory.
Writes are staged then moved into place, so the media host can never serve a
half-uploaded file.

### `DELETE /admin/api/media/{kind}/{filename}`

`{"kind": "...", "filename": "...", "deleted": true}`, or `404` if there is no
such file.

---

## 15. `GET /admin/api/config`

The live bot configuration. This is the exact document `PUT` expects back.

```json
{
  "bot_name": "TVS Passenger 3W Assistant",
  "welcome_text": "Welcome! Choose your language to start …",
  "languages": [{"code": "English", "label": "English"}],
  "capture_fields": [{"id": "pincode", "label": "Pincode", "required": true}],
  "flow_steps": ["intro", "model_interest", "campaign_awareness", "timeline",
                 "location", "feature_awareness", "documents", "wrap_up"],
  "voice_policy": "intro_only",
  "campaign_text": "ACTIVE CAMPAIGN — \"Vaada\" scheme …",
  "campaign_starts_on": "2026-08-01",
  "campaign_ends_on": "2026-10-31",
  "documents": {
    "King Deluxe": {
      "brochure": "https://1.jamoutsourcing.com/f/King_Deluxe_Petrol-English.pdf",
      "fuel": {
        "cng": "https://1.jamoutsourcing.com/f/King_Deluxe_CNG-English.pdf",
        "petrol": "https://1.jamoutsourcing.com/f/King_Deluxe_Petrol-English.pdf"
      },
      "support": [
        {"url": "https://1.jamoutsourcing.com/f/Deluxe-PMS-Schedule.pdf", "kind": "pms"}
      ]
    }
  },
  "intro": {"English": {"text": "Hi! I'm TVS Motor's assistant …", "audio_url": null}},
  "entry_sources": {"whatsapp": {"welcome_override": null}}
}
```

> Only `bot_name`, `campaign_text`, `flow_steps` and `capture_fields` currently affect the WhatsApp bot. `welcome_text`, `intro`, `languages`, `voice_policy` and `entry_sources` are stored and returned but **not read** by the WhatsApp path — that copy is hardcoded in `client_static_messages.py`.

## 16. `PUT /admin/api/config`

Replaces the **entire** document. There is no partial update and no version history — always `GET` first, edit, then `PUT` back.

```bash
curl -s -H "$AUTH" "$BASE/admin/api/config" > cfg.json
# edit cfg.json
curl -s -X PUT -H "$AUTH" -H "Content-Type: application/json" \
  --data @cfg.json "$BASE/admin/api/config"
```

Returns the saved document on `200`. Changes reach the worker on its next message — no restart.

**Required fields:** `bot_name`, `welcome_text`, `languages`, `capture_fields`, `flow_steps`, `voice_policy`, `campaign_text`, `intro`.

**Validation rules**, each returning `400` with a message naming the field:

- `bot_name` non-empty string; `welcome_text` and `campaign_text` strings
- `languages` non-empty; every entry `{code, label}`, both non-empty, `code` unique
- `capture_fields` non-empty; every entry needs a unique non-empty `id`; `required` must be boolean
- `flow_steps` non-empty list of non-empty strings
- `voice_policy` one of `always`, `intro_only`, `never`, `mirror_user`
- `intro` must contain an entry for **every** language `code`, each `{text: string, audio_url: string|null}`
- `campaign_starts_on` / `campaign_ends_on` must be `YYYY-MM-DD` or `null`, and the end must not precede the start
- `documents` is optional. Each product needs a non-empty `brochure` URL; `fuel` keys must be `cng`, `lpg` or `petrol`; each `support` entry needs a `url` and a `kind` of `warranty` or `pms`

**Product documents.** `documents` replaces what used to be a hardcoded table, so a new model year is a config edit rather than a redeploy. These PDFs live on JAM's own CDN — `CLIENT_MEDIA_BASE_URL` serves only the share-location card, not brochures.

`brochure` is the default; `fuel` overrides it when the customer names a fuel type; `support` PDFs are sent **only** when they ask about warranty or servicing, so asking for "the brochure" delivers one file rather than three. Removing a product from `documents` stops the bot offering its brochure at all. If the key is absent, or the config cannot be read, the built-in defaults apply — a config problem can never stop a customer getting a brochure.

**Campaign scheduling.** Both date fields are optional and default to `null`, which means open-ended — a config with neither set behaves exactly as before scheduling existed, always on. Bounds are **inclusive** and evaluated in **India time**, so a campaign ending `2026-10-31` stops after that day in IST rather than 5h30m out.

Outside the window the bot does not merely omit the offer: the `CAMPAIGN` section, the "make them aware of the active campaign" goal, and the `campaign_awareness` flow step are all removed from the prompt, and `campaign_shown` is instructed to stay empty. Leaving any of them in was enough for the model to keep pitching a scheme that had expired.

Adding a language therefore means adding its `intro` entry in the same request.

## 17. `GET /admin/api/meta`

Allowed values and factory defaults, for building a form.

```json
{
  "voice_policies": ["always", "intro_only", "mirror_user", "never"],
  "default_config": { "...a full config document..." },
  "gemini": {"configured": true, "source": "env", "model": "gemini-3.5-flash-lite",
             "file_search_store": "fileSearchStores/…"}
}
```

---

## 18. `GET /admin/api/gemini`

```json
{
  "configured": true,
  "source": "env",
  "model": "gemini-3.5-flash-lite",
  "file_search_store": "fileSearchStores/tvsmanual-ur9gkjpgkxyh"
}
```

| Field | Meaning |
|---|---|
| `configured` | Whether a usable client exists. `false` means **the bot cannot answer** |
| `source` | `runtime` (set via #16), `env` (from `.env`), or `null` (none) |

## 19. `POST /admin/api/gemini`

**Request body**

```json
{"api_key": "AIza…"}
```

The key is **validated with a live Gemini call before being saved**. On success it is written to `data/gemini_key.txt` (chmod 600) and overrides the `.env` key; the worker picks it up on its next message.

Returns the same shape as #18, with `source` now `runtime`.

**`400`** on a blank key, or `{"detail": "Key rejected: …"}` when Gemini refuses it. A rejected key is never saved, so a bad paste cannot take the bot down.

## 20. `DELETE /admin/api/gemini`

Removes the runtime key and falls back to `.env`. Returns the same shape as #18.

> If `GEMINI_API_KEY` is empty in `.env`, this leaves the bot with **no key at all** and it stops answering. Check `source` first.

---

## Notes for building a client

- **Render leads from `columns`**, not a hard-coded list — admins can add and reorder capture fields.
- **Group conversations by `mobile`, not `session`.** One customer produces a new `session` every time their 1-hour session lapses.
- **`count` is the filtered total**, so pagination is `Math.ceil(count / limit)`.
- **`404` from #9 is normal**, not an error to surface loudly — it means someone else already reviewed it.
- **Encode `+` as `%2B`** in the `mobile` query parameter, or it arrives as a space.
- **`PUT /config` is read-modify-write.** There is no history, so a blind write loses whatever another admin saved.

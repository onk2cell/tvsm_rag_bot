# Client API and Webhook Integration Guide

This document describes the production contracts between the TVS qualification bot and the client CRM / customer app.

There are three APIs:

1. **Inbound message webhook** — client app/CRM calls the bot when a customer sends a message.
2. **Customer lookup API** — bot calls the client CRM to fetch customer details by mobile.
3. **Reply callback webhook** — bot calls the client to deliver the bot’s text reply.

```text
Customer app
    │
    │  1. POST /client/webhook/messages
    ▼
Bot webhook  ──enqueue──▶  Worker
                              │
                              │  2. GET customer by mobile
                              ▼
                         Client CRM
                              │
                              │  3. POST reply callback
                              ▼
                         Client app/CRM
```

All production traffic must use **HTTPS** and **HTTP Basic Authentication**.

---

## 1. Inbound message webhook (client → bot)

### Endpoint

```http
POST /client/webhook/messages
Authorization: Basic <base64(username:password)>
Content-Type: application/json
```

Credentials are provided during go-live. The production base URL will be shared separately.

### Purpose

Notify the bot that a customer sent a message. The bot acknowledges immediately (`202`) and processes the message asynchronously. The reply is **not** returned in this response.

### Required headers

| Header | Value |
|---|---|
| `Authorization` | HTTP Basic Auth |
| `Content-Type` | `application/json` |

### Request body

| Field | Type | Required | Notes |
|---|---|---|---|
| `message_id` | string | Yes | Unique ID for this message. Max 128 chars. Used for deduplication (7 days). |
| `type` | string | Yes | `text`, `image`, or `audio` |
| `mobile` | string | Yes | Indian E.164: `+91` followed by a 10-digit mobile starting with 6–9 |
| `timestamp` | string | Yes | Client-supplied timestamp string (any format). Stored as metadata only. |
| `content` | string | Required for `text` | Max 4096 characters. Optional caption for media. |
| `media_url` | string | Required for `image`/`audio` | Public HTTPS URL the bot can download |
| `mime_type` | string | Optional | If omitted, the bot detects type from the download `Content-Type`, then from the URL extension |

#### Allowed MIME types

**Images**

- `image/jpeg`
- `image/png`
- `image/webp`

**Audio**

- `audio/webm`
- `audio/ogg`
- `audio/mp4`
- `audio/mpeg`
- `audio/mp3`
- `audio/wav`
- `audio/x-wav`

Media limits: max **10 MB**. Audio max duration: **60 seconds**.

If `mime_type` is omitted:

1. Bot uses the media server’s `Content-Type` when it is a supported type.
2. Otherwise bot guesses from the URL extension (for example `.jpg` → `image/jpeg`, `.mp3` → `audio/mpeg`).
3. If neither works, the bot asks the customer to resend the media.

### Example — text

```bash
curl -X POST "https://<bot-host>/client/webhook/messages" \
  -u "CLIENT_USER:CLIENT_PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{
    "message_id": "crm-msg-1001",
    "type": "text",
    "mobile": "+918286871533",
    "timestamp": "2026-07-20T09:00:00+05:30",
    "content": "Hi, I want details about Jupiter"
  }'
```

### Example — image (document)

```json
{
  "message_id": "crm-msg-1002",
  "type": "image",
  "mobile": "+918286871533",
  "timestamp": "2026-07-20T09:01:00+05:30",
  "media_url": "https://cdn.example.com/docs/dl-front.jpg",
  "content": "Driving licence"
}
```

### Example — audio

```json
{
  "message_id": "crm-msg-1003",
  "type": "audio",
  "mobile": "+918286871533",
  "timestamp": "2026-07-20T09:02:00+05:30",
  "media_url": "https://cdn.example.com/voice/note.mp3"
}
```

### Success responses (`202`)

**Accepted**

```json
{
  "status": "accepted",
  "message_id": "crm-msg-1001",
  "duplicate": false
}
```

**Duplicate** (same `message_id` already received)

```json
{
  "status": "duplicate",
  "message_id": "crm-msg-1001",
  "duplicate": true
}
```

**Ignored** (unsupported `type`)

```json
{
  "status": "ignored",
  "message_id": "crm-msg-1004",
  "duplicate": false,
  "reason": "unsupported_type"
}
```

### Error responses

| HTTP | Meaning |
|---|---|
| `400` | Invalid payload (missing/invalid fields) |
| `401` | Invalid Basic Auth credentials |
| `429` | Rate limited (more than 12 messages/minute for the same mobile) |
| `5xx` | Temporary server error — safe to retry with the same `message_id` |

Example validation error:

```json
{
  "code": "invalid_payload",
  "errors": [
    {"field": "mobile", "message": "String should match pattern ..."},
    {"field": "content", "message": "content is required for text"}
  ]
}
```

### Client responsibilities for inbound webhook

- Generate a **new unique `message_id`** for every customer message.
- On network timeout or `5xx`, retry with the **same** `message_id` (idempotent).
- Do not wait for the bot reply on this call; wait for the reply callback instead.
- Keep using the same `mobile` for the same customer so conversation continuity works.

---

## 2. Customer lookup API (bot → JAM / CRM)

### Current production path (JAM Get Customer Details)

```http
POST https://tvsm.jamoutsourcing.com/index.php/whatsapp_bot/customer
X-API-KEY: <key from JAM>
Content-Type: application/json
```

```json
{ "mobile": "918459522206" }
```

Notes:

- Mobile may include `+` / spaces; JAM matches on the last 10 digits
- Success: HTTP `200` with `"status":"success"` and `data` lead fields
- `404` / no lead: bot creates a temporary identity and shows a **text** language menu
- If `data` includes `state` / `fldv_state` (or aliases), bot maps it to a default language:
  - Maharashtra, Goa → Marathi
  - Tamil Nadu, Puducherry → Tamil
  - Andhra Pradesh, Telangana → Telugu
  - Karnataka → Kannada
  - Kerala → Malayalam
  - Hindi-belt states → Hindi
  - Other / unknown state → English
- If language/state is missing, bot asks (English text only, no buttons):
  1. English  2. हिंदी  3. मराठी  4. தமிழ்
- Customer can later switch by saying the language name or `1`–`4`

### Legacy CRM GET shape (mock / Basic Auth)

```http
GET <CLIENT_CRM_CUSTOMER_URL>?mobile=+918286871533
Authorization: Basic <base64(username:password)>
```

Exact production URL and credentials are provided by the client.

### Purpose

On the first message of a conversation, the bot looks up the customer by mobile number to get identity and preferred language.

### Query parameter

| Param | Example | Required |
|---|---|---|
| `mobile` | `+918286871533` | Yes |

### Expected successful response (`200`)

Preferred shape:

```json
{
  "customers": [
    {
      "customer_id": "C12345",
      "name": "Asha Patil",
      "preferred_language": "Marathi"
    }
  ]
}
```

Also accepted:

- A bare array of customer objects
- A single customer object

Required fields per customer:

| Field | Required | Notes |
|---|---|---|
| `customer_id` (or `id`) | Yes | CRM customer identifier |
| `name` (or `customer_name`) | Yes | Display name |
| `preferred_language` | Recommended | Used for reply language. If missing/unsupported, bot detects from message text |

If multiple customers are returned, the bot uses the **first** record.

### Expected error responses

| HTTP | Bot behavior |
|---|---|
| `404` / empty list | Treated as lookup failure |
| `5xx` | Retried up to 3 times, then customer gets a temporary-unavailable reply |

### Client responsibilities for customer API

- Return identity for known mobiles.
- Prefer stable `customer_id` values.
- Prefer languages the bot supports (for example English, Hindi, Marathi). Exact supported set is configured in the bot admin.

---

## 3. Reply delivery (bot → client / WhatsApp)

### Current production path (JAM WhatsApp send API)

```http
POST https://tvsm.jamoutsourcing.com/index.php/whatsapp_bot/send
X-API-KEY: <key from JAM>
Content-Type: application/json
```

```json
{
  "mobile": "918459522206",
  "type": "text",
  "message": "Bot reply text"
}
```

Notes:

- Mobile must be digits only (`91...`), no `+`
- Success is HTTP `200` with `"status":"success"`
- No `in_reply_to` field in JAM send API; correlation is by mobile
- Customer lookup uses the same `X-API-KEY` against `/whatsapp_bot/customer`

### Lead disposition (JAM Dispose API)

After qualification wrap-up, the bot pushes the conversation outcome once:

```http
POST https://tvsm.jamoutsourcing.com/index.php/whatsapp_bot/dispose
X-API-KEY: <same key as send/customer>
Content-Type: application/json
```

```json
{
  "mobile": "918459522206",
  "pincode": "411001",
  "status": "interested",
  "remark": "notes from chat",
  "dealer_code": "11689",
  "expected_purchased_date": "07/08/2026",
  "product_name": "King Deluxe"
}
```

| Status | Extra fields |
|---|---|
| **all statuses** | `pincode` (mandatory, 6-digit) |
| `interested` | `dealer_code`, `expected_purchased_date` (`DD/MM/YYYY`), `product_name` |
| `not_interested` / `already_purchased_tvs_motor` / `not_enquired` | none beyond pincode |

Notes:

- Updates an existing CRM lead by mobile (does not create leads).
- Bot still attempts dispose even if CRM previously returned no customer (may 404).
- Dispose is skipped until a 6-digit pincode is known (from customer message, location→dealer pin, or CRM dealer pin).
- Purchase-date mapping: “next month” → 7th of next month; “in ≤10 days” → bot asks for exact date; farther day ranges are converted to a concrete date.
- Source: `docs/JAM_WhatsApp_Bot_Dispose_API_postman_collection_v1.1_pincode.json` / PDF docs.

### Legacy callback shape (mock / older assumption)

### Endpoint (client provides)

```http
POST <CLIENT_REPLY_WEBHOOK_URL>
Authorization: Basic <base64(username:password)>
Content-Type: application/json
```

Exact production URL and credentials are provided by the client.

### Purpose

Deliver the bot’s text reply so the client app can show it to the customer.

### Request body

| Field | Type | Always present | Notes |
|---|---|---|---|
| `message_id` | string | Yes | Unique outbound reply ID (client should dedupe on this) |
| `in_reply_to` | string | Yes | Original inbound `message_id` |
| `type` | string | Yes | Always `text` in v1 |
| `mobile` | string | Yes | Same customer mobile |
| `content` | string | Yes | Reply text, max 4096 chars per part |
| `timestamp` | string | Yes | ISO 8601 UTC, e.g. `2026-07-20T03:30:00+00:00` |
| `part_number` | integer | Yes | Starts at `1` |
| `part_count` | integer | Yes | Total parts for this reply |

### Example

```json
{
  "message_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "in_reply_to": "crm-msg-1001",
  "type": "text",
  "mobile": "+918286871533",
  "content": "Namaste Asha! Jupiter chi mahiti pahije ka?",
  "timestamp": "2026-07-20T03:30:12+00:00",
  "part_number": 1,
  "part_count": 1
}
```

### Long replies

If content exceeds 4096 characters, the bot splits it into ordered parts:

1. Sends part 1 and waits for success
2. Then sends part 2, and so on

Use `part_number` / `part_count` plus `in_reply_to` to reassemble.

### Success definition

Any HTTP **`2xx`** response (including `200` or `204`) means the reply was delivered successfully.

### Retry policy (bot side)

- Timeout: 30 seconds per attempt
- Attempts: 3 total
- Wait between attempts: 30 seconds
- After permanent failure: bot keeps the reply for admin review

### Client responsibilities for reply webhook

- Acknowledge with any `2xx` as soon as the reply is safely received/stored.
- Deduplicate by outbound `message_id`.
- Correlate the UI reply using `in_reply_to` (and `part_number` when split).
- Do not require the bot to wait for delivery/read receipts in v1.

---

## Conversation behavior (important for integrators)

| Topic | Behavior |
|---|---|
| Session key | `mobile` |
| Continuity | Same mobile continues one conversation while active |
| Idle expiry | After **1 hour** of inactivity (`CLIENT_HISTORY_TTL_SEC`), Redis session expires and a **new conversation** starts. The bot **always shows the language menu first** (even if CRM has a preferred language), then uses CRM remarks/status for welcome-back |
| Ordering | Messages for one mobile are processed in arrival order |
| Reply type | Text only in v1 |
| Images | Used for document recognition (licence, ID, finance, vehicle docs, etc.) |
| Audio | Transcribed, then answered as text |
| Lead notes | Stored locally by the bot; not written back to CRM in v1 |

---

## Checklist before go-live

Client must provide:

- [ ] Production customer lookup URL
- [ ] Production reply callback URL
- [ ] Basic Auth username/password for both client APIs
- [ ] Confirmation of customer response JSON shape (sample payload)
- [ ] Confirmation that reply webhook returns `2xx` on success

Bot team will provide:

- [ ] Production inbound webhook URL
- [ ] Basic Auth username/password for inbound webhook
- [ ] Staging/test window for end-to-end verification

---

## Quick reference

| Direction | API | Method | Who hosts it |
|---|---|---|---|
| Client → Bot | `/client/webhook/messages` | `POST` | Bot |
| Bot → Client | Customer lookup by `mobile` | `GET` | Client CRM |
| Bot → Client | Reply callback | `POST` | Client app/CRM |

---

## Local mock CRM lab

For end-to-end verification **before production deploy**, run the lab profile.
It uses the same inbound webhook → Redis → worker path, with CRM lookup and
reply callbacks pointed at `mock_client`.

```bash
docker compose --profile lab up -d --build
# open http://localhost:8003/mock/chat
```

In the lab UI:

1. Choose a **preset** (or edit mobile + CRM JSON)
2. **Save CRM for this mobile**
3. **Reset session** to simulate 1h idle expiry (language menu)
4. Chat — replies appear from the mock reply sink

Lab ports: mock UI `8003`, lab webhook `8005`. Values live in `.env.mock`
(test-only). Production remains `docker compose --profile client up -d`.

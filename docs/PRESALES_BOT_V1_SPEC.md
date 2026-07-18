# TVS Presales & Pre-Lead Qualification Bot — V1 Spec

**Status:** Ready for agent implementation  
**Source:** Batch-grill design session + existing codebase (`qualify_prototype`, `LEAD_QUALIFICATION_BOT_SPEC.md`, production WhatsApp RAG stack)  
**Issue tracker:** GitHub (`onk2cell/tvsm_rag_bot`) — label `ready-for-agent`

---

## Problem Statement

TVS Auto needs a presales assistant for **passenger three-wheelers** that behaves like a skilled tele-calling agent: it **qualifies interested customers**, captures structured lead profiles for dealerships, **proactively mentions active campaigns**, and answers **accurate product questions** (CNG, petrol, electric, specs) grounded in an admin-managed knowledge base — without inventing facts or quoting prices the dealership should provide.

Today the repo has **two disconnected paths**: a production **WhatsApp open Q&A RAG bot** and a standalone **web-only qualification prototype**. There is no unified conversation engine, no voice support, no admin-configurable qualification flow, and no campaign/KB management wired into the customer-facing bot. Sales teams cannot reliably get **qualified, downloadable leads** from both **WhatsApp** and a **public web chat** using one consistent experience.

---

## Solution

Build a **single channel-agnostic conversation engine** that runs **qualification-first** conversations with **admin-configurable** capture fields, flow order, branding, languages, voice policy, campaigns, and knowledge base — exposed through **WhatsApp** and **public web** adapters (plus an **admin test playground**).

Customers pick a language, receive an admin-configured intro (text and/or TTS audio), then move through qualification while the bot answers in-scope product questions briefly from the KB and redirects off-topic chat. On completion, the bot emits a structured lead profile to **CSV** for admin download. Voice is supported on both channels: users may speak; the bot detects language and replies in text and/or audio per admin rules.

**Launch scope:** TVS **passenger 3-wheelers** only (King EV MAX, King Deluxe, King Duramax Plus). KB and admin config must allow extension to more vehicles later without architectural rework.

---

## User Stories

1. As a **prospective TVS passenger 3W buyer**, I want to chat on **WhatsApp**, so that I can qualify and get product info where I already communicate.
2. As a **prospective buyer**, I want to chat on the **public website**, so that I can explore and qualify without installing an app.
3. As a **Ric Show attendee**, I want to scan a **QR code** that opens the same bot, so that my interest at the event is tracked without a separate product.
4. As a **customer**, I want to **pick my language** before the conversation starts, so that the entire chat stays in a language I understand.
5. As a **web customer**, I want the bot to **suggest a language from my browser locale** with buttons to switch, so that I don't have to guess how to start.
6. As a **customer**, I want to hear a **short intro** after picking language, so that I know what the bot will help with.
7. As a **customer**, I want to **send voice messages** on WhatsApp, so that I can speak naturally instead of typing.
8. As a **web customer**, I want a **microphone button** to speak my reply, so that voice works the same as on WhatsApp.
9. As a **customer speaking any supported language**, I want the bot to **understand my language and reply in the same language**, so that I don't have to switch to English.
10. As a **customer**, I want the bot to reply in **text**, **audio**, or **both** depending on configuration, so that the experience matches my preference and channel capabilities.
11. As a **customer**, I want the bot to ask **one question at a time** in a conversational tone, so that qualification feels like a human agent call—not a form dump.
12. As a **customer**, I want to tell the bot **which passenger model** I am interested in, so that the dealership knows my product focus.
13. As a **customer**, I want to be told about the **current TVS campaign** (e.g. Vaada scheme), so that I am aware of active offers.
14. As a **customer**, I want to share **when I plan to buy**, so that the dealership can prioritize follow-up.
15. As a **customer**, I want to share my **pincode**, so that I am routed to the nearest dealership.
16. As a **customer outside my home area**, I want to say **where I want the vehicle delivered**, so that routing reflects my actual need—not just my current location pincode.
17. As a **customer**, I want the bot to ask if I **already know the vehicle features**, so that it doesn't repeat information unnecessarily.
18. As a **customer who doesn't know features**, I want a **short accurate pitch** (max ~5 points), so that I understand the model without a spec sheet dump.
19. As a **customer**, I want to ask **fuel-type questions** (CNG vs petrol vs electric) mid-conversation, so that I can resolve doubts without leaving the flow.
20. As a **customer**, I want **brief accurate answers** from the knowledge base when I ask product questions, so that I trust the information.
21. As a **customer**, I want the bot to **return to qualification** after answering my product question, so that the conversation keeps moving toward completion.
22. As a **customer**, I want to be asked about my **driving licence, permit, and commercial badge** status, so that the dealership knows my documentation readiness.
23. As a **customer**, I want the bot to **not promise** the dealership will obtain my RTO badge for me, so that I have accurate expectations.
24. As a **customer asking about EMI or on-road price**, I want the bot to **defer to the dealership**, so that I am not misquoted.
25. As a **customer**, I want a **wrap-up summary** of what was captured and a promise of dealership contact, so that I know what happens next.
26. As a **customer going off-topic**, I want a **gentle redirect** back to TVS passenger 3-wheelers, so that the bot stays useful without being rude.
27. As a **TVS admin**, I want to **configure capture questions and their order** without redeploying code, so that qualification evolves with sales process changes.
28. As a **TVS admin**, I want to configure **bot name, welcome message, and branding**, so that the bot matches TVS tone and campaigns.
29. As a **TVS admin**, I want to configure the **list of supported languages**, so that we can launch with English, Hindi, Marathi, Tamil and extend later.
30. As a **TVS admin**, I want to configure **when the bot sends voice vs text-only replies**, so that we control cost and UX (e.g. voice at intro only, text for Q&A).
31. As a **TVS admin**, I want to configure **intro text** and optionally **upload intro audio**, with **TTS generated for all listed languages** as fallback, so that intro is consistent across languages without recording every language manually.
32. As a **TVS admin**, I want to **upload the active campaign document**, so that the bot mentions the correct scheme until I replace it.
33. As a **TVS admin**, I want to **upload knowledge-base documents** and click **Rebuild KB**, so that product answers stay current when specs or brochures change.
34. As a **TVS admin**, I want to **download captured leads as CSV**, so that I can import into spreadsheets or CRM later.
35. As a **TVS admin**, I want CSV columns to **match configured capture fields**, so that the export reflects what we actually ask.
36. As a **TVS admin**, I want an **admin test playground** using the same engine as production, so that I can validate config and KB before go-live.
37. As a **TVS admin**, I want **entry source tracking** (web, whatsapp, ricshow), so that marketing channels can be measured.
38. As a **sales operations user**, I want leads scored **HOT / WARM / COLD**, so that dealerships prioritize callbacks.
39. As a **developer**, I want **one conversation engine** shared by WhatsApp and web, so that behavior doesn't diverge across channels.
40. As a **developer**, I want **channel adapters** to handle only transport (Meta API, WebSocket, mic, TTS delivery), so that business logic lives in one place.
41. As a **developer**, I want qualification to use **Gemini File Search** for product facts, so that answers stay grounded in uploaded docs—not hardcoded specs.
42. As a **developer**, I want **Redis-backed session state** for WhatsApp, so that conversations survive async worker processing and rate limits apply.
43. As a **developer**, I want **webhook signature verification** on WhatsApp, so that forged messages are rejected in production.
44. As a **developer**, I want **duplicate message deduplication**, so that Meta redeliveries don't double-process leads.
45. As a **developer**, I want **PROFILE_JSON extraction** at wrap-up, so that lead capture is structured and strip-safe before sending to the customer.
46. As a **future platform owner**, I want the **admin config and KB model** to not block multi-tenant SaaS later, so that other OEM clients can be added without rewrite—even if v1 is TVS-only.

---

## Implementation Decisions

### 1. Single conversation engine (primary seam)

Replace the split between open Q&A WhatsApp bot and standalone qualification prototype with **one engine** responsible for:

- Session lifecycle (language selected, intro played, qualification in progress, completed)
- Turn handling: accept text or transcribed voice, produce text and optional audio
- Prompt assembly from admin config + campaign doc + File Search retrieval
- PROFILE_JSON capture and CSV persistence
- Off-topic and pricing guardrails

**Channel adapters** (WhatsApp worker, web WebSocket/HTTP, admin playground) call the engine with a normalized turn input and render the engine output. Adapters do not embed qualification logic.

*Prior art:* `qualify_prototype` POST `/chat` flow; `tasks.handle_message` + `rag.ask` for WhatsApp—merge qualification behavior into the engine, retire open Q&A as the default customer path.

### 2. Default qualification flow (prototype-derived)

Admin may reorder or extend steps; default flow:

```
LANGUAGE_PICK → INTRO → MODEL_INTEREST → CAMPAIGN_AWARENESS → TIMELINE
→ LOCATION (pincode; delivery city/area if out of town) → FEATURE_AWARENESS
→ DOCUMENTS (licence / permit / badge) → WRAP_UP → EMIT_PROFILE
```

- Skip a step if the user volunteers the answer earlier.
- Mid-flow product questions: answer in ≤2 sentences from KB, then resume current step.
- Ric Show / warm entry: **same full flow**; marketing "confirm interest" may be omitted as admin config, not a separate product.

From prototype—PROFILE_JSON contract at wrap-up only:

```json
{
  "lead_name": "",
  "product_interest": "",
  "purchase_timeline": "",
  "timeline_bucket": "immediate | <=30d | 30-90d | exploring",
  "pincode": "",
  "area": "",
  "district": "",
  "delivery_location": "",
  "feature_awareness": "high | low",
  "doc_license": "yes | no | unknown",
  "doc_permit": "yes | no | unknown",
  "doc_badge": "yes | no | unknown",
  "campaign_shown": "",
  "lead_quality": "HOT | WARM | COLD",
  "blockers": [],
  "next_step": "",
  "notes": ""
}
```

Output line format (stripped before customer sees it): `PROFILE_JSON:{...}`

Lead quality (default scoring, tunable later):

- **HOT** — near-term timeline (`immediate` or `<=30d`) AND usable location AND ≥2/3 docs yes
- **WARM** — interest with timeline OR location but docs missing, or `30-90d` timeline
- **COLD** — exploring, no timeline, or disengaged

### 3. Admin configuration store

JSON document (server-side file or Redis/DB—implementation choice) editable via admin API/UI, containing at minimum:

| Key | Purpose |
|-----|---------|
| `bot_name`, `welcome_text` | Branding |
| `languages[]` | Supported codes + display labels |
| `capture_fields[]` | Field id, prompt hint, required, order |
| `flow_steps[]` | Ordered step ids (maps to capture + fixed steps like campaign) |
| `voice_policy` | `always` / `intro_only` / `never` / `mirror_user` (reply with audio when user sent voice) |
| `intro` | Per-language text; optional uploaded audio URLs; TTS fallback flag |
| `campaign_text` | Active scheme body injected into system prompt |
| `entry_sources` | Optional per-source welcome overrides |

Changes take effect without redeploy. CSV header row derives from `capture_fields` + system columns (`timestamp`, `channel`, `source`, `session`, `language`).

### 4. Knowledge base

- **Source of truth:** Gemini File Search store(s)—extend existing indexing pipeline.
- **Launch content:** existing passenger 3W KB built from approved spec sheet.
- **Admin flow:** upload PDF/doc via admin page → manual **Rebuild KB** action triggers re-index (v1—not fully automatic on upload).
- **Answering rule:** specs and features ONLY from retrieved documents; if missing, say so and offer dealership follow-up. Never invent (e.g. wrong displacement).

### 5. Campaign awareness (required)

Admin-uploaded campaign text is **mandatory** for v1. Bot proactively mentions campaign during qualification (1–2 lines, campaign doc only). When campaign ends, admin replaces or clears doc—no redeploy.

### 6. Language handling

**WhatsApp:** interactive list (or buttons if ≤3 langs) before first qualification turn; lock conversation language unless user explicitly switches via admin-provided flow.

**Web:** detect `navigator.language` → suggest regional language with switch buttons; same supported set as WhatsApp.

**Voice language detection:** STT on incoming audio determines reply language; text replies and TTS use detected/locked session language.

### 7. Voice pipeline

| Step | Behavior |
|------|----------|
| Input (WhatsApp) | Download voice note → STT (Gemini or dedicated STT) |
| Input (web) | Browser MediaRecorder → upload/stream → STT |
| Output text | Always available |
| Output audio | TTS for all configured languages when policy allows; pre-uploaded intro audio preferred over TTS where provided |
| Admin | `voice_policy` controls speak vs text-only globally and per turn type |

Robotic TTS acceptable for v1 demo.

### 8. Location capture

- Primary: **pincode** (accept across multiple messages while LOCATION step is open).
- Fallback: city/area text if pincode unknown.
- **Out of town:** additional field `delivery_location` — where customer wants the vehicle, not necessarily home pincode.
- WhatsApp native location share: **out of v1 scope** (pincode + text only).

### 9. Pricing and scope guardrails

- **Pricing / EMI / down payment:** always defer to dealership; ranges only if explicitly in KB or campaign doc.
- **Off-topic:** gentle redirect to TVS passenger 3-wheelers and KB scope.
- **Badge:** dealership guides; RTO issues badge—no over-promise.

### 10. Channels and entry

| Channel | Entry | Notes |
|---------|-------|-------|
| WhatsApp | Meta Cloud API webhook | Language list, text + voice in/out, interactive messages |
| Public web | Embedded chat page | Locale hint, mic, WebSocket or HTTP chat |
| Ric Show | QR/link with `source=ricshow` | Same bot; analytics only—not access gate |
| Admin playground | Password/token-protected | Same engine; config/KB testing |

### 11. Lead storage (v1)

Append-only **CSV** on server; admin download endpoint. One row per completed qualification. Include `channel`, `source`, `wa_id` or web `session` id.

CRM, email alerts, dealership API: **out of scope v1**.

### 12. WhatsApp transport extensions

Extend WhatsApp helper layer beyond `send_text` to support:

- Interactive list / reply buttons (language picker)
- Inbound audio message download and handling
- Outbound audio message upload/send (TTS output)
- Existing: mark read, signature verify, text split at 4096 chars, retries

### 13. Session state

- **WhatsApp:** Redis keys for history, language lock, qualification progress pointer, dedup, rate limit—extend existing memory module patterns.
- **Web:** browser holds display history; server holds session state keyed by session id (Redis recommended for parity).

### 14. Consolidation of existing apps

- Production webhook app becomes qualification bot (not default open Q&A).
- RAG playground (`web.py`) remains or merges: admin/KB tooling + optional dev RAG test; **customer-facing qualification UI** replaces or sits alongside playground per unified design.
- `qualify_prototype.py` logic absorbed into engine; prototype may remain temporarily as reference until parity tests pass.

### 15. Security

- Admin endpoints gated by `ADMIN_TOKEN` (existing pattern).
- Public web chat: optional HTTP Basic Auth for playground; public embed unauthenticated.
- `APP_SECRET` required in production for webhook verification.

---

## Testing Decisions

### What makes a good test

Test **external behavior** at the **conversation engine seam**—given admin config, session state, and a user turn, assert:

- Reply text (and whether audio is requested) matches policy
- Qualification progresses correctly through steps
- PRODUCT questions mid-flow produce KB-grounded short answers then resume qualification
- Off-topic input produces redirect, not hallucination
- Pricing questions defer to dealership
- Wrap-up emits valid PROFILE_JSON and triggers CSV row append
- Language lock respected after picker

Do **not** test Gemini prompt string literals, internal Redis key formats, or Meta HTTP payload shapes in unit tests—mock the LLM and external IO at the engine boundary.

### Primary test target

**Conversation engine** — highest seam; one mock boundary for LLM+retrieval, one for config load.

### Secondary integration tests

- HTTP POST chat endpoint (web adapter)—prior art: `qualify_prototype` `/chat`
- CSV writer appends correct columns for dynamic admin fields
- PROFILE_JSON strip never leaks to simulated customer payload

### Prior art in repo

- `test_rag.py` — terminal RAG validation (retrieval behavior)
- `qualify_prototype.py` — language pick, `/chat`, PROFILE_JSON capture, leads.csv
- Manual webhook testing documented in README

### Suggested test scenarios (minimum)

1. Language pick → intro → first qualification question
2. Mid-flow "CNG vs petrol?" → brief answer → next qualification question
3. "What's the EMI?" → dealership deferral
4. Off-topic "who won the cricket?" → gentle redirect
5. Full flow → PROFILE_JSON → CSV row with HOT/WARM/COLD
6. Voice policy `intro_only` → text reply after user voice message
7. Out-of-town user → `delivery_location` captured
8. Admin adds field to config → CSV header includes new column on next lead

---

## Out of Scope

- Multi-tenant SaaS (multiple OEM clients with isolated config) — v1 is TVS-first; data model should not foreclose later
- Cargo 3W, 2W, 4W product lines at launch
- CRM integration (Salesforce, Zoho, etc.)
- Automated EMI / loan calculator
- WhatsApp location-share → reverse geocode to pincode
- Hard access gate (Ric Show-only bot)
- Automatic KB re-index on every upload (v1 = manual Rebuild KB)
- Per-source completely different qualification flows (admin can customize order/fields; separate flows are later)
- 24h+ WhatsApp template messaging strategy (document constraint; templates not built in v1)
- IP-based geolocation on web

---

## Further Notes

- Existing `docs/LEAD_QUALIFICATION_BOT_SPEC.md` remains useful background; this spec supersedes it for v1 scope including voice, admin config breadth, and single-engine architecture.
- Run `/setup-matt-pocock-skills` to finalize issue tracker docs if publishing via `gh` CLI.
- **Testing seam for user confirmation:** all behavioral tests should target the **conversation engine** public turn API—not individual channel handlers. Channel adapters get thin smoke tests only.
- Gemini model and File Search store selection may follow existing `config.py` / admin page patterns.
- Consider keeping a dev-only open Q&A mode behind admin flag for KB debugging—not customer default.

---

## Testing Seam (confirm before implementation)

**Proposed primary seam:** `ConversationEngine.handle_turn(session, turn_input) -> turn_output`

| Layer | Responsibility | Test depth |
|-------|----------------|------------|
| **Conversation engine** | Qualification, RAG, voice policy, PROFILE_JSON, guardrails | **Full behavioral test suite** |
| **Admin config loader** | Load/validate JSON config | Unit tests |
| **CSV lead writer** | Append row from profile | Unit tests |
| **WhatsApp adapter** | Webhook → engine → Meta send | Smoke / manual |
| **Web adapter** | WebSocket/mic → engine → UI | Smoke / manual |
| **TTS/STT providers** | Audio transcoding | Mocked in engine tests |

Does this seam match your expectations? If yes, implementation proceeds at the engine boundary first, then wires adapters.

# Pre-Lead Qualification & Profiling Bot — Spec

**Purpose:** This bot is NOT a deep Q&A / financing assistant. Its job is **pre-lead
qualification and customer profiling** — replicate what a TVS tele-calling agent does
on a call: confirm interest, make the customer aware of active campaigns, capture a
structured profile, gauge lead quality, and hand a clean lead to the dealership.

**Scope:** All TVS **passenger** three-wheelers (per the existing KB):
- TVS King EV MAX (electric)
- TVS King Deluxe (petrol / CNG / LPG, 200cc)
- TVS King Duramax Plus (petrol / CNG, 225.8cc liquid-cooled)

Modelled on a real Marathi call (King Duramax Plus inquiry, lead "Pradip Tiwari",
Shirur / Pune).

**Channel:** Final target is **WhatsApp** (Meta Cloud API). The web playground is
used for testing the same logic. Everything below is written so the *conversation
logic is channel-independent*; only the input/output widgets differ (see §7).

---

## 1. Design principles

1. **Profile first, answer second.** Every turn moves toward completing the profile.
   Product questions get a brief answer, then steer back to qualification — exactly
   what the human agent did (he kept returning to timeline / location / documents).
2. **One question at a time, conversational.** Never dump a form in chat. Ask,
   acknowledge, ask the next field.
3. **Language-first, via a tick-form.** The first interaction is a selectable
   language picker (WhatsApp interactive list / web radio buttons), not free text.
   Lock every later reply to the chosen language.
4. **Campaign awareness.** Proactively tell the customer about any currently-active
   campaign (e.g. the "Vaada" scheme) — like the agent did — using the admin-uploaded
   campaign document as the source.
5. **Skip pleasantries.** No long scripted name intro; get to qualification.
6. **Be accurate.** Pitch features ONLY from the knowledge base (§5). Never invent
   specs. (The agent said "25cc"; the King Duramax Plus is 225.8cc — the KB is right.)
7. **Don't over-promise.** A commercial driver's BADGE is RTO-issued; the dealership
   GUIDES, it does not "get it done."
8. **Defer pricing.** Down payment / EMI / on-road price → "the dealership shares
   exact figures." Give a published range only if the KB/campaign doc contains one.

---

## 2. Conversation flow (state machine)

```
[START]
  -> ASK_LANGUAGE         tick-form: English / मराठी / हिंदी / தமிழ்  (extensible)
  -> CONFIRM_INTEREST     which TVS passenger model are they interested in
  -> CAMPAIGN_AWARENESS   briefly mention the active campaign (from admin doc)
  -> TIMELINE             when do they want to buy / take delivery
  -> LOCATION             pincode (may arrive across several messages); if unknown,
                          ask city/area OR request WhatsApp location share
  -> FEATURE_AWARENESS    "do you know the features?" -> if low, short accurate pitch
  -> DOCUMENTS            license / permit / badge status (commercial 3W)
  -> WRAP_UP              summarize, set disposition, promise dealership follow-up
  -> EMIT_PROFILE         append the lead row to the CSV store
```

- Skip a step if the user volunteers it earlier.
- If the user asks a question mid-flow, answer in <=2 sentences, then resume.
- **The captured questions/fields are admin-configurable** (§6). The flow above is the
  default; admins can add/remove fields without code changes.

---

## 3. Lead profile schema (one CSV row per conversation)

The CSV the admin downloads has **questions/fields as columns, one lead per row**.
Default columns:

| Column | Meaning |
|--------|---------|
| `timestamp` | when the chat completed |
| `channel` | whatsapp / web |
| `wa_id` / `session` | WhatsApp number or web session id |
| `lead_name` | if given |
| `language` | chosen in the tick-form |
| `product_interest` | which passenger model |
| `purchase_timeline` | free text (e.g. "22nd this month") |
| `timeline_bucket` | immediate / <=30d / 30-90d / exploring |
| `pincode` | captured (possibly across messages) |
| `area` / `district` | if derived or given |
| `feature_awareness` | high / low |
| `doc_license` | yes / no / unknown |
| `doc_permit` | yes / no / unknown |
| `doc_badge` | yes / no / unknown |
| `campaign_shown` | which campaign was mentioned |
| `lead_quality` | HOT / WARM / COLD |
| `blockers` | e.g. "no badge" |
| `next_step` | routing note |
| `notes` | anything else useful |

### Lead-quality scoring (tune later)
- **HOT** — near-term timeline (immediate / <=30d) AND usable location AND >=2/3 docs.
- **WARM** — interested with timeline OR location but docs missing, or 30–90 day timeline.
- **COLD** — "just exploring", no timeline, or unwilling.

(Source call → HOT.)

---

## 4. System prompt (drop-in for rag.py SYSTEM)

```
You are TVS Motor's pre-lead qualification assistant for TVS PASSENGER three-wheelers
(King EV MAX, King Deluxe, King Duramax Plus).

YOUR GOAL is NOT to answer every question in depth. Your goal is to QUALIFY and
PROFILE the lead in a short, friendly chat, mention any active campaign, then hand
them to the dealership.

RULES
1. Language is chosen by the customer via a picker before the chat. Conduct the
   ENTIRE conversation in that chosen language.
2. Qualify the lead by collecting, ONE QUESTION AT A TIME, in a natural tone
   (acknowledge each answer before the next):
     a. Which TVS passenger model they are interested in.
     b. (Proactively) make them aware of the current campaign from the CAMPAIGN
        section provided to you — one or two lines, only what is in that section.
     c. When they want to buy / take delivery (timeline).
     d. Their pin code (to route to the nearest dealership). The pin code may come
        across several messages; accept it whenever it arrives. If they don't know
        it, ask for their city/area instead (or accept a shared location).
     e. Whether they already know the vehicle's features. If not, give a SHORT
        accurate pitch from the KNOWLEDGE BASE — max ~5 points.
     f. Whether they have a driving LICENSE, a PERMIT, and a BADGE.
3. Keep every reply short and clear (chat / WhatsApp).
4. Do NOT quote a down payment, EMI, or on-road price. Say the dealership shares
   exact figures. Give a range only if it appears in the documents/campaign.
5. Never invent specifications. Use ONLY the knowledge base. If a detail is missing,
   say so and offer dealership follow-up.
6. Do not over-promise. A commercial BADGE is issued by the RTO; the dealership can
   GUIDE, it cannot complete it for the customer.
7. When you have enough info (or the user wants to stop), WRAP UP: briefly confirm
   what you captured, say the nearest dealership will contact them, and thank them.
8. Be respectful and patient; never pressure the customer.

After the customer-facing wrap-up, on a NEW final line output the captured fields as
a single JSON object prefixed with `PROFILE_JSON:` using the schema provided. The
app strips this line before sending to the customer and writes it to the CSV.
```

---

## 5. Knowledge base = source of truth (already built)

The bot pitches from the existing KB — **no new spec doc needed**:
- `build_tvs_3w_kb.py` → `tvs_three_wheelers_kb.pdf` — full, accurate passenger +
  cargo specs (King Duramax Plus correctly = 225.8cc, gradeability 12°, etc.).
- Indexed into Gemini File Search (the bot already retrieves from it via `rag.ask`).

**Action:** keep the KB as the single source of truth for specs/features. If any spec
is wrong/outdated, fix it in `build_tvs_3w_kb.py` and re-index — do NOT hardcode specs
in the prompt.

---

## 6. Admin-configurable inputs (no code change to update)

Two things the admin manages from the admin page:

1. **Capture questions / fields** — the list of fields the bot must collect (the CSV
   columns). Stored as a small JSON/list on the server. Editing it changes what the
   bot asks and what the CSV contains. Ships with the §3 default set.
2. **Active campaigns document** — admin uploads the current campaign text (e.g. the
   "Vaada" scheme: 2-yr warranty, 3 free services, 1-yr RSA, ₹10L accident cover,
   ₹1L/child education, ₹4,000/day hospitalization ×30, ₹5,000 ambulance). The bot
   injects this into the prompt's CAMPAIGN section so it can make customers aware.
   When a campaign ends, the admin replaces/clears the doc — no redeploy.

**CSV export:** captured leads are appended to a server-side CSV
(`leads.csv`), downloadable from the admin page (e.g. `GET /admin/leads.csv`).
Questions = columns, leads = rows.

---

## 7. Channel specifics

### WhatsApp (final target)
- **Language tick-form** → WhatsApp **interactive list message** (up to 10 rows) or
  reply buttons (max 3). For 4+ languages use a list. New helper needed in
  `whatsapp.py` (currently only `send_text` exists), e.g. `send_interactive_list`.
- **Location** → you CANNOT use IP geolocation on WhatsApp (messages come via Meta's
  servers, not the user's IP). The clean options are:
  1. Ask the user to type their **pin code** (default).
  2. If unknown, ask for **city/area**, OR send a **location-request** message so the
     user taps "Share location"; WhatsApp returns lat/long which you reverse-geocode
     to a pincode.
- **Multi-message pincode**: keep the LOCATION step "open" — accept a 6-digit pincode
  whenever it appears in any later message, even after moving on.

### Web playground (testing)
- Language tick-form → simple radio buttons / a small form before the chat starts.
- Location → text input; no location-share widget needed for testing.

---

## 8. Worked example — what the source call would produce

```json
{
  "lead_name": "Pradip Tiwari",
  "language": "Marathi",
  "product_interest": "TVS King Duramax Plus",
  "purchase_timeline": "22nd (current month)",
  "timeline_bucket": "<=30d",
  "pincode": "412210",
  "area": "Shirur",
  "district": "Pune",
  "feature_awareness": "low",
  "doc_license": "yes",
  "doc_permit": "yes",
  "doc_badge": "no",
  "campaign_shown": "Vaada scheme",
  "lead_quality": "HOT",
  "blockers": ["No commercial badge yet"],
  "next_step": "Route to nearest Shirur/Pune dealership; dealership to guide on badge",
  "notes": "Customer asked about down payment; deferred to dealership."
}
```

---

## 9. Decisions locked / still open

**Locked (from product owner):**
- Languages: open-ended; launch/test set = English, Marathi, Hindi, Tamil; presented
  as a tick-form picker.
- Specs source of truth: the existing KB (`build_tvs_3w_kb.py`). All passenger models.
- Location: capture pincode (multi-message ok); fall back to city/area; WhatsApp
  location-share possible. No IP geolocation.
- Storage: server-side CSV, admin-downloadable (questions=columns, leads=rows).
- Campaigns: admin uploads the active-campaign doc; bot makes customer aware.
- Admin can edit the capture-questions list.

**Still open (small):**
- Reverse-geocoding provider for shared WhatsApp locations (only if we enable
  location-share) — or just store raw lat/long for the dealership.
- Exact campaign text for launch (admin will upload).
- Do we also want a per-language greeting line shown above the picker?
```

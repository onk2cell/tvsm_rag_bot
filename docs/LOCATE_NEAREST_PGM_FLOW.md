# Locate Nearest PGM — deterministic flow (initial)

Branch: `feature/locate-nearest-pgm` (based on `feature/vehicle-crud` @ `4a30553`).

## What the customer sees

```text
customer   →  Hi
bot        →  Welcome to the TVS Passenger 3W Assistant. Which language do you prefer? 1–7
customer   →  3                                  (Marathi)
bot        →  तुम्हाला अजूनही वाहनात रस आहे का, की तुम्ही जवळचे PGM शोधत आहात?
              वाहनासाठी 1 दाबा / जवळच्या PGM साठी 2 दाबा
customer   →  1                                  →  existing vehicle flow, unchanged
              (still-interested for returning customers, then qualification)
customer   →  2                                  →  locate-nearest-PGM flow
bot        →  नक्की — मी तुम्हाला जवळचे PGM शोधण्यात मदत करेन.
              <share-location how-to image>
              कृपया ... तुमचे WhatsApp करंट लोकेशन शेअर करा, किंवा तुमचा ६-अंकी पिनकोड टाइप करा.
```

The routing question is sent in the language just chosen, in all seven menu
languages. A reply that is not a clear choice is asked again; nothing is
guessed by a model. Once in the PGM flow, no later turn reaches the LLM
qualification path.

The PGM flow body is intentionally only the entry (ask for location, keep a
typed pincode). What a PGM is, how the nearest one is looked up and what is
sent back are a separate requirement and slot into `_handle_pgm_turn`.

## Commits

| Hash | Message |
|------|---------|
| `50b5ded` | Ask vehicle or nearest PGM right after the language menu |
| _(the commit adding this file)_ | Document the locate-nearest-PGM routing |

## Code changes

### `client_flow_intent.py` — new file (50 lines)

| Lines | Change |
|-------|--------|
| 10–11 | `FLOW_VEHICLE = "vehicle"`, `FLOW_PGM = "pgm"` — the two values `ClientSession.flow` can take once routed. |
| 14 | `_OPTION_RE` — accepts `1`, `2`, `1.`, `2)`, `option 2`. |
| 16 | `_PGM_RE` — `pgm` / `p.g.m` (word-bounded) plus the acronym in Devanagari, Telugu, Tamil, Kannada and Malayalam script. |
| 18–29 | `_VEHICLE_RE` — vehicle / gaadi / auto / rickshaw / product names, plus "vehicle"/"auto" in the five native scripts. |
| 32–50 | `parse_flow_intent(text) -> str` — a numbered option decides outright; otherwise a message naming only one side wins; naming both, or neither, returns `""`. |

**Note.** Deterministic by design, mirroring `client_language.parse_language_choice`.
No LLM classifier: an unclear reply is re-asked. Kept in its own module so
`client_processing.py` does not grow another regex table.

### `client_static_messages.py`

| Lines | Change |
|-------|--------|
| 289–333 | `_FLOW_INTENT_ASK` — the routing question with "Press 1 / Press 2", in English, Hindi, Marathi, Telugu, Tamil, Kannada, Malayalam. |
| 335–345 | `_PGM_FLOW_INTRO` — one-line PGM lead-in, same seven languages. |
| 378–379 | Registered as `flow_intent_ask` and `pgm_flow_intro` in `MESSAGE_DEFAULTS`. |
| 581–587 | Accessors `flow_intent_ask(language)` and `pgm_flow_intro(language)`. |

**Note.** Registering in `MESSAGE_DEFAULTS` is what makes both messages
appear in `GET /admin/api/messages` and overridable per language through
`config["messages"]` with no further wiring. All seven languages are supplied
(the file otherwise carries EN/HI/MR) because this is the first thing the
customer reads in the language they just picked. The PGM intro is followed by
the existing `share_location_ask` rather than carrying its own location
wording, so the two flows ask for location in identical words. Neither
message has placeholders.

### `client_processing.py`

| Lines | Change |
|-------|--------|
| 23, 61, 68 | Import `FLOW_PGM`, `FLOW_VEHICLE`, `parse_flow_intent`, `flow_intent_ask`, `pgm_flow_intro`. |
| 278–282 | `ClientSession` gains `awaiting_flow_intent: bool` and `flow: str` (`""` until answered). |
| 437 | `was_awaiting_language` captured before `_resolve_language`, so the turn that answers the language menu is identifiable. |
| 490–505 | `choice_text` hoisted (it was computed later, twice); if `was_awaiting_language`, send the routing ask via `_ask_flow_intent` and return — before still-interested and before any engine turn. |
| 507–514 | `if session.flow == FLOW_PGM:` dispatch to `_handle_pgm_turn` and return. Every later turn in the PGM flow stops here. |
| 518 | Location-event branch gated with `and not session.awaiting_flow_intent`, so a pin sent instead of "1/2" is re-asked, not handed to the dealer lookup. |
| 550–555 | Voice-note language-switch check skipped while the routing ask is pending. |
| 557–567 | `_apply_flow_intent` runs on the pending ask (after `_message_for_event`, so a transcribed voice note is parsed too). `None` means the turn ended there; a string is the seed message for the vehicle flow. |
| 570–581 | The language-only-reply block now calls `_qualification_start_message` and is additionally gated on `not session.flow`. In production the routing ask sits between the menu and this block and seeds the message itself; the block remains for sessions that were never routed (tests pre-select a language). |
| 585 | Still-interested reuses the hoisted `choice_text`. |
| 1197–1224 | `_ask_flow_intent` — sets `awaiting_flow_intent`, clears `flow`, sends the localized ask, saves. Used for the first ask and every re-ask. Not added to `session.history` (see note). |
| 1226–1271 | `_apply_flow_intent` — vehicle → clear flag, `flow = "vehicle"`, return the qualification seed; PGM → clear flag, `flow = "pgm"`, send share-location image (no caption) + `pgm_flow_intro` + `share_location_ask`, complete the turn, return `None`; else re-ask, return `None`. |
| 1273–1286 | `_qualification_start_message(customer, language)` — extracted verbatim from the old inline block so the vehicle route and the legacy path produce the same engine message (including the unknown-CRM "ask their name first" variant). |
| 1288–1324 | `_handle_pgm_turn` — the PGM flow body. Text: `_capture_pincode`, reply `location_thanks` if a pincode was present else `share_location_ask`. Location pin: reply `location_thanks` if coordinates parse. Never calls the engine, still-interested or dispose. The extension point for the pending PGM requirements. |
| 2405–2415 | `_resolve_language` mid-chat switch also skipped while `awaiting_flow_intent` — bare "1" is English in the language menu and was flipping a Marathi customer to English. |

**Notes.**

- The ask and its re-asks are recorded as interactions (`_reply_and_record`)
  but not appended to `session.history`, exactly as the language menu is:
  the model never needs to see menu exchanges, and
  `_maybe_offer_still_interested` fires only on an empty history, so the
  returning-customer still-interested ask still runs after option 1.
- Anything typed alongside the language choice ("2, king ev max price?")
  does not reach the LLM — the routing ask replaces it. This is the same
  trade the language menu already makes with the message that triggers it.
- The digit guard in `_resolve_language` is the same guard still-interested
  already needed for the same reason.

### `client_adapters.py`

| Lines | Change |
|-------|--------|
| 577–580 | `RedisClientState.load_or_start` reads `awaiting_flow_intent` and `flow`. |
| 625–626 | `RedisClientState.save` writes them. |

**Note.** Session fields are hand-listed here rather than round-tripped
generically; `test_client_state_round_trips_every_session_field` fails if a
`ClientSession` field is added without both halves.

## Tests

### `tests/test_client_flow_intent.py` — new file

Parametrised: vehicle replies (digit, English, Hinglish, product names, five
native scripts), PGM replies (digit, `pgm`, `P.G.M`, Devanagari), and unclear
replies (`yes`, `no`, `3`, `Hindi`, both sides named) that must return `""`.

### `tests/test_client_static_messages.py`

| Lines | Change |
|-------|--------|
| 33–35 | `_ALL_LANGUAGES` — the seven menu languages. |
| 38–49 | Routing ask is distinct per language, mentions PGM and both options. |
| 52–57 | PGM intro is distinct per language. |
| 60–78 | Both messages honour a `config["messages"]` override. |

### `tests/test_client_processing.py`

| Lines | Change |
|-------|--------|
| 13 | Import `flow_intent_ask`. |
| 784–796 | `test_missing_language_menu_then_choice_starts_qualification` — answers the routing ask with "1" before asserting the engine turn; asserts the ask was sent in Hindi. |
| 812–846 | `test_returning_customer_chooses_language_then_gets_welcome_back` — same: "1" for vehicle, then still-interested is asserted as before. |
| 2048–2078 | `test_still_interested_digit_reply_does_not_flip_language_choice` — now also covers bare "1" answering the routing ask in Marathi. |
| 2293–2302 | `_fresh_new_lead` — unknown-CRM number walked to the routing ask in Marathi. |
| 2305–2316 | Ask is sent in the chosen language; no engine turn; history stays empty. |
| 2319–2331 | "1" → `flow == "vehicle"`, language still Marathi, engine seeded with the unknown-CRM start message. |
| 2334–2352 | "2" → `flow == "pgm"`, no engine turn, intro + Marathi location ask + caption-less image, turn in history. |
| 2355–2364 | Unclear reply → same ask again, flag still set. |
| 2367–2391 | Location pin while pending → re-asked; dealer directory not called. |
| 2394–2418 | PGM-flow turns: no engine, no still-interested; pincode captured and acknowledged. |
| 2421–2443 | Returning customer: routing ask, then "1", then the still-interested ask in Hindi. |
| 2446–2452 | Both new session fields exist on `ClientSession`. |

Suite: 491 passed, 9 failed — the same 9 failures as before this change
(`test_230707_*`, `test_distance_is_shown_on_the_dealer_card`,
`test_250703_conversation_restarts_after_wrap_up`,
`test_pincode_message_asks_nearest_dealer_confirm_once`,
`test_crm_dealer_confirm_yes_sets_last_dealer_code_and_skips_nearest`), all
pre-existing and unrelated.

## Operating notes

- Both messages are editable live at `PUT /admin/api/messages/flow_intent_ask`
  and `/pgm_flow_intro` per language; no restart.
- `share_location_ask` and `location_thanks` — reused by the PGM flow — only
  have EN/HI/MR built in. A Telugu/Tamil/Kannada/Malayalam customer gets the
  PGM intro in their language followed by the English location ask until an
  operator supplies those translations (existing gap, unchanged here).
- The share-location image needs `CLIENT_MEDIA_BASE_URL` (or
  `share_location_image.url` in config); without it the text is sent alone,
  as in the vehicle flow.
- Dispose is not called anywhere in the PGM flow. Whether a PGM enquiry
  should reach CRM, and as what, is part of the pending requirement.

## Open for the PGM requirements

`_handle_pgm_turn` (`client_processing.py:1288`) is the single place to
extend. It already has the language, the typed pincode (in
`lead_profile["pincode"]`) and, for a shared pin, the parsed coordinates from
`extract_coordinates(event)`. Lookup, result card and any follow-up question
go after the location capture there.

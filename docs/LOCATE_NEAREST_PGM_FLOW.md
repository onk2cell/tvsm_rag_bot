# Locate Nearest PGM — routing, location and the nearest-PGM list

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
              कृपया तुमचे WhatsApp करंट लोकेशन शेअर करा, तुमचा ६-अंकी पिनकोड टाइप करा,
              किंवा ज्या शहर/एरियामध्ये तुम्हाला सर्व्हिस सेंटर पाहायचे आहे त्याचे नाव टाइप करा.

customer   →  Vidyaranyapura                     →  Gemini + Google Search → 560097 → geocode
   — or —   560097                             →  geocode (Nominatim, cached)
   — or —   📍 location pin                    →  coordinates used as-is
bot        →  पिनकोड 560097 जवळचे PGM:

              1. Anees Auto Works — VIDYARANYAPURA (0.3 km)
                 फोन: 8722574132
              2. NAYEEM — Adityanagar (1.1 km)
                 फोन: 9886427865
              3. palya garage — Kanteerava Studio (1.4 km)
                 फोन: 8892467219

              पत्ता आणि नकाशा लिंकसाठी 1, 2 किंवा 3 पाठवा, किंवा पुन्हा शोधण्यासाठी
              दुसरे लोकेशन किंवा पिनकोड पाठवा.
customer   →  1
bot        →  नाव: Anees Auto Works
              पत्ता: VIDYARANYAPURA AMS LAYOUT BANGALORE 560097
              फोन: Ajaz - 8722574132
              नकाशा: https://maps.google.com/?q=13.083038,77.5506637
   — or —
customer   →  Xyzzy Nagar                        →  search says NOT_FOUND
bot        →  त्या ठिकाणाचा पिनकोड सापडला नाही. कृपया जवळच्या मोठ्या शहराचे ... नाव टाइप करा ...
   — or —
customer   →  411001                             →  geocodes to Pune; nothing within 50 km
bot        →  माफ करा, त्या ठिकाणापासून 50 किमीच्या आत सध्या कोणतेही PGM नोंदलेले नाही. ...
```

The routing question is sent in the language just chosen, in all seven menu
languages. A reply that is not a clear choice is asked again; nothing is
guessed by a model. Once in the PGM flow, no later turn reaches the LLM
qualification path.

Inside the PGM flow the customer's typed reply goes through a LangGraph
graph (`bot/pgm_graph.py`):

```text
START ─┬─ has a 6-digit pincode ────────────────────────────→ pincode
       ├─ filler ("ok", "?", bare number) ──────────────────→ unclear  → ask again
       └─ place name ──→ search_web (Gemini + Google Search) ─┬─ pincode in answer → pincode
                                                             ├─ NOT_FOUND         → not_found     → ask bigger city
                                                             └─ call raised       → lookup_failed → ask for pincode
```

A WhatsApp location pin never enters the graph — its coordinates are exact
and go straight to the search.

Once a location is known, `pgms.PgmDirectory` ranks every garage in
`data/pgms.json` by haversine distance and returns the closest three within
50 km. A typed or searched pincode is geocoded first through the same
Nominatim geocoder (and cache file) the dealer flow uses; a pincode the
geocoder cannot place gets `pgm_pincode_unresolved`, an empty result gets
`pgm_none_nearby`. The list's DMS ids are kept in `session.pgm_candidates`
so that a bare `1`–`3` on the next turn opens that garage's card (name,
address, owner + phone, map link); the list stays live for further picks
until the next search replaces it. Filler typed while a list is on screen
gets the list's footer, not the opening location question.

The dataset is the `Overall PGMs BNLR` sheet of the client's network
workbook (`data/pgm_network_bnlr.xlsx`, dated 25.07.2026, not committed —
same as the dealer CSV), built into `data/pgms.json` by
`scripts/build_pgms.py`. Only that sheet: the dealer service centre, DASC,
IASC and APS sheets are other outlet types.

## Commits

| Hash | Message |
|------|---------|
| `50b5ded` | Ask vehicle or nearest PGM right after the language menu |
| `8c0aff5` | Document the locate-nearest-PGM routing |
| `476f58a` | Resolve a typed place name to a pincode in the PGM flow |
| `ff94afa` | Document the PGM location step |
| _(the commit adding this section)_ | List the three nearest PGMs and open one on a pick |

## Code changes

### `scripts/build_pgms.py` — new file

| Function | Change |
|----------|--------|
| `COLUMNS` | Header text → field. `Garage Name` becomes `name`, the sheet's `Name` (the owner) becomes `owner_name`, blanked when it repeats the garage name. |
| `parse_coordinate` | Numbers, numbers-in-strings with stray commas / non-breaking spaces; `x`, blanks and out-of-India values (a `long` of `77569063`) are `None`. |
| `map_url_for` | The sheet's own `maps.app.goo.gl` link when present, else `https://maps.google.com/?q=lat,lon`. |
| `build_pgms` | Drops rows with unreadable coordinates or no name and reports each on stderr. |
| `far_from_the_rest` | Reports (keeps) garages more than `--far-km` (100) from the median garage — a "Bengaluru" garage at Pune coordinates is a mistyped cell, but that is the client's call. |

Current build: 1134 rows → 1131 kept, 3 dropped, 4 flagged (see
"Data issues" below).

### `pgms.py` — new file

| Lines | Change |
|-------|--------|
| `Pgm` | Frozen dataclass: `dms_id, name, phone, address, area, map_url, latitude, longitude, owner_name, distance_km`. |
| `PgmDirectory(pgms=None, *, pgms_path, geocoder, limit=3, max_km=50)` | Loads `data/pgms.json`; rows without coordinates are ignored. |
| `find_nearest_by_coords` | Every garage ranked by `dealers.haversine_km`, then the top `limit` that are within `max_km`. Returns a list, possibly empty. |
| `find_nearest_by_pincode` | Geocodes via the injected `NominatimPincodeGeocoder`; `None` when the pincode does not geocode, as distinct from `[]` (geocoded, none in range). |
| `get_by_id` | For the pick. |

**Note.** Built on `dealers.py`'s geocoder and haversine rather than a copy.
In `client_tasks.py` one `NominatimPincodeGeocoder` is shared by both
directories: each instance owns the `data/pincode_geocode_cache.json`
file and two writers would overwrite each other's entries.

### `client_flow_intent.py` — new file

| Lines | Change |
|-------|--------|
| 10–11 | `FLOW_VEHICLE = "vehicle"`, `FLOW_PGM = "pgm"` — the two values `ClientSession.flow` can take once routed. |
| 14 | `_OPTION_RE` — accepts `1`, `2`, `1.`, `2)`, `option 2`. |
| 16 | `_PGM_RE` — `pgm` / `p.g.m` (word-bounded) plus the acronym in Devanagari, Telugu, Tamil, Kannada and Malayalam script. |
| 18–29 | `_VEHICLE_RE` — vehicle / gaadi / auto / rickshaw / product names, plus "vehicle"/"auto" in the five native scripts. |
| 32–50 | `parse_flow_intent(text) -> str` — a numbered option decides outright; otherwise a message naming only one side wins; naming both, or neither, returns `""`. |
| `_PICK_RE`, `parse_list_pick(text, count)` | A bare number (`2`, `2.`, `option 2`, `no. 2`) within `1..count`, else `0`. `2 more` and pincodes are not picks; a number past the end is nothing, not clamped. |

**Note.** Deterministic by design, mirroring `client_language.parse_language_choice`.
No LLM classifier: an unclear reply is re-asked. Kept in its own module so
`client_processing.py` does not grow another regex table.

### `gemini_setup.py` — new file (39 lines)

| Lines | Change |
|-------|--------|
| 14 | `DEFAULT_MAX_CHARS = 600` — cap on the returned answer. |
| 17–33 | `grounded_search(query, *, max_chars)` — `rag.get_client().models.generate_content` on `MODEL_FAST` with `tools=[Tool(google_search=GoogleSearch())]`, `temperature=0`; returns the stripped text cut to `max_chars`. |
| 36–39 | `search_web` — the LangChain `@tool` wrapper, `search_web.invoke({"query": ..., "max_chars": ...})`. |

**Note.** Built on the bot's shared Gemini client rather than a second one,
so the runtime key an operator sets on the admin page applies here with no
restart. The plain function is kept separate from the `@tool` so tests can
fake the client without going through `invoke()`.

### `bot/pgm_graph.py` — new file (150 lines)

| Lines | Change |
|-------|--------|
| 37–38 | `SEARCH_MAX_CHARS = 400` (the answer is one line; below `search_web`'s 600 default), `NOT_FOUND_TOKEN`. |
| 41–50 | `search_query(place)` — the prompt: PIN code of the place (main/GPO one if several), reply `"411001 Pune"` style, or exactly `NOT_FOUND`. |
| 52–56 | `default_search(query)` — `search_web.invoke(...)` with the PGM cap. |
| 61–66 | `looks_like_place(text)` — ≥ 3 chars and at least one letter in any script; filters filler so it is re-asked, not searched. |
| 69–73 | `PgmLocationState` — `user_message`, `search_result`, `pincode`, `result`. |
| 76–110 | Nodes: `_route` (pincode / unclear / search), `_typed_pincode`, `_unclear`, `_search` (calls the injected search, maps the answer to `pincode` / `not_found` / `lookup_failed`). |
| 113–122 | Graph wiring: `START` → conditional → each node → `END`. |
| 125–150 | `PgmLocation` result dataclass and `resolve_pgm_location(user_message, *, search=None)` — the entry point; `search` rides in `RunnableConfig["configurable"]["search"]`. |

**Notes.**

- Same discipline as `bot/graph.py`: the graph decides, `client_processing`
  does the side effects (session writes, reply text).
- `lookup_failed` and `not_found` are kept apart on purpose. An exception
  means we could not look — the place may be real — so the customer is
  asked for a pincode, not sent hunting for a bigger city.
- No LangGraph checkpointer; the RQ worker is stateless per job and the
  session is already in Redis.

### `client_static_messages.py`

| Lines | Change |
|-------|--------|
| 289–333 | `_FLOW_INTENT_ASK` — the routing question with "Press 1 / Press 2", in English, Hindi, Marathi, Telugu, Tamil, Kannada, Malayalam. |
| 335–345 | `_PGM_FLOW_INTRO` — one-line PGM lead-in, same seven languages. |
| 346–381 | `_PGM_LOCATION_ASK` — location pin / pincode / **name of the city or area where they want the service centre**. |
| 383–393 | `_PGM_PINCODE_NOTED` — `{pincode}` acknowledgement. |
| 395–427 | `_PGM_ASK_BIGGER_CITY` — search returned NOT_FOUND. |
| 429–459 | `_PGM_LOOKUP_FAILED` — search call failed; asks for a pincode or pin. |
| 492–497 | All six PGM messages registered in `MESSAGE_DEFAULTS`. |
| 516 | `pgm_pincode_noted` declares its `{pincode}` placeholder, so an override naming anything else is rejected on write. |
| 700–723 | Accessors `flow_intent_ask`, `pgm_flow_intro`, `pgm_location_ask`, `pgm_pincode_noted(pincode, language)`, `pgm_ask_bigger_city`, `pgm_lookup_failed`. |
| `_LABELS` | Telugu, Tamil, Kannada, Malayalam added to the `dealer_label_*` set (name / address / phone / map / fallback / default dealer) — the PGM list and card reuse them, and the dealer card gains them for free. |
| `_PGM_NEAREST_FOR_PINCODE` (`{pincode}`), `_PGM_NEAREST_FOR_LOCATION` | List headers. Two keys rather than a `{where}` placeholder because "pincode 560097" and "your shared location" decline differently per language. |
| `_PGM_RESULTS_FOOTER` | "Reply 1, 2 or 3 … or share another location or pincode" — closes the list and is the whole reply to filler while a list is on screen. |
| `_PGM_NONE_NEARBY` (`{km}`), `_PGM_PINCODE_UNRESOLVED` (`{pincode}`) | Empty result / pincode that did not geocode. |
| `pgm_results_list(pgms, *, pincode, language)` | `n. name — area (d.d km)` + indented phone line per garage; area is not repeated when already in the name; address and map wait behind the pick. |
| `pgm_card(pgm, *, language)` | Dealer-card shape with the `dealer_label_*` labels; no address falls back to the area; owner shown as `Owner - phone` when it differs from the garage name. |

**Note.** Registering in `MESSAGE_DEFAULTS` is what makes both messages
appear in `GET /admin/api/messages` and overridable per language through
`config["messages"]` with no further wiring. All seven languages are supplied
(the file otherwise carries EN/HI/MR) because this is the first thing the
customer reads in the language they just picked. The PGM flow has its own
location ask (`pgm_location_ask`) because it accepts a third answer the
vehicle flow does not — a place name.

### `client_processing.py`

| Lines | Change |
|-------|--------|
| 13, 24, 62, 69–74 | Import `resolve_pgm_location`, `FLOW_PGM`, `FLOW_VEHICLE`, `parse_flow_intent`, and the PGM message accessors. |
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
| 1231–1276 | `_apply_flow_intent` — vehicle → clear flag, `flow = "vehicle"`, return the qualification seed; PGM → clear flag, `flow = "pgm"`, send share-location image (no caption) + `pgm_flow_intro` + `pgm_location_ask` (line 1258), complete the turn, return `None`; else re-ask, return `None`. |
| 1278–1291 | `_qualification_start_message(customer, language)` — extracted verbatim from the old inline block so the vehicle route and the legacy path produce the same engine message (including the unknown-CRM "ask their name first" variant). |
| `ClientSession.pgm_candidates` | `list[str]` of the DMS ids last listed, in order. Round-tripped in `client_adapters.py`. |
| `__init__(pgm_directory=None)` | Optional; without it the flow degrades to `pgm_pincode_noted` / `location_thanks` as before. |
| `_handle_pgm_turn` | Location pin → `find_nearest_by_coords` → `_pgm_results`. Text → a pick (`parse_list_pick` against `pgm_candidates`) opens `pgm_card`; otherwise `_pgm_text_turn`. Never calls the engine, still-interested or dispose. |
| `_pgm_text_turn` | `resolve_pgm_location(text)`: `not_found` → `pgm_ask_bigger_city`; `lookup_failed` → `pgm_lookup_failed`; `unclear` → `pgm_results_footer` if a list is on screen else `pgm_location_ask`; `pincode` → stored in `lead_profile["pincode"]` (+ `["area"]` when searched), then `find_nearest_by_pincode` → `None` → `pgm_pincode_unresolved` (logged), else `_pgm_results`. |
| `_pgm_results` | Writes `pgm_candidates` (empty list clears a stale one), renders `pgm_none_nearby(max_km)` or `pgm_results_list`. |
| `_resolve_language` | Mid-chat switch skipped while `awaiting_flow_intent`, and for a bare number anywhere in the PGM flow — "2" is a pick (or nothing), not "switch to Hindi". A language typed in words still switches. |

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

### `tests/test_pgm_graph.py` — new file

Typed pincodes (plain, spaced, dashed, in a sentence) resolve with no search;
filler is `unclear` and never searched; a place name is searched with
`search_query(place)` and the pincode parsed from the answer (Latin and
Devanagari input); `NOT_FOUND`, an answer with no pincode, and `NOT_FOUND`
alongside stray digits are all `not_found`; a raising search is
`lookup_failed`.

### `tests/test_gemini_setup.py` — new file

With a fake client: the call goes to `rag.get_client()` with one
`google_search` tool and `temperature=0`; the answer is stripped and capped
(default and explicit `max_chars`); a `None` answer becomes `""`.

### `tests/test_client_static_messages.py`

| Lines | Change |
|-------|--------|
| 33–35 | `_ALL_LANGUAGES` — the seven menu languages. |
| 38–49 | Routing ask is distinct per language, mentions PGM and both options. |
| 52–57 | PGM intro is distinct per language. |
| 60–78 | Both messages honour a `config["messages"]` override. |
| 81–95 | The four location-step messages are distinct per language; `{pincode}` is rendered. |
| 98–103 | `pgm_pincode_noted` declares `{pincode}`; `pgm_location_ask` declares nothing. |

### `tests/test_pgms.py` — new file

Ranking and the limit; the 50 km radius (Mysuru → `[]`, Nelamangala → only
Bengaluru garages); `find_nearest_by_pincode` `None` vs `[]`; `get_by_id`;
`parse_coordinate` on the sheet's real shapes; `build_pgms` cleaning, owner
de-duplication, derived map link and the dropped-row report.

### `tests/test_client_flow_intent.py` (added)

`parse_list_pick`: accepted forms, out-of-range numbers, `2 more`, a
pincode, and a shorter list.

### `tests/test_client_static_messages.py` (added)

The five result messages distinct across all seven languages; list layout
(numbering, area, distance, phone line only when there is a phone, no
address/map in the list); the card in Kannada with the localized labels;
placeholder declarations.

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
| 2334–2353 | "2" → `flow == "pgm"`, no engine turn, intro + Marathi location ask (mentioning the service centre) + caption-less image, turn in history. |
| 2356–2365 | Unclear reply → same ask again, flag still set. |
| 2368–2392 | Location pin while pending → re-asked; dealer directory not called. |
| 2395–2414 | `_pgm_session(monkeypatch, search)` — returning customer walked into the PGM flow with `resolve_pgm_location` bound to a fake search. |
| 2417–2430 | PGM-flow turns never reach the engine or still-interested, whatever is typed. |
| 2433–2445 | Typed pincode is noted with no search; `area` not set. |
| 2448–2463 | Place name → search query names the place → pincode and `area` stored, reply carries the pincode. |
| 2466–2475 | `NOT_FOUND` → bigger-city ask; no pincode stored; still in the PGM flow. |
| 2478–2488 | Search raises → asks for a pincode, not a bigger city. |
| 2491–2500 | Filler → location ask again, no search. |
| 2503–2517 | Location pin → `location_thanks`; pin without coordinates → `location_unreadable`. |
| 2520–2542 | Returning customer: routing ask, then "1", then the still-interested ask in Hindi. |
| 2545–2551 | Both new session fields exist on `ClientSession`. |
| `FakePgmDirectory`, `_pgm_search_session` | Three garages; `geocoded` is what a pincode resolves to, `results` overrides the search. |
| pincode → list | Header names the pincode, three numbered lines with area / distance / phone, footer; `pgm_candidates` and `lead_profile["pincode"]` set; no engine turn. |
| place → list | Searched to a pincode, then geocoded; `area` stored. |
| pin → list | `find_nearest_by_coords` called with the pin, no geocoding; unreadable pin still re-asked. |
| pick | `1` opens the card; `3.` opens another (area as address, phone alone without an owner); list stays. |
| number without a list | Location ask, no search, language unchanged; "Hindi please" still switches. |
| filler after list | Footer, not the intro; `4` (past the end) likewise. |
| new search | Replaces candidates; a stale `3` opens nothing. |
| nothing within radius | `pgm_none_nearby` with 50 km, candidates cleared, still in the flow. |
| pincode did not geocode | `pgm_pincode_unresolved`, no coordinate search. |
| language | Marathi customer: Marathi header, `फोन:` label, `2` opens the card in Marathi and does **not** switch the session to Hindi. |

Suite: 565 passed, 9 failed — the same 9 failures as before these changes
(`test_230707_*`, `test_distance_is_shown_on_the_dealer_card`,
`test_250703_conversation_restarts_after_wrap_up`,
`test_pincode_message_asks_nearest_dealer_confirm_once`,
`test_crm_dealer_confirm_yes_sets_last_dealer_code_and_skips_nearest`), all
pre-existing and unrelated.

## Operating notes

- All PGM messages (`flow_intent_ask`, `pgm_flow_intro`, `pgm_location_ask`,
  `pgm_pincode_noted`, `pgm_ask_bigger_city`, `pgm_lookup_failed`) are
  editable live at `PUT /admin/api/messages/<key>` per language; no restart.
  All six ship in all seven languages.
- `location_thanks` / `location_unreadable` (location pins in the PGM flow)
  only have EN/HI/MR built in — the existing Dravidian gap, fillable from the
  panel.
- The place-name search costs one grounded Gemini call per place typed
  (`MODEL_FAST`, Google Search tool). Filler and pincodes never trigger it.
  If the call fails the customer is asked for a pincode; the failure is
  logged with the place name.
- Google Search grounding is billed separately from plain generation on the
  Gemini API; check the project's quota before go-live.
- The share-location image needs `CLIENT_MEDIA_BASE_URL` (or
  `share_location_image.url` in config); without it the text is sent alone,
  as in the vehicle flow.
- Dispose is not called anywhere in the PGM flow. Whether a PGM enquiry
  should reach CRM, and as what, is part of the pending requirement.

- Rebuilding the dataset: drop the new workbook at
  `data/pgm_network_bnlr.xlsx` and run `python scripts/build_pgms.py`, then
  commit `data/pgms.json` (whitelisted in `.gitignore`) and redeploy. Read
  the `dropped` / `check` lines it prints. `openpyxl` is a dev dependency
  for this script only.
- Radius and list length are constructor arguments on `PgmDirectory`
  (`max_km=50`, `limit=3`); the footer text hard-codes "1, 2 or 3", so
  change both together.
- The pincode geocoder is Nominatim (1 req/s, cached in
  `data/pincode_geocode_cache.json`, shared with the dealer flow). First
  hit on a new pincode costs ~1–2 s.

## Data issues in the 25.07.2026 sheet

Dropped (unreadable coordinates): `58920745 RM AUTO GARAGE` (`x`),
`65135285 S S auto garage` (long `77569063`), `80148008 TANVEER AUTO
SERVICE` (long = lat).

Kept but flagged (far from the rest of the network — likely mistyped or
swapped cells): `58920933 SALIM AUTO WORKS` (Hosahalli) at Pune
coordinates, `58920837 SON AUTO ENGINEERING WORK` (Hosadurga, 167 km),
`58920787 KARNATAKA MOTORS` (Vishveswara Puram) at Mysuru coordinates,
`62885020 RAJA` (Jaya Nagar, 111 km). Until the client corrects them, a
Pune or Mysuru customer will be offered one of these.

## Still open

- Whether a PGM enquiry should reach CRM (dispose), and as what. Nothing
  is sent today.
- An admin upload for the workbook (rebuild without a redeploy), like the
  vehicle and message endpoints.
- Whether to also offer authorised service centres (the other four sheets)
  when no PGM is within range.

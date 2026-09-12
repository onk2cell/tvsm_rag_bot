# WhatsApp Template Request — TVS Passenger 3W Bot

Templates to submit for approval, taken from the copy the bot sends today
(`client_static_messages.py`, `client_language.py`).

**Languages:** English (`en`), Hindi (`hi`), Marathi (`mr`). The bot's language
menu offers 7, but only these 3 have real translations in the code — submit the
other 4 only after the translations exist.

**Variables** are `{{1}}`, `{{2}}` … in order. Meta rejects a body that starts or
ends with a variable, and rejects two adjacent variables. Sample values are
mandatory at submission.

---

## Tier 1 — Required (these open a conversation outside the 24h window)

### T1. `tvs_3w_welcome_back_still_interested`
Category: **MARKETING** · Returning lead, re-engagement

| Lang | Body |
|---|---|
| en | `Hi {{1}}. Last time, you enquired about {{2}}. Are you still planning to purchase this vehicle?` |
| hi | `नमस्ते {{1}}। पिछली बार आपने {{2}} के बारे में पूछा था। क्या आप अभी भी यह वाहन खरीदने की योजना बना रहे हैं?` |
| mr | `नमस्कार {{1}}. गेल्या वेळी तुम्ही {{2}} बद्दल चौकशी केली होती. तुम्ही अजूनही हे वाहन खरेदी करण्याचा विचार करत आहात का?` |

Buttons (Quick Reply): en `Yes` / `No` · hi `हाँ` / `नहीं` · mr `होय` / `नाही`
Samples: `{{1}}` = Deepali · `{{2}}` = King Duramax Plus

> The code today writes `{name}. Last time…` — starting with the variable.
> **Meta will reject that.** The `Hi ` prefix above is required.
> "Press 1 for Yes / Press 2 for No" is replaced by real buttons.

### T2. `tvs_3w_welcome_back_no_name`
Category: **MARKETING** · Same as T1 when CRM has no customer name

| Lang | Body |
|---|---|
| en | `Last time, you enquired about {{1}}. Are you still planning to purchase this vehicle?` |
| hi | `पिछली बार आपने {{1}} के बारे में पूछा था। क्या आप अभी भी यह वाहन खरीदने की योजना बना रहे हैं?` |
| mr | `गेल्या वेळी तुम्ही {{1}} बद्दल चौकशी केली होती. तुम्ही अजूनही हे वाहन खरेदी करण्याचा विचार करत आहात का?` |

Buttons: same as T1 · Sample: `{{1}}` = King EV MAX

### T3. `tvs_3w_language_menu`
Category: **MARKETING** · First message of a fresh conversation

Body (single `en` submission — the script mix is fine, no variables):
```
Welcome to the TVS Passenger 3W Assistant.

Which language do you prefer?
1. English
2. हिंदी (Hindi)
3. मराठी (Marathi)
4. తెలుగు (Telugu)
5. தமிழ் (Tamil)
6. ಕನ್ನಡ (Kannada)
7. മലയാളം (Malayalam)

Reply with 1-7.
```
No buttons — 7 options exceeds the 3-button quick-reply limit, so this stays a
numbered text list exactly as the bot sends it today.

---

## Tier 2 — In-session replies

These fire *after* the customer has messaged, so under standard WhatsApp rules
they are free-form and need **no approval**. Submit them only if the BSP
requires every structured outbound message to be a template.

### T4. `tvs_3w_dealer_details` — UTILITY
```
Please check this dealership details:

Name: {{1}}
Address: {{2}}
Phone: {{3}}
Map: {{4}}

Is this dealership near you / OK for you?
```
Buttons: `Yes` / `No`
Samples: `{{1}}` = Shree Motors · `{{2}}` = Plot 14, MIDC, Pune 411019 ·
`{{3}}` = Rahul Patil - 9876543210 · `{{4}}` = https://maps.google.com/?q=18.52,73.85

> **Submit this one last.** The "Approx. distance" line is a known open bug
> (`dealer_confirm_ask()` has no `distance_km` parameter). Adding it later means
> re-approval — fix the bug first so the template matches final copy.

### T5. `tvs_3w_dealer_share_consent` — UTILITY
| Lang | Body |
|---|---|
| en | `Would you like me to share your nearest dealership details?` |
| hi | `क्या मैं आपको आपकी नज़दीकी डीलरशिप की जानकारी भेजूं?` |
| mr | `मी तुम्हाला तुमच्या जवळच्या डीलरशिपची माहिती पाठवू का?` |

Buttons: `Yes` / `No`

### T6. `tvs_3w_brochure_offer` — UTILITY
The brochure ask names the vehicle, so the customer always knows which model
they are being offered.

| Lang | Body |
|---|---|
| en | `Should I send you the brochure for {{1}}?` |
| hi | `क्या मैं आपको {{1}} का ब्रोशर भेजूं?` |
| mr | `मी तुम्हाला {{1}} चा ब्रोशर पाठवू का?` |

Buttons: `Yes` / `No` · Sample: `{{1}}` = King Duramax Plus

> **Code change needed.** Since 2026-09-12 the brochure offer is written by
> the model, not by the code: the system prompt (rule 11) has it ask in its
> own words and report the offer with an `OFFERED_BROCHURE: <model>` marker
> that `client_processing._arm_brochure_offer` turns into the pending offer.
> Serving it from a template means putting the ask back on the code path —
> a deterministic send after the reply, with the marker still deciding
> *when* — so this template is only worth submitting once that trade is
> agreed. The product would come from `pending_brochure_product`.
>
> T7 below is still needed for the case where no model has been identified yet.

### T7. `tvs_3w_brochure_model_choice` — UTILITY
| Lang | Body |
|---|---|
| en | `Which model's brochure should I send?` |
| hi | `किस मॉडल का ब्रोशर भेजूं?` |
| mr | `कोणत्या मॉडेलचा ब्रोशर पाठवावा?` |

Buttons (Quick Reply): `King EV MAX` / `King Deluxe` / `King Duramax Plus`

### T8. `tvs_3w_brochure_document` — UTILITY
Header: **DOCUMENT** (dynamic URL)
Body: `Here is the {{1}} brochure.` · Sample `{{1}}` = King EV MAX

Also covers warranty and PMS sends — or submit
`tvs_3w_warranty_document` / `tvs_3w_pms_document` with the same shape.

### T9. `tvs_3w_share_location` — UTILITY
Header: **IMAGE** (the share-location instruction card, `data/media/share_location`)
| Lang | Body |
|---|---|
| en | `Please share your current WhatsApp location using the steps in the image, or type your 6-digit pincode.` |
| hi | `कृपया इमेज में दिए स्टेप्स से अपनी WhatsApp करेंट लोकेशन शेयर करें, या अपना 6-अंकों का पिनकोड टाइप करें।` |
| mr | `कृपया इमेजमधील स्टेप्सनुसार तुमचे WhatsApp करंट लोकेशन शेअर करा, किंवा तुमचा ६-अंकी पिनकोड टाइप करा.` |

### T10. `tvs_3w_invalid_pincode` — UTILITY
| Lang | Body |
|---|---|
| en | `That does not look like a valid 6-digit pincode. Please enter a valid 6-digit pincode (for example 411001).` |
| hi | `यह मान्य 6-अंकों का पिनकोड नहीं लगता। कृपया सही 6-अंकों का पिनकोड टाइप करें (जैसे 411001)।` |
| mr | `हे वैध ६-अंकी पिनकोड वाटत नाही. कृपया योग्य ६-अंकी पिनकोड टाइप करा (उदा. 411001).` |

### T11. `tvs_3w_location_not_found` — UTILITY
| Lang | Body |
|---|---|
| en | `I could not find a nearby dealership for that location. Please type your 6-digit pincode, or share live location again.` |
| hi | `उस लोकेशन के लिए पास की डीलरशिप नहीं मिली। कृपया अपना 6-अंकों का पिनकोड टाइप करें, या लाइव लोकेशन फिर से शेयर करें।` |
| mr | `त्या लोकेशनसाठी जवळची डीलरशिप सापडली नाही. कृपया तुमचा ६-अंकी पिनकोड टाइप करा, किंवा लाईव्ह लोकेशन पुन्हा शेअर करा.` |

### T12. `tvs_3w_other_model_offer` — MARKETING
| Lang | Body |
|---|---|
| en | `Thank you for letting us know. Would you like to look at a different TVS passenger model instead?` |
| hi | `बताने के लिए धन्यवाद। क्या आप कोई दूसरा TVS पैसेंजर मॉडल देखना चाहेंगे?` |
| mr | `कळवल्याबद्दल धन्यवाद. तुम्हाला दुसरे TVS पॅसेंजर मॉडेल पाहायला आवडेल का?` |

Buttons: `Yes` / `No`

---

## Tier 3 — Media templates (product images + schemes)

### T13. `tvs_3w_product_info_image` — UTILITY
Triggered when the customer asks for more detail on a model: send the product
photo, then offer the brochure.

Header: **IMAGE** (dynamic — product photo)

| Lang | Body |
|---|---|
| en | `Here is the {{1}}. Would you like me to send the full brochure with detailed specifications?` |
| hi | `यह है {{1}}। क्या मैं आपको विस्तृत जानकारी के साथ पूरा ब्रोशर भेजूं?` |
| mr | `हे आहे {{1}}. मी तुम्हाला सविस्तर माहितीसह पूर्ण ब्रोशर पाठवू का?` |

Buttons (Quick Reply): `Send brochure` / `No thanks`
Sample: `{{1}}` = King EV MAX

On `Send brochure` the bot sends **T8 `tvs_3w_brochure_document`** (DOCUMENT
header). A template has only one header, so image and PDF are two separate
sends — they cannot be combined into one template.

> **Blocker:** `data/media/products/` is empty. No product photos exist yet.
> Three images are needed (King EV MAX, King Deluxe, King Duramax Plus) on a
> public HTTPS URL before this can be submitted.
>
> Until those images exist, **T6 covers this flow on its own** — it already
> names the vehicle and offers the brochure, just without a photo. T13 is the
> upgrade, not a prerequisite.

### T14. `tvs_3w_model_carousel` — MARKETING (Carousel)
The Features-sheet ask ("auto images in carousel"). Carousel templates are
MARKETING-only, max 10 cards, and every card must have the same component
structure and the same button types.

Body above the cards: `Here are our TVS passenger three-wheeler models. Tap a model to get its brochure.`

| Card | Image | Body | Button |
|---|---|---|---|
| 1 | King EV MAX | `Electric. 179 km certified range, 60 km/h top speed.` | `Send brochure` |
| 2 | King Deluxe | `Petrol / CNG / LPG. All-gear start, LED lamps, tubeless tyres.` | `Send brochure` |
| 3 | King Duramax Plus | `Petrol / CNG. Power gear for better gradeability and mileage.` | `Send brochure` |

Same image blocker as T13.

### T15. `tvs_3w_scheme_offer_ask` — MARKETING
The consent ask before any scheme content. This is the fix for bug 010801
("why it giving vada scheme… such big paragraph") — ask first, send after.

| Lang | Body |
|---|---|
| en | `We have special schemes running on TVS passenger three-wheelers right now. Would you like to see the current offers?` |
| hi | `अभी TVS पैसेंजर थ्री-व्हीलर पर खास स्कीम चल रही हैं। क्या आप मौजूदा ऑफर देखना चाहेंगे?` |
| mr | `सध्या TVS पॅसेंजर थ्री-व्हीलरवर विशेष योजना सुरू आहेत. तुम्हाला सध्याचे ऑफर पाहायचे आहेत का?` |

Buttons (Quick Reply): `Yes, show me` / `Not now`

### T16. `tvs_3w_scheme_details_image` — MARKETING · **recommended**
Header: **IMAGE** (dynamic — the scheme creative)

| Lang | Body |
|---|---|
| en | `Here are the benefits under the current {{1}} scheme. Would you like me to share your nearest dealership details?` |
| hi | `यह है मौजूदा {{1}} स्कीम के फायदे। क्या मैं आपको आपकी नज़दीकी डीलरशिप की जानकारी भेजूं?` |
| mr | `हे आहेत सध्याच्या {{1}} योजनेचे फायदे. मी तुम्हाला तुमच्या जवळच्या डीलरशिपची माहिती पाठवू का?` |

Buttons: `Yes` / `No` · Sample: `{{1}}` = Vaada

**Why the image version, not a text version.** The scheme body is
admin-editable (`campaign_text`, `admin_config.py:59` — the Features-sheet ask
"what if the scheme changes… will provide the admin panel"). Two constraints
collide with putting that text in a template:

1. **WhatsApp template variables cannot contain newlines.** The six Vaada
   bullets cannot be passed as one `{{2}}`.
2. If the bullets are hardcoded in the approved template, **every scheme change
   needs Meta re-approval** — which defeats the admin panel entirely.

Putting the benefits in a **creative image** solves both: marketing swaps the
image, the approved template never changes, and `{{1}}` carries only the scheme
name. Needs an admin-panel field for the scheme image URL.

### T16-alt. `tvs_3w_scheme_details_text` — MARKETING · fallback only
Use only if no scheme creative can be produced. Accepts the re-approval cost.

```
Here are the benefits under the current Vaada scheme:

- 2-year warranty + 3 free maintenance services
- 1 year free RSA (roadside assistance, towing to showroom)
- Accident coverage up to Rs 10 lakh
- Education benefit up to Rs 1 lakh per child (max 2 children)
- Hospitalisation cash Rs 4,000/day up to 30 days
- Ambulance coverage up to Rs 5,000

Would you like me to share your nearest dealership details?
```
Buttons: `Yes` / `No`

---

## Engineering work this depends on

1. **JAM send API cannot send templates.** `client_adapters.py` emits only
   `type: "text"`, image, and document. A template-send endpoint is needed on
   JAM's side plus a `send_template()` path in our adapter.
2. **Button replies are not parsed.** `client_processing.py:160` matches the
   literal text `"1"` / `"2"`. Quick-reply buttons arrive as a button payload,
   not `"1"`. Either JAM flattens button payloads to their text, or we add a
   branch. **Confirm this before submitting** — changing button labels after
   approval means re-approval.
3. **Language must be chosen before the customer picks one.** T1/T2 are sent in
   the CRM's `preferred_language`. That field is behind bugs 230707 and 240710.

"""STANDALONE prototype for the pre-lead qualification & profiling bot.

This is intentionally self-contained (no config.py / Redis / WhatsApp imports) so it
can be tested in isolation without touching the production bot. It implements the
flow from docs/LEAD_QUALIFICATION_BOT_SPEC.md:

  - language tick-form picker
  - LLM-driven qualification conversation in the chosen language
  - proactive campaign awareness (Vaada)
  - accurate feature pitch from the embedded passenger-model spec sheet
  - captured lead profile appended to leads.csv (questions = columns, leads = rows)

Run:
  GEMINI_API_KEY=<key> python -m uvicorn qualify_prototype:app --port 8200
  then open http://localhost:8200
"""
from __future__ import annotations

import csv
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from google import genai

API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
LEADS_CSV = Path(__file__).with_name("leads.csv")

client = genai.Client(api_key=API_KEY) if API_KEY else None

# --- languages offered in the tick-form (extensible) ------------------------
LANGUAGES = [
    {"code": "English", "label": "English"},
    {"code": "Marathi", "label": "मराठी (Marathi)"},
    {"code": "Hindi", "label": "हिंदी (Hindi)"},
    {"code": "Tamil", "label": "தமிழ் (Tamil)"},
]

# --- spec sheet (source of truth: build_tvs_3w_kb.py, passenger models) ------
SPECS = """\
TVS PASSENGER THREE-WHEELERS — APPROVED SPEC SHEET (use ONLY these facts)

1) TVS King EV MAX — electric passenger three-wheeler
- Motor: PMSM, max power 11 kW, max torque 40 Nm
- Battery: 51.2V Li-Ion LFP, 9.2 kWh; certified range 179 km; top speed 60 km/h
- Charging: 0-80% in 2h15m; 0-100% in 3h30m; regenerative braking
- Gradeability 31%; Hill Hold Assist; India's first Bluetooth-connected 3W (SmartXonnect)
- Warranty: 6 years / 1,50,000 km + 3 years free maintenance & roadside assistance
- Colours: Pristine White, Neptune Blue

2) TVS King Deluxe — 200cc petrol / CNG / LPG passenger three-wheeler ("Mileage Maharaja")
- Engine: 4-stroke single-cylinder air-cooled, 199.26 cc
- Mileage: CNG ~50 km/l, Petrol ~38 km/l, LPG ~25 km/l
- Top speed: ~63 km/h (petrol); transmission 4 forward + 1 reverse
- Gradeability 10°; warranty 18 months / 72,000 km
- Colours: Glossy Black, Eco Space Green, Neptune Blue, Golden Yellow

3) TVS King Duramax Plus — 225.8cc liquid-cooled petrol / CNG passenger three-wheeler
- Engine: 4-stroke single-cylinder LIQUID-COOLED, 225.8 cc (NOTE: it is 225.8cc, not 25cc)
- Max power: Petrol 7.9 kW @4750rpm; Top speed petrol 65 km/h
- Transmission 4 forward + 1 reverse; gradeability 12°; service interval 10,000 km
- Full metal body, low maintenance, LED lamps, single start/stop switch
- Colours: Glossy Black, Eco Green, Golden Yellow

Documents for commercial passenger 3W: driving LICENCE (required), PERMIT (required),
conductor/driver BADGE (RTO-issued — the dealership only GUIDES, it cannot complete it).
"""

# --- active campaign (in production this is admin-uploaded) ------------------
CAMPAIGN = """\
ACTIVE CAMPAIGN — "Vaada" scheme (mention proactively, briefly):
- 2-year warranty + 3 free maintenance services
- 1 year free RSA (roadside assistance, towing to showroom)
- Accident coverage package up to Rs 10 lakh
- Education benefit up to Rs 1 lakh per child (max 2 children)
- Hospitalization cash Rs 4,000/day up to 30 days
- Ambulance coverage up to Rs 5,000
"""

# --- fields to capture (in production this is admin-configurable) ------------
CSV_FIELDS = [
    "timestamp", "session", "language", "lead_name", "product_interest",
    "purchase_timeline", "timeline_bucket", "pincode", "area", "district",
    "feature_awareness", "doc_license", "doc_permit", "doc_badge",
    "campaign_shown", "lead_quality", "blockers", "next_step", "notes",
]

SYSTEM = f"""You are TVS Motor's pre-lead qualification assistant for TVS PASSENGER \
three-wheelers (King EV MAX, King Deluxe, King Duramax Plus).

YOUR GOAL is NOT to answer every question in depth. Your goal is to QUALIFY and PROFILE \
the lead in a short, friendly chat, make them aware of the active campaign, then hand \
them to the dealership.

RULES
1. Conduct the ENTIRE conversation in this language: {{LANGUAGE}}.
2. Qualify the lead by asking, ONE QUESTION AT A TIME, acknowledging each answer first:
   a. Which TVS passenger model they want.
   b. Proactively mention the current campaign (1-2 lines, only what is in CAMPAIGN).
   c. When they want to buy / take delivery (timeline).
   d. Their pin code (to route to the nearest dealership). It may arrive across several
      messages — accept it whenever it appears. If unknown, ask city/area instead.
   e. Whether they know the features. If not, give a SHORT accurate pitch from SPEC SHEET
      (max ~5 points).
   f. Whether they have a driving LICENCE, a PERMIT, and a BADGE.
3. Keep every reply short and clear (chat style). Ask only ONE thing per message.
4. Do NOT quote down payment / EMI / on-road price — say the dealership shares exact
   figures. Give a range only if it is in the documents.
5. Never invent specs. Use ONLY the SPEC SHEET. Skip long name introductions.
6. Do not over-promise: a BADGE is RTO-issued; the dealership GUIDES, it cannot complete it.
7. When you have enough info (or the user wants to stop), WRAP UP: confirm what you
   captured, say the nearest dealership will contact them, and thank them.

After the customer-facing wrap-up message ONLY (not before), output on a NEW final line a
single JSON object prefixed exactly with `PROFILE_JSON:` with these keys:
{json.dumps(CSV_FIELDS[2:])}
Field formats:
- timeline_bucket: one of immediate, <=30d, 30-90d, exploring.
- feature_awareness: "high" if they already knew the features, else "low".
- doc_license / doc_permit / doc_badge: "yes", "no", or "unknown".
- campaign_shown: the campaign NAME you mentioned (e.g. "Vaada"), or "" if none.
- lead_quality: HOT (near-term timeline + location + >=2/3 docs), WARM, or COLD.
- blockers: short list of strings; next_step / notes: short strings.
Do not output PROFILE_JSON until you are wrapping up.

SPEC SHEET:
{SPECS}

CAMPAIGN:
{CAMPAIGN}
"""

app = FastAPI(title="TVS Lead-Qualification Prototype")


def _contents(history: list[dict]) -> list:
    out = []
    for turn in history:
        role = "model" if turn.get("role") == "model" else "user"
        out.append({"role": role, "parts": [{"text": turn["text"]}]})
    return out


def _save_lead(session: str, language: str, profile: dict) -> None:
    row = {k: "" for k in CSV_FIELDS}
    row["timestamp"] = datetime.now().isoformat(timespec="seconds")
    row["session"] = session
    row["language"] = language
    for k, v in profile.items():
        if k in row:
            row[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
    new_file = not LEADS_CSV.exists()
    with LEADS_CSV.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new_file:
            w.writeheader()
        w.writerow(row)


@app.get("/languages")
def languages():
    return {"languages": LANGUAGES}


@app.post("/chat")
def chat(payload: dict):
    if client is None:
        raise HTTPException(503, "GEMINI_API_KEY is not set — launch with the key in the env.")
    language = payload.get("language") or "English"
    session = payload.get("session") or "anon"
    history = payload.get("history") or []
    message = (payload.get("message") or "").strip()

    contents = _contents(history)
    # First turn after language pick: synthesize a start trigger so the bot opens.
    user_text = message or "(The customer has selected their language. Greet briefly and ask the first qualification question.)"
    contents.append({"role": "user", "parts": [{"text": user_text}]})

    try:
        resp = client.models.generate_content(
            model=MODEL,
            contents=contents,
            config={"system_instruction": SYSTEM.replace("{LANGUAGE}", language), "temperature": 0.3},
        )
        text = resp.text or ""
    except Exception as e:
        raise HTTPException(500, str(e))

    # Strip + capture the PROFILE_JSON line if present.
    captured = None
    m = re.search(r"PROFILE_JSON:\s*(\{.*\})", text, re.DOTALL)
    if m:
        try:
            captured = json.loads(m.group(1))
            _save_lead(session, language, captured)
        except Exception:
            captured = None
        text = text[:m.start()].strip()

    return {"answer": text, "captured": bool(captured)}


@app.get("/admin/leads.csv")
def download_leads():
    if not LEADS_CSV.exists():
        raise HTTPException(404, "No leads captured yet.")
    return FileResponse(LEADS_CSV, media_type="text/csv", filename="leads.csv")


@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML


INDEX_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>TVS Lead-Qualification Prototype</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { font-family: system-ui, sans-serif; margin: 0; height: 100vh; display: flex; flex-direction: column; }
  header { padding: 10px 16px; border-bottom: 1px solid #8884; display: flex; gap: 12px; align-items: center; }
  header h1 { font-size: 15px; margin: 0; }
  .status { font-size: 12px; margin-left: auto; }
  #pick { margin: auto; text-align: center; }
  #pick h2 { font-weight: 500; }
  .lang { display: block; width: 260px; margin: 8px auto; padding: 12px; font-size: 16px; cursor: pointer;
          border: 1px solid #8886; border-radius: 10px; background: transparent; }
  .lang:hover { background: #8882; }
  #chat { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
  .msg { max-width: 75%; padding: 8px 12px; border-radius: 12px; white-space: pre-wrap; line-height: 1.4; }
  .msg.user { align-self: flex-end; background: #2563eb; color: #fff; }
  .msg.bot  { align-self: flex-start; background: #8882; }
  .msg.error { align-self: flex-start; background: #ef444433; color: #b91c1c; }
  .saved { align-self: center; font-size: 12px; color: green; }
  form { display: flex; gap: 8px; padding: 12px 16px; border-top: 1px solid #8884; }
  form input { flex: 1; padding: 8px; font-size: 14px; }
  button { padding: 8px 12px; cursor: pointer; font-size: 14px; }
  .hidden { display: none; }
</style></head>
<body>
<header>
  <h1>TVS Lead-Qualification Prototype</h1>
  <a href="/admin/leads.csv" style="font-size:13px">Download leads.csv</a>
  <button id="restart" type="button">Restart</button>
  <span id="status" class="status"></span>
</header>

<div id="pick">
  <h2>Which language are you comfortable in? / आपण कोणत्या भाषेत बोलू इच्छिता?</h2>
  <div id="langButtons"></div>
</div>

<main id="chat" class="hidden"></main>
<form id="form" class="hidden">
  <input type="text" id="input" placeholder="Type your reply…" autocomplete="off">
  <button type="submit">Send</button>
</form>

<script>
const session = 'web-' + Math.random().toString(36).slice(2, 10);
let language = null;
let history = [];
const chat = document.getElementById('chat');
const form = document.getElementById('form');
const input = document.getElementById('input');
const statusEl = document.getElementById('status');

function render(role, text) {
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}
function note(text) {
  const div = document.createElement('div');
  div.className = 'saved';
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

fetch('/languages').then(r => r.json()).then(d => {
  const box = document.getElementById('langButtons');
  d.languages.forEach(l => {
    const b = document.createElement('button');
    b.className = 'lang'; b.textContent = l.label;
    b.onclick = () => startChat(l.code);
    box.appendChild(b);
  });
});

async function send(message) {
  statusEl.textContent = '…thinking';
  try {
    const r = await fetch('/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ language, session, history, message }),
    });
    const d = await r.json();
    statusEl.textContent = '';
    if (!r.ok) { render('error', '⚠ ' + (d.detail || 'error')); return; }
    render('bot', d.answer);
    if (message) history.push({ role: 'user', text: message });
    history.push({ role: 'model', text: d.answer });
    if (d.captured) note('✓ Lead captured to leads.csv');
  } catch (e) { statusEl.textContent = ''; render('error', '⚠ ' + e); }
}

function startChat(code) {
  language = code;
  document.getElementById('pick').classList.add('hidden');
  chat.classList.remove('hidden');
  form.classList.remove('hidden');
  input.focus();
  send('');   // empty message → bot greets and asks the first question
}

form.addEventListener('submit', (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  render('user', text);
  input.value = '';
  send(text);
});

document.getElementById('restart').addEventListener('click', () => location.reload());
</script>
</body></html>"""

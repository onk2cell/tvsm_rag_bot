"""Public web qualification chat — routes and UI for the conversation engine."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

import admin_config
import config
from conversation_engine import ConversationEngine, TurnInput, make_engine

_engine: ConversationEngine | None = None


def get_engine() -> ConversationEngine:
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def set_engine(engine: ConversationEngine | None) -> None:
    """Override engine — for tests."""
    global _engine
    _engine = engine


def _normalize_source(source: str | None) -> str:
    allowed = {"web", "ricshow", "whatsapp"}
    s = (source or "web").strip().lower()
    return s if s in allowed else "web"


router = APIRouter(tags=["qualify"])


@router.get("/api/qualify/languages")
def qualify_languages(source: str = Query(default="web")):
    cfg = admin_config.get_store().get()
    src = _normalize_source(source)
    entry = (cfg.get("entry_sources") or {}).get(src) or {}
    welcome = entry.get("welcome_override") or cfg.get("welcome_text", "")
    return {
        "bot_name": cfg.get("bot_name", ""),
        "welcome_text": welcome,
        "languages": cfg.get("languages", []),
        "source": src,
    }


@router.post("/api/qualify/chat")
def qualify_chat(payload: dict):
    try:
        from rag import has_client
        if not has_client():
            raise HTTPException(
                status_code=503,
                detail="Gemini API key is not configured. Set GEMINI_API_KEY in .env or use /admin.",
            )
    except HTTPException:
        raise
    except Exception:
        pass

    language = (payload.get("language") or "").strip()
    if not language:
        raise HTTPException(status_code=400, detail="language is required")

    session_id = (payload.get("session_id") or payload.get("session") or "").strip()
    if not session_id:
        session_id = f"web-{uuid.uuid4().hex[:8]}"

    message = payload.get("message")
    if message is not None:
        message = str(message).strip() or None

    history = payload.get("history") or []
    if not isinstance(history, list):
        raise HTTPException(status_code=400, detail="history must be a list")
    history = [
        {"role": h.get("role"), "text": h.get("text", "")}
        for h in history[-(config.MAX_HISTORY_TURNS * 2) :]
        if isinstance(h, dict) and h.get("text")
    ]

    source = _normalize_source(payload.get("source"))
    channel = (payload.get("channel") or "web").strip() or "web"

    try:
        out = get_engine().handle_turn(
            TurnInput(
                session_id=session_id,
                language=language,
                message=message,
                channel=channel,
                source=source,
                history=history,
            )
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {
        "answer": out.reply_text,
        "captured": out.captured,
        "citations": out.citations,
        "session_id": session_id,
    }


def qualify_page_html(*, admin_test: bool = False) -> str:
    banner = (
        '<div class="banner">Admin test mode — same engine as public chat</div>'
        if admin_test
        else ""
    )
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>TVS Qualification Chat</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: system-ui, sans-serif; margin: 0; height: 100vh; display: flex; flex-direction: column; }}
  .banner {{ background: #fef3c7; color: #92400e; padding: 8px 16px; font-size: 13px; text-align: center; }}
  header {{ padding: 10px 16px; border-bottom: 1px solid #8884; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }}
  header h1 {{ font-size: 15px; margin: 0; }}
  .status {{ font-size: 12px; margin-left: auto; }}
  #pick {{ margin: auto; text-align: center; max-width: 420px; padding: 16px; }}
  #pick h2 {{ font-weight: 500; font-size: 1.1rem; }}
  #pick p {{ opacity: 0.75; font-size: 14px; }}
  .lang {{ display: block; width: 100%; margin: 8px 0; padding: 12px; font-size: 16px; cursor: pointer;
          border: 1px solid #8886; border-radius: 10px; background: transparent; }}
  .lang.suggested {{ border-color: #2563eb; box-shadow: 0 0 0 2px #2563eb33; }}
  .lang:hover {{ background: #8882; }}
  #chat {{ flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; }}
  .msg {{ max-width: 75%; padding: 8px 12px; border-radius: 12px; white-space: pre-wrap; line-height: 1.4; }}
  .msg.user {{ align-self: flex-end; background: #2563eb; color: #fff; }}
  .msg.bot  {{ align-self: flex-start; background: #8882; }}
  .msg.error {{ align-self: flex-start; background: #ef444433; color: #b91c1c; }}
  .saved {{ align-self: center; font-size: 12px; color: green; }}
  .cites {{ font-size: 11px; opacity: 0.7; margin-top: 6px; }}
  form {{ display: flex; gap: 8px; padding: 12px 16px; border-top: 1px solid #8884; }}
  form input {{ flex: 1; padding: 8px; font-size: 14px; }}
  button {{ padding: 8px 12px; cursor: pointer; font-size: 14px; }}
  .hidden {{ display: none; }}
</style></head>
<body>
{banner}
<header>
  <h1 id="botTitle">TVS Qualification</h1>
  <button id="changeLang" type="button" class="hidden">Change language</button>
  <button id="restart" type="button">Restart</button>
  <span id="status" class="status"></span>
</header>

<div id="pick">
  <h2 id="welcomeHeading">Which language are you comfortable in?</h2>
  <p id="localeHint"></p>
  <div id="langButtons"></div>
</div>

<main id="chat" class="hidden"></main>
<form id="form" class="hidden">
  <input type="text" id="input" placeholder="Type your reply…" autocomplete="off">
  <button type="submit">Send</button>
</form>

<script>
const params = new URLSearchParams(location.search);
const SOURCE = params.get('source') || 'web';
const STORAGE_PREFIX = 'tvs_qualify_' + SOURCE + '_';

let sessionId = localStorage.getItem(STORAGE_PREFIX + 'session') || ('web-' + Math.random().toString(36).slice(2, 10));
let language = localStorage.getItem(STORAGE_PREFIX + 'language') || null;
let history = JSON.parse(localStorage.getItem(STORAGE_PREFIX + 'history') || '[]');

const chat = document.getElementById('chat');
const form = document.getElementById('form');
const input = document.getElementById('input');
const statusEl = document.getElementById('status');
const pick = document.getElementById('pick');

function persist() {{
  localStorage.setItem(STORAGE_PREFIX + 'session', sessionId);
  if (language) localStorage.setItem(STORAGE_PREFIX + 'language', language);
  localStorage.setItem(STORAGE_PREFIX + 'history', JSON.stringify(history));
}}

function render(role, text, cites) {{
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.textContent = text;
  if (cites && cites.length) {{
    const c = document.createElement('div');
    c.className = 'cites';
    c.textContent = 'Sources: ' + cites.join(', ');
    div.appendChild(c);
  }}
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}}

function note(text) {{
  const div = document.createElement('div');
  div.className = 'saved';
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}}

function suggestLanguageCode(languages) {{
  const nav = (navigator.language || 'en').toLowerCase();
  const map = {{ en: 'English', hi: 'Hindi', mr: 'Marathi', ta: 'Tamil' }};
  for (const [prefix, code] of Object.entries(map)) {{
    if (nav.startsWith(prefix) && languages.some(l => l.code === code)) return code;
  }}
  return null;
}}

async function loadLanguages() {{
  const r = await fetch('/api/qualify/languages?source=' + encodeURIComponent(SOURCE));
  const d = await r.json();
  if (d.bot_name) document.getElementById('botTitle').textContent = d.bot_name;
  if (d.welcome_text) document.getElementById('welcomeHeading').textContent = d.welcome_text;
  const suggested = suggestLanguageCode(d.languages);
  if (suggested) {{
    document.getElementById('localeHint').textContent =
      'Suggested for your browser: ' + suggested + ' — tap a language below to start.';
  }}
  const box = document.getElementById('langButtons');
  d.languages.forEach(l => {{
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'lang' + (l.code === suggested ? ' suggested' : '');
    b.textContent = l.label;
    b.onclick = () => startChat(l.code);
    box.appendChild(b);
  }});
}}

async function send(message) {{
  statusEl.textContent = '…thinking';
  try {{
    const r = await fetch('/api/qualify/chat', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{
        session_id: sessionId,
        language,
        source: SOURCE,
        channel: 'web',
        history,
        message,
      }}),
    }});
    const d = await r.json();
    statusEl.textContent = '';
    if (!r.ok) {{ render('error', '⚠ ' + (d.detail || 'error')); return; }}
    if (d.session_id) sessionId = d.session_id;
    render('bot', d.answer, d.citations);
    if (message) history.push({{ role: 'user', text: message }});
    history.push({{ role: 'model', text: d.answer }});
    persist();
    if (d.captured) note('✓ Lead captured — thank you!');
  }} catch (e) {{
    statusEl.textContent = '';
    render('error', '⚠ ' + e);
  }}
}}

function showChat() {{
  pick.classList.add('hidden');
  chat.classList.remove('hidden');
  form.classList.remove('hidden');
  document.getElementById('changeLang').classList.remove('hidden');
  input.focus();
}}

function startChat(code) {{
  language = code;
  persist();
  showChat();
  if (history.length === 0) send('');
  else history.forEach(m => render(m.role === 'model' ? 'bot' : 'user', m.text));
}}

document.getElementById('changeLang').addEventListener('click', () => {{
  if (!confirm('Change language? This clears the current conversation.')) return;
  history = [];
  language = null;
  chat.innerHTML = '';
  pick.classList.remove('hidden');
  chat.classList.add('hidden');
  form.classList.add('hidden');
  document.getElementById('changeLang').classList.add('hidden');
  document.getElementById('langButtons').innerHTML = '';
  loadLanguages();
  persist();
}});

form.addEventListener('submit', (e) => {{
  e.preventDefault();
  const text = input.value.trim();
  if (!text || !language) return;
  render('user', text);
  input.value = '';
  send(text);
}});

document.getElementById('restart').addEventListener('click', () => {{
  localStorage.removeItem(STORAGE_PREFIX + 'session');
  localStorage.removeItem(STORAGE_PREFIX + 'language');
  localStorage.removeItem(STORAGE_PREFIX + 'history');
  location.reload();
}});

if (language) {{
  showChat();
  history.forEach(m => render(m.role === 'model' ? 'bot' : 'user', m.text));
  if (history.length === 0) send('');
}} else {{
  loadLanguages();
}}
</script>
</body></html>"""


def register_qualify_routes(app) -> None:
    """Mount qualification API and pages on the FastAPI app."""

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def qualify_index():
        return qualify_page_html(admin_test=False)

    @app.get("/admin/test-chat", response_class=HTMLResponse, include_in_schema=False)
    def admin_test_chat():
        return qualify_page_html(admin_test=True)

    app.include_router(router)

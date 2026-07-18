"""Public web qualification chat — routes and UI for the conversation engine."""
from __future__ import annotations

import base64
import logging
import uuid
from time import perf_counter

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse

import admin_config
import config
import interactions
from conversation_engine import ConversationEngine, TurnInput, make_engine
import voice

log = logging.getLogger(__name__)

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


def _is_intro_turn(message: str | None, history: list) -> bool:
    return not (message or "").strip() and not history


def _reply_audio_fields(
    *,
    reply_text: str,
    language: str,
    bot_config: dict,
    is_intro_turn: bool,
    user_sent_voice: bool,
) -> dict:
    policy = bot_config.get("voice_policy", "intro_only")
    if not voice.should_speak(
        policy,
        is_intro_turn=is_intro_turn,
        user_sent_voice=user_sent_voice,
    ):
        return {}

    if is_intro_turn:
        intro = (bot_config.get("intro") or {}).get(language) or {}
        audio_url = intro.get("audio_url")
        if audio_url:
            return {"audio_url": audio_url}

    if not (reply_text or "").strip():
        return {}

    try:
        wav = voice.synthesize_speech(reply_text, language=language)
    except Exception:
        return {}

    return {
        "audio_mime": "audio/wav",
        "audio_base64": base64.b64encode(wav).decode("ascii"),
    }


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
def qualify_chat(
    payload: dict,
    x_load_test_token: str = Header(default=""),
):
    started = perf_counter()
    try:
        interaction_store = interactions.store_for_load_test_token(
            x_load_test_token
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error

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
    user_sent_voice = bool(payload.get("user_sent_voice"))

    from rag import has_client

    if not has_client():
        error = "Gemini API key is not configured"
        reply = "Sorry, the assistant is temporarily unavailable. Please try again later."
        _record_exchange_best_effort(
            interaction_store,
            session_id=session_id,
            channel=channel,
            source=source,
            language=language,
            message=message,
            answer=reply,
            latency_ms=_elapsed_ms(started),
            status="error",
            error=error,
            needs_review=True,
        )
        raise HTTPException(status_code=503, detail=reply)

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
        _record_exchange_best_effort(
            interaction_store,
            session_id=session_id,
            channel=channel,
            source=source,
            language=language,
            message=message,
            answer="Sorry, I could not answer that right now. Please try again shortly.",
            latency_ms=_elapsed_ms(started),
            status="error",
            error=str(e),
            needs_review=True,
        )
        raise HTTPException(
            status_code=503,
            detail="Sorry, I could not answer that right now. Please try again shortly.",
        ) from e
    except Exception as e:
        _record_exchange_best_effort(
            interaction_store,
            session_id=session_id,
            channel=channel,
            source=source,
            language=language,
            message=message,
            answer="Sorry, something went wrong. Please try again shortly.",
            latency_ms=_elapsed_ms(started),
            status="error",
            error=str(e),
            needs_review=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Sorry, something went wrong. Please try again shortly.",
        ) from e

    bot_config = admin_config.get_store().get()
    audio_fields = _reply_audio_fields(
        reply_text=out.reply_text,
        language=language,
        bot_config=bot_config,
        is_intro_turn=_is_intro_turn(message, history),
        user_sent_voice=user_sent_voice,
    )
    _record_exchange_best_effort(
        interaction_store,
        session_id=session_id,
        channel=channel,
        source=source,
        language=language,
        message=message,
        answer=out.reply_text,
        latency_ms=_elapsed_ms(started),
        citations=out.citations,
    )

    return {
        "answer": out.reply_text,
        "captured": out.captured,
        "citations": out.citations,
        "session_id": session_id,
        **audio_fields,
    }


def _elapsed_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)


def _record_exchange_best_effort(
    store: interactions.InteractionStore,
    *,
    session_id: str,
    channel: str,
    source: str,
    language: str,
    message: str | None,
    answer: str,
    latency_ms: int,
    status: str = "ok",
    error: str = "",
    needs_review: bool = False,
    citations: list[str] | None = None,
) -> None:
    try:
        store.record_exchange(
            session=session_id,
            channel=channel,
            source=source,
            language=language,
            user_message=message,
            assistant_message=answer,
            latency_ms=latency_ms,
            status=status,
            error=error,
            model=config.MODEL,
            citations=citations,
            needs_review=needs_review,
        )
    except Exception:
        log.exception("Could not persist interaction session=%s", session_id)


@router.post("/api/qualify/transcribe")
async def qualify_transcribe(
    audio: UploadFile = File(...),
    language: str = Form(default=""),
):
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

    raw = await audio.read()
    mime = audio.content_type or "audio/webm"
    lang = (language or "").strip() or None

    try:
        transcript = voice.transcribe_audio(raw, mime, language_hint=lang)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    if not transcript:
        raise HTTPException(
            status_code=400,
            detail="Could not hear speech. Try again closer to the microphone.",
        )

    return {"transcript": transcript}


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
  .msg-actions {{ margin-top: 6px; }}
  .msg-actions button {{ font-size: 12px; padding: 2px 8px; }}
  .saved {{ align-self: center; font-size: 12px; color: green; }}
  .cites {{ font-size: 11px; opacity: 0.7; margin-top: 6px; }}
  form {{ display: flex; gap: 8px; padding: 12px 16px; border-top: 1px solid #8884; align-items: center; }}
  form input {{ flex: 1; padding: 8px; font-size: 14px; }}
  button {{ padding: 8px 12px; cursor: pointer; font-size: 14px; }}
  #micBtn {{ min-width: 44px; }}
  #micBtn.recording {{ background: #ef4444; color: #fff; border-color: #ef4444; }}
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
  <p>
    Privacy notice: your conversation is stored for customer support and lead
    follow-up, and is automatically deleted after {config.INTERACTION_RETENTION_DAYS} days.
  </p>
  <div id="langButtons"></div>
</div>

<main id="chat" class="hidden"></main>
<form id="form" class="hidden">
  <input type="text" id="input" placeholder="Type your reply…" autocomplete="off">
  <button type="button" id="micBtn" title="Hold to speak">🎤</button>
  <button type="submit">Send</button>
</form>

<script>
const MAX_RECORD_SEC = {config.MAX_AUDIO_RECORD_SEC};
const params = new URLSearchParams(location.search);
const SOURCE = params.get('source') || 'web';
const STORAGE_PREFIX = 'tvs_qualify_' + SOURCE + '_';

let sessionId = localStorage.getItem(STORAGE_PREFIX + 'session') || ('web-' + Math.random().toString(36).slice(2, 10));
let language = localStorage.getItem(STORAGE_PREFIX + 'language') || null;
let history = JSON.parse(localStorage.getItem(STORAGE_PREFIX + 'history') || '[]');

const chat = document.getElementById('chat');
const form = document.getElementById('form');
const input = document.getElementById('input');
const micBtn = document.getElementById('micBtn');
const statusEl = document.getElementById('status');
const pick = document.getElementById('pick');

let mediaRecorder = null;
let recordChunks = [];
let recordTimer = null;
let micStream = null;

function persist() {{
  localStorage.setItem(STORAGE_PREFIX + 'session', sessionId);
  if (language) localStorage.setItem(STORAGE_PREFIX + 'language', language);
  localStorage.setItem(STORAGE_PREFIX + 'history', JSON.stringify(history));
}}

function render(role, text, cites, audio) {{
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.textContent = text;
  if (cites && cites.length) {{
    const c = document.createElement('div');
    c.className = 'cites';
    c.textContent = 'Sources: ' + cites.join(', ');
    div.appendChild(c);
  }}
  if (role === 'bot' && audio) {{
    const actions = document.createElement('div');
    actions.className = 'msg-actions';
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = '🔊 Play';
    btn.onclick = () => playBotAudio(audio);
    actions.appendChild(btn);
    div.appendChild(actions);
  }}
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}}

function audioPayloadFromResponse(d) {{
  if (d.audio_url) return {{ url: d.audio_url }};
  if (d.audio_base64) {{
    return {{
      url: 'data:' + (d.audio_mime || 'audio/wav') + ';base64,' + d.audio_base64,
    }};
  }}
  return null;
}}

function playBotAudio(audio) {{
  if (!audio || !audio.url) return;
  const el = new Audio(audio.url);
  el.play().catch(() => {{}});
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

async function send(message, opts) {{
  opts = opts || {{}};
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
        user_sent_voice: !!opts.userSentVoice,
      }}),
    }});
    const d = await r.json();
    statusEl.textContent = '';
    if (!r.ok) {{ render('error', '⚠ ' + (d.detail || 'error')); return; }}
    if (d.session_id) sessionId = d.session_id;
    const audio = audioPayloadFromResponse(d);
    render('bot', d.answer, d.citations, audio);
    if (audio) playBotAudio(audio);
    if (message) history.push({{ role: 'user', text: message }});
    history.push({{ role: 'model', text: d.answer }});
    persist();
    if (d.captured) note('✓ Lead captured — thank you!');
  }} catch (e) {{
    statusEl.textContent = '';
    render('error', '⚠ ' + e);
  }}
}}

function pickRecorderMime() {{
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/mp4',
  ];
  if (!window.MediaRecorder) return '';
  return candidates.find(m => MediaRecorder.isTypeSupported(m)) || '';
}}

async function stopMicStream() {{
  if (micStream) {{
    micStream.getTracks().forEach(t => t.stop());
    micStream = null;
  }}
}}

async function transcribeAndSend(blob, mimeType) {{
  statusEl.textContent = '…transcribing';
  const fd = new FormData();
  fd.append('audio', blob, 'recording.webm');
  fd.append('language', language || '');
  try {{
    const r = await fetch('/api/qualify/transcribe', {{ method: 'POST', body: fd }});
    const d = await r.json();
    statusEl.textContent = '';
    if (!r.ok) {{
      render('error', '⚠ ' + (d.detail || 'Could not transcribe'));
      return;
    }}
    const text = (d.transcript || '').trim();
    if (!text) {{
      render('error', '⚠ Could not hear speech. Try again.');
      return;
    }}
    render('user', text);
    await send(text, {{ userSentVoice: true }});
  }} catch (e) {{
    statusEl.textContent = '';
    render('error', '⚠ ' + e);
  }}
}}

async function stopRecording() {{
  if (recordTimer) {{
    clearTimeout(recordTimer);
    recordTimer = null;
  }}
  micBtn.classList.remove('recording');
  micBtn.title = 'Tap to speak';
  statusEl.textContent = '';
  if (!mediaRecorder || mediaRecorder.state === 'inactive') {{
    await stopMicStream();
    return;
  }}
  const rec = mediaRecorder;
  mediaRecorder = null;
  await new Promise(resolve => {{
    rec.onstop = resolve;
    rec.stop();
  }});
  await stopMicStream();
  const mimeType = rec.mimeType || 'audio/webm';
  const blob = new Blob(recordChunks, {{ type: mimeType }});
  recordChunks = [];
  if (blob.size === 0) {{
    render('error', '⚠ No audio captured. Try again.');
    return;
  }}
  await transcribeAndSend(blob, mimeType);
}}

async function startRecording() {{
  if (!language) return;
  if (!navigator.mediaDevices || !window.MediaRecorder) {{
    render('error', '⚠ Voice input is not supported in this browser.');
    return;
  }}
  const mimeType = pickRecorderMime();
  if (!mimeType) {{
    render('error', '⚠ Voice recording is not supported in this browser.');
    return;
  }}
  try {{
    micStream = await navigator.mediaDevices.getUserMedia({{ audio: true }});
  }} catch (e) {{
    render('error', '⚠ Microphone permission denied.');
    return;
  }}
  recordChunks = [];
  mediaRecorder = new MediaRecorder(micStream, {{ mimeType }});
  mediaRecorder.ondataavailable = (ev) => {{
    if (ev.data && ev.data.size) recordChunks.push(ev.data);
  }};
  mediaRecorder.start();
  micBtn.classList.add('recording');
  micBtn.title = 'Tap to stop';
  statusEl.textContent = 'Recording… tap mic to stop';
  recordTimer = setTimeout(() => stopRecording(), MAX_RECORD_SEC * 1000);
}}

micBtn.addEventListener('click', async () => {{
  if (mediaRecorder && mediaRecorder.state === 'recording') {{
    await stopRecording();
  }} else {{
    await startRecording();
  }}
}});

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

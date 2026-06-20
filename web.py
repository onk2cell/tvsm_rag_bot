"""Browser playground for the TVS RAG bot — no WhatsApp, no Redis.

Features
  - Pick the knowledge base (File Search store) to answer from, or use the default.
  - Pick the Gemini model at runtime.
  - Continuous chat over a WebSocket (/ws/chat). The browser owns the conversation
    history (saved in localStorage), so it survives a page refresh. "Clear chat" resets it.

End users do NOT upload anything — the knowledge bases are managed separately
(e.g. with build_tvs_3w_kb.py / index_document.py).

Run:  uvicorn web:app --reload --port 8000     then open  http://localhost:8000
"""
import base64
import os
import secrets
import tempfile
import time

from fastapi import (
    Depends, FastAPI, File, Form, Header, HTTPException, UploadFile,
    WebSocket, WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse

import config
from rag import ask, get_client, has_client, set_api_key


class BasicAuthMiddleware:
    """Password-protect the whole app (HTTP + WebSocket) via HTTP Basic Auth.

    Disabled when config.APP_PASSWORD is empty. The browser caches the credentials
    after loading any page, so it also sends them on the WebSocket handshake.
    """

    def __init__(self, app, username: str, password: str):
        self.app = app
        self.username = username
        self.password = password

    async def __call__(self, scope, receive, send):
        if self.password and scope["type"] in ("http", "websocket"):
            headers = dict(scope.get("headers") or [])
            if not self._authorised(headers.get(b"authorization", b"").decode()):
                if scope["type"] == "http":
                    await send({"type": "http.response.start", "status": 401, "headers": [
                        (b"www-authenticate", b'Basic realm="TVS RAG"'),
                        (b"content-type", b"text/plain"),
                    ]})
                    await send({"type": "http.response.body", "body": b"Unauthorized"})
                else:
                    await send({"type": "websocket.close", "code": 1008})
                return
        await self.app(scope, receive, send)

    def _authorised(self, header: str) -> bool:
        if not header.startswith("Basic "):
            return False
        try:
            user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
        except Exception:
            return False
        return (secrets.compare_digest(user, self.username)
                and secrets.compare_digest(pw, self.password))


def require_admin(x_admin_token: str = Header(default="")):
    """Gate admin endpoints behind config.ADMIN_TOKEN (sent as X-Admin-Token header)."""
    if not config.ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="Admin is disabled: set ADMIN_TOKEN in .env")
    if x_admin_token != config.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing admin token")

app = FastAPI(title="TVS RAG Playground")
app.add_middleware(BasicAuthMiddleware, username=config.APP_USER, password=config.APP_PASSWORD)

CURATED = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
]


@app.get("/models")
def list_models():
    """Gemini models that support generateContent. Falls back to a curated list."""
    names = []
    try:
        for m in get_client().models.list():
            actions = getattr(m, "supported_actions", None) or []
            if "generateContent" in actions and "gemini" in m.name:
                names.append(m.name.replace("models/", ""))
    except Exception:
        pass
    ordered = [m for m in CURATED if m in names] + sorted(n for n in names if n not in CURATED)
    return {"default": config.MODEL, "models": ordered or CURATED}


@app.get("/stores")
def list_stores():
    """Available knowledge bases (File Search stores) to choose from."""
    stores = []
    try:
        for s in get_client().file_search_stores.list():
            stores.append({"name": s.name, "label": getattr(s, "display_name", None) or s.name})
    except Exception:
        pass
    if not any(s["name"] == config.FILE_SEARCH_STORE for s in stores):
        stores.insert(0, {"name": config.FILE_SEARCH_STORE, "label": config.FILE_SEARCH_STORE})
    return {"default": config.FILE_SEARCH_STORE, "stores": stores}


# ----------------------------------------------------------------------------
# Admin endpoints (token-gated) — create / populate / delete knowledge bases.
# ----------------------------------------------------------------------------
@app.get("/admin/gemini-key")
def admin_gemini_key_status(_=Depends(require_admin)):
    """Report whether a Gemini API key is currently configured (never echoes it)."""
    return {"configured": has_client()}


@app.post("/admin/gemini-key")
def admin_set_gemini_key(payload: dict, _=Depends(require_admin)):
    """Set / replace the Gemini API key used to answer questions (kept in memory)."""
    api_key = (payload.get("api_key") or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="api_key is required")
    try:
        set_api_key(api_key, validate=True)   # rejects a bad key without swapping
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not use that API key: {e}")
    return {"configured": True}


@app.post("/admin/stores")
def admin_create_store(payload: dict, _=Depends(require_admin)):
    """Create a new, empty knowledge base (File Search store)."""
    label = (payload.get("display_name") or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="display_name is required")
    store = get_client().file_search_stores.create(config={"display_name": label})
    return {"name": store.name, "label": label}


@app.post("/admin/upload")
async def admin_upload(store: str = Form(...), file: UploadFile = File(...), _=Depends(require_admin)):
    """Index an uploaded document into the given knowledge base."""
    data = await file.read()
    suffix = os.path.splitext(file.filename)[1] or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        gc = get_client()
        op = gc.file_search_stores.upload_to_file_search_store(
            file_search_store_name=store,
            file=tmp_path,
            config={"display_name": file.filename},
        )
        waited = 0
        while not getattr(op, "done", False) and waited < 300:
            time.sleep(3)
            waited += 3
            op = gc.operations.get(op)
        return {"status": "indexed", "filename": file.filename, "store": store}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)


@app.delete("/admin/stores")
def admin_delete_store(name: str, _=Depends(require_admin)):
    """Delete a knowledge base and everything in it."""
    get_client().file_search_stores.delete(name=name, config={"force": True})
    return {"deleted": name}


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return ADMIN_HTML


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    """Continuous chat. The browser sends prior history with each message, so the
    conversation survives a page refresh. The chosen model/store apply per message."""
    await ws.accept()
    try:
        while True:
            payload = await ws.receive_json()
            message = (payload.get("message") or "").strip()
            model = payload.get("model") or config.MODEL
            store = payload.get("store") or config.FILE_SEARCH_STORE
            history = payload.get("history") or []
            history = history[-(config.MAX_HISTORY_TURNS * 2):]   # bound context + cost
            if not message:
                continue
            try:
                answer, citations = ask(message, history, model=model, store=store)
            except Exception as e:
                await ws.send_json({"error": str(e)})
                continue
            await ws.send_json({"answer": answer, "citations": citations, "model": model})
    except WebSocketDisconnect:
        pass


@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TVS RAG Playground</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { font-family: system-ui, sans-serif; margin: 0; height: 100vh; display: flex; flex-direction: column; }
  header { padding: 10px 16px; border-bottom: 1px solid #8884; display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
  header h1 { font-size: 16px; margin: 0 8px 0 0; }
  .status { font-size: 12px; margin-left: auto; }
  label { font-size: 13px; }
  select, input[type=text] { padding: 6px 8px; font-size: 14px; }
  button { padding: 6px 12px; cursor: pointer; font-size: 14px; }
  #chat { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
  .msg { max-width: 70%; padding: 8px 12px; border-radius: 12px; white-space: pre-wrap; line-height: 1.4; }
  .msg.user { align-self: flex-end; background: #2563eb; color: #fff; }
  .msg.bot  { align-self: flex-start; background: #8882; }
  .msg.error { align-self: flex-start; background: #ef444433; color: #b91c1c; }
  .cites { font-size: 11px; opacity: 0.7; margin-top: 6px; }
  form { display: flex; gap: 8px; padding: 12px 16px; border-top: 1px solid #8884; }
  form input { flex: 1; }
</style>
</head>
<body>
<header>
  <h1>TVS RAG Playground</h1>
  <label>Knowledge base: <select id="store"></select></label>
  <label>Model: <select id="model"></select></label>
  <button id="clearBtn" type="button">Clear chat</button>
  <span id="status" class="status">connecting…</span>
</header>
<main id="chat"></main>
<form id="form">
  <input type="text" id="input" placeholder="Ask in any language…" autocomplete="off">
  <button type="submit">Send</button>
</form>
<script>
const STORAGE_KEY = 'tvs_chat_history';
const chat = document.getElementById('chat');
const input = document.getElementById('input');
const modelSel = document.getElementById('model');
const storeSel = document.getElementById('store');
const statusEl = document.getElementById('status');

// history = [{role:'user'|'model', text}]  — persisted so refresh keeps the conversation
let history = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');

function save() { localStorage.setItem(STORAGE_KEY, JSON.stringify(history)); }

function render(role, text, cites) {
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.textContent = text;
  if (cites && cites.length) {
    const c = document.createElement('div');
    c.className = 'cites';
    c.textContent = 'Sources: ' + cites.join(', ');
    div.appendChild(c);
  }
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

// restore previous conversation on load
history.forEach(m => render(m.role === 'model' ? 'bot' : 'user', m.text));

fetch('/models').then(r => r.json()).then(d => {
  d.models.forEach(m => {
    const o = document.createElement('option');
    o.value = m; o.textContent = m;
    if (m === d.default) o.selected = true;
    modelSel.appendChild(o);
  });
});

fetch('/stores').then(r => r.json()).then(d => {
  d.stores.forEach(s => {
    const o = document.createElement('option');
    o.value = s.name; o.textContent = s.label;
    if (s.name === d.default) o.selected = true;
    storeSel.appendChild(o);
  });
});

let ws;
function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(proto + '://' + location.host + '/ws/chat');
  ws.onopen = () => { statusEl.textContent = '● connected'; statusEl.style.color = 'green'; };
  ws.onclose = () => { statusEl.textContent = '● disconnected'; statusEl.style.color = 'crimson'; };
  ws.onmessage = (e) => {
    const d = JSON.parse(e.data);
    if (d.error) { render('error', '⚠ ' + d.error); return; }
    render('bot', d.answer, d.citations);
    history.push({ role: 'model', text: d.answer });
    save();
  };
}
connect();

document.getElementById('form').addEventListener('submit', (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || !ws || ws.readyState !== 1) return;
  render('user', text);
  // send prior history (everything before this message), then record the new turn
  ws.send(JSON.stringify({ message: text, model: modelSel.value, store: storeSel.value, history: history }));
  history.push({ role: 'user', text: text });
  save();
  input.value = '';
});

document.getElementById('clearBtn').addEventListener('click', () => {
  history = [];
  save();
  chat.innerHTML = '';
});
</script>
</body>
</html>"""


ADMIN_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TVS RAG Admin</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { font-family: system-ui, sans-serif; max-width: 760px; margin: 0 auto; padding: 24px; }
  h1 { font-size: 20px; }
  section { border: 1px solid #8884; border-radius: 10px; padding: 16px; margin: 16px 0; }
  h2 { font-size: 15px; margin-top: 0; }
  input, select, button { padding: 7px 10px; font-size: 14px; }
  input[type=text], select { min-width: 240px; }
  button { cursor: pointer; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin: 6px 0; }
  .msg { font-size: 13px; margin-left: 6px; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  td, th { border-bottom: 1px solid #8883; padding: 6px 8px; text-align: left; }
  .danger { color: crimson; }
</style>
</head>
<body>
<h1>TVS RAG — Admin</h1>

<section>
  <h2>Admin token</h2>
  <div class="row">
    <input type="password" id="token" placeholder="X-Admin-Token (from .env)">
    <button id="saveToken" type="button">Save</button>
    <span id="tokenMsg" class="msg"></span>
  </div>
</section>

<section>
  <h2>Gemini API key</h2>
  <div class="row">
    <input type="password" id="geminiKey" placeholder="Paste a Gemini API key">
    <button id="saveKey" type="button">Save key</button>
    <span id="keyStatus" class="msg"></span>
  </div>
  <p class="msg" style="opacity:.6">Kept in memory only — used for answering and managing knowledge bases. Resets to the .env key on restart.</p>
</section>

<section>
  <h2>Create a new knowledge base</h2>
  <div class="row">
    <input type="text" id="newName" placeholder="Display name, e.g. tvs-spare-parts">
    <button id="createBtn" type="button">Create</button>
    <span id="createMsg" class="msg"></span>
  </div>
</section>

<section>
  <h2>Upload a document into a knowledge base</h2>
  <div class="row">
    <select id="storeSel"></select>
    <input type="file" id="file">
    <button id="uploadBtn" type="button">Upload &amp; index</button>
    <span id="uploadMsg" class="msg"></span>
  </div>
</section>

<section>
  <h2>Existing knowledge bases</h2>
  <table id="storeTable"><tbody></tbody></table>
</section>

<p><a href="/">&larr; Back to chat</a></p>

<script>
const tokenInput = document.getElementById('token');
tokenInput.value = sessionStorage.getItem('admin_token') || '';

function headers() { return { 'X-Admin-Token': tokenInput.value }; }

document.getElementById('saveToken').addEventListener('click', () => {
  sessionStorage.setItem('admin_token', tokenInput.value);
  document.getElementById('tokenMsg').textContent = 'saved';
  refreshKeyStatus();
});

const keyStatus = document.getElementById('keyStatus');

async function refreshKeyStatus() {
  if (!tokenInput.value) { keyStatus.textContent = ''; return; }
  try {
    const r = await fetch('/admin/gemini-key', { headers: headers() });
    if (!r.ok) { keyStatus.textContent = ''; return; }
    const d = await r.json();
    keyStatus.textContent = d.configured ? '✓ a key is configured' : 'no key configured';
  } catch (e) { keyStatus.textContent = ''; }
}

document.getElementById('saveKey').addEventListener('click', async () => {
  const keyInput = document.getElementById('geminiKey');
  const api_key = keyInput.value.trim();
  if (!api_key) { keyStatus.textContent = 'enter a key'; return; }
  keyStatus.textContent = 'validating…';
  const r = await fetch('/admin/gemini-key', {
    method: 'POST',
    headers: { ...headers(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key }),
  });
  const d = await r.json();
  if (r.ok) {
    keyStatus.textContent = '✓ key saved';
    keyInput.value = '';
    loadStores();
  } else {
    keyStatus.textContent = '✗ ' + (d.detail || 'failed');
  }
});

refreshKeyStatus();

async function loadStores() {
  const d = await (await fetch('/stores')).json();
  const sel = document.getElementById('storeSel');
  sel.innerHTML = '';
  const tb = document.querySelector('#storeTable tbody');
  tb.innerHTML = '';
  d.stores.forEach(s => {
    const o = document.createElement('option');
    o.value = s.name; o.textContent = s.label;
    sel.appendChild(o);

    const tr = document.createElement('tr');
    const isDefault = s.name === d.default ? ' (default)' : '';
    tr.innerHTML = '<td>' + s.label + isDefault + '</td><td style="opacity:.6">' + s.name + '</td>';
    const td = document.createElement('td');
    const btn = document.createElement('button');
    btn.textContent = 'Delete'; btn.className = 'danger';
    btn.onclick = () => deleteStore(s.name, s.label);
    td.appendChild(btn); tr.appendChild(td);
    tb.appendChild(tr);
  });
}

document.getElementById('createBtn').addEventListener('click', async () => {
  const name = document.getElementById('newName').value.trim();
  const msg = document.getElementById('createMsg');
  if (!name) { msg.textContent = 'enter a name'; return; }
  msg.textContent = 'creating…';
  const r = await fetch('/admin/stores', {
    method: 'POST',
    headers: { ...headers(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ display_name: name }),
  });
  const d = await r.json();
  msg.textContent = r.ok ? ('✓ created') : ('✗ ' + (d.detail || 'failed'));
  if (r.ok) { document.getElementById('newName').value = ''; loadStores(); }
});

document.getElementById('uploadBtn').addEventListener('click', async () => {
  const f = document.getElementById('file').files[0];
  const store = document.getElementById('storeSel').value;
  const msg = document.getElementById('uploadMsg');
  if (!f) { msg.textContent = 'choose a file'; return; }
  if (!store) { msg.textContent = 'no knowledge base selected'; return; }
  msg.textContent = 'uploading & indexing… (can take a minute)';
  const fd = new FormData();
  fd.append('store', store);
  fd.append('file', f);
  const r = await fetch('/admin/upload', { method: 'POST', headers: headers(), body: fd });
  const d = await r.json();
  msg.textContent = r.ok ? ('✓ indexed: ' + d.filename) : ('✗ ' + (d.detail || 'failed'));
});

async function deleteStore(name, label) {
  if (!confirm('Delete knowledge base "' + label + '" and all its documents?')) return;
  const r = await fetch('/admin/stores?name=' + encodeURIComponent(name), {
    method: 'DELETE', headers: headers(),
  });
  if (r.ok) loadStores();
  else { const d = await r.json(); alert('Failed: ' + (d.detail || r.status)); }
}

loadStores();
</script>
</body>
</html>"""

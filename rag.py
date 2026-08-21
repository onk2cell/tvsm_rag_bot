"""The RAG layer: ask a question, get a grounded answer + source titles."""
from __future__ import annotations

import os
import time
from pathlib import Path

from google import genai
from google.genai import errors as genai_errors

import config

# The Gemini client is swappable at runtime: an admin can supply a key via the
# admin page (see web.py), which calls persist_api_key() to store and rebuild it.
# We initialise from GEMINI_API_KEY in the environment if it's present, and a key
# persisted to config.GEMINI_KEY_RUNTIME_PATH overrides it. Because the admin app
# and the message worker are separate processes, the persisted key is reloaded
# lazily whenever the file changes — see _maybe_load_runtime_key().
_client = None
_runtime_key_mtime: float | None = None


def _runtime_key_path() -> Path:
    return Path(config.GEMINI_KEY_RUNTIME_PATH)


def set_api_key(api_key: str, validate: bool = False) -> None:
    """(Re)create the Gemini client with the given API key.

    If validate=True, the key is checked with a cheap authenticated call before
    it replaces the current client, so a bad key leaves the old one in place.
    """
    global _client
    if not api_key:
        raise ValueError("API key must not be empty")
    candidate = genai.Client(api_key=api_key)
    if validate:
        list(candidate.models.list())   # raises if the key is invalid
    _client = candidate


def _maybe_load_runtime_key() -> None:
    """Adopt the persisted runtime key when the file appears or changes.

    Called on every get_client()/has_client() so a key set in the admin process
    is picked up by the worker process on its next turn — no restart needed.
    """
    global _runtime_key_mtime
    path = _runtime_key_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return
    if mtime == _runtime_key_mtime:
        return
    key = path.read_text(encoding="utf-8").strip()
    if key:
        set_api_key(key)
        _runtime_key_mtime = mtime


def persist_api_key(api_key: str, validate: bool = True) -> None:
    """Validate, activate, and persist an admin-supplied key to disk (0600).

    Persisting under data/ lets the key survive restarts and reach the separate
    worker process via _maybe_load_runtime_key().
    """
    global _runtime_key_mtime
    if not api_key or not api_key.strip():
        raise ValueError("API key must not be empty")
    api_key = api_key.strip()
    set_api_key(api_key, validate=validate)   # raises on a bad key before we save
    path = _runtime_key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(api_key, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    _runtime_key_mtime = path.stat().st_mtime


def clear_persisted_key() -> None:
    """Remove the persisted runtime key and fall back to the env key, if any."""
    global _client, _runtime_key_mtime
    try:
        _runtime_key_path().unlink()
    except FileNotFoundError:
        pass
    _runtime_key_mtime = None
    _client = None
    if config.GEMINI_API_KEY:
        set_api_key(config.GEMINI_API_KEY)


def runtime_key_active() -> bool:
    """True when a key persisted from the admin page is in effect."""
    return _runtime_key_path().exists()


def get_client():
    """Return the active Gemini client, or explain how to configure one."""
    _maybe_load_runtime_key()
    if _client is None:
        raise RuntimeError(
            "Gemini API key is not configured. Set GEMINI_API_KEY in .env, "
            "or add it on the admin page."
        )
    return _client


def has_client() -> bool:
    _maybe_load_runtime_key()
    return _client is not None


if config.GEMINI_API_KEY:
    set_api_key(config.GEMINI_API_KEY)
_maybe_load_runtime_key()   # a persisted admin key overrides the env key

def _build_contents(history: list, question: str) -> list:
    """Turn stored history + the new question into Gemini 'contents'."""
    contents = []
    for turn in history:
        role = "model" if turn.get("role") == "model" else "user"
        contents.append({"role": role, "parts": [{"text": turn["text"]}]})
    contents.append({"role": "user", "parts": [{"text": question}]})
    return contents


def _extract_citations(resp) -> list:
    """Pull the source snippets the answer was grounded on.

    Defensive: the exact attribute path can vary by SDK version, so we fail soft.
    """
    cites: list = []
    try:
        meta = resp.candidates[0].grounding_metadata
        for chunk in (meta.grounding_chunks or []):
            ctx = getattr(chunk, "retrieved_context", None)
            title = getattr(ctx, "title", None) if ctx else None
            if title:
                cites.append(title)
    except (AttributeError, IndexError, TypeError):
        pass
    return list(dict.fromkeys(cites))     # de-duplicate, preserve order


def ask(question: str, history: list | None = None, model: str | None = None,
        store: str | None = None) -> tuple[str, list]:
    """Return (answer_text, source_titles). Retries transient errors up to 3x.

    `model` overrides the default LLM; `store` overrides the default knowledge base
    (File Search store) — both per request. On a 429 (quota / rate limit) we stop
    immediately, since retrying only burns more quota.
    """
    contents = _build_contents(history or [], question)
    model = model or config.MODEL
    store = store or config.FILE_SEARCH_STORE
    last_err = None
    client = get_client()
    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=contents,
                config={
                    "system_instruction": SYSTEM,
                    "tools": [
                        {"file_search": {"file_search_store_names": [store]}}
                    ],
                    "temperature": 0.2,
                },
            )
            return resp.text, _extract_citations(resp)
        except genai_errors.ClientError as e:
            last_err = e
            if e.code == 429:           # quota / rate limit — don't retry, it won't help
                break
            time.sleep(1.5 * (attempt + 1))
        except Exception as e:          # transient network/server errors — retry
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise last_err

"""The RAG layer: ask a question, get a grounded answer + source titles."""
from __future__ import annotations

import time

from google import genai
from google.genai import errors as genai_errors

import config

# The Gemini client is swappable at runtime: an admin can supply a key via the
# admin page (see web.py), which calls set_api_key() to rebuild it. We initialise
# from GEMINI_API_KEY in the environment if it's present.
_client = None


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


def get_client():
    """Return the active Gemini client, or explain how to configure one."""
    if _client is None:
        raise RuntimeError(
            "Gemini API key is not configured. Set GEMINI_API_KEY in .env, "
            "or add it on the admin page."
        )
    return _client


def has_client() -> bool:
    return _client is not None


if config.GEMINI_API_KEY:
    set_api_key(config.GEMINI_API_KEY)

SYSTEM = (
    "You are TVS Motor's helpful assistant for TVS three-wheelers. You help with their "
    "specifications, features, colours, warranty, AND loan / financing document requirements "
    "and eligibility. Answer using ONLY the provided documents (the knowledge base). "
    "Loan and finance questions ARE in scope when the documents cover them - answer them "
    "normally; do NOT refuse them. Only if the specific answer is genuinely not in the "
    "documents, say you don't have that detail and suggest contacting TVS support or the dealer. "
    "Keep replies short and clear for WhatsApp. Reply in the same language the user used."
)


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

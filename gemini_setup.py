"""Gemini-backed tools shared by the LangGraph flows.

``search_web`` answers a question with Gemini grounded in Google Search. It
uses the same client as the rest of the bot (rag.get_client), so the key an
operator sets on the admin page applies here too, with no restart.
"""
from __future__ import annotations

from langchain_core.tools import tool

# A grounded answer to a one-line question is a sentence or two; the cap only
# bounds what a caller has to parse or log, it never truncates a pincode.
DEFAULT_MAX_CHARS = 600


def grounded_search(query: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Plain function behind the tool, so callers that already have a query
    string (and tests that fake the client) need not go through invoke()."""
    from google.genai import types

    from bot.config import MODEL_FAST
    from rag import get_client

    response = get_client().models.generate_content(
        model=MODEL_FAST,
        contents=query,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0,
        ),
    )
    return (response.text or "").strip()[:max_chars]


@tool
def search_web(query: str, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Answer `query` using Gemini with Google Search grounding. Returns the
    model's text answer, cut to `max_chars` characters."""
    return grounded_search(query, max_chars=max_chars)

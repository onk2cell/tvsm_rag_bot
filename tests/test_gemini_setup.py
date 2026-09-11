"""search_web: Gemini with Google Search grounding, on the bot's own client."""
from __future__ import annotations

import gemini_setup


class _Response:
    def __init__(self, text):
        self.text = text


class _Models:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return _Response(self.text)


class _Client:
    def __init__(self, text):
        self.models = _Models(text)


def test_search_web_uses_google_search_tool_on_the_shared_client(monkeypatch):
    client = _Client("  411001 Pune  ")
    monkeypatch.setattr("rag.get_client", lambda: client)

    answer = gemini_setup.search_web.invoke({"query": "pincode for Pune"})

    assert answer == "411001 Pune"
    call = client.models.calls[0]
    assert call["contents"] == "pincode for Pune"
    tools = call["config"].tools
    assert len(tools) == 1 and tools[0].google_search is not None
    assert call["config"].temperature == 0


def test_search_web_caps_the_answer(monkeypatch):
    client = _Client("x" * 1000)
    monkeypatch.setattr("rag.get_client", lambda: client)

    assert len(gemini_setup.search_web.invoke({"query": "q"})) == gemini_setup.DEFAULT_MAX_CHARS
    assert len(gemini_setup.search_web.invoke({"query": "q", "max_chars": 40})) == 40


def test_search_web_tolerates_an_empty_answer(monkeypatch):
    monkeypatch.setattr("rag.get_client", lambda: _Client(None))
    assert gemini_setup.search_web.invoke({"query": "q"}) == ""

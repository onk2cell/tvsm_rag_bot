"""Pytest fixtures — set env before app modules load."""
from __future__ import annotations

import os

import pytest

# Minimal env so config.py imports without a real deployment.
os.environ.setdefault("FILE_SEARCH_STORE", "fileSearchStores/test")
os.environ.setdefault("ADMIN_TOKEN", "admin-test-token")
os.environ.setdefault("ADMIN_CONFIG_PATH", "data/test_admin_config.json")


@pytest.fixture(autouse=True)
def stub_turn_classifiers(monkeypatch, request):
    """Keep the suite hermetic and fast.

    These classifiers run on ordinary inbound turns, so without stubbing,
    every processor test would make a real Gemini call — the suite would
    depend on a live API key and on what the model happens to answer.

    Each stub keeps the deterministic half of the real graph and drops only
    the LLM branch, replacing it with that branch's production safe default.
    Tests exercising an LLM-decided branch override these with their own
    monkeypatch, which wins because it is applied later.
    """
    if request.node.get_closest_marker("live_classifier"):
        return

    # Safe default: the turn continues as normal conversation instead of
    # being answered with a canned location reply.
    monkeypatch.setattr(
        "client_processing.classify_location_reply",
        lambda _message, _last_bot_message="": "other",
        raising=False,
    )

    def offline_language_switch(message: str) -> str:
        from bot.graph import _route_language_switch
        from client_language import parse_language_choice

        state = {"user_message": message, "language": ""}
        if _route_language_switch(state) == "explicit":
            return parse_language_choice(message or "")
        return ""  # safe default: keep the language already in use

    monkeypatch.setattr(
        "client_processing.classify_language_switch",
        offline_language_switch,
        raising=False,
    )

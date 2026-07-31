"""Tests for bot/graph.py's still-interested classifier graph."""
from __future__ import annotations

import pytest

from bot.graph import StillInterestedClassification, classify_still_interested_reply


def _forbid_llm(monkeypatch):
    """Fail loudly if the regex fast path ever falls through to the LLM."""

    def _raise(tier="smart"):
        raise AssertionError(f"get_llm({tier!r}) should not be called on the fast path")

    monkeypatch.setattr("bot.graph.get_llm", _raise)


def test_clear_yes_uses_regex_fast_path_no_llm_call(monkeypatch):
    _forbid_llm(monkeypatch)
    assert classify_still_interested_reply("1") is False
    assert classify_still_interested_reply("yes definitely") is False


def test_clear_no_uses_regex_fast_path_no_llm_call(monkeypatch):
    _forbid_llm(monkeypatch)
    assert classify_still_interested_reply("2") is True
    assert classify_still_interested_reply("no i dont want to buy this vehicle") is True


class _FakeClassifierLLM:
    def __init__(self, declining: bool):
        self._declining = declining
        self.prompts: list[str] = []

    def with_structured_output(self, schema):
        assert schema is StillInterestedClassification
        return self

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        return StillInterestedClassification(declining=self._declining)


def test_ambiguous_reply_falls_back_to_llm_classifier(monkeypatch):
    fake = _FakeClassifierLLM(declining=False)
    monkeypatch.setattr("bot.graph.get_llm", lambda tier="smart": fake)

    result = classify_still_interested_reply("not sure, tell me about the Duramax")

    assert result is False
    assert fake.prompts  # the LLM was actually consulted
    assert "Duramax" in fake.prompts[0]


def test_ambiguous_reply_llm_classifies_as_declining(monkeypatch):
    fake = _FakeClassifierLLM(declining=True)
    monkeypatch.setattr("bot.graph.get_llm", lambda tier="smart": fake)

    assert classify_still_interested_reply("hmm let me think about it") is True


class _BrokenClassifierLLM:
    def with_structured_output(self, schema):
        return self

    def invoke(self, prompt: str):
        raise RuntimeError("boom")


def test_classifier_failure_defaults_to_proceeding(monkeypatch):
    monkeypatch.setattr("bot.graph.get_llm", lambda tier="smart": _BrokenClassifierLLM())

    # Should not raise — falls back to the safe default (proceed).
    assert classify_still_interested_reply("something ambiguous") is False

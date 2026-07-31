"""Parity tests for bot.engine.LangGraphEngine against
conversation_engine.ConversationEngine — same TurnInput -> TurnOutput
contract, scripted FakeLLM standing in for Gemini (mirrors
tests/test_conversation_engine.py's FakeLLM pattern)."""
from __future__ import annotations

import csv
import json

import pytest

import admin_config
from admin_config import AdminConfigStore
from bot.engine import LangGraphEngine
from conversation_engine import ConversationEngine, GenerateResult, TurnInput
from leads import LeadWriter


class FakeLLM:
    """Scripted LLM matching the LLMPort protocol used by both engines."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def generate(self, *, system_instruction: str, contents: list[dict]) -> GenerateResult:
        self.calls.append({"system_instruction": system_instruction, "contents": contents})
        if not self.responses:
            raise RuntimeError("FakeLLM out of responses")
        return GenerateResult(text=self.responses.pop(0))


@pytest.fixture
def stores(tmp_path):
    admin_config.reset_store_for_tests()
    cfg_path = tmp_path / "admin_config.json"
    leads_path = tmp_path / "leads.csv"
    config_store = AdminConfigStore(cfg_path)
    config_store.ensure_seeded()
    lead_writer = LeadWriter(leads_path, config_store)
    return config_store, lead_writer, leads_path


def _langgraph_engine(config_store, lead_writer, llm, monkeypatch):
    monkeypatch.setattr("bot.graph.get_llm", lambda tier="smart": llm)
    return LangGraphEngine(config_store=config_store, lead_writer=lead_writer)


def test_reply_text_and_citations_match_conversation_engine(stores, monkeypatch):
    config_store, lead_writer, _ = stores
    reply = "Great, which model interests you most?"

    legacy = ConversationEngine(
        config_store=config_store, llm=FakeLLM([reply]), lead_writer=lead_writer
    )
    legacy_out = legacy.handle_turn(
        TurnInput(session_id="s1", language="English", message="hi")
    )

    graph_engine = _langgraph_engine(config_store, lead_writer, FakeLLM([reply]), monkeypatch)
    graph_out = graph_engine.handle_turn(
        TurnInput(session_id="s1", language="English", message="hi")
    )

    assert graph_out.reply_text == legacy_out.reply_text == reply
    assert graph_out.captured == legacy_out.captured is False


def test_profile_json_stripped_and_captured(stores, monkeypatch):
    config_store, lead_writer, leads_path = stores
    profile = {"product_interest": "King EV MAX", "lead_quality": "WARM"}
    raw = f"Thanks! We will call you.\nPROFILE_JSON:{json.dumps(profile)}"

    engine = _langgraph_engine(config_store, lead_writer, FakeLLM([raw]), monkeypatch)
    out = engine.handle_turn(
        TurnInput(
            session_id="web-abc",
            language="English",
            message="yes I have licence",
            channel="web",
            source="ricshow",
        )
    )

    assert out.captured is True
    assert "PROFILE_JSON" not in out.reply_text
    assert out.profile == profile

    rows = list(csv.DictReader(leads_path.open(encoding="utf-8-sig")))
    assert len(rows) == 1
    assert rows[0]["product_interest"] == "King EV MAX"
    assert rows[0]["session"] == "web-abc"


def test_system_instruction_carries_language_and_product_hint(stores, monkeypatch):
    config_store, lead_writer, _ = stores
    llm = FakeLLM(["Noted."])
    engine = _langgraph_engine(config_store, lead_writer, llm, monkeypatch)

    engine.handle_turn(
        TurnInput(
            session_id="s1",
            language="Hindi",
            message="EV MAX ke baare mein batao",
            product_hint="King EV MAX",
            confirm_crm_dealer=True,
        )
    )

    system = llm.calls[0]["system_instruction"]
    assert "Hindi" in system
    assert "King EV MAX" in system
    assert "Do NOT mention CRM" in system


def test_history_passed_through_to_contents(stores, monkeypatch):
    config_store, lead_writer, _ = stores
    llm = FakeLLM(["CNG King Deluxe gets ~50 km/kg. Which model interests you most?"])
    engine = _langgraph_engine(config_store, lead_writer, llm, monkeypatch)

    history = [
        {"role": "model", "text": "Which model?"},
        {"role": "user", "text": "King Deluxe"},
    ]
    engine.handle_turn(
        TurnInput(
            session_id="s1",
            language="Hindi",
            message="CNG mileage kya hai?",
            history=history,
        )
    )

    contents = llm.calls[0]["contents"]
    assert contents[0]["role"] == "user"
    assert contents[-1]["parts"][0]["text"] == "CNG mileage kya hai?"


def test_no_reply_text_when_llm_returns_only_profile(stores, monkeypatch):
    config_store, lead_writer, _ = stores
    profile = {"product_interest": "King Deluxe"}
    llm = FakeLLM([f"PROFILE_JSON:{json.dumps(profile)}"])
    engine = _langgraph_engine(config_store, lead_writer, llm, monkeypatch)

    out = engine.handle_turn(TurnInput(session_id="s1", language="English", message="done"))

    assert out.reply_text == ""
    assert out.captured is True

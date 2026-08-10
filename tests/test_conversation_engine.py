"""Tests for conversation_engine.ConversationEngine (mocked LLM seam)."""
from __future__ import annotations

import csv
import json

import pytest

import admin_config
from admin_config import AdminConfigStore, default_config
from conversation_engine import (
    ConversationEngine,
    GenerateResult,
    TurnInput,
    build_system_instruction,
    parse_profile_json,
)
from leads import LeadWriter


class FakeLLM:
    """Scripted LLM for behavioural tests at the engine seam."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def generate(self, *, system_instruction: str, contents: list[dict]) -> GenerateResult:
        self.calls.append({
            "system_instruction": system_instruction,
            "contents": contents,
        })
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


def test_build_system_includes_campaign_and_guardrails(stores):
    config_store, _, _ = stores
    system = build_system_instruction(config_store.get(), "English")
    assert "Vaada" in system or "CAMPAIGN" in system
    assert "dealership shares exact" in system or "dealership shares exact figures" in system.lower()
    assert "KNOWLEDGE BASE" in system
    assert "gently redirect" in system.lower() or "off-topic" in system.lower()


def test_system_instruction_soft_asks_product_hint(stores):
    config_store, _, _ = stores
    system = build_system_instruction(
        config_store.get(),
        "English",
        product_hint="King EV MAX",
        confirm_crm_dealer=True,
    )
    assert "King EV MAX" in system
    assert "Do NOT mention CRM" in system
    assert "Do NOT ask for a pincode yet" in system


def test_profile_json_stripped_from_customer_reply(stores):
    profile = {"product_interest": "King EV MAX", "lead_quality": "WARM"}
    raw = f"Thanks! We will call you.\nPROFILE_JSON:{json.dumps(profile)}"
    text, parsed = parse_profile_json(raw)
    assert "PROFILE_JSON" not in text
    assert parsed == profile


def test_profile_json_with_trailing_text_is_still_stripped(stores):
    """The model sometimes adds a sign-off AFTER the PROFILE_JSON block.
    Anchoring the pattern to end-of-string makes that whole block leak to
    the customer, so the payload match must not require it.
    """
    profile = {"product_interest": "King EV MAX", "lead_quality": "HOT"}
    raw = f"Thanks!\nPROFILE_JSON:{json.dumps(profile)}\nBye!"
    text, parsed = parse_profile_json(raw)
    assert "PROFILE_JSON" not in text
    assert "lead_quality" not in text
    assert text == "Thanks!"
    assert parsed == profile


def test_profile_json_fenced_with_prefix_is_stripped(stores):
    """The prompt allows PROFILE_JSON: to be present even if the model
    wraps it in a code fence — still stripped and parsed."""
    profile = {"product_interest": "King Deluxe", "lead_quality": "HOT"}
    raw = f"Thanks!\nPROFILE_JSON:\n```json\n{json.dumps(profile)}\n```"
    text, parsed = parse_profile_json(raw)
    assert text == "Thanks!"
    assert parsed == profile


def test_bare_fenced_json_without_prefix_is_stripped_and_parsed(stores):
    """Real production leak: the model dropped the PROFILE_JSON: prefix
    entirely and just fenced the object. The strict prefix-only regex
    missed this, so the raw profile (product, pincode, doc status,
    lead_quality...) went straight into a WhatsApp reply to the customer.
    """
    profile = {
        "product_interest": "King Duramax Plus",
        "pincode": "431401",
        "doc_license": "yes",
        "lead_quality": "HOT",
    }
    raw = (
        "छान, डीलरशिपची माहिती योग्य आहे! धन्यवाद!\n\n"
        f"```json\n{json.dumps(profile, ensure_ascii=False)}\n```"
    )
    text, parsed = parse_profile_json(raw)
    assert "```" not in text
    assert "{" not in text
    assert text == "छान, डीलरशिपची माहिती योग्य आहे! धन्यवाद!"
    assert parsed == profile


def test_stray_unclosed_fence_around_plain_reply_is_cleaned_not_dropped(stores):
    """Real production leak: the model opened a ```json fence around an
    ordinary (non-JSON) reply and never closed it. No JSON payload exists
    to extract, so the fix must strip only the stray backtick markers —
    dropping the whole block would silently swallow a real reply the
    customer needed to see (in the observed case, a dealer-confirm ask).
    """
    raw = "```json\n\nकृपया ही डीलरशिप तपशील तपासा: होय किंवा नाही उत्तर द्या."
    text, parsed = parse_profile_json(raw)
    assert "```" not in text
    assert "कृपया ही डीलरशिप तपशील तपासा" in text
    assert parsed is None


def test_profile_json_saved_to_csv(stores):
    config_store, lead_writer, leads_path = stores
    profile = {
        "product_interest": "King Deluxe",
        "purchase_timeline": "next month",
        "timeline_bucket": "<=30d",
        "pincode": "411001",
        "lead_quality": "HOT",
        "doc_license": "yes",
        "doc_permit": "yes",
        "doc_badge": "no",
    }
    llm = FakeLLM([
        f"Thank you! Dealership will contact you.\nPROFILE_JSON:{json.dumps(profile)}"
    ])
    engine = ConversationEngine(config_store=config_store, llm=llm, lead_writer=lead_writer)
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
    rows = list(csv.DictReader(leads_path.open(encoding="utf-8-sig")))
    assert len(rows) == 1
    assert rows[0]["product_interest"] == "King Deluxe"
    assert rows[0]["channel"] == "web"
    assert rows[0]["source"] == "ricshow"
    assert rows[0]["session"] == "web-abc"


def test_mid_flow_product_question_passes_history(stores):
    config_store, lead_writer, _ = stores
    llm = FakeLLM(["CNG King Deluxe gets ~50 km/kg. Which model interests you most?"])
    engine = ConversationEngine(config_store=config_store, llm=llm, lead_writer=lead_writer)
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
    assert "Hindi" in llm.calls[0]["system_instruction"]


def test_emi_rule_in_system_prompt(stores):
    config_store, lead_writer, _ = stores
    llm = FakeLLM([
        "Exact EMI figures are shared by the dealership. When do you plan to buy?"
    ])
    engine = ConversationEngine(config_store=config_store, llm=llm, lead_writer=lead_writer)
    engine.handle_turn(
        TurnInput(session_id="s1", language="English", message="What is the EMI?")
    )
    system = llm.calls[0]["system_instruction"]
    assert "EMI" in system
    assert "dealership" in system.lower()


def test_off_topic_rule_in_system_prompt(stores):
    config_store, lead_writer, _ = stores
    llm = FakeLLM(["I help with TVS passenger three-wheelers. Which model interests you?"])
    engine = ConversationEngine(config_store=config_store, llm=llm, lead_writer=lead_writer)
    engine.handle_turn(
        TurnInput(session_id="s1", language="English", message="Who won the cricket?")
    )
    system = llm.calls[0]["system_instruction"]
    assert "off-topic" in system.lower() or "redirect" in system.lower()


def test_brochure_rule_tells_llm_system_handles_delivery(stores):
    config_store, _, _ = stores
    system = build_system_instruction(config_store.get(), "English")
    assert "never attach files yourself" in system.lower()
    assert "never say you are unable to send a brochure" in system.lower()
    # Claiming a send is allowed ONLY when the system said it is sending.
    # Without that, the bot promised brochures nobody ever sent (bug 010805).
    assert "only when a system note" in system.lower()
    assert "offer it instead" in system.lower()
    # Must not assert a completed send as fact — only the deterministic
    # sender knows whether the document actually went out.
    assert "never claim in past tense" in system.lower()


def test_delivery_location_in_profile_keys(stores):
    config_store, _, _ = stores
    system = build_system_instruction(config_store.get(), "English")
    assert "delivery_location" in system


def test_csv_columns_update_when_config_changes(stores, tmp_path):
    config_store, lead_writer, leads_path = stores
    profile = {"product_interest": "King EV MAX", "lead_quality": "COLD"}
    llm = FakeLLM([
        f"Done.\nPROFILE_JSON:{json.dumps(profile)}",
        f"Done.\nPROFILE_JSON:{json.dumps({**profile, 'custom_field': 'x'})}",
    ])
    engine = ConversationEngine(config_store=config_store, llm=llm, lead_writer=lead_writer)
    engine.handle_turn(TurnInput(session_id="s1", language="English", message="done"))

    cfg = config_store.get()
    cfg["capture_fields"].append(
        {"id": "custom_field", "label": "Custom", "required": False}
    )
    config_store.update(cfg)

    engine.handle_turn(TurnInput(session_id="s2", language="English", message="done"))
    with leads_path.open(encoding="utf-8-sig") as f:
        header = f.readline().strip().split(",")
    assert "custom_field" in header

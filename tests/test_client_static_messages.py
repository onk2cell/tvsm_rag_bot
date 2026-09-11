"""Localized static WhatsApp cards."""
from __future__ import annotations

from client_static_messages import dealer_confirm_ask, place_redirect_message


def test_dealer_card_is_marathi_when_language_is_marathi():
    ask = dealer_confirm_ask(
        name="Rhythm Auto",
        address="Hinjewadi",
        language="Marathi",
    )
    assert "कृपया ही डीलरशिप" in ask
    assert "नाव: Rhythm Auto" in ask
    assert "होय किंवा नाही" in ask
    assert "Reply Yes or No" not in ask


def test_dealer_card_english_default():
    ask = dealer_confirm_ask(name="Rhythm Auto", address="Pune")
    assert "Please check this dealership details:" in ask
    assert "Reply Yes or No" in ask


def test_place_redirect_marathi():
    text = place_redirect_message("Marathi")
    assert "पिनकोड" in text
    assert "city/area" not in text.lower() or "शहर" in text


# --- vehicle-or-PGM routing ask ---------------------------------------------

_ALL_LANGUAGES = (
    "English", "Hindi", "Marathi", "Telugu", "Tamil", "Kannada", "Malayalam"
)


def test_flow_intent_ask_is_localized_for_every_menu_language():
    """The routing ask is the first thing a customer reads in the language
    they just chose, so no language in the 1-7 menu may fall back to English."""
    from client_static_messages import flow_intent_ask

    texts = {lang: flow_intent_ask(lang) for lang in _ALL_LANGUAGES}
    assert len(set(texts.values())) == len(_ALL_LANGUAGES)
    for lang, text in texts.items():
        assert "PGM" in text, lang
        assert "1" in text and "2" in text, lang
    assert "still interested in the vehicle" in texts["English"]
    assert "nearest PGM" in texts["English"]


def test_pgm_flow_intro_is_localized_for_every_menu_language():
    from client_static_messages import pgm_flow_intro

    texts = {lang: pgm_flow_intro(lang) for lang in _ALL_LANGUAGES}
    assert len(set(texts.values())) == len(_ALL_LANGUAGES)
    assert all("PGM" in text for text in texts.values())


def test_flow_intent_ask_is_admin_editable(tmp_path, monkeypatch):
    """Both new messages ride the same override path as every other card."""
    import admin_config
    from client_static_messages import flow_intent_ask, pgm_flow_intro

    admin_config.reset_store_for_tests()
    store = admin_config.get_store(tmp_path / "admin_config.json")
    cfg = store.ensure_seeded()
    cfg["messages"] = {
        "flow_intent_ask": {"Hindi": "गाड़ी या PGM? 1 या 2"},
        "pgm_flow_intro": {"Hindi": "ठीक है, PGM ढूँढते हैं।"},
    }
    store.update(cfg)
    try:
        assert flow_intent_ask("Hindi") == "गाड़ी या PGM? 1 या 2"
        assert pgm_flow_intro("Hindi") == "ठीक है, PGM ढूँढते हैं।"
        assert "Press 1 for Vehicle" in flow_intent_ask("English")
    finally:
        admin_config.reset_store_for_tests()

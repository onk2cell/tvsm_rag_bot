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


def test_pgm_location_step_messages_are_localized_for_every_menu_language():
    from client_static_messages import (
        pgm_ask_bigger_city,
        pgm_location_ask,
        pgm_lookup_failed,
        pgm_pincode_noted,
    )

    for fn in (pgm_location_ask, pgm_ask_bigger_city, pgm_lookup_failed):
        texts = {lang: fn(lang) for lang in _ALL_LANGUAGES}
        assert len(set(texts.values())) == len(_ALL_LANGUAGES), fn.__name__
    noted = {lang: pgm_pincode_noted("411001", lang) for lang in _ALL_LANGUAGES}
    assert len(set(noted.values())) == len(_ALL_LANGUAGES)
    assert all("411001" in text for text in noted.values())
    assert "{pincode}" not in noted["English"]


def test_pgm_pincode_noted_declares_its_placeholder():
    """validate_messages rejects an override naming anything else."""
    from client_static_messages import placeholders_for

    assert placeholders_for("pgm_pincode_noted") == {"pincode"}
    assert placeholders_for("pgm_location_ask") == frozenset()


# --- PGM results -------------------------------------------------------------


class _Pgm:
    def __init__(self, **values):
        defaults = dict(
            dms_id="1", name="Anees Auto Works", phone="8722574132",
            address="VIDYARANYAPURA AMS LAYOUT BANGALORE 560097",
            area="Vidyaranyapura", map_url="https://maps.google.com/?q=13.08,77.55",
            owner_name="", distance_km=1.23,
        )
        defaults.update(values)
        self.__dict__.update(defaults)


def test_pgm_result_messages_are_localized_for_every_menu_language():
    from client_static_messages import (
        pgm_none_nearby,
        pgm_pincode_unresolved,
        pgm_results_footer,
        pgm_results_list,
    )

    footers = {lang: pgm_results_footer(lang) for lang in _ALL_LANGUAGES}
    assert len(set(footers.values())) == len(_ALL_LANGUAGES)
    none = {lang: pgm_none_nearby(50, lang) for lang in _ALL_LANGUAGES}
    assert len(set(none.values())) == len(_ALL_LANGUAGES)
    assert all("50 " in text for text in none.values())
    unresolved = {lang: pgm_pincode_unresolved("560097", lang) for lang in _ALL_LANGUAGES}
    assert len(set(unresolved.values())) == len(_ALL_LANGUAGES)
    assert all("560097" in text for text in unresolved.values())
    headers = set()
    for lang in _ALL_LANGUAGES:
        by_pin = pgm_results_list([_Pgm()], pincode="560097", language=lang)
        by_loc = pgm_results_list([_Pgm()], language=lang)
        assert "560097" in by_pin.splitlines()[0]
        assert by_pin.splitlines()[0] != by_loc.splitlines()[0]
        headers.add(by_pin.splitlines()[0])
    assert len(headers) == len(_ALL_LANGUAGES)


def test_pgm_results_list_numbers_entries_with_area_distance_and_phone():
    from client_static_messages import pgm_results_list

    text = pgm_results_list(
        [_Pgm(), _Pgm(dms_id="2", name="GK Motors Laggere", area="Laggere",
                      phone="", distance_km=4.0)],
        pincode="560097",
    )

    assert text.splitlines()[0] == "Nearest PGMs to pincode 560097:"
    assert "1. Anees Auto Works — Vidyaranyapura (1.2 km)" in text
    assert "   Phone: 8722574132" in text
    # Area already in the name is not repeated; no phone, no phone line.
    assert "2. GK Motors Laggere (4.0 km)" in text
    assert text.count("Phone:") == 1
    assert text.rstrip().endswith("to search again.")
    # The card details wait behind the pick.
    assert "AMS LAYOUT" not in text and "maps.google" not in text


def test_pgm_card_uses_the_dealer_labels_in_the_customer_language():
    from client_static_messages import pgm_card

    card = pgm_card(_Pgm(owner_name="Ajaz"), language="Kannada")
    assert card.splitlines() == [
        "ಹೆಸರು: Anees Auto Works",
        "ವಿಳಾಸ: VIDYARANYAPURA AMS LAYOUT BANGALORE 560097",
        "ಫೋನ್: Ajaz - 8722574132",
        "ನಕ್ಷೆ: https://maps.google.com/?q=13.08,77.55",
    ]
    # No address falls back to the area; no owner shows the phone alone.
    card = pgm_card(_Pgm(address=""))
    assert "Address: Vidyaranyapura" in card
    assert "Phone: 8722574132" in card


def test_pgm_result_messages_declare_their_placeholders():
    from client_static_messages import placeholders_for

    assert placeholders_for("pgm_nearest_for_pincode") == {"pincode"}
    assert placeholders_for("pgm_none_nearby") == {"km"}
    assert placeholders_for("pgm_pincode_unresolved") == {"pincode"}
    assert placeholders_for("pgm_results_footer") == frozenset()

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

"""Language selection helpers for client channel."""
from __future__ import annotations

from client_language import (
    language_from_remark,
    language_from_state,
    parse_language_choice,
)


def test_language_from_state_maps_known_states():
    assert language_from_state("Maharashtra") == "Marathi"
    assert language_from_state("Tamil Nadu") == "Tamil"
    assert language_from_state("Uttar Pradesh") == "Hindi"
    assert language_from_state("Karnataka") == "Kannada"
    assert language_from_state("Andhra Pradesh") == "Telugu"
    assert language_from_state("Telangana") == "Telugu"
    assert language_from_state("Kerala") == "Malayalam"
    assert language_from_state("") == ""
    assert language_from_state(None) == ""


def test_language_from_remark_recovers_preferred_language():
    assert (
        language_from_remark(
            "preferred_language: Hindi | product_interest: King EV MAX"
        )
        == "Hindi"
    )
    assert language_from_remark("preferred_language: Marathi") == "Marathi"
    assert language_from_remark("no language here") == ""
    assert language_from_remark("") == ""


def test_parse_language_choice_accepts_numbers_and_names():
    assert parse_language_choice("2") == "Hindi"
    assert parse_language_choice("3.") == "Marathi"
    assert parse_language_choice("4") == "Telugu"
    assert parse_language_choice("5") == "Tamil"
    assert parse_language_choice("6") == "Kannada"
    assert parse_language_choice("7") == "Malayalam"
    assert parse_language_choice("हिंदी") == "Hindi"
    assert parse_language_choice("தமிழ்") == "Tamil"
    assert parse_language_choice("తెలుగు") == "Telugu"
    assert parse_language_choice("ಕನ್ನಡ") == "Kannada"
    assert parse_language_choice("മലയാളം") == "Malayalam"
    assert parse_language_choice("please talk in marathi") == "Marathi"
    assert parse_language_choice("malyalam please") == "Malayalam"
    assert parse_language_choice("I want King EV") == ""

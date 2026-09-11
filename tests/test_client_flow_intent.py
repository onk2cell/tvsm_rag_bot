"""Vehicle-or-nearest-PGM routing: deterministic parsing of the reply."""
from __future__ import annotations

import pytest

from client_flow_intent import FLOW_PGM, FLOW_VEHICLE, parse_flow_intent


@pytest.mark.parametrize(
    "text",
    ["1", " 1 ", "1.", "1)", "option 1", "vehicle", "Vehicle please", "gaadi",
     "I want the auto", "king ev max", "गाडी हवी", "वाहन", "వాహనం", "வாகனம்",
     "ವಾಹನ", "വാഹനം"],
)
def test_vehicle_replies(text):
    assert parse_flow_intent(text) == FLOW_VEHICLE


@pytest.mark.parametrize(
    "text",
    ["2", "2.", "option 2", "pgm", "PGM", "P.G.M", "nearest pgm chahiye",
     "looking for pgm", "पीजीएम"],
)
def test_pgm_replies(text):
    assert parse_flow_intent(text) == FLOW_PGM


@pytest.mark.parametrize(
    "text",
    ["", None, "hello", "yes", "no", "3", "12", "vehicle and pgm",
     "pgm ya gaadi?", "Hindi"],
)
def test_unclear_replies_are_not_guessed(text):
    """Anything that is not a clear choice is re-asked, never routed."""
    assert parse_flow_intent(text) == ""


# --- picking from the numbered PGM list --------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [("1", 1), (" 2 ", 2), ("3.", 3), ("2)", 2), ("option 3", 3), ("no. 2", 2),
     ("number 1", 1), ("4", 0), ("0", 0), ("2 more", 0), ("560097", 0),
     ("", 0), (None, 0), ("first", 0)],
)
def test_parse_list_pick(text, expected):
    from client_flow_intent import parse_list_pick

    assert parse_list_pick(text, 3) == expected


def test_parse_list_pick_respects_a_shorter_list():
    from client_flow_intent import parse_list_pick

    assert parse_list_pick("2", 1) == 0
    assert parse_list_pick("1", 0) == 0

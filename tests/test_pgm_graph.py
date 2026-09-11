"""Locate-nearest-PGM location step: pincode from a typed reply."""
from __future__ import annotations

import pytest

from bot.pgm_graph import (
    NOT_FOUND_TOKEN,
    SEARCH_MAX_CHARS,
    looks_like_place,
    resolve_pgm_location,
    search_query,
)


def _never(query: str) -> str:
    raise AssertionError(f"search must not be called, got {query!r}")


@pytest.mark.parametrize("text", ["411001", "pin 411 035", "44-11-33", "my pincode is 560001"])
def test_typed_pincode_needs_no_search(text):
    located = resolve_pgm_location(text, search=_never)
    assert located.result == "pincode"
    assert len(located.pincode) == 6


@pytest.mark.parametrize("text", ["", "ok", "?", "..", "12", "50000", "  "])
def test_filler_is_unclear_not_searched(text):
    assert not looks_like_place(text)
    assert resolve_pgm_location(text, search=_never).result == "unclear"


def test_place_name_is_resolved_by_search():
    seen = []

    def fake(query):
        seen.append(query)
        return "411057 Hinjewadi, Pune"

    located = resolve_pgm_location("Hinjewadi", search=fake)
    assert located.result == "pincode"
    assert located.pincode == "411057"
    assert located.search_result == "411057 Hinjewadi, Pune"
    assert seen == [search_query("Hinjewadi")]


def test_search_query_asks_for_one_pincode_or_not_found():
    query = search_query("Parbhani")
    assert "'Parbhani'" in query
    assert "PIN code" in query
    assert NOT_FOUND_TOKEN in query
    assert SEARCH_MAX_CHARS < 600  # a pincode line, not a page


def test_native_script_place_name_is_searched():
    located = resolve_pgm_location("परभणी", search=lambda q: "431401 Parbhani")
    assert located.result == "pincode"
    assert located.pincode == "431401"


@pytest.mark.parametrize(
    "answer",
    [NOT_FOUND_TOKEN, "not_found", "I could not find that place.", ""],
)
def test_no_pincode_in_answer_asks_for_bigger_city(answer):
    located = resolve_pgm_location("Xyzzy Nagar", search=lambda q: answer)
    assert located.result == "not_found"
    assert located.pincode == ""


def test_not_found_wins_even_if_answer_contains_digits():
    """The model may explain itself with a number in it; the token decides."""
    located = resolve_pgm_location(
        "Somewhere", search=lambda q: f"{NOT_FOUND_TOKEN} (there are 100000 villages)"
    )
    assert located.result == "not_found"


def test_search_failure_is_reported_not_treated_as_missing_place():
    def boom(query):
        raise RuntimeError("429 quota")

    located = resolve_pgm_location("Pune", search=boom)
    assert located.result == "lookup_failed"
    assert located.pincode == ""

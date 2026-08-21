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
    depend on a live API key and on what the model happens to answer. Two
    tests used to do exactly that and had to be deselected in CI.

    Each stub reuses the real graph's router, so the deterministic half is
    genuinely exercised; only the LLM branch is replaced, with that branch's
    own production safe default. Tests exercising an LLM-decided branch
    override these with their own monkeypatch, which wins because it is
    applied later.
    """
    if request.node.get_closest_marker("live_classifier"):
        return

    from bot import graph

    def offline(router, outcomes, safe_default, state_key="user_message"):
        """Route with the real regexes; answer the classify branch safely."""

        def stub(message, *args, **kwargs):
            state = {state_key: message, "last_bot_message": ""}
            try:
                branch = router(state)
            except Exception:
                return safe_default
            return outcomes.get(branch, safe_default)

        return stub

    for name, router, outcomes, safe in (
        (
            "classify_still_interested_reply",
            graph._route_still_interested_reply,
            {"declining": True, "proceeding": False},
            False,  # keep qualifying rather than closing the lead
        ),
        (
            "classify_dealer_confirm_reply",
            graph._route_dealer_confirm_reply,
            {"yes": "yes", "no": "no"},
            "unclear",
        ),
        (
            "classify_brochure_offer_reply",
            graph._route_brochure_offer_reply,
            {"yes": "yes", "no": "no"},
            "unclear",
        ),
        (
            "classify_brochure_request",
            graph._route_brochure_request,
            {"yes": True, "no": False},
            False,
        ),
        (
            "classify_product_info_request",
            graph._route_product_info_request,
            {"yes": True, "no": False},
            False,
        ),
        (
            "classify_share_consent_reply",
            graph._route_share_consent,
            {"yes": "yes", "no": "no"},
            "unclear",  # never share contact details on a guess
        ),
        (
            "classify_location_reply",
            graph._route_location_reply,
            {"other": "other", "bad_pincode": "bad_pincode"},
            "other",  # fall through to normal qualification
        ),
    ):
        monkeypatch.setattr(
            f"client_processing.{name}",
            offline(router, outcomes, safe),
            raising=False,
        )

    def offline_language_switch(message: str) -> str:
        from client_language import parse_language_choice

        state = {"user_message": message, "language": ""}
        if graph._route_language_switch(state) == "explicit":
            return parse_language_choice(message or "")
        return ""  # safe default: keep the language already in use

    monkeypatch.setattr(
        "client_processing.classify_language_switch",
        offline_language_switch,
        raising=False,
    )

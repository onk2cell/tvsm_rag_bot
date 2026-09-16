"""Tests for bot/graph.py's still-interested and dealer-confirm classifier
graphs."""
from __future__ import annotations

import pytest

from bot.graph import (
    BrochureOfferClassification,
    BrochureRequestClassification,
    DealerConfirmClassification,
    StillInterestedClassification,
    classify_brochure_offer_reply,
    classify_brochure_request,
    classify_dealer_confirm_reply,
    classify_still_interested_reply,
)


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


def test_dealer_confirm_clear_yes_uses_regex_fast_path_no_llm_call(monkeypatch):
    _forbid_llm(monkeypatch)
    # Dealer-confirm asks for literal Yes/No text, not numbered options.
    assert classify_dealer_confirm_reply("yes") == "yes"
    assert classify_dealer_confirm_reply("haan") == "yes"


def test_dealer_confirm_clear_no_uses_regex_fast_path_no_llm_call(monkeypatch):
    _forbid_llm(monkeypatch)
    assert classify_dealer_confirm_reply("no") == "no"
    assert classify_dealer_confirm_reply("nahi") == "no"


class _FakeDealerConfirmLLM:
    def __init__(self, result: str):
        self._result = result
        self.prompts: list[str] = []

    def with_structured_output(self, schema):
        assert schema is DealerConfirmClassification
        return self

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        return DealerConfirmClassification(result=self._result)


def test_dealer_confirm_natural_phrasing_falls_back_to_llm_classifier(monkeypatch):
    # The exact reported bug: "ha ye dealrshime mere pass hai" doesn't match
    # the strict single-word _is_affirmative regex.
    fake = _FakeDealerConfirmLLM(result="yes")
    monkeypatch.setattr("bot.graph.get_llm", lambda tier="smart": fake)

    result = classify_dealer_confirm_reply("ha ye dealrshime mere pass hai")

    assert result == "yes"
    assert fake.prompts  # the LLM was actually consulted


def test_dealer_confirm_llm_classifies_as_no(monkeypatch):
    fake = _FakeDealerConfirmLLM(result="no")
    monkeypatch.setattr("bot.graph.get_llm", lambda tier="smart": fake)

    assert classify_dealer_confirm_reply("nahi ye galat hai") == "no"


def test_dealer_confirm_unrelated_message_classifies_as_unclear(monkeypatch):
    fake = _FakeDealerConfirmLLM(result="unclear")
    monkeypatch.setattr("bot.graph.get_llm", lambda tier="smart": fake)

    assert classify_dealer_confirm_reply("what is the price?") == "unclear"


class _BrokenDealerConfirmLLM:
    def with_structured_output(self, schema):
        return self

    def invoke(self, prompt: str):
        raise RuntimeError("boom")


def test_dealer_confirm_classifier_failure_defaults_to_unclear(monkeypatch):
    monkeypatch.setattr(
        "bot.graph.get_llm", lambda tier="smart": _BrokenDealerConfirmLLM()
    )

    assert classify_dealer_confirm_reply("something ambiguous") == "unclear"


class _FakeBrochureOfferLLM:
    def __init__(self, result: str):
        self._result = result
        self.prompts: list[str] = []

    def with_structured_output(self, schema):
        assert schema is BrochureOfferClassification
        return self

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        return BrochureOfferClassification(result=self._result)


def test_brochure_offer_clear_bhejo_uses_regex_fast_path(monkeypatch):
    _forbid_llm(monkeypatch)
    assert classify_brochure_offer_reply("bhejo") == "yes"
    assert classify_brochure_offer_reply("no") == "no"


def test_brochure_offer_natural_phrasing_uses_llm(monkeypatch):
    fake = _FakeBrochureOfferLLM(result="yes")
    monkeypatch.setattr("bot.graph.get_llm", lambda tier="smart": fake)
    assert classify_brochure_offer_reply("हो नक्की पाठवा ना") == "yes"
    assert fake.prompts


def test_brochure_offer_llm_unclear_for_unrelated(monkeypatch):
    fake = _FakeBrochureOfferLLM(result="unclear")
    monkeypatch.setattr("bot.graph.get_llm", lambda tier="smart": fake)
    assert classify_brochure_offer_reply("what is the price?") == "unclear"


class _FakeMediaOfferLLM:
    def __init__(self, result: str):
        self._result = result
        self.prompts: list[str] = []

    def with_structured_output(self, schema):
        from bot.graph import MediaOfferClassification

        assert schema is MediaOfferClassification
        return self

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        from bot.graph import MediaOfferClassification

        return MediaOfferClassification(result=self._result)


def test_media_offer_regex_fast_path(monkeypatch):
    """Replies to "brochure, photos, or both? 1/2/3" that never need the LLM."""
    from bot.graph import classify_brochure_or_images_reply as classify

    _forbid_llm(monkeypatch)
    assert classify("1") == "brochure"
    assert classify("1.") == "brochure"
    assert classify("brochure bhejo") == "brochure"
    assert classify("2") == "images"
    assert classify("photo bhejo") == "images"
    assert classify("3") == "both"
    assert classify("both") == "both"
    assert classify("दोनों") == "both"
    assert classify("photo aur brochure dono") == "both"
    # A plain yes to a three-way offer sends everything rather than re-asking.
    assert classify("yes") == "both"
    assert classify("haan") == "both"
    assert classify("bhejo") == "both"
    assert classify("no") == "no"
    assert classify("nahi") == "no"


def test_media_offer_natural_phrasing_uses_llm(monkeypatch):
    from bot.graph import classify_brochure_or_images_reply as classify

    fake = _FakeMediaOfferLLM(result="images")
    monkeypatch.setattr("bot.graph.get_llm", lambda tier="smart": fake)
    assert classify("फक्त गाडी कशी दिसते ते दाखवा") == "images"
    assert fake.prompts and "reply 3" in fake.prompts[0]


def test_media_offer_classifier_failure_defaults_to_unclear(monkeypatch):
    from bot.graph import classify_brochure_or_images_reply as classify

    class _Broken:
        def with_structured_output(self, schema):
            return self

        def invoke(self, prompt):
            raise RuntimeError("quota")

    monkeypatch.setattr("bot.graph.get_llm", lambda tier="smart": _Broken())
    assert classify("what is the price?") == "unclear"


class _FakeBrochureRequestLLM:
    def __init__(self, wants: bool):
        self._wants = wants
        self.prompts: list[str] = []

    def with_structured_output(self, schema):
        assert schema is BrochureRequestClassification
        return self

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        return BrochureRequestClassification(wants_brochure=self._wants)


def test_brochure_request_regex_fast_path_no_llm(monkeypatch):
    _forbid_llm(monkeypatch)
    assert classify_brochure_request("send me the brochure") is True
    assert classify_brochure_request("hello") is False


def test_brochure_request_soft_signal_uses_llm(monkeypatch):
    fake = _FakeBrochureRequestLLM(wants=True)
    monkeypatch.setattr("bot.graph.get_llm", lambda tier="smart": fake)
    # Soft signal "bhej"/"file" but not the hard brochure/pdf regex.
    assert classify_brochure_request("woh file bhej dena please") is True
    assert fake.prompts


def test_brochure_request_transliterated_verb_reaches_llm(monkeypatch):
    """Voice notes in a Hindi session come back with "send"/"share" in
    Devanagari; the soft gate has to let those through to the classifier."""
    fake = _FakeBrochureRequestLLM(wants=True)
    monkeypatch.setattr("bot.graph.get_llm", lambda tier="smart": fake)
    assert classify_brochure_request("वो डॉक्यूमेंट सेंड कर दो") is True
    assert fake.prompts


def test_photo_request_never_reaches_the_brochure_classifier(monkeypatch):
    """"Send me photos" trips the "send" soft signal, and the classifier
    was willing to call a photo a brochure — the customer asked for
    pictures and got a PDF (JAM feedback, 2026-09-16)."""
    fake = _FakeBrochureRequestLLM(wants=True)
    monkeypatch.setattr("bot.graph.get_llm", lambda tier="smart": fake)
    assert classify_brochure_request("send me photos of king ev max") is False
    assert classify_brochure_request("मुझे फोटो भेजो") is False
    assert fake.prompts == []
    # ...unless a document word is there too — then it is a brochure ask.
    assert classify_brochure_request("send photos and the brochure") is True

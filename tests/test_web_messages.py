"""Admin-editable bot copy: sparse overrides, validated on write, safe to render."""
from __future__ import annotations

import admin_config
import client_static_messages as csm
import pytest
from tests.test_web_admin import _app, _auth
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate_store():
    """client_static_messages reads the process-wide store, so point that at
    the same file the test app writes to — otherwise the module reads the real
    deployment's config and the assertions are meaningless."""
    admin_config.reset_store_for_tests()
    yield
    admin_config.reset_store_for_tests()


def _c(tmp_path):
    app = _app(tmp_path)
    admin_config.reset_store_for_tests()
    admin_config.get_store(tmp_path / "admin_config.json")
    return TestClient(app)


def _get(client, key):
    return client.get(f"/admin/api/messages/{key}", headers=_auth()).json()


# --- reading ----------------------------------------------------------------


def test_lists_every_editable_message(tmp_path):
    body = _c(tmp_path).get("/admin/api/messages", headers=_auth()).json()
    assert len(body["messages"]) == len(csm.message_keys())
    assert {"key", "placeholders", "defaults", "overrides"} <= set(body["messages"][0])


def test_shows_which_languages_fall_back_to_english(tmp_path):
    """The Dravidian gap should be visible, not silent."""
    body = _get(_c(tmp_path), "dealer_ask")
    assert set(body["falls_back_to_english"]) == {
        "Telugu", "Tamil", "Kannada", "Malayalam",
    }
    assert body["defaults"]["Hindi"]


def test_placeholders_are_declared_per_message(tmp_path):
    client = _c(tmp_path)
    assert _get(client, "brochure_caption")["placeholders"] == ["product"]
    assert _get(client, "dealer_ask")["placeholders"] == []


def test_unknown_message_is_404(tmp_path):
    assert _c(tmp_path).get("/admin/api/messages/nope", headers=_auth()).status_code == 404


def test_messages_need_a_token(tmp_path):
    assert _c(tmp_path).get("/admin/api/messages").status_code == 401


# --- writing ----------------------------------------------------------------


def test_translating_a_missing_language_closes_the_gap(tmp_path):
    client = _c(tmp_path)
    resp = client.put(
        "/admin/api/messages/dealer_ask", headers=_auth(),
        json={"text": {"Telugu": "ఈ డీలర్‌షిప్ మీకు దగ్గరగా ఉందా?"}},
    )
    assert resp.status_code == 200
    assert "Telugu" not in resp.json()["falls_back_to_english"]
    assert csm.message_text("dealer_ask", "Telugu").startswith("ఈ డీలర్")


def test_only_overrides_are_stored_not_the_whole_catalogue(tmp_path):
    """Sparse: config must not gain 27 keys because one was edited."""
    client = _c(tmp_path)
    client.put("/admin/api/messages/dealer_ask", headers=_auth(),
               json={"text": {"Telugu": "x"}})
    stored = client.get("/admin/api/config", headers=_auth()).json()["messages"]
    assert list(stored) == ["dealer_ask"]
    assert list(stored["dealer_ask"]) == ["Telugu"]


def test_a_typod_placeholder_is_rejected_naming_it(tmp_path):
    resp = _c(tmp_path).put(
        "/admin/api/messages/brochure_caption", headers=_auth(),
        json={"text": {"English": "Here is the {prduct} brochure."}},
    )
    assert resp.status_code == 400
    assert "prduct" in resp.json()["detail"]


def test_a_placeholder_that_message_cannot_supply_is_rejected(tmp_path):
    resp = _c(tmp_path).put(
        "/admin/api/messages/dealer_ask", headers=_auth(),
        json={"text": {"English": "Is {product} ok?"}},
    )
    assert resp.status_code == 400


def test_blank_text_restores_the_builtin_rather_than_muting_the_bot(tmp_path):
    client = _c(tmp_path)
    client.put("/admin/api/messages/dealer_ask", headers=_auth(),
               json={"text": {"English": "Custom?"}})
    assert csm.message_text("dealer_ask", "English") == "Custom?"
    client.put("/admin/api/messages/dealer_ask", headers=_auth(),
               json={"text": {"English": "   "}})
    assert csm.message_text("dealer_ask", "English").startswith("Is this dealership")


def test_delete_restores_the_builtin_wording(tmp_path):
    client = _c(tmp_path)
    client.put("/admin/api/messages/dealer_ask", headers=_auth(),
               json={"text": {"English": "Custom?"}})
    resp = client.delete("/admin/api/messages/dealer_ask", headers=_auth())
    assert resp.status_code == 200
    assert resp.json()["overrides"] == {}
    assert csm.message_text("dealer_ask", "English").startswith("Is this dealership")


# --- rendering safety -------------------------------------------------------


def test_a_bad_template_on_disk_still_answers_the_customer(tmp_path, monkeypatch):
    """Validation guards the API; config can still reach disk by hand.

    A typo must cost the operator their override, never cost a customer a reply.
    """
    monkeypatch.setattr(
        csm, "_overrides",
        lambda: {"brochure_caption": {"English": "Here is the {prduct} one."}},
    )
    assert csm.brochure_caption("King Deluxe", "English") == "King Deluxe brochure"


def test_an_unreadable_config_falls_back_to_builtins(tmp_path, monkeypatch):
    def boom():
        raise RuntimeError("config unreadable")
    monkeypatch.setattr(csm.admin_config, "get_store", boom)
    assert csm.message_text("dealer_ask", "English").startswith("Is this dealership")

"""Vehicle CRUD: a view over config["documents"], not a second store."""
from __future__ import annotations

import dispose
from tests.test_web_admin import TOKEN, _app, _auth
from fastapi.testclient import TestClient


class FakeKbWithDocs:
    def __init__(self, names=()):
        self._names = list(names)

    def summary(self):
        return {"documents": [{"name": n} for n in self._names]}


def _c(tmp_path, **kw):
    return TestClient(_app(tmp_path, **kw))


# --- reading ----------------------------------------------------------------


def test_lists_the_configured_vehicles(tmp_path):
    body = _c(tmp_path).get("/admin/api/vehicles", headers=_auth()).json()
    assert [v["name"] for v in body["vehicles"]] == [
        "King EV MAX", "King Deluxe", "King Duramax Plus",
    ]


def test_aliases_are_seeded_from_builtins_so_they_can_be_edited(tmp_path):
    """An unedited vehicle must show the spellings it actually matches on.

    They live in dispose.PRODUCT_ALIASES, not in config, so without seeding the
    operator sees an empty box while seventeen Devanagari variants still match.
    """
    body = _c(tmp_path).get("/admin/api/vehicles/King Deluxe", headers=_auth()).json()
    assert body["aliases_seeded_from_builtins"] is True
    assert "delux" in body["aliases"] and "डीलक्स" in body["aliases"]


def test_unknown_vehicle_is_404(tmp_path):
    assert _c(tmp_path).get("/admin/api/vehicles/Nope", headers=_auth()).status_code == 404


def test_vehicles_need_a_token(tmp_path):
    assert _c(tmp_path).get("/admin/api/vehicles").status_code == 401


# --- creating ---------------------------------------------------------------


def test_adding_a_vehicle_derives_aliases_from_its_name(tmp_path):
    client = _c(tmp_path)
    resp = client.post(
        "/admin/api/vehicles",
        headers=_auth(),
        json={"name": "King Kargo", "brochure": "https://x/kargo.pdf"},
    )
    assert resp.status_code == 201
    # "king" is shared with three other models, so it cannot disambiguate.
    assert resp.json()["aliases"] == ["king kargo", "kargo"]


def test_a_new_vehicle_is_recognised_by_the_bot(tmp_path):
    """The point of the feature: config drives dispose's matcher."""
    client = _c(tmp_path)
    client.post(
        "/admin/api/vehicles",
        headers=_auth(),
        json={"name": "King Kargo", "brochure": "https://x/kargo.pdf"},
    )
    docs = client.get("/admin/api/config", headers=_auth()).json()["documents"]
    import admin_config
    pairs = admin_config.product_alias_pairs(docs, dispose.builtin_aliases_for)
    dispose.set_alias_source(lambda: pairs)
    try:
        assert dispose.normalize_product_name("i want the kargo") == "King Kargo"
        assert dispose.normalize_product_name("delux") == "King Deluxe"
    finally:
        dispose.reset_alias_source()


def test_duplicate_name_is_409(tmp_path):
    resp = _c(tmp_path).post(
        "/admin/api/vehicles", headers=_auth(),
        json={"name": "King Deluxe", "brochure": "https://x/d.pdf"},
    )
    assert resp.status_code == 409


def test_blank_name_is_400(tmp_path):
    resp = _c(tmp_path).post(
        "/admin/api/vehicles", headers=_auth(), json={"name": "   "},
    )
    assert resp.status_code == 400


def test_a_typed_alias_that_belongs_to_another_vehicle_is_rejected(tmp_path):
    """Typed spellings are a hard error: the operator meant them."""
    resp = _c(tmp_path).post(
        "/admin/api/vehicles", headers=_auth(),
        json={"name": "King Kargo", "brochure": "https://x/k.pdf",
              "aliases": ["delux"]},
    )
    assert resp.status_code == 400
    assert "delux" in resp.json()["detail"]


def test_a_derived_alias_that_collides_is_dropped_not_rejected(tmp_path):
    """Derived spellings were never asked for, so a clash just drops them."""
    resp = _c(tmp_path).post(
        "/admin/api/vehicles", headers=_auth(),
        json={"name": "Deluxe Cargo", "brochure": "https://x/c.pdf"},
    )
    assert resp.status_code == 201
    assert "deluxe" not in resp.json()["aliases"]
    assert "cargo" in resp.json()["aliases"]


def test_warns_when_nothing_in_the_knowledge_base_describes_it(tmp_path):
    resp = _c(tmp_path, knowledge_base=FakeKbWithDocs(["TVS King specs"])).post(
        "/admin/api/vehicles", headers=_auth(),
        json={"name": "King Kargo", "brochure": "https://x/k.pdf"},
    )
    assert resp.status_code == 201
    assert "knowledge-base" in resp.json()["warning"]


def test_no_warning_when_the_knowledge_base_covers_it(tmp_path):
    resp = _c(tmp_path, knowledge_base=FakeKbWithDocs(["King Kargo brochure"])).post(
        "/admin/api/vehicles", headers=_auth(),
        json={"name": "King Kargo", "brochure": "https://x/k.pdf"},
    )
    assert "warning" not in resp.json()


# --- updating, renaming, deleting -------------------------------------------


def test_update_replaces_documents_and_keeps_aliases(tmp_path):
    client = _c(tmp_path)
    resp = client.put(
        "/admin/api/vehicles/King Deluxe", headers=_auth(),
        json={"brochure": "https://x/new.pdf"},
    )
    assert resp.status_code == 200
    assert resp.json()["brochure"] == "https://x/new.pdf"
    assert "delux" in resp.json()["aliases"]


def test_rename_keeps_aliases_that_were_only_builtins(tmp_path):
    """Built-ins are keyed by the old name, so a rename must materialise them.

    Without that the vehicle silently loses every spelling and customers who
    type "delux" stop being understood.
    """
    client = _c(tmp_path)
    resp = client.post(
        "/admin/api/vehicles/King Deluxe/rename", headers=_auth(),
        json={"new_name": "King Deluxe 2026"},
    )
    assert resp.status_code == 200
    assert "delux" in resp.json()["aliases"]
    names = [v["name"] for v in client.get("/admin/api/vehicles", headers=_auth()).json()["vehicles"]]
    assert names == ["King EV MAX", "King Deluxe 2026", "King Duramax Plus"]


def test_rename_onto_an_existing_name_is_409(tmp_path):
    resp = _c(tmp_path).post(
        "/admin/api/vehicles/King Deluxe/rename", headers=_auth(),
        json={"new_name": "King EV MAX"},
    )
    assert resp.status_code == 409


def test_delete_removes_it_and_warns_about_live_conversations(tmp_path):
    client = _c(tmp_path)
    resp = client.delete("/admin/api/vehicles/King Deluxe", headers=_auth())
    assert resp.status_code == 200
    assert "warning" in resp.json()
    names = [v["name"] for v in client.get("/admin/api/vehicles", headers=_auth()).json()["vehicles"]]
    assert "King Deluxe" not in names


def test_delete_unknown_is_404(tmp_path):
    assert _c(tmp_path).delete("/admin/api/vehicles/Nope", headers=_auth()).status_code == 404

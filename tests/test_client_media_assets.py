"""Public media URL helpers for outbound WhatsApp images/documents."""
from __future__ import annotations

from client_media_assets import (
    brochure_product_from_text,
    doesnt_know_pincode,
    product_brochure_caption,
    product_brochure_url,
    product_document_pack,
    share_location_caption,
    share_location_image_url,
    wants_product_brochure,
    wants_product_info,
)


def test_share_location_image_url_uses_how_to_card(monkeypatch):
    monkeypatch.setattr(
        "client_media_assets.media_base_url",
        lambda: "https://example.com/media",
    )
    assert (
        share_location_image_url("Hindi")
        == "https://example.com/media/share_location/how_to.jpg"
    )
    assert (
        share_location_image_url("Marathi")
        == "https://example.com/media/share_location/how_to.jpg"
    )


def test_share_location_caption_falls_back_to_english():
    assert "location" in share_location_caption("English").lower()
    assert share_location_caption("NotALang") == share_location_caption("English")


def test_doesnt_know_pincode_detects_common_phrases():
    assert doesnt_know_pincode("I don't know my pincode")
    assert doesnt_know_pincode("pin code nahi pata")
    assert doesnt_know_pincode("पिनकोड नहीं पता")
    assert doesnt_know_pincode("पिनकोड माहित नाही")
    assert not doesnt_know_pincode("My pincode is 411001")
    assert not doesnt_know_pincode("Yes")


def test_wants_product_brochure_detects_literal_document_requests():
    assert wants_product_brochure("Send me the brochure")
    assert wants_product_brochure("send me the pdf")
    assert wants_product_brochure("share the catalogue")
    # General info questions are NOT a document request — see
    # wants_product_info below; they get an offer, not an auto-send.
    assert not wants_product_brochure("EV MAX details please")
    assert not wants_product_brochure("information about EV MAX")
    assert not wants_product_brochure("मुझे जानकारी चाहिए")
    assert not wants_product_brochure("yes")
    assert not wants_product_brochure("411048")


def test_wants_product_brochure_detects_romanized_spelling_variants():
    """Regression: real WhatsApp typing romanizes "brochure" phonetically
    (Hindi/Marathi speakers typing in Latin script) — these must still
    trigger the real document send, not silently fall through while the
    LLM assumes it worked."""
    assert wants_product_brochure("adhi brocher send kra")
    assert wants_product_brochure("brocher send krta ka")
    assert wants_product_brochure("borcher kahi ahy aka")
    assert wants_product_brochure("brochar please")


def test_wants_product_info_detects_general_questions():
    assert wants_product_info("EV MAX details please")
    assert wants_product_info("can you give me info about ev king max")
    assert wants_product_info("information about EV MAX")
    assert wants_product_info("मुझे जानकारी चाहिए")
    # A literal document ask is not classified as a general info question.
    assert not wants_product_info("Send me the brochure")
    assert not wants_product_info("yes")
    assert not wants_product_info("411048")


def test_product_brochure_url_and_caption():
    assert (
        product_brochure_url("King EV MAX")
        == "https://1.jamoutsourcing.com/f/King_EV_MAX-English.pdf"
    )
    assert (
        product_brochure_url("King Deluxe")
        == "https://1.jamoutsourcing.com/f/King_Deluxe_Petrol-English.pdf"
    )
    assert (
        product_brochure_url("King Deluxe", "I want Deluxe CNG")
        == "https://1.jamoutsourcing.com/f/King_Deluxe_CNG-English.pdf"
    )
    assert (
        product_brochure_url("King Duramax Plus", "Duramax LPG")
        == "https://1.jamoutsourcing.com/f/King_Duramax_Plus_Petrol-English.pdf"
    )
    assert (
        product_brochure_url("King Duramax Plus", "Duramax CNG")
        == "https://1.jamoutsourcing.com/f/King_Duramax_Plus_CNG-English.pdf"
    )
    assert product_brochure_caption("King EV MAX") == "King EV MAX brochure"
    assert brochure_product_from_text("I want EV MAX details") == "King EV MAX"
    assert brochure_product_from_text("info about ev king max") == "King EV MAX"
    assert brochure_product_from_text("hello", "King Deluxe") == "King Deluxe"


def test_product_document_pack_is_the_brochure_alone_by_default():
    """Asking for "the brochure" must deliver one file. It used to send the
    brochure, the PMS schedule and the warranty policy (bug 010804)."""
    assert [kind for _, kind in product_document_pack("King EV MAX")] == ["brochure"]
    assert [kind for _, kind in product_document_pack("King Duramax Plus")] == [
        "brochure"
    ]

    deluxe = product_document_pack("King Deluxe", "Deluxe CNG")
    assert [kind for _, kind in deluxe] == ["brochure"]
    assert deluxe[0][0].endswith("/King_Deluxe_CNG-English.pdf")


def test_product_document_pack_adds_support_docs_when_asked():
    ev = product_document_pack("King EV MAX", include_support_docs=True)
    assert [kind for _, kind in ev] == ["brochure", "warranty"]
    assert ev[1][0].endswith("/TVS_King_EV_MAX_Warranty_Policy.pdf")

    deluxe = product_document_pack(
        "King Deluxe", "Deluxe CNG", include_support_docs=True
    )
    assert [kind for _, kind in deluxe] == ["brochure", "pms", "warranty"]
    assert deluxe[0][0].endswith("/King_Deluxe_CNG-English.pdf")
    assert deluxe[1][0].endswith("/Deluxe-PMS-Schedule.pdf")
    assert deluxe[2][0].endswith("/Deluxe-Warranty-Policy-new.pdf")

    duramax = product_document_pack("King Duramax Plus", include_support_docs=True)
    assert [kind for _, kind in duramax] == ["brochure", "pms", "warranty"]
    assert duramax[1][0].endswith("/Duramaxplus-PMS-Schedule.pdf")
    assert duramax[2][0].endswith("/Duramaxplus-Warranty-Policy.pdf")


def test_wants_support_documents_detects_warranty_and_service_asks():
    from client_media_assets import wants_support_documents

    assert wants_support_documents("what is the warranty on this?")
    assert wants_support_documents("send me the service schedule")
    assert wants_support_documents("मला वॉरंटी माहिती हवी")
    assert not wants_support_documents("send brochure")
    assert not wants_support_documents("Yes send brochure")


# --- admin-configurable product documents -----------------------------------


def _documents_config(monkeypatch, documents):
    """Point client_media_assets at a config carrying these documents."""
    import client_media_assets

    class FakeStore:
        def get(self):
            return {"documents": documents}

    monkeypatch.setattr(
        client_media_assets.admin_config, "get_store", lambda: FakeStore()
    )


def test_no_documents_configured_means_no_brochure(monkeypatch):
    """A bot with no documents configured sends nothing.

    This used to fall back to the TVS brochures, which on any other client's
    stack meant sending that client's customers a TVS King PDF. Sending
    nothing is the safe answer; client_processing turns it into "the team
    will share it" rather than a silent non-delivery.
    """
    import client_media_assets

    class EmptyStore:
        def get(self):
            return {}

    monkeypatch.setattr(
        client_media_assets.admin_config, "get_store", lambda: EmptyStore()
    )
    assert client_media_assets.product_brochure_url("King EV MAX") == ""
    assert client_media_assets.configured_products() == []


def test_a_new_model_year_needs_only_a_config_edit(monkeypatch):
    import client_media_assets

    _documents_config(
        monkeypatch,
        {"King EV MAX": {"brochure": "https://cdn.example/King_EV_MAX-2027.pdf"}},
    )
    assert (
        client_media_assets.product_brochure_url("King EV MAX")
        == "https://cdn.example/King_EV_MAX-2027.pdf"
    )


def test_fuel_override_comes_from_config(monkeypatch):
    import client_media_assets

    _documents_config(
        monkeypatch,
        {
            "King Deluxe": {
                "brochure": "https://cdn.example/deluxe.pdf",
                "fuel": {"cng": "https://cdn.example/deluxe-cng.pdf"},
            }
        },
    )
    assert (
        client_media_assets.product_brochure_url("King Deluxe", "cng chahiye")
        == "https://cdn.example/deluxe-cng.pdf"
    )
    # no fuel named, and an unconfigured fuel, both fall back to the default
    assert (
        client_media_assets.product_brochure_url("King Deluxe")
        == "https://cdn.example/deluxe.pdf"
    )
    assert (
        client_media_assets.product_brochure_url("King Deluxe", "petrol")
        == "https://cdn.example/deluxe.pdf"
    )


def test_support_docs_come_from_config_and_stay_opt_in(monkeypatch):
    import client_media_assets

    _documents_config(
        monkeypatch,
        {
            "King Deluxe": {
                "brochure": "https://cdn.example/deluxe.pdf",
                "support": [
                    {"url": "https://cdn.example/warranty.pdf", "kind": "warranty"}
                ],
            }
        },
    )
    # asking for "the brochure" must still deliver exactly one file
    assert client_media_assets.product_document_pack("King Deluxe") == [
        ("https://cdn.example/deluxe.pdf", "brochure")
    ]
    assert client_media_assets.product_document_pack(
        "King Deluxe", include_support_docs=True
    ) == [
        ("https://cdn.example/deluxe.pdf", "brochure"),
        ("https://cdn.example/warranty.pdf", "warranty"),
    ]


def test_a_product_removed_from_config_sends_nothing(monkeypatch):
    import client_media_assets

    _documents_config(monkeypatch, {"King EV MAX": {"brochure": "https://x/ev.pdf"}})
    assert client_media_assets.product_brochure_url("King Deluxe") == ""
    assert client_media_assets.product_document_pack("King Deluxe") == []
    assert client_media_assets.brochure_product_from_text("king deluxe") == ""


def test_an_unreadable_config_sends_nothing_rather_than_the_wrong_brochure(
    monkeypatch,
):
    """A config problem must not send another client's document.

    This deliberately reverses the earlier trade-off. It used to send the TVS
    brochure so that a corrupt config never cost a customer their PDF — a
    reasonable call while TVS was the only client. With more than one, the
    same code would send TVS documents to somebody else's customers, so a
    broken config now yields no document at all.
    """
    import client_media_assets

    def explode():
        raise RuntimeError("config file is corrupt")

    monkeypatch.setattr(client_media_assets.admin_config, "get_store", explode)
    assert client_media_assets.product_brochure_url("King EV MAX") == ""


# --- share-location card ----------------------------------------------------


def _share_config(monkeypatch, value):
    import client_media_assets

    class FakeStore:
        def get(self):
            return {"share_location_image": value}

    monkeypatch.setattr(
        client_media_assets.admin_config, "get_store", lambda: FakeStore()
    )


def test_card_falls_back_to_the_media_host(monkeypatch):
    """Unconfigured behaves exactly as before this setting existed."""
    import client_media_assets

    _share_config(monkeypatch, {})
    monkeypatch.setattr(
        client_media_assets, "media_base_url", lambda: "https://media.example.com/media"
    )
    assert client_media_assets.share_location_image_url("Hindi") == (
        "https://media.example.com/media/share_location/how_to.jpg"
    )


def test_card_can_be_pointed_at_a_stable_cdn(monkeypatch):
    import client_media_assets

    _share_config(monkeypatch, {"url": "https://1.jamoutsourcing.com/f/how_to.jpg"})
    assert client_media_assets.share_location_image_url("Hindi") == (
        "https://1.jamoutsourcing.com/f/how_to.jpg"
    )


def test_a_language_override_wins(monkeypatch):
    import client_media_assets

    _share_config(
        monkeypatch,
        {
            "url": "https://cdn/how_to.jpg",
            "by_language": {"Tamil": "https://cdn/tamil.jpg"},
        },
    )
    assert client_media_assets.share_location_image_url("Tamil") == "https://cdn/tamil.jpg"
    assert client_media_assets.share_location_image_url("Hindi") == "https://cdn/how_to.jpg"


def test_an_unreadable_config_still_yields_a_card(monkeypatch):
    import client_media_assets

    def explode():
        raise RuntimeError("corrupt")

    monkeypatch.setattr(client_media_assets.admin_config, "get_store", explode)
    monkeypatch.setattr(client_media_assets, "media_base_url", lambda: "https://m/media")
    assert client_media_assets.share_location_image_url("Hindi").endswith("how_to.jpg")

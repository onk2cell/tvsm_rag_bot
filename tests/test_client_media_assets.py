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


def test_wants_product_brochure_detects_info_asks():
    assert wants_product_brochure("Send me the brochure")
    assert wants_product_brochure("EV MAX details please")
    assert wants_product_brochure("can you give me info about ev king max")
    assert wants_product_brochure("information about EV MAX")
    assert wants_product_brochure("मुझे जानकारी चाहिए")
    assert not wants_product_brochure("yes")
    assert not wants_product_brochure("411048")


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


def test_product_document_pack_includes_warranty_and_pms():
    ev = product_document_pack("King EV MAX")
    assert [kind for _, kind in ev] == ["brochure", "warranty"]
    assert ev[1][0].endswith("/TVS_King_EV_MAX_Warranty_Policy.pdf")

    deluxe = product_document_pack("King Deluxe", "Deluxe CNG")
    assert [kind for _, kind in deluxe] == ["brochure", "pms", "warranty"]
    assert deluxe[0][0].endswith("/King_Deluxe_CNG-English.pdf")
    assert deluxe[1][0].endswith("/Deluxe-PMS-Schedule.pdf")
    assert deluxe[2][0].endswith("/Deluxe-Warranty-Policy-new.pdf")

    duramax = product_document_pack("King Duramax Plus")
    assert [kind for _, kind in duramax] == ["brochure", "pms", "warranty"]
    assert duramax[1][0].endswith("/Duramaxplus-PMS-Schedule.pdf")
    assert duramax[2][0].endswith("/Duramaxplus-Warranty-Policy.pdf")

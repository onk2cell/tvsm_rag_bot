"""Dispose date parsing and payload mapping."""
from __future__ import annotations

from datetime import date

from dispose import (
    build_dispose_payload,
    resolve_dispose_customer_name,
    infer_dispose_status,
    normalize_product_name,
    resolve_purchase_date,
    wants_callback,
)


def test_normalize_product_name_aliases():
    assert normalize_product_name("I want EV MAX") == "King EV MAX"
    assert normalize_product_name("ev king max") == "King EV MAX"
    assert normalize_product_name("King Deluxe CNG") == "King Deluxe"
    assert normalize_product_name("duramax plus") == "King Duramax Plus"


def test_infer_interested_when_model_mentioned():
    assert (
        infer_dispose_status({"product_interest": "King EV MAX"}) == "interested"
    )


def test_infer_explicit_disposition():
    assert (
        infer_dispose_status(
            {
                "disposition": "not_interested",
                "product_interest": "King Deluxe",
            }
        )
        == "not_interested"
    )


def test_next_month_becomes_seventh():
    result = resolve_purchase_date("next month", today=date(2026, 7, 24))
    assert result.value == "07/08/2026"
    assert result.needs_exact_date is False


def test_month_name_date_parses():
    result = resolve_purchase_date("November 23, 2026", today=date(2026, 7, 24))
    assert result.value == "23/11/2026"
    assert result.rule == "month_name"
    assert (
        resolve_purchase_date("23 Nov 2026", today=date(2026, 7, 24)).value
        == "23/11/2026"
    )


def test_near_term_days_asks_for_exact_date():
    result = resolve_purchase_date("in next 10 days", today=date(2026, 7, 24))
    assert result.value is None
    assert result.needs_exact_date is True


def test_longer_day_range_computes_date():
    result = resolve_purchase_date("in 20 days", today=date(2026, 7, 24))
    assert result.value == "13/08/2026"


def test_explicit_dmy_accepted():
    result = resolve_purchase_date("looking to buy on 15/09/2026")
    assert result.value == "15/09/2026"


def test_interested_payload_includes_dealer_product_date():
    payload = build_dispose_payload(
        mobile="918459522206",
        profile={
            "product_interest": "King Deluxe",
            "purchase_timeline": "next month",
            "notes": "WhatsApp qualify",
        },
        dealer_code="11689",
        pincode="411001",
        today=date(2026, 7, 24),
    )
    assert payload is not None
    assert payload.body == {
        "mobile": "918459522206",
        "pincode": "411001",
        "status": "interested",
        "remark": payload.body["remark"],
        "dealer_code": "11689",
        "expected_purchased_date": "07/08/2026",
        "product_name": "King Deluxe",
    }
    assert "King Deluxe" in payload.body["remark"]
    assert "preferred_language" not in payload.body["remark"]


def test_dispose_includes_customername_from_lead_name():
    payload = build_dispose_payload(
        mobile="918459522206",
        profile={
            "lead_name": "Ravi Kumar",
            "product_interest": "King Deluxe",
            "purchase_timeline": "15/08/2026",
        },
        dealer_code="11689",
        pincode="411001",
        today=date(2026, 7, 24),
    )
    assert payload is not None
    assert payload.body["customername"] == "Ravi Kumar"


def test_dispose_skips_stub_customer_name():
    assert resolve_dispose_customer_name({"lead_name": "Customer 8459522206"}) == ""
    payload = build_dispose_payload(
        mobile="918459522206",
        profile={
            "lead_name": "Customer 8459522206",
            "disposition": "not_interested",
            "pincode": "411001",
        },
    )
    assert payload is not None
    assert "customername" not in payload.body


def test_dispose_remark_includes_preferred_language():
    payload = build_dispose_payload(
        mobile="918459522206",
        profile={
            "preferred_language": "Marathi",
            "product_interest": "King Deluxe",
            "purchase_timeline": "15/08/2026",
            "notes": "WhatsApp qualify",
        },
        dealer_code="11689",
        pincode="411001",
        today=date(2026, 7, 24),
    )
    assert payload is not None
    assert "preferred_language: Marathi" in payload.body["remark"]


def test_dispose_requires_pincode():
    assert (
        build_dispose_payload(
            mobile="918459522206",
            profile={"product_interest": "King Deluxe", "disposition": "not_interested"},
            dealer_code="11689",
        )
        is None
    )


def test_dispose_accepts_spaced_pincode_from_profile():
    payload = build_dispose_payload(
        mobile="918459522206",
        profile={
            "disposition": "not_interested",
            "pincode": "41 10 01",
            "notes": "no thanks",
        },
    )
    assert payload is not None
    assert payload.body["pincode"] == "411001"
    assert payload.body["status"] == "not_interested"


def test_wants_callback_detects_common_phrases():
    assert wants_callback("Please call me")
    assert wants_callback("call karo")
    assert wants_callback("कॉल करा")
    assert wants_callback("फोन करो")
    assert not wants_callback("I want King Deluxe")


def test_callback_dispose_is_interested_with_callback_remark():
    payload = build_dispose_payload(
        mobile="919922325350",
        profile={
            "callback_requested": True,
            "product_interest": "King Deluxe",
            "pincode": "411019",
        },
        dealer_code="11982",
        today=date(2026, 7, 24),
    )
    assert payload is not None
    assert payload.body["status"] == "interested"
    assert payload.body["pincode"] == "411019"
    assert "callback" in payload.body["remark"].lower()
    assert payload.body["dealer_code"] == "11982"
    assert payload.body["product_name"] == "King Deluxe"
    assert payload.body["expected_purchased_date"] == "07/08/2026"

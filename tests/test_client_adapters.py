"""HTTP delivery, CRM lookup, and server-side client state contracts."""
from __future__ import annotations

import json

import pytest
import requests

from client_adapters import (
    HttpCustomerDirectory,
    HttpReplySender,
    RedisClientState,
    ReplyDeliveryError,
)


class FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url, **kwargs):
        self.calls.append({"method": "GET", "url": url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def post(self, url, **kwargs):
        self.calls.append({"method": "POST", "url": url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_customer_lookup_uses_first_crm_match():
    http = FakeHttp(
        [
            FakeResponse(
                200,
                {
                    "customers": [
                        {
                            "customer_id": "crm-1",
                            "name": "Asha",
                            "preferred_language": "Marathi",
                        },
                        {"customer_id": "crm-2", "name": "Other"},
                    ]
                },
            )
        ]
    )
    directory = HttpCustomerDirectory(
        "https://crm.example/customers",
        username="api",
        password="secret",
        timeout=30,
        http=http,
        sleep=lambda _: None,
    )

    customer = directory.lookup("+918286871533")

    assert customer.customer_id == "crm-1"
    assert customer.name == "Asha"
    assert http.calls[0]["params"] == {"mobile": "+918286871533"}
    assert http.calls[0]["auth"] == ("api", "secret")


def test_customer_lookup_retries_transient_failures():
    http = FakeHttp(
        [
            requests.Timeout("slow"),
            FakeResponse(503),
            FakeResponse(200, {"customer_id": "crm-1", "name": "Asha"}),
        ]
    )
    waits = []
    directory = HttpCustomerDirectory(
        "https://crm.example/customers",
        timeout=30,
        http=http,
        sleep=waits.append,
        retry_wait=0.1,
    )

    assert directory.lookup("+918286871533").name == "Asha"
    assert len(http.calls) == 3
    assert waits == [0.1, 0.1]


def test_reply_sender_splits_and_correlates_long_messages():
    http = FakeHttp([FakeResponse(204), FakeResponse(200)])
    sender = HttpReplySender(
        "https://crm.example/replies",
        timeout=30,
        http=http,
        sleep=lambda _: None,
    )

    sender.send(
        mobile="+918286871533",
        in_reply_to="incoming-1",
        text="x" * 4097,
    )

    payloads = [call["json"] for call in http.calls]
    assert [len(payload["content"]) for payload in payloads] == [4096, 1]
    assert [payload["part_number"] for payload in payloads] == [1, 2]
    assert all(payload["part_count"] == 2 for payload in payloads)
    assert all(payload["in_reply_to"] == "incoming-1" for payload in payloads)
    assert payloads[0]["message_id"] != payloads[1]["message_id"]
    assert payloads[0]["timestamp"].endswith("+00:00")


def test_reply_sender_retries_three_times_then_flags_failure():
    http = FakeHttp([FakeResponse(500), FakeResponse(500), FakeResponse(500)])
    waits = []
    sender = HttpReplySender(
        "https://crm.example/replies",
        timeout=30,
        http=http,
        sleep=waits.append,
        retry_wait=30,
    )

    with pytest.raises(ReplyDeliveryError):
        sender.send(
            mobile="+918286871533",
            in_reply_to="incoming-1",
            text="hello",
        )

    assert len(http.calls) == 3
    assert waits == [30, 30]


def test_jam_whatsapp_reply_sender_uses_api_key_and_strips_plus():
    from client_adapters import JamWhatsAppReplySender

    http = FakeHttp([FakeResponse(200, {"status": "success", "data": {}})])
    sender = JamWhatsAppReplySender(
        "https://tvsm.jamoutsourcing.com/index.php/whatsapp_bot/send",
        api_key="secret-key",
        timeout=30,
        http=http,
        sleep=lambda _: None,
    )

    sender.send(
        mobile="+918459522206",
        in_reply_to="incoming-1",
        text="Hello from bot",
    )

    call = http.calls[0]
    assert call["url"].endswith("/whatsapp_bot/send")
    assert call["headers"]["X-API-KEY"] == "secret-key"
    assert call["json"] == {
        "mobile": "918459522206",
        "type": "text",
        "message": "Hello from bot",
    }


def test_jam_whatsapp_reply_sender_splits_long_text():
    from client_adapters import JamWhatsAppReplySender

    http = FakeHttp(
        [
            FakeResponse(200, {"status": "success"}),
            FakeResponse(200, {"status": "success"}),
        ]
    )
    sender = JamWhatsAppReplySender(
        "https://tvsm.jamoutsourcing.com/index.php/whatsapp_bot/send",
        api_key="secret-key",
        http=http,
        sleep=lambda _: None,
    )

    sender.send(
        mobile="918459522206",
        in_reply_to="incoming-1",
        text="x" * 4097,
    )

    assert [len(call["json"]["message"]) for call in http.calls] == [4096, 1]


def test_jam_whatsapp_reply_sender_send_image():
    from client_adapters import JamWhatsAppReplySender

    http = FakeHttp([FakeResponse(200, {"status": "success", "data": {}})])
    sender = JamWhatsAppReplySender(
        "https://tvsm.jamoutsourcing.com/index.php/whatsapp_bot/send",
        api_key="secret-key",
        http=http,
        sleep=lambda _: None,
    )

    sender.send_image(
        mobile="+918459522206",
        link="https://aichatbot.jamoutsourcing.com/media/share_location/english.jpg",
        caption="Please share location",
    )

    assert http.calls[0]["json"] == {
        "mobile": "918459522206",
        "type": "image",
        "link": "https://aichatbot.jamoutsourcing.com/media/share_location/english.jpg",
        "message": "Please share location",
    }


def test_jam_whatsapp_reply_sender_send_document():
    from client_adapters import JamWhatsAppReplySender

    http = FakeHttp([FakeResponse(200, {"status": "success", "data": {}})])
    sender = JamWhatsAppReplySender(
        "https://tvsm.jamoutsourcing.com/index.php/whatsapp_bot/send",
        api_key="secret-key",
        http=http,
        sleep=lambda _: None,
    )

    sender.send_document(
        mobile="+918459522206",
        link="https://example.com/media/brochures/king_ev_max.pdf",
        caption="King EV MAX brochure",
    )

    assert http.calls[0]["json"] == {
        "mobile": "918459522206",
        "type": "document",
        "link": "https://example.com/media/brochures/king_ev_max.pdf",
        "message": "King EV MAX brochure",
    }


def test_jam_dispose_client_posts_payload_with_api_key():
    from client_adapters import JamDisposeClient

    http = FakeHttp([FakeResponse(200, {"status": "success", "message": "ok"})])
    client = JamDisposeClient(
        "https://tvsm.jamoutsourcing.com/index.php/whatsapp_bot/dispose",
        api_key="secret-key",
        http=http,
        sleep=lambda _: None,
    )

    client.dispose(
        {
            "mobile": "+918459522206",
            "status": "interested",
            "remark": "ok",
            "dealer_code": "11689",
            "expected_purchased_date": "07/08/2026",
            "product_name": "King Deluxe",
        }
    )

    call = http.calls[0]
    assert call["url"].endswith("/dispose")
    assert call["headers"]["X-API-KEY"] == "secret-key"
    assert call["json"]["mobile"] == "918459522206"
    assert call["json"]["status"] == "interested"


def test_jam_customer_directory_does_not_invent_language_from_state():
    from client_adapters import JamCustomerDirectory

    http = FakeHttp(
        [
            FakeResponse(
                200,
                {
                    "status": "success",
                    "data": {
                        "fldi_lead_id": 123,
                        "Customer Name": "Ravi Kumar",
                        "State": "MAHARASHTRA",
                    },
                },
            )
        ]
    )
    directory = JamCustomerDirectory(
        "https://tvsm.jamoutsourcing.com/index.php/whatsapp_bot/customer",
        api_key="secret-key",
        http=http,
        sleep=lambda _: None,
    )

    customer = directory.lookup("+918459522206")

    assert customer.customer_id == "123"
    assert customer.name == "Ravi Kumar"
    assert customer.state == "MAHARASHTRA"
    # Maharashtra must NOT force Marathi — customer gets the language menu.
    assert customer.preferred_language == ""
    assert http.calls[0]["json"] == {"mobile": "918459522206"}
    assert http.calls[0]["headers"]["X-API-KEY"] == "secret-key"


def test_jam_customer_directory_recovers_language_from_dispose_remark():
    from client_adapters import JamCustomerDirectory

    http = FakeHttp(
        [
            FakeResponse(
                200,
                {
                    "status": "success",
                    "data": {
                        "fldi_lead_id": 123,
                        "Customer Name": "Ravi Kumar",
                        "State": "MAHARASHTRA",
                        "fldt_last_comment": (
                            "preferred_language: Hindi | product_interest: King EV MAX"
                        ),
                    },
                },
            )
        ]
    )
    directory = JamCustomerDirectory(
        "https://tvsm.jamoutsourcing.com/index.php/whatsapp_bot/customer",
        api_key="secret-key",
        http=http,
        sleep=lambda _: None,
    )

    customer = directory.lookup("+918459522206")
    assert customer.preferred_language == "Hindi"


def test_jam_customer_directory_maps_product_and_dealership_fields():
    from client_adapters import JamCustomerDirectory

    http = FakeHttp(
        [
            FakeResponse(
                200,
                {
                    "status": "success",
                    "data": {
                        "fldi_lead_id": 307569,
                        "Customer Name": "Ajit Trimbak Sutar",
                        "State": "MAHARASHTRA",
                        "City": "Pune",
                        "Dealership Id": "11982",
                        "Dealership Name": "Sarthak Auto",
                        "Product Enquired": "TVS KING PASSENGER DELUXE",
                    },
                },
            )
        ]
    )
    directory = JamCustomerDirectory(
        "https://tvsm.jamoutsourcing.com/index.php/whatsapp_bot/customer",
        api_key="secret-key",
        http=http,
        sleep=lambda _: None,
    )

    customer = directory.lookup("919922325350")

    assert customer.product_enquired == "TVS KING PASSENGER DELUXE"
    assert customer.dealership_id == "11982"
    assert customer.dealership_name == "Sarthak Auto"
    assert customer.city == "Pune"
    assert customer.state == "MAHARASHTRA"
    assert customer.preferred_language == ""


def test_jam_customer_directory_maps_last_remark_and_status():
    from client_adapters import JamCustomerDirectory

    http = FakeHttp(
        [
            FakeResponse(
                200,
                {
                    "status": "success",
                    "data": {
                        "fldi_lead_id": 1,
                        "Customer Name": "Ravi",
                        "State": "KERALA",
                        "fldt_last_comment": "Asked for callback on King Deluxe",
                        "fldv_last_status": "Call Back",
                    },
                },
            )
        ]
    )
    directory = JamCustomerDirectory(
        "https://tvsm.jamoutsourcing.com/index.php/whatsapp_bot/customer",
        api_key="secret-key",
        http=http,
        sleep=lambda _: None,
    )

    customer = directory.lookup("919999999999")
    assert customer.last_remark == "Asked for callback on King Deluxe"
    assert customer.last_status == "Call Back"
    assert customer.preferred_language == ""


def test_jam_customer_directory_404_returns_empty_language_for_picker():
    from client_adapters import JamCustomerDirectory

    http = FakeHttp([FakeResponse(404, {"status": "fail", "message": "No customer"})])
    directory = JamCustomerDirectory(
        "https://tvsm.jamoutsourcing.com/index.php/whatsapp_bot/customer",
        api_key="secret-key",
        http=http,
        sleep=lambda _: None,
    )

    customer = directory.lookup("918459522206")

    assert customer.preferred_language == ""
    assert customer.customer_id.startswith("unknown-")


def test_stub_customer_directory_builds_identity_from_mobile():
    from client_adapters import StubCustomerDirectory

    customer = StubCustomerDirectory().lookup("+918459522206")

    assert customer.customer_id == "stub-918459522206"
    assert customer.name == "Customer 8459522206"
    assert customer.preferred_language == "English"


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}
        self.expiries: dict[str, int] = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None, **_):
        self.data[key] = value
        if ex:
            self.expiries[key] = ex
        return True


def test_client_state_persists_history_customer_and_four_hour_ttl():
    redis = FakeRedis()
    state = RedisClientState(redis, ttl_seconds=14400, id_factory=lambda: "conversation-1")
    session = state.load_or_start("+918286871533")
    session.history.append({"role": "user", "text": "hi"})
    state.save(session)

    loaded = state.load_or_start("+918286871533")

    assert loaded.conversation_id == "conversation-1"
    assert loaded.history == [{"role": "user", "text": "hi"}]
    assert redis.expiries["client:session:+918286871533"] == 14400
    assert json.loads(redis.data["client:session:+918286871533"])["mobile"] == (
        "+918286871533"
    )

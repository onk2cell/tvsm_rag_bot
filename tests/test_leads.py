"""Tests for leads.LeadWriter."""
from __future__ import annotations

import csv
import json

from admin_config import AdminConfigStore
from leads import LeadWriter


def test_lead_writer_creates_file_with_dynamic_header(tmp_path):
    config_store = AdminConfigStore(tmp_path / "cfg.json")
    config_store.ensure_seeded()
    writer = LeadWriter(tmp_path / "leads.csv", config_store)
    writer.append(
        channel="web",
        source="web",
        session="s1",
        language="English",
        profile={"product_interest": "King EV MAX", "lead_quality": "WARM"},
    )
    rows = list(csv.DictReader((tmp_path / "leads.csv").open(encoding="utf-8-sig")))
    assert rows[0]["product_interest"] == "King EV MAX"
    assert rows[0]["channel"] == "web"


def test_client_lead_is_created_then_updated_in_place(tmp_path):
    config_store = AdminConfigStore(tmp_path / "cfg.json")
    config_store.ensure_seeded()
    writer = LeadWriter(tmp_path / "leads.csv", config_store)

    writer.upsert_client_identity(
        session="client-conversation-1",
        mobile="+918286871533",
        customer_id="crm-1",
        customer_name="Asha",
        language="Marathi",
    )
    writer.append(
        channel="client_app",
        source="client_app",
        session="client-conversation-1",
        language="Marathi",
        profile={"product_interest": "King EV MAX", "lead_quality": "HOT"},
    )

    rows = list(csv.DictReader((tmp_path / "leads.csv").open(encoding="utf-8-sig")))
    assert len(rows) == 1
    assert rows[0]["mobile"] == "+918286871533"
    assert rows[0]["crm_customer_id"] == "crm-1"
    assert rows[0]["customer_name"] == "Asha"
    assert rows[0]["product_interest"] == "King EV MAX"


def test_client_documents_deduplicate_exact_url(tmp_path):
    config_store = AdminConfigStore(tmp_path / "cfg.json")
    config_store.ensure_seeded()
    writer = LeadWriter(tmp_path / "leads.csv", config_store)
    writer.upsert_client_identity(
        session="client-conversation-1",
        mobile="+918286871533",
        customer_id="crm-1",
        customer_name="Asha",
        language="Marathi",
    )

    for _ in range(2):
        writer.add_documents(
            session="client-conversation-1",
            document_types=["driving_licence", "permit"],
            url="https://client.example/document.jpg",
            status="recognized",
        )

    rows = list(csv.DictReader((tmp_path / "leads.csv").open(encoding="utf-8-sig")))
    documents = json.loads(rows[0]["documents"])
    assert documents == [
        {
            "types": ["driving_licence", "permit"],
            "url": "https://client.example/document.jpg",
            "status": "recognized",
        }
    ]

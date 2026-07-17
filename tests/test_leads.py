"""Tests for leads.LeadWriter."""
from __future__ import annotations

import csv

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

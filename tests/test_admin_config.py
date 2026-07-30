"""Tests for admin_config.AdminConfigStore."""
from __future__ import annotations

import json

import pytest

from admin_config import (
    AdminConfigStore,
    csv_columns,
    default_config,
    validate_config,
)


@pytest.fixture
def store(tmp_path):
    return AdminConfigStore(tmp_path / "admin_config.json")


def test_default_config_has_required_keys():
    cfg = default_config()
    for key in (
        "bot_name",
        "welcome_text",
        "languages",
        "capture_fields",
        "flow_steps",
        "voice_policy",
        "campaign_text",
        "intro",
    ):
        assert key in cfg
    assert len(cfg["languages"]) == 7
    assert cfg["voice_policy"] == "intro_only"


def test_ensure_seeded_creates_file(store):
    assert not store.path.exists()
    cfg = store.ensure_seeded()
    assert store.path.exists()
    assert cfg["bot_name"] == "TVS Passenger 3W Assistant"
    reloaded = json.loads(store.path.read_text(encoding="utf-8"))
    assert reloaded["bot_name"] == cfg["bot_name"]


def test_get_reloads_after_external_edit(store):
    store.ensure_seeded()
    data = json.loads(store.path.read_text(encoding="utf-8"))
    data["bot_name"] = "Updated Name"
    store.path.write_text(json.dumps(data), encoding="utf-8")
    assert store.get()["bot_name"] == "Updated Name"


def test_update_persists_valid_config(store):
    store.ensure_seeded()
    cfg = store.get()
    cfg["bot_name"] = "New Bot"
    cfg["campaign_text"] = "Summer offer"
    out = store.update(cfg)
    assert out["bot_name"] == "New Bot"
    assert store.get()["campaign_text"] == "Summer offer"


def test_update_rejects_missing_language_intro(store):
    store.ensure_seeded()
    cfg = store.get()
    del cfg["intro"]["Tamil"]
    with pytest.raises(ValueError, match="intro missing entry for language: Tamil"):
        store.update(cfg)


def test_update_rejects_invalid_voice_policy(store):
    store.ensure_seeded()
    cfg = store.get()
    cfg["voice_policy"] = "sometimes"
    with pytest.raises(ValueError, match="voice_policy must be one of"):
        store.update(cfg)


def test_update_rejects_duplicate_capture_field_id(store):
    store.ensure_seeded()
    cfg = store.get()
    cfg["capture_fields"].append({"id": "pincode", "required": False})
    with pytest.raises(ValueError, match="Duplicate capture field id"):
        store.update(cfg)


def test_csv_columns_order(store):
    cfg = default_config()
    cols = csv_columns(cfg)
    assert cols[:5] == ["timestamp", "channel", "source", "session", "language"]
    assert "product_interest" in cols
    assert "delivery_location" in cols


def test_validate_config_rejects_non_object():
    with pytest.raises(ValueError, match="must be a JSON object"):
        validate_config([])

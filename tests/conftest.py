"""Pytest fixtures — set env before app modules load."""
from __future__ import annotations

import os

# Minimal env so config.py and web.py import without a real deployment.
os.environ.setdefault("FILE_SEARCH_STORE", "fileSearchStores/test")
os.environ.setdefault("WHATSAPP_TOKEN", "test-token")
os.environ.setdefault("PHONE_NUMBER_ID", "123456")
os.environ.setdefault("VERIFY_TOKEN", "verify-test")
os.environ.setdefault("ADMIN_TOKEN", "admin-test-token")
os.environ.setdefault("ADMIN_CONFIG_PATH", "data/test_admin_config.json")

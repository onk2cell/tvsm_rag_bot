"""Pytest fixtures — set env before app modules load."""
from __future__ import annotations

import os

# Minimal env so config.py imports without a real deployment.
os.environ.setdefault("FILE_SEARCH_STORE", "fileSearchStores/test")
os.environ.setdefault("ADMIN_TOKEN", "admin-test-token")
os.environ.setdefault("ADMIN_CONFIG_PATH", "data/test_admin_config.json")

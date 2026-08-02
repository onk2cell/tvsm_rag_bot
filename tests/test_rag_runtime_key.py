"""Runtime Gemini-key persistence + cross-process reload (rag.py)."""
from __future__ import annotations

import pytest

import config
import rag


@pytest.fixture
def key_env(tmp_path, monkeypatch):
    """Isolate the runtime key file and stub out real client creation."""
    path = tmp_path / "gemini_key.txt"
    monkeypatch.setattr(config, "GEMINI_KEY_RUNTIME_PATH", str(path))
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    # Rebuild the client with a sentinel instead of a real genai.Client.
    def fake_set(api_key, validate=False):
        if not api_key:
            raise ValueError("API key must not be empty")
        rag._client = f"client::{api_key}"
    monkeypatch.setattr(rag, "set_api_key", fake_set)
    monkeypatch.setattr(rag, "_client", None)
    monkeypatch.setattr(rag, "_runtime_key_mtime", None)
    return path


def test_persist_writes_secure_file_and_activates(key_env):
    rag.persist_api_key("AIza-runtime", validate=False)
    assert key_env.read_text(encoding="utf-8") == "AIza-runtime"
    assert (key_env.stat().st_mode & 0o777) == 0o600
    assert rag.has_client() is True
    assert rag.runtime_key_active() is True


def test_get_client_lazily_adopts_key_written_by_another_process(key_env):
    # Simulate the admin process persisting a key by writing the file directly.
    assert rag.has_client() is False
    key_env.write_text("AIza-from-admin", encoding="utf-8")
    # The worker process only ever calls get_client()/has_client().
    assert rag.get_client() == "client::AIza-from-admin"


def test_key_rotation_is_picked_up_on_change(key_env, monkeypatch):
    import os

    rag.persist_api_key("AIza-one", validate=False)
    assert rag.get_client() == "client::AIza-one"
    # Rewrite with a newer mtime; next read should adopt the rotated key.
    key_env.write_text("AIza-two", encoding="utf-8")
    os.utime(key_env, (10**10, 10**10))
    assert rag.get_client() == "client::AIza-two"


def test_clear_removes_file_and_falls_back_to_env(key_env, monkeypatch):
    rag.persist_api_key("AIza-runtime", validate=False)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "AIza-env")
    rag.clear_persisted_key()
    assert not key_env.exists()
    assert rag.runtime_key_active() is False
    # Fell back to the env key.
    assert rag.get_client() == "client::AIza-env"

"""cached_context.py — the flag, the cache lifecycle, the ladder, the fallback."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors

import cached_context
import corpus as corpus_module
from cached_context import (
    CORPUS_ACK,
    CachedContextAdapter,
    ContextCache,
    FallbackLLM,
    Registry,
    build_smart_llm,
    cache_key,
)
from conversation_engine import GeminiLLMAdapter

T0 = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def _client_error(code: int, message: str = "nope") -> genai_errors.ClientError:
    return genai_errors.ClientError(code, {"error": {"code": code, "message": message}})


class FakeClock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakeCaches:
    """Enough of client.caches to exercise create / list / update."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.created: list[dict] = []
        self.updated: list[str] = []
        self.listed = 0
        self.existing: list[SimpleNamespace] = []
        self.create_error: Exception | None = None
        self.update_error: Exception | None = None
        self.list_error: Exception | None = None
        self._n = 0

    def create(self, *, model, config):
        if self.create_error:
            raise self.create_error
        self._n += 1
        self.created.append({"model": model, "config": config})
        return SimpleNamespace(
            name=f"cachedContents/c{self._n}",
            display_name=config.display_name,
            expire_time=self.clock() + timedelta(seconds=int(config.ttl[:-1])),
            usage_metadata=SimpleNamespace(total_token_count=10_500),
        )

    def list(self):
        self.listed += 1
        if self.list_error:
            raise self.list_error
        return iter(self.existing)

    def update(self, *, name, config):
        if self.update_error:
            raise self.update_error
        self.updated.append(name)
        return SimpleNamespace(
            name=name, expire_time=self.clock() + timedelta(seconds=int(config.ttl[:-1])),
        )


class FakeModels:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.errors: list[Exception] = []   # popped per call, in order
        self.text = "answer"

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.errors:
            raise self.errors.pop(0)
        cached = 10_500 if "cached_content" in config else 0
        return SimpleNamespace(
            text=self.text,
            usage_metadata=SimpleNamespace(
                prompt_token_count=10_600, candidates_token_count=40,
                cached_content_token_count=cached,
            ),
        )


class FakeClient:
    def __init__(self, clock: FakeClock) -> None:
        self.caches = FakeCaches(clock)
        self.models = FakeModels()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def client(clock):
    return FakeClient(clock)


@pytest.fixture
def registry(tmp_path, clock):
    return Registry(tmp_path / "caches.json", clock=clock)


@pytest.fixture
def kb(tmp_path):
    root = tmp_path / "kb"
    root.mkdir()
    (root / "one.md").write_text("# One\n\nRange 179 km.\n", encoding="utf-8")
    return corpus_module.build(root)


@pytest.fixture
def adapter(client, registry, kb, clock, monkeypatch):
    monkeypatch.setenv("CACHED_CONTEXT_LOG_PATH", "")
    return CachedContextAdapter(
        "gemini-test", kb, registry=registry, ttl_seconds=3600,
        client_factory=lambda: client, clock=clock,
    )


CONTENTS = [{"role": "user", "parts": [{"text": "KNOWN SO FAR: -\n\nWhat is the range?"}]}]


# --- the request shape ---------------------------------------------------------

def test_first_turn_creates_the_cache_with_instruction_and_corpus(adapter, client, kb):
    result = adapter.generate(system_instruction="SYS", contents=CONTENTS)

    assert result.text == "answer"
    assert result.citations == []
    assert result.prompt_tokens == 10_600 and result.completion_tokens == 40
    [created] = client.caches.created
    assert created["model"] == "gemini-test"
    assert created["config"].system_instruction == "SYS"
    assert created["config"].display_name == "tvsm-kb/" + cache_key("gemini-test", "SYS", kb.sha256)
    corpus_turn, ack = created["config"].contents      # coerced to types.Content by the SDK
    assert corpus_turn.role == "user" and kb.text in corpus_turn.parts[0].text
    assert ack.role == "model" and ack.parts[0].text == CORPUS_ACK
    [call] = client.models.calls
    assert call["config"] == {"cached_content": "cachedContents/c1", "temperature": 0.3}
    assert "system_instruction" not in call["config"]
    assert call["contents"] == CONTENTS      # history + question only; the corpus is in the cache


def test_second_turn_reuses_the_cache(adapter, client):
    adapter.generate(system_instruction="SYS", contents=CONTENTS)
    adapter.generate(system_instruction="SYS", contents=CONTENTS)
    assert len(client.caches.created) == 1
    assert client.caches.listed == 1        # once, cold, before creating; never per turn


def test_a_different_instruction_is_a_different_cache(adapter, client):
    adapter.generate(system_instruction="SYS in Hindi", contents=CONTENTS)
    adapter.generate(system_instruction="SYS in Marathi", contents=CONTENTS)
    names = {c["config"].display_name for c in client.caches.created}
    assert len(names) == 2


# --- the lifecycle ------------------------------------------------------------

def test_a_new_process_recalls_the_handle_from_the_registry(client, registry, kb, clock, monkeypatch):
    monkeypatch.setenv("CACHED_CONTEXT_LOG_PATH", "")
    first = CachedContextAdapter("m", kb, registry=registry, ttl_seconds=3600,
                                 client_factory=lambda: client, clock=clock)
    first.generate(system_instruction="SYS", contents=CONTENTS)

    second = CachedContextAdapter("m", kb, registry=registry, ttl_seconds=3600,
                                  client_factory=lambda: client, clock=clock)
    second.generate(system_instruction="SYS", contents=CONTENTS)

    assert len(client.caches.created) == 1
    assert client.caches.listed == 1        # the first process, cold; the second recalled the handle
    assert client.models.calls[-1]["config"]["cached_content"] == "cachedContents/c1"


def test_without_a_registry_entry_a_live_cache_is_adopted_from_the_provider(client, registry, kb, clock):
    key = cache_key("m", "SYS", kb.sha256)
    client.caches.existing = [SimpleNamespace(
        name="cachedContents/old", display_name="tvsm-kb/" + key,
        expire_time=clock() + timedelta(hours=1),
        usage_metadata=SimpleNamespace(total_token_count=9_000),
    )]
    cache = ContextCache(client, registry, model="m", system_instruction="SYS",
                         corpus_text=kb.text, corpus_sha256=kb.sha256, ttl_seconds=3600, clock=clock)
    assert cache.name() == "cachedContents/old"
    assert client.caches.created == []
    assert registry.get(key)[0] == "cachedContents/old"


def test_a_nearly_expired_cache_is_extended_then_recreated_if_that_fails(client, registry, kb, clock):
    cache = ContextCache(client, registry, model="m", system_instruction="SYS",
                         corpus_text=kb.text, corpus_sha256=kb.sha256, ttl_seconds=3600, clock=clock)
    cache.name()
    clock.tick(3600 - 100)                       # inside the 300 s margin
    assert cache.name() == "cachedContents/c1"
    assert client.caches.updated == ["cachedContents/c1"]

    clock.tick(3600 - 100)
    client.caches.update_error = RuntimeError("update failed")
    assert cache.name() == "cachedContents/c2"


def test_a_stale_registry_entry_is_not_recalled(client, registry, kb, clock):
    key = cache_key("m", "SYS", kb.sha256)
    registry.put(key, "cachedContents/stale", clock() + timedelta(seconds=10), tokens=1)
    cache = ContextCache(client, registry, model="m", system_instruction="SYS",
                         corpus_text=kb.text, corpus_sha256=kb.sha256, ttl_seconds=3600, clock=clock)
    assert cache.name() == "cachedContents/c1"


def test_a_cache_the_provider_lost_is_rebuilt_once_in_the_same_turn(adapter, client, registry, kb):
    adapter.generate(system_instruction="SYS", contents=CONTENTS)
    client.models.errors = [_client_error(404, "CachedContent not found")]

    result = adapter.generate(system_instruction="SYS", contents=CONTENTS)

    assert result.text == "answer"
    assert [c["config"].display_name for c in client.caches.created] == [
        "tvsm-kb/" + cache_key("gemini-test", "SYS", kb.sha256)] * 2
    assert client.models.calls[-1]["config"]["cached_content"] == "cachedContents/c2"
    assert registry.get(cache_key("gemini-test", "SYS", kb.sha256))[0] == "cachedContents/c2"


# --- the ladder ---------------------------------------------------------------

def test_a_malformed_request_steps_down_to_inline_and_is_remembered(adapter, client, registry, clock, kb):
    client.caches.create_error = _client_error(400, "Caching is not supported for this model")

    result = adapter.generate(system_instruction="SYS", contents=CONTENTS)

    assert result.text == "answer"
    [call] = client.models.calls
    assert call["config"] == {"system_instruction": "SYS", "temperature": 0.3}
    assert call["contents"][0]["role"] == "user" and kb.text in call["contents"][0]["parts"][0]["text"]
    assert call["contents"][1]["parts"][0]["text"] == CORPUS_ACK
    assert call["contents"][2:] == CONTENTS
    assert registry.inline_until() == clock() + timedelta(seconds=cached_context.REPROBE_SECONDS)

    # The next turn goes inline without touching the cache API again...
    client.caches.create_error = None
    adapter.generate(system_instruction="SYS", contents=CONTENTS)
    assert client.caches.created == []
    # ...until the window passes, when the cache is probed again.
    clock.tick(cached_context.REPROBE_SECONDS + 1)
    adapter.generate(system_instruction="SYS", contents=CONTENTS)
    assert len(client.caches.created) == 1
    assert client.models.calls[-1]["config"]["cached_content"] == "cachedContents/c1"


@pytest.mark.parametrize("code", [401, 403, 429])
def test_auth_and_quota_errors_are_not_shape_problems(adapter, client, registry, code):
    client.caches.create_error = _client_error(code)
    with pytest.raises(genai_errors.ClientError):
        adapter.generate(system_instruction="SYS", contents=CONTENTS)
    assert registry.inline_until() is None
    assert client.models.calls == []


def test_server_errors_propagate_untouched(adapter, client):
    client.models.errors = [genai_errors.ServerError(503, {"error": {"message": "busy"}})]
    with pytest.raises(genai_errors.ServerError):
        adapter.generate(system_instruction="SYS", contents=CONTENTS)


# --- the fallback and the flag ---------------------------------------------------

def test_fallback_serves_the_turn_when_the_primary_raises():
    class Boom:
        def generate(self, **_):
            raise RuntimeError("cache exploded")

    class Old:
        def __init__(self):
            self.calls = []

        def generate(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(text="old path")

    old = Old()
    result = FallbackLLM(Boom(), old).generate(system_instruction="SYS", contents=CONTENTS)
    assert result.text == "old path"
    assert old.calls == [{"system_instruction": "SYS", "contents": CONTENTS}]


def test_flag_off_is_the_plain_file_search_adapter(monkeypatch):
    monkeypatch.setattr("config.CACHED_CONTEXT", False)
    llm = build_smart_llm("m", "fileSearchStores/x")
    assert type(llm) is GeminiLLMAdapter
    assert llm._store == "fileSearchStores/x"


def test_flag_on_wraps_the_cached_adapter_around_the_old_one(monkeypatch, tmp_path):
    monkeypatch.setattr("config.CACHED_CONTEXT", True)
    monkeypatch.setattr("config.CACHED_CONTEXT_REGISTRY_PATH", str(tmp_path / "r.json"))
    monkeypatch.setenv("CACHED_CONTEXT_LOG_PATH", "")
    llm = build_smart_llm("m", "fileSearchStores/x")
    assert isinstance(llm, FallbackLLM)
    assert isinstance(llm.primary, CachedContextAdapter)
    assert type(llm.fallback) is GeminiLLMAdapter


def test_flag_on_with_an_unusable_corpus_serves_the_old_path(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr("config.CACHED_CONTEXT", True)
    monkeypatch.setattr("config.KNOWLEDGE_BASE_DIR", str(tmp_path / "missing"))
    with caplog.at_level("WARNING", logger="cached_context"):
        llm = build_smart_llm("m", "fileSearchStores/x")
    assert type(llm) is GeminiLLMAdapter
    assert "cached context unavailable" in caplog.text


def test_flag_on_refuses_a_corpus_over_the_token_limit(monkeypatch):
    monkeypatch.setattr("config.CACHED_CONTEXT", True)
    monkeypatch.setattr("config.CACHED_CONTEXT_MAX_TOKENS", 10)
    llm = build_smart_llm("m", "fileSearchStores/x")
    assert type(llm) is GeminiLLMAdapter


def test_registry_survives_a_corrupt_file_and_prunes_expired_entries(tmp_path, clock):
    path = tmp_path / "r.json"
    path.write_text("{not json", encoding="utf-8")
    registry = Registry(path, clock=clock)
    assert registry.get("k") is None
    registry.put("old", "cachedContents/old", clock() + timedelta(seconds=5), tokens=1)
    registry.put("new", "cachedContents/new", clock() + timedelta(hours=1), tokens=1)
    clock.tick(10)
    registry.set_inline_until(None)         # any write prunes
    assert registry.get("old") is None
    assert registry.get("new")[0] == "cachedContents/new"

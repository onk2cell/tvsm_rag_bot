"""Answer from the whole knowledge base held in a Gemini context cache.

The second way the smart tier answers (``CACHED_CONTEXT=true``). Instead of
File Search retrieving passages per turn, the whole corpus and the system
instruction sit in a provider-side cache and the model answers in one call::

    [ system instruction ][ knowledge base ] [ history ][ known state + question ]
    └──────── cached, never changes ───────┘ └────────── sent each turn ─────────┘

The prefix is what is cached, so everything that varies rides at the end:
``build_contents`` already keeps the known-state snapshot on the user turn
for that reason. The system instruction *does* vary — per language, product
hint and admin config — and an explicit cache cannot take a per-request
instruction, so there is one cache per distinct instruction, keyed on
sha256(model, instruction, corpus). That is a handful of caches (three
languages times a few hints), each living ``CACHED_CONTEXT_TTL_SECONDS``.

Handles live in a small JSON registry under ``data/`` because the RQ
worker forks a fresh process per job: without it every turn would pay a
``caches.list()`` round-trip to find the cache the previous turn made.

Nothing about the provider API is assumed. A request the provider rejects
as malformed (a 4xx that is not auth or quota — the model does not support
caching, the corpus is under the cache minimum) steps the adapter down to
sending the corpus inline, remembered for ``REPROBE_SECONDS``. A cache the
provider says is gone is rebuilt once, in place. Anything else propagates,
and ``FallbackLLM`` serves the turn from the File Search adapter — the
customer sees an answer either way, the log sees why.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from google.genai import errors as genai_errors
from google.genai import types

import config
import corpus as corpus_module
from conversation_engine import GenerateResult, GeminiLLMAdapter, _extract_usage

log = logging.getLogger(__name__)

DISPLAY_PREFIX = "tvsm-kb/"

# What frames the corpus when it is sent as a turn. Hashed into the cache
# key, so changing it changes the cache.
CORPUS_PREAMBLE = (
    "KNOWLEDGE BASE. The complete TVS three-wheeler documents follow, each "
    "inside a <document> tag whose source attribute names the file. These "
    "are the only documents; use them, and only them, for every fact about "
    "the vehicles, their specifications, warranty and financing."
)
CORPUS_ACK = "Understood. I will answer from these documents only."

# Mirrors GeminiLLMAdapter so the only thing that changes between the two
# paths is how the model sees the knowledge base.
TEMPERATURE = 0.3

# How long a step down to inline is remembered before the cache is tried
# again. A rejection is usually permanent (the model does not support
# caching) but a provider incident should not pin the bot on the poorer,
# full-price request shape for good.
REPROBE_SECONDS = 900

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _log_handler_once() -> None:
    """Per-turn metrics also go to a file: the worker has no logging config,
    so INFO from this module would otherwise never be seen in production,
    and a cache hit rate that cannot be seen cannot be trusted."""
    if getattr(_log_handler_once, "done", False):
        return
    _log_handler_once.done = True  # type: ignore[attr-defined]
    path = os.environ.get("CACHED_CONTEXT_LOG_PATH", "data/cached_context.log")
    if not path:
        return
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
        if log.level == logging.NOTSET or log.level > logging.INFO:
            log.setLevel(logging.INFO)
    except OSError:
        pass


# --- the registry ----------------------------------------------------------

class Registry:
    """Cache handles and the step-down window, shared between processes.

    A plain JSON file, rewritten atomically. Losing it costs one
    ``caches.list()`` (or one creation) per key, never a wrong answer.
    """

    def __init__(self, path: str | Path, *, clock: Clock = _utcnow) -> None:
        self._path = Path(path)
        self._clock = clock
        self._lock = threading.Lock()

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict[str, Any]) -> None:
        now = self._clock()
        caches = {
            key: entry for key, entry in data.get("caches", {}).items()
            if _parse_time(entry.get("expires")) and _parse_time(entry["expires"]) > now
        }
        data["caches"] = caches
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(self._path.name + ".tmp")
            tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as exc:
            log.info("could not write %s (%s); handles will not outlive this process",
                     self._path, exc)

    def get(self, key: str) -> tuple[str, datetime] | None:
        with self._lock:
            entry = self._read().get("caches", {}).get(key)
        if not entry:
            return None
        expires = _parse_time(entry.get("expires"))
        if not entry.get("name") or expires is None:
            return None
        return entry["name"], expires

    def put(self, key: str, name: str, expires: datetime, *, tokens: int | None) -> None:
        with self._lock:
            data = self._read()
            data.setdefault("caches", {})[key] = {
                "name": name, "expires": expires.isoformat(), "tokens": tokens,
            }
            self._write(data)

    def drop(self, key: str) -> None:
        with self._lock:
            data = self._read()
            if data.get("caches", {}).pop(key, None) is not None:
                self._write(data)

    def inline_until(self) -> datetime | None:
        with self._lock:
            return _parse_time(self._read().get("inline_until"))

    def set_inline_until(self, when: datetime | None) -> None:
        with self._lock:
            data = self._read()
            if when is None:
                data.pop("inline_until", None)
            else:
                data["inline_until"] = when.isoformat()
            self._write(data)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# --- one cache -------------------------------------------------------------

def cache_key(model: str, system_instruction: str, corpus_sha256: str) -> str:
    digest = hashlib.sha256("\x1f".join([
        model, system_instruction, corpus_sha256,
        CORPUS_PREAMBLE, CORPUS_ACK, str(corpus_module.FORMAT_VERSION),
    ]).encode("utf-8")).hexdigest()
    return digest[:16]


def corpus_turns(corpus_text: str) -> list[dict]:
    """The knowledge base as a user turn the model has acknowledged, so the
    conversation history can follow with its roles intact."""
    return [
        {"role": "user", "parts": [{"text": f"{CORPUS_PREAMBLE}\n\n{corpus_text}"}]},
        {"role": "model", "parts": [{"text": CORPUS_ACK}]},
    ]


class ContextCache:
    """A handle for one (model, instruction, corpus) that is valid right now.

    Created on first use, adopted from the registry or from the provider's
    listing when another process already made it, extended before it
    expires, forgotten when the provider says it is gone. Provider errors
    propagate: whether a failure means "send inline" or "fall back" is the
    adapter's call.
    """

    def __init__(
        self,
        client,
        registry: Registry,
        *,
        model: str,
        system_instruction: str,
        corpus_text: str,
        corpus_sha256: str,
        ttl_seconds: int,
        clock: Clock = _utcnow,
    ) -> None:
        self._client = client
        self._registry = registry
        self._model = model
        self._system_instruction = system_instruction
        self._corpus_text = corpus_text
        self._ttl = max(int(ttl_seconds), 60)
        self._clock = clock
        # Renew when this close to expiry: a tenth of the TTL, capped, so a
        # short TTL in a test still leaves a usable window.
        self._margin = timedelta(seconds=min(self._ttl // 10, 300) or 1)
        self.key = cache_key(model, system_instruction, corpus_sha256)
        self.display_name = DISPLAY_PREFIX + self.key
        self.token_count: int | None = None
        self._name: str | None = None
        self._expires: datetime | None = None

    @property
    def current(self) -> str | None:
        return self._name

    def name(self) -> str:
        """A handle valid for at least the renewal margin from now."""
        if self._name is None:
            self._recall() or self._adopt() or self._create()
        elif self._expires is not None and self._expires - self._clock() < self._margin:
            self._extend() or self._create()
        assert self._name is not None
        return self._name

    def invalidate(self) -> None:
        """The provider said this handle is gone; forget it everywhere."""
        self._name = None
        self._expires = None
        self._registry.drop(self.key)

    def _remember(self, name: str, expires: datetime | None, tokens: int | None) -> None:
        self._name = name
        self._expires = expires or (self._clock() + timedelta(seconds=self._ttl))
        if tokens:
            self.token_count = tokens
        self._registry.put(self.key, name, self._expires, tokens=self.token_count)

    def _recall(self) -> bool:
        """The registry knows a handle a previous process made."""
        found = self._registry.get(self.key)
        if found is None:
            return False
        name, expires = found
        if expires - self._clock() < self._margin:
            return False
        self._name, self._expires = name, expires
        return True

    def _adopt(self) -> bool:
        """The provider still has one with our display name. Best effort."""
        try:
            for cache in self._client.caches.list():
                if cache.display_name != self.display_name or not cache.expire_time:
                    continue
                if cache.expire_time - self._clock() > self._margin:
                    usage = getattr(cache, "usage_metadata", None)
                    self._remember(cache.name, cache.expire_time,
                                   getattr(usage, "total_token_count", None))
                    log.info("adopted context cache %s (expires %s)",
                             cache.name, cache.expire_time.isoformat())
                    return True
        except Exception as exc:  # noqa: BLE001 - listing is a convenience
            log.info("could not list context caches (%s); creating one", exc)
        return False

    def _create(self) -> None:
        cache = self._client.caches.create(
            model=self._model,
            config=types.CreateCachedContentConfig(
                display_name=self.display_name,
                system_instruction=self._system_instruction,
                contents=corpus_turns(self._corpus_text),
                ttl=f"{self._ttl}s",
            ),
        )
        usage = getattr(cache, "usage_metadata", None)
        self._remember(cache.name, cache.expire_time, getattr(usage, "total_token_count", None))
        log.info("created context cache %s: %s tokens, expires %s",
                 cache.name, self.token_count or "?", self._expires.isoformat())

    def _extend(self) -> bool:
        """Push expiry out by another TTL. False means make a new one."""
        try:
            cache = self._client.caches.update(
                name=self._name,
                config=types.UpdateCachedContentConfig(ttl=f"{self._ttl}s"),
            )
        except Exception as exc:  # noqa: BLE001 - creation is the fallback
            log.info("could not extend context cache %s (%s); recreating", self._name, exc)
            self.invalidate()
            return False
        self._remember(cache.name, cache.expire_time, None)
        log.info("extended context cache %s to %s", cache.name, self._expires.isoformat())
        return True


# --- the adapter -----------------------------------------------------------

def _is_cache_gone(exc: BaseException) -> bool:
    if not isinstance(exc, genai_errors.ClientError):
        return False
    text = str(exc).lower()
    return exc.code == 404 or ("cachedcontent" in text and exc.code in (400, 403))


def _is_malformed(exc: BaseException) -> bool:
    """A request the provider will never accept as built. Sending the
    corpus inline might work; retrying as-is will not."""
    return isinstance(exc, genai_errors.ClientError) and exc.code not in (401, 403, 429)


class CachedContextAdapter:
    """The LLMPort over a context cache. Same signature as GeminiLLMAdapter."""

    def __init__(
        self,
        model: str,
        corpus_obj: corpus_module.Corpus,
        *,
        registry: Registry,
        ttl_seconds: int,
        client_factory: Callable[[], Any] | None = None,
        clock: Clock = _utcnow,
    ) -> None:
        self._model = model
        self._corpus = corpus_obj
        self._registry = registry
        self._ttl = ttl_seconds
        self._client_factory = client_factory
        self._clock = clock
        self._caches: dict[str, ContextCache] = {}
        _log_handler_once()

    def _client(self):
        if self._client_factory is not None:
            return self._client_factory()
        from rag import get_client

        return get_client()

    def _cache_for(self, system_instruction: str) -> ContextCache:
        key = cache_key(self._model, system_instruction, self._corpus.sha256)
        cache = self._caches.get(key)
        if cache is None:
            cache = self._caches[key] = ContextCache(
                self._client(), self._registry,
                model=self._model, system_instruction=system_instruction,
                corpus_text=self._corpus.text, corpus_sha256=self._corpus.sha256,
                ttl_seconds=self._ttl, clock=self._clock,
            )
        return cache

    def generate(self, *, system_instruction: str, contents: list[dict]) -> GenerateResult:
        inline_until = self._registry.inline_until()
        if inline_until is not None and inline_until > self._clock():
            return self._inline(system_instruction, contents, reason="stepped down")

        cache = self._cache_for(system_instruction)
        started = time.monotonic()
        try:
            try:
                resp = self._cached_call(cache, contents)
            except genai_errors.ClientError as exc:
                if not _is_cache_gone(exc):
                    raise
                log.warning("context cache %s gone (%s); rebuilding once", cache.current, exc)
                cache.invalidate()
                resp = self._cached_call(cache, contents)
        except genai_errors.ClientError as exc:
            if not _is_malformed(exc):
                raise
            until = self._clock() + timedelta(seconds=REPROBE_SECONDS)
            self._registry.set_inline_until(until)
            log.warning("provider rejected the cached request (%s); sending the corpus "
                        "inline until %s", exc, until.isoformat())
            return self._inline(system_instruction, contents, reason=str(exc)[:120])
        return self._result(resp, contents, mode="cache", cache=cache.current,
                            elapsed=time.monotonic() - started)

    def _cached_call(self, cache: ContextCache, contents: list[dict]):
        name = cache.name()
        return self._client().models.generate_content(
            model=self._model,
            contents=contents,
            config={"cached_content": name, "temperature": TEMPERATURE},
        )

    def _inline(self, system_instruction: str, contents: list[dict], *, reason: str) -> GenerateResult:
        """The same layout with no cache: corpus first, so the request prefix
        is still identical turn to turn and implicit caching can help."""
        started = time.monotonic()
        resp = self._client().models.generate_content(
            model=self._model,
            contents=corpus_turns(self._corpus.text) + contents,
            config={"system_instruction": system_instruction, "temperature": TEMPERATURE},
        )
        return self._result(resp, contents, mode="inline", cache=reason,
                            elapsed=time.monotonic() - started)

    def _result(self, resp, contents: list[dict], *, mode: str, cache: str | None,
                elapsed: float) -> GenerateResult:
        prompt_tokens, completion_tokens = _extract_usage(resp)
        usage = getattr(resp, "usage_metadata", None)
        cache_read = getattr(usage, "cached_content_token_count", None) or 0
        log.info(
            "cached-context answer: mode=%s total=%dms prompt=%s cache_read=%s output=%s "
            "history=%d cache=%s",
            mode, int(elapsed * 1000), prompt_tokens, cache_read, completion_tokens,
            max(0, len(contents) - 1), cache,
        )
        return GenerateResult(
            text=resp.text or "",
            citations=[],   # no retrieval, so nothing to cite; the documents are all in view
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )


class FallbackLLM:
    """Try the cached-context path; serve the turn from the old path if it raises."""

    def __init__(self, primary, fallback) -> None:
        self.primary = primary
        self.fallback = fallback

    def generate(self, *, system_instruction: str, contents: list[dict]) -> GenerateResult:
        try:
            return self.primary.generate(system_instruction=system_instruction, contents=contents)
        except Exception:  # noqa: BLE001 - whatever it was, the old path answers
            log.warning("cached-context path failed; answering from the File Search path",
                        exc_info=True)
            return self.fallback.generate(system_instruction=system_instruction, contents=contents)


def build_smart_llm(model: str, file_search_store: str):
    """The smart-tier adapter the flag asks for.

    Flag off: the very GeminiLLMAdapter the app always made. Flag on: the
    cached-context adapter with that adapter as its fallback — or, when the
    knowledge base cannot be bundled, the plain adapter again with a warning
    saying why, so a bad document degrades service rather than ending it.
    """
    retrieval = GeminiLLMAdapter(model, file_search_store)
    if not config.CACHED_CONTEXT:
        return retrieval
    try:
        corpus_obj = corpus_module.build(config.KNOWLEDGE_BASE_DIR)
        if corpus_obj.estimated_tokens > config.CACHED_CONTEXT_MAX_TOKENS:
            raise corpus_module.CorpusError(
                f"corpus is ~{corpus_obj.estimated_tokens:,} tokens, over "
                f"CACHED_CONTEXT_MAX_TOKENS={config.CACHED_CONTEXT_MAX_TOKENS:,}"
            )
    except corpus_module.CorpusError as exc:
        log.warning("cached context unavailable; serving the File Search path\n  %s", exc)
        return retrieval
    log.info("cached context: %d documents, ~%s tokens, model %s, ttl %ds",
             len(corpus_obj.documents), f"{corpus_obj.estimated_tokens:,}", model,
             config.CACHED_CONTEXT_TTL_SECONDS)
    primary = CachedContextAdapter(
        model, corpus_obj,
        registry=Registry(config.CACHED_CONTEXT_REGISTRY_PATH),
        ttl_seconds=config.CACHED_CONTEXT_TTL_SECONDS,
    )
    return FallbackLLM(primary, retrieval)

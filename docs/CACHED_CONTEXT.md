# The cached-context path — `CACHED_CONTEXT=true`

The second way the bot grounds its answers. Instead of Gemini File Search
retrieving passages from `FILE_SEARCH_STORE` on every turn, the whole
knowledge base sits in a Gemini context cache together with the system
instruction, and the model answers in one call with no retrieval step:

```
[ system instruction ][ knowledge base (~10k tokens) ] [ history ][ known state + question ]
└──────────── provider-side cache, never changes ────┘ └────────── sent each turn ──────────┘
```

Off by default. With the flag off `cached_context.py` never runs and the
bot behaves exactly as before.

## What the model reads

`knowledge_base/*.md` — the source of truth for this path. Today:

| File | Was |
|---|---|
| `tvs_three_wheelers.md` | `tvs_three_wheelers_kb.pdf` (`build_tvs_3w_kb.py`) |
| `tvs_king_ev_max.md` | `tvs_king_ev_max_kb.pdf` (`build_kb_pdf.py`) |
| `tvs_3w_loan_documents.md` | `tvs_3w_loan_documents_kb.pdf` (`build_loan_docs_kb.py`) |

Same content as the three documents in the production File Search store,
as Markdown. `corpus.py` renders them into one deterministic bundle, each
file wrapped as `<document index="n" source="file.md">…</document>`, sorted
by path, whitespace normalised — byte-identical for identical input,
because a bundle that differs by one byte is a new cache.

```bash
python corpus.py            # what would be cached: files, sizes, sha
python corpus.py --write    # also build/corpus/corpus.txt, to read it
```

**To change what the bot knows on this path:** edit or add a `.md` file
under `knowledge_base/`, run `python corpus.py` to see it bundle, deploy.
The next turn creates a new cache (the corpus sha is in the key); the old
one expires on its own. Only `.md`/`.txt` are accepted; a file that is not
UTF-8 or normalises to nothing fails the bundle by name — and a failed
bundle means the bot **serves the File Search path with a warning**, not
a partial corpus.

The admin page's knowledge-base upload still feeds the File Search store.
With the flag on that store is the fallback only; what customers hear
comes from `knowledge_base/`.

## Turning it on

Server `.env`:

```bash
CACHED_CONTEXT=true
GEMINI_MODEL=gemini-3.5-flash-lite      # or whichever; the cache is per model
# optional: CACHED_CONTEXT_TTL_SECONDS=3600  CACHED_CONTEXT_MAX_TOKENS=200000
```

then `docker compose --profile client up -d client-worker`. The flag is
read at process start; the worker forks a fresh process per job, so every
job after the restart sees it.

Then prove it. `data/cached_context.log` (host: `~/tvsm_rag_bot/data/`)
gets one line per turn:

```
… INFO cached context: 3 documents, ~10,197 tokens, model gemini-3.5-flash-lite, ttl 3600s
… INFO created context cache cachedContents/abc…: 11,9xx tokens, expires 2026-09-19T…
… INFO cached-context answer: mode=cache total=1843ms prompt=12105 cache_read=11968 output=61 history=0 cache=cachedContents/abc…
```

`cache_read` is the provider's own `cached_content_token_count`. A number
near the corpus size means the cache is live; **a number near zero means
you are paying full price with no error** — that is the failure mode of
prompt caching and the reason this line exists.

The admin status (`/admin/api/status`) reports `"cached_context": true`.

## Revert

Two levels. Either one is complete on its own.

**1. Flag off (seconds, no rebuild).** On the server:

```bash
cd ~/tvsm_rag_bot
cp .env .env.bak-$(date +%Y%m%d-%H%M%S)
sed -i 's/^CACHED_CONTEXT=.*/CACHED_CONTEXT=false/' .env
docker compose --profile client up -d client-worker
```

The smart tier is `GeminiLLMAdapter` over `FILE_SEARCH_STORE` again — the
same object, same request shape, same store as before this change. The
File Search store was never touched, so nothing has to be re-indexed. Set
`GEMINI_MODEL` back at the same time if the model was changed with it.

**2. Code revert.** `git revert <the cached-context commit>` on the
branch, push, `bash ./update.sh` on the server. Deletes the path entirely;
the flag becomes a no-op.

Caches the provider still holds expire on their own TTL (default one
hour) and cost nothing after that; nothing needs deleting.

## Measured (2026-09-19, prod container, gemini-3.5-flash-lite)

Three turns through the adapter with a 300 s TTL:

| turn | mode | total | prompt | cache read | output |
|---|---|---|---|---|---|
| spec question (cold, creates cache) | cache | 4946 ms | 9,652 | 9,627 | 119 |
| follow-up with history | cache | 2013 ms | 9,787 | 9,627 | 120 |
| Hindi question (new instruction → new cache) | cache | 4686 ms | 9,642 | 9,627 | 101 |

Gemini counted the corpus plus instruction at 9,627 tokens (the estimate
said ~10,200). Every turn read the whole cache and paid uncached for only
the history and question. Cache creation costs ~3 s on the turn that needs
it; a warm turn is ~2 s end to end. Turned on in production the same day,
with `GEMINI_MODEL=gemini-3.5-flash-lite`.

## What holds

**Flag off is the old path, untouched.** `build_smart_llm()` returns the
`GeminiLLMAdapter` the app always made — the same class, not a wrapper.

**Any failure falls back.** With the flag on, the smart tier is a
`FallbackLLM`: the cached-context adapter first, the File Search adapter
if it raises. The customer sees an answer either way; the log sees a
warning with the traceback.

**Nothing about the provider API is assumed.** If the provider rejects
the cached request as malformed (a 4xx that is not 401/403/429 — a model
that does not support caching, a corpus under the cache minimum), the
adapter sends the corpus inline instead — same layout, no cache, system
instruction on the request — and remembers that for 15 minutes before
trying the cache again. Auth, quota, 5xx and network errors are not
shape problems: they propagate and the fallback serves the turn.

**One cache per system instruction.** An explicit cache cannot take a
per-request system instruction, and this bot's instruction varies per
language, product hint and admin config. So the key is
sha256(model, instruction, corpus): three languages times a few product
hints — a handful of caches, each ~10k tokens, each alive
`CACHED_CONTEXT_TTL_SECONDS` after its last extension. The known-state
snapshot already rides on the user turn (`build_contents`), so within a
conversation the prefix is stable. Changing the admin config or the
corpus changes the key; old caches simply expire.

**Handles outlive the process.** `data/context_caches.json` remembers
each cache's name and expiry, because the RQ worker forks a fresh process
per job; without it every turn would list the provider's caches before
answering. A stale or missing entry costs one listing or one creation,
never a wrong answer. A cache the provider reports gone (404) is rebuilt
once, in the same turn. A cache within a tenth of its TTL of expiring is
extended rather than recreated.

**Citations are empty on this path.** There is no retrieval metadata to
read; the documents are all in view. `TurnOutput.citations` is `[]`.

## Cost shape

Per turn, uncached tokens are the history plus the question (~100–600);
the ~10k-token corpus is billed at the cached rate. Cache storage is
billed per token-hour while a cache lives; with one-hour TTLs and lazy
creation, an idle hour costs nothing. Creating a cache is one full-price
read of the corpus (~10k tokens).

## Config

| Variable | Default | |
|---|---|---|
| `CACHED_CONTEXT` | off | the switch |
| `KNOWLEDGE_BASE_DIR` | `knowledge_base` | the `.md` files |
| `CACHED_CONTEXT_TTL_SECONDS` | `3600` | cache lifetime; extended when used near expiry |
| `CACHED_CONTEXT_MAX_TOKENS` | `200000` | refuse a corpus over this (estimated) size |
| `CACHED_CONTEXT_REGISTRY_PATH` | `data/context_caches.json` | handles shared between worker processes |
| `CACHED_CONTEXT_LOG_PATH` | `data/cached_context.log` | per-turn metrics; empty disables the file |

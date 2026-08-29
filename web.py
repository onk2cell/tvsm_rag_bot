"""Admin panel: a small FastAPI app to edit the bot's runtime configuration.

The conversation engine and CSV writer read from the AdminConfigStore on every
turn (reload-on-read), so edits saved here reach the separate worker process on
its next message — no restart, no redeploy. The Gemini API key set here is
persisted and picked up the same way (see rag.persist_api_key).

It also reports operational status (``/admin/api/status``) and can reset one
stuck customer's WhatsApp session (``/admin/api/session/reset``). Both read
through Redis, because this process runs in its own container and cannot see
the worker directly.

Auth is a single bearer token: config.ADMIN_TOKEN. An empty token disables every
admin endpoint (503), matching the "empty = admin endpoints disabled" contract
in config.py. The HTML shell itself carries no secrets and is served unauthed;
the browser prompts for the token and sends it as ``Authorization: Bearer``.
"""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any, Callable

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import client_static_messages
import config
import dispose
import rag
from admin_config import (
    VOICE_POLICIES,
    AdminConfigStore,
    default_config,
    derive_aliases,
    get_store,
    validate_config,
)
from admin_status import StatusReporter
from knowledge_base import KnowledgeBase, KnowledgeBaseError
from leads import read_leads, read_leads_csv
from media_library import MEDIA_KINDS, MediaError, MediaLibrary
from session_keys import client_session_key

_PAGE_PATH = Path(__file__).with_name("assets") / "admin.html"

_DOCS_DIR = Path(__file__).with_name("docs")

# Slug -> filename. A fixed map rather than a path parameter, so nothing a
# caller sends ever reaches the filesystem. Only .html is shipped in the image
# (see .dockerignore); the markdown and PDFs in docs/ stay out of the build.
DOC_PAGES: dict[str, tuple[str, str]] = {
    "api": ("admin_api_docs.html", "Admin API reference"),
    "status": ("status_report.html", "Control panel status"),
}

API_VERSION = "1.0.0"

API_DESCRIPTION = """\
Every endpoint except the health probe and the panel HTML requires
`Authorization: Bearer <ADMIN_TOKEN>`. One shared token, no roles.

If `ADMIN_TOKEN` is unset on the server every admin endpoint returns **503** —
the panel is disabled, not open.

Two things to know before building a client:

* **Conversations group by `mobile`, not `session`.** A returning customer gets
  a fresh `session` id whenever their hour-long window lapses. Turns recorded
  before the `mobile` column shipped have `mobile: ""` and cannot be found by
  number; there is no backfill.
* **`PUT /admin/api/config` replaces the whole document.** There is no partial
  update and no version history, so read, edit, then write back.
"""

API_TAGS = [
    {"name": "operations", "description": "Is the bot working, and unstick customers."},
    {"name": "conversations", "description": "What the bot and customers said."},
    {"name": "leads", "description": "Qualified leads captured for the dealership."},
    {"name": "configuration", "description": "What the bot says and asks."},
    {"name": "credentials", "description": "The Gemini API key backing the bot."},
    {"name": "media", "description": "Brochures and images served by the media host."},
    {"name": "knowledge base", "description": "Documents the bot grounds its answers on."},
]

_UNAUTHORIZED = {
    401: {"description": "Missing or invalid admin token."},
    503: {"description": "Admin panel disabled (ADMIN_TOKEN unset)."},
}

# auto_error=False so a missing header reaches require_admin, which returns the
# same 401 body as a wrong one — and 503 when the panel is switched off.
_bearer_scheme = HTTPBearer(auto_error=False, description="ADMIN_TOKEN")


def _default_redis_factory() -> Any:
    from redis import Redis

    return Redis.from_url(config.REDIS_URL, decode_responses=True)


def create_admin_app(
    *,
    admin_token: str,
    config_store: AdminConfigStore,
    key_manager: Any = rag,
    redis_factory: Callable[[], Any] = _default_redis_factory,
    status_reporter: StatusReporter | None = None,
    interaction_store: Any = None,
    leads_path: Path | None = None,
    media_library: MediaLibrary | None = None,
    knowledge_base: KnowledgeBase | None = None,
) -> FastAPI:
    app = FastAPI(
        title="TVS Bot Admin",
        version=API_VERSION,
        summary="Configure the TVS WhatsApp bot and inspect what it is doing.",
        description=API_DESCRIPTION,
        openapi_tags=API_TAGS,
    )

    def interactions() -> Any:
        """Resolved lazily: opening the DB at import time would create the
        file in whatever directory the process happened to start in."""
        if interaction_store is not None:
            return interaction_store
        import interactions as interactions_module

        return interactions_module.get_store()

    def leads_file() -> Path:
        return leads_path or Path(config.LEADS_CSV_PATH)

    media = media_library or MediaLibrary(Path(config.MEDIA_ROOT))
    kb = knowledge_base or KnowledgeBase()

    reporter = status_reporter or StatusReporter(
        redis_factory=redis_factory,
        key_manager=key_manager,
        queue_name=config.CLIENT_QUEUE_NAME,
        warn_depth=config.ADMIN_QUEUE_WARN_DEPTH,
        crm_url=config.CLIENT_CRM_CUSTOMER_URL,
        dispose_url=config.CLIENT_DISPOSE_URL,
        cache_seconds=config.ADMIN_PROBE_CACHE_SEC,
    )

    def require_admin(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    ) -> None:
        if not admin_token:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Admin panel is disabled (ADMIN_TOKEN is not set).",
            )
        # compare_digest so a wrong token cannot be narrowed down by timing.
        if credentials is None or not secrets.compare_digest(
            credentials.credentials, admin_token
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing admin token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def _gemini_status() -> dict[str, Any]:
        if key_manager.runtime_key_active():
            source: str | None = "runtime"
        elif config.GEMINI_API_KEY:
            source = "env"
        else:
            source = None
        return {
            "configured": key_manager.has_client(),
            "source": source,
            "model": config.MODEL,
            "file_search_store": config.FILE_SEARCH_STORE,
        }

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/admin")

    @app.get("/admin/health", tags=["operations"], summary="Liveness probe")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
    def admin_page() -> HTMLResponse:
        return HTMLResponse(_PAGE_PATH.read_text(encoding="utf-8"))

    @app.get("/admin/docs", response_class=HTMLResponse, include_in_schema=False)
    def docs_index() -> HTMLResponse:
        # The slugs are not guessable, so an index is the only way in.
        links = "\n".join(
            f'<li><a href="/admin/docs/{slug}">{title}</a></li>'
            for slug, (_, title) in DOC_PAGES.items()
        )
        return HTMLResponse(
            "<title>Documentation</title>"
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<body style="font:16px/1.6 system-ui;max-width:36rem;margin:3rem auto;padding:0 1rem">'
            f"<h1>Documentation</h1><ul>{links}</ul></body>"
        )

    @app.get("/admin/docs/{page}", response_class=HTMLResponse, include_in_schema=False)
    def docs_page(page: str) -> HTMLResponse:
        entry = DOC_PAGES.get(page)
        if entry is None:
            raise HTTPException(status_code=404, detail="No such document.")
        path = _DOCS_DIR / entry[0]
        if not path.is_file():
            # The file is committed but was excluded from this image.
            raise HTTPException(status_code=404, detail="Document not in this build.")
        return HTMLResponse(path.read_text(encoding="utf-8"))

    @app.get("/admin/api/meta", tags=["configuration"], summary="Allowed values and factory defaults", responses=_UNAUTHORIZED)
    def meta(_: None = Depends(require_admin)) -> dict[str, Any]:
        return {
            "voice_policies": sorted(VOICE_POLICIES),
            "default_config": default_config(),
            "gemini": _gemini_status(),
        }

    @app.get("/admin/api/config", tags=["configuration"], summary="Read the live bot configuration", responses=_UNAUTHORIZED)
    def read_config(_: None = Depends(require_admin)) -> dict[str, Any]:
        return config_store.get()

    @app.put("/admin/api/config", tags=["configuration"], summary="Replace the bot configuration", responses={**_UNAUTHORIZED, 400: {"description": "Validation failed; detail names the field."}})
    def write_config(
        payload: dict[str, Any],
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        try:
            return config_store.update(payload)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

    # --- vehicles ----------------------------------------------------------
    #
    # A view over config["documents"], never a second store. The bot reads
    # documents to decide what it offers, recognises and sends, so a separate
    # vehicle table would be a copy that silently drifts from what runs. These
    # endpoints exist so a UI can edit one vehicle without PUTting whole config.

    def _documents() -> tuple[dict[str, Any], dict[str, Any]]:
        cfg = config_store.get()
        docs = cfg.get("documents")
        return cfg, (dict(docs) if isinstance(docs, dict) else {})

    def _save_documents(cfg: dict[str, Any], docs: dict[str, Any]) -> None:
        cfg["documents"] = docs
        try:
            config_store.update(cfg)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

    def _vehicle_view(name: str, entry: dict[str, Any]) -> dict[str, Any]:
        """One vehicle, showing the aliases actually in force.

        A vehicle with no "aliases" key has never been edited here, so it still
        matches on this build's built-in spellings. Showing those is what lets
        an operator edit or drop them rather than guess at what already matches.
        """
        aliases = entry.get("aliases")
        seeded = aliases is None
        if seeded:
            aliases = list(dispose.builtin_aliases_for(name))
        return {
            "name": name,
            "brochure": entry.get("brochure", ""),
            "fuel": entry.get("fuel") or {},
            "support": entry.get("support") or [],
            "aliases": list(aliases),
            "aliases_seeded_from_builtins": seeded,
        }

    def _claimed_spellings(docs: dict[str, Any], exclude: str) -> set[str]:
        """Every spelling the other vehicles already answer to."""
        claimed: set[str] = set()
        for other, entry in docs.items():
            if other == exclude:
                continue
            claimed.add(" ".join(other.lower().split()))
            for alias in _vehicle_view(other, entry or {})["aliases"]:
                claimed.add(" ".join(alias.lower().split()))
        return claimed

    def _resolve_aliases(
        payload: dict[str, Any], name: str, docs: dict[str, Any]
    ) -> list[str]:
        """Aliases the operator typed, or ones derived from the name.

        Derived spellings are dropped on collision -- they were a convenience
        the operator never asked for. A typed spelling that collides is a 400:
        they meant it, so silently discarding it would be a lie.
        """
        claimed = _claimed_spellings(docs, name)
        typed = payload.get("aliases")
        if typed is not None:
            if not isinstance(typed, list):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="aliases must be a list of strings",
                )
            for alias in typed:
                if " ".join(str(alias).lower().split()) in claimed:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"alias {alias!r} already belongs to another "
                            "vehicle; a spelling can only mean one product"
                        ),
                    )
            return [str(a) for a in typed]
        derived = derive_aliases(name, [n for n in docs if n != name])
        return [a for a in derived if a not in claimed]

    def _kb_warning(name: str) -> str | None:
        """Flag a vehicle nothing in the knowledge base describes.

        Retrieval still answers specification questions -- from other vehicles'
        documents -- so the failure is a confident wrong answer, not a blank.
        Never blocks: a brochure-only vehicle is a legitimate thing to add.
        """
        try:
            documents = (kb.summary() or {}).get("documents") or []
        except Exception:
            return None
        needle = name.lower()
        for doc in documents:
            if needle in str((doc or {}).get("name", "")).lower():
                return None
        return (
            f"No knowledge-base document mentions {name!r}. The bot will still "
            "answer specification questions about it, using other vehicles' "
            "documents. Index one with POST /admin/api/kb."
        )

    @app.get("/admin/api/vehicles", tags=["vehicles"], summary="List configured vehicles", responses=_UNAUTHORIZED)
    def list_vehicles(_: None = Depends(require_admin)) -> dict[str, Any]:
        """Every vehicle the bot offers, with the aliases it matches on."""
        _, docs = _documents()
        return {
            "vehicles": [_vehicle_view(n, e or {}) for n, e in docs.items()]
        }

    @app.get("/admin/api/vehicles/{name}", tags=["vehicles"], summary="Read one vehicle", responses={**_UNAUTHORIZED, 404: {"description": "No such vehicle."}})
    def read_vehicle(name: str, _: None = Depends(require_admin)) -> dict[str, Any]:
        _, docs = _documents()
        if name not in docs:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No vehicle named {name!r}.",
            )
        return _vehicle_view(name, docs[name] or {})

    @app.post("/admin/api/vehicles", tags=["vehicles"], summary="Add a vehicle", status_code=status.HTTP_201_CREATED, responses={**_UNAUTHORIZED, 400: {"description": "Invalid payload; detail names the field."}, 409: {"description": "A vehicle with that name already exists."}})
    def create_vehicle(
        payload: dict[str, Any],
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        """Add a vehicle. Aliases are derived from the name unless supplied."""
        cfg, docs = _documents()
        name = str((payload or {}).get("name") or "").strip()
        if not name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="name is required.",
            )
        if name in docs:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A vehicle named {name!r} already exists.",
            )
        entry = {
            "brochure": payload.get("brochure", ""),
            "fuel": payload.get("fuel") or {},
            "support": payload.get("support") or [],
            "aliases": _resolve_aliases(payload, name, docs),
        }
        docs[name] = entry
        _save_documents(cfg, docs)
        view = _vehicle_view(name, entry)
        warning = _kb_warning(name)
        if warning:
            view["warning"] = warning
        return view

    @app.put("/admin/api/vehicles/{name}", tags=["vehicles"], summary="Update a vehicle", responses={**_UNAUTHORIZED, 400: {"description": "Invalid payload; detail names the field."}, 404: {"description": "No such vehicle."}})
    def update_vehicle(
        name: str,
        payload: dict[str, Any],
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        """Replace a vehicle's documents and aliases. Use rename to change name."""
        cfg, docs = _documents()
        if name not in docs:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No vehicle named {name!r}.",
            )
        current = dict(docs[name] or {})
        payload = payload or {}
        entry = {
            "brochure": payload.get("brochure", current.get("brochure", "")),
            "fuel": payload.get("fuel", current.get("fuel") or {}),
            "support": payload.get("support", current.get("support") or []),
            "aliases": (
                _resolve_aliases(payload, name, docs)
                if "aliases" in payload
                else _vehicle_view(name, current)["aliases"]
            ),
        }
        docs[name] = entry
        _save_documents(cfg, docs)
        return _vehicle_view(name, entry)

    @app.post("/admin/api/vehicles/{name}/rename", tags=["vehicles"], summary="Rename a vehicle", responses={**_UNAUTHORIZED, 400: {"description": "new_name missing or blank."}, 404: {"description": "No such vehicle."}, 409: {"description": "The new name is already taken."}})
    def rename_vehicle(
        name: str,
        payload: dict[str, Any],
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        """Rename in place, keeping documents, aliases and configured order.

        Built-in spellings are keyed by the old name, so they are written into
        the entry first: without that, renaming would silently cost the vehicle
        every alias it had and customers would stop being understood.
        """
        cfg, docs = _documents()
        if name not in docs:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No vehicle named {name!r}.",
            )
        new_name = str((payload or {}).get("new_name") or "").strip()
        if not new_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="new_name is required.",
            )
        if new_name != name and new_name in docs:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A vehicle named {new_name!r} already exists.",
            )
        entry = dict(docs[name] or {})
        entry["aliases"] = _vehicle_view(name, entry)["aliases"]
        renamed = {
            (new_name if key == name else key): (
                entry if key == name else value
            )
            for key, value in docs.items()
        }
        _save_documents(cfg, renamed)
        return _vehicle_view(new_name, entry)

    @app.delete("/admin/api/vehicles/{name}", tags=["vehicles"], summary="Remove a vehicle", responses={**_UNAUTHORIZED, 404: {"description": "No such vehicle."}})
    def delete_vehicle(name: str, _: None = Depends(require_admin)) -> dict[str, Any]:
        """Remove a vehicle. Config is re-read per turn, so this is immediate.

        A customer mid-conversation about this vehicle stops matching it: their
        brochure request will find no product and send nothing.
        """
        cfg, docs = _documents()
        if name not in docs:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No vehicle named {name!r}.",
            )
        docs.pop(name)
        _save_documents(cfg, docs)
        return {
            "name": name,
            "deleted": True,
            "warning": (
                "Customers already talking about this vehicle will stop "
                "receiving its brochure from their next message onward."
            ),
        }

    # --- messages ----------------------------------------------------------
    #
    # Overrides are sparse: config carries only what an operator reworded, and
    # everything else falls through to client_static_messages. That is what
    # lets a message added in a later build appear without migrating configs,
    # and lets DELETE mean "give me the built-in wording back".

    def _message_view(key: str, overrides: dict[str, Any], languages: list[str]) -> dict[str, Any]:
        override = overrides.get(key) or {}
        defaults = client_static_messages.MESSAGE_DEFAULTS.get(key, {})
        return {
            "key": key,
            "placeholders": sorted(client_static_messages.placeholders_for(key)),
            "defaults": dict(defaults),
            "overrides": dict(override),
            # Which configured languages this message has no text for and so
            # will answer in English. This is how the Telugu/Tamil/Kannada/
            # Malayalam gap becomes visible instead of silently falling back.
            "falls_back_to_english": [
                lang
                for lang in languages
                if lang != "English"
                and not str(override.get(lang, "")).strip()
                and not str(defaults.get(lang, "")).strip()
            ],
        }

    def _messages_state() -> tuple[dict[str, Any], dict[str, Any], list[str]]:
        cfg = config_store.get()
        raw = cfg.get("messages")
        overrides = dict(raw) if isinstance(raw, dict) else {}
        languages = [
            str(lang.get("code", ""))
            for lang in (cfg.get("languages") or [])
            if isinstance(lang, dict) and str(lang.get("code", "")).strip()
        ]
        return cfg, overrides, languages

    def _save_messages(cfg: dict[str, Any], overrides: dict[str, Any]) -> None:
        cfg["messages"] = overrides
        try:
            config_store.update(cfg)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

    @app.get("/admin/api/messages", tags=["messages"], summary="Every editable bot message", responses=_UNAUTHORIZED)
    def list_messages(_: None = Depends(require_admin)) -> dict[str, Any]:
        """Built-in wording, any overrides, and which languages fall back."""
        _, overrides, languages = _messages_state()
        return {
            "languages": languages,
            "messages": [
                _message_view(key, overrides, languages)
                for key in client_static_messages.message_keys()
            ],
        }

    @app.get("/admin/api/messages/{key}", tags=["messages"], summary="Read one message", responses={**_UNAUTHORIZED, 404: {"description": "No such message."}})
    def read_message(key: str, _: None = Depends(require_admin)) -> dict[str, Any]:
        _, overrides, languages = _messages_state()
        if key not in client_static_messages.MESSAGE_DEFAULTS:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No message named {key!r}.",
            )
        return _message_view(key, overrides, languages)

    @app.put("/admin/api/messages/{key}", tags=["messages"], summary="Reword a message", responses={**_UNAUTHORIZED, 400: {"description": "Bad placeholder or empty text; detail names the language."}, 404: {"description": "No such message."}})
    def write_message(
        key: str,
        payload: dict[str, Any],
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        """Set this message's text per language. Omitted languages are unchanged.

        A language whose text is blank has its override removed rather than
        stored empty, so clearing a box restores the built-in wording instead
        of leaving the bot with nothing to say.
        """
        cfg, overrides, languages = _messages_state()
        if key not in client_static_messages.MESSAGE_DEFAULTS:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No message named {key!r}.",
            )
        incoming = (payload or {}).get("text", payload) or {}
        if not isinstance(incoming, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="text must be an object keyed by language",
            )
        current = dict(overrides.get(key) or {})
        for language, text in incoming.items():
            if isinstance(text, str) and text.strip():
                current[str(language)] = text
            else:
                current.pop(str(language), None)
        if current:
            overrides[key] = current
        else:
            overrides.pop(key, None)
        _save_messages(cfg, overrides)
        _, saved, languages = _messages_state()
        return _message_view(key, saved, languages)

    @app.delete("/admin/api/messages/{key}", tags=["messages"], summary="Restore a message's built-in wording", responses={**_UNAUTHORIZED, 404: {"description": "No such message."}})
    def clear_message(key: str, _: None = Depends(require_admin)) -> dict[str, Any]:
        """Drop every override for this message. The built-in wording returns."""
        cfg, overrides, languages = _messages_state()
        if key not in client_static_messages.MESSAGE_DEFAULTS:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No message named {key!r}.",
            )
        overrides.pop(key, None)
        _save_messages(cfg, overrides)
        _, saved, languages = _messages_state()
        return _message_view(key, saved, languages)

    @app.get("/admin/api/status", tags=["operations"], summary="Is the bot working?", responses=_UNAUTHORIZED)
    def operational_status(_: None = Depends(require_admin)) -> dict[str, Any]:
        """Is the bot working? One verdict plus the six checks behind it."""
        return reporter.snapshot()

    @app.post("/admin/api/session/reset", tags=["operations"], summary="Hard-reset one customer's session", responses={**_UNAUTHORIZED, 400: {"description": "mobile missing or blank."}, 503: {"description": "Redis unavailable."}})
    def reset_session(
        payload: dict[str, Any],
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        """Hard-reset one customer: their next message starts from scratch.

        Deduplication keys are deliberately untouched — they are keyed per
        message, not per customer, and any new inbound message carries a
        fresh id.
        """
        mobile = (payload or {}).get("mobile", "")
        if not isinstance(mobile, str) or not mobile.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="mobile is required.",
            )
        mobile = mobile.strip()
        try:
            removed = redis_factory().delete(client_session_key(mobile))
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Redis unavailable: {exc}",
            ) from exc
        return {"mobile": mobile, "cleared": bool(removed)}

    # --- conversations -----------------------------------------------------

    @app.get("/admin/api/interactions", tags=["conversations"], summary="Search conversation turns", responses=_UNAUTHORIZED)
    def list_interactions(
        mobile: str | None = None,
        session: str | None = None,
        channel: str | None = None,
        language: str | None = None,
        interaction_status: str | None = Query(default=None, alias="status"),
        needs_review: bool | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        """Search conversation turns. `mobile` is the support entry point."""
        return interactions().list_interactions(
            mobile=mobile,
            session=session,
            channel=channel,
            language=language,
            status=interaction_status,
            needs_review=needs_review,
            search=search,
            limit=limit,
            offset=offset,
        )

    @app.get("/admin/api/interactions/export.csv", tags=["conversations"], summary="Download conversations as CSV", response_class=PlainTextResponse, responses=_UNAUTHORIZED)
    def export_interactions(
        mobile: str | None = None,
        session: str | None = None,
        channel: str | None = None,
        language: str | None = None,
        interaction_status: str | None = Query(default=None, alias="status"),
        needs_review: bool | None = None,
        search: str | None = None,
        _: None = Depends(require_admin),
    ) -> PlainTextResponse:
        body = interactions().export_csv(
            mobile=mobile,
            session=session,
            channel=channel,
            language=language,
            status=interaction_status,
            needs_review=needs_review,
            search=search,
        )
        return PlainTextResponse(
            body,
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="interactions.csv"'
            },
        )

    @app.get("/admin/api/interactions/{session_id}", tags=["conversations"], summary="Read one full transcript", responses={**_UNAUTHORIZED, 404: {"description": "No turns for that session."}})
    def read_conversation(
        session_id: str,
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        """Whole transcript for one conversation, oldest turn first."""
        result = interactions().list_interactions(session=session_id, limit=500)
        if not result["items"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No conversation found for session {session_id}.",
            )
        return {"session": session_id, **result}

    @app.post("/admin/api/interactions/{interaction_id}/review", tags=["conversations"], summary="Mark a flagged turn reviewed", responses={**_UNAUTHORIZED, 404: {"description": "Not awaiting review — already handled, or never flagged."}})
    def review_interaction(
        interaction_id: int,
        payload: dict[str, Any] | None = None,
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        note = ((payload or {}).get("note") or "").strip()
        if not interactions().mark_reviewed(interaction_id, note=note):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Interaction {interaction_id} is not awaiting review "
                    "(already reviewed, or never flagged)."
                ),
            )
        return {"id": interaction_id, "reviewed": True, "note": note}

    # --- leads -------------------------------------------------------------

    @app.get("/admin/api/leads", tags=["leads"], summary="List captured leads, newest first", responses=_UNAUTHORIZED)
    def list_leads(
        search: str = "",
        limit: int = 100,
        offset: int = 0,
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        """Captured leads, newest first. `search` matches any column."""
        return read_leads(
            leads_file(),
            config_store,
            search=search,
            limit=limit,
            offset=offset,
        )

    @app.get("/admin/api/leads/export.csv", tags=["leads"], summary="Download all leads as CSV", response_class=PlainTextResponse, responses=_UNAUTHORIZED)
    def export_leads(_: None = Depends(require_admin)) -> PlainTextResponse:
        return PlainTextResponse(
            read_leads_csv(leads_file()),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="leads.csv"'},
        )

    # --- media -------------------------------------------------------------

    def library_for(kind_name: str) -> MediaLibrary:
        kind = MEDIA_KINDS.get(kind_name)
        if kind is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Unknown media kind {kind_name!r}. "
                    f"Expected one of: {', '.join(sorted(MEDIA_KINDS))}."
                ),
            )
        return media.for_kind(kind)

    @app.get("/admin/api/media/{kind}", tags=["media"], summary="List uploaded media", responses={**_UNAUTHORIZED, 404: {"description": "Unknown media kind."}})
    def list_media(kind: str, _: None = Depends(require_admin)) -> dict[str, Any]:
        library = library_for(kind)
        return {
            "kind": kind,
            "base_url": library.url_for("").rstrip("/"),
            "max_upload_bytes": library.kind.max_bytes,
            "allowed_suffixes": sorted(library.kind.suffixes),
            "items": [item.as_dict() for item in library.list()],
        }

    @app.post("/admin/api/media/{kind}", tags=["media"], summary="Upload a brochure or image", responses={**_UNAUTHORIZED, 400: {"description": "Wrong type, too large, empty, or the name already exists."}, 404: {"description": "Unknown media kind."}})
    async def upload_media(
        kind: str,
        file: UploadFile = File(..., description="The file to publish."),
        overwrite: bool = Form(False, description="Replace a file of the same name."),
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        """Publish a file on the media host and return its public URL.

        `kind` is `brochures` (PDF) or `images` (JPEG/PNG share-location cards).

        This does not change what the bot sends. Point
        ``documents.<product>.brochure`` or ``share_location_image.url`` at the
        returned URL to make it live — uploading a draft must never start
        sending it.
        """
        library = library_for(kind)
        content = await file.read()
        try:
            saved = library.save(file.filename or "", content, overwrite=overwrite)
        except MediaError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        return {"kind": kind, **saved.as_dict()}

    @app.delete("/admin/api/media/{kind}/{filename}", tags=["media"], summary="Delete a brochure or image", responses={**_UNAUTHORIZED, 404: {"description": "Unknown media kind, or no such file."}})
    def delete_media(
        kind: str,
        filename: str,
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        library = library_for(kind)
        try:
            removed = library.delete(filename)
        except MediaError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        if not removed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No {kind} file named {filename}.",
            )
        return {"kind": kind, "filename": filename, "deleted": True}

    # --- knowledge base ----------------------------------------------------

    @app.get("/admin/api/kb", tags=["knowledge base"], summary="What the bot grounds its answers on", responses={**_UNAUTHORIZED, 502: {"description": "The knowledge base could not be read."}})
    def read_knowledge_base(_: None = Depends(require_admin)) -> dict[str, Any]:
        """Every document in the File Search store, with duplicates flagged.

        Indexing never replaces, so a display name appearing twice means two
        copies are live and the bot may be citing the older one.
        """
        try:
            return kb.summary()
        except KnowledgeBaseError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
            ) from exc

    @app.post("/admin/api/kb", tags=["knowledge base"], summary="Index a document into the knowledge base", responses={**_UNAUTHORIZED, 400: {"description": "Empty, too large, or unnamed."}, 502: {"description": "The knowledge base could not be reached."}})
    async def add_knowledge_document(
        file: UploadFile = File(..., description="The document to index."),
        display_name: str = Form("", description="Defaults to the filename."),
        replace: bool = Form(False, description="Delete existing documents with the same display name."),
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        """Add a document the bot will ground its answers on.

        Returns as soon as the file is accepted, not once it is searchable —
        indexing runs for minutes, and holding the request open that long would
        be dropped by the tunnel in front of this app. Poll `GET /admin/api/kb`
        and watch the document go from `STATE_PENDING` to `STATE_ACTIVE`.

        Pass `replace=true` when re-indexing a corrected document: indexing has
        no upsert, so otherwise the new copy simply joins the stale one and the
        bot may cite either.
        """
        content = await file.read()
        try:
            return kb.add(
                file.filename or "",
                content,
                display_name=display_name,
                replace=replace,
            )
        except KnowledgeBaseError as exc:
            message = str(exc)
            rejected = any(
                phrase in message
                for phrase in ("limit is", "empty", "is required")
            )
            raise HTTPException(
                status_code=(
                    status.HTTP_400_BAD_REQUEST
                    if rejected
                    else status.HTTP_502_BAD_GATEWAY
                ),
                detail=message,
            ) from exc

    @app.delete("/admin/api/kb/{document_id}", tags=["knowledge base"], summary="Remove a document from the knowledge base", responses={**_UNAUTHORIZED, 404: {"description": "No such document in this store."}, 502: {"description": "The knowledge base could not be reached."}})
    def delete_knowledge_document(
        document_id: str,
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        """Delete one document. Takes effect on the next customer message."""
        try:
            removed = kb.delete(document_id)
        except KnowledgeBaseError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
            ) from exc
        if not removed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No document {document_id} in this knowledge base.",
            )
        return {"document_id": document_id, "deleted": True}

    @app.get("/admin/api/gemini", tags=["credentials"], summary="Gemini key state", responses=_UNAUTHORIZED)
    def gemini_status(_: None = Depends(require_admin)) -> dict[str, Any]:
        return _gemini_status()

    @app.post("/admin/api/gemini", tags=["credentials"], summary="Set or rotate the Gemini key", responses={**_UNAUTHORIZED, 400: {"description": "Key missing, or rejected by Gemini."}})
    def set_gemini_key(
        payload: dict[str, Any],
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        api_key = (payload or {}).get("api_key", "")
        if not isinstance(api_key, str) or not api_key.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="api_key is required.",
            )
        try:
            key_manager.persist_api_key(api_key, validate=True)
        except Exception as exc:  # invalid key / network — report, don't 500
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Key rejected: {exc}",
            ) from exc
        return _gemini_status()

    @app.delete("/admin/api/gemini", tags=["credentials"], summary="Clear the runtime Gemini key", responses=_UNAUTHORIZED)
    def clear_gemini_key(_: None = Depends(require_admin)) -> dict[str, Any]:
        key_manager.clear_persisted_key()
        return _gemini_status()

    return app


def _production_app() -> FastAPI:
    store = get_store()
    store.ensure_seeded()
    return create_admin_app(admin_token=config.ADMIN_TOKEN, config_store=store)


app = _production_app()

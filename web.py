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

import config
import rag
from admin_config import (
    VOICE_POLICIES,
    AdminConfigStore,
    default_config,
    get_store,
    validate_config,
)
from admin_status import StatusReporter
from leads import read_leads, read_leads_csv
from media_library import MEDIA_KINDS, MediaError, MediaLibrary
from session_keys import client_session_key

_PAGE_PATH = Path(__file__).with_name("assets") / "admin.html"

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

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

from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse

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
from session_keys import client_session_key

_PAGE_PATH = Path(__file__).with_name("assets") / "admin.html"


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
) -> FastAPI:
    app = FastAPI(title="TVS Bot Admin")

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
        authorization: str | None = Header(default=None),
    ) -> None:
        if not admin_token:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Admin panel is disabled (ADMIN_TOKEN is not set).",
            )
        expected = f"Bearer {admin_token}"
        if not authorization or authorization != expected:
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

    @app.get("/admin/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
    def admin_page() -> HTMLResponse:
        return HTMLResponse(_PAGE_PATH.read_text(encoding="utf-8"))

    @app.get("/admin/api/meta")
    def meta(_: None = Depends(require_admin)) -> dict[str, Any]:
        return {
            "voice_policies": sorted(VOICE_POLICIES),
            "default_config": default_config(),
            "gemini": _gemini_status(),
        }

    @app.get("/admin/api/config")
    def read_config(_: None = Depends(require_admin)) -> dict[str, Any]:
        return config_store.get()

    @app.put("/admin/api/config")
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

    @app.get("/admin/api/status")
    def operational_status(_: None = Depends(require_admin)) -> dict[str, Any]:
        """Is the bot working? One verdict plus the six checks behind it."""
        return reporter.snapshot()

    @app.post("/admin/api/session/reset")
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

    @app.get("/admin/api/gemini")
    def gemini_status(_: None = Depends(require_admin)) -> dict[str, Any]:
        return _gemini_status()

    @app.post("/admin/api/gemini")
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

    @app.delete("/admin/api/gemini")
    def clear_gemini_key(_: None = Depends(require_admin)) -> dict[str, Any]:
        key_manager.clear_persisted_key()
        return _gemini_status()

    return app


def _production_app() -> FastAPI:
    store = get_store()
    store.ensure_seeded()
    return create_admin_app(admin_token=config.ADMIN_TOKEN, config_store=store)


app = _production_app()

"""Local/CI simulator for the client CRM and reply webhook."""
from __future__ import annotations

import os
import secrets
import threading
import time
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials


DEFAULT_CUSTOMERS = {
    "+918286871533": [
        {
            "customer_id": "mock-customer-1",
            "name": "Asha",
            "preferred_language": "Marathi",
        }
    ]
}


def create_mock_client(*, username: str, password: str) -> FastAPI:
    app = FastAPI(title="Mock Client CRM")
    security = HTTPBasic()
    lock = threading.Lock()
    state = {
        "customers": {key: list(value) for key, value in DEFAULT_CUSTOMERS.items()},
        "lookups": [],
        "replies": [],
        "reply_statuses": [],
        "lookup_statuses": [],
        "lookup_delay_seconds": 0.0,
    }

    def authenticate(credentials: HTTPBasicCredentials = Depends(security)) -> None:
        valid = secrets.compare_digest(credentials.username, username)
        valid = valid and secrets.compare_digest(credentials.password, password)
        if not valid:
            raise HTTPException(status_code=401, detail="Invalid mock client credentials")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/mock/customers")
    def customers(mobile: str, _: None = Depends(authenticate)):
        with lock:
            delay = state["lookup_delay_seconds"]
        if delay:
            time.sleep(delay)
        with lock:
            state["lookups"].append(
                {
                    "mobile": mobile,
                    "timestamp": datetime.now(timezone.utc).isoformat(
                        timespec="milliseconds"
                    ),
                }
            )
            status_code = (
                state["lookup_statuses"].pop(0)
                if state["lookup_statuses"]
                else 200
            )
            matches = list(state["customers"].get(mobile) or [])
        if not 200 <= status_code < 300:
            return JSONResponse(
                status_code=status_code,
                content={"error": "configured lookup response"},
            )
        if not matches:
            return JSONResponse(status_code=404, content={"customers": []})
        return {"customers": matches}

    @app.post("/mock/replies")
    def replies(payload: dict, _: None = Depends(authenticate)):
        with lock:
            state["replies"].append(payload)
            status_code = (
                state["reply_statuses"].pop(0)
                if state["reply_statuses"]
                else 204
            )
        return Response(status_code=status_code)

    @app.get("/mock/state")
    def inspect_state(_: None = Depends(authenticate)):
        with lock:
            return {
                "lookups": list(state["lookups"]),
                "replies": list(state["replies"]),
            }

    @app.post("/mock/control/reply-statuses")
    def set_reply_statuses(payload: dict, _: None = Depends(authenticate)):
        statuses = payload.get("statuses")
        if not isinstance(statuses, list) or not all(
            isinstance(item, int) and 100 <= item <= 599 for item in statuses
        ):
            raise HTTPException(status_code=400, detail="statuses must be HTTP integers")
        with lock:
            state["reply_statuses"] = list(statuses)
        return {"status": "ok"}

    @app.post("/mock/control/customer")
    def set_customer(payload: dict, _: None = Depends(authenticate)):
        mobile = str(payload.get("mobile") or "")
        customers = payload.get("customers")
        if not mobile or not isinstance(customers, list):
            raise HTTPException(
                status_code=400,
                detail="mobile and customers list are required",
            )
        with lock:
            state["customers"][mobile] = list(customers)
        return {"status": "ok"}

    @app.post("/mock/control/lookup")
    def configure_lookup(payload: dict, _: None = Depends(authenticate)):
        statuses = payload.get("statuses") or []
        delay = payload.get("delay_seconds", 0)
        if not isinstance(statuses, list) or not all(
            isinstance(item, int) and 100 <= item <= 599 for item in statuses
        ):
            raise HTTPException(status_code=400, detail="statuses must be HTTP integers")
        if not isinstance(delay, (int, float)) or delay < 0:
            raise HTTPException(status_code=400, detail="delay_seconds must be positive")
        with lock:
            state["lookup_statuses"] = list(statuses)
            state["lookup_delay_seconds"] = float(delay)
        return {"status": "ok"}

    @app.post("/mock/control/reset")
    def reset(_: None = Depends(authenticate)):
        with lock:
            state["lookups"] = []
            state["replies"] = []
            state["reply_statuses"] = []
            state["lookup_statuses"] = []
            state["lookup_delay_seconds"] = 0.0
            state["customers"] = {
                key: list(value) for key, value in DEFAULT_CUSTOMERS.items()
            }
        return {"status": "ok"}

    @app.get("/mock/media/audio.mp3")
    def audio_fixture():
        return Response(content=b"ID3mock-audio", media_type="audio/mpeg")

    @app.get("/mock/media/document.jpg")
    def image_fixture():
        return Response(
            content=b"\xff\xd8\xff\xe0mock-document\xff\xd9",
            media_type="image/jpeg",
        )

    @app.get("/mock/media/{case}.jpg")
    def image_case_fixture(case: str):
        allowed = {"document", "unclear", "non-document", "multiple"}
        if case not in allowed:
            raise HTTPException(status_code=404, detail="Unknown fixture")
        return Response(
            content=b"\xff\xd8\xff\xe0" + case.encode() + b"\xff\xd9",
            media_type="image/jpeg",
        )

    return app


app = create_mock_client(
    username=os.environ.get("MOCK_CLIENT_USER", "mock-client"),
    password=os.environ.get("MOCK_CLIENT_PASSWORD", "mock-secret"),
)

"""``POST /api/intake/submissions`` — the HTTP door of the intake contract (operator paste; Grok uses the CLI).

* A delivery that fails the contract is refused with 422 before any database connection is opened.
* The database work (one transaction, including a possible wait on the intake advisory lock) runs in a worker thread
  (``run_in_threadpool``), never on the event loop, so other requests keep being served meanwhile (review 004 #3).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from projectzero.core.config import Settings
from projectzero.core.db import transaction
from projectzero.dealflow.intake.contract import validate_external
from projectzero.dealflow.intake.postgres import IntakeClosedError, PostgresIntake
from projectzero.dealflow.intake.service import IntakeService

router = APIRouter(prefix="/api/intake", tags=["intake"])


def submit_delivery(settings: Settings, payload: dict[str, Any], submitted_by: str) -> tuple[int, dict[str, Any]]:
    """Blocking: record and resolve one delivery in one transaction. Returns (HTTP status, body)."""
    try:
        with transaction(settings.db_url) as conn:
            store = PostgresIntake(conn, settings.schema)
            result = IntakeService(store, resolver=store).submit_external(payload, submitted_by=submitted_by)
    except IntakeClosedError as exc:
        return 409, {"ok": False, "error": str(exc)}
    return 200, {
        "ok": True,
        "outcome": result.outcome,
        "sha256": result.sha256,
        "accepted": result.accepted,
        "resolution": list(result.resolution),
    }


@router.post("/submissions")
async def submit(request: Request) -> JSONResponse:
    try:
        payload: Any = await request.json()
    except ValueError:
        return JSONResponse({"ok": False, "error": "body is not valid JSON"}, status_code=400)
    issues = validate_external(payload)
    if issues:
        return JSONResponse(
            {"ok": False, "error": "delivery refused by the intake contract", "issues": [str(i) for i in issues]},
            status_code=422,
        )
    submitted_by = "operator" if payload.get("origin") == "manual" else str(payload.get("origin"))
    status, body = await run_in_threadpool(submit_delivery, request.app.state.settings, payload, submitted_by)
    return JSONResponse(body, status_code=status)

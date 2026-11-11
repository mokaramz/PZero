"""Deal Flow endpoints — thin: parse, run the blocking store call in the threadpool (sync ``def`` routes), shape.

* ``GET  /api/deal-flow/inbox``                      the whole Deal Flow in the old ``/api/inbox`` shape (review 009)
* ``GET  /api/deal-flow/candidates``                 list: ``status`` / ``origin`` (repeatable), ``q``, ``limit``,
                                                     ``cursor``
* ``GET  /api/deal-flow/candidates/{id}``            detail; ``?ns=scout_intake|native_scout`` resolves an old id
* ``POST /api/deal-flow/candidates/{id}/decision``   ``{status, reason?, notes?, expected_status?}``

Errors use ``{ok: false, error, ...}`` with 400 / 404 / 409, like the rest of the API.
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from projectzero.core.db import transaction
from projectzero.dealflow.candidates import DealFlowStore, DecisionError, ListQuery, validate_operator_status
from projectzero.dealflow.inbox_view import inbox_view

router = APIRouter(prefix="/api/deal-flow", tags=["deal-flow"])


def _error(exc: DecisionError) -> JSONResponse:
    return JSONResponse({"ok": False, "error": str(exc), **exc.extra}, status_code=exc.status)


def _ok(body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(jsonable_encoder({"ok": True, **body}))


@router.get("/inbox")
def get_inbox(request: Request) -> JSONResponse:
    """The page ranks the whole pool on the client, so it reads it at once (the old ``GET /api/inbox``)."""
    settings = request.app.state.settings
    with transaction(settings.db_url) as conn:
        return JSONResponse(jsonable_encoder(inbox_view(conn, settings.schema)))


@router.get("/candidates")
def list_candidates(
    request: Request,
    status: Annotated[list[str] | None, Query()] = None,
    origin: Annotated[list[str] | None, Query()] = None,
    q: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> JSONResponse:
    settings = request.app.state.settings
    try:
        query = ListQuery(tuple(status or ()), tuple(origin or ()), q.strip() if q else None, limit, cursor)
        with transaction(settings.db_url) as conn:
            return _ok(DealFlowStore(conn, settings.schema).list_candidates(query))
    except DecisionError as exc:
        return _error(exc)


@router.get("/candidates/{candidate_id}")
def get_candidate(request: Request, candidate_id: str, ns: str = "candidate") -> JSONResponse:
    settings = request.app.state.settings
    try:
        with transaction(settings.db_url) as conn:
            store = DealFlowStore(conn, settings.schema)
            resolved = store.resolve_id(ns, candidate_id)
            detail = store.get_candidate(resolved) if resolved else None
    except DecisionError as exc:
        return _error(exc)
    if detail is None:
        return JSONResponse({"ok": False, "error": "candidate not found"}, status_code=404)
    return _ok({"resolved_from": {"namespace": ns, "id": candidate_id}, **detail})


class DecisionBody(BaseModel):
    status: str
    reason: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=10000)
    expected_status: str | None = None


@router.post("/candidates/{candidate_id}/decision")
def decide(request: Request, candidate_id: str, body: DecisionBody) -> JSONResponse:
    settings = request.app.state.settings
    try:
        validate_operator_status(body.status)
        with transaction(settings.db_url) as conn:
            store = DealFlowStore(conn, settings.schema)
            resolved = store.resolve_id("candidate", candidate_id)  # an absorbed old id decides its survivor
            if resolved is None:
                return JSONResponse({"ok": False, "error": "candidate not found"}, status_code=404)
            result = store.decide(
                resolved, body.status, reason=body.reason, notes=body.notes, expected_status=body.expected_status
            )
            result["resolved_from"] = {"namespace": "candidate", "id": candidate_id}
    except DecisionError as exc:
        return _error(exc)
    except psycopg.errors.UniqueViolation as exc:  # last line of defence: the database's one-open-candidate rule
        if exc.diag.constraint_name != "candidates_one_open_per_company":
            raise
        return JSONResponse(
            {"ok": False, "error": "this company already has an open candidate; reload and decide again"},
            status_code=409,
        )
    return _ok(result)

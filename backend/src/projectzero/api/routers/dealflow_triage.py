"""Deal Flow machine triage — thin: parse, run the blocking work in the threadpool (sync ``def`` routes), shape.

* ``GET  /api/deal-flow/triage``              the old ``GET /api/triage`` payload (``architecture``, ``proposals``,
                                              ``counts``, ``calibration``, ``pending``, ``note``), built from ``pz``
                                              by ``dealflow.triage.view.triage_view``. Like the old route, the body is
                                              the payload itself (no ``ok`` envelope).
* ``POST /api/deal-flow/triage/decide``       the old ``/api/triage_decide`` (review 035a): ``{id, verdict:
                                              KEEP|RESEARCH|WATCH|REJECT, mode: accept|override, note?,
                                              expected_status?}`` -> ``{ok, verdict, agreed, inbox_decision,
                                              open_keep}``
* ``POST /api/deal-flow/triage/batch_reject`` the old ``/api/triage_batch_reject``: ``{ids, confirm?}`` -> the preview
                                              ``{ok, preview: true, eligible, skipped}`` or ``{ok, applied, skipped}``

The writes are ``dealflow.triage.decide``, each in ONE transaction; the answer is sent after it commits. Errors use
``{ok: false, error, ...}``: 400 with the old texts, the decision route's 404 / 409 bodies, 409 before the import.
``app.state.clock`` is the test seam for the logged ``ts``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

import psycopg
from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from projectzero.api.routers.conviction import Body
from projectzero.core.db import snapshot_transaction, transaction
from projectzero.dealflow.candidates import DecisionError
from projectzero.dealflow.intake.postgres import IntakeClosedError
from projectzero.dealflow.triage import decide as triage_decide
from projectzero.dealflow.triage.view import triage_view
from projectzero.network.view import BERLIN

router = APIRouter(prefix="/api/deal-flow", tags=["deal-flow"])


def _clock(request: Request) -> datetime:
    clock: Callable[[], datetime] | None = getattr(request.app.state, "clock", None)
    return clock() if clock is not None else datetime.now(BERLIN)


@router.get("/triage")
def get_triage(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    with transaction(settings.db_url) as conn:
        body = triage_view(conn, settings.schema)
    return JSONResponse(jsonable_encoder(body))


def _write(
    request: Request,
    body: Any,
    check: Callable[[Any], Any],
    work: Callable[..., dict[str, Any]],
    read_only: Callable[[Any], bool] = lambda _body: False,
) -> JSONResponse:
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    try:
        check(body)  # the pure checks first: a bad request never opens a connection
        # a read (the batch preview) runs over ONE read-only snapshot, chosen before the first query (H-351)
        tx = snapshot_transaction if read_only(body) else transaction
        with tx(settings.db_url) as conn:
            out = work(conn, settings.schema, body, _clock(request))
    except triage_decide.TriageError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=exc.status)
    except DecisionError as exc:
        return JSONResponse({"ok": False, "error": str(exc), **exc.extra}, status_code=exc.status)
    except IntakeClosedError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
    except psycopg.errors.UniqueViolation as exc:  # last line of defence: the database's one-open-candidate rule
        if exc.diag.constraint_name != "candidates_one_open_per_company":
            raise
        return JSONResponse(
            {"ok": False, "error": "this company already has an open candidate; reload and decide again"},
            status_code=409,
        )
    return JSONResponse(jsonable_encoder(out))


@router.post("/triage/decide")
def decide(request: Request, body: Body) -> JSONResponse:
    return _write(request, body, triage_decide.parse_decide, triage_decide.decide)


@router.post("/triage/batch_reject")
def batch_reject(request: Request, body: Body) -> JSONResponse:
    return _write(request, body, triage_decide.parse_batch, triage_decide.batch_reject,
                  read_only=lambda b: not triage_decide.batch_confirm(b))  # fmt: skip

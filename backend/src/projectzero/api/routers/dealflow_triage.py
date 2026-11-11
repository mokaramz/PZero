"""Deal Flow triage read side — thin: run the blocking read in the threadpool (sync ``def`` route), return the payload.

* ``GET /api/deal-flow/triage``   the old ``GET /api/triage`` payload (``architecture``, ``proposals``, ``counts``,
                                  ``calibration``, ``pending``, ``note``), built from ``pz`` by
                                  ``dealflow.triage.view.triage_view``. Like the old route, the body is the payload
                                  itself (no ``ok`` envelope), so the ported Deal Flow page reads it unchanged.

The decide / batch-reject write side comes with the triage panel's own review.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from projectzero.core.db import transaction
from projectzero.dealflow.triage.view import triage_view

router = APIRouter(prefix="/api/deal-flow", tags=["deal-flow"])


@router.get("/triage")
def get_triage(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    with transaction(settings.db_url) as conn:
        body = triage_view(conn, settings.schema)
    return JSONResponse(jsonable_encoder(body))

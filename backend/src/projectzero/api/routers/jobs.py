"""Background-job endpoints (review 032c): the old ``/api/catchup`` and ``/api/catchup_run`` with the old bodies.

* ``GET  /api/catchup``      the old ``scheduler.status()``: ``{running, queue, current, done, started, finished,
                             enabled, plan, lock, runners}`` (the in-process run of this app, the switch, the plan
                             with ``availability: "not ported yet"`` on the six unported jobs, the lock, and the runner
                             records: the archived ``runner.json`` overlaid by source, the ONE reader System health
                             uses too)
* ``POST /api/catchup_run``  ``{only?: [job id]}`` -> ``{started: true}`` (the overdue jobs run in a thread, source
                             ``app``), or ``{started: false, reason: "already running"}`` while a run of this app is in
                             progress, or ``{started: false, reason: <IMPORT_REFUSED>}`` before the live import
                             (decision a: nothing runs, nothing is recorded)

``app.state.clock`` (the run's clock) and ``app.state.jobs_deps`` (the jobs' fetchers / transports; ``None``: the
network) are the test seams, as the Events and News routes take theirs.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from projectzero.api.routers.conviction import Body
from projectzero.events.when import BERLIN
from projectzero.jobs import runner

router = APIRouter(prefix="/api", tags=["background jobs"])


def _clock(request: Request) -> Callable[[], datetime]:
    clock: Callable[[], datetime] | None = getattr(request.app.state, "clock", None)
    return clock if clock is not None else (lambda: datetime.now(BERLIN))


@router.get("/catchup")
def catchup(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    body = runner.status(settings.db_url, settings.schema, now=_clock(request)())
    return JSONResponse(jsonable_encoder(body))


@router.post("/catchup_run")
def catchup_run(request: Request, body: Body) -> JSONResponse:
    """Run the overdue jobs now, in the background (the same pass the app runs on start)."""
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    raw: Any = body.get("only") or []
    only = [str(x) for x in raw] if isinstance(raw, list) else []
    out = runner.start_manual(settings.db_url, settings.schema, only or None,
                              deps=getattr(request.app.state, "jobs_deps", None), clock=_clock(request))  # fmt: skip
    return JSONResponse(jsonable_encoder(out))

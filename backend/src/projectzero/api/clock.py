"""The request clock of the read models (Codex H-299): the request instant as naive Europe/Berlin wall time.

Without an injected ``app.state.clock`` the instant is ``datetime.now(BERLIN)``, an AWARE time, so a server running
in UTC (or any other zone) still answers the Berlin date: at 23:30 UTC on 13 November it is already 14 November in
Berlin. An injected clock may be aware (converted) or naive (taken as Berlin wall time, as the old app did).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from fastapi import Request

from projectzero.events.when import BERLIN
from projectzero.network.view import berlin_now


def berlin_request_now(request: Request) -> datetime:
    clock: Callable[[], datetime] | None = getattr(request.app.state, "clock", None)
    instant = clock() if clock is not None else datetime.now(BERLIN)
    return berlin_now(instant).replace(tzinfo=None)

"""Codex H-299: the read models' request clock answers the BERLIN wall time even when no clock is injected and the
server runs in UTC. At 23:30 UTC on 13 November (no daylight saving: CET is UTC+1) Berlin is at 00:30 on 14 November.
No database: the machine clock is replaced."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from projectzero.api import clock as api_clock

INSTANT = datetime(2026, 11, 13, 23, 30, tzinfo=UTC)


class _MachineClock(datetime):
    """``datetime.now()`` as a UTC server answers it: naive means UTC wall time here, aware is converted."""

    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
        return INSTANT.astimezone(tz) if tz is not None else INSTANT.replace(tzinfo=None)


def _request(clock: Any = None) -> Any:
    state = SimpleNamespace() if clock is None else SimpleNamespace(clock=clock)
    return SimpleNamespace(app=SimpleNamespace(state=state))


def test_without_an_injected_clock_a_utc_server_answers_the_berlin_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_clock, "datetime", _MachineClock)
    now = api_clock.berlin_request_now(_request())
    assert now == datetime(2026, 11, 14, 0, 30) and now.tzinfo is None
    assert now.date().isoformat() == "2026-11-14"  # the naive machine time would have said 2026-11-13


@pytest.mark.parametrize(
    "injected",
    [INSTANT, INSTANT.astimezone(timezone(timedelta(hours=-5))), datetime(2026, 11, 14, 0, 30)],
    ids=["aware-utc", "aware-other-zone", "naive-berlin-wall-time"],
)
def test_an_injected_clock_is_berlin_wall_time(injected: datetime) -> None:
    assert api_clock.berlin_request_now(_request(lambda: injected)) == datetime(2026, 11, 14, 0, 30)

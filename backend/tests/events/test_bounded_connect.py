"""Codex H-284: ``bounded_transaction`` never opens a connection that could outlive its deadline. libpq's smallest
connect timeout is 2 s: with less time left no connection is attempted (a 503 with nothing done); otherwise the timeout
is rounded DOWN to the time left. No database: the connection seam is replaced."""

from __future__ import annotations

from typing import Any

import pytest

from projectzero.events import scan
from projectzero.events.edits import EventsError


class _Refused(Exception):
    pass


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []

    def fake_connect(db_url: str, *, connect_timeout: int) -> Any:
        calls.append(connect_timeout)
        raise _Refused  # stop before any SQL: only the connect step is under test

    monkeypatch.setattr(scan, "_connect", fake_connect)
    return calls


@pytest.mark.parametrize("left", [0.0, 0.1, 1.0, 1.99])
def test_no_connection_is_attempted_when_its_shortest_timeout_cannot_fit(seen: list[int], left: float) -> None:
    with (
        pytest.raises(EventsError) as exc,
        scan.bounded_transaction("postgresql://invented", 100.0 + left, lambda: 100.0),
    ):
        pass
    assert exc.value.status == 503 and seen == []


@pytest.mark.parametrize(("left", "timeout"), [(2.0, 2), (3.7, 3), (59.99, 59)])
def test_the_connect_timeout_is_rounded_down_to_the_time_left(seen: list[int], left: float, timeout: int) -> None:
    with pytest.raises(_Refused), scan.bounded_transaction("postgresql://invented", 100.0 + left, lambda: 100.0):
        pass
    assert seen == [timeout]

"""Review 030a revision 2: ``today.inputs.load`` opens no connection of its own: every reader gets the ONE connection
it was given (the route's REPEATABLE READ snapshot), and the ``after_first_read`` seam runs after the pipeline read and
before every other read. No database: each reader is replaced by a recorder."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from projectzero.today import inputs as today_inputs


class _Conn:
    """A stand-in connection; any attempt to use it as a real one fails the test."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the fake connection was used directly: {name}")


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    seen: list[tuple[str, Any]] = []

    class Store:
        def __init__(self, conn: Any, schema: str) -> None:
            seen.append(("conviction", conn))

        def entry_rows(self) -> list[Any]:
            return []

        def rest(self) -> dict[str, Any]:
            return {"week": ""}

    class Calls:
        def __init__(self, conn: Any, schema: str) -> None:
            seen.append(("founder_calls", conn))

        def load(self) -> None:
            return None

    def recorder(name: str, value: Any) -> Any:
        def read(conn: Any, schema: str, *a: Any, **kw: Any) -> Any:
            seen.append((name, conn))
            return value() if callable(value) else value

        return read

    from projectzero.conviction import pipeline
    from projectzero.conviction.pipeline import Inputs
    from projectzero.dealflow.triage import view as triage_view
    from projectzero.events import store as events_store
    from projectzero.events.store import EventsData

    monkeypatch.setattr(today_inputs, "ConvictionStore", Store)
    monkeypatch.setattr(today_inputs, "FounderCallsStore", Calls)
    monkeypatch.setattr(today_inputs, "load_people", recorder("people", list))
    monkeypatch.setattr(today_inputs, "load_documents", recorder("documents", dict))
    monkeypatch.setattr(today_inputs, "inputs_from", lambda docs, people: Inputs())
    monkeypatch.setattr(pipeline, "build", lambda *a: {"signals": []})
    monkeypatch.setattr(events_store, "load", recorder("events", lambda: EventsData([], [])))
    monkeypatch.setattr(today_inputs, "candidate_rows", recorder("candidates", list))
    monkeypatch.setattr(triage_view, "load", recorder("triage", lambda: triage_view.TriageInputs([], {})))
    monkeypatch.setattr(triage_view, "build", lambda inp: {"proposals": {}})
    monkeypatch.setattr(today_inputs, "_queue_routing", recorder("queue_routing", lambda: {"routes": {}}))
    return seen


def test_every_reader_gets_the_one_connection_and_the_seam_runs_after_the_pipeline(calls: list[Any]) -> None:
    conn = _Conn()
    seam = lambda: calls.append(("seam", conn))  # noqa: E731
    today_inputs.load(conn, "pz_invented", datetime(2026, 11, 13, 9), after_first_read=seam)  # type: ignore[arg-type]
    names = [n for n, _ in calls]
    assert all(c is conn for _, c in calls)
    assert names.index("seam") == names.index("documents") + 1  # right after the pipeline's last read
    after = set(names[names.index("seam") + 1 :])
    assert after == {"founder_calls", "events", "candidates", "triage", "queue_routing"}


def test_the_triage_summaries_are_keyed_in_inbox_order() -> None:
    proposals = {"c-101": {"n": 1}, "c-205": {"n": 2}, "c-300": {"n": 3}}
    out = today_inputs.in_inbox_order(proposals, ["c-205", "c-999", "c-101"])
    assert list(out) == ["c-205", "c-101", "c-300"]  # the inbox order, then any summary the inbox does not list
    assert out["c-205"] is proposals["c-205"]

"""Review 031a acceptance tests against the hosted project, in throw-away scratch schemas, with invented names only.

* every golden world, imported by the PRODUCTION importer and served by ``GET /api/home``, answers exactly what the
  OLD ``ecosys.home()`` answered (the oracle's golden); the GET leaves every table unchanged (whole rows compared);
* the inbox order decides ``latest_signals`` (``main``: a later id first in the inbox);
* a candidate the new intake created counts as a new signal, with its source name; a Scout-only candidate the merge
  brought into Deal Flow counts too (declared j);
* the read runs at REPEATABLE READ, READ ONLY (decision c).
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.types.json import Jsonb

from projectzero.api.app import create_app
from projectzero.core.config import Settings
from projectzero.core.db import connect, snapshot_transaction, transaction
from projectzero.dealflow.ranking.tagging import TAGGING_VERSION
from projectzero.home import inputs as home_inputs
from projectzero.ops.parity_founder_calls import utc_instant
from projectzero.ops.parity_home import read_golden
from projectzero.ops.parity_ranking import diff, js
from projectzero.ops.parity_validation import _fingerprint
from projectzero.ops.scratch_import import import_world

pytestmark = pytest.mark.hosted


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture(scope="module")
def golden() -> dict[str, Any]:
    return read_golden()


def importable(docs: dict[str, Any]) -> dict[str, Any]:
    """The world as the importer takes it: an inbox record without an ``id`` stops the import plan, and both the old
    reader (``compat.records(..., ("id",))``) and the new one drop such a record anyway, so it is left out here (the
    answer must still equal the old one, which saw it)."""
    out = copy.deepcopy(docs)
    inbox = out.get("inbox.json")
    if isinstance(inbox, dict) and isinstance(inbox.get("candidates"), list):
        inbox["candidates"] = [c for c in inbox["candidates"] if isinstance(c, dict) and c.get("id")]
    real = out.get("real_data.json")  # likewise a Conviction record with no usable company name (an import blocker)
    if isinstance(real, dict) and isinstance(real.get("signals"), list):
        real["signals"] = [e for e in real["signals"] if isinstance(e, dict) and isinstance(e.get("company"), str)
                           and e["company"].strip()]  # fmt: skip
    return out


@pytest.fixture
def world(settings: Settings, golden: dict[str, Any]) -> Iterator[Callable[[str], str]]:
    made: list[str] = []

    def make(name: str) -> str:
        made.append(import_world(settings.db_url, importable(golden["worlds"][name]["docs"])))
        return made[-1]

    yield make
    with connect(settings.db_url, autocommit=True) as admin:
        for schema in made:
            admin.execute(sql.SQL("drop schema if exists {} cascade").format(sql.Identifier(schema)))


def _get(settings: Settings, schema: str, clock: str) -> dict[str, Any]:
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    app.state.clock = lambda: utc_instant(clock)
    with TestClient(app, base_url="http://127.0.0.1:8177") as client:
        r = client.get("/api/home")
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


@pytest.mark.parametrize("name", ["main", "fallback", "gated", "legacy", "empty"])
def test_an_imported_world_answers_what_the_old_code_answered_and_writes_nothing(
    settings: Settings, golden: dict[str, Any], world: Callable[[str], str], name: str
) -> None:
    w = golden["worlds"][name]
    schema = world(name)
    with transaction(settings.db_url) as conn:
        before = _fingerprint(conn, schema)
    got = _get(settings, schema, w["clock"])
    with transaction(settings.db_url) as conn:
        after = _fingerprint(conn, schema)
    assert diff(js(w["expected"]["ok"]), js(got)) == []
    assert json.dumps(w["expected"]["ok"], ensure_ascii=False) == json.dumps(got, ensure_ascii=False)  # key order
    assert sorted(t for t in before if before[t] != after.get(t)) == []


def test_the_inbox_order_decides_the_latest_signals(
    settings: Settings, golden: dict[str, Any], world: Callable[[str], str]
) -> None:
    w = golden["worlds"]["main"]
    inbox = [c for c in w["docs"]["inbox.json"]["candidates"] if c.get("id") and c.get("decision") == "new"]
    by_id = sorted(inbox, key=lambda c: c["id"])
    assert [c["name"] for c in inbox[:3]] != [c["name"] for c in by_id[:3]]  # the world tells the two orders apart
    got = _get(settings, world("main"), w["clock"])
    assert [s["name"] for s in got["latest_signals"]] == [c["name"] for c in inbox[:3]]


def _candidate(conn: Any, schema: str, cid: str, name: str, origins: list[str], attrs: dict[str, Any]) -> None:
    q = sql.SQL(
        "insert into {}.candidates (id, name, status, origins, first_seen_at, attrs) values (%s, %s, 'new', %s, %s, %s)"
    ).format(sql.Identifier(schema))
    conn.execute(q, (cid, name, origins, datetime(2026, 11, 12, 8, tzinfo=UTC), Jsonb(attrs)))


def test_new_intake_and_scout_only_candidates_count_as_new_signals(
    settings: Settings, golden: dict[str, Any], world: Callable[[str], str]
) -> None:
    w = golden["worlds"]["gated"]  # no new signal of its own
    schema = world("gated")
    before = _get(settings, schema, w["clock"])
    assert before["new_signals"] == 0 and before["latest_signals"] == []
    record = {"id": "c-intake-0001", "name": "Invented Plover Systems", "decision": "new",
              "source": "Invented Lab Spin-outs", "description": "Invented spin-out."}  # fmt: skip
    with transaction(settings.db_url) as conn:
        _candidate(conn, schema, "c-intake-0001", "Invented Plover Systems", ["manual"],
                   {"tagging": {"version": TAGGING_VERSION, "inputs": {}, "sightings": [], "record": record}})  # fmt: skip
        _candidate(conn, schema, "c-scout-0001", "Invented Tern Robotics", ["legacy_scout00"], {})
    with snapshot_transaction(settings.db_url) as conn:
        inputs = home_inputs.load(conn, schema, datetime.fromisoformat(w["clock"]))
    sources = {c["id"]: c["source"] for c in inputs.candidates if c["id"] in ("c-intake-0001", "c-scout-0001")}
    assert sources == {"c-intake-0001": "Invented Lab Spin-outs", "c-scout-0001": "legacy_scout00"}
    after = _get(settings, schema, w["clock"])
    assert after["new_signals"] == 2  # declared (j): the merged Deal Flow counts the Scout-only candidate too
    assert after["latest_signals"] == [
        {"name": "Invented Plover Systems", "source": "Invented Lab Spin-outs"},
        {"name": "Invented Tern Robotics", "source": "legacy_scout00"},
    ]  # no inbox position: first sighting, then id


def test_the_route_reads_at_repeatable_read_read_only(settings: Settings, world: Callable[[str], str]) -> None:
    schema = world("main")
    with snapshot_transaction(settings.db_url) as conn:
        level = conn.execute(b"show transaction_isolation").fetchone()
        ro = conn.execute(b"show transaction_read_only").fetchone()
        home_inputs.load(conn, schema, datetime(2026, 11, 13, 9))
    assert level == ("repeatable read",) and ro == ("on",)


def test_without_an_injected_clock_the_routes_answer_the_berlin_date(
    settings: Settings, world: Callable[[str], str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex H-299: no ``app.state.clock``; the machine says 23:30 UTC on 13 November, Berlin is on 14 November. Both
    read models (the desk and Today) answer the Berlin date."""
    from projectzero.api import clock as api_clock

    instant = datetime(2026, 11, 13, 23, 30, tzinfo=UTC)

    class MachineClock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
            return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)

    monkeypatch.setattr(api_clock, "datetime", MachineClock)
    app = create_app(Settings(db_url=settings.db_url, schema=world("main")))
    assert not hasattr(app.state, "clock")
    with TestClient(app, base_url="http://127.0.0.1:8177") as client:
        home = client.get("/api/home").json()
        today = client.get("/api/today").json()
    assert (home["date"], home["weekday"]) == ("2026-11-14", "Saturday")
    assert today["date"] == "2026-11-14"


def test_a_failing_import_drops_its_scratch_schema_and_keeps_the_error(
    settings: Settings, golden: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex H-299: the schema exists before the plan is built; an exception in planning or applying, or a refused
    plan, drops it, and the original error reaches the caller."""
    from projectzero.ops import scratch_import

    def exists(name: str) -> bool:
        with connect(settings.db_url) as c:
            q = "select 1 from information_schema.schemata where schema_name = %s"
            return c.execute(q.encode(), (name,)).fetchone() is not None

    class Boom(RuntimeError):
        pass

    def raising(*a: Any, **kw: Any) -> Any:
        raise Boom("invented planning failure")

    docs = importable(golden["worlds"]["gated"]["docs"])
    from projectzero.ops.db_check import _scratch_sql as real_scratch_sql  # what the helper forwards to

    for target, replacement, error in [
        ("build_plan", raising, Boom),
        ("apply_plan", raising, Boom),
        ("apply_plan", lambda *a, **kw: {"applied": False, "refused": "invented"}, ValueError),
    ]:
        # Codex H-301: the production RANDOM name is kept (concurrent runs never share one); a spy that forwards to
        # the real ``_scratch_sql`` captures the name the helper allocated
        allocated: list[str] = []

        def spy(name: str, _seen: list[str] = allocated) -> str:
            _seen.append(name)
            return real_scratch_sql(name)

        monkeypatch.setattr(scratch_import, "_scratch_sql", spy)
        monkeypatch.setattr(scratch_import, target, replacement)
        with pytest.raises(error):
            scratch_import.import_world(settings.db_url, docs)
        monkeypatch.undo()
        assert len(allocated) == 1 and re.fullmatch(r"pz_itest_[0-9a-f]{8}", allocated[0]), allocated
        assert not exists(allocated[0]), allocated[0]

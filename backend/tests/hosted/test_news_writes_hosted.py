"""Review 028b acceptance tests (plan revision 2, Codex H-249 / H-251) against the hosted project, in throw-away
scratch schemas, with invented names only (the shipped curated case aside).

* a confirm records ONE Validation outcome and ONE action line together; once confirmed, a repeat confirm, a reject
  and a not-enough answer the prior confirmation and append nothing; before a confirm, a reject appends every time;
* a failure after the Validation row leaves BOTH logs unchanged; concurrent confirms record one outcome;
* the seeding is stored by the first write, in its own transaction: a backcast on the case it just seeded succeeds
  (the stored event has the seed and the signal, one history row each, the refresh count includes it); a REFUSED first
  write on its own unseeded fixture leaves no seed, history, action or rest change;
* a miss audit writes the Validation audit (its note says "from News") and the action line; the GETs show them.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
from collections.abc import Iterator
from itertools import count
from typing import Any

import pytest
from fastapi.testclient import TestClient

from projectzero.api.app import create_app
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.news import store as news_store
from projectzero.ops.db_check import _scratch_sql
from projectzero.ops.parity_founder_calls import utc_instant
from projectzero.ops.parity_news import day, ev, src

pytestmark = pytest.mark.hosted
NOW = utc_instant("2026-11-12T10:00:00")
CASE = "nw-case-robco-unicorn-2026-10"  # the shipped curated case (resources/news_cases/robco.json)
ROUND = ev("nw-round", "Invented Alder Robotics", "Invented Alder Robotics raises €4M seed", "funding", day(3), "MEDIUM",
           rnd="seed", amount=4.0, sources=[src("Sifted", "round", day(3), "Invented Alder Robotics raises €4M seed")])  # fmt: skip
MISS = ev("nw-miss", "Invented Birch Bio", "Invented Birch Bio raises €30M Series A", "funding", day(9), "HIGH",
          geo=["FR"], themes=["deeptech"], rnd="series a", amount=30.0)  # fmt: skip


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def _archive(conn: Any, schema: str, path: str, text: str) -> None:
    raw = text.encode("utf-8")
    conn.execute(f"insert into {schema}.legacy_documents (path, sha256, bytes, raw, parsed) values "
                 "(%s, %s, %s, %s, %s::jsonb)".encode(),
                 (path, hashlib.sha256(raw).hexdigest(), len(raw), raw, text if path.endswith(".json") else None))  # fmt: skip


@pytest.fixture
def make(settings: Settings) -> Iterator[Any]:
    made: list[str] = []

    def build(seeded: list[str] | None = None) -> tuple[TestClient, str]:
        name = f"pz_itest_{secrets.token_hex(4)}"
        with connect(settings.db_url, autocommit=True) as admin:
            admin.execute(re.sub(r"\bpz\b", name, _scratch_sql("pz")).encode())
        made.append(name)
        doc = {"events": {"nw-round": ROUND, "nw-miss": MISS}, "seeded": [CASE] if seeded is None else seeded}
        with transaction(settings.db_url) as conn:
            _archive(conn, name, "news/events.json", json.dumps(doc, indent=1))
            conn.execute(
                f"select {name}.backfill_news(), {name}.backfill_news_files()".encode()
            )  # the importer's call (an existing installation)
        app = create_app(Settings(db_url=settings.db_url, schema=name))
        app.state.clock = lambda: NOW
        hexes = count()
        app.state.new_hex = lambda: f"{next(hexes):016x}"
        return TestClient(app, base_url="http://127.0.0.1:8177", raise_server_exceptions=False), name

    yield build
    for name in made:
        with connect(settings.db_url, autocommit=True) as admin:
            admin.execute(f"drop schema if exists {name} cascade".encode())


def _logs(settings: Settings, schema: str) -> tuple[list[str], list[str]]:
    with transaction(settings.db_url) as conn:
        actions = [
            r[0] for r in conn.execute(f"select line from {schema}.news_actions order by seq".encode()).fetchall()
        ]
        validation = [
            r[0] for r in conn.execute(f"select line from {schema}.validation_log order by seq".encode()).fetchall()
        ]
    return actions, validation


def _state(settings: Settings, schema: str) -> tuple[Any, ...]:
    with transaction(settings.db_url) as conn:
        q = (f"select (select count(*) from {schema}.news_events), (select count(*) from {schema}.news_event_history), "
             f"(select count(*) from {schema}.news_actions), (select body::text from {schema}.news_events_rest)")  # fmt: skip
        return tuple(conn.execute(q.encode()).fetchone() or ())


def test_the_decision_matrix_and_atomic_pairs(settings: Settings, make: Any) -> None:
    c, schema = make()
    assert (
        c.post("/api/news/outcome", json={"event_id": "nw-round", "decision": "reject"}).json()["decision"] == "reject"
    )
    r = c.post("/api/news/outcome", json={"event_id": "nw-round", "decision": "confirm"})
    assert r.status_code == 200 and r.json()["outcome_id"].startswith("oc-"), r.text
    first = r.json()
    actions, validation = _logs(settings, schema)
    assert [json.loads(a)["decision"] for a in actions] == ["reject", "confirm"]
    assert len(validation) == 1 and json.loads(validation[0])["note"].startswith("confirmed from News: ")
    assert list(json.loads(actions[1])) == sorted(json.loads(actions[1]))  # the old outcome_decision line: sorted
    for decision in ("confirm", "reject", "not_enough"):  # once confirmed: the prior confirmation, nothing appended
        again = c.post("/api/news/outcome", json={"event_id": "nw-round", "decision": decision}).json()
        assert again["already"] is True and again["outcome_id"] == first["outcome_id"]
    assert _logs(settings, schema) == (actions, validation)
    for bad, error in (({"event_id": "nw-round", "decision": "maybe"}, "decision must be confirm, reject or not_enough"),
                       ({"event_id": "nw-none", "decision": "confirm"}, "no such news event")):  # fmt: skip
        r = c.post("/api/news/outcome", json=bad)
        assert (r.status_code, r.json()) == (400, {"ok": False, "error": error})
    assert _logs(settings, schema) == (actions, validation)


def test_a_failure_after_the_validation_row_leaves_both_logs_unchanged(
    settings: Settings, make: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, schema = make()

    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("invented failure after the Validation row")

    monkeypatch.setattr(news_store, "append_action", boom)
    assert c.post("/api/news/outcome", json={"event_id": "nw-round", "decision": "confirm"}).status_code == 500
    assert _logs(settings, schema) == ([], [])


def test_concurrent_confirms_record_one_outcome(settings: Settings, make: Any) -> None:
    c, schema = make()
    codes: list[int] = []

    def post() -> None:
        codes.append(c.post("/api/news/outcome", json={"event_id": "nw-round", "decision": "confirm"}).status_code)

    threads = [threading.Thread(target=post) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    actions, validation = _logs(settings, schema)
    assert codes == [200] * 4 and len(actions) == 1 and len(validation) == 1


def test_the_first_write_stores_the_seed_it_needs(settings: Settings, make: Any) -> None:
    c, schema = make(seeded=[])  # an existing installation whose curated case was never stored
    assert c.get("/api/news/refresh_status").json()["events_total"] == 2
    signal = {
        "event_id": CASE,
        "date": "2019-05",
        "url": "https://evidence.invented.example/lab",
        "text": "Invented lab note",
    }
    r = c.post("/api/news/backcast", json=signal)
    assert r.status_code == 200, r.text
    with transaction(settings.db_url) as conn:
        rec = conn.execute(f"select record from {schema}.news_events where event_id = %s".encode(), (CASE,)).fetchone()
        history = conn.execute(f"select action from {schema}.news_event_history order by id".encode()).fetchall()
    assert rec is not None and rec[0]["curated"] is True
    assert [s.get("text") for s in rec[0]["backcast"]][-1] == "Invented lab note"  # the seed AND the signal
    assert [h[0] for h in history] == ["seed", "backcast"]
    assert c.get("/api/news/refresh_status").json()["events_total"] == 3  # the persisted seed is counted
    assert json.loads(_state(settings, schema)[3])["seeded"] == [CASE]
    c.post("/api/news/backcast", json={**signal, "text": "Invented second note"})
    with transaction(settings.db_url) as conn:
        n = conn.execute(f"select count(*) from {schema}.news_event_history where action = 'seed'".encode()).fetchone()
        conn.execute(f"select {schema}.backfill_news()".encode())  # a rerun keeps the edits
        kept = conn.execute(f"select record from {schema}.news_events where event_id = %s".encode(), (CASE,)).fetchone()
    assert n is not None and n[0] == 1  # seeded once
    assert kept is not None and [s.get("text") for s in kept[0]["backcast"]][-2:] == [
        "Invented lab note",
        "Invented second note",
    ]


def test_a_refused_first_write_leaves_no_seed(settings: Settings, make: Any) -> None:
    c, schema = make(seeded=[])  # its own unseeded fixture (Codex H-251)
    before = _state(settings, schema)
    r = c.post(
        "/api/news/backcast",
        json={"event_id": CASE, "date": "next spring", "url": "https://evidence.invented.example/x"},
    )
    assert (r.status_code, r.json()["error"]) == (400, "date as YYYY, YYYY-MM or YYYY-MM-DD")
    assert _state(settings, schema) == before  # no seed, no history, no action, the rest unchanged
    assert c.get("/api/news/refresh_status").json()["events_total"] == 2


def test_a_miss_audit_writes_the_validation_audit_and_the_action(settings: Settings, make: Any) -> None:
    c, schema = make()
    r = c.post("/api/news/audit_miss", json={"event_id": "nw-miss"})
    assert r.status_code == 200, r.text
    audit = r.json()["audit"]
    actions, validation = _logs(settings, schema)
    assert json.loads(validation[0])["id"] == audit["id"] and "from News" in audit["note"]
    assert json.loads(actions[0]) == {"kind": "miss_audit", "event_id": "nw-miss", "audit_id": audit["id"],
                                      "at": "2026-11-12T10:00:00"}  # fmt: skip
    assert [m["company"] for m in c.get("/api/validation").json()["misses"]] == ["Invented Birch Bio"]
    story = next(s for s in c.get("/api/news").json()["misses"] if s["event_id"] == "nw-miss")
    assert story["audit_id"] == audit["id"]

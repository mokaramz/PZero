"""Review 027b acceptance tests (plan revision 2, Codex H-233 / H-235) against the hosted project, in throw-away scratch
schemas, with invented names only.

* each write appends exactly its rows to ``validation_log`` (an outcome one, a confirmed import one per usable row),
  stored as the old sorted line; the answer's entry keeps the insertion order; the next GET shows it;
* a refusal (400, the old text) writes nothing; a retraction withdraws its target from the GET;
* concurrent outcomes are all stored, and the GET reads them in ``seq`` order (commit order under the one lock);
* a confirmed import that fails after its first insert publishes NO row; the retry appears in input order even though
  the failed attempt consumed sequence values;
* the packet mark logs the sha of the packet the page showed; a stale sha is a 409 and logs nothing.
"""

from __future__ import annotations

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
from projectzero.ops.db_check import _scratch_sql
from projectzero.ops.parity_founder_calls import utc_instant
from projectzero.validation import store, writes

pytestmark = pytest.mark.hosted
NOW = utc_instant("2026-11-12T10:00:00")
ROUND = {"company": "Invented Kestrel Robotics", "kind": "institutional_round", "event_date": "2026-11-02",
         "evidence_url": "https://invented.example/kestrel-seed", "note": "Invented seed round."}  # fmt: skip
CSV = (
    "name,first seen\nInvented Heron Labs,2026-10-03\nInvented Plover Systems,2026-10-09\nInvented Godwit,2099-01-01\n"
)


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture
def make(settings: Settings) -> Iterator[Any]:
    made: list[str] = []

    def build() -> tuple[TestClient, str]:
        name = f"pz_itest_{secrets.token_hex(4)}"
        with connect(settings.db_url, autocommit=True) as admin:
            admin.execute(re.sub(r"\bpz\b", name, _scratch_sql("pz")).encode())
        made.append(name)
        app = create_app(Settings(db_url=settings.db_url, schema=name))
        app.state.clock = lambda: NOW
        hexes = count()
        app.state.new_hex = lambda: f"{next(hexes):016x}"
        return TestClient(app, base_url="http://127.0.0.1:8177", raise_server_exceptions=False), name

    yield build
    for name in made:
        with connect(settings.db_url, autocommit=True) as admin:
            admin.execute(f"drop schema if exists {name} cascade".encode())


def _rows(settings: Settings, schema: str) -> list[tuple[int, str, str, str]]:
    with transaction(settings.db_url) as conn:
        return conn.execute(
            f"select seq, log, line, source from {schema}.validation_log order by seq".encode()
        ).fetchall()


def test_an_outcome_appends_one_sorted_line_and_a_refusal_writes_nothing(settings: Settings, make: Any) -> None:
    c, schema = make()
    r = c.post("/api/validation/outcome", json=ROUND)
    assert r.status_code == 200, r.text
    entry = r.json()["entry"]
    assert list(entry)[:4] == ["id", "recorded_at", "recorded_by", "company"]  # the answer: insertion order
    assert entry["recorded_at"] == "2026-11-12T10:00:00" and entry["id"].startswith("oc-")
    rows = _rows(settings, schema)
    assert [(log, src) for _seq, log, _line, src in rows] == [("outcomes", "app")]
    assert rows[0][2] == json.dumps(entry, ensure_ascii=False, sort_keys=True)  # the stored line: the old sorted dump
    assert [o["id"] for o in c.get("/api/validation").json()["outcomes"]] == [entry["id"]]
    for bad, error in (({**ROUND, "event_date": "2099-01-01"}, "event_date is in the future"),
                       ({**ROUND, "evidence_url": ""}, "a real-world outcome needs an evidence URL"),
                       ({**ROUND, "kind": "rumour"}, "unknown outcome kind 'rumour'")):  # fmt: skip
        r = c.post("/api/validation/outcome", json=bad)
        assert r.status_code == 400 and r.json()["ok"] is False and r.json()["error"].startswith(error), r.text
    assert len(_rows(settings, schema)) == 1


def test_a_retraction_and_the_audits(settings: Settings, make: Any) -> None:
    c, schema = make()
    oc = c.post("/api/validation/outcome", json=ROUND).json()["entry"]["id"]
    assert c.post("/api/validation/retract", json={"id": oc, "reason": "short"}).status_code == 400
    assert c.post("/api/validation/retract", json={"id": "oc-nothing", "reason": "invented wrong id"}).json() == {
        "ok": False, "error": "no such entry"}  # fmt: skip
    r = c.post("/api/validation/retract", json={"id": oc, "reason": "invented: recorded against the wrong company"})
    assert r.status_code == 200 and r.json()["entry"]["retracts"] == oc
    assert c.get("/api/validation").json()["outcomes"] == []  # withdrawn; the history stays in the log
    miss = {"type": "miss", "company": "Invented Dunlin Robotics", "why_missed": "source_not_covered"}
    fp = {"type": "false_positive", "company": "Invented Avocet AG", "causes": []}
    assert c.post("/api/validation/audit", json=miss).status_code == 200
    assert c.post("/api/validation/audit", json=fp).status_code == 400  # at least one cause
    logs = [(log, json.loads(line).get("type") or (json.loads(line).get("retracts") and "rx"))
            for _s, log, line, _src in _rows(settings, schema)]  # fmt: skip
    assert logs == [("outcomes", None), ("outcomes", "rx"), ("audits", "miss")]
    body = c.get("/api/validation").json()
    assert [m["company"] for m in body["misses"]] == ["Invented Dunlin Robotics"]


def test_concurrent_outcomes_are_all_stored_and_read_in_sequence_order(settings: Settings, make: Any) -> None:
    c, schema = make()
    answers: list[str] = []

    def post(i: int) -> None:
        r = c.post("/api/validation/outcome", json={**ROUND, "company": f"Invented Kestrel {i}"})
        assert r.status_code == 200, r.text
        answers.append(r.json()["entry"]["id"])

    threads = [threading.Thread(target=post, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    rows = _rows(settings, schema)
    by_seq = [json.loads(line)["id"] for _s, _log, line, _src in rows]
    assert sorted(by_seq) == sorted(answers) and len(by_seq) == 5
    assert [o["id"] for o in c.get("/api/validation").json()["outcomes"]] == by_seq  # the read order is seq order


def test_a_failed_import_publishes_nothing_and_the_retry_keeps_input_order(
    settings: Settings, make: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, schema = make()
    body = {"system": "Invented DB", "csv": CSV, "confirm": True}
    real_append = store.append

    def failing(conn: Any, schema_: str, rows: Any) -> int:
        rows = list(rows)
        real_append(conn, schema_, rows[:1])  # the first row is inserted (its seq consumed) ...
        raise RuntimeError("invented failure after the first insert")  # ... then the transaction fails

    monkeypatch.setattr(store, "append", failing)
    assert c.post("/api/validation/benchmark_import", json=body).status_code == 500
    assert _rows(settings, schema) == []  # nothing published
    monkeypatch.setattr(store, "append", real_append)
    preview = c.post("/api/validation/benchmark_import", json={**body, "confirm": False}).json()
    assert (preview["rows"], preview["usable"], preview["skipped"], preview["imported"]) == (3, 2, 1, False)
    assert _rows(settings, schema) == []  # a preview writes nothing
    r = c.post("/api/validation/benchmark_import", json=body)
    assert r.status_code == 200 and r.json()["imported"] is True
    rows = _rows(settings, schema)
    assert [json.loads(line)["company"] for _s, _log, line, _src in rows] == ["Invented Heron Labs",
                                                                               "Invented Plover Systems"]  # fmt: skip
    seqs = [s for s, *_ in rows]
    assert seqs == sorted(seqs)  # ordered; consecutive values are not assumed (the failed attempt consumed some)
    bad = c.post("/api/validation/benchmark_import", json={**body, "csv": "name,date\nInvented A,2026-10-01,extra\n"})
    assert bad.status_code == 400 and bad.json()["error"].startswith(writes.CSV_UNREADABLE)
    assert len(_rows(settings, schema)) == 2


def test_the_packet_mark_logs_the_shown_sha_and_refuses_a_stale_one(settings: Settings, make: Any) -> None:
    c, schema = make()
    packet = c.get("/api/validation/scout_packet", params={"cycle": ""}).json()
    generated = writes.generated_at(packet["text"])
    stale = c.post("/api/validation/scout_packet", json={"cycle": "", "generated": generated, "sha": "0" * 16})
    assert stale.status_code == 409 and stale.json() == {"ok": False, "error": writes.STALE_PACKET}
    assert _rows(settings, schema) == []
    r = c.post("/api/validation/scout_packet", json={"cycle": "", "generated": generated, "sha": packet["sha"]})
    assert r.status_code == 200, r.text
    rows = _rows(settings, schema)
    assert [(log, json.loads(line)["sha"]) for _s, log, line, _src in rows] == [("scout_feedback", packet["sha"])]

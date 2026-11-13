"""Review 035b acceptance tests for machine triage (the cascade's runner, automatic triage, the retry, the lock),
against the hosted project in throw-away ``pz_itest_*`` schemas imported by the PRODUCTION importer. Invented names
only. The model is a paid ``FakeProvider`` behind the REAL gateway and the Postgres budget store; no network.

* one run at a time across the three triggers; a trigger without the lock recovers nothing;
* per-candidate commits survive a crash; an interrupted run is recovered by the lock holder (revision 3: its
  dispositions are final, the rest re-checked); two triggers racing after a crash: exactly one recovers;
* revision 2 / 3 with the provider PAUSED on an event: a KEEP during inference (then a crash), an absorption (then a
  crash), a changed card (then a crash), an operator decision, a KEEP transaction held open across the selection;
  each prints its post-recovery pending ids, attempt counts and provider calls (``[035b-paused]``);
* replacing an IMPORTED current row; a forced insert failure rolls back; the run id on every ledger row; the run cap;
* paid off: the job writes no run, Retry now reports the stop, Stage 0 still proposes; the skip rule: 0 calls;
* the proposal-only invariant over the whole schema; nothing written before the import; the scan's triage note;
* the 035a batch-confirm timing at 50, 200 and 500 candidates (``[035b-batch]``).
"""

from __future__ import annotations

import copy
import json
import re
import socket
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from projectzero.api.app import create_app
from projectzero.core import net
from projectzero.core.config import Settings
from projectzero.core.db import transaction
from projectzero.core.inference.providers import FakeProvider, ProviderError, Reply
from projectzero.dealflow.intake import postgres as intake_pg
from projectzero.dealflow.triage import auto, records, runner
from projectzero.dealflow.triage import decide as td
from projectzero.network.view import BERLIN
from projectzero.ops import parity_triage_cascade as ptc
from projectzero.ops import parity_triage_decide as ptd
from projectzero.ops.parity_validation import _fingerprint
from projectzero.ops.scratch_import import drop_schema, import_world

pytestmark = pytest.mark.hosted
RUN = "2026-11-13 09:00:00"
T0 = datetime(2026, 11, 13, 9, 5, tzinfo=BERLIN)
GOOD = {"proposal": "RESEARCH", "entity_type": "VENTURE", "capital_stage": "PRE_COMPANY", "sector": "robots",
        "themes": [], "founders": [], "reasons": ["an invented reason"], "missing": [], "confidence": "medium"}  # fmt: skip
TRIAGE_TABLES = {"triage_proposals", "triage_runs", "triage_auto_runs", "triage_run_items", "triage_retry_state",
                 "model_ledger", "model_reservations", "model_cache"}  # fmt: skip
OBSERVED: dict[str, Any] = {}


class Crash(BaseException):
    """An injected process death: not an ``Exception``, so nothing in the app catches it."""


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture(autouse=True)
def only_the_database(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No live network: the system resolver answers only the database's host."""
    db_host = urlsplit(settings.db_url).hostname or ""
    real = socket.getaddrinfo

    def guarded(host: Any, *a: Any, **k: Any) -> Any:
        if host != db_host:
            raise AssertionError(f"the network was used: {host}")
        return real(host, *a, **k)

    monkeypatch.setattr(socket, "getaddrinfo", guarded)
    monkeypatch.setattr(net, "default_resolver", lambda host: (_ for _ in ()).throw(AssertionError(host)))
    yield


@pytest.fixture
def world(settings: Settings) -> Iterator[Callable[..., str]]:
    made: list[str] = []

    def build(docs: dict[str, Any]) -> str:
        name = import_world(settings.db_url, copy.deepcopy(docs))
        made.append(name)
        return name

    yield build
    for name in made:
        drop_schema(settings.db_url, name)


def cand(n: int, desc: str | None = None, run: str = RUN, **kw: Any) -> dict[str, Any]:
    cid = f"t{n:02d}"
    return {"id": cid, "name": f"Invented {cid.upper()} Robotics", "source": "Invented Feed", "source_id": "fx-feed",
            "description": desc if desc is not None else f"Invented {cid.upper()} Robotics builds welding cells.",
            "discovery_tier": "announcement", "decision": "new", "notes": "", "geo": ["DE"], "country": "DE",
            "first_seen": f"2026-10-{n:02d}", "source_url": f"https://feed.invented.example/news/{cid}",
            "first_seen_run": run, "last_observed": run, "run_id": run, **kw}  # fmt: skip


def stale(c: dict[str, Any], **kw: Any) -> dict[str, Any]:
    """An imported current proposal the scan's run will re-triage (its card changed since)."""
    return ptc._prop(c, "WATCH", input_sha="0" * 16, **kw)


def docs_of(cands: list[dict[str, Any]], props: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    return {"inbox.json": {"candidates": cands, "last_run": RUN, "reprocess_v": 3},
            "triage_proposals.json": {"version": 1, "proposals": props or {}}, **extra}  # fmt: skip


class Model:
    """A paid fake model: per candidate the reply (default ``GOOD``) and its reported cost; ``pause(cid)`` stops the
    provider inside that candidate's call until ``resume``; ``calls`` counts the provider calls per candidate."""

    def __init__(self, usd: float = 0.0001, replies: dict[str, list[Any]] | None = None) -> None:
        self.usd = usd
        self.replies = replies or {}
        self.calls: Counter[str] = Counter()
        self.pauses: dict[str, tuple[threading.Event, threading.Event]] = {}
        self.provider = FakeProvider(self._respond, paid=True, name="deepinfra")

    def pause(self, cid: str) -> tuple[threading.Event, threading.Event]:
        self.pauses[cid] = (threading.Event(), threading.Event())
        return self.pauses[cid]

    def _respond(self, messages: list[dict[str, str]], model: str) -> Any:
        m = re.search(r"/news/(t\d+)", messages[-1]["content"])
        cid = m.group(1) if m else "?"
        self.calls[cid] += 1
        if cid in self.pauses:
            entered, resume = self.pauses.pop(cid)
            entered.set()
            assert resume.wait(60), "the test never resumed the provider"
        queue = self.replies.get(cid)
        out = queue.pop(0) if queue else GOOD
        if isinstance(out, ProviderError):
            raise out
        text = json.dumps(out) if isinstance(out, dict) else str(out)
        return Reply(text=text, usage={"prompt_tokens": 100, "completion_tokens": 50, "estimated_cost": self.usd},
                     reported_usd=self.usd, model=model)  # fmt: skip


def deps(model: Model, *, paid: bool = True, hooks: runner.Hooks | None = None, at: datetime = T0) -> auto.Deps:
    gw = {"env": {"PZ_AI_PAID": "on"} if paid else {}, "providers": {"deepinfra": model.provider},
          "clock": lambda: at, "sleep": lambda s: None}  # fmt: skip
    return auto.Deps(gateway_kw=gw, clock=lambda: at, env={}, hooks=hooks)


def crash_after(cid_or_n: str | int) -> runner.Hooks:
    seen = [0]

    def after(cid: str, disposition: str) -> None:
        seen[0] += 1
        if cid == cid_or_n or seen[0] == cid_or_n:
            raise Crash(f"injected after {cid} ({disposition})")

    return runner.Hooks(after_commit=after)


def in_thread(fn: Callable[[], Any]) -> tuple[threading.Thread, dict[str, Any]]:
    out: dict[str, Any] = {}

    def body() -> None:
        try:
            out["value"] = fn()
        except Crash as e:
            out["crash"] = str(e)

    t = threading.Thread(target=body, daemon=True)
    t.start()
    return t, out


def q(settings: Settings, schema: str, query: str, params: Any = ()) -> list[tuple[Any, ...]]:
    with transaction(settings.db_url) as conn:
        return conn.execute(query.replace("{s}", schema).encode(), params).fetchall()


def runs(settings: Settings, schema: str) -> list[dict[str, Any]]:
    with transaction(settings.db_url) as conn:
        return records.auto_runs(conn, schema)["runs"]


def retry(settings: Settings, schema: str) -> dict[str, Any]:
    with transaction(settings.db_url) as conn:
        return records.retry_state(conn, schema, records.aliases(conn, schema))


def current(settings: Settings, schema: str, cid: str) -> list[tuple[Any, ...]]:
    return q(settings, schema, "select status, proposal, run_id from {s}.triage_proposals where candidate_id = %s and "
             "is_current", (cid,))  # fmt: skip


def dispositions(settings: Settings, schema: str) -> dict[str, str]:
    return {
        str(r[0]): str(r[1]) for r in q(settings, schema, "select candidate_id, disposition from {s}.triage_run_items")
    }


def client_of(settings: Settings, schema: str, model: Model, paid: bool = True) -> TestClient:
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    app.state.clock = lambda: T0
    app.state.triage_gateway_kw = deps(model, paid=paid).gateway_kw
    app.state.triage_env = {}
    app.state.triage_wait = True
    return TestClient(app, base_url="http://127.0.0.1:8177")


def observe(
    case: str, settings: Settings, schema: str, model: Model, rec: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The values Codex asked for after recovery: the pending ids (with their attempts) and the provider calls."""
    last = rec or runs(settings, schema)[-1]
    rs = retry(settings, schema)
    pend = [str(p["id"]) for p in (last.get("pending") or []) + (last.get("failed") or [])]
    seen = {"state": last.get("state"), "pending": pend, "attempts": {i: int((rs.get(i) or {}).get("attempts", 0)) for i in pend},
            "provider_calls": dict(sorted(model.calls.items())), "accounting": last.get("accounting")}  # fmt: skip
    OBSERVED[case] = seen
    print(f"\n[035b-paused] {case}: " + json.dumps(seen, ensure_ascii=False))
    return seen


# ------------------------------------------------------------------ one run at a time, recovery by the lock
def test_one_run_at_a_time_across_the_three_triggers(settings: Settings, world: Callable[..., str]) -> None:
    schema = world(docs_of([cand(1)]))
    model = Model()
    holder = records.take_lock(settings.db_url, schema)  # another session's run
    try:
        assert auto.after_scan(settings.db_url, schema, RUN, deps(model)) == {
            "started": False,
            "reason": auto.SCAN_BUSY,
        }
        assert auto.run_retry(settings.db_url, schema, deps=deps(model)) == {"started": False, "reason": auto.BUSY}
        with transaction(settings.db_url) as conn:  # something due, so the route reaches the lock
            records.put_retry(conn, schema, "t01", {"attempts": 1, "category": "RETRYABLE", "next_eligible": None})
        with client_of(settings, schema, model) as client:
            assert client.get("/api/deal-flow/triage_auto").json()["running"] is True
            r = client.post("/api/deal-flow/triage_retry", json={})
            assert r.status_code == 200 and r.json() == {"started": False, "reason": auto.BUSY_ROUTE}
    finally:
        records.release_lock(holder, schema)
    assert runs(settings, schema) == [] and model.calls == Counter()  # nothing ran, nothing was recorded
    with client_of(settings, schema, model) as client:
        assert client.get("/api/deal-flow/triage_auto").json()["running"] is False


def test_a_crash_keeps_each_committed_result_and_the_lock_holder_recovers(
    settings: Settings, world: Callable[..., str]
) -> None:
    cands = [cand(n) for n in range(1, 7)]
    schema = world(docs_of(cands))
    model = Model()
    t, out = in_thread(lambda: auto.after_scan(settings.db_url, schema, RUN, deps(model, hooks=crash_after(3))))
    t.join(120)
    assert "crash" in out
    assert [r[0] for r in q(settings, schema, "select state from {s}.triage_auto_runs")] == ["running"]
    assert sorted(dispositions(settings, schema)) == ["t01", "t02", "t03"]  # each commit survived the crash
    assert all(current(settings, schema, c)[0][0] == "proposed" for c in ("t01", "t02", "t03"))
    # a second session holding the lock: a trigger recovers NOTHING
    holder = records.take_lock(settings.db_url, schema)
    try:
        assert auto.run_retry(settings.db_url, schema, deps=deps(model))["reason"] == auto.BUSY
        assert q(settings, schema, "select state from {s}.triage_auto_runs")[0][0] == "running"
    finally:
        records.release_lock(holder, schema)
    note = auto.retry_note(auto.run_retry(settings.db_url, schema, deps=deps(model)))  # the job: recovery, nothing due
    assert note == auto.NOTHING
    (rec,) = runs(settings, schema)
    assert rec["state"] == "failed" and rec["note"] == auto.INTERRUPTED_NOTE
    assert rec["counts"] == {"RESEARCH": 3} and [p["id"] for p in rec["pending"]] == ["t04", "t05", "t06"]
    assert all(p["reason"] == auto.INTERRUPTED_REASON for p in rec["pending"]) and rec["accounting"]["balanced"]
    assert auto_rules_summary(rec).startswith(
        "Machine triage could not run — 3 processed (3 RESEARCH); 3 preserved for automatic retry because interrupted "
        "by an app restart"
    )
    assert dict(model.calls) == {"t01": 1, "t02": 1, "t03": 1}


def auto_rules_summary(rec: dict[str, Any]) -> str:
    from projectzero.dealflow.triage import auto_rules

    shown = auto_rules.plain(rec)  # type: ignore[no-untyped-call]
    return str(shown["summary"])


def test_two_triggers_racing_after_a_crash_one_recovers_and_nothing_is_lost(
    settings: Settings, world: Callable[..., str]
) -> None:
    cands = [cand(n) for n in range(1, 7)]
    schema = world(docs_of(cands))
    model = Model()
    t, out = in_thread(lambda: auto.after_scan(settings.db_url, schema, RUN, deps(model, hooks=crash_after(3))))
    t.join(120)
    assert "crash" in out and dict(model.calls) == {"t01": 1, "t02": 1, "t03": 1}
    entered, resume = model.pause("t04")  # the winner holds the lock inside its first call
    barrier = threading.Barrier(2)

    def trigger() -> dict[str, Any]:
        barrier.wait(30)
        return auto.after_scan(settings.db_url, schema, RUN, deps(model))

    (ta, a), (tb, b) = in_thread(trigger), in_thread(trigger)
    assert entered.wait(60)
    deadline = time.monotonic() + 60
    while not (("value" in a) or ("value" in b)) and time.monotonic() < deadline:
        time.sleep(0.05)
    loser = a if "value" in a else b
    assert loser["value"] == {"started": False, "reason": auto.SCAN_BUSY}
    resume.set()
    ta.join(120)
    tb.join(120)
    winner = b if loser is a else a
    rows = q(settings, schema, "select state, record::text from {s}.triage_auto_runs order by id")
    assert [r[0] for r in rows] == ["failed", "done"]  # the crashed run recovered ONCE, then the winner's own run
    recovered = json.loads(rows[0][1])
    assert recovered["note"] == auto.INTERRUPTED_NOTE and [p["id"] for p in recovered["pending"]] == [
        "t04",
        "t05",
        "t06",
    ]
    won = winner["value"]  # every id selected again; the three committed ones skipped by the rule (no call)
    assert (won["selected"], won["triaged"], won["unchanged_skipped"]) == (6, 3, 3)
    assert dict(model.calls) == {f"t0{n}": 1 for n in range(1, 7)}  # the three committed results: never called again
    observe("two_triggers_after_a_crash", settings, schema, model, recovered)


# ------------------------------------------------------------------ revision 2 / 3: the provider paused
def _paused(settings: Settings, schema: str, model: Model, cid: str, during: Callable[[], None],
            hooks: runner.Hooks | None = None) -> dict[str, Any]:  # fmt: skip
    entered, resume = model.pause(cid)
    t, out = in_thread(lambda: auto.after_scan(settings.db_url, schema, RUN, deps(model, hooks=hooks)))
    assert entered.wait(60), "the run never reached the paused candidate"
    during()
    resume.set()
    t.join(120)
    return out


def test_an_operator_decision_during_inference_wins(settings: Settings, world: Callable[..., str]) -> None:
    cs = [cand(1), cand(2), cand(3)]
    schema = world(docs_of(cs, {"t02": stale(cs[1])}))
    model = Model()
    lines: list[Any] = []

    def decide() -> None:
        with client_of(settings, schema, model) as client:
            r = client.post("/api/deal-flow/triage/decide", json={"id": "t02", "verdict": "WATCH", "mode": "override"})
            assert r.status_code == 200, r.text
        lines.extend(q(settings, schema, "select seq, entry::text from {s}.triage_decisions"))

    out = _paused(settings, schema, model, "t02", decide)
    rec = out["value"]
    assert dispositions(settings, schema)["t02"] == "decided_meanwhile"
    assert q(settings, schema, "select status from {s}.candidates where id = 't02'")[0][0] == "watch"
    assert q(settings, schema, "select seq, entry::text from {s}.triage_decisions") == lines  # the line unchanged
    assert current(settings, schema, "t02")[0][2] == "triage-20261001-080000-0f0f"  # the late result was not written
    assert "t02" not in [p["id"] for p in rec["pending"]] and rec["accounting"]["decided_meanwhile"] == 1
    observe("operator_decision_during_inference", settings, schema, model, rec)


def test_a_log_only_keep_during_inference_then_a_crash(settings: Settings, world: Callable[..., str]) -> None:
    cs = [cand(1), cand(2), cand(3), cand(4)]
    schema = world(docs_of(cs, {"t02": stale(cs[1])}))
    model = Model()

    def keep() -> None:
        with client_of(settings, schema, model) as client:
            r = client.post("/api/deal-flow/triage/decide", json={"id": "t02", "verdict": "KEEP", "mode": "override"})
            assert r.status_code == 200 and r.json()["open_keep"] is True, r.text

    out = _paused(settings, schema, model, "t02", keep, hooks=crash_after("t02"))
    assert "crash" in out
    keep_line = q(settings, schema, "select seq, entry::text from {s}.triage_decisions")
    assert dispositions(settings, schema) == {"t01": "proposed", "t02": "decided_meanwhile"}
    assert auto.retry_note(auto.run_retry(settings.db_url, schema, deps=deps(model))) == auto.NOTHING  # recovery
    (rec,) = runs(settings, schema)
    seen = observe("log_only_keep_then_crash", settings, schema, model, rec)
    assert "t02" not in seen["pending"] and seen["pending"] == ["t03", "t04"]
    assert q(settings, schema, "select status from {s}.candidates where id = 't02'")[0][0] == "new"
    assert q(settings, schema, "select seq, entry::text from {s}.triage_decisions") == keep_line
    assert model.calls["t02"] == 1  # no further call for the kept candidate


def test_an_absorption_during_inference_then_a_crash(settings: Settings, world: Callable[..., str]) -> None:
    cs = [cand(1), cand(2), cand(3), cand(9, run="2026-10-01 08:00:00")]
    schema = world(docs_of(cs, {"t02": stale(cs[1]), "t09": ptc._prop(cs[3], "RESEARCH")}))
    model = Model()

    def absorb() -> None:  # t02 merged into t09 meanwhile (its id now resolves to the survivor)
        q(settings, schema, "update {s}.candidate_aliases set candidate_id = 't09', reason = 'merge' "
          "where namespace = 'candidate' and alias_id = 't02' returning 1")  # fmt: skip

    out = _paused(settings, schema, model, "t02", absorb, hooks=crash_after("t02"))
    assert "crash" in out
    assert dispositions(settings, schema)["t02"] == "decided_meanwhile"
    assert auto.retry_note(auto.run_retry(settings.db_url, schema, deps=deps(model))) == auto.NOTHING
    (rec,) = runs(settings, schema)
    seen = observe("absorption_then_crash", settings, schema, model, rec)
    assert "t02" not in seen["pending"] and "t09" not in seen["pending"] and seen["pending"] == ["t03"]
    assert model.calls["t09"] == 0 and current(settings, schema, "t02")[0][2] == "triage-20261001-080000-0f0f"


def test_a_changed_card_during_inference_then_a_crash_stays_retryable(
    settings: Settings, world: Callable[..., str]
) -> None:
    cs = [cand(1), cand(2), cand(3)]
    schema = world(docs_of(cs, {"t02": stale(cs[1])}))
    model = Model()

    def change() -> None:
        q(settings, schema, "update {s}.candidates set legacy = jsonb_set(legacy, '{description}', "
          "to_jsonb('Invented T02 Robotics now builds welding cells for shipyards.'::text)) where id = 't02' returning 1")  # fmt: skip

    out = _paused(settings, schema, model, "t02", change, hooks=crash_after("t02"))
    assert "crash" in out and dispositions(settings, schema)["t02"] == "changed_meanwhile"
    auto.run_retry(settings.db_url, schema, deps=deps(model))  # recovery
    (rec,) = runs(settings, schema)
    seen = observe("changed_card_then_crash", settings, schema, model, rec)
    assert seen["pending"] == ["t02", "t03"] and seen["attempts"] == {"t02": 0, "t03": 0}
    assert current(settings, schema, "t02")[0][2] == "triage-20261001-080000-0f0f"  # not written
    nxt = auto.after_scan(settings.db_url, schema, "2026-11-13 10:00:00", deps(model, at=T0 + timedelta(hours=1)))
    assert nxt["state"] == "done" and nxt["selected"] == 2 and model.calls["t02"] == 2  # re-selected, re-triaged
    assert current(settings, schema, "t02")[0][:2] == ("proposed", "RESEARCH")


def test_a_keep_transaction_held_open_across_the_selection_is_caught_by_the_mark(
    settings: Settings, world: Callable[..., str]
) -> None:
    cs = [cand(1), cand(2), cand(3)]
    schema = world(docs_of(cs, {"t02": stale(cs[1])}))
    model = Model()
    conn = psycopg.connect(settings.db_url)
    try:  # the KEEP's request starts BEFORE the selection: its line (and its seq) exist, uncommitted
        assert td.decide(conn, schema, {"id": "t02", "verdict": "KEEP", "mode": "override"}, T0)["open_keep"]
        entered, resume = model.pause("t02")
        t, out = in_thread(lambda: auto.after_scan(settings.db_url, schema, RUN, deps(model)))
        assert entered.wait(60)  # the selection is done (t02 selected with the mark it saw) and t02 is in flight
        with transaction(settings.db_url) as c2:
            (sel,) = c2.execute(sql.SQL("select selection::text from {}.triage_auto_runs").format(
                sql.Identifier(schema))).fetchone()  # fmt: skip
        assert ["t02", 0] in json.loads(sel)
        conn.commit()  # the KEEP commits AFTER the selection
    finally:
        conn.close()
    resume.set()
    t.join(120)
    rec = out["value"]
    assert dispositions(settings, schema)["t02"] == "decided_meanwhile"
    assert "t02" not in [p["id"] for p in rec["pending"]] and rec["state"] == "done"
    observe("keep_transaction_across_the_selection", settings, schema, model, rec)


# ------------------------------------------------------------------ the write itself
def test_replacing_an_imported_current_row_and_a_failed_insert_rolls_back(
    settings: Settings, world: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    cs = [cand(1), cand(2)]
    schema = world(docs_of(cs, {"t01": stale(cs[0]), "t02": stale(cs[1])}))
    model = Model()
    real = records.write_proposal

    def broken(conn: psycopg.Connection[Any], s: str, entry: Any, at: datetime) -> int:
        if entry["candidate_id"] == "t02":
            conn.execute(sql.SQL("update {}.triage_proposals set is_current = false where candidate_id = 't02'").format(
                sql.Identifier(s)))  # fmt: skip
            raise RuntimeError("forced: the insert fails")
        return real(conn, s, entry, at)

    monkeypatch.setattr(records, "write_proposal", broken)
    rec = auto.after_scan(settings.db_url, schema, RUN, deps(model))
    rows = q(
        settings, schema, "select is_current, run_id from {s}.triage_proposals where candidate_id = 't01' order by id"
    )
    assert [r[0] for r in rows] == [False, True] and rows[1][1] == rec["triage_run_id"]  # one current: the new one
    assert current(settings, schema, "t02")[0][2] == "triage-20261001-080000-0f0f"  # rolled back: the imported row
    assert "t02" not in dispositions(settings, schema) and [p["id"] for p in rec["pending"]] == ["t02"]
    assert rec["stopped"].startswith("error: RuntimeError: forced")


def test_the_run_id_is_on_every_ledger_row(settings: Settings, world: Callable[..., str]) -> None:
    rej = {**GOOD, "proposal": "REJECT", "reject_basis": "NON_VENTURE", "reject_evidence": "builds welding cells"}
    cs = [cand(n) for n in range(1, 4)]
    schema = world(docs_of(cs))
    model = Model(replies={"t01": ["garbage", rej, "garbage", rej]})  # a schema retry on Flash AND on the veto
    rec = auto.after_scan(settings.db_url, schema, RUN, deps(model))
    rows = q(settings, schema, "select run_id, purpose, entity_ref from {s}.model_ledger order by id")
    assert {r[0] for r in rows} == {rec["triage_run_id"]}  # every row: Flash, the veto and both schema retries
    assert Counter(r[1] for r in rows) == Counter({"shadow_triage": 4, "shadow_triage_veto": 2})
    assert {r[2] for r in rows} == {"inbox:t01", "inbox:t02", "inbox:t03"}
    assert current(settings, schema, "t01")[0][:2] == ("proposed", "REJECT") and rec["state"] == "done"


def test_a_run_whose_spend_reaches_the_cap_stops_and_keeps_the_rest(
    settings: Settings, world: Callable[..., str]
) -> None:
    cs = [cand(n) for n in range(1, 6)]
    schema = world(docs_of(cs))
    model = Model(usd=0.2)  # $0.20 per reply: the fourth call no longer fits the $0.50 run cap
    rec = auto.after_scan(settings.db_url, schema, RUN, deps(model))
    assert rec["stopped"].startswith("budget_blocked: run cap reached for " + rec["triage_run_id"])
    assert rec["state"] == "partial" and rec["triaged"] == 3 and [p["id"] for p in rec["pending"]] == ["t04", "t05"]
    assert all(p["category"] == "BUDGET" and p["attempts"] == 0 for p in rec["pending"])
    assert "the configured AI budget limit was reached" in rec["pending"][0]["reason"]
    assert dict(model.calls) == {"t01": 1, "t02": 1, "t03": 1} and rec["usd"] == 0.6


# ------------------------------------------------------------------ paid off, the skip rule
def test_paid_off_the_job_writes_no_run_retry_now_reports_the_stop_and_stage0_proposes(
    settings: Settings, world: Callable[..., str]
) -> None:
    cs = [cand(1, desc="", name="(406)"), cand(2), cand(3, desc="", name="05.10.2026 14:00")]
    schema = world(docs_of(cs))
    model = Model()
    rec = auto.after_scan(settings.db_url, schema, RUN, deps(model, paid=False))
    assert (
        rec["state"] == "partial"
        and rec["counts"] == {"REJECT": 1}
        and [p["id"] for p in rec["pending"]] == ["t02", "t03"]
    )
    assert current(settings, schema, "t01")[0][:2] == ("proposed", "REJECT") and not current(settings, schema, "t02")
    assert "PZ_AI_PAID is not 'on'" in rec["pending"][0]["reason"] and model.calls == Counter()
    later = T0 + timedelta(minutes=30)
    note = auto.retry_note(auto.run_retry(settings.db_url, schema, deps=deps(model, paid=False, at=later)))
    assert note == "Paid AI is off — 2 candidate(s) waiting for machine triage." and len(runs(settings, schema)) == 1
    with client_of(settings, schema, model, paid=False) as client:
        assert client.post("/api/deal-flow/triage_retry", json={}).json() == {"started": True}
        status = client.get("/api/deal-flow/triage_auto").json()
        pending = client.get("/api/deal-flow/triage").json()["pending"]
    assert status["last"]["scan_run_id"].startswith("retry-now ") and status["last"]["state"] == "failed"
    assert (
        "paid AI is switched off (PZ_AI_PAID is not 'on')" in status["last"]["summary"]
        and status["retry"]["waiting"] == 2
    )
    assert pending["t02"].startswith("TRIAGE PENDING: paid AI is switched off (PZ_AI_PAID is not 'on')")
    assert model.calls == Counter()


def test_the_skip_rule_makes_no_call_on_the_imported_proposals(settings: Settings, world: Callable[..., str]) -> None:
    cs = [cand(n) for n in range(1, 5)]
    schema = world(docs_of(cs, {c["id"]: ptc._prop(c, "RESEARCH") for c in cs}))
    model = Model()
    rec = auto.after_scan(settings.db_url, schema, RUN, deps(model))
    assert rec["state"] == "done" and rec["unchanged_skipped"] == 4 and rec["triaged"] == 0 and model.calls == Counter()
    assert set(dispositions(settings, schema).values()) == {"unchanged_skipped"}
    assert (
        q(settings, schema, "select count(*) from {s}.triage_proposals where run_id <> 'triage-20261001-080000-0f0f'")[
            0
        ][0]
        == 0
    )
    assert q(settings, schema, "select count(*) from {s}.model_ledger")[0][0] == 0


# ------------------------------------------------------------------ invariants
def test_the_proposal_only_invariant_over_the_whole_schema(settings: Settings, world: Callable[..., str]) -> None:
    rej = {**GOOD, "proposal": "REJECT", "reject_basis": "NON_VENTURE", "reject_evidence": "builds welding cells"}
    cs = [cand(1), cand(2), cand(3, desc="", name="(406)"), cand(4)]
    schema = world(docs_of(cs, {"t04": ptc._prop(cs[3], "RESEARCH")}, **{"real_data.json": {"signals": [
        {"company": "Invented Conviction Co", "status": "new", "one_liner": "an invented record"}]}}))  # fmt: skip
    model = Model(replies={"t01": [rej, rej], "t02": [ProviderError("timeout", "timed out", dispatched=False)] * 3})
    with transaction(settings.db_url) as conn:
        before = _fingerprint(conn, schema)
    auto.after_scan(settings.db_url, schema, RUN, deps(model))
    auto.run_retry(settings.db_url, schema, force=True, deps=deps(model))
    with transaction(settings.db_url) as conn:
        after = _fingerprint(conn, schema)
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    assert changed and changed <= TRIAGE_TABLES, changed - TRIAGE_TABLES  # no decision, status, Conviction, score, ...
    assert q(settings, schema, "select count(*) from {s}.candidate_events")[0][0] == before["candidate_events"][0]


def test_nothing_is_written_before_the_import(
    settings: Settings, world: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = world(docs_of([cand(1)]))
    with transaction(settings.db_url) as conn:
        conn.execute(sql.SQL("delete from {}.documents where key = 'ops/legacy_import'").format(sql.Identifier(schema)))
        records.put_retry(conn, schema, "t01", {"attempts": 1, "category": "RETRYABLE", "next_eligible": None})
    real = intake_pg.ensure_intake_open

    def guarded(conn: psycopg.Connection[Any], s: str, *, live: str = "pz") -> None:
        real(conn, s, live=s)  # the production guard, pointed at this scratch name

    monkeypatch.setattr(intake_pg, "ensure_intake_open", guarded)
    with transaction(settings.db_url) as conn:
        before = _fingerprint(conn, schema)
    model = Model()
    out = auto.after_scan(settings.db_url, schema, RUN, deps(model))
    assert out["started"] is False and "legacy import" in out["reason"]
    with pytest.raises(intake_pg.IntakeClosedError):
        auto.run_retry(settings.db_url, schema, deps=deps(model))
    with client_of(settings, schema, model) as client:
        r = client.post("/api/deal-flow/triage_retry", json={})
        assert r.status_code == 409 and "legacy import" in r.json()["error"]
        assert client.get("/api/deal-flow/triage_auto").status_code == 200  # a read answers
    with transaction(settings.db_url) as conn:
        assert _fingerprint(conn, schema) == before
    assert model.calls == Counter()


def test_the_scan_starts_triage_after_it_committed_and_never_fails_because_of_it(
    settings: Settings, world: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.hosted.test_scan_hosted import DEFAULTS_OFF, SOURCES, feeds

    from projectzero.ops.parity_scan import FixtureTransport, fixture_resolver, item

    schema = world(
        {"sources.json": {"sources": [*SOURCES, *DEFAULTS_OFF]}, "inbox.json": {"candidates": [], "reprocess_v": 3}}
    )
    model = Model()
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    app.state.clock = lambda: T0
    app.state.dealflow_resolver = fixture_resolver
    app.state.dealflow_transport = FixtureTransport(feeds([item("Aurora Robotics")]))
    app.state.dealflow_scan_wait = True
    app.state.dealflow_scan_options = {"max_workers": 2}
    app.state.triage_gateway_kw = deps(model).gateway_kw
    app.state.triage_env = {}
    with TestClient(app, base_url="http://127.0.0.1:8177") as client:
        assert client.post("/api/deal-flow/find", json={"days": 7}).json() == {"started": True}
        job = client.get("/api/deal-flow/find_status").json()
        status = client.get("/api/deal-flow/triage_auto").json()
    assert job["running"] is False and job["result"]["new"] == 1 and "triage" not in job["result"]
    assert status["last"]["scan_run_id"] == job["result"]["run_id"] and status["last"]["state"] == "done"
    assert status["last"]["counts"] == {"RESEARCH": 1} and sum(model.calls.values()) == 1

    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(runner, "run", boom)
    app.state.dealflow_transport = FixtureTransport(feeds([item("Bravo Sensors")]))
    with TestClient(app, base_url="http://127.0.0.1:8177") as client:
        assert client.post("/api/deal-flow/find", json={"days": 7}).json() == {"started": True}
        job = client.get("/api/deal-flow/find_status").json()
        last = client.get("/api/deal-flow/triage_auto").json()["last"]
    assert job["result"]["new"] == 1 and not job["error"]  # the scan succeeded
    assert last["state"] == "failed" and "kept for an automatic retry" in last["pending"][0]["reason"]
    assert "exploded" not in last["summary"] and "RuntimeError" not in last["summary"] and "exploded" in last["stopped"]


# ------------------------------------------------------------------ 035a's batch confirm timing (plan revision 2)
@pytest.mark.parametrize("size", [50, 200, 500])
def test_the_batch_confirm_timing(settings: Settings, world: Callable[..., str], size: int) -> None:
    cands = [ptd._c(f"bt{n:04d}", f"Invented Batch {n:04d} Holdings", f"Invented Batch {n:04d} Holdings is a family "
                    "haulage business since 1952.") for n in range(size)]  # fmt: skip
    schema = world(docs_of(cands, {c["id"]: ptd._both(c) for c in cands}))
    ids = [c["id"] for c in cands]
    t0 = time.monotonic()
    with transaction(settings.db_url) as conn:
        out = td.batch_reject(conn, schema, {"ids": ids, "confirm": True}, T0)
    seconds = round(time.monotonic() - t0, 2)
    body = json.dumps(out)
    assert out["applied"] == size and out["skipped"] == {}
    assert q(settings, schema, "select count(*) from {s}.candidates where status = 'rejected'")[0][0] == size
    print("\n[035b-batch] " + json.dumps({"batch": size, "applied": out["applied"], "seconds": seconds,
                                         "answer_bytes": len(body), "per_candidate_ms": round(1000 * seconds / size, 1)}))  # fmt: skip


# ------------------------------------------------------------------ H-360
def test_retry_now_as_the_first_trigger_after_a_crash_recovers_before_it_answers(
    settings: Settings, world: Callable[..., str]
) -> None:
    """H-360 (1): a scan crashed after its selection was stored and before its first commit (no call, no retry
    entry). Retry now takes the lock and recovers FIRST: the run is finalized failed (the old heading), its ids
    pending with the old interrupted reason. Those ids hold no retry entry (the old ``recover_interrupted`` wrote none,
    and its reason is not retryable for the legacy fold), so nothing is due: the old synchronous "Nothing is waiting
    for a retry." The next scan re-selects them (they are pending) and triages them."""
    schema = world(docs_of([cand(1), cand(2), cand(3)]))
    model = Model()

    def die(cid: str) -> None:
        raise Crash(f"injected before {cid}")

    t, out = in_thread(
        lambda: auto.after_scan(settings.db_url, schema, RUN, deps(model, hooks=runner.Hooks(before_candidate=die)))
    )
    t.join(120)
    assert "crash" in out and model.calls == Counter() and dispositions(settings, schema) == {}
    assert [r[0] for r in q(settings, schema, "select state from {s}.triage_auto_runs")] == ["running"] and retry(
        settings, schema
    ) == {}
    with client_of(settings, schema, model) as client:
        r = client.post("/api/deal-flow/triage_retry", json={})
        assert r.status_code == 200 and r.json() == {"started": False, "reason": auto.NOTHING_ROUTE}
        status = client.get("/api/deal-flow/triage_auto").json()
        pending = client.get("/api/deal-flow/triage").json()["pending"]
    (rec,) = runs(settings, schema)
    assert rec["state"] == "failed" and rec["note"] == auto.INTERRUPTED_NOTE
    assert [p["id"] for p in rec["pending"]] == ["t01", "t02", "t03"] and rec["accounting"]["interrupted"] == 3
    assert status["running"] is False and status["last"]["summary"].startswith(
        "Machine triage could not run — 0 processed"
    )
    assert status["retry"] == {"waiting": 0, "next_try": None}
    assert pending == {c: "TRIAGE PENDING: " + auto.INTERRUPTED_REASON for c in ("t01", "t02", "t03")}
    seen = observe("retry_now_first_after_a_crash", settings, schema, model, rec)
    assert seen["attempts"] == {"t01": 0, "t02": 0, "t03": 0} and seen["provider_calls"] == {}
    nxt = auto.after_scan(settings.db_url, schema, "2026-11-13 10:00:00", deps(model, at=T0 + timedelta(hours=1)))
    assert (nxt["state"], nxt["selected"], nxt["triaged"]) == ("done", 3, 3) and dict(model.calls) == {
        "t01": 1,
        "t02": 1,
        "t03": 1,
    }
    OBSERVED["retry_now_first_after_a_crash"]["next_scan"] = {"selected": nxt["selected"], "calls": dict(model.calls)}
    print(
        "[035b-paused] retry_now_first_after_a_crash, the next scan: "
        + json.dumps(OBSERVED["retry_now_first_after_a_crash"]["next_scan"])
    )


def test_a_skip_is_rechecked_under_the_locks_a_card_edited_meanwhile_stays_pending(
    settings: Settings, world: Callable[..., str]
) -> None:
    """H-360 (2): the second candidate's card matches its proposal in the run's snapshot (a skip), and is edited
    during the first candidate's call. Its skip is re-checked under the locks: ``changed_meanwhile`` (no call, no
    final skip); after an interruption it is pending with its attempts unchanged."""
    cs = [cand(1), cand(2)]
    schema = world(docs_of(cs, {"t02": ptc._prop(cs[1], "RESEARCH")}))
    model = Model()

    def edit() -> None:
        q(settings, schema, "update {s}.candidates set legacy = jsonb_set(legacy, '{description}', "
          "to_jsonb('Invented T02 Robotics now builds welding cells for shipyards.'::text)) where id = 't02' returning 1")  # fmt: skip

    out = _paused(settings, schema, model, "t01", edit, hooks=crash_after("t02"))
    assert "crash" in out and dispositions(settings, schema) == {"t01": "proposed", "t02": "changed_meanwhile"}
    calls_before = dict(model.calls)
    assert calls_before == {"t01": 1}  # zero calls for t02 before recovery
    assert auto.retry_note(auto.run_retry(settings.db_url, schema, deps=deps(model))) == auto.NOTHING  # recovery
    (rec,) = runs(settings, schema)
    seen = observe("skip_rechecked_card_edited_meanwhile", settings, schema, model, rec)
    assert seen["pending"] == ["t02"] and seen["attempts"] == {"t02": 0} and rec.get("unchanged_skipped", 0) == 0
    assert current(settings, schema, "t02")[0][2] == "triage-20261001-080000-0f0f" and model.calls["t02"] == 0

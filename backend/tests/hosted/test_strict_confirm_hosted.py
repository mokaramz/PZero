"""Review 036a acceptance tests: a strict boolean ``confirm`` on every confirming write, through the HTTP routes,
against the hosted project in throw-away ``pz_itest_*`` schemas imported by the PRODUCTION importer from each view's
synthetic parity corpus. Invented names only. No model, no network.

Per gate: a supplied non-boolean ``confirm`` (``"false"``, ``1``, ``null``, ``0``, ``"true"``, ``[]``) is a 400 in
that route's own error shape and the schema's fingerprint (every table's rows) is unchanged; ``false`` and an absent
key give the route's existing not-confirmed answer and write nothing; ``true`` gives the existing success, which
writes where the route persists. The gates: Ecosystems adopt; Evaluator evidence (OPERATOR VERIFIED; PUBLIC SOURCED
FACT still needs no ``confirm``) and the IMQ trigger; the Founder Calls briefing (generated on demand, persists
nothing; a malformed value generates no briefing); Founder Radar's LinkedIn verification, identity confirmation,
identity verification, merge and the company fact's NESTED ``fact.confirm``; the Validation benchmark import.
Founder Radar's review keeps ``confirm`` as its list of proposal ids.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from projectzero.api.app import create_app
from projectzero.core.body import CONFIRM_REFUSAL
from projectzero.core.config import Settings
from projectzero.core.db import transaction
from projectzero.ecosystems import adopt, coverage
from projectzero.ecosystems.store import EcosystemsStore
from projectzero.founder_calls import core as founder_calls_core
from projectzero.founder_calls.catalog import LABEL
from projectzero.ops import parity_ecosystems as pe
from projectzero.ops import parity_evaluator as pv
from projectzero.ops import parity_founder_calls as pc
from projectzero.ops import parity_founder_radar as pr
from projectzero.ops.parity_founder_calls import utc_instant
from projectzero.ops.scratch_import import drop_schema, import_world

pytestmark = pytest.mark.hosted
MALFORMED: list[Any] = ["false", 1, None, 0, "true", []]
NOT_CONFIRMED: list[dict[str, Any]] = [{"confirm": False}, {}]  # merged into a body: false, then the key absent
BENCH = "name,first seen\nInvented Heron Labs,2026-10-03\nInvented Plover Systems,2026-10-09\n"


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture(scope="module")
def worlds(settings: Settings) -> Iterator[Callable[[str], str]]:
    """One imported scratch schema per view (built on first use, dropped at the end of the module)."""
    corpora: dict[str, Callable[[], dict[str, Any]]] = {
        "ecosystems": lambda: {k: v for k, v in pe.corpus().items() if k not in ("inbox.json", "real_data.json")},  # malformed by design
        "evaluator": pv.corpus, "founder_radar": pr.corpus,
        "founder_calls": lambda: {"founder_calls.json": pc.main_doc()},  # its full corpus holds deliberate blockers
        "validation": dict,
    }  # fmt: skip
    made: dict[str, str] = {}

    def get(view: str) -> str:
        if view not in made:
            made[view] = import_world(settings.db_url, copy.deepcopy(corpora[view]()))
        return made[view]

    yield get
    for name in made.values():
        drop_schema(settings.db_url, name)


CLOCKS = {"ecosystems": pe.CLOCK, "evaluator": pv.CLOCK, "founder_calls": pc.CLOCK, "founder_radar": pr.CLOCK,
          "validation": "2026-11-12T10:00:00"}  # fmt: skip


def client_of(settings: Settings, schema: str, view: str) -> TestClient:
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    now: datetime = utc_instant(CLOCKS[view])
    app.state.clock = lambda: now
    return TestClient(app, base_url="http://127.0.0.1:8177")


def fingerprint(settings: Settings, schema: str) -> dict[str, tuple[int, str]]:
    """Every table of the schema: its row count and an md5 over its rows' text, in a stable order."""
    with transaction(settings.db_url) as conn:
        tables = [r[0] for r in conn.execute(
            "select table_name from information_schema.tables where table_schema = %s and table_type = 'BASE TABLE' "
            "order by table_name", (schema,)).fetchall()]  # fmt: skip
        out: dict[str, tuple[int, str]] = {}
        for t in tables:
            q = sql.SQL("select count(*), md5(coalesce(string_agg(x::text, '|' order by x::text), '')) from {}.{} x")
            row = conn.execute(q.format(sql.Identifier(schema), sql.Identifier(t))).fetchone()
            assert row is not None
            out[t] = (int(row[0]), str(row[1]))
    return out


def refuses_malformed(
    settings: Settings, schema: str, c: TestClient, path: str, body: dict[str, Any], shape: Callable[[str], Any],
    nested: str = "",
) -> None:  # fmt: skip
    """Each malformed value: a 400 whose body is ``shape(CONFIRM_REFUSAL)``, and the fingerprint unchanged."""
    before = fingerprint(settings, schema)
    for value in MALFORMED:
        sent = copy.deepcopy(body)
        (sent[nested] if nested else sent)["confirm"] = value
        r = c.post(path, json=sent)
        assert (r.status_code, r.json()) == (400, shape(CONFIRM_REFUSAL)), (value, r.text)
    assert fingerprint(settings, schema) == before


def not_confirmed(
    settings: Settings, schema: str, c: TestClient, path: str, body: dict[str, Any], nested: str = ""
) -> list[tuple[int, Any]]:
    """``false`` then an absent key: the answers (expected equal), and the fingerprint unchanged."""
    before = fingerprint(settings, schema)
    answers = []
    for extra in NOT_CONFIRMED:
        sent = copy.deepcopy(body)
        target = sent[nested] if nested else sent
        target.pop("confirm", None)
        target.update(extra)
        r = c.post(path, json=sent)
        answers.append((r.status_code, r.json()))
    assert answers[0] == answers[1], answers
    assert fingerprint(settings, schema) == before
    return answers


def ok_error(msg: str) -> dict[str, Any]:
    return {"ok": False, "error": msg}


def error_only(msg: str) -> dict[str, Any]:
    return {"error": msg}


# ------------------------------------------------------------------ 1. Ecosystems adopt
def test_ecosystems_adopt(settings: Settings, worlds: Callable[[str], str]) -> None:
    schema = worlds("ecosystems")
    now = utc_instant(pe.CLOCK)
    with transaction(settings.db_url) as conn:
        inp = EcosystemsStore(conn, schema).inputs(now)
    cid = next(c["id"] for c in coverage.candidate_sources(inp) if adopt.adopt_plan(inp, c["id"], True).writes)
    path, body = "/api/ecosystems/coverage/adopt", {"id": cid}
    with client_of(settings, schema, "ecosystems") as c:
        refuses_malformed(settings, schema, c, path, body, ok_error)
        answers = not_confirmed(settings, schema, c, path, body)
        assert answers[0] == (200, ok_error("explicit confirmation required"))
        before = fingerprint(settings, schema)
        r = c.post(path, json={**body, "confirm": True})
        assert r.status_code == 200 and r.json()["ok"] is True and r.json()["source_id"], r.text
        assert "already" not in r.json()
    assert fingerprint(settings, schema) != before  # the adoption wrote


# ------------------------------------------------------------------ 2-3. Evaluator evidence and the IMQ trigger
def test_evaluator_operator_evidence(settings: Settings, worlds: Callable[[str], str]) -> None:
    schema = worlds("evaluator")
    path = "/api/evaluator/evidence"
    body = {"id": pv.LONG_ID, "claim_id": "cl-oldunknown", "kind": "operator", "note": "Checked with the founder"}
    with client_of(settings, schema, "evaluator") as c:
        refuses_malformed(settings, schema, c, path, body, ok_error)
        answers = not_confirmed(settings, schema, c, path, body)
        assert answers[0][0] == 200 and answers[0][1]["ok"] is False
        assert answers[0][1]["error"] == "explicit confirmation required" and "panel" in answers[0][1]
        before = fingerprint(settings, schema)
        r = c.post(path, json={**body, "confirm": True})
        assert r.status_code == 200 and r.json()["ok"] is True, r.text
        assert r.json()["claim"]["state"] == "OPERATOR VERIFIED"
        after = fingerprint(settings, schema)
        assert after != before
        # the PUBLIC SOURCED FACT branch still needs no ``confirm`` (unchanged behaviour)
        pub = {"id": pv.SHORT_ID, "claim_id": "cl-tieclaim01", "url": pv.URL, "label": "Invoices", "note": "Checked"}
        r = c.post(path, json=pub)
        assert r.status_code == 200 and r.json()["ok"] is True, r.text
        assert r.json()["claim"]["state"] == "PUBLIC SOURCED FACT"
    assert fingerprint(settings, schema) != after


def test_evaluator_imq_trigger(settings: Settings, worlds: Callable[[str], str]) -> None:
    schema = worlds("evaluator")
    path, body = "/api/conviction/imq_trigger", {k: v for k, v in pv.TRIGGER.items() if k != "confirm"}
    with client_of(settings, schema, "evaluator") as c:
        refuses_malformed(settings, schema, c, path, body, ok_error)
        answers = not_confirmed(settings, schema, c, path, body)
        assert answers[0] == (200, ok_error("explicit confirmation required"))
        before = fingerprint(settings, schema)
        r = c.post(path, json={**body, "confirm": True})
        assert r.status_code == 200 and r.json()["ok"] is True, r.text
        assert r.json()["trigger"]["fact"] == pv.TRIGGER["fact"]
    assert fingerprint(settings, schema) != before


# ------------------------------------------------------------------ 4. Founder Calls briefing (persists nothing)
def test_founder_calls_briefing(
    settings: Settings, worlds: Callable[[str], str], monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = worlds("founder_calls")
    real = founder_calls_core.briefing_markdown
    generated: list[Any] = []

    def counted(*args: Any, **kw: Any) -> Any:
        generated.append(args[1])
        return real(*args, **kw)

    monkeypatch.setattr(founder_calls_core, "briefing_markdown", counted)
    path, body = "/api/founder-calls/briefing", {"founder_id": pc.F1}
    before = fingerprint(settings, schema)
    with client_of(settings, schema, "founder_calls") as c:
        refuses_malformed(settings, schema, c, path, body, error_only)
        assert generated == []  # a malformed value generates no briefing
        answers = not_confirmed(settings, schema, c, path, body)
        assert answers[0] == (400, error_only("explicit confirmation required")) and generated == []
        r = c.post(path, json={**body, "confirm": True})
        assert r.status_code == 200 and set(r.json()) == {"markdown", "label"}, r.text
        assert r.json()["markdown"] and r.json()["label"] == LABEL
        assert generated == [pc.F1]
    assert fingerprint(settings, schema) == before  # nothing is stored in any case


# ------------------------------------------------------------------ 5-9. Founder Radar
RADAR_GATES: dict[str, tuple[str, dict[str, Any], str]] = {
    "linkedin": ("/api/founder-radar/action", {"id": pr.ILSA, "action": "linkedin", "verified": True,
                 "url": "https://www.linkedin.com/in/ilsa-marrowfield/", "fact": "profile matches", "founder": True,
                 "note": "checked"}, ""),
    "confirm_identity": ("/api/founder-radar/action", {"id": pr.RHEA, "action": "confirm_identity",
                         "name": "Rhea Quintaval", "company": "Larkspur Analytics", "url": pr.URL, "label": "team page",
                         "fact": "Rhea Quintaval, Co-Founder & CEO of Larkspur Analytics."}, ""),
    "verify_identity": ("/api/founder-radar/action", {"id": pr.TEODOR, "action": "verify_identity",
                        "url": "https://optics.example/teodor", "label": "lab page",
                        "fact": "Teodor Vanstrel heads the lab"}, ""),
    "merge": ("/api/founder-radar/action", {"id": pr.WENNA_A, "action": "merge", "other": pr.WENNA_B}, ""),
    "company_fact": ("/api/founder-radar/company", {"key": pr.LARK, "fact": {"field": "founded", "value": "2025",
                     "claim": "Larkspur Analytics was founded in 2025", "url": pr.NEWS, "label": "news"}}, "fact"),
}  # fmt: skip


@pytest.mark.parametrize("gate", list(RADAR_GATES))
def test_founder_radar(settings: Settings, worlds: Callable[[str], str], gate: str) -> None:
    schema = worlds("founder_radar")
    path, body, nested = RADAR_GATES[gate]
    with client_of(settings, schema, "founder_radar") as c:
        refuses_malformed(settings, schema, c, path, body, ok_error, nested)
        answers = not_confirmed(settings, schema, c, path, body, nested)
        status, answer = answers[0]
        assert status == 200 and answer["ok"] is False, answers
        if gate == "merge":
            assert answer["needs_confirmation"] is True
        before = fingerprint(settings, schema)
        sent = copy.deepcopy(body)
        (sent[nested] if nested else sent)["confirm"] = True
        r = c.post(path, json=sent)
        assert r.status_code == 200 and r.json()["ok"] is True, r.text
    assert fingerprint(settings, schema) != before


@pytest.mark.parametrize("gate", ["linkedin", "confirm_identity", "verify_identity", "merge"])
def test_founder_radar_checks_confirm_before_the_person_lookup(
    settings: Settings, worlds: Callable[[str], str], gate: str
) -> None:
    """H-371: an UNKNOWN person with a malformed ``confirm`` is the 400 (no write); with a boolean ``confirm`` it is
    still the old ``unknown person`` answer."""
    schema = worlds("founder_radar")
    path, body, _ = RADAR_GATES[gate]
    ghost = {**body, "id": "person-that-does-not-exist"}
    with client_of(settings, schema, "founder_radar") as c:
        refuses_malformed(settings, schema, c, path, ghost, ok_error)
        before = fingerprint(settings, schema)
        for value in (True, False):
            r = c.post(path, json={**ghost, "confirm": value})
            assert (r.status_code, r.json()) == (200, {"ok": False, "error": "unknown person"}), (value, r.text)
    assert fingerprint(settings, schema) == before


def test_founder_radar_company_checks_the_nested_confirm_first(
    settings: Settings, worlds: Callable[[str], str]
) -> None:
    """H-371: a malformed ``fact.confirm`` is the 400 even where an earlier refusal (no company key) would answer."""
    schema = worlds("founder_radar")
    path, body, _ = RADAR_GATES["company_fact"]
    keyless = {k: v for k, v in body.items() if k != "key"}
    with client_of(settings, schema, "founder_radar") as c:
        refuses_malformed(settings, schema, c, path, keyless, ok_error, "fact")
        r = c.post(path, json={**keyless, "fact": {**body["fact"], "confirm": True}})
        assert (r.status_code, r.json()) == (200, {"ok": False, "error": "company key required"}), r.text


def test_founder_radar_review_keeps_its_list(settings: Settings, worlds: Callable[[str], str]) -> None:
    """``radar_review``'s ``confirm`` is a list of proposal ids by design: an unknown company answers as before."""
    schema = worlds("founder_radar")
    with client_of(settings, schema, "founder_radar") as c:
        r = c.post("/api/founder-radar/review", json={"key": "dom:unknown.example", "confirm": ["status-01"]})
        assert r.status_code == 200 and r.json()["ok"] is False and r.json()["error"] != CONFIRM_REFUSAL, r.text


# ------------------------------------------------------------------ 10. Validation benchmark import
def test_validation_benchmark_import(settings: Settings, worlds: Callable[[str], str]) -> None:
    schema = worlds("validation")
    path, body = "/api/validation/benchmark_import", {"system": "Invented DB", "csv": BENCH}
    with client_of(settings, schema, "validation") as c:
        refuses_malformed(settings, schema, c, path, body, ok_error)
        answers = not_confirmed(settings, schema, c, path, body)
        assert answers[0][0] == 200 and answers[0][1]["imported"] is False and answers[0][1]["usable"] == 2
        before = fingerprint(settings, schema)
        r = c.post(path, json={**body, "confirm": True})
        assert r.status_code == 200 and r.json()["imported"] is True, r.text
    after = fingerprint(settings, schema)
    assert after["validation_log"][0] == before["validation_log"][0] + 2  # the two usable rows appended

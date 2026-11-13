"""Review 024 acceptance tests (Codex H-183 / H-184 and PORT_ORDER step 6, H-139) against the hosted project, in
throw-away scratch schemas.

The archive fixture is the parity corpus (invented names only): its sessions' INSERTION order differs from JSONB's
(JSONB sorts keys by length: the short id ``e9`` would come first), and the long id and the short id share the SAME
``created``, so the workspace's stable sort shows the original order.

* both import paths (every migration before 0015, the archive, then 0015; or 0015, the archive, then the backfill the
  importer calls): the ordered ids (compared as LISTS), a direct lookup, the workspace tie, Conviction's gate C through
  the shared reader, Founder Calls' ``is_conversation`` through the same reader; a new session survives a second
  backfill in last place;
* a public claim's evidence survives a reload; the company's verified facts (and the radar archive) are unchanged;
* ending a session is ONE transaction: a failure after the founder-call write leaves nothing written; two concurrent
  ends make one founder call;
* a refusal that changed nothing writes nothing; the why-now trigger: refusals write nothing, a success is visible on
  a fresh pipeline read with one ``imq_trigger`` event;
* writes are closed before the import in production.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from projectzero.api.app import create_app
from projectzero.conviction.inputs import load_inputs
from projectzero.conviction.operator import calls_for
from projectzero.conviction.pipeline import verified_facts
from projectzero.conviction.store import ConvictionStore
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.dealflow.ranking.names import slug as radar_slug
from projectzero.evaluator.store import EvaluationsStore
from projectzero.ops.db_check import MIGRATIONS, _scratch_sql
from projectzero.ops.parity_evaluator import (
    DECK,
    LATTICE,
    LONG_ID,
    MID_ID,
    SHORT_ID,
    TRIGGER,
    URL,
    evaluations,
    founder_calls_doc,
    radar_companies,
    signals,
)
from projectzero.ops.parity_founder_calls import call, utc_instant

pytestmark = pytest.mark.hosted
FILES = sorted(MIGRATIONS.glob("*.sql"))
M15 = next(p for p in FILES if "evaluator" in p.name)
NOW = utc_instant("2026-11-12T10:00:00")
LATTICE_SLUG = "invented-lattice-freight"
ORDER = [LONG_ID, MID_ID, SHORT_ID]
GATE_C = "C · unresolved contradiction: Traction: deck vs founder"


def _calls_doc() -> dict[str, Any]:
    """The corpus's Founder Calls file plus two calls an evaluator End wrote: one for the open short-id session
    (``ended`` empty: not a conversation) and one for the ended session with an answer (a conversation)."""
    doc = founder_calls_doc()
    co, fo = next(iter(doc["companies"])), next(iter(doc["founders"]))
    doc["calls"] = {
        "fc-call-fromshort": call("fc-call-fromshort", fo, co, "2026-10-01", "10:00",
                                  objective=f"Active Evaluator session {SHORT_ID}"),
        "fc-call-frommid": call("fc-call-frommid", fo, co, "2026-10-05", "11:00",
                                objective=f"Active Evaluator session {MID_ID}"),
    }  # fmt: skip
    return doc


ARCHIVES = {
    "evaluations.json": evaluations(),
    "radar_companies.json": radar_companies(),
    "founder_calls.json": _calls_doc(),
}


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def _make(settings: Settings, sql: str) -> str:
    name = f"pz_itest_{secrets.token_hex(4)}"
    with connect(settings.db_url, autocommit=True) as admin:
        admin.execute(re.sub(r"\bpz\b", name, sql).encode())
    return name


def _drop(settings: Settings, name: str) -> None:
    with connect(settings.db_url, autocommit=True) as admin:
        admin.execute(f"drop schema if exists {name} cascade".encode())


def _seed(settings: Settings, schema: str) -> None:
    """The byte-exact archives, the Founder Calls (0014) and Founder Radar (0016) backfills and the imported-style
    Conviction entries."""
    with transaction(settings.db_url) as conn:
        for path, doc in ARCHIVES.items():
            raw = json.dumps(doc, indent=1, ensure_ascii=False).encode("utf-8")
            conn.execute(f"insert into {schema}.legacy_documents (path, sha256, bytes, raw, parsed) values "
                         "(%s, %s, %s, %s, %s::jsonb)".encode(),
                         (path, hashlib.sha256(raw).hexdigest(), len(raw), raw, raw.decode("utf-8")))  # fmt: skip
        conn.execute(f"select {schema}.backfill_founder_calls()".encode())
        # review 026a moved the Radar company records into ``radar_companies`` (the archive keeps the top-level keys
        # only): seed them the way an import does, or the readers see no company (stale since 026a, found in 036a).
        # The "upgrade" path seeds before 0016 exists; 0016's own migration then backfills, as it does in production.
        exists = conn.execute(f"select to_regprocedure('{schema}.backfill_founder_radar()')".encode()).fetchone()
        if exists and exists[0] is not None:
            conn.execute(f"select {schema}.backfill_founder_radar()".encode())
        for r in signals():
            co = conn.execute(f"insert into {schema}.companies (name) values (%s) returning id".encode(),
                              (r["company"],)).fetchone()  # fmt: skip
            assert co is not None
            conn.execute(
                f"insert into {schema}.conviction_entries (company_id, slug, status, verified, scores, legacy) "
                "values (%s, %s, %s, %s, %s, %s)".encode(),
                (co[0], radar_slug(r["company"]), r.get("status") or "new", Jsonb(r.get("verified") or {}),
                 Jsonb(r.get("scores") or {}), Jsonb(r)),
            )  # fmt: skip


def _backfill(settings: Settings, schema: str) -> int:
    with transaction(settings.db_url) as conn:
        row = conn.execute(f"select {schema}.backfill_evaluations()".encode()).fetchone()
    assert row is not None
    return int(row[0])


def _app(settings: Settings, schema: str) -> TestClient:
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    app.state.clock = lambda: NOW
    return TestClient(app, base_url="http://127.0.0.1:8177")


def _q(settings: Settings, schema: str, query: str) -> list[tuple[Any, ...]]:
    with transaction(settings.db_url) as conn:
        return list(conn.execute(query.format(s=schema).encode()).fetchall())


def _lattice(c: TestClient) -> dict[str, Any]:
    r = c.get("/api/conviction/pipeline")
    assert r.status_code == 200, r.text
    return next(e for e in r.json()["signals"] if e["slug"] == LATTICE_SLUG)


@pytest.mark.parametrize("path", ["upgrade", "import"])
def test_the_session_mapping_survives_both_import_paths_and_a_retry(settings: Settings, path: str) -> None:
    if path == "upgrade":  # every migration before 0015, the archives, then 0015 (which runs the backfill)
        schema = _make(settings, "\n".join(p.read_text(encoding="utf-8") for p in FILES if p < M15))
        _seed(settings, schema)
        with connect(settings.db_url, autocommit=True) as admin:  # 0015 (its backfill), then every later migration
            for later in (p for p in FILES if p >= M15):
                admin.execute(re.sub(r"\bpz\b", schema, later.read_text(encoding="utf-8")).encode())
    else:  # a schema with 0015, then the archives and the backfill the importer calls
        schema = _make(settings, _scratch_sql("pz"))
        _seed(settings, schema)
        assert _backfill(settings, schema) == 3
    try:
        with transaction(settings.db_url) as conn:
            doc = EvaluationsStore(conn, schema).load()
            inp = load_inputs(conn, schema)
        assert doc is not None and list(doc) == ["version", "sessions"]  # the archive's top level, in order
        assert list(doc["sessions"]) == ORDER  # compared as a LIST: the archive's insertion order, not JSONB's
        assert doc["sessions"] == evaluations()["sessions"]
        talks = [c["id"] for c in calls_for({"slug": LATTICE_SLUG, "company": LATTICE}, inp.operator)]
        assert talks == ["fc-call-frommid"]  # Founder Calls' is_conversation, through the shared reader
        with _app(settings, schema) as c:
            r = c.get("/api/evaluator/session", params={"id": SHORT_ID})  # a direct lookup by id
            assert r.status_code == 200 and r.json()["session"]["id"] == SHORT_ID
            assert c.get("/api/evaluator/session", params={"id": "ev-nope"}).json() == {"error": "unknown session"}
            ws = c.get("/api/evaluator/sessions").json()
            assert [s["id"] for s in ws["sessions"]] == [MID_ID, LONG_ID, SHORT_ID]  # the tie keeps the archive order
            assert GATE_C in _lattice(c)["imq_eval"]["blockers"]  # Conviction's gate C, through the shared reader
            r = c.post("/api/evaluator/start", json={"subject": {"kind": "company", "slug": LATTICE_SLUG}})
            assert r.status_code == 200 and r.json()["ok"], r.text
            new_id = r.json()["id"]
        assert _backfill(settings, schema) == 0
        with transaction(settings.db_url) as conn:
            doc = EvaluationsStore(conn, schema).load()
        assert doc is not None and list(doc["sessions"]) == [*ORDER, new_id]  # the new session stays last
        assert _q(settings, schema, "select action from {s}.eval_events") == [("start",)]
    finally:
        _drop(settings, schema)


@pytest.fixture
def client(settings: Settings) -> Iterator[tuple[TestClient, str]]:
    schema = _make(settings, _scratch_sql("pz"))
    try:
        _seed(settings, schema)
        _backfill(settings, schema)
        with _app(settings, schema) as c:
            yield c, schema
    finally:
        _drop(settings, schema)


def _events(settings: Settings, schema: str) -> list[str]:
    return [r[0] for r in _q(settings, schema, "select action from {s}.eval_events order by id")]


def test_a_public_claims_evidence_survives_a_reload_and_the_verified_facts_are_unchanged(
    settings: Settings, client: tuple[TestClient, str]
) -> None:
    c, schema = client
    radar_before = _q(settings, schema, "select raw from {s}.legacy_documents where path = 'radar_companies.json'")
    facts_before = _verified_facts(settings, schema)
    sid = c.post("/api/evaluator/start", json={"subject": {"kind": "company", "slug": LATTICE_SLUG}}).json()["id"]
    facts_seen = c.get("/api/evaluator/session", params={"id": sid}).json()["session"]["context"]["research_facts"]
    ledger = c.post("/api/evaluator/deck", json={"id": sid, "text": DECK}).json()["session"]["ledger"]
    claim = next(x for x in ledger if "ARR of" in x["text"])
    r = c.post("/api/evaluator/evidence", json={"id": sid, "claim_id": claim["id"], "url": URL, "label": "Invoices",
                                                "note": "Checked"})  # fmt: skip
    assert r.status_code == 200 and r.json()["ok"], r.text
    reloaded = c.get("/api/evaluator/session", params={"id": sid}).json()["session"]
    stored = next(x for x in reloaded["ledger"] if x["id"] == claim["id"])
    assert [(e["kind"], e["url"], e["label"]) for e in stored["evidence"]] == [("public", URL, "Invoices")]
    assert reloaded["context"]["research_facts"] == facts_seen  # the company's verified facts are unchanged
    assert (
        _q(settings, schema, "select raw from {s}.legacy_documents where path = 'radar_companies.json'") == radar_before
    )
    assert _q(settings, schema, "select count(*) from {s}.documents where key = 'radar_companies.json'") == [(0,)]
    assert _verified_facts(settings, schema) == facts_before  # what Conviction's IMQ reads from research
    assert _events(settings, schema) == ["start", "deck", "evidence"]


def _verified_facts(settings: Settings, schema: str) -> dict[str, Any]:
    with transaction(settings.db_url) as conn:
        comps = load_inputs(conn, schema).imq.radar_companies
    lattice = next(v for v in comps.values() if v.get("name") == LATTICE)
    facts = verified_facts(lattice)
    assert facts  # the corpus has confirmed, sourced facts for this company
    return facts


def _end_state(settings: Settings, schema: str) -> tuple[Any, ...]:
    return (
        _q(settings, schema, "select status, attrs from {s}.eval_sessions order by pos"),
        _q(settings, schema, "select id from {s}.fc_calls order by pos"),
        _q(settings, schema, "select count(*) from {s}.fc_events"),
        _q(settings, schema, "select slug, attrs from {s}.conviction_entries order by slug"),
        _q(settings, schema, "select count(*) from {s}.conviction_events"),
        _events(settings, schema),
    )


def test_ending_a_session_is_one_transaction(
    settings: Settings, client: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    c, schema = client
    before = _end_state(settings, schema)

    def fail(*_: Any, **__: Any) -> int:  # after the session and the founder call were written in the transaction
        raise RuntimeError("injected after the founder-call write")

    monkeypatch.setattr(ConvictionStore, "write_records", fail)
    with pytest.raises(RuntimeError, match="injected"):
        c.post("/api/evaluator/end", json={"id": LONG_ID})
    assert _end_state(settings, schema) == before  # none of the three was written
    monkeypatch.undo()

    r = c.post("/api/evaluator/end", json={"id": LONG_ID})
    assert r.status_code == 200 and r.json()["ok"], r.text
    call_id = r.json()["ended"]["call_id"]
    assert call_id and _q(settings, schema, "select id from {s}.fc_calls order by pos")[-1] == (call_id,)
    assert _q(settings, schema, "select action from {s}.fc_events") == [("save",)]
    rows = _q(settings, schema, "select slug, action, detail from {s}.conviction_events")
    assert [(s, a) for s, a, _ in rows] == [(LATTICE_SLUG, "evaluator_end")] and rows[0][2]["evaluation"] == LONG_ID
    record = _q(settings, schema, f"select attrs->'record' from {{s}}.conviction_entries where slug = '{LATTICE_SLUG}'")
    assert "Resolve contradiction: Traction: deck vs founder" in record[0][0]["verify_list"]
    assert record[0][0]["evaluator_last"]  # the linked Conviction fields
    assert _events(settings, schema) == ["end"]
    again = c.post("/api/evaluator/end", json={"id": LONG_ID})  # already ended: no second side effect
    assert again.json()["ok"] and _events(settings, schema) == ["end"]
    assert len(_q(settings, schema, "select id from {s}.fc_calls")) == len(before[1]) + 1


def test_two_concurrent_ends_make_one_founder_call(settings: Settings, client: tuple[TestClient, str]) -> None:
    c, schema = client
    calls = len(_q(settings, schema, "select id from {s}.fc_calls"))
    codes: list[int] = []
    threads = [threading.Thread(target=lambda: codes.append(c.post("/api/evaluator/end", json={"id": LONG_ID}).status_code))
               for _ in range(2)]  # fmt: skip
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert codes == [200, 200]
    assert len(_q(settings, schema, "select id from {s}.fc_calls")) == calls + 1
    assert _events(settings, schema) == ["end"]
    assert _q(settings, schema, "select action from {s}.conviction_events") == [("evaluator_end",)]


def test_a_refusal_that_changed_nothing_writes_nothing(settings: Settings, client: tuple[TestClient, str]) -> None:
    c, schema = client
    state = _q(settings, schema, "select attrs from {s}.eval_sessions order by pos")
    for act, body, error in [("skip", {"id": LONG_ID, "qid": "q-nope"}, "unknown question"),
                             ("deck", {"id": "ev-nope", "text": "x"}, "unknown session"),
                             ("resolve", {"id": LONG_ID, "claim_id": "cl-nope"}, None)]:  # fmt: skip
        r = c.post(f"/api/evaluator/{act}", json=body)
        assert r.status_code == 200 and r.json()["ok"] is False, r.text
        if error:
            assert r.json()["error"] == error
    assert _events(settings, schema) == []
    assert _q(settings, schema, "select attrs from {s}.eval_sessions order by pos") == state
    first = c.post("/api/evaluator/next", json={"id": LONG_ID}).json()  # asks a new question: a real change
    assert first["ok"] and _events(settings, schema) == ["next"]
    again = c.post("/api/evaluator/next", json={"id": LONG_ID}).json()  # the same open question: nothing changes
    assert again["next"]["id"] == first["next"]["id"] and _events(settings, schema) == ["next"]


def test_the_why_now_trigger_refusals_write_nothing_and_a_success_reads_back(
    settings: Settings, client: tuple[TestClient, str]
) -> None:
    c, schema = client
    for bad in (dict(TRIGGER, date="2026-12-01"), dict(TRIGGER, kind="vibes"), dict(TRIGGER, confirm=False),
                dict(TRIGGER, slug="invented-nobody")):  # fmt: skip
        r = c.post("/api/conviction/imq_trigger", json=bad)
        assert r.status_code == 200 and r.json()["ok"] is False, r.text
    assert _q(settings, schema, "select count(*) from {s}.conviction_events") == [(0,)]
    assert "imq_trigger" not in _lattice(c)
    r = c.post("/api/conviction/imq_trigger", json=TRIGGER)
    assert r.status_code == 200 and r.json()["ok"], r.text
    seen = _lattice(c)  # a fresh pipeline read
    assert seen["imq_trigger"]["fact"] == TRIGGER["fact"] and seen["imq_trigger"]["date"] == TRIGGER["date"]
    assert not any(b.startswith("E · ") for b in seen["imq_eval"]["blockers"])  # its IMQ effect: timing established
    rows = _q(settings, schema, "select slug, action from {s}.conviction_events")
    assert rows == [(LATTICE_SLUG, "imq_trigger")]


def test_writes_are_closed_before_the_import_in_production(settings: Settings) -> None:
    with _app(settings, "pz") as c:
        r = c.post("/api/evaluator/next", json={"id": "ev-anything"})
        t = c.post("/api/conviction/imq_trigger", json={"slug": "x", "confirm": True})
    if r.status_code == 409:
        assert "after the legacy import" in r.json()["error"]
        assert t.status_code == 409
    else:  # the live import has happened: the boundary is open (an unknown session is the old 200 refusal)
        assert r.json() == {"ok": False, "error": "unknown session"}


@pytest.mark.parametrize("path", ["evaluations.json", "founder_calls.json"])
def test_a_bom_prefixed_archive_backfills_and_reads_back_in_order(settings: Settings, path: str) -> None:
    """Codex H-192: the optional UTF-8 BOM is skipped by the backfill and the reader alike; the bytes are kept."""
    from projectzero.founder_calls.store import FounderCallsStore

    coll = "sessions" if path == "evaluations.json" else "calls"
    doc = ARCHIVES[path]
    raw = b"\xef\xbb\xbf" + json.dumps(doc, indent=1, ensure_ascii=False).encode("utf-8")
    schema = _make(settings, _scratch_sql("pz"))
    try:
        with transaction(settings.db_url) as conn:
            conn.execute(f"insert into {schema}.legacy_documents (path, sha256, bytes, raw, parsed) values "
                         "(%s, %s, %s, %s, %s::jsonb)".encode(),
                         (path, hashlib.sha256(raw).hexdigest(), len(raw), raw, json.dumps(doc)))  # fmt: skip
            fn = "backfill_evaluations" if path == "evaluations.json" else "backfill_founder_calls"
            row = conn.execute(f"select {schema}.{fn}()".encode()).fetchone()
            assert row is not None and int(row[0]) > 0
        with transaction(settings.db_url) as conn:
            loaded = (EvaluationsStore if path == "evaluations.json" else FounderCallsStore)(conn, schema).load()
        assert loaded is not None and list(loaded) == list(doc)  # the archived top level, in order
        assert list(loaded[coll]) == list(doc[coll])
        assert _q(settings, schema, f"select raw from {{s}}.legacy_documents where path = '{path}'") == [(raw,)]
    finally:
        _drop(settings, schema)

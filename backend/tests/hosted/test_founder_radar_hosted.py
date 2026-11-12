"""Review 026a acceptance tests (plan revisions 2 / 3, Codex H-205 / H-207) against the hosted project, in throw-away
scratch schemas, invented names only.

* migration 0016 on both import paths: the companies and research records in the archive's order, each record's OWN
  key order (proposals / pages / pairings) kept by the ``json`` column, compared as LISTS, with the BOM; a retry keeps
  an edit; after a live write and a fresh read the inner order holds and the new key comes last;
* Conviction's IMQ inputs read radar companies through the one reader;
* the merge: one transaction (records, identifier transfer, events); stale Network writes against the LOSING id answer
  exactly as a never-existing id does and write nothing; the survivor owns the identifiers; the tombstone and its
  earlier events survive; a failure mid-transfer restores both people and every identifier's owner; a recommendation
  or an add that would reuse the merged id is an atomic 409.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from projectzero.api.app import create_app
from projectzero.conviction.inputs import load_documents
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.founder_radar.store import FounderRadarStore
from projectzero.network.people import columns_of, distinct_identifiers
from projectzero.network.store import PeopleStore, load_people
from projectzero.ops.db_check import MIGRATIONS, _scratch_sql
from projectzero.ops.parity_founder_calls import utc_instant

pytestmark = pytest.mark.hosted
FILES = sorted(MIGRATIONS.glob("*.sql"))
M16 = next(p for p in FILES if "founder_radar" in p.name)
NOW = utc_instant("2026-11-12T10:00:00")

COMPANIES = {"version": 1, "companies": {  # the LONG key first: JSONB would put the short one first
    "name:invented-longer-robotics": {"founder_refs": {}, "facts": [], "notes": "imported", "_dirty": True},
    "dom:a.example": {"description": "An invented company"},
}}  # fmt: skip
RESEARCH = {"domains": {"name:invented-longer-robotics": {
    "domain": "longer.example",
    "pages": {"https://longer.example/team-and-company": {"chars": 10}, "https://longer.example/": {"chars": 20}},
    "proposals": {"pr-zzzzzzzzzzzz": {"status": "pending", "field": "founded"}, "pr-a": {"status": "pending"}},
    "pairings": {"pr-zzzzzzzzzzzz": {"person": "p-x"}, "pr-a": {"person": "p-y"}},
    "history": [],
}}}  # fmt: skip


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def _exec(settings: Settings, sql_text: str, schema: str) -> None:
    with connect(settings.db_url, autocommit=True) as admin:
        admin.execute(re.sub(r"\bpz\b", schema, sql_text).encode())


def _drop(settings: Settings, schema: str) -> None:
    with connect(settings.db_url, autocommit=True) as admin:
        admin.execute(f"drop schema if exists {schema} cascade".encode())


def _archive(settings: Settings, schema: str, path: str, doc: Any, bom: bool = False) -> None:
    raw = (b"\xef\xbb\xbf" if bom else b"") + json.dumps(doc).encode("utf-8")
    with transaction(settings.db_url) as conn:
        conn.execute(f"insert into {schema}.legacy_documents (path, sha256, bytes, raw, parsed) values "
                     "(%s, %s, %s, %s, %s::jsonb)".encode(),
                     (path, hashlib.sha256(raw).hexdigest(), len(raw), raw, json.dumps(doc)))  # fmt: skip


def _backfill(settings: Settings, schema: str) -> int:
    with transaction(settings.db_url) as conn:
        row = conn.execute(f"select {schema}.backfill_founder_radar()".encode()).fetchone()
    assert row is not None
    return int(row[0])


def _loaded(settings: Settings, schema: str) -> tuple[Any, Any]:
    with transaction(settings.db_url) as conn:
        store = FounderRadarStore(conn, schema)
        return store.load_companies(), store.load_research()


def _check_order(companies: Any, research: Any) -> None:
    assert list(companies) == list(COMPANIES)  # the archived top level, in order
    assert list(companies["companies"]) == list(COMPANIES["companies"])  # compared as LISTS
    assert "_dirty" not in companies["companies"]["name:invented-longer-robotics"]  # decision (a)
    r = research["domains"]["name:invented-longer-robotics"]
    src = RESEARCH["domains"]["name:invented-longer-robotics"]
    assert list(r) == list(src)
    for k in ("pages", "proposals", "pairings"):
        assert list(r[k]) == list(src[k]), k  # the record's OWN key order, kept by the json column


@pytest.mark.parametrize("path", ["upgrade", "import"])
def test_the_radar_records_keep_their_order_on_both_paths_through_a_live_write(settings: Settings, path: str) -> None:
    schema = f"pz_itest_{secrets.token_hex(4)}"
    try:
        if path == "upgrade":  # every migration before 0016, the archives, then 0016 and later (its backfill)
            _exec(settings, "\n".join(p.read_text(encoding="utf-8") for p in FILES if p < M16), schema)
            _archive(settings, schema, "radar_companies.json", COMPANIES, bom=True)
            _archive(settings, schema, "radar_research.json", RESEARCH)
            for later in (p for p in FILES if p >= M16):
                _exec(settings, later.read_text(encoding="utf-8"), schema)
        else:
            _exec(settings, _scratch_sql("pz"), schema)
            _archive(settings, schema, "radar_companies.json", COMPANIES, bom=True)
            _archive(settings, schema, "radar_research.json", RESEARCH)
            assert _backfill(settings, schema) == 3
        companies, research = _loaded(settings, schema)
        _check_order(companies, research)
        with transaction(settings.db_url) as conn:  # a live write: an edited proposal, a new pairing, a new company
            store = FounderRadarStore(conn, schema)
            store.lock()
            new_research = json.loads(json.dumps(research))
            rec = new_research["domains"]["name:invented-longer-robotics"]
            rec["proposals"]["pr-a"]["status"] = "confirmed"
            rec["pairings"]["pr-new"] = {"person": "p-z"}
            assert store.write_records("research", research, new_research, "review", {"request": {}}) == [
                "name:invented-longer-robotics"
            ]
            new_companies = json.loads(json.dumps(companies))
            new_companies["companies"]["name:invented-new"] = {"notes": "new"}
            assert store.write_records("companies", companies, new_companies, "company", {}) == ["name:invented-new"]
            assert store.write_records("companies", new_companies, new_companies, "company", {}) == []  # (e)
        assert _backfill(settings, schema) == 0
        companies, research = _loaded(settings, schema)
        r = research["domains"]["name:invented-longer-robotics"]
        assert list(r["proposals"]) == ["pr-zzzzzzzzzzzz", "pr-a"] and r["proposals"]["pr-a"]["status"] == "confirmed"
        assert list(r["pairings"]) == ["pr-zzzzzzzzzzzz", "pr-a", "pr-new"]  # the new key last
        assert list(companies["companies"]) == [*COMPANIES["companies"], "name:invented-new"]
        with transaction(settings.db_url) as conn:
            docs = load_documents(conn, schema)
        assert docs["radar_companies.json"] == companies  # Conviction / the evaluator read the same records
        n = _q(settings, schema, "select entity, action from {s}.radar_events order by id")
        assert n == [("research", "review"), ("company", "company")]
    finally:
        _drop(settings, schema)


# ── the merge ─────────────────────────────────────────────────────────────────────────────────────────────────────
ADA = {"id": "p-ada-invented", "name": "Ada Invented", "provenance": "radar_detected", "orcid": "0000-0002-1825-0097",
       "openalex_id": "A5000000001", "aliases": ["ada i"]}  # fmt: skip
ADA2 = {
    "id": "p-ada-invented-2",
    "name": "Ada Invented",
    "provenance": "radar_detected",
    "patent_inventor_id": "INV-INVENTED-2",
    "aliases": ["ada two"],
}  # fmt: skip — one strong, one weak identifier
HOST = {"id": "p-host-invented", "name": "Host Invented", "provenance": "user_provided"}


def _q(settings: Settings, schema: str, query: str, params: Any = ()) -> list[tuple[Any, ...]]:
    with transaction(settings.db_url) as conn:
        return list(conn.execute(query.replace("{s}", schema).encode(), params).fetchall())


def _seed_people(settings: Settings, schema: str, people: list[dict[str, Any]]) -> None:
    raw = json.dumps({"people": people}).encode()
    with transaction(settings.db_url) as conn:
        conn.execute(f"insert into {schema}.legacy_documents (path, sha256, bytes, raw, parsed) values "
                     "(%s, %s, %s, %s, %s)".encode(),
                     ("people.json", hashlib.sha256(raw).hexdigest(), len(raw), raw, Jsonb(json.loads(raw))))  # fmt: skip
        for p in people:
            cols = columns_of(p["id"], p)
            conn.execute(
                f"insert into {schema}.people (id, name, normalized_name, country, identity_status, founder_status, "
                "radar_state, attrs, legacy) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)".encode(),
                (p["id"], cols["name"], cols["normalized_name"], cols["country"], cols["identity_status"],
                 cols["founder_status"], cols["radar_state"], Jsonb(cols["attrs"]), Jsonb(p)),
            )  # fmt: skip
            for kind, value in distinct_identifiers(p):
                conn.execute(f"insert into {schema}.person_identifiers (person_id, kind, value) values (%s, %s, %s)"
                             .encode(), (p["id"], kind, value))  # fmt: skip


@pytest.fixture
def people(settings: Settings) -> Iterator[tuple[TestClient, str]]:
    schema = f"pz_itest_{secrets.token_hex(4)}"
    _exec(settings, _scratch_sql("pz"), schema)
    try:
        _seed_people(settings, schema, [ADA, ADA2, HOST])
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        app.state.clock = lambda: NOW
        with TestClient(app, base_url="http://127.0.0.1:8177") as c:
            yield c, schema
    finally:
        _drop(settings, schema)


def _merge(settings: Settings, schema: str) -> None:
    with transaction(settings.db_url) as conn:
        store = PeopleStore(conn, schema)
        store._lock()
        survivor = {**ADA, "patent_inventor_id": "INV-INVENTED-2", "aliases": ["ada i", "ada two"]}
        assert store.merge_into(ADA["id"], ADA2["id"], survivor, {"request": {"action": "merge"}})


def _owners(settings: Settings, schema: str) -> list[tuple[Any, ...]]:
    return _q(settings, schema, "select kind, value, person_id from {s}.person_identifiers order by kind, value")


def test_after_a_merge_stale_network_writes_answer_as_an_unknown_id_and_write_nothing(
    settings: Settings, people: tuple[TestClient, str]
) -> None:
    c, schema = people
    tomb_events_before = _q(settings, schema, "select action from {s}.person_events where person_id = %s order by id",
                            (ADA2["id"],))  # fmt: skip
    _merge(settings, schema)
    owners = _owners(settings, schema)
    assert {o[2] for o in owners if o[1] in ("INV-INVENTED-2", "ada two")} == {ADA["id"]}  # transferred
    assert not [o for o in owners if o[2] == ADA2["id"]]  # the tombstone owns none
    assert _q(settings, schema, "select merged_into from {s}.people where id = %s", (ADA2["id"],)) == [(ADA["id"],)]
    events = _q(settings, schema, "select person_id, action from {s}.person_events order by id")
    assert events[-2:] == [(ADA["id"], "merge"), (ADA2["id"], "merged")]
    with transaction(settings.db_url) as conn:
        assert ADA2["id"] not in [p["id"] for p in load_people(conn, schema)]  # gone, as the old merge deleted it
    snapshot = (_q(settings, schema, "select id, attrs, merged_into from {s}.people order by id"), _owners(settings, schema),
                _q(settings, schema, "select count(*) from {s}.person_events"))  # fmt: skip
    for path, body in [("person_save", {"name": "Ada Edited", "notes": "stale"}), ("watch_log", {"note": "stale"}),
                       ("talented", {"persons": [{"name": "Newly Named"}]})]:  # fmt: skip
        merged = c.post(f"/api/network/{path}", json={"id": ADA2["id"], **body})
        unknown = c.post(f"/api/network/{path}", json={"id": "p-never-existed", **body})
        assert merged.status_code == unknown.status_code, path
        assert {k: v for k, v in merged.json().items() if k != "id"} == {k: v for k, v in unknown.json().items()
                                                                          if k != "id"}, path  # fmt: skip
    after = (_q(settings, schema, "select id, attrs, merged_into from {s}.people order by id"), _owners(settings, schema),
             _q(settings, schema, "select count(*) from {s}.person_events"))  # fmt: skip
    assert after == snapshot  # zero writes
    tomb_events = _q(settings, schema, "select action from {s}.person_events where person_id = %s order by id",
                     (ADA2["id"],))  # fmt: skip
    assert tomb_events == [*tomb_events_before, ("merged",)]  # its earlier events survive


def test_a_recommendation_or_an_add_reusing_the_merged_id_is_an_atomic_409(
    settings: Settings, people: tuple[TestClient, str]
) -> None:
    c, schema = people
    _merge(settings, schema)
    # the losing id is the slug of "Ada Invented 2"
    snapshot = (_q(settings, schema, "select id, attrs, merged_into from {s}.people order by id"), _owners(settings, schema),
                _q(settings, schema, "select count(*) from {s}.person_events"))  # fmt: skip
    r = c.post("/api/network/talented", json={"id": HOST["id"], "persons": [{"name": "Fresh Invented"},
                                                                             {"name": "Ada Invented 2"}]})  # fmt: skip
    assert r.status_code == 409 and r.json()["merged_into"] == ADA["id"], r.text
    assert "was merged into Ada Invented — recommend that person instead" in r.json()["error"]
    r = c.post("/api/network/person_save", json={"name": "Ada Invented 2"})
    assert r.status_code == 409 and r.json()["merged_into"] == ADA["id"], r.text
    after = (_q(settings, schema, "select id, attrs, merged_into from {s}.people order by id"), _owners(settings, schema),
             _q(settings, schema, "select count(*) from {s}.person_events"))  # fmt: skip
    assert after == snapshot  # nothing written: not even "Fresh Invented"
    ok = c.post("/api/network/talented", json={"id": HOST["id"], "persons": [{"name": "Fresh Invented"}]})
    assert ok.json() == {"ok": True, "created": ["p-fresh-invented"]}
    again = c.post("/api/network/talented", json={"id": HOST["id"], "persons": [{"name": "Fresh Invented"}]})
    assert again.json() == {"ok": True, "created": ["p-fresh-invented"]}  # the old answer lists every named person
    rows = _q(settings, schema, "select id from {s}.people where id like 'p-fresh-invented%%'")
    assert rows == [("p-fresh-invented",)]  # the retry linked the person the first call created, no second one


def test_a_failure_during_the_identifier_transfer_restores_both_people(
    settings: Settings, people: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, schema = people
    snapshot = (_q(settings, schema, "select id, attrs, merged_into from {s}.people order by id"), _owners(settings, schema),
                _q(settings, schema, "select count(*) from {s}.person_events"))  # fmt: skip
    real = PeopleStore._rows
    moved = {"n": 0}

    def failing(self: PeopleStore, query: str, params: Any = ()) -> list[dict[str, Any]]:
        if query.startswith("update {s}.person_identifiers set person_id"):
            moved["n"] += 1
            if moved["n"] == 2:  # after the FIRST identifier moved
                raise RuntimeError("injected during the identifier transfer")
        return real(self, query, params)

    monkeypatch.setattr(PeopleStore, "_rows", failing)
    with pytest.raises(RuntimeError, match="injected"):
        _merge(settings, schema)
    monkeypatch.undo()
    assert moved["n"] == 2
    after = (_q(settings, schema, "select id, attrs, merged_into from {s}.people order by id"), _owners(settings, schema),
             _q(settings, schema, "select count(*) from {s}.person_events"))  # fmt: skip
    assert after == snapshot  # both people, every identifier's owner, no event


# ── the routes, over the parity corpus (invented names) seeded as the importer stores it ──────────────────────────
def _radar_schema(settings: Settings) -> str:
    from projectzero.ops.parity_founder_radar import companies_doc, people, research_doc

    schema = f"pz_itest_{secrets.token_hex(4)}"
    _exec(settings, _scratch_sql("pz"), schema)
    _seed_people(settings, schema, people())
    _archive(settings, schema, "radar_companies.json", companies_doc())
    _archive(settings, schema, "radar_research.json", research_doc())
    _backfill(settings, schema)
    return schema


@pytest.fixture
def radar(settings: Settings) -> Iterator[tuple[TestClient, str]]:
    schema = _radar_schema(settings)
    try:
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        app.state.clock = lambda: NOW
        with TestClient(app, base_url="http://127.0.0.1:8177") as c:
            yield c, schema
    finally:
        _drop(settings, schema)


TABLES = ("people", "person_identifiers", "person_events", "radar_companies", "radar_research", "radar_events",
          "documents")  # fmt: skip


def _all(settings: Settings, schema: str) -> tuple[Any, ...]:
    """Every row a Founder Radar request could touch (whole rows; the json records as text)."""
    out = []
    for t in TABLES:
        col = "x.key || x.record::text" if t in ("radar_companies", "radar_research") else "to_jsonb(x)::text"
        out.append(_q(settings, schema, f"select {col} from {{s}}.{t} x order by 1"))
    return tuple(out)


def test_the_get_and_the_proposals_read_write_nothing(settings: Settings, radar: tuple[TestClient, str]) -> None:
    from projectzero.ops.parity_founder_radar import LARK

    c, schema = radar
    before = _all(settings, schema)
    r = c.get("/api/founder-radar")
    assert r.status_code == 200 and len(r.json()["people"]) > 5, r.text
    p = c.post("/api/founder-radar/proposals", json={"key": LARK})
    assert p.status_code == 200 and p.json()["ok"] and p.json()["proposals"], p.text
    ordered = [x["id"] for x in p.json()["proposals"]]
    assert ordered[:2] == ["founded-news-long-identifier-0001", "status-01"]  # the archive's insertion order
    assert _all(settings, schema) == before  # decision (a): no migration, founder ref, region or metrics write


def test_one_action_is_one_transaction(
    settings: Settings, radar: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from projectzero.ops.parity_founder_radar import TEODOR

    c, schema = radar
    before = _all(settings, schema)

    def fail(*_: Any, **__: Any) -> bool:  # the metrics snapshot comes AFTER the person write
        raise RuntimeError("injected after the person write")

    monkeypatch.setattr(FounderRadarStore, "write_document", fail)
    with pytest.raises(RuntimeError, match="injected"):
        c.post("/api/founder-radar/action", json={"id": TEODOR, "action": "watch"})
    assert _all(settings, schema) == before  # the person, its event and the metrics: none written
    monkeypatch.undo()
    ok = c.post("/api/founder-radar/action", json={"id": TEODOR, "action": "watch"})
    assert ok.status_code == 200 and ok.json()["ok"], ok.text
    assert _q(settings, schema, "select action from {s}.person_events where person_id = %s", (TEODOR,)) == [("radar",)]
    assert _q(settings, schema, "select entity, action from {s}.radar_events") == [("metrics", "snapshot")]


def test_verify_identity_keeps_the_operator_evidence_through_the_recomputation(
    settings: Settings, radar: tuple[TestClient, str]
) -> None:
    from projectzero.ops.parity_founder_radar import TEODOR

    c, _ = radar
    body = {"id": TEODOR, "action": "verify_identity", "url": "https://optics.example/teodor", "label": "lab page",
            "fact": "Teodor Vanstrel heads the lab", "confirm": True}  # fmt: skip
    r = c.post("/api/founder-radar/action", json=body)
    assert r.status_code == 200 and r.json()["ok"], r.text
    fresh = next(p for p in c.get("/api/founder-radar").json()["people"] if p["id"] == TEODOR)  # a reload
    kept = [e for e in fresh["evidence"] if e.get("source_url") == "https://optics.example/teodor"]
    assert kept and "Teodor Vanstrel heads the lab" in json.dumps(kept)  # the operator's source and fact survived


def test_after_a_radar_merge_stale_radar_writes_answer_as_an_unknown_id(
    settings: Settings, radar: tuple[TestClient, str]
) -> None:
    from projectzero.ops.parity_founder_radar import LARK, WENNA_A, WENNA_B

    c, schema = radar
    tomb_before = _q(settings, schema, "select action from {s}.person_events where person_id = %s", (WENNA_B,))
    r = c.post("/api/founder-radar/action", json={"id": WENNA_A, "action": "merge", "other": WENNA_B, "confirm": True})
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert _q(settings, schema, "select merged_into from {s}.people where id = %s", (WENNA_B,)) == [(WENNA_A,)]
    assert not _q(settings, schema, "select 1 from {s}.person_identifiers where person_id = %s", (WENNA_B,))
    tomb_after = _q(
        settings, schema, "select action from {s}.person_events where person_id = %s order by id", (WENNA_B,)
    )
    assert tomb_after == [*tomb_before, ("merged",)]
    assert WENNA_B not in [p["id"] for p in c.get("/api/founder-radar").json()["people"]]
    snapshot = _all(settings, schema)
    for path, body in [
        ("action", {"action": "watch"}),
        ("action", {"action": "evidence", "kind": "technical", "url": "https://github.com/x", "label": "x"}),
        ("promote", {"how": "met"}),
        ("boardy_brief", {}),
    ]:
        merged = c.post(f"/api/founder-radar/{path}", json={"id": WENNA_B, **body})
        unknown = c.post(f"/api/founder-radar/{path}", json={"id": "p-never-existed", **body})
        assert (merged.status_code, merged.json()) == (unknown.status_code, unknown.json()), path
    merged = c.post("/api/founder-radar/review", json={"key": LARK, "bindings": {"fz": WENNA_B}, "confirm": ["fz"]})
    unknown = c.post(
        "/api/founder-radar/review", json={"key": LARK, "bindings": {"fz": "p-never-existed"}, "confirm": ["fz"]}
    )
    assert merged.status_code == unknown.status_code
    assert _absent(merged.json(), WENNA_B) == _absent(unknown.json(), "p-never-existed")
    assert _all(settings, schema)[:3] == snapshot[:3]  # no person, identifier or person event changed


def _absent(body: dict[str, Any], pid: str) -> Any:
    """A review answer with the bound (absent) person id masked: the two requests name different absent ids."""
    return json.loads(json.dumps(body).replace(pid, "<absent>"))


def test_two_concurrent_actions_on_one_person_both_land(settings: Settings, radar: tuple[TestClient, str]) -> None:
    import threading

    from projectzero.ops.parity_founder_radar import TEODOR

    c, schema = radar
    codes: list[int] = []

    def post(n: int) -> None:
        body = {"id": TEODOR, "action": "evidence", "kind": "technical", "url": f"https://github.com/teodor-{n}",
                "label": f"repo {n}", "claim": f"Maintains repository {n}"}  # fmt: skip
        codes.append(c.post("/api/founder-radar/action", json=body).status_code)

    threads = [threading.Thread(target=post, args=(n,)) for n in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert codes == [200, 200]
    person = next(p for p in c.get("/api/founder-radar").json()["people"] if p["id"] == TEODOR)
    urls = {e.get("source_url") for e in person["evidence"]}
    assert {"https://github.com/teodor-1", "https://github.com/teodor-2"} <= urls  # serialized: neither lost
    assert len(_q(settings, schema, "select 1 from {s}.person_events where person_id = %s", (TEODOR,))) == 2


def test_a_company_write_is_what_conviction_reads(settings: Settings, radar: tuple[TestClient, str]) -> None:
    from projectzero.ops.parity_founder_radar import LARK

    c, schema = radar
    r = c.post("/api/founder-radar/company", json={"key": LARK, "notes": "Invented note for the check"})
    assert r.status_code == 200 and r.json()["ok"], r.text
    with transaction(settings.db_url) as conn:
        docs = load_documents(conn, schema)
    assert docs["radar_companies.json"]["companies"][LARK]["notes"] == "Invented note for the check"
    assert _q(settings, schema, "select entity, action from {s}.radar_events") == [("company", "company")]


def test_radar_writes_are_closed_before_the_import_in_production(settings: Settings) -> None:
    app = create_app(Settings(db_url=settings.db_url, schema="pz"))
    app.state.clock = lambda: NOW
    with TestClient(app, base_url="http://127.0.0.1:8177") as c:
        r = c.post("/api/founder-radar/action", json={"id": "p-anything", "action": "watch"})
    if r.status_code == 409:
        assert "after the legacy import" in r.json()["error"]
    else:  # the live import has happened: the boundary is open (an unknown person is the old refusal)
        assert r.json() == {"ok": False, "error": "unknown person"}


# ── Codex H-211: route merges keep every identifier, and a chain of merges names the live survivor ──────────────────
ILKA_KEEP = {"id": "p-ilka-invented-0001", "name": "Ilka Invented", "provenance": "radar_detected",
             "company": "Invented Optics"}  # fmt: skip
ILKA_GONE = {"id": "p-ilka-invented-0002", "name": "Ilka Invented", "provenance": "radar_detected",
             "company": "Invented Optics", "patent_inventor_id": "INV-INVENTED-777", "aliases": ["ilka i"]}  # fmt: skip
CHAIN = [{"id": pid, "name": "Chain Invented", "provenance": "radar_detected", "company": "Invented Chain Co"}
         for pid in ("p-chain-invented", "p-chain-invented-0002", "p-chain-invented-0003")]  # fmt: skip
CHAIN_HOST = {"id": "p-chain-host", "name": "Chain Host", "provenance": "user_provided"}


@pytest.fixture
def merges(settings: Settings) -> Iterator[tuple[TestClient, str]]:
    schema = f"pz_itest_{secrets.token_hex(4)}"
    _exec(settings, _scratch_sql("pz"), schema)
    try:
        _seed_people(settings, schema, [ILKA_KEEP, ILKA_GONE, *CHAIN, CHAIN_HOST])
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        app.state.clock = lambda: NOW
        with TestClient(app, base_url="http://127.0.0.1:8177") as c:
            yield c, schema
    finally:
        _drop(settings, schema)


def _owner(settings: Settings, schema: str, kind: str, value: str) -> list[tuple[Any, ...]]:
    return _q(settings, schema, "select person_id from {s}.person_identifiers where kind = %s and value = %s",
              (kind, value))  # fmt: skip


def test_a_route_merge_keeps_the_losing_persons_strong_identifier_through_later_edits(
    settings: Settings, merges: tuple[TestClient, str]
) -> None:
    c, schema = merges
    assert _owner(settings, schema, "patent_inventor", "INV-INVENTED-777") == [(ILKA_GONE["id"],)]
    r = c.post("/api/founder-radar/action", json={"id": ILKA_KEEP["id"], "action": "merge", "other": ILKA_GONE["id"],
                                                  "confirm": True})  # fmt: skip
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert _owner(settings, schema, "patent_inventor", "INV-INVENTED-777") == [(ILKA_KEEP["id"],)]
    assert _owner(settings, schema, "alias", "ilka i") == [(ILKA_KEEP["id"],)]
    detail = _q(settings, schema, "select detail from {s}.person_events where person_id = %s and action = 'merge'",
                (ILKA_KEEP["id"],))[0][0]  # fmt: skip
    assert "patent_inventor_id" in detail["fields_carried"]
    # unrelated edits afterwards, through Network and through Founder Radar, keep the owner
    assert c.post("/api/network/person_save", json={"id": ILKA_KEEP["id"], "notes": "met later"}).status_code == 200
    assert c.post("/api/founder-radar/action", json={"id": ILKA_KEEP["id"], "action": "watch"}).json()["ok"]
    assert _owner(settings, schema, "patent_inventor", "INV-INVENTED-777") == [(ILKA_KEEP["id"],)]
    assert _owner(settings, schema, "alias", "ilka i") == [(ILKA_KEEP["id"],)]


def test_after_two_merges_the_reserved_id_refusals_name_the_live_survivor(
    settings: Settings, merges: tuple[TestClient, str]
) -> None:
    c, schema = merges
    a, b, live = (p["id"] for p in CHAIN)
    for keep, gone in ((b, a), (live, b)):  # A merged into B, then B merged into C
        r = c.post("/api/founder-radar/action", json={"id": keep, "action": "merge", "other": gone, "confirm": True})
        assert r.status_code == 200 and r.json()["ok"], r.text
    assert _q(settings, schema, "select id, merged_into from {s}.people where id like 'p-chain-invented%%' order by id") == [
        (a, b), (b, live), (live, None)]  # fmt: skip
    snapshot = _all(settings, schema)
    talented = c.post("/api/network/talented", json={"id": CHAIN_HOST["id"], "persons": [{"name": "Chain Invented"}]})
    added = c.post("/api/network/person_save", json={"name": "Chain Invented"})  # slug(name) is A's id
    for r in (talented, added):
        assert r.status_code == 409, r.text
        assert r.json()["merged_into"] == live  # the person the operator can open, not the hidden B
        assert "was merged into Chain Invented" in r.json()["error"]
    assert _all(settings, schema) == snapshot  # nothing written


# Codex H-213: two DIFFERENT patent inventor ids are two people: the merge is refused and nothing is written
PAT_A = {"id": "p-pat-invented-0001", "name": "Pat Invented", "provenance": "radar_detected",
         "company": "Invented Patents Co", "patent_inventor_id": "INV-A"}  # fmt: skip
PAT_B = {"id": "p-pat-invented-0002", "name": "Pat Invented", "provenance": "radar_detected",
         "company": "Invented Patents Co", "patent_inventor_id": "INV-B"}  # fmt: skip


def test_a_merge_of_two_different_patent_inventor_ids_is_refused_and_writes_nothing(settings: Settings) -> None:
    schema = f"pz_itest_{secrets.token_hex(4)}"
    _exec(settings, _scratch_sql("pz"), schema)
    try:
        _seed_people(settings, schema, [PAT_A, PAT_B])
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        app.state.clock = lambda: NOW
        with TestClient(app, base_url="http://127.0.0.1:8177") as c:
            before = _all(settings, schema)
            r = c.post("/api/founder-radar/action", json={"id": PAT_A["id"], "action": "merge", "other": PAT_B["id"],
                                                          "confirm": True})  # fmt: skip
            assert r.status_code == 200, r.text
            assert r.json() == {"ok": False, "needs_confirmation": False, "error": "merge refused: conflicting "
                                "patent_inventor_id (INV-A vs INV-B) — never merged automatically"}  # fmt: skip
            assert _all(settings, schema) == before  # zero writes
            assert _owner(settings, schema, "patent_inventor", "INV-A") == [(PAT_A["id"],)]
            assert _owner(settings, schema, "patent_inventor", "INV-B") == [(PAT_B["id"],)]
            assert _q(settings, schema, "select count(*) from {s}.people where merged_into is not null") == [(0,)]
    finally:
        _drop(settings, schema)

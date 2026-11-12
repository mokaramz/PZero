"""Review 025 acceptance tests (plan revision 2, Codex H-189 / H-193) against the hosted project, in throw-away scratch
schemas, with invented names only.

* the reads write nothing: a PLACEABLE Conviction record with no coordinates keeps its whole stored row (every column)
  through every Map endpoint, and no event table changes; the pins still carry its geocoded coordinates (decision a);
* the archives' key order survives: the archived News and source-network orders (long keys first, which JSONB would
  put last) decide the city detail's ``news`` and ``source_candidates``;
* a missing News or source-network archive empties only its layer;
* an existing import with a malformed source-network archive (decision f): the city detail answers 200 with the usable
  candidates in order and a note naming the dropped one; every other layer equals the valid-archive answer; the
  intelligence, search and the sourcing day answer 200.
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
from projectzero.core.config import Settings
from projectzero.core.db import connect, read_only_transaction, transaction
from projectzero.ecosystems.store import EcosystemsStore
from projectzero.map import inputs as map_inputs
from projectzero.ops.db_check import _scratch_sql
from projectzero.ops.parity_founder_calls import utc_instant

pytestmark = pytest.mark.hosted
NOW = utc_instant("2026-11-12T10:00:00")
CITY = "Munich"
COMPANY = "Invented Isar Robotics"
EVENT_TABLES = ("conviction_events", "source_events", "fc_events", "eval_events", "candidate_events")


def _news(eid: str, headline: str) -> dict[str, Any]:
    return {"event_id": eid, "headline": headline, "summary": "", "materiality": "HIGH", "event_type": "grant",
            "event_date": "2026-11-01", "sources": [{"publisher": "Invented Wire"}], "themes": ["robotics"]}  # fmt: skip


NEWS = {"version": 1, "events": {  # the LONG key first: JSONB would put the short one first
    "nw-zzzzzzzz-long": _news("nw-zzzzzzzz-long", "Invented Alpha wins a Munich robotics grant"),
    "n1": _news("n1", "Invented Beta joins a Munich accelerator"),
}}  # fmt: skip


def _cand(name: str, state: str, url: str) -> dict[str, Any]:
    return {"name": name, "state": state, "url": url, "family": "university_lab"}


NETWORK = {"candidates": {  # the LONG key first
    "net-zzzzzzzz-long": _cand("Invented Long Feed", "DISCOVERED", "https://long.invented.de/feed"),
    "n2": _cand("Invented Short Feed", "PROBATION", "https://short.invented.de/feed"),
}}  # fmt: skip
BAD_NETWORK = {"candidates": {  # one candidate the old city detail would break on, between the two usable ones
    "net-zzzzzzzz-long": NETWORK["candidates"]["net-zzzzzzzz-long"],
    "nb": _cand("Invented Broken Feed", "DISCOVERED", "invented.de"),
    "n2": NETWORK["candidates"]["n2"],
}}  # fmt: skip


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def _archive(conn: Any, schema: str, path: str, doc: Any) -> None:
    raw = json.dumps(doc, indent=1).encode("utf-8")
    conn.execute(f"insert into {schema}.legacy_documents (path, sha256, bytes, raw, parsed) values "
                 "(%s, %s, %s, %s, %s::jsonb)".encode(),
                 (path, hashlib.sha256(raw).hexdigest(), len(raw), raw, raw.decode("utf-8")))  # fmt: skip


def _schema(settings: Settings, archives: dict[str, Any]) -> str:
    name = f"pz_itest_{secrets.token_hex(4)}"
    with connect(settings.db_url, autocommit=True) as admin:
        admin.execute(re.sub(r"\bpz\b", name, _scratch_sql("pz")).encode())
    with transaction(settings.db_url) as conn:
        for path, doc in archives.items():
            _archive(conn, name, path, doc)
        record = {
            "company": COMPANY,
            "slug": "invented-isar-robotics",
            "status": "new",
            "location": "Munich, Germany",
            "scores": {"founder": 20},
            "verified": {},
            "founders": [{"name": "Ada Invented"}],
            "one_liner": "Invented warehouse robots.",
        }  # fmt: skip — placeable, and no lat / lng stored
        co = conn.execute(
            f"insert into {name}.companies (name) values (%s) returning id".encode(), (COMPANY,)
        ).fetchone()
        assert co is not None
        conn.execute(f"insert into {name}.conviction_entries (company_id, slug, status, verified, scores, legacy) "
                     "values (%s, %s, 'new', '{}', %s, %s)".encode(),
                     (co[0], record["slug"], Jsonb(record["scores"]), Jsonb(record)))  # fmt: skip
    return name


def _drop(settings: Settings, name: str) -> None:
    with connect(settings.db_url, autocommit=True) as admin:
        admin.execute(f"drop schema if exists {name} cascade".encode())


@pytest.fixture
def make(settings: Settings) -> Iterator[Any]:
    made: list[str] = []

    def build(archives: dict[str, Any]) -> tuple[TestClient, str]:
        schema = _schema(settings, archives)
        made.append(schema)
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        app.state.clock = lambda: NOW
        return TestClient(app, base_url="http://127.0.0.1:8177"), schema

    yield build
    for schema in made:
        _drop(settings, schema)


FULL = {"news/events.json": NEWS, "sources/network.json": NETWORK}


def _stored(settings: Settings, schema: str) -> tuple[Any, ...]:
    with transaction(settings.db_url) as conn:
        entries = conn.execute(f"select to_jsonb(e) from {schema}.conviction_entries e order by id".encode()).fetchall()
        counts = []
        for table in EVENT_TABLES:
            exists = conn.execute(b"select to_regclass(%s)", (f"{schema}.{table}",)).fetchone()
            if exists and exists[0]:
                n = conn.execute(f"select count(*) from {schema}.{table}".encode()).fetchone()
                counts.append((table, n[0] if n else None))
    return entries, counts


def test_every_map_read_writes_nothing_and_the_pins_geocode_in_memory(settings: Settings, make: Any) -> None:
    c, schema = make(FULL)
    before = _stored(settings, schema)
    pins = c.get("/api/map/pins").json()
    for r in (c.get("/api/map/intel"), c.get("/api/map/ecosystem", params={"city": CITY}),
              c.get("/api/map/search", params={"q": "invented"}),
              c.post("/api/map/sourcing_day", json={"city": CITY, "date": "2026-11-20"})):  # fmt: skip
        assert r.status_code == 200, r.text
    assert _stored(settings, schema) == before  # the whole row of the placeable record, and every event table
    pin = next(s for s in pins["startups"] if s["company"] == COMPANY)
    assert pin["lat"] is not None and pin["lng"] is not None  # geocoded for the answer only
    assert "lat" not in before[0][0][0]["legacy"]


def test_the_archived_order_decides_the_news_and_the_source_candidates(settings: Settings, make: Any) -> None:
    c, _ = make(FULL)
    d = c.get("/api/map/ecosystem", params={"city": CITY}).json()
    assert [n["headline"] for n in d["news"]] == [e["headline"] for e in NEWS["events"].values()]
    assert [s["name"] for s in d["source_candidates"]] == ["Invented Long Feed", "Invented Short Feed"]
    assert "could not be interpreted" not in d["note"]


def test_a_missing_news_or_network_archive_empties_only_its_layer(settings: Settings, make: Any) -> None:
    full, _ = make(FULL)
    no_news, _ = make({"sources/network.json": NETWORK})
    no_net, _ = make({"news/events.json": NEWS})
    f = full.get("/api/map/ecosystem", params={"city": CITY}).json()
    a = no_news.get("/api/map/ecosystem", params={"city": CITY}).json()
    b = no_net.get("/api/map/ecosystem", params={"city": CITY}).json()
    assert a["news"] == [] and a["source_candidates"] == f["source_candidates"]
    assert b["source_candidates"] == [] and b["news"] == f["news"]
    for d in (a, b):
        assert d["companies"] == f["companies"] and d["institutions"] == f["institutions"]


def test_an_existing_import_with_a_malformed_network_keeps_every_other_layer(settings: Settings, make: Any) -> None:
    good, _ = make(FULL)
    bad, _ = make({"news/events.json": NEWS, "sources/network.json": BAD_NETWORK})  # written past the importer
    g = good.get("/api/map/ecosystem", params={"city": CITY}).json()
    r = bad.get("/api/map/ecosystem", params={"city": CITY})
    assert r.status_code == 200, r.text
    d = r.json()
    assert [s["name"] for s in d["source_candidates"]] == ["Invented Long Feed", "Invented Short Feed"]
    assert "Source network: 1 record(s) could not be interpreted — skipped safely" in d["note"]
    assert "nb" in d["note"]
    for k in ("companies", "people", "events", "news", "institutions", "why_here"):
        assert d[k] == g[k], k
    for resp in (bad.get("/api/map/intel"), bad.get("/api/map/search", params={"q": "munich"}),
                 bad.post("/api/map/sourcing_day", json={"city": CITY, "date": "2026-11-20"})):  # fmt: skip
        assert resp.status_code == 200, resp.text
    assert "could not be interpreted" in bad.get("/api/map/intel").json()["note"]


def test_the_old_refusals(settings: Settings, make: Any) -> None:
    c, _ = make({})
    r = c.get("/api/map/ecosystem", params={"city": "Invented Nowhere"})
    assert (r.status_code, r.json()) == (404, {"ok": False, "error": "unknown or unplaced ecosystem: Invented Nowhere"})
    r = c.post("/api/map/sourcing_day", json={"city": "Invented Nowhere", "date": "2026-11-20"})
    assert r.status_code == 400 and r.json()["error"] == "unknown or unplaced ecosystem: Invented Nowhere"
    r = c.post("/api/map/sourcing_day", json={"city": CITY, "date": "next week"})
    assert (r.status_code, r.json()) == (400, {"ok": False, "error": "date as YYYY-MM-DD"})
    assert (
        c.post("/api/map/sourcing_day", content=b"[1]", headers={"Content-Type": "application/json"}).status_code == 400
    )


def test_bom_prefixed_archives_keep_their_candidates_and_their_first_watch_record(
    settings: Settings, make: Any
) -> None:
    """Codex H-201: the importer accepts an optional UTF-8 BOM, so the Map reads the archives the same way."""
    c, schema = make({"news/events.json": NEWS})
    network = b"\xef\xbb\xbf" + json.dumps(NETWORK).encode("utf-8")
    watch = b"\xef\xbb\xbf" + "\n".join(json.dumps(line) for line in [
        {"id": "w-1", "name": COMPANY, "predicate": "raised", "at": "2026-11-10T09:00:00"},  # the FIRST record
        {"kind": "status", "trigger_id": "w-other", "status": "done"},
    ]).encode("utf-8")  # fmt: skip
    with transaction(settings.db_url) as conn:
        for path, raw, parsed in (("sources/network.json", network, json.dumps(NETWORK)),
                                  ("watch/triggers.jsonl", watch, None)):  # fmt: skip
            conn.execute(f"insert into {schema}.legacy_documents (path, sha256, bytes, raw, parsed) values "
                         "(%s, %s, %s, %s, %s::jsonb)".encode(),
                         (path, hashlib.sha256(raw).hexdigest(), len(raw), raw, parsed))  # fmt: skip
    d = c.get("/api/map/ecosystem", params={"city": CITY}).json()
    assert [s["name"] for s in d["source_candidates"]] == ["Invented Long Feed", "Invented Short Feed"]
    assert "could not be interpreted" not in d["note"]
    company = next(x for x in d["companies"] if x["name"] == COMPANY)
    assert company["watch"] is True  # the first JSONL record, right after the BOM, was read


def _inbox_record(cid: str, name: str, location: str) -> dict[str, Any]:
    return {"id": cid, "name": name, "decision": "new", "discovery_tier": "announcement",
            "source_id": "s-invented-wire", "first_seen": "2026-11-01", "location": location,
            "description": f"{name}, invented."}  # fmt: skip


def _absorbed_world(settings: Settings, schema: str, own: dict[str, Any] | None = None) -> None:
    """Two old inbox records (Munich) absorbed into one survivor whose own record is a Scout item (or, with ``own``,
    an inbox record itself, archived first); the survivor holds the current proposal."""
    first = _inbox_record("c-absorbed-01", "Invented Dunlin Robotics", "Munich, Germany")
    second = _inbox_record("c-absorbed-02", "Invented Dunlin Robotics GmbH", "Munich, Germany")
    archived = [r for r in (own, first, second) if r]
    inbox = json.dumps({"candidates": archived}).encode("utf-8")
    scout = {"id": "si-005-invented-dunlin", "entity_name": "Invented Dunlin Robotics", "cycle_id": "005"}
    with transaction(settings.db_url) as conn:
        conn.execute(f"insert into {schema}.legacy_documents (path, sha256, bytes, raw, parsed) values "
                     "(%s, %s, %s, %s, %s::jsonb)".encode(),
                     ("inbox.json", hashlib.sha256(inbox).hexdigest(), len(inbox), inbox, inbox.decode()))  # fmt: skip
        sid = own["id"] if own else "s-survivor-01"
        conn.execute(f"insert into {schema}.candidates (id, name, status, origins, legacy) values "
                     "(%s, 'Invented Dunlin Robotics', 'new', '{legacy_dealflow,legacy_scout00}', %s)".encode(),
                     (sid, Jsonb(own or scout)))  # fmt: skip
        for rec in (first, second):
            conn.execute(f"insert into {schema}.observations (candidate_id, origin, payload) values (%s, %s, %s)".encode(),
                         (sid, "legacy_dealflow", Jsonb({"merged_record": rec})))  # fmt: skip
        conn.execute(f"insert into {schema}.triage_proposals (candidate_id, proposal, detail) values (%s, 'KEEP', '{{}}')".encode(),
                     (sid,))  # fmt: skip


def test_an_absorbed_inbox_record_keeps_its_place_on_the_map(settings: Settings, make: Any) -> None:
    """Codex H-232 / H-237: two old inbox records (placed in Munich) were merged into a survivor whose own record is a
    Scout Intake item. The old ``inbox.json`` held both, so the old Map counted both in Munich's Deal Flow, counted
    both in ``new_signals`` while the decision was ``new``, and looked their proposals up by their own ids."""
    c, schema = make({"news/events.json": NEWS})
    _absorbed_world(settings, schema)
    names = [x["name"] for x in c.get("/api/map/ecosystem", params={"city": CITY}).json()["companies"]]
    assert {"Invented Dunlin Robotics", "Invented Dunlin Robotics GmbH"} <= set(names)
    base = c.get("/api/map/pins").json()["new_signals"]
    with read_only_transaction(settings.db_url) as conn:
        inputs = map_inputs.load(conn, schema, NOW)
        coverage = EcosystemsStore(conn, schema).inputs(NOW)
    ids = [r["id"] for r in inputs.inbox]
    assert ids[:2] == ["c-absorbed-01", "c-absorbed-02"] and "s-survivor-01" not in ids  # archived order; no Scout item
    assert {k: v["proposal"] for k, v in inputs.proposals.items()} == {"c-absorbed-01": "KEEP", "c-absorbed-02": "KEEP"}
    assert [r["id"] for r in coverage.inbox if "Dunlin" in r["name"]] == ["c-absorbed-01", "c-absorbed-02"]
    with transaction(settings.db_url) as conn:
        conn.execute(f"update {schema}.candidates set status = 'watch' where id = 's-survivor-01'".encode())
    assert c.get("/api/map/pins").json()["new_signals"] == base - 2  # both records followed the survivor's decision


def test_a_survivor_that_is_an_inbox_record_keeps_its_own_record_and_the_absorbed_one(
    settings: Settings, make: Any
) -> None:
    own = _inbox_record("c-own-0001", "Invented Dunlin AG", "Munich, Germany")
    _, schema = make({})
    _absorbed_world(settings, schema, own=own)
    with read_only_transaction(settings.db_url) as conn:
        inputs = map_inputs.load(conn, schema, NOW)
    assert [r["id"] for r in inputs.inbox][:3] == ["c-own-0001", "c-absorbed-01", "c-absorbed-02"]

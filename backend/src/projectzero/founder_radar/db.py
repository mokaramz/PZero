"""Founder Radar's database reads and the one way an ``Outcome`` is written (reviews 026a / 026b), shared by the request
endpoints and the scan / research runs.

* ``documents(conn, schema)`` — the radar documents kept as ``documents`` rows (health, regions, metrics, sources,
  cursor, the research queue). A row still equal to its byte-exact archive is read from the archive, so its key order
  is the old one (JSONB sorts keys); a row written since is read as stored.
* ``inputs(conn, schema)`` — the pure routes' ``Inputs``: the LIVE people (a merged person is absent), the companies
  and research records (the 0016 reader), the documents, the Conviction records as pipeline signals, and every
  tombstone id (reserved for new ids).
* ``apply_outcome(...)`` — in the caller's transaction, under the write lock then the people lock: the people through
  the Network store (``person_events``; a merge through ``merge_into``), the companies and research records, the
  metrics, and the run documents (cursor, health, research queue), each with its ``radar_events`` row. Only what the
  outcome changed is written.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from projectzero.conviction.store import ConvictionStore, record_of
from projectzero.core.db import schema_ident
from projectzero.founder_radar import routes
from projectzero.founder_radar.store import FounderRadarStore
from projectzero.network.store import PeopleStore, load_people

INPUT_DOCUMENTS = {"health": "radar_health.json", "regions": "radar_regions.json", "metrics": "radar_metrics.json"}
RUN_DOCUMENTS = {"sources": "radar_sources.json", "cursor": "radar_cursor.json", "queue": "radar_research_queue.json"}
METRICS = INPUT_DOCUMENTS["metrics"]
EVENT_ACTION = {"action": "action", "import": "import", "company": "company", "promote": "promote",
                "boardy_brief": "boardy", "pair": "pair", "review": "review", "scan": "scan", "research": "research",
                "research_queue": "research"}  # fmt: skip


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def documents(conn: psycopg.Connection[Any], schema: str) -> dict[str, Any]:
    """Every radar document by its field name (``health``, ``regions``, ``metrics``, ``sources``, ``cursor``,
    ``queue``); None when missing."""
    wanted = {**INPUT_DOCUMENTS, **RUN_DOCUMENTS}
    s = schema_ident(schema)
    keys = list(wanted.values())
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL("select key, body from {}.documents where key = any(%s)").format(s), (keys,))
        stored = {r["key"]: r["body"] for r in cur.fetchall()}
        cur.execute(sql.SQL("select path, raw from {}.legacy_documents where path = any(%s)").format(s), (keys,))
        archived = {r["path"]: r["raw"] for r in cur.fetchall()}
    out: dict[str, Any] = {}
    for name, key in wanted.items():
        body = stored.get(key)
        if key in archived:
            try:
                parsed = json.loads(bytes(archived[key]).decode("utf-8-sig"))
            except (UnicodeDecodeError, ValueError):
                parsed = None
            if parsed is not None and (body is None or _same(parsed, body)):
                body = parsed
        out[name] = body
    return out


def tombstones(conn: psycopg.Connection[Any], schema: str) -> frozenset[str]:
    s = schema_ident(schema)
    with conn.cursor() as cur:
        cur.execute(sql.SQL("select id from {}.people where merged_into is not null").format(s))
        return frozenset(str(r[0]) for r in cur.fetchall())


def inputs(conn: psycopg.Connection[Any], schema: str, docs: dict[str, Any] | None = None) -> routes.Inputs:
    store = FounderRadarStore(conn, schema)
    d = docs if docs is not None else documents(conn, schema)
    return routes.Inputs(
        people=load_people(conn, schema),
        companies=store.load_companies(),
        research=store.load_research(),
        signals=[record_of(r) for r in ConvictionStore(conn, schema).entry_rows()],
        reserved_ids=tombstones(conn, schema),
        **{k: d.get(k) for k in INPUT_DOCUMENTS},
    )


def lock(conn: psycopg.Connection[Any], schema: str) -> None:
    """The one write lock (and the production write boundary), then the people lock: the one lock order."""
    FounderRadarStore(conn, schema).lock()
    PeopleStore(conn, schema)._lock()


def apply_outcome(
    conn: psycopg.Connection[Any],
    schema: str,
    before: routes.Inputs,
    outcome: routes.Outcome,
    endpoint: str,
    detail: dict[str, Any],
    *,
    run_documents: dict[str, Any] | None = None,
) -> None:
    """Write what ``outcome`` changed relative to ``before`` (read under the same locks). ``run_documents``: the run
    documents to store by key (cursor, health, research queue; written only when they changed)."""
    people = PeopleStore(conn, schema)
    action = EVENT_ACTION[endpoint]
    info = {**detail, "endpoint": endpoint}
    if outcome.people is not None and outcome.people_changed:
        new_by_id = {str(p.get("id")): p for p in outcome.people if isinstance(p, dict)}
        survivor = outcome.merged[0] if outcome.merged else None
        ids = [str(i) for i in outcome.people_changed if str(i) != survivor]
        live = people._lock_rows(ids)  # the one lock order; a person merged meanwhile is absent
        before_by_id = {str(p.get("id")): p for p in before.people if isinstance(p, dict)}
        for pid in ids:
            if pid in before_by_id and pid not in live:
                continue  # merged by a concurrent request: absent for this write (026a revision 2)
            people._write(pid, before_by_id.get(pid), new_by_id[pid], "radar", info)
        if outcome.merged is not None:
            s_id, t_id = outcome.merged
            people.merge_into(s_id, t_id, new_by_id[s_id], info)
    radar = FounderRadarStore(conn, schema)
    if outcome.companies is not None:
        radar.write_records("companies", before.companies, outcome.companies, action, detail)
    if outcome.research is not None:
        radar.write_records("research", before.research, outcome.research, action, detail)
    if outcome.metrics is not None:
        radar.write_document(METRICS, outcome.metrics, "snapshot", info)
    for key, body in (run_documents or {}).items():
        if body is not None:
            radar.write_document(key, body, action, info, entity="document")

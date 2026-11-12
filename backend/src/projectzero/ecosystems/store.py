"""The database side of Ecosystems (review 022): load the pure functions' inputs and perform the one write.

* ``inputs()`` reads, in one transaction: the stored Deal Flow registry (normalized as in 021), the archived
  documents (``event_health.json``, ``radar_*.json``, ``coverage_*.json``, ``ecosystems.json``; a missing one is
  ``None`` and the pure code reads the old default in memory, decision a), the records in the old file order
  (inbox candidates, Conviction records, people, events) and the ``coverage_adoptions`` rows by ``adopted_at``.
* ``adopt(candidate_id, confirm, now)``: under the one write lock, the pure ``adopt_plan`` decides (the old order,
  plan revision 3). Only a real adoption writes, in this ONE transaction: the whole normalized registry with the new
  watcher appended (the old ``save_registry``), its ``source_events`` row (``adopt``) and the ``coverage_adoptions``
  row (the adoption and the new source's declaration). The imported documents are never rewritten.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from projectzero.conviction.store import ConvictionStore
from projectzero.conviction.store import record_of as conviction_record
from projectzero.core.db import schema_ident
from projectzero.dealflow.inbox_view import candidate_rows
from projectzero.dealflow.ranking.service import ranking_input
from projectzero.dealflow.sources.normalize import load_registry
from projectzero.dealflow.sources.store import SourcesStore
from projectzero.ecosystems import cities
from projectzero.ecosystems.adopt import adopt_plan
from projectzero.ecosystems.coverage import coverage_view
from projectzero.ecosystems.inputs import CoverageInputs
from projectzero.events import engine
from projectzero.events import store as events_store
from projectzero.network.store import load_people
from projectzero.network.view import berlin_today

DOCS = {
    "event_health": "event_health.json",
    "radar_regions": "radar_regions.json",
    "radar_sources": "radar_sources.json",
    "radar_health": "radar_health.json",
    "coverage_sources": "coverage_sources.json",
    "coverage_adopted": "coverage_adopted.json",
    "coverage_registry": "coverage_registry.json",
    "coverage_candidates": "coverage_candidates.json",
    "ecosystems_doc": "ecosystems.json",
}


class EcosystemsStore:
    def __init__(self, conn: psycopg.Connection[Any], schema: str = "pz") -> None:
        self.conn = conn
        self._schema = schema
        self.s = schema_ident(schema)

    def _rows(self, query: str, params: Any = ()) -> list[dict[str, Any]]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql.SQL(query).format(s=self.s), params)
            return list(cur.fetchall()) if cur.description else []

    def _docs(self) -> dict[str, Any]:
        rows = self._rows("select key, body from {s}.documents where key = any(%s)", (list(DOCS.values()),))
        by_key = {r["key"]: r["body"] for r in rows}
        return {field: by_key.get(key) for field, key in DOCS.items()}

    def _signals(self) -> list[dict[str, Any]]:
        return [conviction_record(r) for r in ConvictionStore(self.conn, self._schema).entry_rows()]

    def _events(self, now: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """(the event records, the Events listing as the old ``events.listing()`` returned it)."""
        data = events_store.load(self.conn, self._schema, berlin_today(now), people=False)
        return data.events, engine.listing(data.events, berlin_today(now), data.source_city(), data.pins)

    def inputs(self, now: datetime) -> CoverageInputs:
        stored = SourcesStore(self.conn, self._schema).stored()
        records, _ = self._events(now)
        adoptions = self._rows(
            "select candidate_id, source_id, families, countries, cities, note, by, adopted_at "
            "from {s}.coverage_adoptions order by adopted_at, candidate_id"
        )
        return CoverageInputs(
            sources=load_registry({"sources": stored})["sources"],
            **self._docs(),
            inbox=[ranking_input(r)[0] for r in candidate_rows(self.conn, self._schema)],
            signals=self._signals(),
            people=load_people(self.conn, self._schema),
            events=records,
            adoptions=[dict(r) for r in adoptions],
        )

    # ── reads ───────────────────────────────────────────────────────────────────────────────────────────────────
    def coverage(self, now: datetime) -> dict[str, Any]:
        return coverage_view(self.inputs(now), now)

    def registry(self, now: datetime) -> dict[str, Any]:
        _, listing = self._events(now)
        eco_doc = self._docs()["ecosystems_doc"]
        people = load_people(self.conn, self._schema)
        return cities.city_registry(self._signals(), listing, people, eco_doc, berlin_today(now))

    def eco(self, city: str, now: datetime) -> dict[str, Any]:
        _, listing = self._events(now)
        eco_doc = self._docs()["ecosystems_doc"]
        people = load_people(self.conn, self._schema)
        return cities.eco_view(city, self._signals(), listing, people, eco_doc, berlin_today(now))

    # ── the write ───────────────────────────────────────────────────────────────────────────────────────────────
    def adopt(self, candidate_id: Any, confirm: Any, now: datetime) -> dict[str, Any]:
        sources = SourcesStore(self.conn, self._schema)
        sources._lock()  # the one write lock (and the production boundary), held to the end of this transaction
        inputs = self.inputs(now)
        decision = adopt_plan(inputs, candidate_id, confirm)
        if not decision.writes or decision.source is None or decision.declaration is None:
            return decision.response
        stored = sources.stored()
        # the old adopt: load_registry() (normalized, repair-added sources included), THEN append the watcher, then
        # save the whole registry: the new source comes after every normalized one (Codex H-171)
        registry = [*load_registry({"sources": stored})["sources"], decision.source]
        sources.save_registry(stored, registry)
        sid = str(decision.source_id)
        sources.event(sid, "adopt", {}, {"candidate_id": decision.candidate_id, "enabled": True})
        d = decision.declaration
        self._rows(
            "insert into {s}.coverage_adoptions (candidate_id, source_id, families, countries, cities, note, by, "
            "adopted_at) values (%s, %s, %s, %s, %s, %s, %s, %s)",
            (str(decision.candidate_id), sid, list(d.get("families") or []), list(d.get("countries") or []),
             list(d.get("cities") or []), d.get("note"), decision.by or "operator", now),
        )  # fmt: skip
        return decision.response

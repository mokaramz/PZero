"""The Deal Flow source registry (review 021): the stored records, the view, and the on/off toggle.

* The stored record of a source is ``attrs.record`` once written here, else the imported ``legacy`` record; records
  come in the archived ``sources.json`` order (``legacy_stub`` rows the importer made for unknown ids are not part
  of the registry). They hold the BASELINE only (the imported counters); ``view`` adds the deltas to a copy.
* ``toggle`` is the old ``source_toggle``: ``enabled = bool(body.get("enabled"))`` on the NORMALIZED stored record
  (the old ``save_registry`` persisted the read-time repairs), one ``source_events`` row only when ``enabled``
  changes; a source that exists only through the normalization is inserted on its first toggle; an unknown id is
  the old ``{ok: true}`` with nothing written. Every write runs under the one write lock, after the import boundary.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from projectzero.core.db import schema_ident
from projectzero.dealflow import workspaces
from projectzero.dealflow.intake.postgres import ensure_intake_open
from projectzero.dealflow.ranking.service import RankingContext
from projectzero.dealflow.sources import counters
from projectzero.dealflow.sources.normalize import load_registry
from projectzero.dealflow.sources.registry import country_code
from projectzero.dealflow.sources.view import sources_view

_STORED = """
    select s.id, s.legacy, s.attrs, a.pos
    from {s}.sources s
    left join (
        select (e.value->>'id') as id, min(e.ord) as pos
        from {s}.legacy_documents d, jsonb_array_elements(d.parsed->'sources') with ordinality as e(value, ord)
        where d.path = 'sources.json' and jsonb_typeof(d.parsed->'sources') = 'array'
        group by 1
    ) a on a.id = s.id
    where s.kind <> 'legacy_stub'
    order by a.pos nulls last, s.created_at, s.id
"""


def record_of(row: dict[str, Any]) -> dict[str, Any] | None:
    attrs = row.get("attrs") or {}
    rec = attrs.get("record") if isinstance(attrs, dict) else None
    if isinstance(rec, dict):
        return rec
    legacy = row.get("legacy")
    return legacy if isinstance(legacy, dict) else None


class SourcesStore:
    def __init__(self, conn: psycopg.Connection[Any], schema: str = "pz") -> None:
        self.conn = conn
        self._schema = schema
        self.s = schema_ident(schema)

    def _rows(self, query: str, params: Any = ()) -> list[dict[str, Any]]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql.SQL(query).format(s=self.s), params)
            return list(cur.fetchall()) if cur.description else []

    # ── read ────────────────────────────────────────────────────────────────────────────────────────────────────
    def stored(self) -> list[dict[str, Any]]:
        """The stored registry records (the baseline), in the archived order."""
        return [r for r in (record_of(row) for row in self._rows(_STORED)) if r is not None]

    def view(self) -> dict[str, Any]:
        keys = ["inbox.json#rest", "workspace_geos.json"]
        docs = {
            r["key"]: r["body"] for r in self._rows("select key, body from {s}.documents where key = any(%s)", (keys,))
        }
        rest = docs.get("inbox.json#rest")
        return sources_view(
            self.stored(),
            ledger=RankingContext.load(self.conn, self._schema).ledger,
            deltas=counters.deltas(self.conn, self._schema),
            override=workspaces.parse_override(docs.get("workspace_geos.json") or {}),
            inbox_rest=rest if isinstance(rest, dict) else {},
        )

    # ── write ───────────────────────────────────────────────────────────────────────────────────────────────────
    def _lock(self) -> None:
        ensure_intake_open(self.conn, self._schema)  # the production write boundary: nothing before the import
        self._rows("select pg_advisory_xact_lock(hashtext(%s))", (f"{self._schema}.intake",))

    _UPSERT = (
        "insert into {s}.sources "
        "(id, name, url, kind, parser, enabled, country, geo_scope, sectors, attrs, created_at) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, jsonb_build_object('record', %s::jsonb), clock_timestamp()) "
        "on conflict (id) do update set name = excluded.name, url = excluded.url, kind = excluded.kind, "
        "parser = excluded.parser, enabled = excluded.enabled, "
        "attrs = {s}.sources.attrs || jsonb_build_object('record', %s::jsonb), updated_at = now()"
    )

    def _write(self, record: dict[str, Any]) -> None:
        sid = str(record["id"])
        sectors = [x for x in record.get("sectors") or [] if isinstance(x, str)]
        self._rows(self._UPSERT, (sid, record.get("name") or sid, record.get("url"), record.get("kind") or "watcher",
                                  record.get("parser"), bool(record.get("enabled")), country_code(record),
                                  record.get("geo_scope"), sectors, Jsonb(record), Jsonb(record)))  # fmt: skip

    def toggle(self, body: dict[str, Any]) -> dict[str, Any]:
        self._lock()
        source_id = body.get("id")
        enabled = bool(body.get("enabled"))
        stored = self.stored()
        normalized = load_registry({"sources": stored})["sources"]
        target = next((s for s in normalized if isinstance(s, dict) and s.get("id") == source_id), None)
        if target is None:
            return {"ok": True}  # the old route: an unknown id changes nothing
        was = bool(target.get("enabled"))
        if was == enabled:
            return {"ok": True}  # nothing visible changes: no write, no event
        changed = {**target, "enabled": enabled}  # the normalized STORED record: its counters are the baseline
        self.save_registry(stored, [changed if s is target else s for s in normalized])
        self.event(str(source_id), "toggle", {"enabled": was}, {"enabled": enabled})
        return {"ok": True}

    def save_registry(self, stored: list[dict[str, Any]], registry: list[Any]) -> None:
        """The old ``save_registry`` (call under ``_lock``): it persisted the WHOLE normalized registry, so every
        source that exists only through the normalization (or was just appended) is stored now, in the registry's
        order (``clock_timestamp``), and a stored source whose record differs is rewritten. The order never moves."""
        have = {s.get("id"): s for s in stored}
        for rec in registry:
            if not isinstance(rec, dict):
                continue
            if rec.get("id") not in have or rec != have[rec.get("id")]:
                self._write(rec)

    def event(self, source_id: str, action: str, before: Any, after: Any) -> None:
        self._rows(
            "insert into {s}.source_events (source_id, actor, action, before, after) "
            "values (%s, 'operator', %s, %s, %s)",
            (source_id, action, Jsonb(before), Jsonb(after)),
        )

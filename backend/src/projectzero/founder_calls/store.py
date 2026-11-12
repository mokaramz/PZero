"""The database side of Founder Calls (review 023): ONE reader that rebuilds the old ``founder_calls.json`` document
from the ordered tables (migration 0014), and the write path.

* ``load(conn, schema)`` -> the old document, or ``None`` when there is no archive and no row (the pure code then
  reads the old empty document). Its top level keeps the ARCHIVED key order (``version``, ``label``, ... as written),
  with ``companies`` / ``founders`` / ``calls`` rebuilt from the tables in ``pos`` order, so their key order is the
  original insertion order (Codex H-175); the old ``load`` defaulting applies (``core.loaded``): with no archive, or
  an archive missing a top-level key, the key is appended as the old first save wrote it (Codex H-179).
  Conviction reads founder calls through this reader too (``conviction/inputs.py``).
* ``apply(old, outcome, action, detail)`` writes an ``Outcome`` of the pure functions: only the records it lists as
  changed (``attrs.record`` and the mirrored columns; a new record goes after the last position of its table, the old
  dict append) and ONE ``fc_events`` row with those records before -> after. An outcome that changed nothing writes
  nothing. The caller holds the one write lock (after the import boundary) for the whole read-modify-write.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from projectzero.core.db import schema_ident
from projectzero.dealflow.intake.postgres import ensure_intake_open
from projectzero.founder_calls import core
from projectzero.founder_calls.routes import Outcome

ARCHIVE = "founder_calls.json"
TABLES = {"companies": "fc_companies", "founders": "fc_founders", "calls": "fc_calls"}


def _mirrors(coll: str, rec: dict[str, Any]) -> dict[str, Any]:
    def text(k: str) -> str | None:
        v = rec.get(k)
        return v if isinstance(v, str) else None

    if coll == "companies":
        return {"name": text("name")}
    if coll == "founders":
        return {"name": text("name"), "company_id": text("company_id")}
    return {"founder_id": text("founder_id"), "company_id": text("company_id"), "call_date": text("date")}


class FounderCallsStore:
    def __init__(self, conn: psycopg.Connection[Any], schema: str = "pz") -> None:
        self.conn = conn
        self._schema = schema
        self.s = schema_ident(schema)

    def _rows(self, query: str, params: Any = ()) -> list[dict[str, Any]]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql.SQL(query).format(s=self.s), params)
            return list(cur.fetchall()) if cur.description else []

    def _archive(self) -> Any:
        rows = self._rows("select raw from {s}.legacy_documents where path = %s", (ARCHIVE,))
        if not rows:
            return None
        try:
            return json.loads(bytes(rows[0]["raw"]).decode("utf-8"))  # keeps the archived key order
        except (UnicodeDecodeError, ValueError):
            return None

    def load(self) -> dict[str, Any] | None:
        archived = self._archive()
        objects: dict[str, dict[str, Any]] = {}
        for coll, table in TABLES.items():
            rows = self._rows(f"select id, attrs->'record' as record from {{s}}.{table} order by pos")
            objects[coll] = {str(r["id"]): r["record"] for r in rows}
        if archived is None and not any(objects.values()):
            return None
        # the old load() defaulting (Codex H-179): the archive, or the empty document when there is none, with every
        # missing top-level key appended as the old code wrote it on its first save (version, label, the objects)
        top = core.loaded(archived)
        return {k: objects.get(k, v) for k, v in top.items()}

    # ── the write ───────────────────────────────────────────────────────────────────────────────────────────────
    def lock(self) -> None:
        ensure_intake_open(self.conn, self._schema)  # the production write boundary: nothing before the import
        self._rows("select pg_advisory_xact_lock(hashtext(%s))", (f"{self._schema}.intake",))

    def apply(self, old: dict[str, Any] | None, outcome: Outcome, action: str, detail: dict[str, Any]) -> None:
        changed = {k: list(v) for k, v in (outcome.changed or {}).items() if v}
        if not changed or outcome.doc is old:
            return
        before: dict[str, dict[str, Any]] = {}
        after: dict[str, dict[str, Any]] = {}
        new_doc = outcome.doc
        for coll, ids in changed.items():
            table = TABLES[coll]
            prev = (old or {}).get(coll) or {}
            top = self._rows(f"select coalesce(max(pos), -1) as pos from {{s}}.{table}")[0]["pos"]
            for rid in ids:
                rec = new_doc[coll][rid]
                cols = _mirrors(coll, rec)
                names = ", ".join(cols)
                sets = ", ".join(f"{c} = %s" for c in cols)
                exists = self._rows(f"select 1 from {{s}}.{table} where id = %s", (rid,))
                record = "jsonb_build_object('record', %s::jsonb)"
                if exists:
                    update = f"update {{s}}.{table} set {sets}, attrs = attrs || {record} where id = %s"
                    self._rows(update, (*cols.values(), Jsonb(rec), rid))
                else:
                    top += 1
                    slots = ", ".join("%s" for _ in cols)
                    insert = f"insert into {{s}}.{table} (id, pos, {names}, attrs) values (%s, %s, {slots}, {record})"
                    self._rows(insert, (rid, top, *cols.values(), Jsonb(rec)))
                before.setdefault(coll, {})[rid] = prev.get(rid)
                after.setdefault(coll, {})[rid] = rec
        self._rows(
            "insert into {s}.fc_events (actor, action, before, after, detail) values ('operator', %s, %s, %s, %s)",
            (action, Jsonb(before), Jsonb(after), Jsonb(detail)),
        )

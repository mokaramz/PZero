"""The database side of Founder Radar (review 026a), part one: the ONE reader of the old ``radar_companies.json`` and
``radar_research.json`` documents, rebuilt from the ordered record tables (migration 0016), and their writes.

* ``load_companies()`` / ``load_research()`` -> the old document, or ``None`` when there is no archive and no row. The
  top level keeps the ARCHIVED key order with the old ``load()`` defaulting (``companies`` / ``domains`` default to
  ``{}``); the records come from the table in ``pos`` order, each in its OWN key order (a ``json`` column), and a
  leaked ``_dirty`` flag is never read back (decision a). Founder Radar, Conviction (IMQ gate E) and the evaluator all
  read radar companies through ``load_companies``.
* ``write_records(kind, old, new, action, detail)`` stores every record of ``new`` that differs from ``old`` (a new key
  goes after the last position) with one ``radar_events`` row each; nothing when nothing changed (decision e). The
  caller holds the one write lock.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Json, Jsonb

from projectzero.core.db import schema_ident
from projectzero.dealflow.intake.postgres import ensure_intake_open

KINDS: dict[str, tuple[str, str, str, str]] = {  # kind -> (archive, collection, table, event entity)
    "companies": ("radar_companies.json", "companies", "radar_companies", "company"),
    "research": ("radar_research.json", "domains", "radar_research", "research"),
}
NEVER_STORED = ("_dirty",)  # decision (a): the old GET's leaked flag


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _clean(record: Any) -> Any:
    return {k: v for k, v in record.items() if k not in NEVER_STORED} if isinstance(record, dict) else record


class FounderRadarStore:
    def __init__(self, conn: psycopg.Connection[Any], schema: str = "pz") -> None:
        self.conn = conn
        self._schema = schema
        self.s = schema_ident(schema)

    def _rows(self, query: str, params: Any = ()) -> list[dict[str, Any]]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql.SQL(query).format(s=self.s), params)
            return list(cur.fetchall()) if cur.description else []

    def _archive(self, path: str) -> Any:
        rows = self._rows("select raw from {s}.legacy_documents where path = %s", (path,))
        if not rows:
            return None
        try:
            return json.loads(bytes(rows[0]["raw"]).decode("utf-8-sig"))  # the archived key order; an optional BOM
        except (UnicodeDecodeError, ValueError):
            return None

    def _load(self, kind: str) -> dict[str, Any] | None:
        path, coll, table, _ = KINDS[kind]
        archived = self._archive(path)
        # json (not jsonb): ``record::text`` is the stored text, parsed here so every record keeps its own key order
        rows = self._rows(f"select key, record::text as record from {{s}}.{table} order by pos")
        if archived is None and not rows:
            return None
        top: dict[str, Any] = dict(archived) if isinstance(archived, dict) else {}
        top.setdefault(coll, {})  # the old load(): the collection defaults to {}
        records = {str(r["key"]): _clean(json.loads(r["record"])) for r in rows}
        return {k: (records if k == coll else v) for k, v in top.items()}

    def load_companies(self) -> dict[str, Any] | None:
        return self._load("companies")

    def load_research(self) -> dict[str, Any] | None:
        return self._load("research")

    # ── the write ───────────────────────────────────────────────────────────────────────────────────────────────
    def lock(self) -> None:
        ensure_intake_open(self.conn, self._schema)  # the production write boundary: nothing before the import
        self._rows("select pg_advisory_xact_lock(hashtext(%s))", (f"{self._schema}.intake",))

    def write_records(
        self, kind: str, old: Mapping[str, Any] | None, new: Mapping[str, Any], action: str, detail: dict[str, Any]
    ) -> list[str]:
        """Store every record of ``new`` that differs from ``old``; returns their keys (in document order)."""
        _, coll, table, entity = KINDS[kind]
        before_all = (old or {}).get(coll) or {}
        changed: list[str] = []
        top = self._rows(f"select coalesce(max(pos), -1) as pos from {{s}}.{table}")[0]["pos"]
        for key, rec in (new.get(coll) or {}).items():
            rec = _clean(rec)
            prev = before_all.get(key)
            if prev is not None and _same(_clean(prev), rec):
                continue
            if not self._rows(f"select 1 from {{s}}.{table} where key = %s", (key,)):
                top += 1
                self._rows(f"insert into {{s}}.{table} (key, pos, record) values (%s, %s, %s)",
                           (key, top, Json(rec)))  # fmt: skip
            else:
                self._rows(f"update {{s}}.{table} set record = %s, updated_at = now() where key = %s", (Json(rec), key))
            self._rows(
                "insert into {s}.radar_events (entity, key, actor, action, before, after, detail) "
                "values (%s, %s, 'operator', %s, %s, %s, %s)",
                (entity, key, action, None if prev is None else Jsonb(_clean(prev)), Jsonb(rec), Jsonb(detail)),
            )
            changed.append(key)
        return changed

    def write_document(self, key: str, body: Any, action: str, detail: dict[str, Any]) -> bool:
        """A radar document kept as a ``documents`` row (the metrics snapshot): stored only when it changed, with one
        ``radar_events`` row (entity ``metrics``)."""
        rows = self._rows("select body from {s}.documents where key = %s for update", (key,))
        prev = rows[0]["body"] if rows else None
        if prev is not None and _same(prev, body):
            return False
        self._rows(
            "insert into {s}.documents (key, body) values (%s, %s) on conflict (key) do update "
            "set body = excluded.body, updated_at = now()",
            (key, Jsonb(body)),
        )
        self._rows(
            "insert into {s}.radar_events (entity, key, actor, action, before, after, detail) "
            "values ('metrics', %s, 'operator', %s, %s, %s, %s)",
            (key, action, None if prev is None else Jsonb(prev), Jsonb(body), Jsonb(detail)),
        )
        return True

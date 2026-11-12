"""The database side of the Active Evaluator (review 024): ONE reader that rebuilds the old ``evaluations.json``
document from the ordered table (migration 0015), and the session write.

* ``load()`` -> the old document, or ``None`` when there is no archive and no row. The top level keeps the ARCHIVED
  key order with the old ``load()`` defaulting (``sessions`` defaults to ``{}``); ``sessions`` is rebuilt from the
  table in ``pos`` order, so its key order is the original insertion order (Codex H-183). The evaluator, Conviction
  (gate C, contradictions) and Founder Calls (``is_conversation``) all read sessions through it.
* ``write_sessions(old, new, action, detail)`` stores the sessions that differ between the two documents
  (``attrs.record`` and the mirrored columns; a new session goes after the last position) and one ``eval_events`` row
  per changed session. Nothing is written when nothing changed. The caller holds the one write lock.
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

ARCHIVE = "evaluations.json"


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _mirrors(rec: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    raw = rec.get("subject")
    subject: dict[str, Any] = raw if isinstance(raw, dict) else {}

    def text(v: Any) -> str | None:
        return v if isinstance(v, str) else None

    return text(rec.get("status")), text(subject.get("kind")), text(subject.get("name"))


class EvaluationsStore:
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
            return json.loads(bytes(rows[0]["raw"]).decode("utf-8-sig"))  # archived key order; an optional BOM
        except (UnicodeDecodeError, ValueError):
            return None

    def load(self) -> dict[str, Any] | None:
        archived = self._archive()
        rows = self._rows("select id, attrs->'record' as record from {s}.eval_sessions order by pos")
        if archived is None and not rows:
            return None
        top: dict[str, Any] = dict(archived) if isinstance(archived, dict) else {}
        top.setdefault("sessions", {})  # the old load(): sessions defaults to {}
        sessions = {str(r["id"]): r["record"] for r in rows}
        return {k: (sessions if k == "sessions" else v) for k, v in top.items()}

    # ── the write ───────────────────────────────────────────────────────────────────────────────────────────────
    def lock(self) -> None:
        ensure_intake_open(self.conn, self._schema)  # the production write boundary: nothing before the import
        self._rows("select pg_advisory_xact_lock(hashtext(%s))", (f"{self._schema}.intake",))

    def write_sessions(
        self, old: dict[str, Any] | None, new: dict[str, Any], action: str, detail: dict[str, Any]
    ) -> list[str]:
        """Store every session of ``new`` that differs from ``old``; returns their ids (in document order)."""
        before_all = (old or {}).get("sessions") or {}
        changed: list[str] = []
        top = self._rows("select coalesce(max(pos), -1) as pos from {s}.eval_sessions")[0]["pos"]
        for sid, rec in (new.get("sessions") or {}).items():
            prev = before_all.get(sid)
            if prev is not None and _same(prev, rec):
                continue
            status, kind, name = _mirrors(rec)
            if prev is None and not self._rows("select 1 from {s}.eval_sessions where id = %s", (sid,)):
                top += 1
                self._rows(
                    "insert into {s}.eval_sessions (id, pos, status, subject_kind, subject_name, attrs) "
                    "values (%s, %s, %s, %s, %s, jsonb_build_object('record', %s::jsonb))",
                    (sid, top, status, kind, name, Jsonb(rec)),
                )
            else:
                self._rows(
                    "update {s}.eval_sessions set status = %s, subject_kind = %s, subject_name = %s, "
                    "attrs = attrs || jsonb_build_object('record', %s::jsonb) where id = %s",
                    (status, kind, name, Jsonb(rec), sid),
                )
            self._rows(
                "insert into {s}.eval_events (session_id, actor, action, before, after, detail) "
                "values (%s, 'operator', %s, %s, %s, %s)",
                (sid, action, None if prev is None else Jsonb(prev), Jsonb(rec), Jsonb(detail)),
            )
            changed.append(sid)
        return changed

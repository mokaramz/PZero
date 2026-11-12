"""The content log (review 020): the old ``content.json`` behind ``/api/content``, as rows in ``pz.content_items``.

The old routes (``api/routers/network.py`` at revision 6c739b9), with the plan's decisions (Codex H-145 / H-147):

* ``view``: ``{**the archived document without items, "items": [the live records in list order]}``; no archived
  document reads as the old default ``{"items": []}``.
* ``save``: a falsy ``id`` generates ``c-%y%m%d%H%M%S`` (Berlin wall time) and, on a collision, ``-2``, ``-3``, ...
  (the old code overwrote; decision b); a non-empty string is used as sent; any other value is refused (400). Only the
  fields present are set, their JSON values stored as sent. A new item gets ``created`` = today and goes on top. An
  id with no row creates that item; a DELETED id is recreated fresh (only the body's fields, today, on top), its
  history kept (``create`` with ``{replaces_deleted: true}``). An edit that changes nothing writes no event.
* ``delete``: soft (``deleted_at``); ONE ``delete`` event on the live -> deleted transition only; no id, an unknown
  or an already deleted one is the old ``{ok: true}`` with nothing written; any present non-string id (``0``,
  ``false``, ``null`` included) is refused (``delete_id``).

Every write runs under the one write lock (after the import boundary). Errors: ``ContentError``.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from projectzero.core.db import schema_ident
from projectzero.dealflow.intake.postgres import ensure_intake_open
from projectzero.network.view import berlin_now

FIELDS = ("platform", "kind", "title", "url", "notes", "inbound", "status")  # the old CONTENT_FIELDS
MIRRORED = ("title", "platform", "kind", "status", "url", "created")
ID_NOT_STRING = "id must be a string"


class ContentError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _same(a: Any, b: Any) -> bool:
    """JSON equality: ``1`` and ``True`` (equal in Python) are different values."""
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _text(v: Any) -> str | None:
    return v if isinstance(v, str) else None


def delete_id(body: dict[str, Any]) -> str | None:
    """The delete id under the contract (Codex H-149): no ``id`` key is the old ``{ok: true}`` (``None``); a string is
    used as sent (an unknown one, or ``""``, matches nothing); ANY other present value, ``0`` / ``false`` / ``null``
    included, is refused (400). Checked before any connection opens."""
    if "id" not in body:
        return None
    raw = body["id"]
    if not isinstance(raw, str):
        raise ContentError(400, ID_NOT_STRING)
    return raw


def request_id(body: dict[str, Any]) -> str | None:
    """The body's id under the contract: ``None`` for a falsy one (the old ``body.get("id") or ...``), the string as
    sent, else ``ContentError(400)``. Checked before any connection opens."""
    raw = body.get("id")
    if not raw:
        return None
    if not isinstance(raw, str):
        raise ContentError(400, ID_NOT_STRING)
    return raw


class ContentStore:
    def __init__(self, conn: psycopg.Connection[Any], schema: str = "pz") -> None:
        self.conn = conn
        self._schema = schema
        self.s = schema_ident(schema)

    def _rows(self, query: str, params: Any = ()) -> list[dict[str, Any]]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql.SQL(query).format(s=self.s), params)
            return list(cur.fetchall()) if cur.description else []

    def _first(self, query: str, params: Any = ()) -> dict[str, Any] | None:
        rows = self._rows(query, params)
        return rows[0] if rows else None

    # ── read ────────────────────────────────────────────────────────────────────────────────────────────────────
    def view(self) -> dict[str, Any]:
        doc = self._first("select body from {s}.documents where key = 'content.json'")
        body = doc["body"] if doc else None
        rest = {k: v for k, v in body.items() if k != "items"} if isinstance(body, dict) else {}
        live = "select attrs->'record' as record from {s}.content_items where deleted_at is null order by pos"
        items = [r["record"] for r in self._rows(live)]
        return {**rest, "items": items}

    # ── writes ──────────────────────────────────────────────────────────────────────────────────────────────────
    def _lock(self) -> None:
        ensure_intake_open(self.conn, self._schema)  # the production write boundary: nothing before the import
        self._rows("select pg_advisory_xact_lock(hashtext(%s))", (f"{self._schema}.intake",))

    def _event(self, item_id: str, action: str, before: Any, after: Any, detail: dict[str, Any] | None = None) -> None:
        self._rows(
            "insert into {s}.content_item_events (item_id, actor, action, before, after, detail) "
            "values (%s, 'operator', %s, %s, %s, %s)",
            (item_id, action, None if before is None else Jsonb(before), Jsonb(after), Jsonb(detail or {})),
        )

    def _top(self) -> int:
        row = self._first("select coalesce(min(pos), 0) - 1 as pos from {s}.content_items")
        return int(row["pos"]) if row else -1

    def _generated_id(self, now: datetime) -> str:
        base = "c-" + berlin_now(now).strftime("%y%m%d%H%M%S")
        taken = {r["id"] for r in self._rows("select id from {s}.content_items where id = %s or id like %s",
                                             (base, base + "-%"))}  # fmt: skip
        if base not in taken:
            return base
        n = 2
        while f"{base}-{n}" in taken:
            n += 1
        return f"{base}-{n}"

    def _write(self, item_id: str, record: dict[str, Any], *, pos: int | None = None, revive: bool = False) -> None:
        cols = {k: _text(record.get(k)) for k in MIRRORED}
        self._rows(
            "update {s}.content_items set title = %s, platform = %s, kind = %s, status = %s, url = %s, created = %s, "
            "attrs = attrs || jsonb_build_object('record', %s::jsonb), pos = coalesce(%s, pos), "
            "deleted_at = case when %s then null else deleted_at end, "
            "created_at = case when %s then now() else created_at end where id = %s",
            (*cols.values(), Jsonb(record), pos, revive, revive, item_id),
        )

    def save(self, body: dict[str, Any], now: datetime) -> dict[str, Any]:
        given = request_id(body)
        self._lock()
        iid = given or self._generated_id(now)
        row = self._first("select id, attrs->'record' as record, deleted_at from {s}.content_items where id = %s",
                          (iid,))  # fmt: skip
        if row is not None and row["deleted_at"] is None:  # an edit of a live item
            before = row["record"] if isinstance(row["record"], dict) else {}
            record = copy.deepcopy(before)
            changed = [k for k in FIELDS if k in body and (k not in before or not _same(before[k], body[k]))]
            for k in FIELDS:
                if k in body:
                    record[k] = body[k]
            if changed:
                self._write(iid, record)
                self._event(iid, "save", {k: before.get(k) for k in changed}, {k: record[k] for k in changed})
            return {"ok": True, "id": iid}
        record = {"id": iid, "created": berlin_now(now).strftime("%Y-%m-%d")}  # the old new item
        for k in FIELDS:
            if k in body:
                record[k] = body[k]
        top = self._top()
        if row is None:
            self._rows(
                "insert into {s}.content_items (id, pos, title, platform, kind, status, url, created, attrs) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, jsonb_build_object('record', %s::jsonb))",
                (iid, top, *(_text(record.get(k)) for k in MIRRORED), Jsonb(record)),
            )
            self._event(iid, "create", None, record)
        else:  # a deleted id named again: a fresh item on top, its history kept (Codex H-147)
            self._write(iid, record, pos=top, revive=True)
            self._event(iid, "create", None, record, {"replaces_deleted": True})
        return {"ok": True, "id": iid}

    def delete(self, body: dict[str, Any]) -> dict[str, Any]:
        iid = delete_id(body)
        if not iid:
            return {"ok": True}  # no id, or "": the old route matched nothing
        self._lock()
        row = self._first("select attrs->'record' as record from {s}.content_items "
                          "where id = %s and deleted_at is null for update", (iid,))  # fmt: skip
        if row is None:
            return {"ok": True}  # unknown or already deleted: the old response, nothing written
        self._rows("update {s}.content_items set deleted_at = now() where id = %s", (iid,))
        self._event(iid, "delete", row["record"], {"deleted": True})
        return {"ok": True}

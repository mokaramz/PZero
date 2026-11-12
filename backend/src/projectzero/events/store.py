"""Events reads on ``pz`` (review 015). Reads only; the writes are review 016.

``load(conn, schema, today)`` reads everything the Events views need in the caller's (read-only) transaction:

* **events / leads:** each row's current record (``record_of``: ``attrs.record`` once the app writes it, else the
  imported ``legacy``), in the old ``events.json`` order. Events: the archived file order, then rows created here by
  ``created_at``, then ``id`` (the old file appended). Leads: rows created here first, newest first (the old
  ``add_leads`` inserted at the front), then the archived ones in file order. The old ``listing`` sort is stable, so
  ties keep this order;
* **pins:** for a start / end written as free text ("Sept 20"), the stored ``start_date`` / ``end_date``, a date or
  NULL (review 014 resolved the missing year once, at the import clock); ``engine`` uses that result instead of
  re-reading the words with today's year (review 015, Codex H-101 / H-103);
* **documents:** ``event_sources.json`` (each source's configured city), ``event_health.json`` (the last scan) and
  ``scout_intake.json#rest`` (the Scout 00 event reports);
* **people:** the one people reader (``network.store.load_people``), for Where should I go and the weekend planner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from projectzero.core.db import schema_ident
from projectzero.events.engine import Pins
from projectzero.events.when import free_text_form
from projectzero.network.store import load_people

DOCS = ("event_sources.json", "event_health.json", "scout_intake.json#rest")

_ROWS = """
    with arch as (
        select (e.value->>'id') as id, min(e.ord) as pos
        from {s}.legacy_documents d, jsonb_array_elements(d.parsed->{key}) with ordinality as e(value, ord)
        where d.path = 'events.json' and jsonb_typeof(d.parsed->{key}) = 'array'
        group by 1
    )
    select t.id, t.attrs, t.legacy{dates}
    from {s}.{table} t left join arch a on a.id = t.id
    order by {order}
"""
# events: the old file appended new events; leads: the old add_leads inserted new leads at the FRONT (newest first)
_ORDER = {
    "events": "a.pos nulls last, t.created_at, t.id",
    "event_leads": "(a.pos is not null), case when a.pos is null then t.created_at end desc, a.pos, t.id",
}


def record_of(row: dict[str, Any]) -> dict[str, Any]:
    """Today's record of an event / lead row: ``attrs.record`` once the app wrote it, else the imported ``legacy``;
    a row with neither is its flattened ``attrs`` and id."""
    raw = row.get("attrs")
    attrs: dict[str, Any] = raw if isinstance(raw, dict) else {}
    rec = attrs.get("record")
    if isinstance(rec, dict):
        return rec
    legacy = row.get("legacy")
    if isinstance(legacy, dict):
        return legacy
    return {**attrs, "id": row["id"]}


def pins_of(record: dict[str, Any], row: dict[str, Any]) -> dict[str, date | None]:
    """The stored result of each side the record states as free text: the persisted date, or ``None`` when it was
    stored as no date. Which sides are free text is decided by the value's FORM (``when.free_text_form``), never by
    re-reading it with today's date: "Feb 29" stored in a leap year keeps its date in the next year, and one stored as
    no date in a non-leap year does not become a date in the next leap year (Codex H-103)."""
    out: dict[str, date | None] = {}
    for side, column in (("start", "start_date"), ("end", "end_date")):
        if free_text_form(record.get(side)) and column in row:
            value = row[column]
            out[side] = value if isinstance(value, date) else None
    return out


@dataclass
class EventsData:
    events: list[dict[str, Any]]
    leads: list[dict[str, Any]]
    pins: dict[str, Pins] = field(default_factory=dict)
    documents: dict[str, Any] = field(default_factory=dict)
    people: list[dict[str, Any]] = field(default_factory=list)

    def source_city(self) -> dict[Any, str]:
        """source id -> its configured city (the old ``listing``'s ``src_city``)."""
        doc = self.documents.get("event_sources.json")
        srcs = (doc if isinstance(doc, dict) else {}).get("sources") or []
        return {s.get("id"): s.get("city", "") for s in srcs if isinstance(s, dict)}

    def health(self) -> dict[str, Any]:
        """The persisted Event Source Health (the old ``load_health``; absent -> the empty state)."""
        doc = self.documents.get("event_health.json")
        if doc is not None:
            return doc if isinstance(doc, dict) else {}
        return {"scan_time": "", "totals": {}, "sources": [], "note": "No event scan yet — press Scan sources."}


def _rows(conn: psycopg.Connection[Any], schema: str, table: str, key: str, dates: bool) -> list[dict[str, Any]]:
    query = sql.SQL(_ROWS).format(
        s=schema_ident(schema),
        table=sql.Identifier(table),
        key=sql.Literal(key),
        dates=sql.SQL(", t.start_date, t.end_date" if dates else ""),
        order=sql.SQL(_ORDER[table]),
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query)
        return cur.fetchall()


def load(
    conn: psycopg.Connection[Any], schema: str, today: date, *, people: bool = True, records: bool = True
) -> EventsData:
    """``records=False`` reads the documents only (the health view needs nothing else)."""
    events: list[dict[str, Any]] = []
    pins: dict[str, Pins] = {}
    leads: list[dict[str, Any]] = []
    if records:
        for row in _rows(conn, schema, "events", "events", dates=True):
            rec = record_of(row)
            events.append(rec)
            if pinned := pins_of(rec, row):
                pins[str(rec.get("id", row["id"]))] = pinned
        leads = [record_of(r) for r in _rows(conn, schema, "event_leads", "leads", dates=False)]
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("select key, body from {}.documents where key = any(%s)").format(schema_ident(schema)),
            (list(DOCS),),
        )
        documents = dict(cur.fetchall())
    return EventsData(events, leads, pins, documents, load_people(conn, schema) if people else [])

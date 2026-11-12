"""The old ``inbox.json`` records, one per old inbox record, in the old order (reviews 027a / 025b).

The importer merged inbox records that resolve to one company into a survivor (``candidate_aliases``), keeping each
absorbed record only as a ``merged_record`` observation. The old inbox held every one of them, and the views that read
the old inbox (Validation, the Map's Deal Flow layer, the ecosystem coverage) read them all again:

* each survivor's OWN record counts when it is an old inbox record, or when it absorbed none (a candidate the new
  intake created, or one imported from another origin);
* each absorbed inbox record is read AT ITS OWN archived inbox position, through the consumer's record rule, with the
  survivor's current status and notes (``{**row, "legacy": record}``); so a survivor whose own record is a Scout Intake
  item but which absorbed an inbox record is that inbox record (its Scout item is read from the archive, as before);
* records without an archived position (the new intake's) follow in the view order.

Each consumer keeps its own filters (which survivors it reads) and its own record rule. ``OldRecord.row`` is the
survivor, so a consumer attaches the survivor's current proposal to each of its records.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from projectzero.core.db import schema_ident
from projectzero.dealflow.ranking.service import is_legacy_inbox_record, ranking_input

_ABSORBED = (
    "select candidate_id, payload->'merged_record' as record from {}.observations "
    "where payload ? 'merged_record' order by id"
)
_POSITIONS = (
    "select (e.value->>'id') as id, min(e.ord) as pos "
    "from {}.legacy_documents d, jsonb_array_elements(d.parsed->'candidates') with ordinality as e(value, ord) "
    "where d.path = 'inbox.json' and jsonb_typeof(d.parsed->'candidates') = 'array' group by 1"
)
_NO_POSITION = 1 << 62  # after every archived inbox position


@dataclass(frozen=True)
class Absorbed:
    """The absorbed inbox records by survivor id (in observation order) and every archived inbox position."""

    records: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    positions: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class OldRecord:
    record: dict[str, Any]
    row: dict[str, Any]  # the survivor


def load_absorbed(conn: psycopg.Connection[Any], schema: str) -> Absorbed:
    s = schema_ident(schema)
    records: dict[str, list[dict[str, Any]]] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL(_ABSORBED).format(s))
        for r in cur.fetchall():
            if is_legacy_inbox_record(r["record"]):
                records.setdefault(str(r["candidate_id"]), []).append(r["record"])
        cur.execute(sql.SQL(_POSITIONS).format(s))
        positions = {str(r["id"]): int(r["pos"]) for r in cur.fetchall()}
    return Absorbed(records=records, positions=positions)


def ranking_record(row: dict[str, Any]) -> dict[str, Any]:
    """The default record rule: the record the ranking reads (the Map, the ecosystem coverage)."""
    return ranking_input(row)[0]


def old_inbox(
    rows: Iterable[dict[str, Any]],
    absorbed: Absorbed,
    record_of: Callable[[dict[str, Any]], dict[str, Any]] = ranking_record,
) -> list[OldRecord]:
    """The old inbox records of ``rows`` (candidate rows in the view order, already filtered by the consumer)."""
    out: list[tuple[int, int, OldRecord]] = []
    for i, row in enumerate(rows):
        mine = absorbed.records.get(str(row["id"]), [])
        own = [row] if is_legacy_inbox_record(row.get("legacy")) or not mine else []
        for r in [*own, *({**row, "legacy": m} for m in mine)]:
            c = record_of(r)
            c.setdefault("id", row["id"])
            out.append((absorbed.positions.get(str(c["id"]), _NO_POSITION), i, OldRecord(c, row)))
    out.sort(key=lambda x: (x[0], x[1]))  # stable: a survivor's records keep their order on equal keys
    return [r for _pos, _i, r in out]


def proposals_of(old: Iterable[OldRecord], proposal_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The old ``triage_proposals.json`` keyed by inbox record id: the survivor's current proposal for each record."""
    out: dict[str, Any] = {}
    for r in old:
        p = proposal_rows.get(str(r.row["id"]))
        if p is not None:
            out[str(r.record["id"])] = p
    return out

"""The database side of Validation (review 027a): ``load(conn, schema, now) -> ValidationInputs``, in ONE read
transaction. Validation's reads never write (decision a).

Where each old input comes from:

* ``inbox.json`` candidates: ``candidates`` in the view order, through ``candidate_record`` (decision f: a candidate
  the new intake created gets ``first_seen`` = the Berlin date of ``first_seen_at`` and keeps the intake's own
  ``discovery_tier``). The candidates imported ONLY from the retired Scout views are left out, as on the Map
  (decision i there): their Scout Intake items are read from the archive, and counting them twice would change counts.
* ``triage_proposals.json``: the current ``triage_proposals``, keyed by the inbox record id.
* ``real_data.json`` signals: ``conviction_entries`` through the Conviction store (file order).
* ``founder_calls.json``: the Founder Calls reader (023, archived order).
* ``sources.json``: the stored source registry.
* ``queue_routing.json``: ``candidate_routing`` (routes) plus ``documents['queue_routing.json#rest']`` (``left_queue``).
* ``inference_ledger.jsonl``: ``model_ledger`` in insertion order, each row as ``{ts, usd}``, ``ts`` in Berlin time.
* ``triage_decisions.jsonl``, ``verification_decisions.jsonl``, the four ``validation/*.jsonl`` logs,
  ``scout_intake.json``, ``news/events.json`` and ``sources/network.json``: the byte-exact archive (``utf-8-sig``) in
  line / key order; a missing file reads as its old default. 027b moves the four Validation logs into a table.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from projectzero.conviction.store import ConvictionStore
from projectzero.conviction.store import record_of as conviction_record
from projectzero.core.db import schema_ident
from projectzero.dealflow.inbox_view import candidate_rows
from projectzero.dealflow.ranking.service import is_legacy_inbox_record
from projectzero.dealflow.sources.store import SourcesStore
from projectzero.dealflow.triage.view import proposal_record, route_record
from projectzero.founder_calls.store import FounderCallsStore
from projectzero.map.inputs import RETIRED_ORIGINS
from projectzero.network.view import berlin_now, berlin_today
from projectzero.validation.inputs_model import ValidationInputs, candidate_record, inputs_from_docs

JSON_ARCHIVES = ("scout_intake.json", "news/events.json", "sources/network.json")
TEXT_ARCHIVES = (
    "triage_decisions.jsonl",
    "verification_decisions.jsonl",
    "validation/outcomes.jsonl",
    "validation/audits.jsonl",
    "validation/snapshots.jsonl",
    "validation/scout_feedback.jsonl",
)
LEDGER_TS = "%Y-%m-%dT%H:%M:%S"  # the old ``ledger.now_ts()``
_PROPOSALS = (
    "select distinct on (candidate_id) * from {}.triage_proposals "
    "order by candidate_id, is_current desc, proposed_at desc, id desc"
)
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


def _old_inbox(row: dict[str, Any]) -> bool:
    origins = row.get("origins") or []
    return not origins or not set(origins) <= RETIRED_ORIGINS


def _inbox(
    rows: list[dict[str, Any]],
    absorbed: dict[str, list[dict[str, Any]]],
    positions: dict[str, int],
    proposal_rows: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The old ``inbox.json`` candidates, one record per old inbox record, in the old order.

    The importer merged inbox records that resolve to one company into a survivor; each absorbed record is kept as a
    ``merged_record`` observation. The old inbox held every one of them, so each is read again AT ITS OWN archived
    position, through the same ``candidate_record`` rule with the survivor's current status and notes. A survivor's
    own record is read when it is an old inbox record, or when it absorbed none (a candidate the new intake created,
    decision f); a survivor whose own record is a Scout Intake item but which absorbed an inbox record is that inbox
    record (its Scout item is read from the archive, as before). Records without an archived position (the new
    intake's) follow in the view order. The survivor's current proposal is the proposal of each of its records."""
    out: list[tuple[int, int, dict[str, Any], dict[str, Any] | None]] = []
    for i, row in enumerate(rows):
        if not _old_inbox(row):
            continue
        own_inbox = is_legacy_inbox_record(row.get("legacy"))
        records = [row] if own_inbox or not absorbed.get(str(row["id"])) else []
        records += [{**row, "legacy": m} for m in absorbed.get(str(row["id"]), [])]
        p = proposal_rows.get(str(row["id"]))
        for r in records:
            c = candidate_record(r)  # decision (f)
            c.setdefault("id", row["id"])
            out.append((positions.get(str(c["id"]), _NO_POSITION), i, c, p))
    out.sort(key=lambda x: (x[0], x[1]))  # stable: a survivor's records keep their order on equal keys
    proposals = {str(c["id"]): p for _pos, _i, c, p in out if p is not None}
    return [c for _pos, _i, c, _p in out], proposals


def _text(raw: Any) -> str:
    try:
        return bytes(raw).decode("utf-8-sig")
    except UnicodeDecodeError:
        return ""  # the old ``storage.read_text``: undecodable -> ""


def _parse(raw: Any) -> Any:
    try:
        return json.loads(bytes(raw).decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return None  # tolerant: each consumer applies its old default


def load(conn: psycopg.Connection[Any], schema: str, now: datetime) -> ValidationInputs:
    s = schema_ident(schema)
    rows = candidate_rows(conn, schema)
    stored_sources = SourcesStore(conn, schema).stored()
    signals = [conviction_record(r) for r in ConvictionStore(conn, schema).entry_rows()]
    calls = FounderCallsStore(conn, schema).load()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL(_PROPOSALS).format(s))
        proposal_rows = {str(r["candidate_id"]): proposal_record(r) for r in cur.fetchall()}
        cur.execute(sql.SQL("select * from {}.candidate_routing order by candidate_id").format(s))
        routes = {str(r["candidate_id"]): route_record(r) for r in cur.fetchall()}
        cur.execute(sql.SQL("select body from {}.documents where key = 'queue_routing.json#rest'").format(s))
        rest = cur.fetchone()
        cur.execute(sql.SQL("select at, usd from {}.model_ledger order by id").format(s))
        ledger = [{"ts": berlin_now(r["at"]).strftime(LEDGER_TS), "usd": float(r["usd"] or 0)} for r in cur.fetchall()]
        cur.execute(
            sql.SQL("select path, raw from {}.legacy_documents where path = any(%s)").format(s),
            ([*JSON_ARCHIVES, *TEXT_ARCHIVES],),
        )
        archived = {r["path"]: r["raw"] for r in cur.fetchall()}
        cur.execute(sql.SQL(_ABSORBED).format(s))
        absorbed: dict[str, list[dict[str, Any]]] = {}
        for r in cur.fetchall():
            if is_legacy_inbox_record(r["record"]):
                absorbed.setdefault(str(r["candidate_id"]), []).append(r["record"])
        cur.execute(sql.SQL(_POSITIONS).format(s))
        positions = {str(r["id"]): int(r["pos"]) for r in cur.fetchall()}

    inbox, proposals = _inbox(rows, absorbed, positions, proposal_rows)

    rest_body = rest["body"] if rest and isinstance(rest["body"], dict) else {}
    docs: dict[str, Any] = {
        "inbox.json": {"candidates": inbox},
        "triage_proposals.json": {"proposals": proposals},
        "real_data.json": {"signals": signals},
        "sources.json": {"sources": stored_sources},
        "queue_routing.json": {**rest_body, "routes": routes, "left_queue": rest_body.get("left_queue") or {}},
        "inference_ledger.jsonl": "".join(json.dumps(r) + "\n" for r in ledger),
    }
    if calls is not None:
        docs["founder_calls.json"] = calls
    for path in JSON_ARCHIVES:
        if path in archived:
            docs[path] = _parse(archived[path])
    for path in TEXT_ARCHIVES:
        docs[path] = _text(archived[path]) if path in archived else ""
    return inputs_from_docs(docs, berlin_today(now))

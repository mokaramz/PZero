"""The database side of Validation (review 027a) and News & Learning (028a): ``load_docs(conn, schema, now)`` reads
every old input document in ONE read transaction, ``load`` builds ``ValidationInputs`` from them (News builds
``NewsInputs`` from the same documents, ``news.inputs.load``). The reads never write (decision a).

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
* the four ``validation/*.jsonl`` logs: ``validation_log`` (review 027b) through ``validation.store.texts``, each
  log's lines in ``seq`` order.
* every News file through ``news.store``: ``news/events.json`` and ``news/actions.jsonl`` from ``news_events`` /
  ``news_events_rest`` / ``news_actions`` (review 028b); the run's logs (``news/{runs,disagreements,source_log,
  source_history,weekly}.jsonl``) from ``news_logs`` and its documents (``news/{source_metrics,source_state,
  feeds_extra,run_state,feed_cooldown}.json``) from ``news_documents`` (review 028c). No News archive is read.
* ``triage_decisions.jsonl``, ``verification_decisions.jsonl``, ``scout_intake.json``, ``sources/network.json`` and
  ``scan_history.json``: the byte-exact archive (``utf-8-sig``) in line / key order, else (the JSON files) the
  imported ``documents`` row; a missing file reads as its old default.
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
from projectzero.dealflow import inbox_records
from projectzero.dealflow.inbox_view import candidate_rows
from projectzero.dealflow.sources.store import SourcesStore
from projectzero.dealflow.triage.view import proposal_record, route_record
from projectzero.founder_calls.store import FounderCallsStore
from projectzero.map.inputs import RETIRED_ORIGINS
from projectzero.network.view import berlin_now, berlin_today
from projectzero.news import store as news_store
from projectzero.validation import store
from projectzero.validation.inputs_model import ValidationInputs, candidate_record, inputs_from_docs

JSON_ARCHIVES = (
    "scout_intake.json",
    "sources/network.json",
    "scan_history.json",
)
TEXT_ARCHIVES = (
    "triage_decisions.jsonl",
    "verification_decisions.jsonl",
)
LEDGER_TS = "%Y-%m-%dT%H:%M:%S"  # the old ``ledger.now_ts()``
_PROPOSALS = (
    "select distinct on (candidate_id) * from {}.triage_proposals "
    "order by candidate_id, is_current desc, proposed_at desc, id desc"
)


def _old_inbox(row: dict[str, Any]) -> bool:
    origins = row.get("origins") or []
    return not origins or not set(origins) <= RETIRED_ORIGINS


def archived_text(raw: Any) -> str:
    try:
        return bytes(raw).decode("utf-8-sig")
    except UnicodeDecodeError:
        return ""  # the old ``storage.read_text``: undecodable -> ""


def parse_archived(raw: Any) -> Any:
    try:
        return json.loads(bytes(raw).decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return None  # tolerant: each consumer applies its old default


def load(conn: psycopg.Connection[Any], schema: str, now: datetime) -> ValidationInputs:
    return inputs_from_docs(load_docs(conn, schema, now), berlin_today(now))


def load_docs(conn: psycopg.Connection[Any], schema: str, now: datetime) -> dict[str, Any]:
    """Every old input document Validation and News read, as old-format documents (``inputs_from_docs``)."""
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
        cur.execute(sql.SQL("select key, body from {}.documents where key = any(%s)").format(s), (list(JSON_ARCHIVES),))
        stored = {r["key"]: r["body"] for r in cur.fetchall()}
    old = inbox_records.old_inbox(
        [r for r in rows if _old_inbox(r)], inbox_records.load_absorbed(conn, schema), candidate_record
    )  # decision (f); the absorbed inbox records (review 025b)
    inbox = [r.record for r in old]
    proposals = inbox_records.proposals_of(old, proposal_rows)

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
            docs[path] = parse_archived(archived[path])
        elif path in stored:
            docs[path] = stored[path]
    for path in TEXT_ARCHIVES:
        docs[path] = archived_text(archived[path]) if path in archived else ""
    docs.update(store.texts(conn, schema))  # the four Validation logs (027b), in seq order
    events = news_store.events_doc(conn, schema)  # the News tables (028b)
    if events is not None:
        docs["news/events.json"] = events
    docs["news/actions.jsonl"] = news_store.actions_text(conn, schema)
    docs.update(news_store.log_texts(conn, schema))  # the run's logs (028c)
    docs.update(news_store.documents(conn, schema))  # the run's documents (028c)
    return docs

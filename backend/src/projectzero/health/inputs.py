"""The database adapter behind System health (review 032a): ``HealthInputs`` from ONE connection.

The caller opens that connection with ``core.db.snapshot_transaction`` (REPEATABLE READ, READ ONLY, set before the
first query), so both reads see one committed state. Nothing here opens a connection or writes; the paid switch and
the key presence are read from the environment (never a key's value).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from projectzero.conviction.inputs import inputs_from, load_documents
from projectzero.conviction.store import ConvictionStore, record_of
from projectzero.core.db import schema_ident
from projectzero.core.inference import config as icfg
from projectzero.dealflow.inbox_view import candidate_rows
from projectzero.dealflow.ranking.service import ranking_input
from projectzero.dealflow.sources.store import SourcesStore
from projectzero.dealflow.triage import auto as triage_auto
from projectzero.dealflow.triage import view as triage_view
from projectzero.ecosystems.store import EcosystemsStore
from projectzero.health.inputs_model import HealthInputs
from projectzero.jobs import store as jobs_store
from projectzero.network.store import load_people
from projectzero.network.view import berlin_now
from projectzero.validation import inputs as validation_inputs
from projectzero.validation.inputs import parse_archived
from projectzero.validation.inputs_model import inputs_from_docs as validation_from_docs
from projectzero.watch import targets as watch_targets

logger = logging.getLogger(__name__)
LEDGER_TS = "%Y-%m-%dT%H:%M:%S"


def _rows(conn: psycopg.Connection[Any], s: sql.Identifier, query: str, params: Any = ()) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL(query).format(s=s), params)
        return list(cur.fetchall())


def _document(conn: psycopg.Connection[Any], s: sql.Identifier, key: str, default: Any) -> Any:
    rows = _rows(conn, s, "select body from {s}.documents where key = %s", (key,))
    return rows[0]["body"] if rows else default


def _archived_first(conn: psycopg.Connection[Any], s: sql.Identifier, path: str, key: str, default: Any) -> Any:
    """A document nothing in the new app writes, in the OLD KEY ORDER: the byte-exact archive (``documents`` is jsonb,
    which reorders object keys; the order decides the payload's key order), else the ``documents`` row."""
    rows = _rows(conn, s, "select raw from {s}.legacy_documents where path = %s", (path,))
    if rows:
        parsed = parse_archived(rows[0]["raw"])
        return default if parsed is None else parsed
    return _document(conn, s, key, default)


def ledger_line(row: dict[str, Any]) -> dict[str, Any]:
    """A ``model_ledger`` row as the old ``inference_ledger.jsonl`` line (``role``: the generated column, so an
    imported row keeps the old ledger's role, decision g)."""
    detail = row.get("detail") or {}
    return {**detail, "ts": berlin_now(row["at"]).strftime(LEDGER_TS), "purpose": row["purpose"],
            "provider": row["provider"], "model": row["model"], "entity_id": row["entity_ref"],
            "usd": float(row["usd"] or 0), "input_tokens": row["tokens_in"], "output_tokens": row["tokens_out"],
            "cached": row["cached"], "outcome": row["outcome"], "role": row["role"]}  # fmt: skip


def load(conn: psycopg.Connection[Any], schema: str, now: datetime) -> HealthInputs:
    """``now``: the request instant as naive Berlin wall time."""
    s = schema_ident(schema)
    docs = validation_inputs.load_docs(conn, schema, now)  # the old-format documents Validation and News read
    validation = validation_from_docs(docs, now.date())
    people = load_people(conn, schema)
    operator = inputs_from(load_documents(conn, schema), people).operator
    triage = triage_view.load(conn, schema)
    try:
        coverage = EcosystemsStore(conn, schema).snapshot(now).inputs
    except (ValueError, TypeError, KeyError):  # the registry could not be read: the old "temporarily unavailable"
        logger.exception("health: the coverage inputs could not be built")
        coverage = None
    inbox = docs.get("inbox.json")
    return HealthInputs(
        sources=SourcesStore(conn, schema).stored(),
        scan_history=docs.get("scan_history.json", {"scans": []}),
        candidates=inbox.get("candidates") if isinstance(inbox, dict) else None,
        auto_runs=triage.auto_runs,
        proposals=triage.proposals,
        aliases=triage.aliases,
        triage_next_try=triage_auto.next_try(conn, schema),  # review 035b: the retry state's earliest next try
        research_questions=(
            _archived_first(conn, s, "research_questions.json", "research_questions.json", {}) or {}
        ).get("questions")
        or {},
        watch_targets={"targets": watch_targets.effective_targets(conn, schema)},  # review 037a: the Watchlist's
        watch_candidates=watch_targets.watch_candidates(conn, schema)[0],  # targets and watched set (revision 2)
        watch_events=list(operator.watch_events),  # the ONE trigger reader, through Conviction's loader
        job_state={str(r["job"]): r["detail"] for r in _rows(conn, s, "select job, detail from {s}.job_state")},
        config=operator.config,
        event_health=_document(conn, s, "event_health.json", {}),
        runs=[r["detail"] for r in _rows(conn, s, "select detail from {s}.job_runs order by id")],
        runners=jobs_store.runner_records(conn, schema),  # 032c: the archive overlaid by source (the ONE reader)
        ledger=[ledger_line(r) for r in _rows(conn, s, "select * from {s}.model_ledger order by id")],
        inference_config=icfg.load(),
        paid=icfg.paid_enabled(os.environ),
        keys={n: bool(str(os.environ.get(n) or "").strip()) for n in icfg.KEY_ENVS},
        validation=validation,
        news=validation.news_inputs,
        coverage=coverage,
        queue_routing=_archived_first(conn, s, "queue_routing.json", "queue_routing.json#rest", {}),
        signals=[record_of(r) for r in ConvictionStore(conn, schema).entry_rows()],
        inbox_decisions=[str(ranking_input(r)[0].get("decision") or "") for r in candidate_rows(conn, schema)],
        lock=jobs_store.lock_status(conn, schema, now),
    )

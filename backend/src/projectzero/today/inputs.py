"""The database adapter behind Today (review 030a, revision 2): ``TodayInputs`` from ONE connection.

The caller opens that connection with ``core.db.snapshot_transaction`` (REPEATABLE READ, READ ONLY, set before the
first query), so every reader below sees ONE committed state even when an operator edit commits between two of the
reads (Codex H-287). Nothing here opens a connection or writes.

Each input is read once (decision a): the Conviction documents and the people feed both the pipeline and the operator
inputs; the pipeline is built at the request clock with no IMQ persist. The pure parts that the old code ran inside
its own ``try`` (the pipeline build, the triage view build) fail into the "temporarily unavailable" sections as
before; a database error is not caught (the transaction is aborted anyway, so the request fails as a whole).
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from projectzero.conviction import pipeline
from projectzero.conviction.inputs import inputs_from, load_documents
from projectzero.conviction.store import ConvictionStore, record_of
from projectzero.core.db import schema_ident
from projectzero.dealflow.inbox_view import candidate_rows
from projectzero.dealflow.triage import view as triage_view
from projectzero.events import store as events_store
from projectzero.founder_calls.store import FounderCallsStore
from projectzero.network.store import load_people
from projectzero.today.inputs_model import UNREADABLE, TodayInputs

logger = logging.getLogger(__name__)

AfterRead = Callable[[], None]


def in_inbox_order(proposals: dict[str, dict[str, Any]], order: list[str]) -> dict[str, dict[str, Any]]:
    """Decision g / h: the triage summaries keyed in the inbox view order (the old ``triage_review.view()`` iterated
    the inbox); a summary of a candidate the view does not list (none expected) keeps its place after them."""
    out = {cid: proposals[cid] for cid in order if cid in proposals}
    out.update((cid, p) for cid, p in proposals.items() if cid not in out)
    return out


def _queue_routing(conn: psycopg.Connection[Any], schema: str, routes: dict[str, Any]) -> dict[str, Any]:
    """The old ``compressor.load()``: the imported ``queue_routing.json`` (decision f: no compression run is ported).
    ``routes``: the ``candidate_routing`` records the triage read already decoded (Codex H-292: the table is read once
    per view); only the ``#rest`` document is read here. A copy: the compressor never shares the triage's objects."""
    s = schema_ident(schema)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL("select body from {}.documents where key = 'queue_routing.json#rest'").format(s))
        rest = cur.fetchone()
    body = (rest or {}).get("body")
    return {**(body if isinstance(body, dict) else {}), "routes": copy.deepcopy(routes)}


def load(
    conn: psycopg.Connection[Any], schema: str, now: datetime, *, after_first_read: AfterRead | None = None
) -> TodayInputs:
    """``now``: the request instant as naive Berlin wall time. ``after_first_read`` (tests only) runs right after the
    pipeline read, so a regression can commit an edit between two reads of the same view."""
    store = ConvictionStore(conn, schema)
    stored = [record_of(r) for r in store.entry_rows()]
    rest = store.rest()
    people = load_people(conn, schema)
    conviction = inputs_from(load_documents(conn, schema), people)  # read once: pipeline + operator
    try:
        signals: list[dict[str, Any]] | None = pipeline.build(rest, stored, conviction, now)["signals"]
    except Exception:  # the old pipeline read raised: the pipeline, prepared-case and hold sections fail with it
        logger.exception("today: the pipeline build failed")
        signals = None
    if after_first_read is not None:
        after_first_read()
    calls = FounderCallsStore(conn, schema).load()
    events = events_store.load(conn, schema, now.date(), people=False)
    rows = candidate_rows(conn, schema)
    triage_inputs = triage_view.load(conn, schema)
    try:
        triage: dict[str, dict[str, Any]] | None = in_inbox_order(
            triage_view.build(triage_inputs)["proposals"], [str(r["id"]) for r in rows]
        )
    except Exception:  # the old triage view raised: the triage section is unavailable
        logger.exception("today: the triage view failed")
        triage = None
    return TodayInputs(
        signals=signals,
        people=people,
        operator=conviction.operator,
        founder_calls=calls,
        events=events,
        triage=triage,
        live_ids=frozenset(str(r["id"]) for r in rows if r.get("status") == "new"),
        queue_routing=_queue_routing(conn, schema, triage_inputs.routes),
    )


__all__ = ["UNREADABLE", "in_inbox_order", "load"]

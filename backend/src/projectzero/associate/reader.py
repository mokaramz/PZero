"""The PZ Associate's database ``Reader`` (review 033a): every tool read through the NEW read model of its view.

Revision 2 (decision b): each tool call opens its OWN ``snapshot_transaction`` (repeatable read, read only) and closes
it before the model runs again, so no transaction is open while a model call is pending and every tool answer comes
from one committed state. Inside it, ``DbViews`` gives the old tool bodies (``tools.ViewReader``) the payloads they
read before, from the same functions the NEW routes call:

* ``pipeline`` -> ``ConvictionStore.pipeline_view(now)`` (``GET /api/conviction/pipeline``);
* ``case`` -> ``ConvictionStore.case_view(slug, now)`` (``GET /api/conviction/case``, read-only);
* ``radar`` -> ``ConvictionStore.signals(now)`` + ``ConvictionStore.radar_of`` (``GET /api/conviction/radar``'s
  ``_radar_read``), WITHOUT ``credit_radar``: the Associate writes no PZ record (decision f), and the view is
  composed before the credit, as the old view returned it;
* ``inbox`` -> ``dealflow.inbox_view.inbox_view`` (``GET /api/deal-flow/inbox``);
* ``today`` -> ``today.inputs.load`` + ``today.core.view`` (``GET /api/today``'s ``today_view``);
* ``events`` -> ``events.store.load(..., people=False)`` + ``events.view.events_payload`` (``GET /api/events``);
* ``resolve`` -> ``DealFlowStore.resolve_id`` over the ``candidate``, ``scout_intake`` and ``native_scout``
  namespaces (``GET /api/deal-flow/candidates/{id}?ns=``), decision c;
* ``analysis`` -> the imported ``analyses/<id>.json`` (``legacy_documents``) as the old ``GET /api/analysis`` returned
  it: the analysis port is not done yet, so the archived file is the only analysis a candidate has.

``now`` is the request instant as naive Europe/Berlin wall time (``api.clock.berlin_request_now``).
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from projectzero.associate.tools import ViewReader
from projectzero.conviction.store import ConvictionStore
from projectzero.core.db import schema_ident, snapshot_transaction
from projectzero.dealflow.candidates import ALIAS_NAMESPACES, DealFlowStore
from projectzero.dealflow.inbox_view import inbox_view
from projectzero.events import store as events_store
from projectzero.events import view as events_view
from projectzero.events.scan import bounded_transaction
from projectzero.today import core as today_core
from projectzero.today import inputs as today_inputs


def analysis_path(cid: str) -> str:
    """The old ``analyst._apath`` file name, relative to the data folder."""
    return "analyses/" + re.sub(r"[^\w\-]", "_", cid) + ".json"


class DbViews:
    """The old read handlers' payloads from the NEW read models, on one connection (one snapshot)."""

    def __init__(self, conn: psycopg.Connection[Any], schema: str, now: datetime) -> None:
        self.conn = conn
        self.schema = schema
        self.now = now
        self._pipeline: dict[str, Any] | None = None

    def _store(self) -> ConvictionStore:
        return ConvictionStore(self.conn, self.schema)

    def pipeline(self) -> dict[str, Any]:
        if self._pipeline is None:  # one snapshot: the same answer however often a tool asks
            self._pipeline = self._store().pipeline_view(self.now)
        return self._pipeline

    def inbox(self) -> dict[str, Any]:
        return inbox_view(self.conn, self.schema)

    def today(self) -> dict[str, Any]:
        return today_core.view(today_inputs.load(self.conn, self.schema, self.now), self.now.date(), self.now)

    def radar(self) -> dict[str, Any]:
        view, _placed = ConvictionStore.radar_of(list(self.pipeline()["signals"]))
        return dict(view)

    def events(self) -> dict[str, Any]:
        today = events_view.berlin_today(self.now)
        data = events_store.load(self.conn, self.schema, today, people=False, records=True)
        return events_view.events_payload(data, today)

    def case(self, slug: str) -> dict[str, Any]:
        return self._store().case_view(slug, self.now)

    def analysis(self, id: str) -> dict[str, Any] | None:
        q = sql.SQL("select parsed from {}.legacy_documents where path = %s").format(schema_ident(self.schema))
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(q, (analysis_path(id),))
            row = cur.fetchone()
        parsed = row["parsed"] if row else None
        return {"analysis": parsed if isinstance(parsed, dict) else None}

    def resolve(self, id: str) -> str | None:
        store = DealFlowStore(self.conn, self.schema)
        for namespace in ALIAS_NAMESPACES:  # candidate (an absorbed record), scout_intake, native_scout
            found = store.resolve_id(namespace, id)
            if found:
                return found
        return None


class DbReader:
    """The ``tools.Reader`` of the database: each method is one tool read in its own snapshot."""

    def __init__(
        self,
        db_url: str,
        schema: str,
        now: datetime,
        *,
        done_by: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.db_url = db_url
        self.schema = schema
        self.now = now
        self.done_by = done_by  # Codex H-317: the ask's deadline bounds every tool read (connect, locks, statements)
        self.clock = clock

    @contextmanager
    def _snapshot(self) -> Iterator[psycopg.Connection[Any]]:
        """One tool read's snapshot: REPEATABLE READ, READ ONLY. With the ask's deadline it is a
        ``bounded_transaction`` (the connect, the lock and statement waits and a running read are cut at the deadline:
        ``EventsError`` 503); without one, the plain ``snapshot_transaction``."""
        if self.done_by is None:
            with snapshot_transaction(self.db_url) as conn:
                yield conn
            return
        with bounded_transaction(self.db_url, self.done_by, self.clock) as conn:
            conn.execute("set transaction isolation level repeatable read, read only")
            yield conn

    def _views(self, conn: psycopg.Connection[Any]) -> ViewReader:
        return ViewReader(DbViews(conn, self.schema, self.now))

    def today_missions(self) -> dict[str, Any]:
        with self._snapshot() as conn:
            return self._views(conn).today_missions()

    def conviction_companies(self, segment: str) -> dict[str, Any]:
        with self._snapshot() as conn:
            return self._views(conn).conviction_companies(segment)

    def manager_decisions(self) -> dict[str, Any]:
        with self._snapshot() as conn:
            return self._views(conn).manager_decisions()

    def company_detail(self, slug: str) -> dict[str, Any]:
        with self._snapshot() as conn:
            return self._views(conn).company_detail(slug)

    def deal_flow_candidates(self, view: str, limit: int) -> dict[str, Any]:
        with self._snapshot() as conn:
            return self._views(conn).deal_flow_candidates(view, limit)

    def candidate_detail(self, id: str) -> dict[str, Any]:
        with self._snapshot() as conn:
            return self._views(conn).candidate_detail(id)

    def radar(self) -> dict[str, Any]:
        with self._snapshot() as conn:
            return self._views(conn).radar()

    def upcoming_events(self, limit: int) -> dict[str, Any]:
        with self._snapshot() as conn:
            return self._views(conn).upcoming_events(limit)

    def find_records(self, query: str) -> dict[str, Any]:
        with self._snapshot() as conn:
            return self._views(conn).find_records(query)

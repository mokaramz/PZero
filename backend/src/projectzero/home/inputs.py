"""The database adapter behind the Investment Desk (review 031a): ``HomeInputs`` from ONE connection.

The caller opens that connection with ``core.db.snapshot_transaction`` (REPEATABLE READ, READ ONLY, set before the
first query: decision c), so every reader below sees one committed state. Nothing here opens a connection or writes.
Each input is read once: the people feed both the operator inputs and the desk's listings.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg

from projectzero.conviction.inputs import inputs_from, load_documents
from projectzero.conviction.store import ConvictionStore, record_of
from projectzero.dealflow.inbox_view import candidate_rows
from projectzero.dealflow.ranking.service import ranking_input
from projectzero.events import store as events_store
from projectzero.home.inputs_model import HomeInputs
from projectzero.network.store import load_people


def load(conn: psycopg.Connection[Any], schema: str, now: datetime) -> HomeInputs:
    """``now``: the request instant as naive Berlin wall time (its date is the events' ``today``)."""
    signals = [record_of(r) for r in ConvictionStore(conn, schema).entry_rows()]  # stored order
    people = load_people(conn, schema)  # file order
    operator = inputs_from(load_documents(conn, schema), people).operator
    events = events_store.load(conn, schema, now.date(), people=False)  # stored order, with the pins
    candidates = [{**ranking_input(r)[0], "id": r["id"]} for r in candidate_rows(conn, schema)]  # inbox order
    return HomeInputs(signals=signals, people=people, operator=operator, events=events, candidates=candidates)

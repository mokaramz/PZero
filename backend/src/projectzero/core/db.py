"""Database access: one helper to open a transaction on the configured schema.

Every write path runs inside ``transaction()``: commit on success, rollback on any exception. The schema name is a
parameter (``pz`` in production, a scratch schema in hosted tests) and is always quoted as an identifier.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import sql

_SCHEMA = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def schema_ident(schema: str) -> sql.Identifier:
    if not _SCHEMA.match(schema):
        raise ValueError(f"invalid schema name: {schema!r}")
    return sql.Identifier(schema)


IDLE_IN_TRANSACTION_TIMEOUT = "5min"


def connect(db_url: str, *, autocommit: bool = False) -> psycopg.Connection[Any]:
    """A session that can't outlive its client by long: if the client vanishes mid-transaction (network drop), the
    server ends the session after ``IDLE_IN_TRANSACTION_TIMEOUT`` instead of holding its locks indefinitely."""
    conn = psycopg.connect(db_url, autocommit=True, connect_timeout=15, application_name="projectzero")
    conn.execute(
        sql.SQL("set idle_in_transaction_session_timeout = {}").format(sql.Literal(IDLE_IN_TRANSACTION_TIMEOUT))
    )
    conn.autocommit = autocommit
    return conn


@contextmanager
def transaction(db_url: str) -> Iterator[psycopg.Connection[Any]]:
    conn = connect(db_url)
    try:
        with conn.transaction():
            yield conn
    finally:
        conn.close()

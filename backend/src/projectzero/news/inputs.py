"""The database side of News & Learning (review 028a): ``load(conn, schema, now) -> NewsInputs`` in ONE read
transaction, over the SAME old-format documents Validation reads (``validation.inputs.load_docs``: the News archives
in their key / line order, the Validation logs from ``validation_log``, the stored sources and the Deal Flow,
Conviction and Founder Calls inputs of the Validation entity model). The Validation entities are built ONCE per request
(decision b). The curated cases come from the package. Nothing is written (decision a: the curated seeding is applied in
memory).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql

from projectzero.core.db import schema_ident
from projectzero.network.view import berlin_today
from projectzero.news.inputs_model import NewsInputs, base_from_docs, inputs_from_docs
from projectzero.validation.inputs import archived_text, load_docs, parse_archived

STATUS = ("news/events.json", "news/runs.jsonl")  # all the refresh status reads


def load(conn: psycopg.Connection[Any], schema: str, now: datetime) -> NewsInputs:
    return inputs_from_docs(load_docs(conn, schema, now), berlin_today(now))


def load_status(conn: psycopg.Connection[Any], schema: str) -> NewsInputs:
    """Only what ``refresh_status`` reads (the runs log and the stored events), the same archives ``load`` reads."""
    q = sql.SQL("select path, raw from {}.legacy_documents where path = any(%s)").format(schema_ident(schema))
    raw = dict(conn.execute(q, (list(STATUS),)).fetchall())
    docs: dict[str, Any] = {}
    if "news/events.json" in raw:
        docs["news/events.json"] = parse_archived(raw["news/events.json"])
    else:
        row = conn.execute(
            sql.SQL("select body from {}.documents where key = 'news/events.json'").format(schema_ident(schema))
        ).fetchone()
        if row is not None:
            docs["news/events.json"] = row[0]
    docs["news/runs.jsonl"] = archived_text(raw["news/runs.jsonl"]) if "news/runs.jsonl" in raw else ""
    return base_from_docs(docs)

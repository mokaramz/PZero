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

from projectzero.network.view import berlin_today
from projectzero.news import store as news_store
from projectzero.news.inputs_model import NewsInputs, base_from_docs, inputs_from_docs
from projectzero.validation.inputs import load_docs

RUNS = "news/runs.jsonl"


def load(conn: psycopg.Connection[Any], schema: str, now: datetime) -> NewsInputs:
    return inputs_from_docs(load_docs(conn, schema, now), berlin_today(now))


def load_status(conn: psycopg.Connection[Any], schema: str) -> tuple[NewsInputs, int]:
    """Only what ``refresh_status`` reads (Codex H-251): the stored runs log (``news_logs``, review 028c) and the STORED
    event count (a persisted seed included) instead of the whole events document."""
    inputs = base_from_docs(news_store.log_texts(conn, schema, ("runs",)))
    return inputs, news_store.event_count(conn, schema)

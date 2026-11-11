"""Review 009: ``GET /api/deal-flow/inbox`` (the old ``/api/inbox`` shape) through HTTP, in a scratch schema."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from psycopg.types.json import Jsonb
from tests.hosted.test_ranking_hosted import client_for, schema, settings, store_as_imported

from projectzero.core.config import Settings
from projectzero.core.db import connect

pytestmark = pytest.mark.hosted
__all__ = ["schema", "settings"]


def rec(cid: str, name: str, **extra: Any) -> dict[str, Any]:
    return {"id": cid, "name": name, "decision": "new", "discovery_tier": "registry", "source_id": "src-a",
            "source": "Oracle", "description": "Builds tools.", "geo": ["DE"]} | extra  # fmt: skip


def archive(settings: Settings, schema: str, path: str, doc: dict[str, Any]) -> None:
    raw = json.dumps(doc).encode()
    with connect(settings.db_url, autocommit=True) as conn:
        conn.execute(
            f"insert into {schema}.legacy_documents (path, sha256, bytes, raw, parsed) values (%s, %s, %s, %s, %s)".encode(),
            (path, hashlib.sha256(raw).hexdigest(), len(raw), raw, Jsonb(doc)),
        )


def test_the_inbox_keeps_the_archived_order_through_merges(settings: Settings, schema: str) -> None:
    records = [rec("a", "Alpha"), rec("c", "Gamma"), rec("d", "Delta")]
    store_as_imported(settings, schema, records, "2026-11-08 19:09:09", None)
    with connect(settings.db_url, autocommit=True) as conn:
        conn.execute(
            f"insert into {schema}.candidates (id, name, status, origins, attrs, first_seen_at) values "
            "('scout-1', 'Merged Survivor', 'new', '{legacy_scout00}', '{}', '2020-01-01'),"
            "('live-1', 'Live Lead', 'new', '{grok}', '{}', '2026-11-10')".encode()
        )
        conn.execute(
            f"insert into {schema}.candidate_aliases (namespace, alias_id, candidate_id, reason) "
            "values ('candidate', 'b', 'scout-1', 'merge')".encode()
        )
    # archived order: d, b (merged into scout-1), a, c
    archive(settings, schema, "inbox.json", {"candidates": [{"id": "d"}, {"id": "b"}, {"id": "a"}, {"id": "c"}]})
    archive(settings, schema, "sources.json", {"sources": [{"id": "src-a"}]})
    with connect(settings.db_url, autocommit=True) as conn:
        conn.execute(
            f"insert into {schema}.sources (id, name, kind, legacy) values ('src-a', 'Oracle', 'registry', %s)".encode(),
            (Jsonb({"id": "src-a", "geo": ["DACH", "XX"]}),),
        )
    with client_for(settings, schema) as client:
        body = client.get("/api/deal-flow/inbox").json()
    assert [c["id"] for c in body["candidates"]] == ["d", "scout-1", "a", "c", "live-1"]
    assert body["last_run"] == "2026-11-08 19:09:09"
    assert body["ws_geos"]["un"] == ["XX"] and "DACH" in body["ws_geos"]["eu"]
    assert (body["feedback_cap"], body["feedback_min_reviewed"]) == (3, 5)
    first = body["candidates"][0]
    assert {"attention_v2", "themes", "lens", "feedback"} <= set(first) and first["name"] == "Delta"

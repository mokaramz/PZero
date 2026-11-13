"""A golden world's documents through the PRODUCTION importer into a new throw-away ``pz_itest_*`` schema (the hosted
acceptance tests of the read models, reviews 030a / 031a). Never touches ``pz`` or any data folder: the documents are
written to a temporary legacy data folder, captured, planned and applied like a real import."""

from __future__ import annotations

import json
import re
import secrets
import tempfile
from pathlib import Path
from typing import Any

from psycopg import sql

from projectzero.core.db import connect
from projectzero.ops.db_check import _scratch_sql
from projectzero.ops.legacy.apply import apply_plan
from projectzero.ops.legacy.plan import build_plan
from projectzero.ops.legacy.source import LegacySnapshot

# the files the importer requires that a world may not hold (empty collections, as a fresh install had them)
FILLER: dict[str, Any] = {
    "inbox.json": {"candidates": []}, "real_data.json": {"signals": []}, "people.json": {"people": []},
    "events.json": {"events": [], "leads": []}, "triage_proposals.json": {"proposals": {}},
    "queue_routing.json": {"routes": {}}, "sources.json": {"sources": []}, "scout_intake.json": {"items": {}},
    "native_scout.json": {"signals": {}}, "committee.json": {"second_pass": {}}, "bridge_jobs.json": {"jobs": {}},
    "schedule/jobs.json": {}, "inference_ledger.jsonl": "", "schedule/runs.jsonl": "",
}  # fmt: skip


def files_of(docs: dict[str, Any]) -> dict[str, bytes]:
    return {
        k: (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=2)).encode("utf-8")
        for k, v in docs.items()
    }


def import_world(db_url: str, docs: dict[str, Any]) -> str:
    """A new scratch schema holding ``docs`` (plus ``FILLER`` for the required files it lacks), as imported."""
    name = f"pz_itest_{secrets.token_hex(4)}"
    with tempfile.TemporaryDirectory(prefix="pz-world-") as tmp:
        for rel, raw in files_of({**{k: v for k, v in FILLER.items() if k not in docs}, **docs}).items():
            target = (Path(tmp) / rel).resolve()
            if Path(tmp).resolve() not in target.parents:
                raise ValueError(f"refusing a path outside the scratch folder: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        snapshot = LegacySnapshot.capture(Path(tmp))
    with connect(db_url, autocommit=True) as admin:
        admin.execute(_scratch_sql(name).encode())
    try:  # from here on the schema exists: any failure drops it (Codex H-299), keeping the original error
        conn = connect(db_url)
        try:
            applied = apply_plan(build_plan(snapshot), schema=name, conn=conn)
        finally:
            conn.close()
        if not applied.get("applied"):
            raise ValueError(f"the importer refused the world: {applied}")
    except BaseException:
        drop_schema(db_url, name)
        raise
    return name


def drop_schema(db_url: str, name: str) -> None:
    """Drop one of OUR scratch schemas (never anything else)."""
    if not re.fullmatch(r"pz_(itest|rehearse)_[0-9a-f]{8}", name):
        raise ValueError(f"refusing to drop a schema that is not a scratch schema: {name}")
    with connect(db_url, autocommit=True) as admin:
        admin.execute(sql.SQL("drop schema if exists {} cascade").format(sql.Identifier(name)))

"""Write an ImportPlan into a schema — atomically and at most once.

* One transaction for everything (rows + byte archive + marker). Any error rolls back all of it.
* Plain INSERTs, no ON CONFLICT: a destination row or archive path that already exists is unexpected (a genuine
  replay is caught by the marker first), so its unique violation aborts the whole transaction and no marker is written.
* Plans with blockers (missing required files, secrets in the source, unresolvable conflicts) are refused before
  any connection is opened.
* Once-only: a ``documents`` row ``ops/legacy_import`` records the plan fingerprint. A second apply with the same
  fingerprint is a no-op ("already imported"); a different fingerprint is refused (the live data has diverged and an
  operator must decide).
* ``rehearse`` applies into a scratch copy of the schema on the hosted database, verifies it against the plan
  (row counts, byte-exact archive restore, alias resolution, re-apply no-op), then drops the scratch schema.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Iterable
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from projectzero.ops.db_check import _connect, _scratch_sql
from projectzero.ops.legacy.plan import TABLE_ORDER, ImportPlan

MARKER_KEY = "ops/legacy_import"
JSONB_COLUMNS = frozenset(
    {
        "attrs",
        "legacy",
        "payload",
        "evidence",
        "detail",
        "outcome_detail",
        "scores",
        "request",
        "result",
        "body",
        "verified",
    }
)
BATCH = 500


def fingerprint(plan: ImportPlan) -> str:
    """Identifies the source snapshot: every archived file's path and sha256."""
    digest = hashlib.sha256()
    for f in sorted(plan.archive, key=lambda f: f.path):
        digest.update(f"{f.path}\0{f.sha256}\n".encode())
    return digest.hexdigest()


def _adapt(column: str, value: Any) -> Any:
    return Jsonb(value) if column in JSONB_COLUMNS and value is not None else value


def _insert(cur: psycopg.Cursor[Any], schema: str, table: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    columns = list(rows[0].keys())
    statement = sql.SQL("insert into {}.{} ({}) values ({})").format(
        sql.Identifier(schema),
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(c) for c in columns),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
    )
    for start in range(0, len(rows), BATCH):
        chunk = rows[start : start + BATCH]
        cur.executemany(statement, [tuple(_adapt(c, row.get(c)) for c in columns) for row in chunk])
    return len(rows)


def _archive_rows(plan: ImportPlan) -> Iterable[dict[str, Any]]:
    for f in plan.archive:
        yield {"path": f.path, "sha256": f.sha256, "bytes": len(f.raw), "raw": f.raw, "parsed": f.parsed}


def _insert_archive(cur: psycopg.Cursor[Any], schema: str, plan: ImportPlan) -> int:
    statement = sql.SQL(
        "insert into {}.legacy_documents (path, sha256, bytes, raw, parsed) values (%s, %s, %s, %s, %s)"
    ).format(sql.Identifier(schema))
    batch: list[tuple[Any, ...]] = []
    count = 0
    for row in _archive_rows(plan):
        parsed = Jsonb(row["parsed"]) if row["parsed"] is not None else None
        batch.append((row["path"], row["sha256"], row["bytes"], row["raw"], parsed))
        if len(batch) >= 100:
            cur.executemany(statement, batch)
            count += len(batch)
            batch = []
    if batch:
        cur.executemany(statement, batch)
        count += len(batch)
    return count


def apply_plan(plan: ImportPlan, *, schema: str, conn: psycopg.Connection[Any] | None = None) -> dict[str, Any]:
    if plan.blockers:
        return {"applied": False, "refused": "the plan has blockers", "blockers": plan.blockers}
    fp = fingerprint(plan)
    own = conn is None
    conn = conn or _connect(autocommit=False)
    try:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(sql.SQL("lock table {}.documents in exclusive mode").format(sql.Identifier(schema)))
            cur.execute(
                sql.SQL("select body from {}.documents where key = %s").format(sql.Identifier(schema)), (MARKER_KEY,)
            )
            marker = cur.fetchone()
            if marker:
                if marker[0].get("fingerprint") == fp:
                    return {"applied": False, "already_imported": True, "fingerprint": fp}
                return {
                    "applied": False,
                    "refused": "a different legacy snapshot was already imported",
                    "imported_fingerprint": marker[0].get("fingerprint"),
                    "this_fingerprint": fp,
                }
            written = {table: _insert(cur, schema, table, plan.tables[table]) for table in TABLE_ORDER}
            written["legacy_documents"] = _insert_archive(cur, schema, plan)
            cur.execute(sql.SQL("select {}.backfill_content_items()").format(sql.Identifier(schema)))
            row = cur.fetchone()
            written["content_items"] = int(row[0]) if row else 0  # review 020: the shared 0011 mapping
            cur.execute(sql.SQL("select {}.backfill_founder_calls()").format(sql.Identifier(schema)))
            row = cur.fetchone()
            written["founder_calls"] = int(row[0]) if row else 0  # review 023: the 0014 mapping, raw order
            cur.execute(sql.SQL("select {}.backfill_evaluations()").format(sql.Identifier(schema)))
            row = cur.fetchone()
            written["evaluations"] = int(row[0]) if row else 0  # review 024: the 0015 mapping, raw order
            cur.execute(sql.SQL("select {}.backfill_founder_radar()").format(sql.Identifier(schema)))
            row = cur.fetchone()
            written["founder_radar"] = int(row[0]) if row else 0  # review 026a: the 0016 mapping, raw order
            cur.execute(sql.SQL("select {}.backfill_validation()").format(sql.Identifier(schema)))
            row = cur.fetchone()
            written["validation_log"] = int(row[0]) if row else 0  # review 027b: the 0018 mapping, line order
            body = {"fingerprint": fp, "counts": plan.counts(), "generated_at": plan.report["generated_at"]}
            cur.execute(
                sql.SQL("insert into {}.documents (key, body) values (%s, %s)").format(sql.Identifier(schema)),
                (MARKER_KEY, Jsonb(body)),
            )
        return {"applied": True, "fingerprint": fp, "written": written}
    finally:
        if own:
            conn.close()


def rehearse(plan: ImportPlan) -> dict[str, Any]:
    schema = f"pz_rehearse_{secrets.token_hex(4)}"
    checks: dict[str, Any] = {"schema": schema}
    setup = _connect()
    try:
        setup.execute(_scratch_sql(schema).encode())
        conn = _connect(autocommit=False)
        try:
            first = apply_plan(plan, schema=schema, conn=conn)
            checks["first_apply"] = {k: v for k, v in first.items() if k != "written"}
            checks["counts"] = _verify_counts(conn, schema, plan)
            checks["archive"] = _verify_archive(conn, schema, plan)
            checks["aliases"] = _verify_aliases(conn, schema, plan)
            second = apply_plan(plan, schema=schema, conn=conn)
            checks["second_apply_is_noop"] = bool(second.get("already_imported"))
            checks["counts_after_second_apply"] = _verify_counts(conn, schema, plan)
        finally:
            conn.close()
    finally:
        setup.execute(sql.SQL("drop schema if exists {} cascade").format(sql.Identifier(schema)))
        setup.close()
        checks["scratch_schema_dropped"] = True
    checks["conflict_existing_row"] = _conflict_case(plan, "row")
    checks["conflict_existing_archive_path"] = _conflict_case(plan, "archive")
    checks["passed"] = bool(
        checks["first_apply"].get("applied")
        and checks["counts"]["all_match"]
        and checks["archive"]["all_match"]
        and checks["aliases"]["all_resolve"]
        and checks["second_apply_is_noop"]
        and checks["counts_after_second_apply"]["all_match"]
        and checks["conflict_existing_row"]["passed"]
        and checks["conflict_existing_archive_path"]["passed"]
    )
    print(json.dumps({k: v for k, v in checks.items() if k != "counts"}, indent=2, default=str))
    return checks


def _conflict_case(plan: ImportPlan, kind: str) -> dict[str, Any]:
    """Review 003 #1 on the hosted DB: a pre-existing, different destination row (or archive path) must abort the
    whole apply — nothing written, no marker — instead of being skipped."""
    schema = f"pz_conflict_{secrets.token_hex(4)}"
    ident = sql.Identifier(schema)
    setup = _connect()
    result: dict[str, Any] = {"schema": schema, "kind": kind}
    try:
        setup.execute(_scratch_sql(schema).encode())
        if kind == "row":
            target = plan.tables["candidates"][0]["id"]
            setup.execute(
                sql.SQL("insert into {}.candidates (id, name) values (%s, %s)").format(ident),
                (target, "pre-existing, different row"),
            )
            result["preexisting"] = f"candidates.id = {target}"
        else:
            path, raw = plan.archive[0].path, b"pre-existing, different bytes"
            setup.execute(
                sql.SQL("insert into {}.legacy_documents (path, sha256, bytes, raw) values (%s, %s, %s, %s)").format(
                    ident
                ),
                (path, hashlib.sha256(raw).hexdigest(), len(raw), raw),
            )
            result["preexisting"] = f"legacy_documents.path = {path}"
        conn = _connect(autocommit=False)
        try:
            outcome = apply_plan(plan, schema=schema, conn=conn)
            result["outcome"] = f"NOT ABORTED: {outcome}"
        except psycopg.errors.UniqueViolation as exc:
            result["outcome"] = f"aborted: unique violation on {exc.diag.constraint_name}"
        finally:
            conn.close()
        counts = {}
        for table in ("documents", "candidates", "legacy_documents", "companies"):
            row = setup.execute(sql.SQL("select count(*) from {}.{}").format(ident, sql.Identifier(table))).fetchone()
            counts[table] = row[0] if row else -1
        result["counts_after"] = counts
        expected = {"documents": 0, "companies": 0} | (
            {"candidates": 1, "legacy_documents": 0} if kind == "row" else {"candidates": 0, "legacy_documents": 1}
        )
        result["passed"] = result["outcome"].startswith("aborted") and counts == expected
    finally:
        setup.execute(sql.SQL("drop schema if exists {} cascade").format(ident))
        setup.close()
        result["scratch_schema_dropped"] = True
    return result


def _verify_counts(conn: psycopg.Connection[Any], schema: str, plan: ImportPlan) -> dict[str, Any]:
    expected = plan.counts()
    expected["documents"] += 1  # the import marker
    actual = {}
    with conn.cursor() as cur:
        for table in expected:
            cur.execute(sql.SQL("select count(*) from {}.{}").format(sql.Identifier(schema), sql.Identifier(table)))
            row = cur.fetchone()
            actual[table] = row[0] if row else 0
    conn.commit()
    mismatches = {t: {"expected": expected[t], "actual": actual[t]} for t in expected if expected[t] != actual[t]}
    return {"all_match": not mismatches, "mismatches": mismatches, "actual": actual}


def _verify_archive(conn: psycopg.Connection[Any], schema: str, plan: ImportPlan) -> dict[str, Any]:
    """Every archived file restored from the database is byte-identical to the source file."""
    by_path = {f.path: f for f in plan.archive}
    mismatched: list[str] = []
    restored_bytes = 0
    with conn.cursor(name="archive_scan") as cur:
        cur.execute(sql.SQL("select path, raw from {}.legacy_documents").format(sql.Identifier(schema)))
        for path, raw in cur:
            restored = bytes(raw)
            restored_bytes += len(restored)
            if path not in by_path or restored != by_path[path].raw:
                mismatched.append(path)
    conn.commit()
    return {
        "files": len(by_path),
        "restored_bytes": restored_bytes,
        "mismatched": mismatched,
        "all_match": not mismatched and restored_bytes == sum(len(f.raw) for f in plan.archive),
    }


def _verify_aliases(conn: psycopg.Connection[Any], schema: str, plan: ImportPlan) -> dict[str, Any]:
    unresolved = []
    with conn.cursor() as cur:
        for alias in plan.tables["candidate_aliases"]:
            cur.execute(
                sql.SQL("select {}.resolve_candidate(%s, %s)").format(sql.Identifier(schema)),
                (alias["namespace"], alias["alias_id"]),
            )
            row = cur.fetchone()
            if not row or row[0] != alias["candidate_id"]:
                unresolved.append(alias)
    conn.commit()
    return {
        "checked": len(plan.tables["candidate_aliases"]),
        "unresolved": unresolved[:20],
        "all_resolve": not unresolved,
    }

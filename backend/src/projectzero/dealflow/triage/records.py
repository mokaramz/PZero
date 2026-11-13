"""Machine triage's stored state (review 035b, migration 0026), overlaid on the imported documents.

* **The run lock** (``take_lock``): ONE session advisory lock ``<schema>.dealflow.triage`` on a dedicated autocommit
  connection, shared by every trigger (after a scan, the hourly retry, Retry now); its key is derived from the schema
  at run time. ``lock_held`` reads ``pg_locks`` (the ``running`` flag of ``GET triage_auto``).
* **The automatic runs** (``auto_runs``): the imported ``shadow_triage/auto_runs.json`` runs, then the
  ``triage_auto_runs`` records in id order, applied as the old ``_store`` applied each record (a record replaces the
  earlier one with the same ``scan_run_id``; the last ``KEEP_RUNS`` kept).
* **The retry state** (``retry_state``): the imported ``shadow_triage/retry_state.json`` (its archived bytes, in the
  old key order; keys mapped to survivors), then the ``triage_retry_state`` rows in ``ord`` order: a cleared row pops
  the entry (the old ``rs.pop``), a re-added one moves to the end, any other updates it in place.
* **The proposals** (``current_proposals``, ``write_proposal``): the view's read (a survivor's current row, else the
  newest one carried to it); a write clears the previous current row, then inserts the new current one, in the
  caller's transaction.
* **The runner runs** (``insert_run``) and the per-candidate dispositions (``insert_item`` / ``items``).
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Json, Jsonb

from projectzero.core.db import connect, schema_ident
from projectzero.dealflow.triage import auto_rules
from projectzero.dealflow.triage.view import AUTO_RUNS_DOC, proposal_record

LOCK = "{schema}.dealflow.triage"
RETRY_DOC = "shadow_triage/retry_state.json"
PROPOSALS_REST = "triage_proposals.json#rest"
PROMOTED = ("candidate_id", "run_id", "prompt_version", "input_sha", "proposal", "status", "model", "veto_model",
            "usd", "proposed_at")  # fmt: skip  # the importer's promoted columns (``map_records.triage``)
DISPOSITIONS = ("proposed", "needs_human", "error", "decided_meanwhile", "changed_meanwhile", "unchanged_skipped")


class TriageBusy(Exception):
    """Another session holds the triage run lock."""


# ------------------------------------------------------------------ the lock
def _key(schema: str) -> str:
    schema_ident(schema)  # a valid schema name only
    return LOCK.format(schema=schema)


def take_lock(db_url: str, schema: str) -> psycopg.Connection[Any]:
    """The run lock on a dedicated autocommit SESSION; ``TriageBusy`` when another session holds it."""
    conn = connect(db_url, autocommit=True)
    try:
        row = conn.execute("select pg_try_advisory_lock(hashtext(%s))", (_key(schema),)).fetchone()
    except BaseException:
        conn.close()
        raise
    if not (row and row[0]):
        conn.close()
        raise TriageBusy
    return conn


def release_lock(conn: psycopg.Connection[Any], schema: str) -> None:
    try:
        with contextlib.suppress(Exception):
            conn.execute("select pg_advisory_unlock(hashtext(%s))", (_key(schema),))
    finally:
        conn.close()


def lock_held(conn: psycopg.Connection[Any], schema: str) -> bool:
    """Whether ANY session holds the run lock (``pg_locks``; the bigint key split into its two oids)."""
    row = conn.execute(
        "with k as (select hashtext(%s)::bigint as v) "
        "select exists(select 1 from pg_locks l, k where l.locktype = 'advisory' and l.granted and l.objsubid = 1 "
        "and l.classid = ((k.v >> 32) & 4294967295)::oid and l.objid = (k.v & 4294967295)::oid)",
        (_key(schema),),
    ).fetchone()
    return bool(row and row[0])


# ------------------------------------------------------------------ small helpers
def _rows(conn: psycopg.Connection[Any], schema: str, query: str, params: Any = ()) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL(query).format(s=schema_ident(schema)), params)
        return list(cur.fetchall())


def _document(conn: psycopg.Connection[Any], schema: str, key: str) -> Any:
    rows = _rows(conn, schema, "select body from {s}.documents where key = %s", (key,))
    return rows[0]["body"] if rows else None


def _archived(conn: psycopg.Connection[Any], schema: str, path: str) -> Any:
    """An imported file in its OLD key order (the archived bytes), else its ``documents`` row, else None."""
    rows = _rows(conn, schema, "select raw from {s}.legacy_documents where path = %s", (path,))
    if rows and rows[0]["raw"] is not None:
        try:
            return json.loads(bytes(rows[0]["raw"]).decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError):
            return None
    return _document(conn, schema, path)


def aliases(conn: psycopg.Connection[Any], schema: str) -> dict[str, str]:
    return {
        str(r["alias_id"]): str(r["candidate_id"])
        for r in _rows(
            conn, schema, "select alias_id, candidate_id from {s}.candidate_aliases where namespace = 'candidate'"
        )
    }


# ------------------------------------------------------------------ the automatic runs
def store_record(runs: list[dict[str, Any]], rec: dict[str, Any]) -> list[dict[str, Any]]:
    """The old ``_store``: the record replaces an earlier one with its ``scan_run_id``; the last ``KEEP_RUNS``."""
    out = [r for r in runs if not (isinstance(r, dict) and r.get("scan_run_id") == rec.get("scan_run_id"))] + [rec]
    return out[-auto_rules.KEEP_RUNS :]


def auto_runs(conn: psycopg.Connection[Any], schema: str) -> dict[str, Any]:
    """The old ``auto_runs.json`` document as it reads now: the imported runs, then every new record."""
    doc = _document(conn, schema, AUTO_RUNS_DOC)
    doc = doc if isinstance(doc, dict) else {}
    found = doc.get("runs")
    runs: list[dict[str, Any]] = list(found) if isinstance(found, list) else []
    for r in _rows(conn, schema, "select record::text as rec from {s}.triage_auto_runs order by id"):
        runs = store_record(list(runs), json.loads(r["rec"]))
    return {**doc, "runs": runs}


def running_auto_runs(conn: psycopg.Connection[Any], schema: str) -> list[dict[str, Any]]:
    return [
        {**r, "record": json.loads(r["rec"]), "selection": json.loads(r["sel"])}
        for r in _rows(
            conn,
            schema,
            "select id, scan_run_id, kind, triage_run_id, record::text as rec, "
            "selection::text as sel from {s}.triage_auto_runs where state = 'running' order by id for update",
        )
    ]


def insert_auto_run(
    conn: psycopg.Connection[Any],
    schema: str,
    *,
    scan_run_id: str,
    kind: str,
    triage_run_id: str | None,
    state: str,
    selection: list[list[Any]],
    record: Mapping[str, Any],
    started_at: datetime,
    finished_at: datetime | None,
) -> int:
    rows = _rows(
        conn,
        schema,
        "insert into {s}.triage_auto_runs (scan_run_id, kind, triage_run_id, state, selection, "
        "record, started_at, finished_at) values (%s, %s, %s, %s, %s, %s, %s, %s) returning id",
        (scan_run_id, kind, triage_run_id, state, Json(selection), Json(dict(record)), started_at, finished_at),
    )
    return int(rows[0]["id"])


def finish_auto_run(
    conn: psycopg.Connection[Any], schema: str, row_id: int, record: Mapping[str, Any], finished_at: datetime
) -> None:
    _rows(
        conn,
        schema,
        "update {s}.triage_auto_runs set state = %s, record = %s, finished_at = %s where id = %s "
        "and state = 'running' returning id",
        (str(record["state"]), Json(dict(record)), finished_at, row_id),
    )


# ------------------------------------------------------------------ the retry state
def retry_state(conn: psycopg.Connection[Any], schema: str, alias_map: Mapping[str, str]) -> dict[str, Any]:
    """The old ``retry_state.json`` as it reads now (keys: survivors)."""
    base = _archived(conn, schema, RETRY_DOC)
    rs: dict[str, Any] = {}
    for k, v in base.items() if isinstance(base, dict) else []:
        rs[alias_map.get(str(k), str(k))] = v
    for r in _rows(
        conn, schema, "select candidate_id, entry::text as e, cleared, moved from {s}.triage_retry_state order by ord"
    ):
        cid = str(r["candidate_id"])
        if r["cleared"]:
            rs.pop(cid, None)
        elif r["moved"] or cid not in rs:
            rs.pop(cid, None)
            rs[cid] = json.loads(r["e"])
        else:
            rs[cid] = json.loads(r["e"])
    return rs


def retry_entry(conn: psycopg.Connection[Any], schema: str, cid: str) -> dict[str, Any] | None:
    """``retry_state(...).get(cid)`` without reading every row: the candidate's row, else the imported entry of an
    id that resolves to it (the last such key, as the overlay maps them)."""
    rows = _rows(
        conn, schema, "select entry::text as e, cleared from {s}.triage_retry_state where candidate_id = %s", (cid,)
    )
    if rows:
        return None if rows[0]["cleared"] else dict(json.loads(rows[0]["e"]))
    base = _archived(conn, schema, RETRY_DOC)
    if not isinstance(base, dict) or not base:
        return None
    keys = [str(k) for k in base]
    amap = {
        str(r["alias_id"]): str(r["candidate_id"])
        for r in _rows(
            conn,
            schema,
            "select alias_id, candidate_id from {s}.candidate_aliases where namespace = 'candidate' "
            "and alias_id = any(%s)",
            (keys,),
        )
    }
    found = None
    for k, v in base.items():
        if amap.get(str(k), str(k)) == cid:
            found = v
    return dict(found) if isinstance(found, dict) else None


def put_retry(conn: psycopg.Connection[Any], schema: str, cid: str, entry: Mapping[str, Any]) -> None:
    """Set one entry (the old ``rs[cid]`` after ``_retry_item``); a cleared row re-added moves to the end."""
    cur = _rows(conn, schema, "select cleared from {s}.triage_retry_state where candidate_id = %s for update", (cid,))
    if not cur:
        _rows(
            conn,
            schema,
            "insert into {s}.triage_retry_state (candidate_id, entry) values (%s, %s) returning ord",
            (cid, Json(dict(entry))),
        )
    elif cur[0]["cleared"]:
        _rows(
            conn,
            schema,
            "update {s}.triage_retry_state set entry = %s, cleared = false, moved = true, "
            "ord = default, updated_at = now() where candidate_id = %s returning ord",
            (Json(dict(entry)), cid),
        )
    else:
        _rows(
            conn,
            schema,
            "update {s}.triage_retry_state set entry = %s, updated_at = now() where candidate_id = %s returning ord",
            (Json(dict(entry)), cid),
        )


def clear_retry(conn: psycopg.Connection[Any], schema: str, cid: str) -> None:
    """The old ``rs.pop(cid, None)``."""
    _rows(
        conn,
        schema,
        "insert into {s}.triage_retry_state (candidate_id, entry, cleared) values (%s, '{{}}', true) "
        "on conflict (candidate_id) do update set cleared = true, updated_at = now() returning ord",
        (cid,),
    )


# ------------------------------------------------------------------ proposals
_CURRENT = (
    "select distinct on (candidate_id) * from {s}.triage_proposals {where} "
    "order by candidate_id, is_current desc, proposed_at desc, id desc"
)


def current_proposals(
    conn: psycopg.Connection[Any], schema: str, ids: list[str] | None = None
) -> dict[str, dict[str, Any]]:
    """The view's proposal per candidate (``view.load``): its current row, else the newest one carried to it."""
    where = "where candidate_id = any(%s)" if ids is not None else ""
    q = _CURRENT.replace("{where}", where)
    return {
        str(r["candidate_id"]): proposal_record(r)
        for r in _rows(conn, schema, q, (list(ids),) if ids is not None else ())
    }


def write_proposal(conn: psycopg.Connection[Any], schema: str, entry: Mapping[str, Any], at: datetime) -> int:
    """The candidate's new current proposal, in the caller's transaction: the previous current row is cleared FIRST,
    then the new one inserted (``triage_proposals_one_current`` holds at every statement). An ``error`` entry
    (proposal None) is stored as ``UNKNOWN``, the importer's convention."""
    cid = str(entry["candidate_id"])
    _rows(
        conn,
        schema,
        "update {s}.triage_proposals set is_current = false where candidate_id = %s and is_current returning id",
        (cid,),
    )
    usd = entry.get("usd")
    rows = _rows(
        conn,
        schema,
        "insert into {s}.triage_proposals (candidate_id, run_id, prompt_version, input_sha, proposal, status, model, "
        "veto_model, usd, detail, proposed_at, is_current) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true) "
        "returning id",
        (
            cid,
            entry.get("run_id"),
            entry.get("prompt_version"),
            entry.get("input_sha"),
            str(entry.get("proposal") or "UNKNOWN"),
            entry.get("status"),
            entry.get("model"),
            entry.get("veto_model"),
            usd if isinstance(usd, int | float) and not isinstance(usd, bool) else None,
            Jsonb({k: v for k, v in entry.items() if k not in PROMOTED}),
            at,
        ),
    )
    return int(rows[0]["id"])


def latest_seq(conn: psycopg.Connection[Any], schema: str, cid: str) -> int:
    """The highest ``triage_decisions.seq`` of the survivor ``cid`` (its own rows and any recorded under an id that
    resolves to it), 0 without one (revision 3's selection mark)."""
    rows = _rows(
        conn,
        schema,
        "select coalesce(max(d.seq), 0) as m from {s}.triage_decisions d where d.candidate_id = %s "
        "or d.candidate_id in (select alias_id from {s}.candidate_aliases where namespace = 'candidate' "
        "and candidate_id = %s)",
        (cid, cid),
    )
    return int(rows[0]["m"])


def latest_seqs(conn: psycopg.Connection[Any], schema: str, alias_map: Mapping[str, str]) -> dict[str, int]:
    """``latest_seq`` of every survivor with a row, in one read."""
    out: dict[str, int] = {}
    for r in _rows(conn, schema, "select candidate_id, max(seq) as m from {s}.triage_decisions group by candidate_id"):
        sid = alias_map.get(str(r["candidate_id"]), str(r["candidate_id"]))
        out[sid] = max(out.get(sid, 0), int(r["m"]))
    return out


# ------------------------------------------------------------------ runner runs and dispositions
def insert_run(
    conn: psycopg.Connection[Any], schema: str, run_id: str, finished_at: datetime, summary: Mapping[str, Any]
) -> None:
    _rows(
        conn,
        schema,
        "insert into {s}.triage_runs (run_id, finished_at, summary) values (%s, %s, %s) returning id",
        (run_id, finished_at, Json(dict(summary))),
    )


def proposal_runs(conn: psycopg.Connection[Any], schema: str) -> list[dict[str, Any]]:
    """The old ``triage_proposals.json`` ``runs[]``: the imported ones, then the new rows."""
    rest = _document(conn, schema, PROPOSALS_REST)
    runs = list(rest.get("runs") or []) if isinstance(rest, dict) else []
    return runs + [
        json.loads(r["s"]) for r in _rows(conn, schema, "select summary::text as s from {s}.triage_runs order by id")
    ]


def run_usd(conn: psycopg.Connection[Any], schema: str, run_id: str) -> float:
    """The old ``ledger.total(ledger.entries(), run_id=run_id)`` (rounded to 6 decimals)."""
    rows = _rows(conn, schema, "select coalesce(sum(usd), 0) as u from {s}.model_ledger where run_id = %s", (run_id,))
    return round(float(rows[0]["u"] or 0), 6)


def insert_item(
    conn: psycopg.Connection[Any],
    schema: str,
    triage_run_id: str,
    cid: str,
    disposition: str,
    detail: Mapping[str, Any],
) -> None:
    assert disposition in DISPOSITIONS, disposition
    _rows(
        conn,
        schema,
        "insert into {s}.triage_run_items (triage_run_id, candidate_id, disposition, detail) "
        "values (%s, %s, %s, %s) returning id",
        (triage_run_id, cid, disposition, Json(dict(detail))),
    )


def items(conn: psycopg.Connection[Any], schema: str, triage_run_id: str) -> dict[str, tuple[str, dict[str, Any]]]:
    return {
        str(r["candidate_id"]): (str(r["disposition"]), json.loads(r["d"]))
        for r in _rows(
            conn,
            schema,
            "select candidate_id, disposition, detail::text as d from {s}.triage_run_items "
            "where triage_run_id = %s order by id",
            (triage_run_id,),
        )
    }

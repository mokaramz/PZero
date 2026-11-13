"""Phase 3 of the Deal Flow scan (review 034a): the old ``ingest_scan`` plus the old registry persistence of
``run_registry_concurrent``, written in the caller's ONE transaction (the deliveries, the run record, the sources'
runtime state and the watch baselines commit or roll back together, revision 2).

**What happens to each record of the batch** (after the cut ``_resolve_batch``), in the batch order:

1. **known by its old id** (the old ``c["id"] in known``): a candidate whose id or ``candidate`` alias is the record's
   old id (an IMPORTED Deal Flow candidate) counts ``known_skipped`` and is NOT submitted: the identity rules put
   registry scans in the Deal Flow family, so a name-only re-delivery would be ambiguous there and create a second
   candidate. Its provenance is counted as the old ``absorb`` would (``provenance_added``) but the imported record is
   never rewritten. A candidate the scan itself created in an EARLIER run (``attrs.scan_record.id``) is submitted:
   its ``external_id`` is its own strong key, so the intake re-reports it and folds the provenance in (the old
   ``absorb``); it counts ``known_skipped``. One the intake could not tie to a company (a placeholder name such as
   ``UNKNOWN``: no key to find it by) is skipped like an imported one, so it is never created twice.
2. **in the pipeline** (the old ``pipeline_match`` over the Conviction entries' name and domain keys): counted
   ``known_pipeline`` and never submitted.
3. **everything else is submitted**, ONE delivery per source (``external_ref`` ``scan:<run_id>:<source_id>``,
   ``REGISTRY_SCAN``, the creation hints of decision c). Counted from the resolution: ``created`` is ``new`` /
   ``baseline`` / ``noise`` by the created status; a strong-key or name join (``re_reported*``) is
   ``merged_into_existing``.

**Refusals** (revision 2): an entity the intake refuses is not counted among the candidates; its source's report row
gains ``refused: N`` and the note "N item(s) refused by the intake: <first reason>", the summary ``refused`` (a new,
declared key). Its cursor key and its watcher line are NOT advanced, so it stays discoverable.

**A duplicate delivery** (revision 3): the ORIGINAL ``intake_submissions`` row is read by its ``sha256``; every item it
accepted counts ``known_skipped`` ("already delivered", the row's ``already_delivered``), every item it refused is
refused again with its original reason. NOTHING advances on a replay: that source's cursor and watch baseline stay as
stored. A cursor or watch line advances only in the run whose delivery accepted the item.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Json, Jsonb

from projectzero.conviction.store import ConvictionStore
from projectzero.conviction.store import record_of as conviction_record
from projectzero.core.db import schema_ident
from projectzero.dealflow.intake.contract import Origin
from projectzero.dealflow.intake.postgres import PostgresIntake, ensure_intake_open
from projectzero.dealflow.intake.service import IntakeService, TrustedBatch
from projectzero.dealflow.ranking.service import ranking_input
from projectzero.dealflow.scan import history, parsers, records, seams
from projectzero.dealflow.sources.normalize import load_registry
from projectzero.dealflow.sources.registry import REGISTRY_KINDS, entity_from_registry_record, registry_value
from projectzero.dealflow.sources.store import SourcesStore
from projectzero.network.view import berlin_now

cut: Any = parsers  # the cut old code is untyped (see parsers.py): every call goes through this alias
TRIAGE_NOTE = "machine triage arrives with the triage port"  # decision d: no auto-triage from the scan
SUBMITTED_BY = "scheduler:deal_flow_scan"
_WEB_URL = re.compile(r"^https?://([A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}(:[0-9]{1,5})?([/?#][^\s]*)?$")
_EXTERNAL_ID = re.compile(r"[^A-Za-z0-9._:-]")


# ------------------------------------------------------------------------------------------------ the batch
@dataclass
class SourceResult:
    index: int
    src: dict[str, Any] | None  # the scanned COPY (its runtime keys, its cursor); None when the worker raised
    ctx: seams.SourceContext | None


@dataclass
class Fetched:
    """Everything phase 2 produced (no transaction was open)."""

    sources: list[dict[str, Any]]  # the registry as phase 1 read it (normalized), in order
    baselines: dict[str, dict[str, Any]]  # snapshot key -> {"lines", "seeded_from", "uid", "url"}
    done: dict[int, SourceResult]
    report: list[dict[str, Any]]
    merged: list[dict[str, Any]]  # the batch after ``_resolve_batch``
    host_of: dict[int, dict[str, Any]]  # id(record) -> the batch record it ended in
    records: list[dict[str, Any]]  # every record of every finished source, before the batch resolution
    timeout_ids: list[str]
    now_stamp: str  # the old ``now`` of the scan (``%Y-%m-%d %H:%M``)
    days: int
    seconds: float = 0.0


def batch_hosts(cands: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Which batch record each record ends in: the cut ``_resolve_batch``'s own loop without its side effects (run it
    BEFORE ``_resolve_batch``: the order and every key are the same)."""
    by_key: dict[str, dict[str, Any]] = {}
    host_of: dict[int, dict[str, Any]] = {}
    for c in sorted(cands, key=cut._batch_order):
        keys = cut.entity_keys(c)
        host = next((by_key[k] for k in keys if k in by_key), None)
        if host is not None:
            for k in keys:
                by_key[k] = host
            host_of[id(c)] = host
            continue
        for k in keys:
            by_key[k] = c
        host_of[id(c)] = c
    return host_of


# ------------------------------------------------------------------------------------------------ the entity
def external_id(c: Mapping[str, Any]) -> str:
    """``<source_id>:<old id>`` (decision a), every character the contract does not allow replaced by ``-``."""
    return _EXTERNAL_ID.sub("-", f"{c.get('source_id') or ''}:{c.get('id') or ''}")[:120]


def entity_of(c: Mapping[str, Any]) -> dict[str, Any]:
    """Decision (a): one old scan record -> one intake entity. ``kind`` company (``opportunity`` for a grant line);
    ``name``; ``key_fact`` the old description; ``evidence`` the source URL; ``flags`` ``pre_company`` for the
    pre-company tier; ``external_id`` ``<source_id>:<old id>``; the registry ids (``uei``, ``duns``, ``org_id``, under
    their schema-valid kinds; the intake qualifies them with the hint's ``source_id`` through the importer's
    ``registry_namespace``, H-343) and the website domain (``website``) as strong keys; the country,
    sectors and signal date as ``sources.registry.entity_from_registry_record`` maps them."""
    e = entity_from_registry_record(c)
    e["kind"] = "opportunity" if c.get("discovery_tier") == "grant" else "company"
    e["external_id"] = external_id(c)
    if c.get("discovery_tier") == "pre_company":
        e["flags"] = ["pre_company"]
    ids = c.get("entity_ids") or {}
    registry: dict[str, str] = {}
    for k in REGISTRY_KINDS:
        if (v := registry_value(ids.get(k))) is not None:
            registry[k] = v
    e.pop("registry_ids", None)
    if registry:
        e["registry_ids"] = registry
    domain = str(ids.get("domain") or "").strip().lower()
    if domain and _WEB_URL.match(f"https://{domain}"):
        e["website"] = f"https://{domain}"
    return e


def creation_status(c: Mapping[str, Any]) -> str:
    return str(c["decision"]) if c.get("decision") in ("baseline", "rejected") else "new"


# ------------------------------------------------------------------------------------------------ helpers
def _rows(conn: psycopg.Connection[Any], schema: str, query: str, params: Any = ()) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL(query).format(s=schema_ident(schema)), params)
        return list(cur.fetchall()) if cur.description else []


def domain_of(url: Any) -> str:
    """The old ``discovery.domain_of``."""
    d = re.sub(r"^https?://", "", str(url or "").strip().lower()).split("/")[0].split("?")[0]
    d = d[4:] if d.startswith("www.") else d
    return d if "." in d else ""


def pipeline_keys(signals: list[dict[str, Any]]) -> dict[str, str]:
    """The old ``discovery.pipeline_keys``: every pipeline company's normalized name AND canonical website domain."""
    keys = {}
    for e in signals:
        nm = cut.norm_company(e.get("company", ""))
        if nm and nm != "unknown":
            keys["nm:" + nm] = e.get("company", "")
        dom = domain_of(e.get("website", ""))
        if dom:
            keys["domain:" + dom] = e.get("company", "")
    return keys


def pipeline_match(c: Mapping[str, Any], pkeys: Mapping[str, str]) -> str | None:
    for k in cut.entity_keys(c):
        if k in pkeys:
            return pkeys[k]
    return None


def unique_run_id(started: datetime, previous: set[Any]) -> str:
    """The old run id: the write phase's start (Berlin wall time), ``" #n"`` on a clash with any earlier run."""
    run_id = started.strftime("%Y-%m-%d %H:%M:%S")
    n = 1
    while run_id in previous:
        n += 1
        run_id = started.strftime("%Y-%m-%d %H:%M:%S") + f" #{n}"
    return run_id


def _label(line: str) -> str:
    """The old ``page()`` label of a line."""
    return " ".join(re.split(r"\s[–\-:|]\s", line)[0].split()[:8])  # noqa: RUF001 - the old pattern verbatim


def record_lines(rec: Mapping[str, Any], fresh: list[str]) -> set[str]:
    """The watcher lines a page record was made from (its title line, its description line)."""
    out = set()
    for ln in fresh:
        if ln == rec.get("description") or ln == rec.get("raw_title") or _label(ln)[:120] == rec.get("name"):
            out.add(ln)
    return out


@dataclass
class Tally:
    added: list[tuple[dict[str, Any], str, str]] = field(default_factory=list)  # (record, candidate id, status)
    position: dict[str, int] = field(default_factory=dict)  # candidate id -> its record's place in the batch
    merged_n: int = 0
    known_pipe: int = 0
    known_inbox: int = 0
    prov_added: int = 0
    refused: int = 0
    pipe_names: list[str] = field(default_factory=list)
    merged_names: list[str] = field(default_factory=list)
    known_names: list[str] = field(default_factory=list)


# ------------------------------------------------------------------------------------------------ phase 3
def write(
    conn: psycopg.Connection[Any],
    schema: str,
    f: Fetched,
    *,
    clock: Callable[[], datetime],
    replay_of: str | None = None,
    trigger: str = "app",
) -> dict[str, Any]:
    """Phase 3 in the caller's transaction. ``replay_of``: an explicit REPLAY of an earlier run's deliveries (the same
    batch delivered again under that run's id: every delivery is then the intake's duplicate); the replay itself is
    recorded as a run of its own."""
    ensure_intake_open(conn, schema)
    conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"{schema}.intake",))
    started = clock()
    wall = berlin_now(started)
    rest_rows = _rows(conn, schema, "select body from {s}.documents where key = 'inbox.json#rest'")
    rest = rest_rows[0]["body"] if rest_rows and isinstance(rest_rows[0]["body"], dict) else {}
    previous = {rest.get("last_run")}
    previous |= {s.get("run_id") for s in history.imported_history(conn, schema).get("scans") or []
                 if isinstance(s, dict)}  # fmt: skip
    previous |= {r["run_id"] for r in _rows(conn, schema, "select run_id from {s}.scan_runs")}
    run_id = unique_run_id(wall, previous)
    delivery = replay_of or run_id  # the deliveries' run (``external_ref`` and the scan records)
    day = wall.strftime("%Y-%m-%d")
    signals = [conviction_record(r) for r in ConvictionStore(conn, schema).entry_rows()]
    pkeys = pipeline_keys(signals)
    ids = sorted({str(c.get("id")) for c in f.merged})
    scan_known = {
        r["k"]: (r["id"], r["company_id"])
        for r in _rows(
            conn,
            schema,
            "select attrs->'scan_record'->>'id' as k, id, company_id from {s}.candidates "
            "where attrs->'scan_record'->>'id' = any(%s) and coalesce(attrs->'scan_record'->>'run_id', '') <> %s",
            (ids, delivery),
        )
    }
    imported_known = {
        r["k"]: r["cid"]
        for r in _rows(
            conn,
            schema,
            "select alias_id as k, candidate_id as cid from {s}.candidate_aliases "
            "where namespace = 'candidate' and alias_id = any(%s) "
            "union select id, id from {s}.candidates where id = any(%s)",
            (ids, ids),
        )
    }
    t = Tally()
    deliveries: dict[str, list[tuple[dict[str, Any], bool]]] = {}  # source id -> [(record, known by a scan record)]
    for c in f.merged:
        cid = str(c.get("id"))
        if cid in scan_known and scan_known[cid][1] is not None:  # its own strong key: the intake re-reports it
            deliveries.setdefault(str(c.get("source_id") or ""), []).append((c, True))
            continue
        known_as = imported_known.get(cid) or (scan_known[cid][0] if cid in scan_known else None)
        if known_as is not None:  # the old "same source + same company as a previous scan: not new"
            t.known_inbox += 1
            t.known_names.append(c.get("name", ""))
            host = _ranking_record(conn, schema, known_as)
            if host is not None:
                t.prov_added += records.absorb(host, c, run_id)  # counted as the old absorb; never stored
            continue
        pipe_hit = pipeline_match(c, pkeys)
        if pipe_hit:
            t.known_pipe += 1
            t.pipe_names.append(pipe_hit)
            continue
        deliveries.setdefault(str(c.get("source_id") or ""), []).append((c, False))

    position = {id(c): i for i, c in enumerate(f.merged)}  # the old summary lists the added records in batch order
    blocked: list[dict[str, Any]] = []  # batch records whose items may not advance
    replayed: set[str] = set()  # sources whose delivery was a duplicate: nothing advances
    report = copy.deepcopy(f.report)  # never the phase-2 rows themselves: a replay writes from the same batch
    rows_by_source = {r.get("source_id"): r for r in report if r.get("tier") != "system" and r.get("status") == "ok"}
    for sid, items in deliveries.items():
        entities = [entity_of(c) for c, _ in items]
        hints: dict[int, dict[str, Any]] = {
            i: {
                "status": creation_status(c),
                "record": records.created(c, delivery, day),
                "run_id": delivery,
                "source_id": sid,
            }
            for i, (c, _) in enumerate(items)
        }
        store = PostgresIntake(conn, schema)
        batch = TrustedBatch(Origin.REGISTRY_SCAN, SUBMITTED_BY, entities, external_ref=f"scan:{delivery}:{sid}",
                             scan=hints)  # fmt: skip
        res = IntakeService(store, resolver=store).submit_trusted(batch)
        row = rows_by_source.get(sid)
        refused: dict[int, str] = {}
        if res.outcome == "duplicate":
            replayed.add(sid)
            original = _rows(conn, schema, "select outcome_detail from {s}.intake_submissions where sha256 = %s",
                             (res.sha256,))  # fmt: skip
            detail = original[0]["outcome_detail"] if original else {}
            refused = {int(r["index"]): (r.get("issues") or [""])[0] for r in detail.get("refused") or []}
            delivered = 0
            for i, (c, _known) in enumerate(items):
                blocked.append(c)
                if i not in refused:
                    delivered += 1
                    t.known_inbox += 1
                    t.known_names.append(c.get("name", ""))
            if row is not None and delivered:
                row["already_delivered"] = delivered
                row["note"] = (row.get("note") or "") + f" · {delivered} item(s) already delivered"
        else:
            refused = {i: str(issues[0]) if issues else "" for i, issues in res.refused}
            by_index = {r["index"]: r for r in res.resolution}
            for i, (c, known) in enumerate(items):
                if i in refused:
                    blocked.append(c)
                    continue
                r = by_index[i]
                t.prov_added += int(r.get("provenance_added") or 0)
                if r["result"] == "created":
                    t.added.append((hints[i]["record"], str(r["candidate_id"]), hints[i]["status"]))
                    t.position[str(r["candidate_id"])] = position[id(c)]
                elif known:
                    t.known_inbox += 1
                    t.known_names.append(c.get("name", ""))
                else:
                    t.merged_n += 1
                    t.merged_names.append(_name_of(conn, schema, str(r["candidate_id"])))
        if refused:
            t.refused += len(refused)
            if row is not None:
                first = refused[min(refused)]
                row["refused"] = len(refused)
                row["note"] = (row.get("note") or "") + f" · {len(refused)} item(s) refused by the intake: {first}"

    t.added.sort(key=lambda a: t.position[a[1]])
    summary = _summary(report, t, run_id, wall, berlin_now(clock()))
    src_rows = [r for r in report if r.get("tier") != "system"]
    sources = [
        {
            "source": r.get("source"),
            "source_id": r.get("source_id", ""),
            "status": r.get("status"),
            "raw": r.get("raw"),
            "count": r.get("count"),
            "baseline": r.get("baseline"),
            "url": r.get("url", ""),
            "note": (r.get("note") or "")[:200],
        }
        for r in src_rows
    ]
    finished = clock()
    conn.execute(
        sql.SQL(
            "insert into {s}.scan_runs (run_id, started_at, finished_at, days, trigger, summary, report, sources) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s)"
        ).format(s=schema_ident(schema)),
        (run_id, started, max(finished, started), f.days, trigger, Json(summary), Json(report), Json(sources)),
    )
    _save_sources(conn, schema, f, blocked, replayed)
    _save_snapshots(conn, schema, f, blocked, replayed, run_id)
    return summary


def _ranking_record(conn: psycopg.Connection[Any], schema: str, candidate_id: str) -> dict[str, Any] | None:
    rows = _rows(conn, schema, "select * from {s}.candidates where id = %s", (candidate_id,))
    return copy.deepcopy(ranking_input(rows[0])[0]) if rows else None


def _name_of(conn: psycopg.Connection[Any], schema: str, candidate_id: str) -> str:
    rows = _rows(conn, schema, "select name from {s}.candidates where id = %s", (candidate_id,))
    return str(rows[0]["name"]) if rows else ""


def _summary(
    report: list[dict[str, Any]], t: Tally, run_id: str, started: datetime, finished: datetime
) -> dict[str, Any]:
    """The old ``last_summary`` (the old key order), plus ``refused`` and ``triage`` (declared, revision 2 / d).
    Appends the old system row to ``report`` when anything was known or merged."""
    src_rows = [r for r in report if r.get("tier") != "system"]
    ok_rows = [r for r in src_rows if r.get("status") == "ok"]
    failed_rows = [r for r in src_rows if r.get("status") == "failed"]
    off_rows = [r for r in src_rows if r.get("status") == "off"]
    raw = sum(int(r.get("raw") or 0) for r in ok_rows)
    merged_batch = sum(int(r.get("merged") or 0) for r in report if r.get("tier") == "system")
    if t.merged_n or t.known_pipe or t.known_inbox:
        report.append(
            {
                "source": "Entity resolution (inbox/pipeline)",
                "tier": "system",
                "status": "ok",
                "geo": ["ALL"],
                "merged_inbox": t.merged_n,
                "known_inbox": t.known_inbox,
                "known_pipeline": t.known_pipe,
                "note": f"{t.merged_n} merged into existing candidates · {t.known_inbox} already known (skipped, not "
                f"new) · {t.known_pipe} {history.PIPELINE_EXISTING_LABEL.lower()} (skipped, never 'new this run')",
            }
        )
    added = t.added
    return {
        "new": sum(s == "new" for _, _, s in added),
        "baseline": sum(s == "baseline" for _, _, s in added),
        "noise": sum(s == "rejected" for _, _, s in added),
        "pre_company_new": sum(
            s == "new" and c["discovery_tier"] == "pre_company" and c.get("name") != "UNKNOWN" for c, _, s in added
        ),
        "run_id": run_id,
        "scan_started": started.strftime("%Y-%m-%d %H:%M:%S"),
        "scan_finished": finished.strftime("%Y-%m-%d %H:%M:%S"),
        "sources_attempted": len(ok_rows) + len(failed_rows),
        "sources_ok": len(ok_rows),
        "sources_failed": len(failed_rows),
        "sources_off": len(off_rows),
        "raw_records": raw,
        "records_after_source_filters": sum(int(r.get("count") or 0) for r in ok_rows),
        "merged_cross_source": merged_batch,
        "merged_into_existing": t.merged_n,
        "provenance_added": t.prov_added,
        "known_skipped": t.known_inbox,
        "known_skipped_names": sorted(set(t.known_names))[:100],
        "known_pipeline": t.known_pipe,
        "known_pipeline_names": sorted(set(t.pipe_names)),
        "pipeline_label": history.PIPELINE_EXISTING_LABEL,
        "new_companies": [
            {
                "id": cid,  # the candidate's id (the old id stays its scan record's ``id``)
                "name": c.get("name", ""),
                "source": c.get("source", ""),
                "source_id": c.get("source_id", ""),
                "source_url": c.get("source_url", ""),
                "source_date": c.get("source_date") or "UNKNOWN",
                "first_seen": c.get("first_seen", ""),
                "decision": s,
            }
            for c, cid, s in added
            if s == "new"
        ][:200],
        "baseline_companies": [
            {
                "id": cid,
                "name": c.get("name", ""),
                "source": c.get("source", ""),
                "source_url": c.get("source_url", ""),
                "first_seen": c.get("first_seen", ""),
            }
            for c, cid, s in added
            if s == "baseline"
        ][:200],
        "merged_names": sorted(set(t.merged_names))[:100],
        "refused": t.refused,
        "triage": TRIAGE_NOTE,
    }


def _blocked_by_source(f: Fetched, blocked: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Every record (of any source) that ended in a blocked batch record, by its own source."""
    hosts = {id(c) for c in blocked}
    out: dict[str, list[dict[str, Any]]] = {}
    for rec in f.records:
        if id(f.host_of.get(id(rec), rec)) in hosts:
            out.setdefault(str(rec.get("source_id") or ""), []).append(rec)
    return out


def _save_sources(
    conn: psycopg.Connection[Any], schema: str, f: Fetched, blocked: list[dict[str, Any]], replayed: set[str]
) -> None:
    """The old race-safe persistence: the LIVE registry re-read, ONLY the runtime keys of completed sources merged in
    (a toggle made mid-scan survives), timeouts counted. A refused record's cursor key is kept out (revision 2); a
    replayed source keeps its stored cursor (revision 3)."""
    store = SourcesStore(conn, schema)
    store._lock()
    stored = store.stored()
    live = load_registry({"sources": stored})["sources"]
    by_id = {s.get("id"): s for s in live if isinstance(s, dict)}
    before = {s.get("id"): s for s in f.sources}
    keys_of: dict[int, str | None] = {}
    for res in f.done.values():
        for rec, key in res.ctx.records if res.ctx is not None else []:
            keys_of[id(rec)] = key
    blocked_keys: dict[str, set[str]] = {}
    for sid, recs in _blocked_by_source(f, blocked).items():
        blocked_keys[sid] = {k for r in recs if (k := keys_of.get(id(r))) is not None}
    for res in f.done.values():
        src = res.src
        if src is None:
            continue
        tgt = by_id.get(src["id"])
        if tgt is None:
            continue  # removed while scanning
        for k in cut.RUNTIME_KEYS:
            if k not in src:
                continue
            if k == "hwm" and src["id"] in replayed:
                continue  # nothing advances on a replay
            value = copy.deepcopy(src[k])
            if k == "hwm" and isinstance(value, dict) and isinstance(value.get("seen"), list):
                had = set(((before.get(src["id"]) or {}).get("hwm") or {}).get("seen") or [])
                drop = blocked_keys.get(str(src["id"]), set()) - had
                value["seen"] = [x for x in value["seen"] if x not in drop]
            tgt[k] = value
    for sid in f.timeout_ids:
        tgt = by_id.get(sid)
        if tgt is not None:
            tgt["failures_in_row"] = int(tgt.get("failures_in_row") or 0) + 1
            tgt["last_scan"] = f.now_stamp
    store.save_registry(stored, live)


def _save_snapshots(
    conn: psycopg.Connection[Any],
    schema: str,
    f: Fetched,
    blocked: list[dict[str, Any]],
    replayed: set[str],
    run_id: str,
) -> None:
    """The new baseline of every finished watcher (its page's lines), minus the lines of refused records."""
    by_source = _blocked_by_source(f, blocked)
    for res in f.done.values():
        src, ctx = res.src, res.ctx
        if src is None or ctx is None or src.get("parser") != "page_diff" or src["id"] in replayed:
            continue
        uid = cut._uid(src["url"])
        key = uid + ".json"
        if key not in ctx.saved:
            continue  # the page was never fetched: the last good baseline stays
        lines = ctx.saved[key]
        base = f.baselines.get(key) or {}
        old = list(base.get("lines") or [])
        fresh = [ln for ln in lines if ln not in set(old)] if old else list(lines)
        drop: set[str] = set()
        for rec in by_source.get(str(src["id"]), []):
            drop |= record_lines(rec, fresh)
        keep = [ln for ln in lines if ln not in drop]
        conn.execute(
            sql.SQL(
                "insert into {s}.scan_watch_snapshots (uid, url, source_id, lines, seeded_from, run_id) "
                "values (%s, %s, %s, %s, %s, %s) on conflict (uid) do update set url = excluded.url, "
                "source_id = excluded.source_id, lines = excluded.lines, run_id = excluded.run_id, updated_at = now()"
            ).format(s=schema_ident(schema)),
            (uid, src["url"], src["id"], Jsonb(keep), base.get("seeded_from"), run_id),
        )

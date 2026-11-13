"""Automatic machine triage (review 035b): the old ``services/auto_triage.py`` over pz — after a scan, the hourly
``triage_retry`` job and Retry now. Proposal-only: nothing here writes a decision, a candidate status, a Conviction
record, a score, a verification or the Radar (decision j).

* **One run at a time, across the three triggers** (decision g, revision 2): every trigger first takes the shared
  session lock (``records.take_lock``, ``pg_try_advisory_lock``); a second caller gets the old "already in progress"
  answer and recovers nothing. The holder keeps it through recovery, the run and its finalization.
* **Recovery** (revision 3): an auto-run row still ``running`` while we hold the lock belonged to a dead process.
  Its recorded dispositions are final (``proposed`` / ``needs_human`` / ``error`` accounted, no repeat call;
  ``decided_meanwhile`` / ``unchanged_skipped`` left out; ``changed_meanwhile`` pending with no attempt counted); a
  selected id with NO disposition is re-checked (absorbed or decided meanwhile, by its selection mark: dropped) and
  otherwise kept pending as the old ``recover_interrupted`` did. The row is finalized ``failed``.
* **The selection** (decision f): undecided candidates that this scan created or re-observed, that an earlier run
  left pending or the retry state says are due, or whose current proposal is stale. The order: ``first_seen_at``,
  then ``id``. Each selected id carries its SELECTION MARK (the highest ``triage_decisions.seq`` of the survivor),
  read in the same snapshot.
* **The record** (``_execute``): the old ``run`` record, built from the per-candidate dispositions; the summary
  sentence and the retry items are the old ones (``auto_rules``, cut by script). Reasons come from the gateway's
  ``error_kind`` (decision c), never from parsing its message.
* **Paid off** (decision d): the hourly job writes no run when the gateway would refuse every call and notes "Paid AI
  is off — N candidate(s) waiting for machine triage."; Retry now and the post-scan run still run.
* **The live schema stays closed until the import** (decision i): every trigger checks ``ensure_intake_open``.
"""

from __future__ import annotations

import functools
import logging
import os
import secrets
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import psycopg

from projectzero.core import occurrence
from projectzero.core.db import snapshot_transaction, transaction
from projectzero.core.inference import config as icfg
from projectzero.core.inference import errors as perrors
from projectzero.core.inference import gateway
from projectzero.core.inference.pg_store import PostgresBudgetStore
from projectzero.core.inference.providers import ProviderError
from projectzero.core.inference.providers import resolve as resolve_provider
from projectzero.dealflow.candidates import DealFlowStore
from projectzero.dealflow.intake import postgres as intake_pg
from projectzero.dealflow.triage import auto_rules, card, records, runner
from projectzero.network.view import BERLIN, berlin_now

log = logging.getLogger(__name__)
_rules: Any = auto_rules  # the cut old code is untyped (see auto_rules.py): its functions are called through this alias
ENABLE_ENV = "PZ_AUTO_TRIAGE"
CONFIG_KEY = "auto_triage_after_scan"
BUSY_ROUTE = "A machine triage run is already in progress."  # the old route's answers
NOTHING_ROUTE = "Nothing is waiting for a retry."
BUSY = "a machine triage run is already in progress"  # the old ``run_retry`` reasons (the job's note)
NOTHING = "nothing is waiting for a retry"
SWITCHED_OFF = "automatic triage is switched off"
SCAN_BUSY = "an automatic triage run is already in progress"  # the old ``start`` reason
PAID_OFF_NOTE = "Paid AI is off — {n} candidate(s) waiting for machine triage."  # decision (d)
INTERRUPTED_NOTE = "interrupted by an app restart"
INTERRUPTED_REASON = "interrupted by an app restart — will retry after the next scan"
DEADLINE_REASON = "the background job's time limit was reached — kept for an automatic retry"
CHANGED_REASON = "the candidate changed while it was being triaged — kept for an automatic retry"  # revision 2
NO_CHANGES = "no new or changed candidates"
TS_FORMAT = "%Y-%m-%dT%H:%M:%S"


@dataclass(frozen=True)
class Deps:
    """What a trigger reaches the outside world through. ``gateway_kw``: the gateway's injectables (``env``,
    ``providers``, ``config``, ``clock``, ``sleep``, ``new_id``); ``clock``: the record clock (aware; default now in
    Berlin); ``new_hex``: the run id's suffix; ``env``: ``PZ_AUTO_TRIAGE`` and the paid check (default
    ``os.environ``); ``complete``: the gateway call (default ``gateway.complete``; the parity records through it);
    ``deadline``: a ``monotonic()`` bound for the run (the scan job's 900 s); ``hooks``: the runner's test seams;
    ``still_due``: the job runner's occurrence check, run on the lock's connection."""

    gateway_kw: Mapping[str, Any] = field(default_factory=dict)
    clock: Callable[[], datetime] | None = None
    new_hex: Callable[[], str] | None = None
    env: Mapping[str, str] | None = None
    complete: Callable[..., gateway.Result] | None = None
    deadline: float | None = None
    hooks: runner.Hooks | None = None
    still_due: occurrence.StillDue | None = None


def _aware(deps: Deps) -> datetime:
    t = deps.clock() if deps.clock is not None else datetime.now(BERLIN)
    return berlin_now(t) if t.tzinfo is not None else t.replace(tzinfo=BERLIN)


def _naive(deps: Deps) -> datetime:
    """The old ``datetime.now()``: naive Berlin wall time."""
    return _aware(deps).replace(tzinfo=None)


def _ts(deps: Deps) -> str:
    return _naive(deps).strftime(TS_FORMAT)


def _env(deps: Deps) -> Mapping[str, str]:
    return deps.env if deps.env is not None else os.environ


# ------------------------------------------------------------------ the inputs (one snapshot)
@dataclass
class State:
    new: list[dict[str, Any]]  # the undecided candidates' old-shaped records, in first_seen_at / id order
    proposals: dict[str, dict[str, Any]]
    runs: list[dict[str, Any]]
    rs: dict[str, Any]
    aliases: dict[str, str]
    seqs: dict[str, int]
    config: Any

    @property
    def by_id(self) -> dict[str, dict[str, Any]]:
        return {str(c["id"]): c for c in self.new}


def load_state(conn: psycopg.Connection[Any], schema: str) -> State:
    amap = records.aliases(conn, schema)
    new = [runner.record_of(r) for r in runner.undecided(conn, schema)]
    return State(
        new=new,
        proposals=records.current_proposals(conn, schema),
        runs=records.auto_runs(conn, schema)["runs"],
        rs=records.retry_state(conn, schema, amap),
        aliases=amap,
        seqs=records.latest_seqs(conn, schema, amap),
        config=records._document(conn, schema, "config.json"),
    )


def enabled(env: Mapping[str, str], config: Any) -> bool:
    """The old ``enabled``."""
    if str(env.get(ENABLE_ENV, "1")).strip().lower() in ("0", "false", "no", "off"):
        return False
    cfg = config if isinstance(config, dict) else {}
    return cfg.get(CONFIG_KEY, True) is not False


def current(p: Any, c: Mapping[str, Any] | None) -> bool:
    """The old ``_current``: a valid v3 proposal that still matches the candidate's current input."""
    if (
        not isinstance(p, Mapping)
        or not c
        or p.get("status") != "proposed"
        or p.get("prompt_version") != card.PROMPT_VERSION
    ):
        return False
    return p.get("input_sha") == card.card_sha(c)


def _items(r: Any) -> list[Any]:
    if not isinstance(r, dict):
        return []
    return list(r.get("pending") or []) + list(r.get("failed") or [])


def pending_ids(st: State) -> set[str]:
    """The old ``_pending_ids``: candidates an earlier automatic run could not triage (ids mapped to survivors)."""
    return {
        st.aliases.get(str(p["id"]), str(p["id"]))
        for r in st.runs[-5:]
        for p in _items(r)
        if isinstance(p, dict) and p.get("id")
    }


def legacy_retryable(st: State, rs: dict[str, Any]) -> None:
    """The old ``_legacy_retryable``: runs recorded before the retry state existed join the retry schedule."""
    for r in st.runs[-5:]:
        for f in _items(r):
            if not isinstance(f, dict):
                continue
            cid = st.aliases.get(str(f.get("id")), str(f.get("id"))) if f.get("id") else None
            p = st.proposals.get(cid or "") or {}
            if not cid or cid in rs or p.get("status") == "proposed":
                continue
            if perrors.category(p.get("error_kind"), p.get("error") or f.get("reason")) == "RETRYABLE":
                when = str(r.get("finished") or r.get("started") or "")[:19]
                try:
                    nxt = (
                        (datetime.fromisoformat(when) + timedelta(minutes=auto_rules.RETRY_BACKOFF_MIN[0])).isoformat(
                            timespec="seconds"
                        )
                        if when
                        else None
                    )
                except ValueError:
                    nxt = None
                rs[cid] = {
                    "attempts": 1,
                    "kind": p.get("error_kind"),
                    "category": "RETRYABLE",
                    "reason": _rules._explain(p.get("error_kind"), p.get("error") or f.get("reason")),
                    "first_failed": when,
                    "last_failed": when,
                    "next_eligible": nxt,
                }


def retry_due(st: State, now: datetime, force: bool = False) -> list[str]:
    """The old ``retry_due``: undecided candidates waiting for a retry whose time has come (``force``: all)."""
    now_s = now.isoformat(timespec="seconds")
    rs = dict(st.rs)
    legacy_retryable(st, rs)
    by = st.by_id
    out = []
    for cid, r in rs.items():
        c = by.get(cid)
        if not c or (st.proposals.get(cid) or {}).get("status") == "proposed":
            continue
        if force or (r.get("attempts", 0) < auto_rules.MAX_AUTO_RETRIES and (r.get("next_eligible") or "") <= now_s):
            out.append(cid)
    return out


def select(st: State, scan_run_id: str, now: datetime) -> list[str]:
    """The old ``select`` (decision f)."""
    pending = pending_ids(st) | set(retry_due(st, now))
    out = []
    for c in st.new:
        cid = str(c["id"])
        touched = c.get("first_seen_run") == scan_run_id or c.get("last_observed") == scan_run_id
        p = st.proposals.get(cid) or {}
        retry = cid in pending and p.get("status") != "proposed"
        stale = p.get("status") == "proposed" and not current(p, c)
        if touched or retry or stale:
            out.append(cid)
    return out


def reason(kind: str, stopped: str) -> str:
    """The old ``_reason`` by the gateway's ``error_kind`` (decision c), with the new paid switch's name."""
    if kind == "budget_blocked":
        return (
            "the configured AI budget limit was reached — kept; it runs again when the budget allows "
            "(caps are never overridden)"
        )
    if kind == "not_configured":
        return "DeepInfra is not configured (DEEPINFRA_API_KEY missing) — kept; it runs once the key is set"
    if kind == "disabled":
        return f"paid AI is switched off {auto_rules.PAID_OFF_NEW} — kept; it runs once paid AI is on again"
    if kind in ("auth", "billing"):
        return "DeepInfra refused the request (API key / billing) — kept; check the DeepInfra account"
    return f"{_rules._explain(kind, stopped)} — kept for an automatic retry"


# ------------------------------------------------------------------ the paid check (decision d)
def would_refuse(gateway_kw: Mapping[str, Any]) -> bool:
    """Whether the gateway would refuse EVERY call of a run (the CHEAP role: off, no provider, no key, no price, or
    the paid switch off): the hourly job then writes no run."""
    given_cfg, given_env = gateway_kw.get("config"), gateway_kw.get("env")
    cfg: Mapping[str, Any] = given_cfg if isinstance(given_cfg, Mapping) else icfg.load()
    env: Mapping[str, str] = given_env if isinstance(given_env, Mapping) else os.environ
    rcfg = (cfg.get("roles") or {}).get("CHEAP")
    if not isinstance(rcfg, Mapping) or not rcfg.get("enabled", True) or not rcfg.get("provider"):
        return True
    try:
        prov = resolve_provider(str(rcfg["provider"]), cfg, gateway_kw.get("providers"))
    except ProviderError:
        return True
    if not bool(getattr(prov, "paid", True)):
        return False
    if prov.ready(env) or icfg.price(cfg, str(rcfg.get("model") or "")) is None:
        return True
    return not icfg.paid_enabled(env)


# ------------------------------------------------------------------ one run (the old ``run``)
def _complete(db_url: str, schema: str, deps: Deps) -> Callable[..., gateway.Result]:
    fn = deps.complete or gateway.complete
    return functools.partial(fn, store=PostgresBudgetStore(db_url, schema), **dict(deps.gateway_kw))


def _new_run_id(deps: Deps) -> str:
    hex4 = (deps.new_hex() if deps.new_hex is not None else secrets.token_hex(2))[:4]
    return "triage-" + _naive(deps).strftime("%Y%m%d-%H%M%S-") + hex4


def _execute(
    db_url: str,
    schema: str,
    deps: Deps,
    *,
    scan_run_id: str,
    kind: str,
    ids: list[str],
    marks: Mapping[str, int],
    retry: bool = False,
) -> dict[str, Any]:
    rec: dict[str, Any] = {"scan_run_id": scan_run_id, "started": _ts(deps), "selected": len(ids), "state": "running"}
    started_at = _aware(deps)
    if not ids:
        rec.update(
            state="done", finished=_ts(deps), triaged=0, counts={}, pending=[], failed=[], usd=0.0, note=NO_CHANGES
        )
        with transaction(db_url) as conn:
            intake_pg.ensure_intake_open(conn, schema)
            records.insert_auto_run(
                conn,
                schema,
                scan_run_id=scan_run_id,
                kind=kind,
                triage_run_id=None,
                state="done",
                selection=[],
                record=rec,
                started_at=started_at,
                finished_at=_aware(deps),
            )
        return rec
    run_id = _new_run_id(deps)
    running = {
        "scan_run_id": scan_run_id,
        "started": rec["started"],
        "state": "running",
        "selected": len(ids),
        "ids": list(ids),
        **({"retry": True} if retry else {}),
    }
    with transaction(db_url) as conn:
        intake_pg.ensure_intake_open(conn, schema)
        row_id = records.insert_auto_run(
            conn,
            schema,
            scan_run_id=scan_run_id,
            kind=kind,
            triage_run_id=run_id,
            state="running",
            selection=[[i, int(marks.get(i, 0))] for i in ids],
            record=running,
            started_at=started_at,
            finished_at=None,
        )
    stop_kind = stopped = ""
    usd = 0.0
    try:
        out = runner.run(
            db_url,
            schema,
            run_id=run_id,
            ids=ids,
            marks=marks,
            complete=_complete(db_url, schema, deps),
            clock=lambda: _aware(deps),
            now_naive=lambda: _naive(deps),
            config=deps.gateway_kw.get("config"),
            deadline=deps.deadline,
            hooks=deps.hooks,
        )
        stop_kind, stopped, usd = out.stop_kind, out.stop_text, float(out.summary.get("usd") or 0.0)
    except Exception as e:  # never let triage errors escape into the scan (the old try/except)
        log.exception("automatic triage failed")
        stopped = f"error: {type(e).__name__}: {str(e)[:160]}"
        stop_kind = _rules._stop_kind(stopped)
        with transaction(db_url) as conn:  # (b): what committed stays accounted; the spend is the ledger's
            usd = records.run_usd(conn, schema, run_id)
    return _finalize(db_url, schema, deps, row_id, rec, run_id, ids, stop_kind, stopped, usd)


def _changed_item(cid: str, name: Any, prior: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        "id": cid,
        "name": name,
        "reason": CHANGED_REASON,
        "category": "RETRYABLE",
        "retry": "automatic",
        "next_try": None,
        "attempts": int((prior or {}).get("attempts", 0)),
    }


def _finalize(
    db_url: str,
    schema: str,
    deps: Deps,
    row_id: int,
    rec: dict[str, Any],
    run_id: str,
    ids: list[str],
    stop_kind: str,
    stopped: str,
    usd: float,
) -> dict[str, Any]:
    now = _naive(deps)
    with transaction(db_url) as conn:
        intake_pg.ensure_intake_open(conn, schema)
        its = records.items(conn, schema, run_id)
        names = _names(conn, schema, ids)
        counts: dict[str, int] = {}
        pending: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        technical: list[dict[str, Any]] = []
        unchanged = decided = 0
        for cid in ids:
            got = its.get(cid)
            if got is None:  # the runner stopped before this candidate (budget / key / paid switch / outage)
                kind = stop_kind or _rules._stop_kind(stopped)
                late = kind == runner.DEADLINE_KIND  # the job's time limit: retried like a timeout
                prior = records.retry_entry(conn, schema, cid)
                part = {cid: prior} if prior is not None else {}
                item = _rules._retry_item(
                    part, cid, names.get(cid), "timeout" if late else kind, stopped or "", now, count=False
                )
                item["reason"] = DEADLINE_REASON if late else f"{reason(kind, stopped)}"
                records.put_retry(conn, schema, cid, part[cid])
                pending.append(item)
                continue
            disposition, detail = got
            if disposition in ("proposed", "needs_human"):
                p = str(detail.get("proposal"))
                counts[p] = counts.get(p, 0) + 1
            elif disposition == "error":
                technical.append({"id": cid, "kind": detail.get("kind"), "error": perrors.compact(detail.get("error"))})
                item = dict(detail.get("item") or {})
                (pending if item.get("retry") != "manual" else failed).append(item)
            elif disposition == "unchanged_skipped":
                unchanged += 1  # already had a current v3 proposal — skipped by the runner, zero calls
            elif disposition == "decided_meanwhile":
                decided += 1  # revision 3: a newer state won; not pending
            else:  # changed_meanwhile: retryable, no attempt counted
                pending.append(_changed_item(cid, names.get(cid), records.retry_entry(conn, schema, cid)))
        done = sum(counts.values())
        ok_all = done + unchanged + len(pending) + len(failed) + decided == len(ids)
        if not ok_all:
            log.error("auto-triage accounting mismatch for %s", rec["scan_run_id"])
        accounting: dict[str, Any] = {
            "selected": len(ids),
            "processed": done,
            "unchanged": unchanged,
            "retry_pending": len(pending),
            "needs_manual_retry": len(failed),
        }
        if decided:
            accounting["decided_meanwhile"] = decided
        accounting["balanced"] = ok_all
        rec.update(
            state="done" if not pending and not failed else ("failed" if not counts and not unchanged else "partial"),
            finished=_ts(deps),
            triage_run_id=run_id,
            triaged=done,
            counts=counts,
            unchanged_skipped=unchanged,
            pending=pending,
            failed=failed,
            usd=usd,
            stopped=perrors.compact(stopped) if stopped else None,
            technical=technical,
            accounting=accounting,
        )
        rec["summary"] = _rules.summary(rec)
        records.finish_auto_run(conn, schema, row_id, rec, _aware(deps))
    return rec


def _names(conn: psycopg.Connection[Any], schema: str, ids: list[str]) -> dict[str, Any]:
    return {str(r["id"]): runner.record_of(r).get("name") for r in runner._candidates(conn, schema, ids)}


# ------------------------------------------------------------------ recovery (revision 3)
def recover(db_url: str, schema: str, deps: Deps) -> int:
    """Finalize every auto-run row still ``running`` (the caller holds the run lock, so its process is gone)."""
    n = 0
    with transaction(db_url) as conn:
        intake_pg.ensure_intake_open(conn, schema)
        for row in records.running_auto_runs(conn, schema):
            _recover_one(conn, schema, deps, row)
            n += 1
    return n


def _recover_one(conn: psycopg.Connection[Any], schema: str, deps: Deps, row: Mapping[str, Any]) -> None:
    sel = [(str(i), int(m)) for i, m in row["selection"]]
    ids = [i for i, _ in sel]
    marks = dict(sel)
    its = records.items(conn, schema, str(row["triage_run_id"])) if row["triage_run_id"] else {}
    names = _names(conn, schema, ids)
    rows = {str(r["id"]): r for r in runner._candidates(conn, schema, ids)}
    counts: dict[str, int] = {}
    pending: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    technical: list[dict[str, Any]] = []
    unchanged = decided = interrupted = 0
    dropped: dict[str, Any] = {}
    for cid in ids:
        got = its.get(cid)
        if got is None:  # never reached, or in flight: re-checked before it is queued
            sid = DealFlowStore(conn, schema).resolve_id("candidate", cid)
            r = rows.get(cid)
            if sid != cid:
                dropped[cid] = {"why": "absorbed", "survivor": sid}
            elif r is None or r["status"] != "new" or records.latest_seq(conn, schema, cid) > marks.get(cid, 0):
                dropped[cid] = {"why": "decided"}
            else:
                pending.append({"id": cid, "reason": INTERRUPTED_REASON})
                interrupted += 1
            continue
        disposition, detail = got
        if disposition in ("proposed", "needs_human"):
            p = str(detail.get("proposal"))
            counts[p] = counts.get(p, 0) + 1
        elif disposition == "error":
            technical.append({"id": cid, "kind": detail.get("kind"), "error": perrors.compact(detail.get("error"))})
            item = dict(detail.get("item") or {})
            (pending if item.get("retry") != "manual" else failed).append(item)
        elif disposition == "unchanged_skipped":
            unchanged += 1
        elif disposition == "decided_meanwhile":
            decided += 1
        else:
            pending.append(_changed_item(cid, names.get(cid), records.retry_entry(conn, schema, cid)))
    rec = dict(row["record"])
    done = sum(counts.values())
    rec.update(
        state="failed",
        finished=_ts(deps),
        note=INTERRUPTED_NOTE,
        pending=pending,
        failed=failed,
        triaged=done,
        counts=counts,
    )
    if unchanged:
        rec["unchanged_skipped"] = unchanged
    if technical:
        rec["technical"] = technical
    rec["accounting"] = {
        "selected": len(ids),
        "processed": done,
        "unchanged": unchanged,
        "retry_pending": len(pending),
        "needs_manual_retry": len(failed),
        "decided_meanwhile": decided + len(dropped),
        "interrupted": interrupted,
        "balanced": done + unchanged + len(pending) + len(failed) + decided + len(dropped) == len(ids),
    }
    if dropped:
        rec["dropped"] = dropped
    records.finish_auto_run(conn, schema, int(row["id"]), rec, _aware(deps))


# ------------------------------------------------------------------ the triggers
def _locked(
    db_url: str,
    schema: str,
    deps: Deps,
    work: Callable[[], dict[str, Any]],
    held: psycopg.Connection[Any] | None = None,
) -> dict[str, Any]:
    """``work`` holding the run lock (taken here unless the caller passes it), after recovery; released on every
    path. ``TriageBusy`` when another session holds it."""
    lock = held if held is not None else records.take_lock(db_url, schema)
    try:
        occurrence.check(deps.still_due, lock)
        recover(db_url, schema, deps)
        return work()
    finally:
        records.release_lock(lock, schema)


def _scan_work(db_url: str, schema: str, deps: Deps, scan_run_id: str) -> dict[str, Any]:
    with snapshot_transaction(db_url) as conn:
        st = load_state(conn, schema)
    ids = select(st, scan_run_id, _naive(deps))
    marks = {i: st.seqs.get(i, 0) for i in ids}
    return _execute(db_url, schema, deps, scan_run_id=scan_run_id, kind="scan", ids=ids, marks=marks)


def after_scan(db_url: str, schema: str, scan_run_id: str, deps: Deps | None = None) -> dict[str, Any]:
    """The old ``start`` + ``run`` after a COMMITTED scan, synchronously (the Find thread and the scan job call it).
    Returns the run's record, or ``{"started": False, "reason"}``. Never raises an ``Exception`` (the scan must
    never fail because of triage)."""
    deps = deps or Deps()
    try:
        with snapshot_transaction(db_url) as conn:
            intake_pg.ensure_intake_open(conn, schema)
            config = records._document(conn, schema, "config.json")
        if not enabled(_env(deps), config):
            return {"started": False, "reason": "disabled"}
        return _locked(db_url, schema, deps, lambda: _scan_work(db_url, schema, deps, scan_run_id))
    except records.TriageBusy:
        return {"started": False, "reason": SCAN_BUSY}
    except Exception as e:
        log.exception("could not run automatic triage (scan unaffected)")
        return {"started": False, "reason": f"{type(e).__name__}: {str(e)[:120]}"}


def _retry_work(db_url: str, schema: str, deps: Deps, force: bool) -> dict[str, Any]:
    """The old ``run_retry`` body (the caller holds the lock)."""
    with snapshot_transaction(db_url) as conn:
        st = load_state(conn, schema)
    if not enabled(_env(deps), st.config) and not force:
        return {"started": False, "reason": SWITCHED_OFF}
    ids = retry_due(st, _naive(deps), force=force)  # the retry state's order (the old accounting order)
    if not ids:
        return {"started": False, "reason": NOTHING}
    if not force and would_refuse(deps.gateway_kw):  # decision (d): no churn while paid calls are off
        return {"started": False, "reason": PAID_OFF_NOTE.format(n=len(ids)), "paid_off": True}
    rid = ("retry-now " if force else "retry ") + _ts(deps)
    marks = {i: st.seqs.get(i, 0) for i in ids}
    rec = _execute(
        db_url, schema, deps, scan_run_id=rid, kind="retry_now" if force else "retry", ids=ids, marks=marks, retry=True
    )
    return {"started": True, **rec}


def run_retry(db_url: str, schema: str, *, force: bool = False, deps: Deps | None = None) -> dict[str, Any]:
    """The hourly job's entry point (the old ``run_retry``): the answer, whose ``summary`` or ``reason`` is the note."""
    deps = deps or Deps()
    with transaction(db_url) as conn:
        intake_pg.ensure_intake_open(conn, schema)
    try:
        return _locked(db_url, schema, deps, lambda: _retry_work(db_url, schema, deps, force))
    except records.TriageBusy:
        return {"started": False, "reason": BUSY}


def retry_note(answer: Mapping[str, Any]) -> str:
    """The old ``_run_triage_retry`` note."""
    return str(answer.get("summary") or answer.get("reason") or "done")


def retry_now(db_url: str, schema: str, deps: Deps | None = None, *, wait: bool = False) -> dict[str, Any]:
    """``POST /api/deal-flow/triage_retry`` (the old route): the run in a background thread, holding the lock.

    H-360: the lock is taken FIRST and an interrupted run recovered BEFORE the queue is tested, synchronously, so the
    busy and empty answers stay the old synchronous ones and an interrupted run is never left open behind "nothing
    is waiting"."""
    deps = deps or Deps()
    with transaction(db_url) as conn:  # decision (i): before the import, refused at once (IntakeClosedError)
        intake_pg.ensure_intake_open(conn, schema)
    try:
        held = records.take_lock(db_url, schema)
    except records.TriageBusy:
        return {"started": False, "reason": BUSY_ROUTE}
    try:
        recover(db_url, schema, deps)
        with snapshot_transaction(db_url) as conn:
            st = load_state(conn, schema)
        due = bool(retry_due(st, _naive(deps), force=True))
    except BaseException:
        records.release_lock(held, schema)
        raise
    if not due:
        records.release_lock(held, schema)
        return {"started": False, "reason": NOTHING_ROUTE}

    def body() -> None:
        try:
            _retry_work(db_url, schema, deps, True)
        except Exception:
            log.exception("Retry now failed")
        finally:
            records.release_lock(held, schema)

    thread = threading.Thread(target=body, daemon=True, name="pz-triage-retry")
    thread.start()
    if wait:
        thread.join()
    return {"started": True}


# ------------------------------------------------------------------ the readers
def status(
    conn: psycopg.Connection[Any], schema: str, env: Mapping[str, str] | None = None, now: datetime | None = None
) -> dict[str, Any]:
    """``GET /api/deal-flow/triage_auto``: the old ``status()``."""
    st = load_state(conn, schema)
    rs = dict(st.rs)
    legacy_retryable(st, rs)
    waiting = [cid for cid, r in rs.items() if isinstance(r, dict) and r.get("category")]
    nxt = min((r["next_eligible"] for r in rs.values() if isinstance(r, dict) and r.get("next_eligible")), default=None)
    t = berlin_now(now).replace(tzinfo=None) if now is not None else datetime.now(BERLIN).replace(tzinfo=None)
    return {
        "running": records.lock_held(conn, schema),
        "last": _rules.plain(st.runs[-1]) if st.runs else None,
        "enabled": enabled(env if env is not None else os.environ, st.config),
        "retry": {"waiting": len(retry_due(st, t, force=True) if waiting else []), "next_try": nxt},
    }


def next_try(conn: psycopg.Connection[Any], schema: str) -> str | None:
    """System health's ``triage_next_try``: the old ``status()["retry"]["next_try"]``."""
    st = load_state(conn, schema)
    rs = dict(st.rs)
    legacy_retryable(st, rs)
    return min(
        (r["next_eligible"] for r in rs.values() if isinstance(r, dict) and r.get("next_eligible")), default=None
    )

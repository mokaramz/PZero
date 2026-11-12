"""The founder scan (``POST /api/radar_scan``): the old ``domain/founder_radar/scanning.py`` ``scan`` / ``_finish``
(rev 6c739b9), ported line for line in the three phases of ``events/scan.py`` (review 026b, plan §2):

1. ``scan_plan(inputs, sources_doc=, cursor_doc=)`` — pure, from the documents of the READ transaction: the rotating
   GitHub city batch (``next_batch`` over the regions and the cursor), the static sources (``load_sources``: never a
   GitHub city), deduplicated by id in that order; the previous health (``last_ok``, the regions) and the pipeline
   signals (``pz_data``).
2. ``scan_fetch(plan, fetch, now=, token=)`` — the network, NO transaction: each source through its collector and the
   injected ``fetching.Fetch``. One failing source never stops the others (the old ``except Exception``). A 403 / 429
   from the GitHub API (``fetching.is_rate_limit``) records the reset (``fetching.reset_text``) and every later GitHub
   source is "not attempted — rate limited", never contacted. The deadline (plan (a)): a network source that cannot
   start before ``fetch.deadline`` is "failed" with ``DEADLINE_NOTE`` (not counted as attempted, so the cursor does
   not skip it); one the deadline cuts off is "failed" with ``CUT_NOTE`` and its candidates are dropped.
   ``pz_data`` and the optional sources need no network and always run.
3. ``scan_apply(current, result, cursor_doc=, now=)`` — pure, on the CURRENT documents re-read in the WRITE
   transaction: each fetched source's candidates are ingested in scan order (``ingestion.ingest`` with the
   deterministic ids of review 026a and the current reserved ids), then the old ``_finish``: totals, the new cursor
   (``radar_cursor.json``), the region health (computed with the NEW cursor, as the old one re-read it), the new
   ``radar_health.json`` and the metrics (``radar_metrics.json``).

``scan(...)`` runs the three on one set of inputs (tests, parity).

What the store writes (``ScanOutcome``), in one transaction: ``outcome.people`` (None: no person changed; else the
whole live list, ``outcome.people_changed`` the new / changed ids in list order) through the Network write model;
``cursor`` and ``health`` ALWAYS (decision e: the attempt is recorded even when nothing new was found);
``outcome.metrics`` when it differs from the stored body. ``outcome.body`` is the answer (the new health document).

Changes (each a plan decision): the clock (decision f: every stamp is ``now``, the Berlin request clock; the old one
called ``datetime.now()`` at each step); the deadline; the GitHub hint names ``PZ_GITHUB_TOKEN`` (decision b; the
old text named ``config.json``); a missing radar_sources / radar_regions document reads as the defaults and is never
written (review 026a decision a; the old ``load_sources`` / ``load_regions`` wrote them). The durations
(``seconds``) come from ``clock`` (``time.monotonic``)."""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from projectzero.ecosystems.coverage import radar_health
from projectzero.founder_radar import collectors, fetching
from projectzero.founder_radar.catalog import NETWORK_STATES
from projectzero.founder_radar.clock import Clock
from projectzero.founder_radar.ingestion import ingest
from projectzero.founder_radar.metrics import append_history, metrics_snapshot
from projectzero.founder_radar.routes import Inputs, Outcome
from projectzero.founder_radar.sources import city_sources, load_cursor, load_sources, next_batch, region_health
from projectzero.network.view import records as _records

SCAN_DEADLINE_S = 120.0  # plan (a): the whole scan, wall clock
TOKEN_HINT = " — GitHub rate limit or blocked: an optional PZ_GITHUB_TOKEN in .env raises the limit (never required)"
OLD_TOKEN_HINT = (
    " — GitHub rate limit or blocked: an optional github_token in config.json raises the limit (never required)"
)
DEADLINE_NOTE = "scan deadline reached — this source was not fetched"
CUT_NOTE = "scan deadline reached while this source was fetched — its results were not kept"
NETWORK_KINDS = ("github_users", "openalex_works")


@dataclass(frozen=True)
class ScanPlan:
    sources: list[dict[str, Any]]  # the scan order: the city batch, then the static sources (ids unique)
    batch: list[dict[str, Any]]
    start: int
    prev_health: dict[str, Any]
    signals: Any


@dataclass
class Fetched:
    src: dict[str, Any]
    row: dict[str, Any]
    cands: list[dict[str, Any]] | None = None  # None: nothing to ingest (failed, rate limited, configuration)
    skipped: list[str] = field(default_factory=list)  # pz_data: the placeholder founder values skipped


@dataclass(frozen=True)
class ScanResult:
    plan: ScanPlan
    fetched: list[Fetched]
    gh_blocked: str | None
    attempted_batch: int
    t0: float


@dataclass(frozen=True)
class ScanOutcome:
    outcome: Outcome  # body: the health document; people / people_changed; metrics (None: unchanged)
    cursor: dict[str, Any]  # radar_cursor.json, always written
    health: dict[str, Any]  # radar_health.json, always written


def _key(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


def _js(v: Any) -> Any:
    return json.loads(json.dumps(v, ensure_ascii=False, default=str))


def scan_plan(inputs: Inputs, *, sources_doc: Any, cursor_doc: Any) -> ScanPlan:
    batch, start = next_batch(inputs.regions, cursor_doc)
    static = [
        x for x in load_sources(sources_doc) if x.get("kind") != "github_users"
    ]  # region registry is the ONLY source of GitHub city searches
    prev_health = radar_health(inputs.health)
    seen = set()
    srcs = []
    for x in batch + static:  # no city / source id is called twice in one scan
        if x["id"] in seen:
            continue
        seen.add(x["id"])
        srcs.append(x)
    return ScanPlan(
        copy.deepcopy(srcs), copy.deepcopy(batch), start, copy.deepcopy(prev_health), copy.deepcopy(inputs.signals)
    )


def scan_fetch(
    plan: ScanPlan,
    fetch: fetching.Fetch,
    *,
    now: datetime,
    today: date | None = None,
    token: str | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ScanResult:
    ck = Clock.at(now, today)
    prev = {s.get("id"): s for s in plan.prev_health.get("sources", [])}
    out: list[Fetched] = []
    t0 = clock()
    gh_blocked = None
    attempted_batch = 0
    for src in plan.sources:
        row = {
            "id": src["id"],
            "name": src["name"],
            "kind": src.get("kind"),
            "url": src.get("url", ""),
            "region": src.get("region", ""),
            "city": src.get("city", ""),
            "status": "",
            "note": "",
            "raw": 0,
            "new": 0,
            "merged": 0,
            "last_ok": (prev.get(src["id"]) or {}).get("last_ok", ""),
            "attempted_at": ck.minute(),
            "seconds": 0,
        }
        f = Fetched(src, row)
        out.append(f)
        if src.get("kind") == "github_users" and gh_blocked:
            row.update({"status": "not attempted — rate limited", "note": gh_blocked, "attempted_at": ""})
            continue
        if src.get("kind") in NETWORK_KINDS and fetch.expired():
            row["status"], row["note"] = "failed", DEADLINE_NOTE
            continue
        if src.get("kind") == "github_users":
            attempted_batch += 1
        st = clock()
        try:
            if src.get("kind") == "optional":
                row["status"], row["note"] = "config_required", src.get("requires_config", "Requires configuration.")
            else:
                if src["kind"] == "github_users":
                    cands = collectors.collect_github(src, fetch, now=ck.now, today=ck.today, token=token)
                elif src["kind"] == "openalex_works":
                    cands = collectors.collect_openalex(src, fetch, now=ck.now, today=ck.today)
                else:
                    cands, f.skipped = collectors.collect_pz_data(src, plan.signals, now=ck.now)
                if src["kind"] == "github_users":
                    cands = [dict(c, region=src.get("region", "")) for c in cands]
                f.cands = cands
        except fetching.DeadlineReached:
            row["status"], row["note"] = "failed", CUT_NOTE
        except Exception as e:
            msg = str(e)[:140]
            limited = src["kind"] == "github_users" and fetching.is_rate_limit(e)
            row["status"] = "failed"
            row["note"] = (f"{type(e).__name__}: {msg}") + (TOKEN_HINT if limited else "")
            if limited:
                reset_txt = fetching.reset_text(getattr(e, "headers", None))
                gh_blocked = f"GitHub rate limit hit — remaining cities not attempted this scan (reset: {reset_txt})"
        row["seconds"] = round(clock() - st, 1)
    return ScanResult(plan, out, gh_blocked, attempted_batch, t0)


def scan_apply(
    current: Inputs,
    result: ScanResult,
    *,
    cursor_doc: Any,
    now: datetime,
    today: date | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ScanOutcome:
    """Onto the CURRENT people and documents (re-read in the write transaction). ``current`` is never changed."""
    ck = Clock.at(now, today)
    people = current.people
    totals = {"raw": 0, "new": 0, "merged": 0, "resolved": 0, "unresolved": 0}
    rows = []
    for f in result.fetched:
        row = copy.deepcopy(f.row)
        rows.append(row)
        if f.cands is None:
            continue
        cands = f.cands
        r = ingest(people, cands, ck=ck, reserved_ids=current.reserved_ids)
        people = r.people
        row.update(
            {
                "status": "ok",
                "raw": len(cands),
                "new": r.result["new"],
                "merged": r.result["merged"],
                "last_ok": ck.minute(),
            }
        )
        if f.src["kind"] == "pz_data" and f.skipped:
            skipped = f.skipped
            row["note"] = (
                f"{len(skipped)} placeholder/aggregate founder value(s) skipped, e.g. {'; '.join(sorted(set(skipped))[:2])}"  # noqa: E501
            )
        for k in ("raw", "new", "merged", "resolved", "unresolved"):
            totals[k] += len(cands) if k == "raw" else r.result[k]
        if not cands:
            row["note"] = "retrieved, no people matched the bounded query"
    return _finish(current, people, rows, totals, result, cursor_doc, ck, clock)


def _finish(
    current: Inputs,
    people: list[Any],
    rows: list[dict[str, Any]],
    totals: dict[str, Any],
    result: ScanResult,
    cursor_doc: Any,
    ck: Clock,
    clock: Callable[[], float],
) -> ScanOutcome:
    P = people
    plan = result.plan
    batch, start, attempted_batch, gh_blocked = plan.batch, plan.start, result.attempted_batch, result.gh_blocked
    totals.update(
        {
            "attempted": len(rows),
            "ok": sum(1 for r in rows if r["status"] == "ok"),
            "failed": sum(1 for r in rows if r["status"] == "failed"),
            "config_required": sum(1 for r in rows if r["status"] == "config_required"),
            "identities_resolved": sum(
                1 for p in P if p.get("identity_status") in ("resolved", "verified by operator")
            ),
            "identities_unresolved": sum(1 for p in P if p.get("identity_status") == "needs identity resolution"),
            "eligible_for_assessment": sum(1 for p in P if (p.get("signal") or {}).get("ordering") is not None),
            "watchlisted": sum(1 for p in P if p.get("radar_state") == "watchlisted"),
            "promoted_to_network": sum(
                1 for p in P if p.get("radar_state") in NETWORK_STATES and p.get("provenance") == "radar_detected"
            ),
            "seconds": round(clock() - result.t0, 1),
        }
    )
    cur = load_cursor(cursor_doc)
    ncs = len(city_sources(current.regions))
    cursor = {
        "next": (start + attempted_batch) % ncs if ncs else 0,
        "batches_completed": cur.get("batches_completed", 0) + 1,
        "last": ck.minute(),
        "rate_limited": bool(gh_blocked),
        "note": gh_blocked or "",
    }
    regions = region_health({r["id"]: r for r in rows}, plan.prev_health.get("regions", []), current.regions, cursor)
    totals["cities_in_registry"] = ncs
    totals["cities_attempted"] = attempted_batch
    totals["cities_rate_limited"] = sum(1 for r in rows if r["status"] == "not attempted — rate limited")
    totals["regions_touched"] = sum(1 for r in regions if r["attempted"])
    health = {
        "scan_time": ck.minute(),
        "totals": totals,
        "sources": rows,
        "regions": regions,
        "batch": {
            "size": len(batch),
            "cities": [b["city"] for b in batch],
            "cursor_next": (start + len(batch)) % ncs if ncs else 0,
            "registry_size": ncs,
        },
        "note": ""
        if totals["new"] or totals["merged"]
        else "No people were retrieved in this scan — the per-source reasons below say why.",
    }
    was = {_key(p.get("id")): _key(p) for p in _records(current.people)}
    changed = [p.get("id") for p in _records(P) if was.get(_key(p.get("id"))) != _key(p)]
    metrics = append_history(current.metrics, metrics_snapshot(P, ck.today))
    return ScanOutcome(
        Outcome(
            200,
            _js(health),
            people=P if changed else None,
            people_changed=changed,
            metrics=None if _key(metrics) == _key(current.metrics) else metrics,
        ),
        _js(cursor),
        _js(health),
    )


def scan(
    inputs: Inputs,
    *,
    sources_doc: Any,
    cursor_doc: Any,
    fetch: fetching.Fetch,
    now: datetime,
    today: date | None = None,
    token: str | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ScanOutcome:
    """The three phases on one set of inputs (no concurrent change possible: tests and parity)."""
    plan = scan_plan(inputs, sources_doc=sources_doc, cursor_doc=cursor_doc)
    result = scan_fetch(plan, fetch, now=now, today=today, token=token, clock=clock)
    return scan_apply(inputs, result, cursor_doc=cursor_doc, now=now, today=today, clock=clock)

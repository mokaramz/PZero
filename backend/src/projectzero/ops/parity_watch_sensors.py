# ruff: noqa: E501
# (the invented world: one record per line)
"""WATCH sensors parity (review 037b): the NEW checks (``watch.run``), page saves and the news bridge against the OLD
``watch.run_checks(only)`` / ``set_target`` / ``news._watch_bridge`` as oracle, over the SAME invented world, script
and RECORDED BYTES (every page served from the step's bytes on both sides), at a FIXED clock. No model call, no network.

    python -m projectzero.ops.parity_watch_sensors goldens   # (re)generates golden_v1/oracle_watch_sensors.json
    python -m projectzero.ops.parity_watch_sensors check     # the pure parts against the stored golden (no database)
    python -m projectzero.ops.parity_watch_sensors hosted    # the whole new side in a throw-away pz_itest_* schema
    python -m projectzero.ops.parity_watch_sensors real      # PZ_LEGACY_DATA (read only) through a pz_rehearse_* import

The world (``world_docs``): three WATCH candidates (one pre-funding with four ``also_seen`` provenances: an
announcement, a grant, another programme, and two that do not count: an older one and one without a source id; one
already funded; one whose target is INACTIVE), a manual active target whose page has an ARCHIVED baseline
(``.watch/wt-<id>.json``), an inactive manual target with no candidate (not watched), and an archived trigger log with
malformed lines, a status line and one trigger whose dedupe key a later page line would make (the archived key blocks
the re-fire). The script (``script``): "Check now" on ONE company (the re-hits of ALL companies fire: decision e), a
full check (baselines; the archived baseline compared), unchanged pages and a failing page, the failure again (2 in a
row), a pilot line (high value: the deferred case refresh), a reflow that does not refire, the failing page recovering
with a material change (fires once; the streak resets, ``last_error`` kept), a page removed by a save, the news
bridge (a funding story of a pre-funding company: ``first_institutional_round``; a hire; a NOISE story and an
unwatched company's: nothing; only the first source) twice (fires once), and a last full check.

``check``: per step, over the OLD state before the step (no database): the new pure run (``watch.run``'s re-hits,
traversal, ``check_one`` and ``recorded``; ``bridge_lines``; ``writes.parse_target`` / ``merged``), compared with the
old answer, log, targets, snapshots, case-refresh calls and view. ``hosted``: the world through the PRODUCTION importer
into a scratch schema, then the same script through the routes (``POST /api/watch_check`` with the step's bytes behind
the fixture transport and resolver; ``POST /api/watch_target``; the bridge through ``watch.run.news_bridge`` in one
transaction, the function the news run calls in its own), the clock frozen per step; compared after each step: the
answer (with its status code), the log lines (archive + rows), the effective targets, the snapshots (rows over the
archive), the view (``GET /api/watch``) and Health's ``failing_checks``. Only ``watch_targets``, ``watch_events``,
``watch_page_snapshots`` and ``watch_check_state`` may change.

Declared differences, ALL applied by ``normalise`` (the ONE place):

* **(d) the budget:** the answer gains ``skipped`` (0 here: every page fits) and, as the job's note, " · N page(s)
  left for the next run" only when N > 0 (the hosted tests cover the deadline and the resume point);
* **(f) the case refresh:** the old high-value trigger called ``case_prep.on_watch_trigger``; the new cut makes the
  SAME call into a seam (compared by ``check``) and nothing runs or is recorded (``hosted`` has nothing to compare);
* **(H-391) a duplicate URL is visited once:** the old ``run_checks`` checked a URL listed twice in a company's stored
  list twice (the second visit saw an unchanged page); the new traversal visits each (company, URL) pair once, at
  its first position (``watch.run.traversal``), so the resume point cannot strand a later page. ``normalise`` drops
  the old answer's repeated page rows (refusing one that fired) and ``fetched_once`` its repeated fetches (the page's
  check record then holds the first visit's state, not the repeat's ``unchanged``). The script's world lists no
  duplicate (``tests/watch`` and the hosted tests pin the collapse);
* **errors:** the old answers carried no status code; every new answer is a 200 here;
* **(not reached by the script)** (a) one check at a time, (c) a private host / the TLS rule, the eligibility
  re-check and the crash between fetch and commit: the hosted tests (``tests/hosted/test_watch_checks_hosted.py``).

The world holds INVENTED names only. Exit 1 on any difference.
"""

from __future__ import annotations

import base64
import copy
import functools
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from projectzero.core import net
from projectzero.core.paths import REPO_ROOT
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js
from projectzero.ops.parity_watch_store import _prop, compare, key_order
from projectzero.ops.scratch_import import files_of
from projectzero.watch import log as watch_log
from projectzero.watch import run as watch_run
from projectzero.watch import sensors, writes
from projectzero.watch import targets as watch_targets
from projectzero.watch import view as watch_view

ORACLE = REPO_ROOT / "scripts" / "oracle" / "watch_sensors_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_watch_sensors.json"
CLOCK0 = datetime(2026, 11, 13, 12, 0, 0)
FIXTURE_IP = "93.184.216.34"  # every fixture host resolves here (a public address; nothing is ever sent to it)
WATCH_TABLES = frozenset({"watch_targets", "watch_events", "watch_page_snapshots", "watch_check_state"})
__all__ = ["PageTransport", "compare", "key_order"]

COR, COR_JOBS = "https://corvane.invented.example/news", "https://corvane.invented.example/careers"
DUN = "https://dunmore.invented.example/press"
ELS = "https://elstree.invented.example/"
GAR = "https://garrow.invented.example/news"
FAL = "https://fallow.invented.example/"
GAR_PILOT = "Garrow Marine starts a pilot with an invented harbour authority"


# ------------------------------------------------------------------ the world (invented names only)
def _c(cid: str, name: str, **extra: Any) -> dict[str, Any]:
    base = {"id": cid, "name": name, "description": f"{name} builds invented things.", "source": "Invented Feed",
            "source_id": "fx-feed", "discovery_tier": "pre_company", "decision": "watch", "notes": "", "geo": ["DE"],
            "sectors": ["ai_sw"], "first_seen": "2026-09-01 10:00:00", "source_date": "2026-08-30",
            "location": "Berlin, Germany", "country": "DE", "source_url": f"https://feed.invented.example/news/{cid}"}  # fmt: skip
    return base | extra


def world_candidates() -> list[dict[str, Any]]:
    also = [
        {"source_id": "fx-press", "source": "Invented Press", "discovery_tier": "announcement", "first_seen": "2026-10-05 08:00:00",
         "url": "https://press.invented.example/corvane", "source_date": "2026-10-04"},
        {"source_id": "fx-grants", "source": "Invented Grant Desk", "discovery_tier": "grant", "first_seen": "2026-10-06 08:00:00",
         "url": "https://grants.invented.example/corvane", "source_date": "2026-10-06T09:00:00"},
        {"source_id": "fx-prog", "source": "", "discovery_tier": "programme", "first_seen": "2026-10-07 08:00:00", "url": ""},
        {"source_id": "fx-old", "source": "Invented Old List", "discovery_tier": "announcement", "first_seen": "2026-08-01 08:00:00",
         "url": "https://old.invented.example/corvane"},
        {"source": "Invented Anonymous", "discovery_tier": "grant", "first_seen": "2026-10-08 08:00:00"},
    ]  # fmt: skip
    return [
        _c("wsn-cor", "Corvane Robotics GmbH", also_seen=also),
        _c("wsn-dun", "Dunmore Sensors"),
        _c("wsn-els", "Elstree Analytics"),
        _c("wsn-hal", "Halbrook Thermal", decision="new"),
    ]


def world_proposals() -> dict[str, dict[str, Any]]:
    by = {c["id"]: c for c in world_candidates()}
    out = {
        "wsn-cor": _prop(by["wsn-cor"], "WATCH", "2026-10-20T08:00:00"),
        "wsn-dun": _prop(by["wsn-dun"], "WATCH", "2026-11-20T08:00:00"),
    }
    out["wsn-dun"]["capital_stage"] = "ALREADY_INSTITUTIONALLY_FUNDED"  # funding stays funding
    return out


def _check(state: str, at: str, failures: int = 0, error: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {"last_checked": at, "last_state": state}
    if not failures:
        out["last_ok"] = at
    out["failures_in_row"] = failures
    if error:
        out["last_error"] = error
    return out


def world_targets() -> dict[str, Any]:
    return {"version": 1, "targets": {
        "corvane robotics": {"name": "Corvane Robotics GmbH", "added_at": "2026-10-02T09:00:00", "checks": {},
                             "urls": [COR, COR_JOBS], "candidate_id": "wsn-cor", "active": True, "updated_at": "2026-10-02T09:00:00"},
        "dunmore sensors": {"name": "Dunmore Sensors", "added_at": "2026-10-03T09:00:00",
                            "checks": {DUN: _check("unchanged", "2026-11-12T07:00:00")}, "urls": [DUN],
                            "candidate_id": "wsn-dun", "active": True, "updated_at": "2026-10-03T09:00:00"},
        "elstree analytics": {"name": "Elstree Analytics", "added_at": "2026-10-04T09:00:00", "checks": {}, "urls": [ELS],
                              "candidate_id": "wsn-els", "active": False, "updated_at": "2026-10-05T09:00:00"},
        "garrow marine": {"name": "Garrow Marine", "added_at": "2026-10-06T09:00:00",
                          "checks": {GAR: _check("unchanged", "2026-11-01T07:00:00")}, "urls": [GAR],
                          "candidate_id": "", "active": True, "updated_at": "2026-10-06T09:00:00"},
        "fallow instruments": {"name": "Fallow Instruments", "added_at": "2026-10-07T09:00:00", "checks": {},
                               "urls": [FAL], "candidate_id": "", "active": False, "updated_at": "2026-10-07T09:00:00"},
    }}  # fmt: skip


def page(*lines: str, tag: str = "p") -> str:
    body = "".join(f"<{tag}>{x}</{tag}>" for x in lines)
    return f"<html><head><title>Invented</title><script>var x = 1;</script></head><body><nav>Menu items here</nav>{body}<footer>Imprint and privacy</footer></body></html>"


COR_BASE = ["Corvane Robotics news", "Corvane Robotics builds inspection robots for invented substations.",
            "Our team of 6 engineers in Leipzig.", "Posted 10:30 · 3 days ago"]  # fmt: skip
COR_PILOT = "Corvane Robotics starts a pilot with an invented grid operator on 12 substations"
DUN_BASE = [
    "Dunmore Sensors press",
    "Dunmore Sensors makes invented humidity probes.",
    "Press contact: an invented office",
]
GAR_ARCHIVED = ["Garrow Marine news", "Garrow Marine builds invented hull sensors."]
GAR_NOW = [*GAR_ARCHIVED, GAR_PILOT, "We're hiring: invented marine engineers"]
ELS_BASE = ["Elstree Analytics", "Elstree Analytics models invented supply chains."]
# the careers page as RECORDED BYTES (latin-1 bytes in a page the old fetch decoded as UTF-8 with replacement)
COR_JOBS_RAW = base64.b64encode(
    page("Careers at Corvane", "Join our team in Leipzig").encode("utf-8") + b"<p>Gr\xfc\xdfe aus Leipzig</p>"
).decode("ascii")


def archived_snapshots() -> dict[str, Any]:
    return {".watch/" + watch_run.snapshot_name("garrow marine", GAR): GAR_ARCHIVED}


def _jl(row: Mapping[str, Any]) -> str:
    return json.dumps(dict(row), ensure_ascii=False, sort_keys=True)


def archived_log() -> str:
    """Malformed lines, a status line and ONE trigger whose dedupe key Garrow's pilot line would make: the archived key
    blocks the re-fire (037a's note)."""
    key = "garrow marine"
    dedupe = sensors._sha(key, GAR, "pilot", sensors._norm(GAR_PILOT))
    blocked = {"id": "wt-" + dedupe[:12], "kind": "trigger", "entity_key": key, "name": "Garrow Marine", "candidate_id": "",
               "predicate": "pilot", "label": "Pilot", "high_value": True, "source": GAR, "source_kind": "page_check",
               "url": GAR, "source_date": "", "first_observed": "2026-10-20T07:00:00", "evidence": GAR_PILOT,
               "dedupe_key": dedupe}  # fmt: skip
    lines = [
        _jl(blocked),
        "not json",
        "[1, 2]",
        _jl(
            {
                "kind": "status",
                "trigger_id": blocked["id"],
                "status": "reviewed",
                "at": "2026-10-21T08:00:00",
                "note": "",
            }
        ),
        _jl({"id": "wt-legacy000002", "kind": "trigger", "name": "Dunmore Sensors", "predicate": "launch"}),
    ]
    return "\n".join(lines) + "\n"


def world_docs() -> dict[str, Any]:
    return {
        "inbox.json": {"candidates": world_candidates(), "last_run": "2026-10-20 08:00:00", "reprocess_v": 3},
        "triage_proposals.json": {"version": 1, "proposals": world_proposals()},
        "watch/targets.json": world_targets(),
        "watch/triggers.jsonl": archived_log(),
        **archived_snapshots(),
    }


def _pages(cor: list[str], dun: Any, *, cor_tag: str = "p", gar: list[str] = GAR_NOW) -> dict[str, Any]:
    return {COR: {"body": page(*cor, tag=cor_tag)}, COR_JOBS: {"raw_b64": COR_JOBS_RAW},
            DUN: dun if isinstance(dun, dict) else {"body": page(*dun)},
            ELS: {"body": page(*ELS_BASE)}, GAR: {"body": page(*gar)}}  # fmt: skip


def news_events() -> dict[str, Any]:
    def ev(eid: str, key: str, company: str, headline: str, etype: str, mat: str, urls: list[str]) -> dict[str, Any]:
        return {"event_id": eid, "entity_key": key, "company": company, "headline": headline, "event_type": etype,
                "event_date": "2026-11-11", "materiality": mat,
                "sources": [{"publisher": f"Invented Wire {i}", "url": u} for i, u in enumerate(urls)]}  # fmt: skip

    return {
        "nw-1": ev("nw-1", "corvane robotics", "Corvane Robotics GmbH", "Corvane Robotics raises an invented seed round", "funding", "MEDIUM",
                   ["https://wire.invented.example/corvane-seed", "https://wire2.invented.example/corvane-seed"]),
        "nw-2": ev("nw-2", "dunmore sensors", "Dunmore Sensors", "Top 10 sensor makers to watch", "other", "NOISE", ["https://wire.invented.example/top10"]),
        "nw-3": ev("nw-3", "dunmore sensors", "Dunmore Sensors", "Dunmore Sensors appoints an invented CTO", "hire", "LOW", ["https://wire.invented.example/dunmore-cto"]),
        "nw-4": ev("nw-4", "invented unwatched", "Invented Unwatched", "Invented Unwatched raises money", "funding", "HIGH", ["https://wire.invented.example/unwatched"]),
        "nw-5": ev("nw-5", "", "", "An invented market story", "other", "LOW", ["https://wire.invented.example/market"]),
    }  # fmt: skip


def script() -> list[dict[str, Any]]:
    material = [f"Completely new invented section number {i} about our approach" for i in range(8)]
    reflowed = [*COR_BASE, "Corvane   Robotics starts a pilot with an invented grid operator on 12 substations"]
    ops: list[dict[str, Any]] = [
        {"op": "check", "only": "Dunmore Sensors", "pages": _pages(COR_BASE, DUN_BASE)},
        {"op": "check", "pages": _pages(COR_BASE, DUN_BASE)},
        {"op": "check", "pages": _pages(COR_BASE, {"error": "invented connection reset"})},
        {"op": "check", "pages": _pages([*COR_BASE, COR_PILOT], {"error": "invented connection reset"})},
        {"op": "check", "pages": _pages(reflowed, DUN_BASE + material, cor_tag="div")},
        {"op": "target", "body": {"name": "Corvane Robotics GmbH", "urls": [COR], "candidate_id": "wsn-cor"}},
        {"op": "check", "pages": _pages([*COR_BASE, COR_PILOT], DUN_BASE + material)},
        {"op": "bridge", "events": news_events()},
        {"op": "bridge", "events": news_events()},
        {"op": "check", "only": "Elstree Analytics", "pages": _pages([*COR_BASE, COR_PILOT], DUN_BASE + material)},
    ]
    return [{"clock": CLOCK0.replace(minute=i).isoformat(), **op} for i, op in enumerate(ops)]


def world_input() -> dict[str, Any]:
    return {"docs": world_docs(), "steps": script()}


# ------------------------------------------------------------------ the oracle
def oracle(inp: Mapping[str, Any]) -> dict[str, Any]:
    return oracle_files(files_of(dict(inp["docs"])), inp["steps"])


def oracle_files(files: Mapping[str, bytes], steps: list[Any]) -> dict[str, Any]:
    """The oracle over raw files (the invented world's, or a byte-exact copy of the real snapshot) in a scratch folder."""
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-watch-sensors-oracle-") as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        for rel, raw in files.items():
            target = (data / rel).resolve()
            if data.resolve() not in target.parents:
                raise SystemExit(f"refusing a path outside the scratch folder: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        srcf, dst = Path(tmp) / "in.json", Path(tmp) / "out.json"
        srcf.write_bytes(json.dumps({"steps": steps}, ensure_ascii=False).encode("utf-8"))
        env = {k: v for k, v in os.environ.items() if k != "SUPABASE_DB_URL" and not k.endswith(("_API_KEY", "_TOKEN"))}
        env.update({"PZ_DATA": str(data), "PZ_TESTING": "1", "PYTHONPATH": str(OLD_REPO / "backend" / "src")})
        res = subprocess.run([str(python), str(ORACLE), str(srcf), str(dst)], env=env, capture_output=True, text=True)
        if res.returncode != 0:
            raise SystemExit(f"oracle failed:\n{res.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_bytes().decode("utf-8"))
        return out


# ------------------------------------------------------------------ the fixture network
class PageTransport:
    """Answers each page from the step's RECORDED bytes (``{"body"}``, ``{"raw_b64"}``, ``{"error"}``: an ``OSError``,
    ``{"status"}``, ``{"slow": seconds}``: the body after ``seconds``, cut at the fetch's deadline) and records every
    request (URL, headers, address). ``pause``: URL -> (entered, release) events: the send signals ``entered`` and
    waits for ``release`` (a check paused mid-fetch)."""

    def __init__(self, responses: Mapping[str, Any] | None = None) -> None:
        self.responses: dict[str, Any] = dict(responses or {})
        self.asked: list[dict[str, Any]] = []
        self.pause: dict[str, tuple[threading.Event, threading.Event]] = {}

    def send(self, target: net.Target, method: str, headers: Mapping[str, str], body: bytes | None, timeout: float,
             max_bytes: int, deadline: float | None = None, *, truncate: bool = False) -> net.Response:  # fmt: skip
        default = 443 if target.scheme == "https" else 80
        url = f"{target.scheme}://{target.host}{'' if target.port == default else f':{target.port}'}{target.path}"
        self.asked.append({"url": url, "headers": dict(headers), "ip": target.ip, "timeout": timeout,
                           "max_bytes": max_bytes, "deadline": deadline})  # fmt: skip
        if url in self.pause:
            entered, release = self.pause[url]
            entered.set()
            release.wait(30)
        spec = self.responses.get(url) or {"status": 404}
        if "slow" in spec:
            left = None if deadline is None else deadline - time.monotonic()
            wait = float(spec["slow"]) if left is None else min(float(spec["slow"]), max(0.0, left))
            time.sleep(wait)
            if deadline is not None and time.monotonic() >= deadline:
                raise net.FetchError("source deadline reached")
        if "error" in spec:
            raise OSError(spec["error"])
        raw = spec.get("raw_b64")
        data = base64.b64decode(raw) if raw is not None else str(spec.get("body", "")).encode("utf-8")
        return net.Response(url, int(spec.get("status", 200)), {}, data)


def fixture_resolver(host: str) -> list[str]:
    return [FIXTURE_IP]


class RefusingTransport:
    """The real snapshot's transport: every URL is refused (nothing is ever sent)."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def send(self, target: net.Target, method: str, headers: Mapping[str, str], body: bytes | None, timeout: float,
             max_bytes: int, deadline: float | None = None, *, truncate: bool = False) -> net.Response:  # fmt: skip
        self.asked.append(target.host)
        raise OSError("refused by the fixture transport")


# ------------------------------------------------------------------ the declared differences (ONE place)
def normalise(step: Mapping[str, Any]) -> dict[str, Any]:
    """The old step -> the expected new one: the answer with its status code (and (d)'s ``skipped``: 0), the log
    lines, the targets, the snapshots, the view."""
    s = copy.deepcopy(dict(step))
    answer: Any = s["answer"]
    if s["op"] == "check":
        seen: set[tuple[str, str]] = set()
        pages = []
        for p in answer["pages"]:  # (H-391): a repeated (company, URL) is visited once
            if (p["entity"], p["url"]) in seen:
                if p["fired"]:
                    raise ValueError(f"a repeated visit of {p['url']} fired: the collapse would lose a trigger")
                continue
            seen.add((p["entity"], p["url"]))
            pages.append(p)
        answer = {"status": 200, **answer, "pages": pages, "skipped": 0}  # (d)
    elif s["op"] == "target":
        answer = {"status": 400, "ok": False, **answer} if "error" in answer else {"status": 200, **answer}
    return {
        "answer": answer,
        "log": str(s["log"]).splitlines(),
        "targets": watch_targets.targets_of(s["targets"]),
        "snapshots": dict(sorted(s["snapshots"].items())),  # a folder listing: no order
        "view": s["view"],
    }


def fetched_once(urls: list[str]) -> list[str]:
    """(H-391) the old fetches with a repeated URL dropped (the script's companies share no URL)."""
    return list(dict.fromkeys(urls))


def failing_of(view: Mapping[str, Any]) -> int:
    """The old Health count over the old ``view()`` (``services/health.py:380-385``)."""
    return sum(
        1 for co in view["companies"] for chk in co["checks"].values() if int(chk.get("failures_in_row") or 0) >= 2
    )


# ------------------------------------------------------------------ check: the pure parts
def _served(spec: Mapping[str, Any] | None, url: str) -> Any:
    """The page as the run hands it to ``check_page``: the decoded bytes, or the exception the fetch raised."""
    if spec is None:
        return KeyError(url)
    if "error" in spec:
        return OSError(spec["error"])
    if "raw_b64" in spec:
        return base64.b64decode(spec["raw_b64"]).decode("utf-8", errors="replace")
    return str(spec["body"])


def pure_step(before: Mapping[str, Any], step: Mapping[str, Any]) -> dict[str, Any]:
    """The new pure run and its effect over the old state before the step."""
    clock = datetime.fromisoformat(step["clock"])
    ts, today = watch_run.ts_of(clock), clock.date()
    log_lines = str(before["log"]).splitlines()
    targets = copy.deepcopy(watch_targets.targets_of(before["targets"]))
    snapshots = copy.deepcopy(dict(before["snapshots"]))
    candidates, proposals = world_candidates(), world_proposals()
    refresh: list[Any] = []
    answer: Any = None
    if step["op"] == "check":
        watched = watch_targets.watched(copy.deepcopy(candidates), targets)
        fired = writes.keys_of(watch_log.parse_text(str(before["log"])))
        rehits = []
        for key, w in watched.items():
            r = watch_run.rehits_of(key, w, fired=fired, proposals=proposals, ts=ts, today=today)
            rehits += r.rows
            log_lines += r.lines
            refresh += r.case_refresh
        pages, failures = [], 0
        for key, url in watch_run.traversal(watched, targets, step.get("only") or None):
            name = watch_run.snapshot_name(key, url)
            o = watch_run.check_one(key, watched[key], url, _served(step["pages"].get(url), url),
                                    baselines={name: snapshots[name]} if name in snapshots else {}, fired=fired,
                                    proposals=proposals, ts=ts, today=today)  # fmt: skip
            snapshots.update(o.saved)
            log_lines += o.lines
            refresh += o.case_refresh
            targets[key] = watch_run.recorded(targets[key], url, o.res["state"], o.ok, o.err, ts)
            pages.append({"entity": watched[key]["name"], **o.res, "error": o.err})
            failures += 0 if o.ok else 1
        answer = {"status": 200, "fired": len(rehits) + sum(len(p["fired"]) for p in pages), "pages": pages,
                  "failures": failures, "skipped": 0}  # fmt: skip
    elif step["op"] == "target":
        try:
            req = writes.parse_target(step["body"])
            record = writes.merged(targets.get(req.key), req, ts)
            targets = watch_targets.overlay(targets, [(req.key, record)])
            answer = {"status": 200, "ok": True, "target": record}
        except writes.WatchError as exc:
            answer = {"status": 400, "ok": False, "error": str(exc)}
    elif step["op"] == "bridge":
        watched = watch_targets.watched(copy.deepcopy(candidates), targets)
        fired = writes.keys_of(watch_log.parse_text(str(before["log"])))
        ctx = sensors.Context(ts=ts, today=today, watched=watched, fired=fired, proposals=proposals,
                              news_events=copy.deepcopy(step["events"]))  # fmt: skip
        with sensors.context(ctx):
            n = sensors._watch_bridge()
        log_lines += ctx.lines
        refresh += ctx.case_refresh
        answer = {"watch_triggers": n}
    watched = watch_targets.watched(copy.deepcopy(candidates), targets)
    view = watch_view.build(watched, targets, proposals, watch_log.parse_text("\n".join(log_lines) + "\n"))
    return {"answer": answer, "log": log_lines, "targets": targets, "snapshots": dict(sorted(snapshots.items())), "view": js(view),
            "case_refresh": refresh}  # fmt: skip


def initial_state() -> dict[str, Any]:
    docs = world_docs()
    return {"log": docs["watch/triggers.jsonl"], "targets": docs["watch/targets.json"],
            "snapshots": {k.removeprefix(".watch/"): v for k, v in archived_snapshots().items()}}  # fmt: skip


def compare_pure(golden: Mapping[str, Any]) -> list[str]:
    inp, exp = golden["input"], golden["expected"]
    problems: list[str] = []
    before: Mapping[str, Any] = initial_state()
    for i, (step, old) in enumerate(zip(inp["steps"], exp["steps"], strict=True)):
        got = pure_step(before, step)
        want = normalise(old)
        problems += compare(want, {k: v for k, v in got.items() if k != "case_refresh"}, f"/step{i}")
        problems += diff(
            js({"v": old["case_refresh"]}), js({"v": got["case_refresh"]}), f"/step{i}/case_refresh"
        )  # (f)
        if step["op"] == "check":
            urls = [u for _k, u in watch_run.traversal(
                watch_targets.watched(world_candidates(), watch_targets.targets_of(before["targets"])),
                watch_targets.targets_of(before["targets"]), step.get("only") or None)]  # fmt: skip
            if urls != fetched_once(old["fetched"]):
                problems.append(f"/step{i}/fetched: {urls} != {old['fetched']}")
        before = old
    return problems


# ------------------------------------------------------------------ hosted: the whole new side
def snapshots_of(conn: Any, schema: str) -> dict[str, Any]:
    """The baselines as the next check resolves them: each row over the archived ``.watch/wt-*.json``."""
    s = schema
    out = {str(r[0]).removeprefix(".watch/"): r[1] for r in conn.execute(
        f"select path, parsed from {s}.legacy_documents where path like '.watch/wt-%%' order by path".encode()).fetchall()}  # fmt: skip
    for sid, lines in conn.execute(f"select id, lines from {s}.watch_page_snapshots".encode()).fetchall():
        out[f"{sid}.json"] = lines
    return dict(sorted(out.items()))


def new_state(client: Any, conn: Any, schema: str, answer: Any) -> dict[str, Any]:
    return {
        "answer": answer,
        "log": watch_log.log_text(conn, schema).splitlines(),
        "targets": watch_targets.effective_targets(conn, schema),
        "snapshots": snapshots_of(conn, schema),
        "view": client.get("/api/watch").json(),
    }


def hosted_step(
    client: Any, app: Any, settings: Any, schema: str, step: Mapping[str, Any], transport: PageTransport
) -> Any:
    from projectzero.core.db import transaction
    from projectzero.network.view import BERLIN

    clock = datetime.fromisoformat(step["clock"]).replace(tzinfo=BERLIN)
    app.state.clock = functools.partial(lambda c: c, clock)
    if step["op"] == "check":
        transport.responses = dict(step["pages"])
        body = {"name": step["only"]} if step.get("only") else {}
        r = client.post("/api/watch_check", json=body)
        return {"status": r.status_code, **r.json()}
    if step["op"] == "target":
        r = client.post("/api/watch_target", json=step["body"])
        return {"status": r.status_code, **r.json()}
    with transaction(settings.db_url) as conn:  # the bridge, as the news run calls it in its own transaction
        return {"watch_triggers": watch_run.news_bridge(conn, schema, clock)(copy.deepcopy(step["events"]))}


def hosted(golden: Mapping[str, Any] | None = None) -> int:  # pragma: no cover - needs the hosted database
    from fastapi.testclient import TestClient

    from projectzero.api.app import create_app
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import transaction
    from projectzero.ops.parity_validation import _fingerprint
    from projectzero.ops.scratch_import import drop_schema, import_world

    load_dotenv()
    settings = Settings.from_env()
    golden = golden or json.loads(GOLDEN.read_text(encoding="utf-8"))
    inp, exp = golden["input"], golden["expected"]
    schema = import_world(settings.db_url, copy.deepcopy(inp["docs"]))
    problems: list[str] = []
    try:
        with transaction(settings.db_url) as conn:
            before_tables = _fingerprint(conn, schema)
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        transport = PageTransport()
        app.state.watch_transport, app.state.watch_resolver = transport, fixture_resolver
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            for i, (step, old) in enumerate(zip(inp["steps"], exp["steps"], strict=True)):
                transport.asked.clear()
                answer = hosted_step(client, app, settings, schema, step, transport)
                with transaction(settings.db_url) as conn:
                    new = new_state(client, conn, schema, answer)
                problems += compare(normalise(old), new, f"/step{i}")
                if step["op"] == "check":
                    asked = [q["url"] for q in transport.asked]
                    if asked != fetched_once(old["fetched"]):
                        problems.append(f"/step{i}/fetched: {asked} != {old['fetched']}")
                    if any(q["ip"] != FIXTURE_IP or q["headers"].get("Accept-Language") != "de,en;q=0.8" or q["timeout"] > 20
                           or q["max_bytes"] != net.MAX_BYTES or q["deadline"] is None for q in transport.asked):  # fmt: skip
                        problems.append(f"/step{i}/requests: not the old browser headers, timeout, cap and a deadline")
                health = client.get("/api/system_health").json()["watch"]["failing_checks"]
                if health != failing_of(old["view"]):
                    problems.append(f"/step{i}/health: failing_checks {health} != {failing_of(old['view'])}")
                print(json.dumps({"step": i, "op": step["op"], "fired": (answer or {}).get("fired", (answer or {}).get("watch_triggers")),
                                  "log_lines": len(new["log"]), "snapshots": len(new["snapshots"]), "failing_checks": health}, ensure_ascii=False))  # fmt: skip
        with transaction(settings.db_url) as conn:
            after_tables = _fingerprint(conn, schema)
        changed = sorted(
            k for k in set(before_tables) | set(after_tables) if before_tables.get(k) != after_tables.get(k)
        )
        if not set(changed) <= WATCH_TABLES:
            problems.append(f"/tables: unexpected tables changed {sorted(set(changed) - WATCH_TABLES)}")
    finally:
        drop_schema(settings.db_url, schema)
    for p in problems[:80]:
        print("  DIFF", p)
    print(
        "WATCH SENSORS HOSTED PARITY PASSED"
        if not problems
        else f"WATCH SENSORS HOSTED PARITY FAILED ({len(problems)})"
    )
    return 1 if problems else 0


# ------------------------------------------------------------------ the real snapshot
REAL_CLOCK = datetime(2026, 11, 13, 13, 0, 0)


def real() -> int:  # pragma: no cover - for the main session: needs the hosted database and the old repository
    """The plan's "Real snapshot" check: the real data folder (READ ONLY: captured once, bytes only) imported by the
    PRODUCTION importer into a throw-away ``pz_rehearse_*`` schema; then ONE full check through ``POST
    /api/watch_check`` with a fixture transport that REFUSES every URL, against the OLD ``run_checks()`` over a
    byte-exact scratch copy of the same bytes (its ``_get`` refusing too). Compared: the answer (the old watched set is
    the old inbox's, the new one every WATCH candidate: decision a, reported as counts), the log, the targets, the
    snapshots; then Health, Today and Conviction read back unchanged (the same clock before and after). Only
    ``watch_check_state`` may change (no page: no check record, no snapshot, no trigger). Aggregates only are printed
    (no name, no id; ids as ``<id>`` in diff paths)."""
    import secrets as _secrets

    from fastapi.testclient import TestClient

    from projectzero.api.app import create_app
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import connect, transaction
    from projectzero.network.view import BERLIN
    from projectzero.ops.db_check import _scratch_sql
    from projectzero.ops.legacy.apply import apply_plan
    from projectzero.ops.legacy.plan import build_plan
    from projectzero.ops.legacy.source import LegacySnapshot
    from projectzero.ops.parity_validation import _fingerprint
    from projectzero.ops.scratch_import import drop_schema

    load_dotenv()
    settings = Settings.from_env()
    snapshot = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))  # reads the bytes; never writes there
    files = {f.path: f.raw for f in snapshot.files()}
    schema = f"pz_rehearse_{_secrets.token_hex(4)}"
    problems: list[str] = []
    report: dict[str, Any] = {}
    admin = connect(settings.db_url, autocommit=True)
    try:
        admin.execute(_scratch_sql(schema).encode())
        conn = connect(settings.db_url)
        try:
            applied = apply_plan(build_plan(snapshot), schema=schema, conn=conn)
            assert applied.get("applied"), "the importer refused the snapshot"
        finally:
            conn.close()
        steps = [{"clock": REAL_CLOCK.isoformat(), "op": "check", "pages": {}}]
        out = oracle_files(files, steps)
        if out.get("blocked"):
            problems.append(f"/blocked: the OLD code wrote outside its scratch folder ({len(out['blocked'])})")
        old = out["steps"][0]
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        transport = RefusingTransport()
        app.state.watch_transport, app.state.watch_resolver = transport, fixture_resolver
        clock = REAL_CLOCK.replace(tzinfo=BERLIN)
        app.state.clock = functools.partial(lambda c: c, clock)
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            with transaction(settings.db_url) as conn:
                before_tables = _fingerprint(conn, schema)
                watched = watch_run.current(conn, schema).watched
            reads = ("/api/system_health", "/api/today", "/api/conviction/radar")
            before_views = {p: client.get(p).json() for p in reads}
            r = client.post("/api/watch_check", json={})
            answer = {"status": r.status_code, **r.json()}
            after_views = {p: client.get(p).json() for p in reads}
            with transaction(settings.db_url) as conn:
                new = new_state(client, conn, schema, answer)
                after_tables = _fingerprint(conn, schema)
        want = normalise(old)
        report.update({"old_watched": len(old["view"]["companies"]), "new_watched": len(watched),
                       "pages": len(answer.get("pages") or []), "fired": answer.get("fired"), "failures": answer.get("failures"),
                       "skipped": answer.get("skipped"), "fetched_old": len(old["fetched"]), "fetched_new": len(transport.asked),
                       "old_targets": len(want["targets"]), "old_snapshots": len(want["snapshots"])})  # fmt: skip
        problems += compare(want["answer"], answer, "/answer")
        problems += compare(
            {k: want[k] for k in ("log", "targets", "snapshots")},
            {k: new[k] for k in ("log", "targets", "snapshots")},
            "",
        )
        for p in reads:
            problems += diff(js(before_views[p]), js(after_views[p]), f"/readback{p}")
        changed = sorted(
            k for k in set(before_tables) | set(after_tables) if before_tables.get(k) != after_tables.get(k)
        )
        report["tables_changed"] = changed
        if not set(changed) <= {"watch_check_state"}:
            problems.append(f"/tables: unexpected tables changed {sorted(set(changed) - {'watch_check_state'})}")
    finally:
        admin.close()
        drop_schema(settings.db_url, schema)
    print(json.dumps(report, ensure_ascii=False))
    shapes = Counter(
        re.sub(r"/(targets|checks|companies|snapshots)/[^/:]+", r"/\1/<id>", d.split(":")[0]) for d in problems
    )
    for shape, n in shapes.most_common(40):
        print(f"  DIFF {shape} x{n}")  # path shapes only: never a real id, name or value
    print("WATCH SENSORS REAL PARITY PASSED" if not problems else f"WATCH SENSORS REAL PARITY FAILED ({len(problems)})")
    return 1 if problems else 0


# ------------------------------------------------------------------ goldens / check
def _summary(golden: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    for step, old in zip(golden["input"]["steps"], golden["expected"]["steps"], strict=True):
        a = old.get("answer") or {}
        out.append({"op": step["op"], "fired": a.get("fired", a.get("watch_triggers")), "failures": a.get("failures"),
                    "states": [p["state"] for p in a.get("pages") or []], "log_lines": len(str(old["log"]).splitlines()),
                    "snapshots": len(old["snapshots"]), "case_refresh": len(old["case_refresh"]),
                    "failing_checks": failing_of(old["view"])})  # fmt: skip
    return out


def write_goldens() -> int:
    inp = world_input()
    out = oracle(inp)
    meta = out.pop("meta")
    golden = {"provenance": {**meta, "clock0": CLOCK0.isoformat()}, "input": inp, "expected": out}
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    if out.get("blocked"):
        print("BLOCKED WRITES in the oracle:", out["blocked"])
        return 1
    for row in _summary(golden):
        print(json.dumps(row, ensure_ascii=False))
    problems = compare_pure(golden)
    for p in problems[:60]:
        print("  DIFF", p)
    print("WATCH SENSORS GOLDENS MATCH" if not problems else f"WATCH SENSORS GOLDENS DIFFER ({len(problems)})")
    return 1 if problems else 0


def check() -> int:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    problems = compare_pure(golden)
    if golden["expected"].get("blocked"):
        problems.append(f"/blocked: the oracle wrote outside its folder: {golden['expected']['blocked']}")
    if golden["input"] != js(world_input()):
        problems.append("/input: the stored world differs from world_input() (regenerate the goldens)")
    for p in problems[:60]:
        print("  DIFF", p)
    print("WATCH SENSORS CHECK PASSED" if not problems else f"WATCH SENSORS CHECK FAILED ({len(problems)})")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    mode = argv[1:]
    if mode == ["goldens"]:
        return write_goldens()
    if mode == ["check"]:
        return check()
    if mode == ["hosted"]:
        return hosted()
    if mode == ["real"]:
        return real()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

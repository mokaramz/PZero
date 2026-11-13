# ruff: noqa: E501
# (the invented world: one record per line)
"""WATCH store parity (review 037a): the NEW view, page saves and acknowledgements against the OLD ``watch.view()`` /
``set_target`` / ``acknowledge`` as oracle, over the SAME invented world and script, at a FIXED clock. No model call,
no network.

    python -m projectzero.ops.parity_watch_store goldens   # (re)generates golden_v1/oracle_watch_store.json
    python -m projectzero.ops.parity_watch_store check     # the pure parts against the stored golden (no database)
    python -m projectzero.ops.parity_watch_store hosted    # the whole new side in a throw-away pz_itest_* schema
    python -m projectzero.ops.parity_watch_store real      # PZ_LEGACY_DATA (read only) through a pz_rehearse_* import

The world (``world_docs``): inbox ``watch`` candidates (one with ``also_seen`` sources and a triage proposal older
than its newest trigger, one whose proposal is newer), a ``new`` candidate with a manual target and a proposal, a
Scout planner lead on MONITORING (imported as a ``watch`` candidate; it also has a manual target), active and inactive
targets with check records, and a triggers log with status lines, a re-acknowledgement, a status line without a
trigger, a legacy trigger missing fields, malformed lines, a CRLF line and more than 10 triggers for one company. The
script (``script``): the view; an imported target saved twice (two then three URLs); a manual company created,
deactivated and reactivated; every refusal; 8 URLs (6 kept); ``active: "false"`` (still active: only JSON ``false``
deactivates); acknowledgements (a re-acknowledgement, twice, unknown, a bad status, an empty id, a 400-character
note, an unwatched company's trigger); a watched candidate's first pages; the view.

``check``: per step, over the OLD state before / after the step (no database): the new pure answer (``parse_target``
/ ``merged`` / ``parse_ack``), the new log line, the new targets, and the new view build (``watch.view.build`` over
``watch.targets.watched``) of the old files. ``hosted``: the world through the PRODUCTION importer into a scratch
schema, then the same script through the routes (``app.state.clock`` frozen per step); compared after each step: the
answer (with its status code), the log lines (archive + rows), the effective targets, the view (``GET /api/watch``),
and the log as every reader reads it (Conviction, Today, Health, Home, the Map). Only ``watch_targets`` and
``watch_events`` may change.

Declared differences, ALL applied by ``normalise`` (the ONE place):

* **(a) the watched set:** every candidate on WATCH, not only the old inbox's: the expected view is the oracle's
  ``view_a`` (the OLD ``view()`` with the old watched set extended by the merged WATCH candidates the old inbox did
  not hold, appended after the inbox records: the Scout planner leads, ``extra_watch``). ``real`` reports their count.
* **errors:** the old ``ApiError`` was a 400 ``{ok: false, error}``; every answer carries its status code.
* **(not reached by the script)** ``urls`` that are not a list of strings: 400 "urls must be a list of strings" (the
  old code crashed); a BOM-prefixed archived log: its first line is read by every reader (the importer's
  ``utf-8-sig``, the Map's rule since H-201; the old Conviction / Today / Health skipped it). The hosted tests cover
  both.

The world holds INVENTED names only. Exit 1 on any difference.
"""

from __future__ import annotations

import copy
import functools
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from projectzero.core.paths import REPO_ROOT
from projectzero.dealflow.triage import card
from projectzero.ops.legacy.convert import stable_short_id
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js
from projectzero.ops.scratch_import import files_of
from projectzero.watch import log as watch_log
from projectzero.watch import targets as watch_targets
from projectzero.watch import view as watch_view
from projectzero.watch import writes

ORACLE = REPO_ROOT / "scripts" / "oracle" / "watch_store_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_watch_store.json"
CLOCK0 = datetime(2026, 11, 13, 10, 0, 0)
WATCH_TABLES = frozenset({"watch_targets", "watch_events"})


# ------------------------------------------------------------------ the world (invented names only)
def _c(cid: str, name: str, **extra: Any) -> dict[str, Any]:
    base = {"id": cid, "name": name, "description": f"{name} builds invented things.", "source": "Invented Feed",
            "source_id": "fx-feed", "discovery_tier": "announcement", "decision": "watch", "notes": "", "geo": ["DE"],
            "sectors": ["ai_sw"], "first_seen": "2026-10-01", "source_date": "2026-09-30", "location": "Berlin, Germany",
            "country": "DE", "source_url": f"https://feed.invented.example/news/{cid}"}  # fmt: skip
    return base | extra


def world_candidates() -> list[dict[str, Any]]:
    also = [{"source_id": "fx-grants", "source": "Invented Grant Desk", "discovery_tier": "grant",
             "first_seen": "2026-10-15 08:00:00", "url": "https://grants.invented.example/arvelle", "source_date": "2026-10-14"},
            {"source_id": "fx-press", "source": "Invented Press", "discovery_tier": "announcement",
             "first_seen": "2026-10-20 08:00:00", "url": "https://press.invented.example/arvelle", "source_date": "2026-10-19"}]  # fmt: skip
    return [
        _c("wat-arv", "Arvelle Robotics GmbH", also_seen=also),
        _c("wat-bro", "Brontide Labs"),
        _c("wat-cal", "Calyx Forge", decision="new"),
        _c("wat-hal", "Halvard Optics", decision="rejected"),
    ]


def _prop(c: Mapping[str, Any], proposal: str, proposed_at: str) -> dict[str, Any]:
    return {"candidate_id": c["id"], "name": c["name"], "proposal": proposal, "status": "proposed",
            "prompt_version": card.PROMPT_VERSION, "input_sha": card.card_sha(c), "proposed_at": proposed_at,
            "model": card.CHEAP_MODEL, "model_proposal": proposal, "stage": "stage1", "path": "cheap",
            "confidence": "medium", "reasons": ["an invented reason"], "missing": [], "flags": [],
            "capital_stage": "PRE_FUNDING", "themes": [], "sector": "software", "entity_type": "VENTURE",
            "run_id": "triage-20261020-080000-ab12", "reject_basis": None, "reject_evidence": None}  # fmt: skip


def world_proposals() -> dict[str, dict[str, Any]]:
    by = {c["id"]: c for c in world_candidates()}
    return {
        "wat-arv": _prop(by["wat-arv"], "WATCH", "2026-10-20T08:00:00"),
        "wat-bro": _prop(by["wat-bro"], "RESEARCH", "2026-11-05T09:30:00"),
        "wat-cal": _prop(by["wat-cal"], "KEEP", "2026-10-25T12:00:00"),
    }


SCOUT_LEADS: list[dict[str, Any]] = [
    {"id": "ns-lumen", "name": "Lumen Quarry", "status": "MONITORING", "origin": "planner", "first_seen": "2026-10-12",
     "last_seen": "2026-10-30", "why": "Invented planner lead: quarry drones.", "evidence": [{"url": "https://lumen.invented.example/", "source": "Invented Planner"}]},
    {"id": "ns-kelpie", "name": "Kelpie Motors", "status": "MONITORING", "origin": "planner", "first_seen": "2026-10-16",
     "last_seen": "2026-10-31", "why": "Invented planner lead: electric boat motors.", "evidence": []},
    {"id": "ns-ivory", "name": "Ivory Kiln", "status": "DISMISSED", "origin": "planner", "first_seen": "2026-10-13", "why": "Invented dismissed lead."},
    {"id": "ns-jasper", "name": "Jasper Weave", "status": "MONITORING", "origin": "scan", "first_seen": "2026-10-14", "why": "Invented non-planner signal."},
]  # fmt: skip


def extra_watch() -> list[dict[str, Any]]:
    """(a): the candidates the merged Deal Flow holds on WATCH that the old inbox did not (the MONITORING planner
    leads), as the old-format records the oracle appends to the old inbox for ``view_a``."""
    return [{"id": stable_short_id(f"native_scout:{s['id']}"), "name": s["name"], "decision": "watch"}
            for s in SCOUT_LEADS if s["origin"] == "planner" and s["status"] == "MONITORING"]  # fmt: skip


def _check(state: str, at: str, failures: int = 0, error: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {"last_checked": at, "last_state": state}
    if not failures:
        out["last_ok"] = at
    out["failures_in_row"] = failures
    if error:
        out["last_error"] = error
    return out


def world_targets() -> dict[str, Any]:
    arv, dorn = "https://arvelle.invented.example/news", "https://dornwell.invented.example/press"
    return {"version": 1, "targets": {
        "arvelle robotics": {"name": "Arvelle Robotics GmbH", "added_at": "2026-10-02T09:00:00",
                             "checks": {arv: _check("unchanged", "2026-11-12T07:00:00")}, "urls": [arv],
                             "candidate_id": "wat-arv", "active": True, "updated_at": "2026-10-02T09:00:00"},
        "dornwell systems": {"name": "Dornwell Systems", "added_at": "2026-10-03T09:00:00",
                             "checks": {dorn: _check("failed", "2026-11-12T07:00:05", 2, "TimeoutError: invented timeout")},
                             "urls": [dorn], "candidate_id": "", "active": True, "updated_at": "2026-10-03T09:00:00"},
        "embry analytics": {"name": "Embry Analytics", "added_at": "2026-10-04T09:00:00", "checks": {}, "urls": [],
                            "candidate_id": "", "active": False, "updated_at": "2026-10-05T09:00:00"},
        "calyx forge": {"name": "Calyx Forge", "added_at": "2026-10-06T09:00:00", "checks": {},
                        "urls": ["https://calyx.invented.example/"], "candidate_id": "wat-cal", "active": True,
                        "updated_at": "2026-10-06T09:00:00"},
        "lumen quarry": {"name": "Lumen Quarry", "added_at": "2026-10-07T09:00:00", "checks": {},
                         "urls": ["https://lumen.invented.example/news"], "candidate_id": "", "active": True,
                         "updated_at": "2026-10-07T09:00:00"},
    }}  # fmt: skip


def _trig(n: int, key: str, name: str, first_observed: str, predicate: str = "pilot", **extra: Any) -> dict[str, Any]:
    from projectzero.watch.view import LABEL

    tid = f"wt-{key[:3]}{n:09d}"
    base = {"id": tid, "kind": "trigger", "entity_key": key, "name": name, "candidate_id": "", "predicate": predicate,
            "label": LABEL.get(predicate, predicate), "high_value": predicate in ("pilot", "funding", "new_grant"),
            "source": f"https://{key[:3]}.invented.example/news", "source_kind": "page_check",
            "url": f"https://{key[:3]}.invented.example/news", "source_date": "", "first_observed": first_observed,
            "evidence": f"{name}: an invented line number {n}.", "dedupe_key": f"{key[:3]}{n:017d}"}  # fmt: skip
    return base | extra


def _status(tid: str, status: str, at: str, note: str = "") -> dict[str, Any]:
    return {"kind": "status", "trigger_id": tid, "status": status, "at": at, "note": note}


def _jl(row: Mapping[str, Any]) -> str:
    return json.dumps(dict(row), ensure_ascii=False, sort_keys=True)


def archived_log() -> str:
    arv, bro, dor = "arvelle robotics", "brontide labs", "dornwell systems"
    lines = [
        _jl(_trig(1, arv, "Arvelle Robotics GmbH", "2026-11-01T07:00:00", candidate_id="wat-arv")),
        _jl(
            _trig(
                2,
                arv,
                "Arvelle Robotics GmbH",
                "2026-11-03T07:00:00",
                "source_rehit",
                candidate_id="wat-arv",
                source="Invented Grant Desk",
                source_kind="scan_rehit",
                source_date="2026-10-14",
            )
        ),
        _jl(_status("wt-arv000000001", "reviewed", "2026-11-02T10:00:00", "Looked at it")),
        "not json",
        "[1, 2]",
        _jl(_trig(1, bro, "Brontide Labs", "2026-11-04T07:00:00", "funding", candidate_id="wat-bro")),
        _jl({"kind": "status", "status": "dismissed", "at": "2026-11-04T08:00:00"}),
        _jl({"id": "wt-legacy000001", "kind": "trigger", "name": "Dornwell Systems", "predicate": "launch"}),
        _jl(_status("wt-bro000000001", "dismissed", "2026-11-05T08:00:00")),
        _jl(_status("wt-bro000000001", "reviewed", "2026-11-05T09:00:00", "Re-acknowledged")),
        _jl(_trig(1, "embry analytics", "Embry Analytics", "2026-11-06T07:00:00", "customer")),
        _jl(_trig(1, "invented unwatched", "Invented Unwatched", "2026-11-06T08:00:00", "launch")),
        _jl(_trig(1, "calyx forge", "Calyx Forge", "2026-11-07T07:00:00", "partnership", candidate_id="wat-cal")),
    ]
    lines += [_jl(_trig(n, dor, "Dornwell Systems", f"2026-11-{n:02d}T06:30:00", "launch")) for n in range(1, 13)]
    text = "\n".join(lines[:5]) + "\r\n" + "\n".join(lines[5:]) + "\n"
    return text


def world_docs() -> dict[str, Any]:
    return {
        "inbox.json": {"candidates": world_candidates(), "last_run": "2026-10-20 08:00:00", "reprocess_v": 3},
        "triage_proposals.json": {"version": 1, "proposals": world_proposals()},
        "native_scout.json": {"signals": SCOUT_LEADS},
        "watch/targets.json": world_targets(),
        "watch/triggers.jsonl": archived_log(),
    }


def script() -> list[dict[str, Any]]:
    many = [f"https://gorsedd.invented.example/page{i}" for i in range(1, 9)]
    ops: list[tuple[str, dict[str, Any]]] = [
        ("view", {}),
        ("target", {"name": "Arvelle Robotics GmbH", "urls": [" https://arvelle.invented.example/news ",
                    "https://arvelle.invented.example/careers", "   "], "candidate_id": "wat-arv"}),
        ("target", {"name": "Arvelle Robotics GmbH", "urls": ["https://arvelle.invented.example/a",
                    "https://arvelle.invented.example/b", "https://arvelle.invented.example/c"]}),
        ("target", {"name": "Fennimore Cartage GmbH", "urls": []}),
        ("target", {"name": "Fennimore Cartage GmbH", "urls": ["https://fennimore.invented.example/"], "active": False}),
        ("target", {"name": "Fennimore Cartage", "urls": [], "active": True}),
        ("target", {"name": "   "}),
        ("target", {"name": "GmbH", "urls": ["https://x.invented.example/"]}),
        ("target", {"name": "Gorsedd Holdings", "urls": ["ftp://gorsedd.invented.example/x"]}),
        ("target", {"name": "Gorsedd Holdings", "urls": ["https://gorsedd.invented.example/ok", "localhost/x"]}),
        ("target", {"name": "Gorsedd Holdings", "urls": many, "candidate_id": "wat-none"}),
        ("target", {"name": "Embry Analytics", "urls": ["https://embry.invented.example/news"], "active": "false"}),
        ("ack", {"id": "wt-arv000000001", "status": "reviewed", "note": "Checked again — ünïcode"}),
        ("ack", {"id": "wt-arv000000001", "status": "dismissed"}),
        ("ack", {"id": "wt-nosuchthing1", "status": "reviewed"}),
        ("ack", {"id": "wt-arv000000002", "status": "closed"}),
        ("ack", {"status": "reviewed"}),
        ("ack", {"id": "wt-inv000000001", "status": "dismissed", "note": "x" * 400}),
        ("ack", {"id": "wt-legacy000001", "status": "reviewed", "note": None}),
        ("ack", {"id": "wt-dor000000012", "status": "reviewed"}),
        ("target", {"name": "Brontide Labs", "urls": ["https://brontide.invented.example/blog"], "candidate_id": ""}),
        ("view", {}),
    ]  # fmt: skip
    return [{"clock": CLOCK0.replace(minute=i).isoformat(), "op": op, "body": body} for i, (op, body) in enumerate(ops)]


def world_input() -> dict[str, Any]:
    return {"extra_watch": extra_watch(), "docs": world_docs(), "steps": script()}


# ------------------------------------------------------------------ the oracle
def oracle(inp: Mapping[str, Any]) -> dict[str, Any]:
    """The invented world (``world_input``): its documents written as ``scratch_import.files_of`` writes them."""
    return oracle_files(files_of(dict(inp["docs"])), inp["extra_watch"], inp["steps"])


def oracle_files(files: Mapping[str, bytes], extra: list[Any], steps: list[Any]) -> dict[str, Any]:
    """The oracle over raw files (the invented world's, or a byte-exact copy of the real snapshot) in a scratch folder."""
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-watch-store-oracle-") as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        for rel, raw in files.items():
            target = (data / rel).resolve()
            if data.resolve() not in target.parents:
                raise SystemExit(f"refusing a path outside the scratch folder: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        srcf, dst = Path(tmp) / "in.json", Path(tmp) / "out.json"
        srcf.write_bytes(json.dumps({"extra_watch": extra, "steps": steps}, ensure_ascii=False).encode("utf-8"))
        env = {k: v for k, v in os.environ.items() if k != "SUPABASE_DB_URL" and not k.endswith(("_API_KEY", "_TOKEN"))}
        env.update({"PZ_DATA": str(data), "PZ_TESTING": "1", "PYTHONPATH": str(OLD_REPO / "backend" / "src")})
        res = subprocess.run([str(python), str(ORACLE), str(srcf), str(dst)], env=env, capture_output=True, text=True)
        if res.returncode != 0:
            raise SystemExit(f"oracle failed:\n{res.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_bytes().decode("utf-8"))
        return out


# ------------------------------------------------------------------ the declared differences (ONE place)
def normalise(step: Mapping[str, Any], op: str) -> dict[str, Any]:
    """The old step -> the expected new one: the answer with its status code (``view``: none), the log lines, the
    targets, and (a) the view over the extended watched set (``view_a``)."""
    s = copy.deepcopy(dict(step))
    answer: dict[str, Any] | None
    if op == "view":
        answer = None
    elif "error" in s:
        answer = {"status": 400, "ok": False, "error": s["error"]}
    else:
        answer = {"status": 200, **s["answer"]}
    return {
        "answer": answer,
        "log": str(s["log"]).splitlines(),
        "targets": watch_targets.targets_of(s["targets"]),
        "view": s["view_a"],  # (a)
    }


def world_state() -> dict[str, Any]:
    """The old state before the first step, in the oracle's step shape (only ``log`` / ``targets`` are read)."""
    docs = world_docs()
    return {"log": docs["watch/triggers.jsonl"].replace("\r\n", "\n"), "targets": docs["watch/targets.json"]}


def key_order(value: Any, path: str = "") -> list[str]:
    """The key order of every object (``diff`` compares values only): the answer's record, the labels, the targets."""
    if isinstance(value, dict):
        out = [f"{path}: {list(value)}"]
        for k, v in value.items():
            out += key_order(v, f"{path}/{k}")
        return out
    if isinstance(value, list):
        return [x for i, v in enumerate(value) for x in key_order(v, f"{path}[{i}]")]
    return []


def compare(want: Mapping[str, Any], got: Mapping[str, Any], path: str) -> list[str]:
    problems = diff(js(want), js(got), path)
    if not problems:
        a, b = key_order(js(want)), key_order(js(got))
        problems += [f"{path}: key order {x} != {y}" for x, y in zip(a, b, strict=True) if x != y][:5]
    return problems


# ------------------------------------------------------------------ check: the pure parts
def pure_view(after: Mapping[str, Any], extra: list[dict[str, Any]]) -> dict[str, Any]:
    docs = world_docs()
    candidates = [*copy.deepcopy(docs["inbox.json"]["candidates"]), *copy.deepcopy(extra)]
    targets = watch_targets.targets_of(after["targets"])
    events = watch_log.parse_text(after["log"])
    return watch_view.build(watch_targets.watched(candidates, targets), targets, world_proposals(), events)


def pure_step(before: Mapping[str, Any], step: Mapping[str, Any]) -> dict[str, Any]:
    """The new pure answer and its effect over the old state before the step."""
    body, ts = step["body"], writes.now_ts(datetime.fromisoformat(step["clock"]))
    lines = str(before["log"]).splitlines()
    targets = watch_targets.targets_of(before["targets"])
    if step["op"] == "view":
        return {"answer": None, "log": lines, "targets": targets}
    try:
        if step["op"] == "target":
            req = writes.parse_target(body)
            record = writes.merged(targets.get(req.key), req, ts)
            return {"answer": {"status": 200, "ok": True, "target": record}, "log": lines,
                    "targets": watch_targets.overlay(targets, [(req.key, record)])}  # fmt: skip
        tid, status, note = writes.parse_ack(body)
        if not any(t["id"] == tid for t in watch_log.triggers(watch_log.parse_text(before["log"]))):
            raise writes.WatchError("no such trigger")
        row = {"kind": "status", "trigger_id": tid, "status": status, "at": ts, "note": note}
        return {"answer": {"status": 200, "ok": True, **row}, "log": [*lines, watch_log.line(row)], "targets": targets}
    except writes.WatchError as exc:
        return {"answer": {"status": 400, "ok": False, "error": str(exc)}, "log": lines, "targets": targets}


def compare_pure(golden: Mapping[str, Any]) -> list[str]:
    inp, exp = golden["input"], golden["expected"]
    problems: list[str] = []
    before: Mapping[str, Any] = world_state()
    for i, (step, old) in enumerate(zip(inp["steps"], exp["steps"], strict=True)):
        want = normalise(old, step["op"])
        got = {**pure_step(before, step), "view": pure_view(old, inp["extra_watch"])}
        problems += compare(want, got, f"/step{i}")
        problems += diff(js(old["events"]), js(watch_log.parse_text(old["log"])), f"/step{i}/events")
        problems += diff(
            js(old["triggers"]), js(watch_log.triggers(watch_log.parse_text(old["log"]))), f"/step{i}/triggers"
        )
        before = old
    return problems


# ------------------------------------------------------------------ hosted: the whole new side
def readers(conn: Any, schema: str, now: datetime) -> dict[str, Any]:
    """The log as every reader reads it (the ONE reader underneath each loader)."""
    from projectzero.conviction.inputs import load_inputs
    from projectzero.health import inputs as health_inputs
    from projectzero.home import inputs as home_inputs
    from projectzero.map import inputs as map_inputs
    from projectzero.today import inputs as today_inputs

    naive = now.replace(tzinfo=None)
    return {
        "conviction": load_inputs(conn, schema).operator.watch_events,
        "today": today_inputs.load(conn, schema, naive).operator.watch_events,
        "health": health_inputs.load(conn, schema, naive).watch_events,
        "home": home_inputs.load(conn, schema, naive).operator.watch_events,
        "map_open": map_inputs.load(conn, schema, naive).watch_open,
    }


def reader_problems(got: Mapping[str, Any], events: list[dict[str, Any]], path: str) -> list[str]:
    out: list[str] = []
    for name in ("conviction", "today", "health", "home"):
        out += diff(js(events), js(got[name]), f"{path}/{name}")
    out += diff(js(watch_log.open_triggers(events)), js(got["map_open"]), f"{path}/map_open")
    return out


def new_state(client: Any, conn: Any, schema: str, response: Any) -> dict[str, Any]:
    return {
        "answer": None if response is None else {"status": response.status_code, **response.json()},
        "log": watch_log.log_text(conn, schema).splitlines(),
        "targets": watch_targets.effective_targets(conn, schema),
        "view": client.get("/api/watch").json(),
    }


def _post(client: Any, step: Mapping[str, Any]) -> Any:
    if step["op"] == "view":
        return None
    return client.post("/api/watch_target" if step["op"] == "target" else "/api/watch_ack", json=step["body"])


def hosted(golden: Mapping[str, Any] | None = None) -> int:  # pragma: no cover - needs the hosted database
    from fastapi.testclient import TestClient

    from projectzero.api.app import create_app
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import transaction
    from projectzero.network.view import BERLIN
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
            imported = sorted(
                str(r[0])
                for r in conn.execute(
                    f"select id from {schema}.candidates where status = 'watch' and origins = array['legacy_native']".encode()
                ).fetchall()
            )
        if imported != sorted(x["id"] for x in inp["extra_watch"]):
            problems.append(f"/extra_watch: the importer put {len(imported)} Scout lead(s) on WATCH")
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            for i, (step, old) in enumerate(zip(inp["steps"], exp["steps"], strict=True)):
                clock = datetime.fromisoformat(step["clock"]).replace(tzinfo=BERLIN)
                app.state.clock = functools.partial(lambda c: c, clock)
                response = _post(client, step)
                with transaction(settings.db_url) as conn:
                    new = new_state(client, conn, schema, response)
                    got_readers = readers(conn, schema, clock)
                problems += compare(normalise(old, step["op"]), new, f"/step{i}")
                problems += reader_problems(got_readers, old["events"], f"/step{i}/readers")
                print(json.dumps({"step": i, "op": step["op"], "status": None if response is None else response.status_code,
                                  "companies": len(new["view"]["companies"]), "log_lines": len(new["log"])}, ensure_ascii=False))  # fmt: skip
        with transaction(settings.db_url) as conn:
            after_tables = _fingerprint(conn, schema)
        changed = sorted(
            k for k in set(before_tables) | set(after_tables) if before_tables.get(k) != after_tables.get(k)
        )
        if set(changed) != WATCH_TABLES:
            problems.append(f"/tables: changed {changed} (expected exactly {sorted(WATCH_TABLES)})")
    finally:
        drop_schema(settings.db_url, schema)
    for p in problems[:80]:
        print("  DIFF", p)
    print("WATCH STORE HOSTED PARITY PASSED" if not problems else f"WATCH STORE HOSTED PARITY FAILED ({len(problems)})")
    return 1 if problems else 0


# ------------------------------------------------------------------ the real snapshot
REAL_CLOCK = datetime(2026, 11, 13, 11, 0, 0)


def real() -> int:  # pragma: no cover - for the main session: needs the hosted database and the old repository
    """The plan's "Real snapshot" check: the real data folder (READ ONLY: captured once, bytes only) imported by the
    PRODUCTION importer into a throw-away ``pz_rehearse_*`` schema, against the OLD code over a byte-exact scratch copy
    of the same bytes. Step 0 writes nothing: the view (``GET /api/watch``) against the old ``view()`` extended by (a)'s
    merged WATCH candidates (those of the new watched set the old inbox does not hold), the log as every reader reads
    it against the old ``_events()`` / ``open_triggers()``. Then the first old-watched company's pages are saved (one
    invented URL) and an unknown trigger is acknowledged ("no such trigger"), compared after each step. Only
    ``watch_targets`` may change. Aggregates only are printed (no name, no id)."""
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
    old_ids = {
        str(c["id"])
        for c in (snapshot.json("inbox.json") or {}).get("candidates", [])
        if isinstance(c, dict) and c.get("id")
    }
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
        with transaction(settings.db_url) as conn:
            records, _props = watch_targets.watch_candidates(conn, schema)
            before_tables = _fingerprint(conn, schema)
        extra = [
            {"id": c["id"], "name": c.get("name"), "decision": "watch"}
            for c in records
            if str(c.get("id")) not in old_ids
        ]
        report["watch_candidates"] = len(records)
        report["extra_watch"] = len(extra)
        probe = oracle_files(files, extra, [{"clock": REAL_CLOCK.isoformat(), "op": "view", "body": {}}])
        first = (probe["steps"][0]["view"]["companies"] or [{}])[0].get("name")
        steps: list[dict[str, Any]] = [{"clock": REAL_CLOCK.isoformat(), "op": "view", "body": {}}]
        if first:
            steps.append({"clock": REAL_CLOCK.replace(minute=1).isoformat(), "op": "target",
                          "body": {"name": first, "urls": ["https://pages.invented.example/news"]}})  # fmt: skip
        steps.append({"clock": REAL_CLOCK.replace(minute=2).isoformat(), "op": "ack",
                      "body": {"id": "wt-nosuchthing1", "status": "reviewed"}})  # fmt: skip
        out = oracle_files(files, extra, steps)
        if out.get("blocked"):
            problems.append(f"/blocked: the OLD code wrote outside its scratch folder ({len(out['blocked'])})")
        report["old_watched"] = len(out["steps"][0]["view"]["companies"])
        report["old_watched_with_a"] = len(out["steps"][0]["view_a"]["companies"])
        report["archived_lines"] = len(out["steps"][0]["events"])
        report["archived_triggers"] = len(out["steps"][0]["triggers"])
        report["old_targets"] = len(watch_targets.targets_of(out["steps"][0]["targets"]))
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            for i, (step, old) in enumerate(zip(steps, out["steps"], strict=True)):
                clock = datetime.fromisoformat(step["clock"]).replace(tzinfo=BERLIN)
                app.state.clock = functools.partial(lambda c: c, clock)
                response = _post(client, step)
                with transaction(settings.db_url) as conn:
                    new = new_state(client, conn, schema, response)
                    got_readers = readers(conn, schema, clock)
                diffs = compare(normalise(old, step["op"]), new, f"/step{i}")
                diffs += reader_problems(got_readers, old["events"], f"/step{i}/readers")
                problems += diffs
                print(json.dumps({"step": i, "op": step["op"], "status": None if response is None else response.status_code,
                                  "companies": len(new["view"]["companies"]), "open": sum(c["open"] for c in new["view"]["companies"]),
                                  "log_lines": len(new["log"]), "targets": len(new["targets"]), "differences": len(diffs)}, ensure_ascii=False))  # fmt: skip
        with transaction(settings.db_url) as conn:
            after_tables = _fingerprint(conn, schema)
        changed = sorted(
            k for k in set(before_tables) | set(after_tables) if before_tables.get(k) != after_tables.get(k)
        )
        report["tables_changed"] = changed
        if not set(changed) <= WATCH_TABLES:
            problems.append(f"/tables: unexpected tables changed {sorted(set(changed) - WATCH_TABLES)}")
    finally:
        admin.close()
        drop_schema(settings.db_url, schema)
    print(json.dumps(report, ensure_ascii=False))
    shapes = Counter(re.sub(r"/(targets|checks)/[^/:]+", r"/\1/<id>", d.split(":")[0]) for d in problems)
    for shape, n in shapes.most_common(40):
        print(f"  DIFF {shape} x{n}")  # path shapes only: never a real id, name or value
    print("WATCH STORE REAL PARITY PASSED" if not problems else f"WATCH STORE REAL PARITY FAILED ({len(problems)})")
    return 1 if problems else 0


# ------------------------------------------------------------------ goldens / check
def _summary(golden: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    for step, old in zip(golden["input"]["steps"], golden["expected"]["steps"], strict=True):
        out.append({"op": step["op"], "answer": old.get("answer") if step["op"] == "ack" else
                    (old.get("error") or ("ok" if old.get("answer") else None)),
                    "log_lines": len(str(old["log"]).splitlines()), "companies": len(old["view"]["companies"]),
                    "companies_a": len(old["view_a"]["companies"])})  # fmt: skip
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
    print("WATCH STORE GOLDENS MATCH" if not problems else f"WATCH STORE GOLDENS DIFFER ({len(problems)})")
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
    print("WATCH STORE CHECK PASSED" if not problems else f"WATCH STORE CHECK FAILED ({len(problems)})")
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

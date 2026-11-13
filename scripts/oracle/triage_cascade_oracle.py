"""ORACLE: the OLD machine-triage cascade and automatic triage (review 035b), with a FIXED clock and uuid. Never
imported by the new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/triage_cascade_oracle.py IN.json OUT.json

IN = {steps: [{clock, op: "scan" | "job" | "retry_now", scan_run_id?, paid}], replies: {candidate id: {role: [outcome,
...]}}, hex: [the run ids' uuid suffixes, in order], estimate: {prices, max_out}, corpus: [{card, cand, data}]}.
``PZ_DATA`` is a scratch folder holding the world's files (``inbox.json``, ``triage_proposals.json``, ...).

The old ``gateway.complete`` is replaced by a script that returns the old ``Result`` from the recorded replies: an
outcome is ``{text, usd}`` (the reply, priced; extracted and validated with the caller's ``validate`` as the old
gateway did: ``malformed`` / ``invalid``), ``{error_kind, error}`` (a provider failure, $0) or ``{stop:
"budget_blocked"}`` (the run cap's refusal text, computed as the new gateway prices it: the run's ledger spend plus the
call's estimate). With ``paid`` false every call is refused ``disabled`` ("paid inference is switched off (PZ_AI_PAID
is not 'on')"). An identical successful request (model, messages, extra) is served from a script cache ($0, cached),
as the old gateway's cache did. Every call appends the old ledger line (its ``usd`` and ``run_id``) and is recorded
(role, purpose, model, ``use_cache``, entity, run id, cap, extra body, the messages' sha256).

Per step, at the step's clock: ``scan`` runs the old ``auto_triage.start(scan_run_id)`` (its thread run
synchronously), ``job`` the old scheduler's ``_run_triage_retry()``, ``retry_now`` the old ``POST /api/triage_retry``
route (its thread synchronous); then the record of: the answer, the calls, every proposal, the runner ``runs[]``,
the automatic runs, the retry state (in its key order), ``pending_map()``, ``status()`` and the triage view
(``proposals`` / ``counts`` / ``pending``). ``corpus``: the old ``validator_for(card, cand)(data)`` per item (the
answer, or the ``ValueError`` text), plus the system prompt's sha256.

The clock: ``datetime.now()`` / ``date.today()`` of every loaded ``projectzero`` module. Writes: ``storage.save_json``
/ ``write_text`` / ``append_line`` outside the scratch data folder are refused and recorded as ``blocked``. Refused: a
``PZ_DATA`` inside ``project-zero-data``, and any ``SUPABASE_DB_URL``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

NOW: list[datetime] = []
BLOCKED: list[str] = []
CALLS: list[dict[str, Any]] = []
CACHE: dict[str, str] = {}
PAID: list[bool] = [True]
COUNTER = [0]
NEW_SWITCH = "paid inference is switched off (PZ_AI_PAID is not 'on')"


class FixedDate(date):
    @classmethod
    def today(cls) -> FixedDate:  # type: ignore[override]
        n = NOW[-1]
        return cls(n.year, n.month, n.day)


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> FixedDateTime:  # type: ignore[override]
        n = NOW[-1]
        return cls(n.year, n.month, n.day, n.hour, n.minute, n.second)


def _freeze() -> list[str]:
    frozen = []
    for name, module in sorted(sys.modules.items()):
        if not name.startswith("projectzero") or module is None:
            continue
        if getattr(module, "date", None) is date:
            module.date = FixedDate  # type: ignore[attr-defined]
            frozen.append(f"{name}.date")
        if getattr(module, "datetime", None) is datetime:
            module.datetime = FixedDateTime  # type: ignore[attr-defined]
            frozen.append(f"{name}.datetime")
    return frozen


def _block(root: Path) -> None:
    from projectzero import storage

    def inside(name: str, fn: Any) -> Any:
        def guarded(target: Any, *a: Any, **k: Any) -> Any:
            p = Path(str(target))
            full = (p if p.is_absolute() else storage.data_dir() / p).resolve()
            if root not in full.parents:
                BLOCKED.append(f"{name}:{full}")
                raise RuntimeError(f"the triage oracle blocks {name} outside the scratch folder: {full}")
            return fn(target, *a, **k)

        return guarded

    storage.save_json = inside("save_json", storage.save_json)  # type: ignore[assignment]
    storage.write_text = inside("write_text", storage.write_text)  # type: ignore[assignment]
    storage.append_line = inside("append_line", storage.append_line)  # type: ignore[assignment]


class SyncThread:
    """``threading.Thread`` run synchronously (the old start / route threads)."""

    def __init__(self, target: Any = None, daemon: Any = None, name: Any = None, **_: Any) -> None:
        self.target = target

    def start(self) -> None:
        self.target()


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and "project-zero-data" not in Path(data_dir).resolve().parts, "PZ_DATA must be a scratch folder"
    assert not os.environ.get("SUPABASE_DB_URL"), "the oracle never sees the database"
    os.environ.setdefault("PZ_TESTING", "1")
    os.environ["PZ_AUTO_TRIAGE"] = "1"
    root = Path(data_dir).resolve()
    inp = json.loads(src.read_bytes().decode("utf-8"))
    NOW.append(datetime.fromisoformat(inp["steps"][0]["clock"]) if inp["steps"] else datetime(2026, 11, 13))
    from projectzero.api.routers import triage as triage_routes
    from projectzero.inference import config as icfg
    from projectzero.inference import gateway, ledger
    from projectzero.services import auto_triage, scheduler, triage_review
    from projectzero.services import shadow_triage as st

    from projectzero import storage

    storage.configure(root)
    hexes = list(inp.get("hex") or [])

    class FixedUUID:
        def __init__(self, h: str) -> None:
            self.hex = h

    uuid.uuid4 = lambda: FixedUUID((hexes.pop(0) if hexes else "ffff") + "0" * 28)  # type: ignore[assignment]
    real_thread = threading.Thread
    threading.Thread = SyncThread  # type: ignore[misc, assignment]
    auto_triage._schedule_retry = lambda when: None  # no real timers (the old test did the same)
    replies: dict[str, dict[str, list[dict[str, Any]]]] = copy.deepcopy(inp.get("replies") or {})
    est_cfg = inp.get("estimate") or {}

    def estimate(messages: list[dict[str, str]], model: str, role: str) -> float:
        p = est_cfg["prices"][model]
        chars = len(json.dumps(messages, ensure_ascii=False))
        return round((chars / 3.5 * p["input"] + est_cfg["max_out"][role] * p["output"]) / 1_000_000, 6)

    def fake_complete(role: str, messages: list[dict[str, str]], *, purpose: str, entity_id: str | None = None,
                      run_id: str | None = None, run_cap_usd: float | None = None, json_mode: bool = True,
                      validate: Any = None, model: str | None = None, max_output_tokens: int | None = None,
                      override_reason: str | None = None, use_cache: bool = True, extra_body: Any = None,
                      **_: Any) -> Any:  # fmt: skip
        COUNTER[0] += 1
        cfg = icfg.load()
        rcfg = cfg["roles"][role]
        mdl = str(model or rcfg["model"])
        res = gateway.Result(ok=False, role=role, provider=str(rcfg["provider"]), model=mdl,
                             call_id=f"ic-{COUNTER[0]:012d}")  # fmt: skip
        CALLS.append({"role": role, "purpose": purpose, "model": mdl, "use_cache": use_cache, "entity_id": entity_id,
                      "run_id": run_id, "run_cap_usd": run_cap_usd, "extra_body": extra_body,
                      "override_reason": override_reason,
                      "messages_sha": hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest()})  # fmt: skip

        def book() -> Any:
            ledger.append({"ts": ledger.now_ts(), "run_id": run_id, "usd": res.usd, "purpose": purpose,
                           "entity_id": entity_id, "model": mdl, "call_id": res.call_id})  # fmt: skip
            return res

        if not PAID[0]:
            res.error_kind, res.error = "disabled", NEW_SWITCH
            return book()
        key = json.dumps([mdl, messages, extra_body or {}], sort_keys=True, ensure_ascii=False)

        def accept(text: str) -> None:
            res.text = text
            data = gateway.extract_json(text)
            if data is None:
                res.error_kind, res.error = "malformed", "reply contained no parseable JSON"
                return
            res.data = data
            if validate is not None:
                try:
                    res.data = validate(data)
                except ValueError as e:
                    res.error_kind, res.error = "invalid", str(e)[:500]
                    return
            res.ok = True

        if use_cache and key in CACHE:
            res.cached = True
            accept(CACHE[key])
            return book()
        cid = str(entity_id or "")[len("inbox:"):]
        queue = replies.get(cid, {}).get(role) or []
        if not queue:
            raise RuntimeError(f"no recorded reply left for {cid} {role}")
        o = queue[0]
        if "stop" in o:
            spent = ledger.total(ledger.entries(), run_id=run_id)
            est = estimate(messages, mdl, role)
            res.error_kind = o["stop"]
            res.error = f"run cap reached for {run_id} (${spent:.4f} spent + ${est:.4f} next > ${run_cap_usd:.2f})"
            queue.pop(0)  # a refusal happens once: the next run of the candidate gets the next reply
            return book()
        queue.pop(0)
        if "error_kind" in o:
            res.error_kind, res.error = o["error_kind"], o["error"]
            res.attempts = 3
            return book()
        res.usd = float(o.get("usd") or 0.0)
        res.usd_source = "reported"
        accept(str(o["text"]))
        if res.ok and use_cache:
            CACHE[key] = str(o["text"])
        return book()

    gateway.complete = fake_complete  # type: ignore[assignment]
    frozen = _freeze()
    _block(root)

    def state() -> dict[str, Any]:
        doc = st.load_proposals()
        view = triage_review.view()
        return {
            "proposals": copy.deepcopy(doc["proposals"]),
            "runs": copy.deepcopy(doc["runs"]),
            "auto_runs": copy.deepcopy(auto_triage._runs()["runs"]),
            "retry_state": [[k, v] for k, v in auto_triage._retry_state().items()],
            "pending_map": auto_triage.pending_map(),
            "status": auto_triage.status(),
            "view": {k: view[k] for k in ("proposals", "counts", "pending")},
        }

    steps = []
    for step in inp["steps"]:
        NOW.append(datetime.fromisoformat(step["clock"]))
        PAID[0] = bool(step.get("paid", True))
        CALLS.clear()
        if step["op"] == "scan":
            answer: Any = auto_triage.start(step["scan_run_id"])
        elif step["op"] == "job":
            answer = {"note": scheduler._run_triage_retry()}
        else:
            answer = triage_routes.triage_retry({})
        steps.append({"clock": step["clock"], "op": step["op"], "answer": answer, "calls": list(CALLS), **state()})
    threading.Thread = real_thread  # type: ignore[misc]
    corpus = []
    for item in inp.get("corpus") or []:
        try:
            corpus.append({"ok": st.validator_for(item["card"], item.get("cand"))(copy.deepcopy(item["data"]))})
        except ValueError as e:
            corpus.append({"error": str(e)})
    old_root = Path(st.__file__).resolve().parents[4]
    revision = subprocess.run(["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()  # fmt: skip
    dirty = subprocess.run(["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
                           capture_output=True, text=True, check=True).stdout.strip()  # fmt: skip
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "mode": "triage_cascade", "frozen": frozen,
            "system_prompt_sha256": st.system_prompt_sha()}  # fmt: skip
    out = {"meta": meta, "steps": steps, "corpus": corpus, "blocked": list(BLOCKED)}
    dst.write_bytes(json.dumps(out, ensure_ascii=False, indent=1).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

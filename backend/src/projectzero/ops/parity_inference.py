"""Inference gateway parity (review 029a): the NEW gateway + ``InMemoryBudgetStore`` + the new ``FakeProvider``
against the OLD ``gateway.complete`` and ``budget.check`` (rev 6c739b9) as oracle.

    python -m projectzero.ops.parity_inference goldens   # (re)generate tests/fixtures/golden_v1/oracle_inference.json
    python -m projectzero.ops.parity_inference check     # the new side against the golden

The oracle (``scripts/oracle/inference_oracle.py``, the old interpreter) replays ``CASES``: each case a scratch data
folder with a seeded ledger, a frozen clock (naive Berlin wall time) and steps (calls with a scripted old fake
provider, direct ``budget.check`` decisions, other callers' reservations). No step reaches a network or a real
provider on either side, and no key exists in either environment. The new side replays the same steps with the
clock as Europe/Berlin, the ledger seeded through the importer's mapping (``ops/legacy/map_records.ledger``) and
compares, per step: the ``Result`` (+ ``must_stop``), the estimate, the waits, the provider calls, the ledger rows
(the old line in the importer's mapping against the new row; ``latency_ms`` normalised to 0) and the decisions;
per case the reservations left. Everything not listed below must be EQUAL.

Declared differences (``expected_new`` applies each to the old output; the result must equal the new output):

* **(c) the paid switch is off by default.** Case ``c_unset`` (``PZ_AI_PAID`` absent): the old call went through;
  the new one is refused exactly as the old one refused with ``PZ_AI_PAID=off`` (case ``c_off``). Everywhere, the
  refusal text ``paid inference is switched off (PZ_AI_PAID=off)`` reads ``... (PZ_AI_PAID is not 'on')``.
* **(d) the cache after the switch.** Case ``d_cache_off``: a cached paid answer asked for with paid calls off was
  a ``cache_hit`` in the old app; the new one is refused exactly as the old refused the same call without the cache
  (case ``d_ref``).
* **(h) RESEARCH is dropped.** The old disabled role answered ``disabled``; the new one is an unknown role
  (``not_configured``, ``unknown role 'RESEARCH'``, row outcome ``error``).
* **One row per attempt** (plan revision 2). The old app wrote one line per call; the new rows carry ``attempt``
  (0 for a call that made no attempt or a cache hit, 1 for a call blocked at its first admission, else the attempt)
  and every retried attempt before the last has its OWN row (outcome ``error``, its error kind, ``attempts`` = its
  index, no tokens), dated like the call's row and carrying the same shas.
* **A failure after dispatch is charged its estimate** (plan revision 2). An attempt that failed once the request
  was sent (a scripted error without ``"dispatched": false``: a timeout, an HTTP error status, a malformed body) is
  charged the call's estimate, ``usd_source`` ``estimated``, where the old app charged $0 ``none``; a failure before
  dispatch stays $0 ``none``. ``Result.usd`` is the sum over the attempts, ``Result.usd_source`` the last one's.
* **Per-attempt admission** (plan revision 2). Case ``retry_blocked``: the first attempt fits the day's last
  headroom and fails after dispatch; its estimate is charged, so the retry no longer fits and is NOT sent
  (``budget_blocked``, a ``blocked`` row for attempt 2); the old app, admitted once per call, sent the retry.

Not a difference: a VALID reply without usage is ``ok`` and charged the estimate (``estimated``) on both sides (the
old code already did; plan revision 3 keeps it); case ``basics`` covers it. Abandoned reservations and late
settlements have no old counterpart (the old reservations lived in one process): ``tests/core/inference`` covers them.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from projectzero.core.inference import budget, gateway
from projectzero.core.inference import config as icfg
from projectzero.core.inference.budget import BERLIN
from projectzero.core.inference.providers import DEFAULT_USAGE, FakeProvider, ProviderError, Reply, reported_cost
from projectzero.core.inference.store import InMemoryBudgetStore, LedgerRow, Reservation
from projectzero.core.paths import REPO_ROOT
from projectzero.ops.legacy.convert import timestamp
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO

ORACLE = REPO_ROOT / "scripts" / "oracle" / "inference_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_inference.json"
CLOCK = "2026-11-12T10:00:00"  # a Thursday
ON = {"PZ_AI_PAID": "on"}
OFF = {"PZ_AI_PAID": "off"}
OLD_SWITCH_TEXT = "paid inference is switched off (PZ_AI_PAID=off)"
NEW_SWITCH_TEXT = "paid inference is switched off (PZ_AI_PAID is not 'on')"
SYSTEM = {"role": "system", "content": "You are a careful analyst of invented companies. Reply in JSON only."}


def msgs(text: str) -> list[dict[str, str]]:
    return [SYSTEM, {"role": "user", "content": text}]


M1 = msgs("Invented Lantern Robotics raised a seed round in Munich. Summarise it.")


def seed(ts: str, usd: float, **kw: Any) -> dict[str, Any]:
    """An old ledger line (imported, no call id)."""
    line = {"ts": ts, "usd": usd, "purpose": "seeded", "provider": "deepinfra",
            "model": "deepseek-ai/DeepSeek-V4-Flash", "outcome": "ok", "usd_source": "reported"}  # fmt: skip
    line.update({"role": kw.get("role"), "entity_id": kw.get("entity_id"), "run_id": kw.get("run_id")})
    return line


def call(role: str = "CHEAP", messages: list[dict[str, str]] | None = None, script: list[Any] | None = None,
         **kw: Any) -> dict[str, Any]:  # fmt: skip
    step: dict[str, Any] = {"op": "call", "role": role, "messages": messages or M1, "script": script or []}
    for k in ("provider", "paid", "usage", "validate", "env", "at", "declared"):
        if k in kw:
            step[k] = kw.pop(k)
    step["kw"] = {"purpose": kw.pop("purpose", "parity"), **kw}
    return step


def check(est: float, **kw: Any) -> dict[str, Any]:
    return {"op": "check", "est": est, "purpose": kw.pop("purpose", "t"), **kw}


def reserve(
    call_id: str, usd: float, role: str, entity_id: str | None = None, run_id: str | None = None
) -> dict[str, Any]:
    return {"op": "reserve", "call_id": call_id, "usd": usd, "role": role, "entity_id": entity_id, "run_id": run_id}


def release(call_id: str) -> dict[str, Any]:
    return {"op": "release", "call_id": call_id}


def ok(text: str = '{"answer": 1}', **kw: Any) -> dict[str, Any]:
    return {"text": text, **kw}


def err(kind: str, message: str, status: int | None = None, retry_after: float | None = None,
        dispatched: bool = True) -> dict[str, Any]:  # fmt: skip
    return {"raise": kind, "message": message, "status": status, "retry_after": retry_after, "dispatched": dispatched}


NC: dict[str, Any] = {"use_cache": False}
EST_M1 = budget.estimate_usd(icfg.price(icfg.DEFAULTS, "deepseek-ai/DeepSeek-V4-Flash") or {},
                             len(json.dumps(M1, ensure_ascii=False)), 700)  # fmt: skip
RETRY_SEED = round(1.0 - 1.5 * EST_M1, 6)

CASES: list[dict[str, Any]] = [
    {
        "name": "basics",
        "clock": CLOCK,
        "env": ON,
        "steps": [
            call(script=[ok('Sure:\n```json\n{"answer": 42}\n```')], entity_id="inbox:lantern", run_id="run-1"),
            call(
                messages=msgs("Invented Quarry Bio?"),
                script=[ok(usage={"prompt_tokens": 10, "completion_tokens": 5, "estimated_cost": 0.0001234567891})],
            ),
            call(messages=msgs("Invented Basin Labs?"), script=[ok('{"answer": "no usage"}', usage=None)]),
            call(messages=msgs("Invented Zephyr Drones?"), script=[ok("plain words, no JSON")], json_mode=False),
            call(messages=msgs("Invented Beacon Automation?"), script=[ok("no json here at all")]),
            call(messages=msgs("Invented Garnet Robotics?"), script=[ok('{"other": 1}')], validate="need_answer"),
            call(
                messages=msgs("Invented Nickel Labs?"), script=[ok('{"answer": "yes", "x": 2}')], validate="need_answer"
            ),
            call(
                messages=msgs("Invented Granite Tools?"),
                script=[
                    ok(
                        '{"answer": 1}',
                        usage={
                            "prompt_tokens": 900,
                            "completion_tokens": 100,
                            "prompt_tokens_details": {"cached_tokens": 400},
                        },
                    )
                ],
            ),
            call(
                messages=msgs("Invented Harbor AI?"),
                script=[
                    {
                        "reply": {
                            "text": '{"answer": 1}',
                            "usage": {"prompt_tokens": 50, "completion_tokens": 9},
                            "tool_calls": [{"id": "t1", "type": "function"}],
                        }
                    }
                ],
            ),
            call(
                messages=msgs("Invented Harbor AI?"), script=[ok('{"answer": 2}')]
            ),  # the tool-call reply was not cached
            call(
                role="STANDARD",
                messages=msgs("Invented Ember Grid?"),
                script=[ok()],
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                max_output_tokens=1200,
                timeout_s=300,
            ),
            call(messages=msgs("Invented Fjord Data?"), script=[ok()], model="Qwen/Qwen3.5-9B"),
            call(messages=msgs("Invented free answer?"), script=[ok()], paid=False),
            call(messages=msgs("Invented free answer?"), script=[ok()], paid=False),  # a free cache hit
            call(
                messages=msgs("Invented free failure?"), script=[err("server", "HTTP 500 : boom")] * 3, paid=False, **NC
            ),
        ],
    },
    {
        "name": "refusals",
        "clock": CLOCK,
        "env": ON,
        "steps": [
            call(role="ESCALATION"),
            call(role="NOPE"),
            call(role="RESEARCH", declared="h"),
            call(model="Invented/unpriced-model"),
            call(provider=None),  # the configured (real) provider without a key: refused before any request
            call(provider=None, env={}),
        ],
    },
    {
        "name": "unconfigured",
        "clock": CLOCK,
        "env": ON,
        "inference": {"roles": {"STANDARD": {"provider": "nowhere"}, "CHEAP": {"model": ""}}},
        "steps": [call(role="STANDARD"), call(role="CHEAP"), call(role="CHEAP", model="deepseek-ai/DeepSeek-V4-Flash")],
    },
    {
        "name": "rules",
        "clock": CLOCK,
        "env": ON,
        "seed": [
            seed("2026-11-10T09:00:00", 0.03, role="STANDARD", run_id="run-a"),
            seed("2026-09-01T12:00:00", 0.60, role="STANDARD", entity_id="inbox:basin"),
            seed("2026-10-15T12:00:00", 0.35, role="STANDARD", entity_id="inbox:basin"),
            seed("2026-11-02T12:00:00", 2.90, role="CHEAP"),
            seed("2026-11-12T08:00:00", 0.50, role="STANDARD"),
        ],
        "steps": [
            check(0.03, run_id="run-a", run_cap_usd=0.05),
            check(0.03, run_id="run-a", run_cap_usd=0.05, override_reason="Mohamed approved this run"),
            check(0.03, run_cap_usd=0.05),  # no run id: no run cap
            check(0.01, run_id="run-a", run_cap_usd=0.05, override_reason="short"),
            check(0.01, override_reason=" 1234567 "),
            check(0.01, override_reason="12345678"),
            check(9.0, override_reason="Mohamed approved a big one"),
            check(0.051),
            check(0.15, purpose="ic_chair"),
            check(0.15, purpose="ic_chair", role="STANDARD"),
            check(0.011, purpose="native_planner"),
            check(0.05, role="STANDARD"),
            check(0.05, role="STANDARD", entity_id="inbox:basin"),
            reserve("ic-other-1", 0.02, "STANDARD", "inbox:basin", "run-b"),
            check(0.04, role="STANDARD", entity_id="inbox:basin"),
            check(0.01, role="STANDARD", run_id="run-b", run_cap_usd=0.025),
            reserve("ic-other-2", 0.45, "CHEAP"),
            check(0.04, role="STANDARD"),
            check(0.02, role="STANDARD"),
            release("ic-other-2"),
            check(0.04, role="STANDARD"),
            reserve("ic-other-3", 0.07, "CHEAP"),
            check(0.04),
            call(**NC),
            call(run_id="run-a", run_cap_usd=0.0301, **NC),
            call(run_id="run-a", run_cap_usd=0.0301, override_reason="Mohamed approved this run", **NC),
            call(override_reason="nope", **NC),
            call(max_output_tokens=300_000, **NC),
            call(max_output_tokens=300_000, override_reason="Invented approval for a long answer", **NC),
            call(role="STANDARD", entity_id="inbox:basin", max_output_tokens=3000, **NC),
            check(0.0001, role="STANDARD", entity_id="inbox:basin"),
        ],
    },
    {
        "name": "win_day",
        "clock": CLOCK,
        "env": ON,
        "seed": [seed("2026-11-12T00:00:00", 0.96), seed("2026-11-11T23:59:59", 0.96)],
        "steps": [check(0.04), check(0.041), call(**NC), check(0.04)],
    },
    {
        "name": "win_day_dst",
        "clock": "2026-10-25T12:00:00",
        "env": ON,
        "seed": [seed("2026-10-25T00:00:00", 0.96), seed("2026-10-24T23:59:59", 0.96)],
        "steps": [check(0.04), check(0.041)],
    },
    {
        "name": "win_week",
        "clock": CLOCK,
        "env": ON,
        "seed": [seed("2026-11-09T00:00:00", 4.96), seed("2026-11-08T23:59:59", 4.96)],
        "steps": [
            check(0.04),
            check(0.041),
            call(max_output_tokens=230_000, **NC),
            call(max_output_tokens=200_000, **NC),
        ],
    },
    {
        "name": "win_week_month_start",
        "clock": "2026-11-02T00:00:30",
        "env": ON,
        "seed": [
            seed("2026-11-02T00:00:00", 0.50),
            seed("2026-11-01T23:59:59", 4.48),
            seed("2026-10-31T23:59:59", 30.0),
        ],
        "steps": [check(0.02), check(0.0201), check(0.02, at="2026-11-01T23:59:59")],
    },
    {
        "name": "win_month",
        "clock": "2026-11-26T10:00:00",
        "env": ON,
        "seed": [
            seed("2026-11-01T00:00:00", 20.0),
            seed("2026-11-22T23:59:59", 4.96),
            seed("2026-10-31T23:59:59", 100.0),
        ],
        "steps": [check(0.04), check(0.041), check(0.04, at="2026-12-01T00:00:00")],
    },
    {
        "name": "win_role",
        "clock": "2026-11-26T10:00:00",
        "env": ON,
        "seed": [
            seed("2026-11-01T00:00:00", 2.96, role="CHEAP"),
            seed("2026-10-31T23:59:59", 5.0, role="CHEAP"),
            seed("2026-11-20T12:00:00", 1.5, role="STANDARD"),
        ],
        "steps": [check(0.04), check(0.041), check(0.041, role="STANDARD"), call(max_output_tokens=230_000, **NC)],
    },
    {
        "name": "win_entity",
        "clock": CLOCK,
        "env": ON,
        "seed": [
            seed("2025-06-01T12:00:00", 0.50, entity_id="inbox:e"),
            seed("2026-10-01T12:00:00", 0.46, entity_id="inbox:e"),
            seed("2026-10-02T12:00:00", 0.30, entity_id="inbox:other"),
        ],
        "steps": [
            check(0.04, entity_id="inbox:e"),
            check(0.041, entity_id="inbox:e"),
            check(0.041, entity_id="inbox:f"),
            call(entity_id="inbox:e", max_output_tokens=230_000, **NC),
        ],
    },
    {
        "name": "retries",
        "clock": CLOCK,
        "env": ON,
        "steps": [
            call(script=[err("timeout", "timed out after 60s"), ok()], **NC),
            call(script=[err("rate_limited", "HTTP 429 : slow down", 429, 12), ok()], **NC),
            call(script=[err("rate_limited", "HTTP 429 : slow down", 429, 90)] * 3, **NC),
            call(script=[err("rate_limited", "HTTP 429 : slow down", 429, 1), ok()], **NC),
            call(script=[err("server", "HTTP 503 engine_overloaded: Model busy, retry later", 503)] * 2 + [ok()], **NC),
            call(script=[err("timeout", "the engine is busy"), ok()], **NC),
            call(script=[err("network", "ConnectionRefusedError: refused", dispatched=False), ok()], **NC),
            call(script=[err("network", "ConnectionResetError: reset"), ok()], **NC),
            call(script=[err("server", "HTTP 500 : boom", 500)] * 3, **NC),
            call(script=[err("network", "URLError: no route", dispatched=False)] * 3, **NC),
            call(script=[err("auth", "HTTP 401 invalid: bad key", 401)], **NC),
            call(script=[err("auth", "HTTP 403 : forbidden", 403)], **NC),
            call(script=[err("billing", "HTTP 402 : pay", 402)], **NC),
            call(script=[err("bad_request", "HTTP 400 : bad", 400)], **NC),
            call(script=[err("bad_request", "refused 'https://x': DNS resolution failed", dispatched=False)], **NC),
            call(script=[err("malformed", "unexpected response shape (KeyError)")], **NC),
            call(script=[err("timeout", "timed out after 60s"), ok("no json")], **NC),
            call(
                script=[err("server", "HTTP 502 : bad gateway", 502), ok('{"other": 1}')], validate="need_answer", **NC
            ),
        ],
    },
    {
        "name": "cache",
        "clock": CLOCK,
        "env": ON,
        "steps": [
            call(script=[ok('{"answer": "cached"}')]),
            call(script=[ok('{"answer": "never asked"}')], at="2026-11-12T11:00:00"),
            call(script=[ok()], validate="reject"),
            call(script=[ok('{"answer": "uncached"}')], use_cache=False),
            call(script=[ok('{"answer": "fresh"}')], validate="need_answer"),
            call(messages=msgs("Invented invalid first?"), script=[ok('{"x": 1}')], validate="need_answer"),
            call(messages=msgs("Invented invalid first?"), script=[ok('{"answer": 3}')], validate="need_answer"),
            call(messages=msgs("Invented malformed first?"), script=[ok("nothing")]),
            call(messages=msgs("Invented malformed first?"), script=[ok('{"answer": 4}')]),
            call(messages=msgs("Invented text?"), script=[ok("words")], json_mode=False),
            call(messages=msgs("Invented text?"), script=[ok("other words")], json_mode=False),
            call(messages=msgs("Invented text?"), script=[ok('{"answer": 5}')]),  # json mode: another key
            call(script=[ok('{"answer": "max out"}')], max_output_tokens=500),  # another key
            call(script=[ok('{"answer": "entity"}')], entity_id="inbox:x", run_id="run-z"),  # the same key
        ],
    },
    {"name": "c_unset", "clock": CLOCK, "env": {}, "steps": [call(script=[ok()])]},
    {"name": "c_off", "clock": CLOCK, "env": OFF, "steps": [call(script=[ok()])]},
    {
        "name": "d_cache_off",
        "clock": CLOCK,
        "env": ON,
        "steps": [call(script=[ok('{"answer": "cached"}')]), call(script=[ok()], env=OFF), call(script=[ok()])],
    },
    {
        "name": "d_ref",
        "clock": CLOCK,
        "env": ON,
        "steps": [
            call(script=[ok('{"answer": "cached"}')]),
            call(script=[ok()], env=OFF, use_cache=False),
            call(script=[ok()]),
        ],
    },
    {
        "name": "retry_blocked",
        "clock": CLOCK,
        "env": ON,
        "seed": [seed("2026-11-12T08:00:00", RETRY_SEED)],
        "steps": [call(script=[err("server", "HTTP 500 : boom", 500), ok()], declared="retry_admission", **NC)],
    },
]
REFERENCE = {"c_unset": "c_off", "d_cache_off": "d_ref"}  # declared (c) and (d): the new case equals the old ref


# ------------------------------------------------------------------ the oracle
def run_oracle() -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-inference-oracle-") as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        src, dst = Path(tmp) / "in.json", Path(tmp) / "out.json"
        src.write_bytes(json.dumps({"cases": CASES}).encode("utf-8"))
        env = {k: v for k, v in os.environ.items() if k not in icfg.KEY_ENVS and k != "SUPABASE_DB_URL"}
        env.update({"PZ_DATA": str(data), "PZ_TESTING": "1", "PYTHONPATH": str(OLD_REPO / "backend" / "src"),
                    "PZ_AI_PAID": "on"})  # fmt: skip
        env.pop("PZ_SCOUT00_PAID", None)
        run = subprocess.run([str(python), str(ORACLE), str(src), str(dst)], env=env, capture_output=True, text=True)
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_bytes().decode("utf-8"))
        return out


# ------------------------------------------------------------------ the new side
def _validators() -> dict[str, Any]:
    def need_answer(d: Any) -> Any:
        if not isinstance(d, dict) or "answer" not in d:
            raise ValueError("Invented check: the reply has no answer")
        return {"answer": d["answer"], "checked": True}

    def reject(d: Any) -> Any:
        raise ValueError("Invented check refuses every reply")

    return {"need_answer": need_answer, "reject": reject}


def _responder(script: list[dict[str, Any]], default_usage: dict[str, Any]) -> Any:
    queue = list(script)

    def responder(messages: Any, model: str) -> str | Reply:
        item: dict[str, Any] = queue.pop(0) if queue else {"text": '{"ok": true}'}
        if "raise" in item:
            raise ProviderError(
                item["raise"],
                item.get("message", ""),
                item.get("status"),
                retry_after=item.get("retry_after"),
                dispatched=item.get("dispatched", True),
            )
        if "reply" in item:
            r = item["reply"]
            usage = dict(r.get("usage") or {})
            return Reply(text=r.get("text", ""), usage=usage, reported_usd=reported_cost(usage), model=model,
                         tool_calls=list(r.get("tool_calls") or []))  # fmt: skip
        usage = default_usage if "usage" not in item else (item["usage"] or {})
        return Reply(text=item["text"], usage=dict(usage), reported_usd=reported_cost(usage), model=model)

    return responder


def imported(line: dict[str, Any]) -> dict[str, Any]:
    """An old ledger line in the importer's mapping (``ops/legacy/map_records.ledger``), ``at`` in Berlin ISO."""
    promoted = {"ts", "purpose", "provider", "model", "entity_id", "usd", "input_tokens", "output_tokens", "cached",
                "outcome"}  # fmt: skip
    usd = line.get("usd")
    at = timestamp(line.get("ts"))
    return {
        "at": at.isoformat() if at else None,
        "purpose": str(line.get("purpose") or "unknown"),
        "provider": line.get("provider"),
        "model": line.get("model"),
        "entity_ref": line.get("entity_id"),
        "usd": usd if isinstance(usd, int | float) and not isinstance(usd, bool) else 0,
        "tokens_in": line.get("input_tokens") if isinstance(line.get("input_tokens"), int) else None,
        "tokens_out": line.get("output_tokens") if isinstance(line.get("output_tokens"), int) else None,
        "cached": bool(line.get("cached")),
        "outcome": line.get("outcome"),
        "detail": {k: v for k, v in line.items() if k not in promoted},
    }


def as_row(d: dict[str, Any]) -> LedgerRow:
    at = datetime.fromisoformat(d["at"])
    return LedgerRow(at, d["purpose"], d["provider"], d["model"], d["entity_ref"], float(d["usd"]), d["tokens_in"],
                     d["tokens_out"], d["cached"], d["outcome"], dict(d["detail"]))  # fmt: skip


def row_dict(r: LedgerRow) -> dict[str, Any]:
    return {"at": r.at.astimezone(BERLIN).isoformat(), "purpose": r.purpose, "provider": r.provider, "model": r.model,
            "entity_ref": r.entity_ref, "usd": r.usd, "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
            "cached": r.cached, "outcome": r.outcome, "detail": dict(r.detail)}  # fmt: skip


def _estimate(cfg: dict[str, Any], role: str, messages: Any, kw: dict[str, Any]) -> float | None:
    rcfg = (cfg.get("roles") or {}).get(role)
    if not isinstance(rcfg, dict):
        return None
    price = icfg.price(cfg, str(kw.get("model") or rcfg.get("model") or ""))
    if price is None:
        return None
    max_out = int(kw.get("max_output_tokens") or rcfg.get("max_output_tokens") or 1000)
    return budget.estimate_usd(price, len(json.dumps(messages, ensure_ascii=False)), max_out)


def _fixed(t: datetime) -> Callable[[], datetime]:
    return lambda: t


def run_new(case: dict[str, Any]) -> dict[str, Any]:
    cfg = icfg.load(case.get("inference"))
    store = InMemoryBudgetStore([as_row(imported(line)) for line in case.get("seed", [])])
    counter = [0]

    def new_id() -> str:
        counter[0] += 1
        return f"ic-{counter[0]:012d}"

    validators = _validators()
    out: list[dict[str, Any]] = []
    for step in case["steps"]:
        now = datetime.fromisoformat(step.get("at") or case["clock"]).replace(tzinfo=BERLIN)
        env = dict(step["env"] if "env" in step else case["env"])
        op = step["op"]
        if op == "reserve":
            held = Reservation(step["call_id"], 1, step["usd"], step["role"], "other", "deepinfra", "m",
                               step.get("entity_id"), step.get("run_id"), now, now + timedelta(days=1))  # fmt: skip
            store.hold(held)
            out.append({})
            continue
        if op == "release":
            store.drop(step["call_id"], 1)
            out.append({})
            continue
        if op == "check":
            role = step.get("role", "CHEAP")
            spend = store.spend(now=now, role=role, entity_id=step.get("entity_id"), run_id=step.get("run_id"))
            decision = budget.check(budget.limits(cfg), spend, est_usd=step["est"], role=role,
                                    entity_id=step.get("entity_id"), run_id=step.get("run_id"),
                                    run_cap_usd=step.get("run_cap_usd"), override_reason=step.get("override_reason"),
                                    purpose=step.get("purpose", ""))  # fmt: skip
            out.append({"decision": decision})
            continue
        before = len(store.rows)
        waits: list[float] = []
        name = step.get("provider", "deepinfra")
        fake = None
        if name is not None:
            fake = FakeProvider(_responder(step.get("script", []), step.get("usage") or dict(DEFAULT_USAGE)),
                                paid=step.get("paid", True))  # fmt: skip
        kw = dict(step.get("kw") or {})
        if step.get("validate"):
            kw["validate"] = validators[step["validate"]]
        res = gateway.complete(step["role"], step["messages"], **kw, store=store, clock=_fixed(now), env=env,
                               providers={name: fake} if fake is not None and name else None, config=cfg,
                               sleep=waits.append, new_id=new_id)  # fmt: skip
        result = dict(res.__dict__)
        result["must_stop"] = res.must_stop
        calls = [{"model": c["model"], "json_mode": c["json_mode"], "max_output_tokens": c["max_output_tokens"],
                  "extra_body": c["extra_body"]} for c in (fake.calls if fake else [])]  # fmt: skip
        out.append({"result": result, "est": _estimate(cfg, step["role"], step["messages"], kw), "waits": waits,
                    "calls": calls, "rows": [row_dict(r) for r in store.rows[before:]]})  # fmt: skip
    pending = {k[0]: v.usd for k, v in store.reservations.items()}
    return {"name": case["name"], "steps": js(out), "pending": pending}


def js(v: Any) -> Any:
    return json.loads(json.dumps(v, ensure_ascii=False, default=str))


# ------------------------------------------------------------------ the declared differences
def _norm(step: dict[str, Any]) -> dict[str, Any]:
    """Non-semantic: latency is 0 on both sides; the paid-switch text (declared c)."""
    s = copy.deepcopy(step)
    if "result" in s:
        s["result"]["latency_ms"] = 0
        if s["result"].get("error") == OLD_SWITCH_TEXT:
            s["result"]["error"] = NEW_SWITCH_TEXT
        for r in s["rows"]:
            if r["detail"].get("latency_ms") is not None:
                r["detail"]["latency_ms"] = 0
    return s


def _attempt_rows(step: dict[str, Any], old: dict[str, Any]) -> dict[str, Any]:
    """One row per attempt and the cost of a failure after dispatch (declared)."""
    exp = copy.deepcopy(old)
    res, rows, est = exp["result"], [imported(r) for r in exp["rows"]], exp["est"] or 0.0
    (last,) = rows
    n, paid, script = res["attempts"], step.get("paid", True), step.get("script", [])
    attempt = 1 if last["outcome"] == "blocked" and n == 0 else n  # 0: no attempt (a refusal, a cache hit)
    earlier, total = [], 0.0
    for a in range(1, n):
        item = script[a - 1]
        usd, src = budget.attempt_cost(paid=paid, est_usd=est, dispatched=item.get("dispatched", True))
        total += usd
        d = {k: last["detail"][k] for k in ("call_id", "role", "run_id", "prompt_sha", "request_sha", "override_reason")
             if k in last["detail"]}  # fmt: skip
        d.update({"attempt": a, "attempts": a, "error_kind": item["raise"], "usd_source": src, "latency_ms": 0,
                  "cached_input_tokens": None})  # fmt: skip
        earlier.append({**last, "usd": usd, "tokens_in": None, "tokens_out": None, "cached": False,
                        "outcome": "error", "detail": d})  # fmt: skip
    last["detail"]["attempt"] = attempt
    final = last["usd"]
    lastitem = script[n - 1] if 0 < n <= len(script) else {}
    if "raise" in lastitem:  # the last attempt failed: no reply
        final, src = budget.attempt_cost(paid=paid, est_usd=est, dispatched=lastitem.get("dispatched", True))
        last["usd"], last["detail"]["usd_source"], res["usd_source"] = final, src, src
        res["usd"] = round(total + final, 8)
    else:
        res["usd"] = round(total + final, 8) if total else final
    exp["rows"] = [*earlier, last]
    return exp


def _research(exp: dict[str, Any]) -> dict[str, Any]:
    """(h): RESEARCH is an unknown role."""
    exp["result"].update(error_kind="not_configured", error="unknown role 'RESEARCH'")
    exp["est"] = None  # no role, no price
    exp["rows"][-1].update(outcome="error")
    exp["rows"][-1]["detail"]["error_kind"] = "not_configured"
    return exp


def _retry_admission(case: dict[str, Any], exp: dict[str, Any]) -> dict[str, Any]:
    """Per-attempt admission: the retry no longer fits the day once attempt 1 was charged its estimate."""
    est = exp["est"]
    first, _second = exp["rows"]
    day = round(sum(s["usd"] for s in case["seed"]) + est, 6)
    reason = f"day budget reached (${day:.4f} spent + ${est:.4f} next > $1.00) — Mohamed may override with a reason"
    exp["result"].update(ok=False, text="", data=None, error_kind="budget_blocked", error=reason, usd=est,
                         usd_source="estimated", usage={}, tool_calls=[], attempts=1, must_stop=True)  # fmt: skip
    blocked = copy.deepcopy(first)
    blocked.update(usd=0.0, outcome="blocked")
    blocked["detail"].update(attempt=2, attempts=1, error_kind="budget_blocked", usd_source="none")
    exp["rows"] = [first, blocked]
    exp["calls"] = exp["calls"][:1]
    return exp


def expected_new(case: dict[str, Any], old: dict[str, Any]) -> dict[str, Any]:
    """The old output of ``case`` with every declared difference applied (the new output must equal it)."""
    steps = []
    for step, o in zip(case["steps"], old["steps"], strict=True):
        if step["op"] != "call":
            steps.append(o)
            continue
        exp = _norm(_attempt_rows(step, o))
        if step.get("declared") == "h":
            exp = _research(exp)
        elif step.get("declared") == "retry_admission":
            exp = _retry_admission(case, exp)
        steps.append(exp)
    return {"name": case["name"], "steps": js(steps), "pending": {k: v["usd"] for k, v in old["pending"].items()}}


def _diff(a: Any, b: Any, path: str = "") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}.{k}: {'missing in expected' if k not in a else 'missing in new'}")
            else:
                out.extend(_diff(a[k], b[k], f"{path}.{k}"))
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: {len(a)} expected vs {len(b)} new items"]
        return [d for i, (x, y) in enumerate(zip(a, b, strict=True)) for d in _diff(x, y, f"{path}[{i}]")]
    return [] if a == b else [f"{path}: expected {a!r}, new {b!r}"]


def compare(golden: dict[str, Any]) -> list[str]:
    if js(CASES) != golden["cases"]:
        return ["the golden was generated from other CASES: regenerate it (goldens)"]
    old = {c["name"]: c for c in golden["expected"]}
    problems: list[str] = []
    for case in CASES:
        name = case["name"]
        ref_case = next(c for c in CASES if c["name"] == REFERENCE.get(name, name))
        exp = expected_new(ref_case, old[ref_case["name"]])
        # the declared difference must be real: the old case and its reference differ
        if name in REFERENCE and js(expected_new(case, old[name])["steps"]) == exp["steps"]:
            problems.append(f"{name}: the old app did not differ from {ref_case['name']} (nothing declared)")
        new = run_new(case)
        new["steps"] = [_norm(s) for s in new["steps"]]
        problems.extend(f"{name}{d}" for d in _diff({"steps": exp["steps"], "pending": exp["pending"]},
                                                     {"steps": new["steps"], "pending": new["pending"]}))  # fmt: skip
    return problems


def write_goldens() -> int:
    out = run_oracle()
    golden = {"provenance": out["meta"], "cases": js(CASES), "expected": out["cases"]}
    GOLDEN.write_bytes((json.dumps(golden, ensure_ascii=False, indent=None) + "\n").encode("utf-8"))
    calls = sum(1 for c in CASES for s in c["steps"] if s["op"] == "call")
    checks = sum(1 for c in CASES for s in c["steps"] if s["op"] == "check")
    print(f"inference goldens written: {len(CASES)} cases, {calls} calls, {checks} checks; provenance "
          f"{out['meta']['old_revision'][:7]} dirty={out['meta']['old_dirty']}")  # fmt: skip
    return 0


def load_golden() -> dict[str, Any]:
    golden: dict[str, Any] = json.loads(GOLDEN.read_bytes().decode("utf-8"))
    return golden


def run_check() -> int:
    problems = compare(load_golden())
    for p in problems[:60]:
        print(p)
    calls = sum(1 for c in CASES for s in c["steps"] if s["op"] == "call")
    print(f"inference parity: {len(CASES)} cases, {calls} calls, {len(problems)} differences beyond the declared ones")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["goldens"]:
        return write_goldens()
    if argv[1:] == ["check"]:
        return run_check()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

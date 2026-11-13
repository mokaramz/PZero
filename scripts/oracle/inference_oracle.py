"""ORACLE: the OLD inference gateway (review 029a): ``gateway.complete`` and ``budget.check`` over scripted sequences,
with the old ``FakeProvider`` (``paid=True`` unless a step says otherwise), a FIXED clock, a scratch ledger and a
scratch data folder per case. Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/inference_oracle.py IN.json OUT.json

IN = {cases: [{name, clock, env, inference?, seed: [old ledger lines], steps: [...]}]}. Steps:

* ``call``: ``{role, messages, kw, script, provider?, paid?, usage?, validate?, env?, at?}`` -> the old
  ``complete(role, messages, **kw)``. ``script`` is the fake provider's answers in order: ``{"text": ...}``
  (``"usage"`` absent: the fake's default usage; ``null``: no usage; a dict: that usage), ``{"reply": {text, usage,
  tool_calls}}`` or ``{"raise": kind, "message", "status", "retry_after"}`` (the old ``ProviderError``). ``provider``
  names the provider the fake stands in for (``deepinfra``); ``null`` leaves the old configured provider in place (it
  is only ever reached for its key check: the step's env has no key). Recorded: the ``Result`` (+ ``must_stop``),
  the old estimate for the call, the waits, the provider calls and the ledger lines the call appended.
* ``check``: ``{est, role, entity_id, run_id, run_cap_usd, override_reason, purpose}`` -> the old ``budget.check``.
* ``reserve`` / ``release``: the old in-process reservation of another caller.

Safety: every provider key variable is removed from the environment before anything is imported; the old
``net.fetch``, ``urllib.request.urlopen`` and ``OpenAICompatibleProvider.complete`` raise, so the old code can never
reach a real provider (and no step relies on them). ``PZ_AI_PAID`` is ``on`` unless a case or step says otherwise.
The clock: ``datetime.now()`` in the old ledger frozen at the case's (or step's) naive Berlin wall time;
``time.monotonic()`` constant (latency 0); ``uuid4().hex`` a counter (call ids ``ic-000000000001``...).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from datetime import datetime
from pathlib import Path
from typing import Any

KEY_ENVS = ("DEEPINFRA_API_KEY", "XAI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")
SWITCH_ENVS = ("PZ_AI_PAID", "PZ_SCOUT00_PAID")
for _k in KEY_ENVS:  # before any old module is imported
    os.environ.pop(_k, None)

NOW: list[datetime] = []
COUNTER = [0]


class Refused(RuntimeError):
    pass


def _refuse(*a: Any, **k: Any) -> Any:
    raise Refused("the oracle never reaches the network or a real provider")


def _freeze() -> None:
    import urllib.request

    from projectzero.inference import gateway, ledger, providers

    from projectzero import net

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> FixedDateTime:  # type: ignore[override]
            n = NOW[-1]
            return cls(n.year, n.month, n.day, n.hour, n.minute, n.second)

    ledger.datetime = FixedDateTime  # type: ignore[attr-defined]
    gateway.time = types.SimpleNamespace(monotonic=lambda: 0.0, sleep=_refuse)  # type: ignore[attr-defined]

    def uuid4() -> Any:
        COUNTER[0] += 1
        return types.SimpleNamespace(hex=f"{COUNTER[0]:012d}" + "0" * 20)

    gateway.uuid = types.SimpleNamespace(uuid4=uuid4)  # type: ignore[attr-defined]
    net.fetch = _refuse  # type: ignore[assignment]
    urllib.request.urlopen = _refuse  # type: ignore[assignment]
    providers.OpenAICompatibleProvider.complete = _refuse  # type: ignore[method-assign]
    providers.OpenAICompatibleProvider.list_models = _refuse  # type: ignore[method-assign]


VALIDATORS: dict[str, Any] = {}


def _validators() -> None:
    def need_answer(d: Any) -> Any:
        if not isinstance(d, dict) or "answer" not in d:
            raise ValueError("Invented check: the reply has no answer")
        return {"answer": d["answer"], "checked": True}

    def reject(d: Any) -> Any:
        raise ValueError("Invented check refuses every reply")

    VALIDATORS.update(need_answer=need_answer, reject=reject)


def _set_env(env: dict[str, str]) -> None:
    for k in SWITCH_ENVS:
        os.environ.pop(k, None)
    os.environ.update(env)


def _responder(script: list[dict[str, Any]], default_usage: dict[str, Any]) -> Any:
    from projectzero.inference import providers

    queue = list(script)

    def responder(messages: Any, model: str) -> Any:
        item = queue.pop(0) if queue else {"text": '{"ok": true}'}
        if "raise" in item:
            raise providers.ProviderError(
                item["raise"], item.get("message", ""), item.get("status"), retry_after=item.get("retry_after")
            )
        if "reply" in item:
            r = item["reply"]
            usage = dict(r.get("usage") or {})
            return providers.Reply(text=r.get("text", ""), usage=usage, reported_usd=providers.reported_cost(usage),
                                   model=model, tool_calls=list(r.get("tool_calls") or []))  # fmt: skip
        usage = default_usage if "usage" not in item else (item["usage"] or {})
        return providers.Reply(text=item["text"], usage=dict(usage), reported_usd=providers.reported_cost(usage),
                               model=model)  # fmt: skip

    return responder


def _estimate(role: str, messages: Any, kw: dict[str, Any]) -> float | None:
    from projectzero.inference import budget
    from projectzero.inference import config as icfg

    cfg = icfg.load()
    rcfg = (cfg.get("roles") or {}).get(role)
    if not isinstance(rcfg, dict):
        return None
    model = str(kw.get("model") or rcfg.get("model") or "")
    price = icfg.price(cfg, model)
    if price is None:
        return None
    max_out = int(kw.get("max_output_tokens") or rcfg.get("max_output_tokens") or 1000)
    return budget.estimate_usd(price, len(json.dumps(messages, ensure_ascii=False)), max_out)


def run_case(case: dict[str, Any], root: Path) -> dict[str, Any]:
    from projectzero.inference import budget, gateway, ledger, providers
    from projectzero.inference import config as icfg

    from projectzero import storage

    folder = root / case["name"]
    storage.configure(folder)
    if case.get("inference"):
        storage.save_json("config.json", {"inference": case["inference"]})
    for line in case.get("seed", []):
        ledger.append(line)
    budget._reserved.clear()
    providers._OVERRIDES.clear()
    COUNTER[0] = 0
    out: list[dict[str, Any]] = []
    for step in case["steps"]:
        NOW.append(datetime.fromisoformat(step.get("at") or case["clock"]))
        _set_env(step["env"] if "env" in step else case["env"])
        op = step["op"]
        if op == "reserve":
            budget.reserve(step["call_id"], step["usd"], step["role"], step.get("entity_id"), step.get("run_id"))
            out.append({})
            continue
        if op == "release":
            budget.release(step["call_id"])
            out.append({})
            continue
        if op == "check":
            decision = budget.check(
                icfg.load(),
                est_usd=step["est"],
                role=step.get("role", "CHEAP"),
                entity_id=step.get("entity_id"),
                run_id=step.get("run_id"),
                run_cap_usd=step.get("run_cap_usd"),
                override_reason=step.get("override_reason"),
                purpose=step.get("purpose", ""),
            )
            out.append({"decision": decision})
            continue
        assert op == "call", op
        before = len(ledger.entries())
        waits: list[float] = []
        gateway.SLEEP = waits.append
        providers._OVERRIDES.clear()
        fake = None
        name = step.get("provider", "deepinfra")
        if name is not None:
            fake = providers.FakeProvider(
                _responder(
                    step.get("script", []), step.get("usage") or {"prompt_tokens": 1000, "completion_tokens": 200}
                ),
                paid=step.get("paid", True),
            )
            providers.set_provider(name, fake)
        kw = dict(step.get("kw") or {})
        if step.get("validate"):
            kw["validate"] = VALIDATORS[step["validate"]]
        res = gateway.complete(step["role"], step["messages"], **kw)
        result = {k: v for k, v in res.__dict__.items()}
        result["must_stop"] = res.must_stop
        calls = [{"model": c["model"], "json_mode": c["json_mode"], "max_output_tokens": c["max_output_tokens"],
                  "extra_body": c["extra_body"]} for c in (fake.calls if fake else [])]  # fmt: skip
        out.append({"result": result, "est": _estimate(step["role"], step["messages"], kw), "waits": waits,
                    "calls": calls, "rows": ledger.entries()[before:]})  # fmt: skip
    return {"name": case["name"], "steps": out, "ledger": ledger.entries(), "pending": dict(budget._reserved)}


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and Path(data_dir).name != "project-zero-data", "PZ_DATA must be a scratch folder"
    os.environ.setdefault("PZ_TESTING", "1")
    inp = json.loads(src.read_bytes().decode("utf-8"))
    _freeze()
    _validators()
    from projectzero.domain import taste  # the OLD package

    old_root = Path(taste.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()  # fmt: skip
    cases = [run_case(c, Path(data_dir)) for c in inp["cases"]]
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "mode": "inference"}
    dst.write_bytes(json.dumps({"meta": meta, "cases": cases}, ensure_ascii=False, default=str).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

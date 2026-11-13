"""ORACLE: the OLD News model cards (review 028d): ``services/news._make_cards`` through the OLD inference gateway with
the OLD ``FakeProvider`` (``paid=True``), a FIXED clock, a scratch ledger per case and every events write in memory.
Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/news_cards_oracle.py IN.json OUT.json

IN = {clock, system, card, events, cases: [{name, usage, script, after}]}:

* ``events``: the events document the run starts from (the 028c world: the events after the refresh golden's last
  run); ``news.load`` answers a copy of the in-memory document, ``news._save`` replaces it (recorded per save as the
  events whose card changed: ``{event_id: card}``). ``storage.state_lock`` is the old one.
* ``system``: the NEW prompt (decision b) is installed as the old ``news.SYSTEM`` so the requests, their shas and
  their estimates are the new ones; the old text is recorded as ``old_system`` for the declared check.
* ``script``: the fake provider's answers in call order: ``{"card": true}`` (``card`` with ``{headline}`` replaced by
  the request's headline, as JSON), ``{"text": ...}``, or ``{"raise": kind, "message", "status"}`` (the old
  ``ProviderError``); ``usage`` is the fake's usage for every reply.
* ``after``: ``{call index: "remove" | "carded" | "headline"}``: right after that gateway call returns (before the old
  loop writes), the in-memory document is changed as a concurrent writer would: the event removed, given a model card
  (``CONCURRENT_CARD``), or its headline changed (``HEADLINE_SUFFIX`` appended).

Recorded per case: ``made`` / ``usd`` (the old return), per gateway call the ``entity_id``, the ``Result`` (+
``must_stop``), the old estimate, the waits, the provider calls and the ledger lines it appended; every save; the
events whose record differs from ``events`` at the end (``null``: removed).

Safety: the inference oracle's ``_freeze`` (shared): every provider key variable removed before any old module is
imported, the old ``net.fetch``, ``urllib.request.urlopen`` and ``OpenAICompatibleProvider.complete`` raise, so the
old code can never reach a real provider; ``PZ_AI_PAID`` is ``on`` (the old side only). The clock: the old ledger's
and the old ``news`` module's ``datetime.now()`` frozen at ``clock`` (naive Berlin wall time), ``time.monotonic()``
constant, call ids from a counter. The data folder (``PZ_DATA``, scratch) holds only the per-case ledgers.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import inference_oracle  # the 029a oracle: key removal on import, _freeze, the counter

CONCURRENT_CARD = {
    "what_happened": "Invented concurrent card.",
    "why_it_matters": "Written by another invented writer.",
    "the_company": "",
    "vc_lesson": "",
    "watch_next": [],
    "generated_by": "invented-concurrent-model",
}
HEADLINE_SUFFIX = " (invented correction)"


def _responder(script: list[dict[str, Any]], card: dict[str, Any], usage: dict[str, Any]) -> Any:
    from projectzero.inference import providers

    queue = list(script)

    def fill(v: Any, headline: str) -> Any:
        if isinstance(v, str):
            return v.replace("{headline}", headline)
        if isinstance(v, list):
            return [fill(x, headline) for x in v]
        return v

    def responder(messages: Any, model: str) -> Any:
        item = queue.pop(0) if queue else {"card": True}
        if "raise" in item:
            raise providers.ProviderError(item["raise"], item.get("message", ""), item.get("status"))
        if "card" in item:
            headline = messages[-1]["content"].split("\n", 1)[0][len("HEADLINE: ") :]
            text = json.dumps({k: fill(v, headline) for k, v in card.items()}, ensure_ascii=False)
        else:
            text = item["text"]
        return providers.Reply(text=text, usage=dict(usage), reported_usd=providers.reported_cost(usage), model=model)

    return responder


def run_case(inp: dict[str, Any], case: dict[str, Any], root: Path) -> dict[str, Any]:
    from projectzero.inference import budget, gateway, ledger, providers
    from projectzero.services import news

    from projectzero import storage

    storage.configure(root / case["name"])
    budget._reserved.clear()
    providers._OVERRIDES.clear()
    inference_oracle.COUNTER[0] = 0
    world = inp["events"]
    doc = [copy.deepcopy(world)]
    saves: list[dict[str, Any]] = []

    def load() -> dict[str, Any]:
        return copy.deepcopy(doc[0])

    def save(d: dict[str, Any]) -> None:
        before = doc[0]["events"]
        changed = {
            k: v.get("card") for k, v in d["events"].items() if (before.get(k) or {}).get("card") != v.get("card")
        }
        saves.append(changed)
        doc[0] = json.loads(json.dumps(d, ensure_ascii=False))

    news.load = load  # type: ignore[attr-defined]
    news._save = save  # type: ignore[attr-defined]
    fake = providers.FakeProvider(_responder(case["script"], inp["card"], case["usage"]), paid=True)
    providers.set_provider("deepinfra", fake)
    calls: list[dict[str, Any]] = []
    real_complete = gateway.complete

    def complete(role: str, messages: Any, **kw: Any) -> Any:
        before_rows = len(ledger.entries())
        before_calls = len(fake.calls)
        waits: list[float] = []
        gateway.SLEEP = waits.append
        res = real_complete(role, messages, **kw)
        result = dict(res.__dict__)
        result["must_stop"] = res.must_stop
        est = inference_oracle._estimate(role, messages, kw)
        sent = [{"model": c["model"], "json_mode": c["json_mode"], "max_output_tokens": c["max_output_tokens"],
                 "extra_body": c["extra_body"]} for c in fake.calls[before_calls:]]  # fmt: skip
        calls.append({"entity_id": kw.get("entity_id"), "run_id": kw.get("run_id"), "purpose": kw.get("purpose"),
                      "run_cap_usd": kw.get("run_cap_usd"), "result": result, "est": est, "waits": waits,
                      "calls": sent, "rows": ledger.entries()[before_rows:]})  # fmt: skip
        what = case["after"].get(str(len(calls) - 1))
        eid = str(kw.get("entity_id"))[len("news:") :]
        if what == "remove":
            doc[0]["events"].pop(eid, None)
        elif what == "carded":
            doc[0]["events"][eid]["card"] = dict(CONCURRENT_CARD)
        elif what == "headline":
            doc[0]["events"][eid]["headline"] += HEADLINE_SUFFIX
        return res

    gateway.complete = complete  # type: ignore[assignment]
    try:
        made, usd = news._make_cards()
    finally:
        gateway.complete = real_complete  # type: ignore[assignment]
    end = doc[0]["events"]
    changed = {k: end.get(k) for k in {**world["events"], **end} if end.get(k) != world["events"].get(k)}
    return {"name": case["name"], "made": made, "usd": usd, "calls": calls, "saves": saves,
            "changed": dict(sorted(changed.items())), "ledger": ledger.entries()}  # fmt: skip


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and Path(data_dir).name != "project-zero-data", "PZ_DATA must be a scratch folder"
    assert not os.environ.get("SUPABASE_DB_URL"), "the oracle never sees the database"
    assert not any(os.environ.get(k) for k in inference_oracle.KEY_ENVS), "no provider key in the oracle"
    os.environ.setdefault("PZ_TESTING", "1")
    os.environ["PZ_AI_PAID"] = "on"
    inp = json.loads(src.read_bytes().decode("utf-8"))
    inference_oracle._freeze()
    from projectzero.domain import taste  # the OLD package
    from projectzero.services import news

    clock = datetime.fromisoformat(inp["clock"])
    inference_oracle.NOW.append(clock)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> FixedDateTime:  # type: ignore[override]
            return cls(clock.year, clock.month, clock.day, clock.hour, clock.minute, clock.second)

    news.datetime = FixedDateTime  # type: ignore[attr-defined]
    old_system = news.SYSTEM
    news.SYSTEM = inp["system"]  # type: ignore[attr-defined]
    old_root = Path(taste.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()  # fmt: skip
    cases = [run_case(inp, c, Path(data_dir)) for c in inp["cases"]]
    constants = {"CARD_RUN_CAP_USD": news.CARD_RUN_CAP_USD, "MAX_CARDS_PER_RUN": news.MAX_CARDS_PER_RUN}
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "mode": "news-cards", "constants": constants}
    out = {"meta": meta, "old_system": old_system, "cases": cases}
    dst.write_bytes(json.dumps(out, ensure_ascii=False, default=str).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

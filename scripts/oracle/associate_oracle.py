"""ORACLE: the OLD PZ Associate (review 033a), ``services/associate`` (``engine.ask``, ``tools.run``, ``knowledge``, the
store and the draft route), over invented worlds with a FIXED clock and a SCRIPTED model. Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/associate_oracle.py IN.json OUT.json

IN = {docs_dir, knowledge: {queries, offline}, worlds: [{name, clock, tools, raw: {cases, analysis}, cases, store}]};
the data folder of world ``name`` is ``PZ_DATA/<name>`` (written by the parity script), the documentation folder is
``docs_dir`` (``PZ_DOCS_DIR``: the ten documents as the new index reads them, revision 2's "old index restricted to
the same passages"). Per world, in order:

* ``storage`` is pointed at its folder, the clock is frozen at ``clock`` (naive Berlin wall time) in every loaded old
  ``projectzero`` module whose ``date`` / ``datetime`` is the standard class, and ``uuid.uuid4`` counts from 1 (the
  conversation and draft ids are deterministic);
* ``raw``: the old read handlers the tools call (``GET /api/pipeline``, ``/api/inbox``, ``/api/today``, the Radar
  view, ``/api/events``, ``case_prep.view(slug)``, ``GET /api/analysis``), once each, after one warm-up pipeline read;
* ``tools``: ``tools.run(name, args)`` for each listed call (``{ok}``, ``{rejected}`` or ``{raises}``);
* ``cases``: each turn runs ``engine.ask(message, conversation_id, context)`` with ``gateway.complete`` replaced by a
  SCRIPTED fake that plays the turn's model outputs in order (``{reply}`` a JSON value, ``{text}`` raw text, ``{fail,
  error}`` a failed call; past the end ``{"answer": "done"}``) and records every call it received (role, purpose,
  the JSON switch, the output cap and the messages); every ``tools.run`` the turn makes is recorded too. ``break:
  ["pipeline"]`` makes the old ``tools._pipeline`` raise ``OSError`` for that turn (an unavailable source);
* ``store`` (when set): the draft route's confirmation and caps, the profile, the conversation caps and eviction.

Stubbed, as the new side decides (the Today port's own declared items, review 030a): ``today._native_actions`` /
``_scout00_actions`` answer ``[]``, ``_ready_proposals`` ``[]``, ``scheduler.failing_jobs`` raises,
``source_network.load`` answers no candidate. Case preparation is off (``PZ_CASE_PREP=0``).

Writes: the Associate's own folder (``associate/``) is written as before. The pipeline's IMQ save is held IN MEMORY
and read back (``saves``, as the Today oracle); the Radar milestone credit (``credit_radar_milestones``) is held and
recorded (``held``): the new Associate never writes a PZ record (decision f), and the old view was composed before
it. Every other write raises and is recorded (``blocked``); the folder outside ``associate/`` is checked unchanged
(``changed``). PZ_DATA must not be (or be inside) ``project-zero-data``; ``SUPABASE_DB_URL`` must be unset.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import types
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

NOW: list[datetime] = []
BLOCKED: list[str] = []
HELD: list[str] = []
SAVED: dict[str, Any] = {}
SCRIPT: list[dict[str, Any]] = []
CALLS: list[dict[str, Any]] = []
RUNS: list[dict[str, Any]] = []
UUIDS: list[int] = [0]
ROOT: list[Path] = []


class FixedDate(date):
    @classmethod
    def today(cls) -> FixedDate:  # type: ignore[override]
        n = NOW[-1]
        return cls(n.year, n.month, n.day)


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> FixedDateTime:  # type: ignore[override]
        n = NOW[-1]  # naive wall time, whatever zone is asked (the old store stamps it with a Z)
        return cls(n.year, n.month, n.day, n.hour, n.minute, n.second)


def _imports() -> None:
    from projectzero.domain import analyst, connectors, imq, people, taste  # noqa: F401
    from projectzero.domain import events as evmod  # noqa: F401
    from projectzero.services import case_prep, compressor, scheduler, source_network, today  # noqa: F401
    from projectzero.services import pipeline as pipeline_svc  # noqa: F401
    from projectzero.services.associate import engine, knowledge, store, tools  # noqa: F401

    from projectzero import compat, storage  # noqa: F401
    from projectzero.api import errors  # noqa: F401
    from projectzero.api.routers import analysis, associate, discovery, events, pipeline, triage  # noqa: F401


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


def _uuid4() -> uuid.UUID:
    UUIDS[0] += 1
    return uuid.UUID(int=UUIDS[0] << 88)  # distinct in hex[:10] (a draft id) and hex[:12] (a conversation id)


def _own(target: Any) -> bool:
    from projectzero import storage

    path = storage._resolve(target).resolve()
    return (ROOT[-1] / "associate").resolve() in path.parents


def _block() -> None:
    from projectzero import storage

    for name in ("save_json", "write_text", "append_line"):
        real = getattr(storage, name)

        def guarded(target: Any, *a: Any, _name: str = name, _real: Any = real, **k: Any) -> Any:
            if _own(target):
                return _real(target, *a, **k)  # the Associate's own folder
            BLOCKED.append(f"{_name}:{Path(str(target)).name}")
            raise RuntimeError(f"the Associate oracle blocks {_name}")

        setattr(storage, name, guarded)


def _stub() -> None:
    from projectzero.services import pipeline as pipeline_svc
    from projectzero.services import scheduler, source_network, today

    today._native_actions = lambda: []  # type: ignore[attr-defined]
    today._scout00_actions = lambda: []  # type: ignore[attr-defined]
    today._ready_proposals = lambda entry: []  # type: ignore[attr-defined]

    def failing_jobs() -> Any:
        raise RuntimeError("no scheduler in the new system")

    scheduler.failing_jobs = failing_jobs  # type: ignore[attr-defined]
    source_network.load = lambda: {"candidates": []}  # type: ignore[attr-defined]
    real_load = pipeline_svc.load_signals_doc

    def load_signals_doc() -> Any:
        return copy.deepcopy(SAVED["doc"]) if "doc" in SAVED else real_load()

    def save_signals_doc(d: Any) -> None:  # the IMQ save, in memory (as the old code would have written it)
        stripped = {**{k: v for k, v in d.items() if k not in ("week", "signals")}, "week": d.get("week", ""),
                    "signals": [{k: v for k, v in e.items() if k not in pipeline_svc.COMPUTED_FIELDS}
                                if isinstance(e, dict) else e for e in d.get("signals", [])]}  # fmt: skip
        SAVED["doc"] = json.loads(json.dumps(stripped, ensure_ascii=False))
        SAVED["count"] = SAVED.get("count", 0) + 1

    def credit_radar_milestones(composed: Any) -> int:  # held: the Associate writes no PZ record (decision f)
        HELD.append("credit_radar_milestones")
        return 0

    pipeline_svc.load_signals_doc = load_signals_doc  # type: ignore[assignment]
    pipeline_svc.save_signals_doc = save_signals_doc  # type: ignore[assignment]
    pipeline_svc.credit_radar_milestones = credit_radar_milestones  # type: ignore[assignment]
    uuid.uuid4 = _uuid4  # type: ignore[assignment]


def play(out: dict[str, Any], validate: Any) -> types.SimpleNamespace:
    """One scripted model outcome as the old gateway's ``Result`` (the parity's new side plays the same rules)."""
    usd, model = float(out.get("usd", 0.0004)), str(out.get("model", "assoc-model"))
    if "fail" in out:
        return types.SimpleNamespace(ok=False, data=None, text="", usd=usd, model=model, error=out.get("error", ""),
                                     error_kind=out["fail"])  # fmt: skip
    if "text" in out:
        try:
            data = json.loads(out["text"])
        except ValueError:
            return types.SimpleNamespace(ok=False, data=None, text=out["text"], usd=usd, model=model,
                                         error="the model reply was not JSON", error_kind="invalid_output")  # fmt: skip
    else:
        data = out["reply"]
    try:
        data = validate(data) if validate else data
    except ValueError as exc:
        return types.SimpleNamespace(ok=False, data=None, text="", usd=usd, model=model, error=f"invalid reply: {exc}",
                                     error_kind="invalid_output")  # fmt: skip
    return types.SimpleNamespace(ok=True, data=data, text=json.dumps(data), usd=usd, model=model, error="",
                                 error_kind="")  # fmt: skip


def fake_complete(role: str, messages: Any, *, purpose: str, json_mode: bool = True, validate: Any = None,
                  max_output_tokens: int | None = None, entity_id: Any = None, **kw: Any) -> Any:  # fmt: skip
    CALLS.append({"role": role, "purpose": purpose, "json_mode": json_mode, "max_output_tokens": max_output_tokens,
                  "entity_id": entity_id, "extra": sorted(kw), "messages": copy.deepcopy(messages)})  # fmt: skip
    out = SCRIPT.pop(0) if SCRIPT else {"reply": {"answer": "done"}}
    if out.get("model") == "@role":  # the old gateway names the role's model before it refuses (the real world)
        from projectzero.inference import config as icfg

        out = {**out, "model": str(((icfg.load().get("roles") or {}).get(role) or {}).get("model") or "")}
    return play(out, validate)


def _digest(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*"))
            if p.is_file() and p.relative_to(folder).parts[0] != "associate"}  # fmt: skip


def _call(fn: Any) -> dict[str, Any]:
    try:
        return {"ok": fn()}
    except Exception as exc:  # the old route would have answered 500
        return {"raises": f"{type(exc).__name__}: {exc}"}


def _raw(world: dict[str, Any]) -> dict[str, Any]:
    from projectzero.services import case_prep
    from projectzero.services import pipeline as pipeline_svc

    from projectzero.api.routers import analysis, discovery, events, pipeline, triage

    return {
        "pipeline": _call(pipeline.get_pipeline),
        "inbox": _call(discovery.inbox),
        "today": _call(triage.today),
        "radar": _call(pipeline_svc.radar_view),
        "events": _call(events.list_events),
        "cases": {s: _call(lambda s=s: case_prep.view(s)) for s in world["raw"]["cases"]},
        "analysis": {i: _call(lambda i=i: analysis.analysis(i)) for i in world["raw"]["analysis"]},
    }


def _run_tool(name: str, args: Any) -> dict[str, Any]:
    from projectzero.services.associate import tools

    try:
        return {"ok": tools.run(name, args)}
    except tools.ToolRejected as exc:
        return {"rejected": str(exc)}
    except Exception as exc:
        return {"raises": f"{type(exc).__name__}: {exc}"}


def _recording_run() -> None:
    from projectzero.services.associate import tools

    real = tools.run

    def run(name: str, args: Any) -> dict[str, Any]:
        try:
            out = real(name, args)
        except tools.ToolRejected as exc:
            RUNS.append({"name": name, "args": copy.deepcopy(args), "rejected": str(exc)})
            raise
        RUNS.append({"name": name, "args": copy.deepcopy(args), "ok": copy.deepcopy(out)})
        return out

    tools.run = run  # type: ignore[assignment]


def _turn(turn: dict[str, Any], conversation_id: str | None) -> dict[str, Any]:
    from projectzero.services.associate import engine, tools

    SCRIPT[:] = copy.deepcopy(turn["script"])
    CALLS.clear()
    RUNS.clear()
    real_pipeline = tools._pipeline
    if "pipeline" in turn.get("break", []):

        def boom() -> Any:
            raise OSError("disk unavailable")

        tools._pipeline = boom  # type: ignore[assignment]
    try:
        answer = _call(lambda: engine.ask(turn["message"], conversation_id, turn.get("context")))
    finally:
        tools._pipeline = real_pipeline  # type: ignore[assignment]
    return {"answer": answer, "calls": copy.deepcopy(CALLS), "runs": copy.deepcopy(RUNS), "left": len(SCRIPT)}


def _cases(world: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for case in world["cases"]:
        turns: list[dict[str, Any]] = []
        cid: str | None = None
        for turn in case["turns"]:
            if turn.get("conversation") != "previous":
                cid = None
            got = _turn(turn, cid)
            cid = ((got["answer"].get("ok") or {}).get("conversation") or {}).get("id")
            turns.append(got)
        out.append({"name": case["name"], "turns": turns})
    return out


def _route(fn: Any) -> dict[str, Any]:
    from projectzero.api.errors import ApiError

    try:
        return {"ok": fn()}
    except ApiError as exc:
        return {"error": str(exc), "status": getattr(exc, "status_code", None)}
    except ValueError as exc:
        return {"value_error": str(exc)}


def _store() -> dict[str, Any]:
    from projectzero.services.associate import store

    from projectzero.api.routers import associate as r

    long_title = "T" * 150
    bodies = [
        {"title": "Call prep", "body": "Q1"},
        {"title": "Call prep", "body": "Q1", "confirm": False},
        {"title": "Call prep", "body": "Q1", "confirm": "true"},
        {"title": "Call prep", "body": "   ", "confirm": True},
        {"title": "Call prep", "body": "  Q1 and Q2  ", "confirm": True, "ref": {"kind": "company", "id": "x"}},
        {"title": long_title, "body": "B" * 20500, "confirm": True, "ref": "not-a-dict", "conversation_id": "c-1"},
        {"body": "No title", "confirm": True, "conversation_id": 7},
        {"title": "", "body": "Empty title", "confirm": True},
    ]
    drafts = [_route(lambda b=b: r.associate_draft(b)) for b in bodies]
    listing = r.associate_drafts()
    deleted = [r.associate_draft_delete({"id": (drafts[4].get("ok") or {}).get("draft", {}).get("id")}),
               r.associate_draft_delete({"id": "d-nope"})]  # fmt: skip
    for i in range(store.MAX_DRAFTS + 5):
        store.save_draft(f"d{i}", f"body {i}", None, None)
    kept = store.list_drafts()
    profile_before = r.associate_profile()
    saved = r.associate_profile_save({"interests": "  deep tech, defence  ", "routines": "R" * 1300, "boundaries": 42,
                                      "unknown": "dropped", "sourcing_priorities": None})  # fmt: skip
    profile_after = r.associate_profile()
    convs = [store.new_conversation(f"c{i}")["id"] for i in range(store.MAX_CONVERSATIONS + 3)]
    listed = [c["id"] for c in store.list_conversations()]
    conv = store.load_conversation(convs[-1]) or {}
    conv["messages"] = [{"role": "user", "text": f"m{i}", "at": "x"} for i in range(store.MAX_TURNS + 5)]
    store.save_conversation(conv)
    trimmed = store.load_conversation(convs[-1]) or {}
    titles = [store.new_conversation(t)["title"] for t in ("", "   padded   ", "x" * 100)]
    bad_ids = [_route(lambda c=c: store.load_conversation(c)) for c in ("../../etc", "c-XYZ", "c-0123456789ab", "")]
    return {"drafts": drafts, "listing": listing, "deleted": deleted, "kept": [len(kept), kept[0], kept[-1]],
            "profile_before": profile_before, "saved": saved, "profile_after": profile_after, "created": convs,
            "listed": listed,
            "trimmed": [len(trimmed.get("messages", [])), trimmed["messages"][0], trimmed["messages"][-1]],
            "titles": titles, "bad_ids": bad_ids}  # fmt: skip


def run_world(world: dict[str, Any], root: Path) -> dict[str, Any]:
    from projectzero.services import case_prep

    from projectzero import compat, storage

    folder = root / world["name"]
    storage.configure(folder)
    ROOT.append(folder)
    NOW.append(datetime.fromisoformat(world["clock"]))
    _freeze()
    UUIDS[0] = 0
    SAVED.clear()
    BLOCKED.clear()
    HELD.clear()
    compat.SKIPPED.clear()
    case_prep._queue.clear()
    before = _digest(folder)
    from projectzero.api.routers import pipeline

    _call(pipeline.get_pipeline)  # warm-up: the IMQ save (held in memory) happens before anything is recorded
    raw = _raw(world)
    tool_results = [{"name": n, "args": a, **_run_tool(n, copy.deepcopy(a))} for n, a in world["tools"]]
    cases = _cases(world)
    store_out = _store() if world.get("store") else None
    after = _digest(folder)
    changed = sorted(k for k in {**before, **after} if before.get(k) != after.get(k))
    return {"name": world["name"], "raw": raw, "tools": tool_results, "cases": cases, "store": store_out,
            "saves": SAVED.get("count", 0), "held": sorted(set(HELD)), "blocked": list(BLOCKED), "changed": changed,
            "skipped": compat.skipped()}  # fmt: skip


def knowledge_part(spec: dict[str, Any]) -> dict[str, Any]:
    from projectzero.services.associate import engine, knowledge, tools

    knowledge.reset()
    ix = knowledge.index()
    return {
        "index": {
            "sections": [[s.doc, s.doc_title, s.heading, s.text] for s in ix["sections"]],
            "missing": ix["missing"],
        },
        "search": [{"query": q, "k": k, "result": knowledge.search(q, k=k)} for q, k in spec["queries"]],
        "offline": [{"message": m, "reason": r, "result": engine._offline(m, r, None)} for m, r in spec["offline"]],
        "tables": {
            "DOCS": knowledge.DOCS,
            "PAGES": knowledge.PAGES,
            "catalogue": tools.catalogue(),
            "OPEN_PREFIXES": list(engine.OPEN_PREFIXES),
            "TOOLS": list(tools.TOOLS),
        },
    }


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and Path(data_dir).name != "project-zero-data", "PZ_DATA must be a scratch folder"
    assert "project-zero-data" not in Path(data_dir).resolve().parts, "PZ_DATA must be a scratch folder"
    assert not os.environ.get("SUPABASE_DB_URL"), "the oracle never sees the database"
    os.environ.setdefault("PZ_TESTING", "1")
    os.environ["PZ_CASE_PREP"] = "0"
    inp = json.loads(src.read_bytes().decode("utf-8"))
    os.environ["PZ_DOCS_DIR"] = inp["docs_dir"]
    NOW.append(datetime.fromisoformat(inp["worlds"][0]["clock"]))
    _imports()
    frozen = _freeze()
    _block()
    _stub()
    from projectzero.inference import gateway

    gateway.complete = fake_complete  # type: ignore[assignment]  # no model, no network, no money
    _recording_run()
    from projectzero.services.associate import engine  # the OLD package

    old_root = Path(engine.__file__).resolve().parents[5]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()  # fmt: skip
    knowledge = knowledge_part(inp["knowledge"])
    worlds = [run_world(w, Path(data_dir)) for w in inp["worlds"]]
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "mode": "associate", "frozen": frozen}
    out = {"meta": meta, "knowledge": knowledge, "worlds": worlds}
    dst.write_bytes(json.dumps(out, ensure_ascii=False, default=str).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

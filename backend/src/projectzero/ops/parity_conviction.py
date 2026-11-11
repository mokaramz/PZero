"""Conviction parity: the port against the OLD code as oracle, with a FIXED clock on both sides (review 011).

    python -m projectzero.ops.parity_conviction goldens   # (re)generate tests/fixtures/golden_v1/oracle_conviction.json
    python -m projectzero.ops.parity_conviction real      # the real snapshot: reads (2 clocks) + a write replay

The oracle (``scripts/oracle/conviction_oracle.py``) runs in the OLD repository's interpreter and package, with
``PZ_DATA`` pointed at a temp folder: empty for the rule goldens, or a byte-exact copy of the captured snapshot
(``LegacySnapshot``) for ``real`` — the old data folder itself is only ever read.

``real`` imports the SAME snapshot into a throw-away scratch schema with the production importer, then
1. reads: the old ``pipeline()`` (``imq.persist`` disabled) and ``_meta()`` against ``GET /api/conviction/pipeline``
   and ``/meta``, at each clock in ``REAL_CLOCKS``: every signal (same order), every field;
2. writes: one script of saves / status changes / Keeps replayed on the old ``save_entry`` / ``set_status`` and on the
   new endpoints: per step the HTTP code and error body, every stored record, the probed candidates' decisions and
   the feedback ledger decisions; finally the whole view again.
It prints AGGREGATES and difference PATHS only; real records never leave the machine. Exit 1 on any difference.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from projectzero.conviction import imq, taste
from projectzero.core.paths import REPO_ROOT
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js

ORACLE = REPO_ROOT / "scripts" / "oracle" / "conviction_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_conviction.json"
CLOCK = "2026-11-11T12:00:00"
REAL_CLOCKS = ("2026-11-11T12:00:00", "2027-03-01T09:30:00")  # today, and past every 14-day / 90-day / follow-up line


# ------------------------------------------------------------------ the oracle
def run_oracle(mode: str, inp: Mapping[str, Any], files: Mapping[str, bytes] | None = None) -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-conviction-oracle-") as tmp:
        tmpdir = Path(tmp)
        data = tmpdir / "data"
        data.mkdir()
        for rel, raw in (files or {}).items():
            target = (data / rel).resolve()
            if data.resolve() not in target.parents:
                raise SystemExit(f"refusing a path outside the scratch folder: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        src, dst = tmpdir / "in.json", tmpdir / "out.json"
        src.write_text(json.dumps(inp), encoding="utf-8")
        env = {**os.environ, "PZ_DATA": str(data), "PZ_TESTING": "1", "PYTHONPATH": str(OLD_REPO / "backend" / "src")}
        env.pop("SUPABASE_DB_URL", None)  # the oracle never needs, and never sees, the database
        run = subprocess.run(
            [str(python), str(ORACLE), mode, str(src), str(dst)], env=env, capture_output=True, text=True
        )
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_text(encoding="utf-8"))
        return out


# ------------------------------------------------------------------ the synthetic corpus
def _day(clock: str, days_ago: int) -> str:
    return (datetime.fromisoformat(clock).date() - timedelta(days=days_ago)).isoformat()


def score_corpus() -> list[dict[str, Any]]:
    """Every ladder value, earliness, conflict, penalty, the verified-zeroing rule, clamps, bands and bad values."""
    base: dict[str, Any] = {"company": "Base", "scores": {"founder": 14, "venture_scale": 9, "why_now": 6, "taste": 5,
                                                          "insight": 5}}  # fmt: skip
    out: list[dict[str, Any]] = []
    ladders = {"founder": taste.FOUNDER_LADDER, "venture_scale": taste.VS_LADDER, "why_now": taste.WHYNOW_LADDER,
               "taste": taste.TASTE_LADDER, "insight": taste.INSIGHT_LADDER}  # fmt: skip
    for k, ladder in ladders.items():
        for _label, p in ladder:
            out.append(base | {"scores": base["scores"] | {k: p}})
    for k in [*taste.EARLINESS, "bogus"]:
        out.append(base | {"earliness": k})
    for c in ["none", "similar", "complementary", "clone", "potential_conflict", "unclear", None, "bogus"]:
        out.append(base | {"conflict": c})
        out.append(base | {"conflict": c, "archetype": 15})  # archetype 15 zeroes the resemblance
    for pen in [*taste.PENALTIES, "bogus"]:
        out.append(base | {"penalties": [pen]})
    out.append(base | {"penalties": list(taste.PENALTIES)})  # clamps at 0
    out.append(base | {"penalties": ["known", "known"]})
    out.append(base | {"penalties": ["consumer"], "conflict": "potential_conflict"})
    for flags in (
        {},
        {"founders": True},
        {"traction": True},
        {"funding": True},
        {"founders": True, "funding": True},
        {"founders": True, "traction": True, "funding": True},
        {"founders": False, "traction": "yes"},
    ):
        out.append(base | {"verified": flags, "earliness": "pre_seed", "scores": base["scores"] | {"insight": 5}})
    top = {"founder": 25, "venture_scale": 19, "why_now": 15, "taste": 15, "insight": 10}
    out.append({"company": "Max", "scores": top, "earliness": "pre_company", "conflict": "complementary"})  # clamp 100
    all_v = {"founders": True, "traction": True, "funding": True}
    for total in (80, 79, 65, 64, 50, 49):  # band edges, on the verified and on the provisional basis
        s = {"founder": 25, "venture_scale": 19, "why_now": 15, "taste": total - 59, "insight": 0}
        out.append({"company": f"V{total}", "scores": s, "verified": all_v})
        out.append({"company": f"P{total}", "scores": s})
    outlier: dict[str, Any] = {"company": "Out", "archetype": 15, "verified": all_v, "earliness": "pre_seed",
               "scores": {"founder": 22, "venture_scale": 17, "why_now": 12, "taste": 0, "insight": 8}}  # fmt: skip
    out.append(outlier)
    for k, low in (("founder", 21), ("venture_scale", 16), ("why_now", 11), ("insight", 7)):
        out.append(outlier | {"scores": outlier["scores"] | {k: low}})
    out.append(outlier | {"earliness": "seed"})
    out.append(outlier | {"verified": {"traction": True, "funding": True}})
    out.append(outlier | {"archetype": 14})
    for t in [*taste.FUNDRAISING_TIMING, "bogus"]:
        out.append(base | {"fundraising_timing": t})
    for bad in ({"founder": ""}, {"founder": "12"}, {"founder": 12.7}, {"founder": True}, {"venture_scale": None},
                {"insight": "x"}):  # fmt: skip
        out.append(base | {"scores": base["scores"] | bad})
    out += [{"company": "Empty"}, {"company": "NoneScores", "scores": None, "verified": None},
            {"company": "ListScores", "scores": [1, 2]}, {"company": "BoolArch", "archetype": True}]  # fmt: skip
    return out


def imq_corpus(clock: str) -> list[dict[str, Any]]:
    """All IMQ gates A-E, the conflict gate (potential_conflict AND unclear) and the 90-day window at a fixed clock."""
    people = [
        {"id": "p-ada", "name": "Ada Lovelace", "identity_status": "resolved"},
        {"id": "p-bob", "name": "Bob Builder", "identity_status": "needs identity resolution"},
        {"id": "p-cy", "name": "Cyrille Dupont", "aliases": ["Cy Dupont"], "identity_status": "verified by operator"},
        {"id": "p-dee", "name": "Dee Default", "provenance": "user_provided"},
        {"id": "p-eve", "name": "Eve Elsewhere"},
        {"id": "p-ada2", "name": "Ada Lovelace", "identity_status": "needs identity resolution"},  # the FIRST wins
    ]
    trig = {"kind": "fundraising", "date": _day(clock, 10), "url": "https://news.example.com/a", "fact": "raising",
            "by": "operator"}  # fmt: skip
    q: dict[str, Any] = {
        "company": "Qualified Co", "archetype": 3, "earliness": "pre_company", "conflict": "none",
        "scores": {"founder": 25, "venture_scale": 19, "why_now": 15, "taste": 15, "insight": 10},
        "verified": {"founders": True, "traction": True, "funding": True},
        "founders": [{"name": "Ada Lovelace"}], "imq_trigger": trig, "fundraising_timing": "0_6m",
    }  # fmt: skip

    def case(entry: dict[str, Any], *, research: Any = None, contra: Any = None, plist: Any = None) -> dict[str, Any]:
        return {"entry": entry, "people": people if plist is None else plist, "research": research,
                "contradictions": contra}  # fmt: skip

    fact = {"confirmed": True, "activity_date": _day(clock, 5), "source_url": "https://co.example.com", "claim": "x"}
    out = [
        case(q),
        case(q | {"conflict": "potential_conflict"}), case(q | {"conflict": "unclear"}),
        case(q | {"conflict": "similar"}), case(q | {"conflict": "complementary"}),
        # A
        case(q | {"verified": {"founders": True, "funding": True}}),
        case(q | {"scores": q["scores"] | {"taste": 5}}),
        case(q | {"archetype": 15, "scores": {"founder": 22, "venture_scale": 17, "why_now": 12, "taste": 0,
                                               "insight": 8}, "earliness": "pre_seed"}),  # outlier route
        # B
        case(q | {"scores": q["scores"] | {"founder": 14}}), case(q | {"scores": q["scores"] | {"founder": 20}}),
        case(q | {"verified": {"traction": True, "funding": True}}),
        case(q | {"scores": q["scores"] | {"venture_scale": 9}}), case(q | {"scores": q["scores"] | {"venture_scale": 14}}),
        # C
        case(q | {"founders": []}), case(q | {"founders": ["Ada Lovelace", "", None, {"name": " "}]}),
        case(q | {"founders": [{"name": "Bob Builder"}]}), case(q | {"founders": [{"name": "Nobody Known"}]}),
        case(q | {"founders": [{"name": "Cy Dupont"}]}), case(q | {"founders": [{"name": "Dee Default"}]}),
        case(q | {"founders": [{"name": "Eve Elsewhere"}]}), case(q | {"founders": [{"name": "ADA  lovelace!"}]}),
        case(q | {"founders": [{"name": "Ada Lovelace"}, {"name": "Bob Builder"}]}),
        case(q, contra=[{"state": "CONTRADICTION", "text": "deck says 10 customers, call says 2"}]),
        case(q, contra=[{"state": "contradiction", "claim": "lowercase state counts"}]),
        case(q, contra=[{"state": "CONTRADICTION", "text": "resolved", "resolved": True}, {"state": "SUPPORTED"}]),
        case(q, contra=[{"state": "CONTRADICTION", "text": "y" * 200}]),
        # E: the 90-day window at the fixed clock
        case(q | {"imq_trigger": trig | {"date": _day(clock, 90)}}),
        case(q | {"imq_trigger": trig | {"date": _day(clock, 91)}}),
        case(q | {"imq_trigger": trig | {"date": _day(clock, 0)}}),
        case(q | {"imq_trigger": trig | {"date": _day(clock, -1)}}),  # a future date: not fresh, reads as stale
        case(q | {"imq_trigger": trig | {"date": "not a date"}}),
        case(q | {"imq_trigger": trig | {"by": "scout"}}), case(q | {"imq_trigger": trig | {"url": ""}}),
        case(q | {"imq_trigger": trig | {"kind": "window"}}), case(q | {"imq_trigger": trig | {"kind": "odd"}}),
        case(q | {"imq_trigger": {}}), case(q | {"imq_trigger": None, "fundraising_timing": "raising_now"}),
        case(q | {"imq_trigger": None}, research={"verified_facts": {"recent_activity": fact}}),
        case(q | {"imq_trigger": None}, research={"verified_facts": {"funding": fact | {"activity_date": _day(clock, 91)}}}),
        case(q | {"imq_trigger": None}, research={"verified_facts": {"funding": fact | {"confirmed": False}}}),
        case(q | {"imq_trigger": None}, research={"verified_facts": {"funding": fact | {"source_url": "ftp://x"}}}),
        case(q | {"imq_trigger": trig | {"date": _day(clock, 120)}},
             research={"verified_facts": {"recent_activity": fact, "funding": fact | {"activity_date": _day(clock, 2)}}}),
        # STALE: once qualified, a lost condition is STALE; a conflict is CONFLICT GATED
        case(q | {"imq_trigger": trig | {"date": _day(clock, 91)}, "imq": {"state": imq.QUALIFIED, "qualified_at": "2026-09-01 10:00"}}),
        case(q | {"conflict": "unclear", "imq": {"state": imq.QUALIFIED, "qualified_at": "2026-09-01 10:00"}}),
        case(q | {"imq": {"state": "IMQ — STALE", "qualified_at": "2026-09-01 10:00"}}),
        case({"company": "Bare"}), case({"company": "Bad", "scores": {"founder": "x"}}),
    ]  # fmt: skip
    return out


def persist_corpus(clock: str) -> list[dict[str, Any]]:
    cases = imq_corpus(clock)
    q = cases[0]
    stale_trig = q["entry"]["imq_trigger"] | {"date": _day(clock, 91)}
    snap = {"state": imq.QUALIFIED, "qualified_at": "2026-09-01 10:00", "history": [{"on": "2026-09-01 10:00",
            "to": imq.QUALIFIED}]}  # fmt: skip
    return [
        cases[0],  # turns on: snapshot written
        q | {"entry": q["entry"] | {"imq": snap}},  # already qualified: nothing written
        q | {"entry": q["entry"] | {"imq_trigger": stale_trig, "imq": snap}},  # the 90-day expiry: STALE stamped
        q | {"entry": q["entry"] | {"imq_trigger": stale_trig, "imq": snap | {"state": "IMQ — STALE"}}},  # once only
        q | {"entry": q["entry"] | {"conflict": "potential_conflict", "imq": snap}},  # CONFLICT GATED stamped
        q | {"entry": q["entry"] | {"imq": snap | {"state": "IMQ — STALE", "stale_since": "2026-10-01 09:00"}}},  # back
        cases[13],  # never qualified: nothing written
    ]


def days_corpus(clock: str) -> list[Any]:
    return [
        "",
        None,
        _day(clock, 10),
        _day(clock, 0),
        _day(clock, -30),
        f"{_day(clock, 3)}T23:59:00",
        "garbage",
        20261101,
    ]


def rules_input(clock: str = CLOCK) -> dict[str, Any]:
    return {"clock": clock, "score": score_corpus(), "evaluate": imq_corpus(clock), "persist": persist_corpus(clock),
            "days": days_corpus(clock)}  # fmt: skip


def _try(fn: Any) -> Any:
    try:
        return {"ok": fn()}
    except Exception as exc:
        return {"raises": type(exc).__name__}


def new_rules(inp: Mapping[str, Any]) -> dict[str, Any]:
    import copy

    now = datetime.fromisoformat(inp["clock"])
    today: date = now.date()
    out: dict[str, Any] = {"score": [], "evaluate": [], "persist": [], "days": []}
    for e in inp["score"]:
        out["score"].append(_try(lambda e=e: taste.score(copy.deepcopy(e))))
    for c in inp["evaluate"]:
        out["evaluate"].append(_try(lambda c=c: imq.evaluate(copy.deepcopy(c["entry"]), c["people"], c["research"],
                                                             c["contradictions"], today=today)))  # fmt: skip
    for c in inp["persist"]:
        entry = copy.deepcopy(c["entry"])
        ev = imq.evaluate(entry, c["people"], c["research"], c["contradictions"], today=today)
        changed = imq.persist(entry, ev, now=now)
        out["persist"].append({"changed": changed, "imq": entry.get("imq"), "state": ev["state"]})
    for iso in inp["days"]:
        out["days"].append(taste.days_since(iso, today))
    out["api_meta"] = taste.meta()
    result: dict[str, Any] = js(out)
    return result


def compare_goldens(golden: Mapping[str, Any]) -> list[str]:
    new = new_rules(golden["input"])
    return diff(golden["expected"], new)


def write_goldens() -> int:
    inp = rules_input()
    oracle = run_oracle("rules", inp)
    meta = oracle.pop("meta")
    golden = {"provenance": meta, "input": inp, "expected": oracle}
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    problems = compare_goldens(json.loads(GOLDEN.read_text(encoding="utf-8")))
    raises = sum(1 for r in oracle["score"] + oracle["evaluate"] if "raises" in r)
    states: dict[str, int] = {}
    for r in oracle["evaluate"]:
        if "ok" in r:
            states[r["ok"]["state"]] = states.get(r["ok"]["state"], 0) + 1
    print(f"conviction goldens written: {len(oracle['score'])} score, {len(oracle['evaluate'])} evaluate "
          f"(states {states}), {len(oracle['persist'])} persist, {len(oracle['days'])} days; {raises} raise; "
          f"provenance {meta['old_revision'][:7]} dirty={meta['old_dirty']}; new code differences: {len(problems)}")  # fmt: skip
    for p in problems[:40]:
        print("  DIFF", p)
    return 1 if problems else 0


# ------------------------------------------------------------------ the real snapshot
def compare_view(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[str]:
    """Same signals in the same order (by slug), every field; and the top-level fields."""
    out: list[str] = []
    old_sig, new_sig = old.get("signals") or [], new.get("signals") or []
    if [s.get("slug") for s in old_sig] != [s.get("slug") for s in new_sig]:
        out.append("/signals: slug order differs")
    for o, n in zip(old_sig, new_sig, strict=False):
        out += [f"/signals/{o.get('slug')}{d.split(':')[0]}" for d in diff(js(o), js(n))]
    for k in sorted(set(old) | set(new)):
        if k != "signals":
            out += [f"/{k}{d.split(':')[0]}" for d in diff(js(old.get(k)), js(new.get(k)))]
    return out


def pick_probes(inbox: Mapping[str, Any], existing: set[str]) -> dict[str, dict[str, Any]]:
    """Real inbox records for the write replay: an undecided scanned lead to Keep, a lead on watch for the duplicate
    Keep, and a rejected lead with a unique name for the name-matched provenance of a manual add."""
    from projectzero.dealflow.ranking.names import norm_company, slug

    recs = [c for c in inbox.get("candidates", []) if isinstance(c, dict) and c.get("id") and c.get("name")]
    names: dict[str, int] = {}
    for c in recs:
        names[norm_company(c["name"])] = names.get(norm_company(c["name"]), 0) + 1

    def first(pred: Any) -> dict[str, Any]:
        return next(
            c for c in recs if pred(c) and slug(c["name"]) not in existing and names[norm_company(c["name"])] == 1
        )

    return {
        "keep": first(lambda c: c.get("decision") == "new" and c.get("source_id") and c.get("run_id")),
        "watch": first(lambda c: c.get("decision") == "watch"),
        "match": first(lambda c: c.get("decision") == "rejected" and c.get("source_id")),
    }


def write_steps(probes: Mapping[str, Mapping[str, Any]], names: list[str]) -> list[dict[str, Any]]:
    """``names``: the existing entries' company names, in order."""
    from projectzero.dealflow.ranking.names import slug

    keep, watch, match = probes["keep"], probes["watch"], probes["match"]
    scored = {"scores": {"founder": 20, "venture_scale": 14, "why_now": 11, "taste": 10, "insight": 5},
              "verified": {"founders": True, "traction": False, "funding": False}, "archetype": 7,
              "earliness": "pre_seed", "conflict": "none", "penalties": ["wrapper"], "fundraising_timing": "0_6m",
              "founders": ["Jane Roe — ex-Siemens", {"name": "Max Muster", "role": "CTO"}, "", None],
              "discovery_date": "2026-11-01", "one_liner": "Oracle replay", "sources": ["https://example.com/a"]}  # fmt: skip
    first, second = names[0], names[1]
    keep_body = {"company": keep["name"], "inbox_id": keep["id"], **scored}
    return [
        {"op": "save", "body": {"company": "Replay Bad", "scores": {"founder": 30}}},
        {"op": "save", "body": {"company": "Replay Bad", "scores": {"founder": "x", "insight": -1}, "verified": {"a": 1}}},
        {"op": "save", "body": {"company": "Replay Bad", "discovery_date": "2099-01-01", "status": "won", "archetype": 16}},
        {"op": "save", "body": {"company": "Replay Bad", "conflict": "maybe", "founders": 5, "discovery_date": "11/01"}},
        {"op": "save", "body": {"company": ""}},
        {"op": "save", "body": {"company": "Replay Bad", "inbox_id": "no-such-candidate"}},
        {"op": "save", "body": keep_body},  # Keep
        {"op": "save", "body": keep_body},  # the same Keep again: duplicate, nothing changes
        {"op": "save", "body": {**keep_body, "slug": slug(keep["name"])}},  # Keep through the entry: no second Keep
        {"op": "save", "body": {"company": first, "inbox_id": watch["id"], **scored}},  # duplicate Keep of a watched lead
        {"op": "status", "body": {"slug": slug(keep["name"]), "status": "contacted"}},
        {"op": "status", "body": {"slug": slug(keep["name"]), "status": "contacted"}},
        {"op": "status", "body": {"slug": slug(keep["name"]), "status": "replied"}},
        {"op": "status", "body": {"slug": slug(keep["name"]), "status": "won"}},
        {"op": "status", "body": {"slug": "no-such-company", "status": "dropped"}},
        {"op": "status", "body": {"slug": slug(second), "status": "forwarded"}},
        {"op": "save", "body": {"slug": slug(second), "company": second, "verified": {"founders": True, "funding": True}}},  # checklist
        {"op": "save", "body": {"company": match["name"], "scores": {"founder": 8}}},  # manual add, name-matched
        {"op": "save", "body": {"company": "Replay Robotics GmbH", **scored}},  # manual add
        {"op": "save", "body": {"company": "Replay Robotics"}},  # duplicate by slug
        {"op": "save", "body": {"slug": "no-such-entry"}},  # company required
    ]  # fmt: skip


def real() -> int:  # pragma: no cover - needs the hosted database and the old repository
    import secrets as _secrets

    from fastapi.testclient import TestClient
    from psycopg import sql as _sql

    from projectzero.api.app import create_app
    from projectzero.conviction.store import ConvictionStore, record_of
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import connect, transaction
    from projectzero.dealflow.ranking.service import STATUS_TO_DECISION, RankingContext
    from projectzero.ops.db_check import _scratch_sql
    from projectzero.ops.legacy.apply import apply_plan
    from projectzero.ops.legacy.plan import build_plan
    from projectzero.ops.legacy.source import LegacySnapshot

    load_dotenv()
    settings = Settings.from_env()
    snapshot = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    files = {f.path: f.raw for f in snapshot.files()}
    real_data = snapshot.json("real_data.json")
    from projectzero.dealflow.ranking.names import slug

    existing = [slug(s["company"]) for s in real_data["signals"] if isinstance(s, dict) and s.get("company")]
    existing_names = [s["company"] for s in real_data["signals"] if isinstance(s, dict) and s.get("company")]
    probes = pick_probes(snapshot.json("inbox.json"), set(existing))
    steps = write_steps(probes, existing_names)
    probe_ids = [str(p["id"]) for p in probes.values()]

    reads_old = {c: run_oracle("pipeline", {"clock": c}, files) for c in REAL_CLOCKS}
    writes_old = run_oracle("writes", {"clock": REAL_CLOCKS[0], "steps": steps, "probe_ids": probe_ids}, files)

    schema = f"pz_rehearse_{_secrets.token_hex(4)}"
    report: dict[str, Any] = {"oracle": writes_old["meta"], "signals": len(existing), "probes": len(probe_ids)}
    problems: list[str] = []
    admin = connect(settings.db_url, autocommit=True)
    try:
        admin.execute(_scratch_sql(schema).encode())
        conn = connect(settings.db_url)
        try:
            applied = apply_plan(build_plan(snapshot), schema=schema, conn=conn)
            assert applied.get("applied"), applied
        finally:
            conn.close()
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            for clock in REAL_CLOCKS:
                app.state.clock = lambda clock=clock: datetime.fromisoformat(clock)
                new = client.get("/api/conviction/pipeline").json()
                d = compare_view(reads_old[clock]["view"], new)
                report[f"read@{clock}"] = {"signals_old": len(reads_old[clock]["view"]["signals"]),
                                           "signals_new": len(new["signals"]), "differences": len(d)}  # fmt: skip
                problems += [f"read@{clock}{p}" for p in d]
                ops: dict[str, int] = {}
                for s in new["signals"]:
                    key = f"{s['op']['status']} | {s['imq_eval']['state']}"
                    ops[key] = ops.get(key, 0) + 1
                report[f"read@{clock}"]["op_and_imq_states"] = ops
                case_d: list[str] = []
                for cs, old_case in reads_old[clock]["cases"].items():
                    got = client.get("/api/conviction/case", params={"slug": cs}).json()
                    case_d += [f"/case/{cs}{p.split(':')[0]}" for p in diff(js(old_case), got)]
                report[f"case@{clock}"] = {"slugs": len(reads_old[clock]["cases"]), "differences": len(case_d)}
                problems += [f"read@{clock}{p}" for p in case_d]
                meta_d = diff(js(reads_old[clock]["api_meta"]), client.get("/api/conviction/meta").json())
                report[f"meta@{clock}"] = len(meta_d)
                problems += [f"meta@{clock}{p.split(':')[0]}" for p in meta_d]
            app.state.clock = lambda: datetime.fromisoformat(REAL_CLOCKS[0])
            step_diffs = 0
            codes: list[int] = []
            for i, (step, old) in enumerate(zip(steps, writes_old["steps"], strict=True)):
                r = client.post(f"/api/conviction/{step['op']}", json=step["body"])
                body = r.json()
                codes.append(r.status_code)
                local: list[str] = []
                if r.status_code != old["code"]:
                    local.append(f"/code {old['code']} != {r.status_code}")
                for k in ("error", "slug", "duplicate"):
                    if old["body"].get(k) != body.get(k):
                        local.append(f"/body/{k}")
                with transaction(settings.db_url) as conn:
                    store = ConvictionStore(conn, schema)
                    stored = [record_of(row) for row in store.entry_rows()]
                    ctx = RankingContext.load(conn, schema)
                    status = dict(
                        conn.execute(
                            _sql.SQL("select id, status from {}.candidates where id = any(%s)").format(
                                _sql.Identifier(schema)
                            ),
                            (probe_ids,),
                        ).fetchall()
                    )
                decisions = {pid: STATUS_TO_DECISION.get(str(status.get(pid)), None) for pid in probe_ids}
                led = (ctx.ledger or {}).get("decisions") or {}
                ledger_new = {k: {f: v for f, v in e.items() if f != "ts"} for k, e in led.items()}
                local += [f"/signals{p.split(':')[0]}" for p in diff(js(old["signals"]), js(stored))]
                local += [f"/decisions{p.split(':')[0]}" for p in diff(old["decisions"], decisions)]
                local += [f"/ledger{p.split(':')[0]}" for p in diff(js(old["ledger"]), js(ledger_new))]
                step_diffs += len(local)
                problems += [f"write[{i}]{p}" for p in local]
            report["write_steps"] = len(steps)
            report["write_codes"] = codes
            report["write_differences"] = step_diffs
            final = client.get("/api/conviction/pipeline").json()
            fd = compare_view(writes_old["view"], final)
            report["view_after_writes_differences"] = len(fd)
            problems += [f"after-writes{p}" for p in fd]
    finally:
        admin.execute(_sql.SQL("drop schema if exists {} cascade").format(_sql.Identifier(schema)))
        admin.close()
    report["differences"] = len(problems)
    print(json.dumps(report, indent=2))
    for p in problems[:60]:
        print("  DIFF", p)
    print("CONVICTION PARITY PASSED" if not problems else "CONVICTION PARITY FAILED")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["goldens"]:
        return write_goldens()
    if argv[1:] == ["real"]:
        return real()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

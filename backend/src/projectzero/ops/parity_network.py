"""Network people parity: the port against the OLD code as oracle, with a FIXED clock on both sides (review 013).

    python -m projectzero.ops.parity_network goldens   # (re)generate tests/fixtures/golden_v1/oracle_network.json
    python -m projectzero.ops.parity_network real      # the real snapshot: reads (2 clocks) + a write replay

The oracle (``scripts/oracle/network_oracle.py``) runs in the OLD repository's interpreter and package, with
``PZ_DATA`` pointed at a temp folder: empty for the goldens (each synthetic set is written as people.json), or a
byte-exact copy of the captured snapshot (``LegacySnapshot``) for ``real`` — the old data folder is only ever read.

``goldens``: small synthetic people sets (synthetic names only) at two clocks: missing / malformed
``next_action_date`` and ``last_interaction``, the exact due boundary (the date == today), equal sort keys, link
quirks, and a graph with a cycle, a shared descendant and a path crossing the depth limit; plus the old tables and
``_slug``.

``real`` imports the SAME snapshot into a throw-away scratch schema with the production importer, then
1. reads: the old ``listing()`` / ``talent_tree()`` / watchlist against ``GET /api/network/people`` / ``/graph`` /
   ``/watchlist`` at each clock in ``REAL_CLOCKS``: every person, every field, the exact id sequence;
2. writes: one script of adds / edits / follow-ups / the ritual / signal logs replayed on the old ``upsert`` /
   ``add_talented`` / ``watch_log`` and on the new endpoints. The parity segment must match exactly (codes, bodies,
   every stored person, then the three views). The decision segment that follows differs ONLY where decisions (a) /
   (b) (and the deferred Founder Radar path) say so, and each difference is asserted explicitly.
It prints AGGREGATES and difference PATHS only; real records never leave the machine. Exit 1 on any difference.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from projectzero.core.paths import REPO_ROOT
from projectzero.network import edits, view
from projectzero.network.people import slug
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js

ORACLE = REPO_ROOT / "scripts" / "oracle" / "network_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_network.json"
CLOCKS = ("2026-11-11T12:00:00", "2026-11-12T00:30:00")  # the second is just past midnight: due / days move by one
REAL_CLOCKS = ("2026-11-11T12:00:00", "2027-03-01T09:30:00")


# ------------------------------------------------------------------ the oracle
def run_oracle(mode: str, inp: Mapping[str, Any], files: Mapping[str, bytes] | None = None) -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-network-oracle-") as tmp:
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
def _day(days_ago: int, clock: str = CLOCKS[0]) -> str:
    return (datetime.fromisoformat(clock).date() - timedelta(days=days_ago)).isoformat()


def dates_set() -> list[Any]:
    """``due`` and ``days_since_touch`` edge cases: every branch of the old parse, and the exact boundary."""
    act = {"next_action": "Call back"}
    return [
        {"id": "p-due-today", "name": "Dana Today", **act, "next_action_date": _day(0)},  # date == today: due
        {"id": "p-due-tomorrow", "name": "Tom Morrow", **act, "next_action_date": _day(-1)},  # due at the 2nd clock
        {"id": "p-due-yesterday", "name": "Yara Yester", **act, "next_action_date": _day(1)},
        {"id": "p-no-date", "name": "Nora Nodate", **act},  # missing date: due
        {"id": "p-empty-date", "name": "Emil Empty", **act, "next_action_date": ""},  # empty: due
        {"id": "p-null-date", "name": "Nils Null", **act, "next_action_date": None},  # None: due
        {"id": "p-bad-date", "name": "Bea Bad", **act, "next_action_date": "11/12/2026"},  # unparseable: not due
        {"id": "p-datetime-date", "name": "Tim Stamp", **act, "next_action_date": f"{_day(0)}T09:00"},
        {"id": "p-compact-date", "name": "Cora Compact", **act, "next_action_date": _day(0).replace("-", "")},
        {"id": "p-week-date", "name": "Wes Week", **act, "next_action_date": "2026-W46-3"},
        {"id": "p-int-date", "name": "Ivo Int", **act, "next_action_date": 20261111},
        {"id": "p-no-action", "name": "Nina Noaction", "next_action": "", "next_action_date": _day(5)},
        {"id": "p-action-none", "name": "Otto None", "next_action": None},
        {"id": "p-action-list", "name": "Lia List", "next_action": ["x"], "next_action_date": _day(0)},
        {"id": "p-touch-today", "name": "Theo Touch", "last_interaction": _day(0)},
        {"id": "p-touch-10", "name": "Tara Ten", "last_interaction": _day(10)},
        {"id": "p-touch-future", "name": "Finn Future", "last_interaction": _day(-3)},  # negative days
        {"id": "p-touch-empty", "name": "Elsa Empty", "last_interaction": ""},
        {"id": "p-touch-null", "name": "Ned Null", "last_interaction": None},
        {"id": "p-touch-garbage", "name": "Gus Garbage", "last_interaction": "last week"},
        {"id": "p-touch-int", "name": "Ina Int", "last_interaction": 5},
        {"id": "p-touch-stamp", "name": "Sam Stamp", "last_interaction": f"{_day(2)} 10:00"},
        {"id": "p-touch-week", "name": "Will Week", "last_interaction": "2026-W45-1"},
        {"id": "p-due-touched", "name": "Dora Both", **act, "next_action_date": _day(3), "last_interaction": _day(30)},
        {"name": "No Id At All", "next_action": "x"},  # no id: never listed
        {"id": "", "name": "Empty Id"},
        "not a record",
        {"id": "p-watch", "name": "Wanda Watch", "watch": True, "last_interaction": _day(4)},
        {"id": "p-watch-str", "name": "Walt Watch", "watch": "yes"},
        {"id": "p-watch-false", "name": "Wim Nowatch", "watch": False, **act},
    ]


def ties_set() -> list[Any]:
    """Equal sort keys keep the record order (the old stable sort): imported ties, then people appended later."""
    act = {"next_action": "Ping", "next_action_date": _day(2)}
    out: list[Any] = []
    for i, n in enumerate(["Zoe", "Adam", "Mia", "Ben"]):  # four due ties, deliberately not in name / id order
        out.append({"id": f"p-tie-due-{4 - i}", "name": f"{n} Due", **act, "last_interaction": _day(7)})
    for i, n in enumerate(["Yan", "Bob", "Kai"]):  # three undated ties (9999)
        out.append({"id": f"p-tie-none-{3 - i}", "name": f"{n} Undated"})
    out.append({"id": "p-tie-mid", "name": "Mid Seven", "last_interaction": _day(7)})
    out.append({"id": "p-tie-mid-b", "name": "Abe Seven", "last_interaction": _day(7)})
    # "created here": appended after the archive, as the old upsert / add_talented appended them
    out.append({"id": "p-new-zed", "name": "Zed New", "created": _day(0), "provenance": "user_provided"})
    out.append({"id": "p-new-amy", "name": "Amy New", "created": _day(0), "provenance": "user_provided"})
    out.append({"id": "p-new-due", "name": "Due New", **act, "last_interaction": _day(7)})
    return out


def graph_set() -> list[Any]:
    """A cycle, a shared descendant (within one root and across roots), a path crossing the depth limit."""
    out: list[Any] = [
        {"id": "p-root-a", "name": "Root Alpha", "recommended": ["p-kid-1", "p-kid-2", "p-unknown", "p-kid-1"],
         "role": "CTO", "company": "Alpha Labs", "founder_potential": "high", "relationship_strength": "warm",
         "startups": ["Alpha Labs"], "watch": True},
        {"id": "p-kid-1", "name": "Kid One", "introduced_by": "p-root-a", "recommended": ["p-shared"]},
        {"id": "p-kid-2", "name": "Kid Two", "introduced_by": "p-root-a", "recommended": ["p-shared", "p-root-a"]},
        {"id": "p-shared", "name": "Shared Grandkid", "introduced_by": "p-kid-1"},
        {"id": "p-root-b", "name": "Root Beta", "recommended": ["p-shared"]},  # the shared one, under a 2nd root
        {"id": "p-cyc-1", "name": "Cycle One", "introduced_by": "p-cyc-2"},  # an introduction cycle: no root
        {"id": "p-cyc-2", "name": "Cycle Two", "introduced_by": "p-cyc-1", "recommended": ["p-cyc-3"]},
        {"id": "p-cyc-3", "name": "Cycle Three", "introduced_by": "p-cyc-2"},
        {"id": "p-self", "name": "Self Intro", "introduced_by": "p-self"},
        {"id": "p-orphan", "name": "Orphan Kid", "introduced_by": "p-gone"},  # the introducer is not a person
        {"id": "p-free", "name": "Free Text", "introduced_by": "", "introduced_by_name": "Someone At A Meetup"},
        {"id": "p-noname-intro", "introduced_by": "p-root-b"},  # no name key: "?" in the tree, None as introducer
        {"id": "p-intro-by-noname", "name": "Has Nameless Parent", "introduced_by": "p-noname-intro"},
        {"id": "p-null-name", "name": None, "introduced_by": "p-root-b"},
    ]  # fmt: skip
    for i in range(10):  # a linear chain p-depth-0 <- ... <- p-depth-9: the tree stops after depth 6, chains at 6
        out.append({"id": f"p-depth-{i}", "name": f"Depth {i}", **({"introduced_by": f"p-depth-{i - 1}"} if i else {})})
    return out


def quirks_set() -> list[Any]:
    """Link values of the wrong type: the listing keeps the person (empty chain / names), the old graph raises."""
    return [
        {"id": "p-q-host", "name": "Quirk Host", "recommended": ["p-q-a", {"id": "p-q-a"}, None]},
        {"id": "p-q-a", "name": "Quirk A", "introduced_by": "p-q-host", "recommended": "p-q-host"},  # a string
        {"id": "p-q-int", "name": "Quirk Int", "recommended": 5},
        {"id": "p-q-none", "name": "Quirk None", "recommended": None},
        {"id": "p-q-list-intro", "name": "Quirk List Intro", "introduced_by": ["p-q-host"]},
        {"id": "p-q-dict", "name": "Quirk Dict", "recommended": {"p-q-a": True}},
    ]


def slug_names() -> list[str]:
    return ["Ada Lovelace", "Jürgen Groß", "  Ünal Öztürk-Ärger ", "Émile Zola", "李小龙", "", "!!!", "A" * 60,
            "Dr. Ada O'Brien", "ada_lovelace 2", "Straße", "ÄÖÜ äöü ß", "Ada\tLovelace", "x-" * 30]  # fmt: skip


def goldens_input() -> dict[str, Any]:
    sets = [
        {"name": "dates", "doc": {"people": dates_set()}},
        {"name": "ties", "doc": {"people": ties_set()}},
        {"name": "graph", "doc": {"people": graph_set()}},
        {"name": "quirks", "doc": {"people": quirks_set()}},
        {"name": "dict_collection", "doc": {"people": {"a": graph_set()[0], "b": graph_set()[1]}}},
    ]
    return {"clocks": list(CLOCKS), "sets": sets, "slugs": slug_names()}


def _try(fn: Any) -> Any:
    try:
        return {"ok": fn()}
    except Exception as exc:
        return {"raises": type(exc).__name__}


def new_reads(people: Any, clock: str) -> dict[str, Any]:
    today: date = view.berlin_today(datetime.fromisoformat(clock))
    recs = people if isinstance(people, list) else list(people.values()) if isinstance(people, dict) else []
    out: dict[str, Any] = js(
        {
            "listing": _try(lambda: view.listing(recs, today)),
            "tree": _try(lambda: view.talent_tree(recs)),
            "watchlist": _try(lambda: view.watchlist_view(recs, today)),
        }
    )
    return out


def new_goldens(inp: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"sets": {}}
    for s in inp["sets"]:
        out["sets"][s["name"]] = {c: new_reads(s["doc"]["people"], c) for c in inp["clocks"]}
    out["strengths"] = view.STRENGTHS
    out["potential"] = view.POTENTIAL
    out["fields"] = edits.FIELDS
    out["slugs"] = [slug(n) for n in inp["slugs"]]
    result: dict[str, Any] = js(out)
    return result


def compare_goldens(golden: Mapping[str, Any]) -> list[str]:
    return diff(golden["expected"], new_goldens(golden["input"]))


def write_goldens() -> int:
    inp = goldens_input()
    oracle = run_oracle("reads", inp)
    meta = oracle.pop("meta")
    golden = {"provenance": {**meta, "clocks": list(CLOCKS)}, "input": inp, "expected": oracle}
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    problems = compare_goldens(json.loads(GOLDEN.read_text(encoding="utf-8")))
    counts = {
        name: {c: len(r["listing"].get("ok", [])) for c, r in per.items()} for name, per in oracle["sets"].items()
    }
    raises = sorted({f"{n}:{k}" for n, per in oracle["sets"].items() for r in per.values() for k, v in r.items()
                     if "raises" in v})  # fmt: skip
    print(f"network goldens written: listing sizes {counts}; raising parts {raises}; {len(oracle['slugs'])} slugs; "
          f"provenance {meta['old_revision'][:7]} dirty={meta['old_dirty']}; "
          f"new code differences: {len(problems)}")  # fmt: skip
    for p in problems[:40]:
        print("  DIFF", p)
    return 1 if problems else 0


# ------------------------------------------------------------------ the real snapshot
def compare_people(old: list[dict[str, Any]], new: list[dict[str, Any]], where: str) -> list[str]:
    """The exact id sequence, then every field of every person (by position)."""
    out: list[str] = []
    if [p.get("id") for p in old] != [p.get("id") for p in new]:
        out.append(f"{where}: id sequence differs")
    for o, n in zip(old, new, strict=False):
        out += [f"{where}/{o.get('id')}{d.split(':')[0]}" for d in diff(js(o), js(n))]
    if len(old) != len(new):
        out.append(f"{where}: length {len(old)} != {len(new)}")
    return out


def compare_reads(old: Mapping[str, Any], client: Any, where: str) -> tuple[list[str], dict[str, Any]]:
    people = client.get("/api/network/people").json()
    graph = client.get("/api/network/graph").json()
    watch = client.get("/api/network/watchlist").json()
    problems = compare_people(old["listing"]["ok"], people["people"], f"{where}/people")
    problems += [f"{where}/strengths{d}" for d in diff(js(view.STRENGTHS), people["strengths"])]
    problems += [f"{where}/potential{d}" for d in diff(js(view.POTENTIAL), people["potential"])]
    problems += [f"{where}/graph{d.split(':')[0]}" for d in diff(js(old["tree"]["ok"]), graph["forest"])]
    problems += compare_people(old["watchlist"]["ok"]["people"], watch["people"], f"{where}/watchlist")
    stats = {
        "people": len(people["people"]),
        "due": sum(1 for p in people["people"] if p["due"]),
        "with_days_since_touch": sum(1 for p in people["people"] if p["days_since_touch"] is not None),
        "graph_roots": len(graph["forest"]),
        "watchlist": len(watch["people"]),
        "differences": len(problems),
    }
    return problems, stats


def pick_real(people: list[dict[str, Any]]) -> dict[str, str]:
    """Real people for the replay (ids only): a Founder Radar person to follow up, another to log a signal on, one to
    rename (deferred path), one to recommend, and the user-provided one."""
    radar = [p["id"] for p in people if isinstance(p, dict) and p.get("id") and p.get("provenance") != "user_provided"
             and not p.get("introduced_by") and isinstance(p.get("name"), str)]  # fmt: skip
    user = [p["id"] for p in people if isinstance(p, dict) and p.get("provenance") == "user_provided"]
    return {"follow": radar[0], "signal": radar[1], "rename": radar[2], "recommended": radar[3], "judged": radar[4],
            "user": user[0] if user else radar[5]}  # fmt: skip


def parity_steps(real: Mapping[str, str], today: str) -> list[dict[str, Any]]:
    """Steps whose old and new results must be IDENTICAL. Every save goes through the old ``person_save`` route
    (``operator_save``: since review 026a the new save also runs its radar post-processing)."""
    return [
        {"op": "person_save", "body": {"name": "  "}},  # name required
        {"op": "person_save", "body": {}},
        {
            "op": "person_save",
            "body": {
                "name": "Replay Ada Quill",
                "location": "Karlsruhe",
                "company": "Quill Labs",
                "startups": "Quill Labs, , Side Project ",
                "watch": True,
                "relationship_strength": "warm",
                "founder_potential": "high",
                "next_action": "Coffee",
                "next_action_date": today,
            },
        },
        {
            "op": "person_save",
            "body": {"id": "p-replay-ada-quill", "next_action": "Send the deck", "next_action_date": ""},
        },
        {
            "op": "person_save",
            "body": {"id": real["follow"], "next_action": "Follow up after the paper", "next_action_date": today},
        },  # a follow-up on an imported Founder Radar person
        {"op": "person_save", "body": {"id": real["user"], "last_interaction": today, "notes": "met at the meetup"}},
        {"op": "person_save", "body": {"id": real["judged"], "human_judgment": "strong technical founder"}},  # judgment
        {"op": "person_save", "body": {"name": "Replay Ben Ortiz", "introduced_by": "p-replay-ada-quill"}},
        {
            "op": "talented",
            "body": {
                "id": "p-replay-ada-quill",
                "persons": [
                    {"name": "Replay Cleo Vance", "note": "robotics PhD"},
                    {"name": ""},
                    {"name": "Replay Dev Rao"},
                    {"name": "Replay Cleo Vance", "note": "named twice"},
                ],
            },
        },
        {"op": "talented", "body": {"id": "p-replay-ada-quill", "persons": [{"name": "Replay Dev Rao"}]}},  # a retry
        {"op": "talented", "body": {"id": real["recommended"], "persons": [{"name": "Replay Eli Brandt"}]}},
        {"op": "talented", "body": {"id": "p-no-such-person", "persons": [{"name": "Replay Ghost"}]}},
        {"op": "talented", "body": {"id": "p-replay-ben-ortiz", "persons": []}},
        {"op": "watch_log", "body": {"id": real["signal"], "note": "new arXiv paper"}},
        {"op": "watch_log", "body": {"id": real["signal"], "note": "spoke at a conference"}},
        {"op": "watch_log", "body": {"id": "p-replay-ada-quill", "note": ""}},  # just mark checked
        {"op": "watch_log", "body": {"id": "p-no-such-person", "note": "ignored"}},
        {"op": "person_save", "body": {"id": "p-replay-dev-rao", "watch": True, "startups": ["Rao Robotics"]}},
    ]


def decision_steps(real: Mapping[str, str]) -> list[dict[str, Any]]:
    """Steps where the new code differs ON PURPOSE; each difference is asserted in ``check_decision``."""
    return [
        # (a) an add whose generated id exists: old overwrote the person, new refuses with the existing id
        {
            "op": "person_save",
            "body": {"name": "Replay Ada Quill", "company": "Overwritten Co"},
            "decision": "a-duplicate",
        },
        # (a) an edit of an unknown id: old created it, new refuses and creates nothing
        {"op": "person_save", "body": {"id": "p-replay-unknown", "name": "Replay Unknown"}, "decision": "a-unknown"},
        # (b) another introducer recommends a person who already has an introducer: old re-parented
        {
            "op": "talented",
            "body": {"id": "p-replay-ben-ortiz", "persons": [{"name": "Replay Cleo Vance", "note": "Ben's note"}]},
            "decision": "b-reparent",
        },
        # review 026a: renaming a Founder Radar person takes the old radar-name path
        {
            "op": "person_save",
            "body": {"id": real["rename"], "name": "Replay Renamed Person"},
            "decision": "radar-name",
        },
    ]


def _no_minutes(v: Any) -> Any:
    """A record with its ``YYYY-MM-DD HH:MM`` stamps masked: the old code read the machine clock, the new one the
    request clock (the radar-name path stamps its identity evidence and its source)."""
    return json.loads(re.sub(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", "<minute>", json.dumps(v)))


def _by_id(people: list[Any]) -> dict[str, Any]:
    return {str(p["id"]): p for p in people if isinstance(p, dict) and p.get("id")}


def check_decision(step: Mapping[str, Any], old: Mapping[str, Any], new_code: int, new_body: Mapping[str, Any],
                   before: dict[str, Any], old_after: dict[str, Any], new_after: dict[str, Any],
                   diverged: set[str]) -> list[str]:  # fmt: skip
    """The explicit assertion for one decision step: what the old code did, what the new code must do, and that
    NOTHING else differs: every person other than this step's one (and the ones earlier decision steps diverged on
    purpose, ``diverged``, which this call extends) is identical old vs new."""
    kind = step["decision"]
    out: list[str] = []

    def expect(cond: bool, what: str) -> None:
        if not cond:
            out.append(f"{kind}: {what}")

    touched: set[str]
    if kind == "a-duplicate":
        pid = "p-replay-ada-quill"
        expect(old["code"] == 200 and old_after[pid]["company"] == "Overwritten Co", "old overwrote the person")
        expect(new_code == 409 and new_body.get("id") == pid and new_body.get("duplicate") is True, "new: 409 + id")
        expect(new_after[pid] == before[pid], "new: the existing person is unchanged")
        touched = {pid}
    elif kind == "a-unknown":
        pid = "p-replay-unknown"
        expect(old["code"] == 200 and pid in old_after, "old created the unknown id")
        expect(new_code == 404 and pid not in new_after, "new: 404 and nothing created")
        touched = {pid}
    elif kind == "b-reparent":
        pid, host, first = "p-replay-cleo-vance", "p-replay-ben-ortiz", "p-replay-ada-quill"
        expect(old_after[pid]["introduced_by"] == host, "old re-parented the person")
        expect(new_code == 200 and new_body.get("created") == [pid], "new: 200 + created")
        expect(new_after[pid]["introduced_by"] == first, "new: the original introducer survives")
        expect(new_after[pid]["discovery"] == before[pid]["discovery"], "new: the introduction text survives")
        expect(new_after[pid]["why_interesting"] == before[pid]["why_interesting"], "new: why_interesting kept")
        expect(pid in new_after[host]["recommended"] and pid in old_after[host]["recommended"], "both: recommended")
        expect(new_after[host] == old_after[host], "the introducer is identical old vs new")
        rest_old = {
            k: v for k, v in old_after[pid].items() if k not in ("introduced_by", "discovery", "why_interesting")
        }
        rest_new = {
            k: v for k, v in new_after[pid].items() if k not in ("introduced_by", "discovery", "why_interesting")
        }
        expect(rest_old == rest_new, "every other field of the person is identical")
        touched = {pid}
    else:  # radar-name
        pid = step["body"]["id"]
        expect(old["code"] == 200 and old_after[pid]["name"] == "Replay Renamed Person", "old renamed the person")
        expect(old_after[pid].get("name_by_operator") is True, "old took the radar-name path")
        expect(new_code == 200, "new: 200")
        expect(_no_minutes(new_after[pid]) == _no_minutes(old_after[pid]), "new: the old radar-name result")
        touched = {pid}
    diverged |= touched
    others_old = {k: v for k, v in old_after.items() if k not in diverged}
    others_new = {k: v for k, v in new_after.items() if k not in diverged}
    out += [f"{kind}: others{d.split(':')[0]}" for d in diff(js(others_old), js(others_new))]
    return out


def real() -> int:  # pragma: no cover - needs the hosted database and the old repository
    import secrets as _secrets

    from fastapi.testclient import TestClient
    from psycopg import sql as _sql

    from projectzero.api.app import create_app
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import connect, transaction
    from projectzero.network.store import load_people
    from projectzero.ops.db_check import _scratch_sql
    from projectzero.ops.legacy.apply import apply_plan
    from projectzero.ops.legacy.plan import build_plan
    from projectzero.ops.legacy.source import LegacySnapshot

    load_dotenv()
    settings = Settings.from_env()
    snapshot = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    files = {f.path: f.raw for f in snapshot.files()}
    real_people = (snapshot.json("people.json", {}) or {}).get("people") or []
    picked = pick_real(real_people)
    write_clock = REAL_CLOCKS[0]
    today = datetime.fromisoformat(write_clock).date().isoformat()
    p_steps = parity_steps(picked, today)
    d_steps = decision_steps(picked)
    steps = [*p_steps, *d_steps]

    reads_run = run_oracle("reads", {"clocks": list(REAL_CLOCKS), "sets": None}, files)
    reads_old = reads_run["sets"]["data"]
    writes_old = run_oracle("writes", {"clock": write_clock, "steps": steps}, files)["steps"]
    # the old views right after the parity segment (before any decision step diverges the data)
    after_parity = {p.path: p.raw for p in snapshot.files()}
    after_parity["people.json"] = json.dumps({"people": writes_old[len(p_steps) - 1]["people"]}).encode()
    reads_after_old = run_oracle("reads", {"clocks": [write_clock], "sets": None}, after_parity)["sets"]["data"]

    schema = f"pz_rehearse_{_secrets.token_hex(4)}"
    report: dict[str, Any] = {"oracle": reads_run["meta"], "people": 0}
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
                d, stats = compare_reads(reads_old[clock], client, f"read@{clock}")
                report[f"read@{clock}"] = stats
                problems += d
            app.state.clock = lambda: datetime.fromisoformat(write_clock)
            codes: list[tuple[int, int]] = []
            parity_diffs = 0
            decisions: dict[str, int] = {}
            diverged: set[str] = set()

            def stored() -> list[dict[str, Any]]:
                with transaction(settings.db_url) as c:
                    return load_people(c, schema)

            before = stored()
            for i, (step, old) in enumerate(zip(steps, writes_old, strict=True)):
                path = {"upsert": "person_save", "person_save": "person_save"}.get(step["op"], step["op"])
                r = client.post(f"/api/network/{path}", json=step["body"])
                body = r.json()
                codes.append((old["code"], r.status_code))
                after = stored()
                if "decision" in step:
                    d = check_decision(step, old, r.status_code, body, _by_id(before), _by_id(old["people"]),
                                       _by_id(after), diverged)  # fmt: skip
                    decisions[step["decision"]] = len(d)
                    problems += [f"write[{i}] {p}" for p in d]
                else:
                    local: list[str] = []
                    if r.status_code != old["code"]:
                        local.append(f"/code {old['code']} != {r.status_code}")
                    local += [f"/body{p.split(':')[0]}" for p in diff(js(old["body"]), js(body))]
                    local += compare_people(js(old["people"]), js(after), "/people")
                    parity_diffs += len(local)
                    problems += [f"write[{i}]{p}" for p in local]
                    if i == len(p_steps) - 1:
                        d, stats = compare_reads(reads_after_old[write_clock], client, "after-parity-writes")
                        report["reads_after_parity_writes"] = stats
                        problems += d
                before = after
            report["people"] = len(before)
            report["write_steps"] = {"parity": len(p_steps), "decision": len(d_steps)}
            report["write_codes_old_new"] = " ".join(f"{o}/{n}" for o, n in codes)
            report["parity_write_differences"] = parity_diffs
            report["decision_assertion_failures"] = decisions
            with transaction(settings.db_url) as c:
                events = c.execute(
                    _sql.SQL("select action, count(*) from {}.person_events group by 1 order by 1").format(
                        _sql.Identifier(schema)
                    )
                ).fetchall()
            report["person_events"] = dict(events)
    finally:
        admin.execute(_sql.SQL("drop schema if exists {} cascade").format(_sql.Identifier(schema)))
        admin.close()
    report["differences"] = len(problems)
    print(json.dumps(report, indent=2, default=str))
    for p in problems[:60]:
        print("  DIFF", p)
    print("NETWORK PARITY PASSED" if not problems else "NETWORK PARITY FAILED")
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

"""Review 024, offline: the catalog is the old text cut by script, the port carries only the old literals, and the pure
routes match the OLD code's goldens (``oracle_evaluator.json``, ``python -m projectzero.ops.parity_evaluator
goldens``), key order included."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from projectzero.evaluator import catalog, core, evidence
from projectzero.ops.parity_evaluator import CLOCK, LONG_ID, SETS, SHORT_ID, STEPS, compare_goldens, corpus, expand
from projectzero.ops.parity_ranking import OLD_REPO

GOLDEN: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "golden_v1" / "oracle_evaluator.json").read_text(
        encoding="utf-8"
    )
)
OLD = OLD_REPO / "backend" / "src" / "projectzero"
OLD_MODULE = OLD / "domain" / "evaluator.py"
CUT = ["FILE_NAME", "STATES", "DECK_LABEL", "FOUNDER_LABEL", "UNKNOWN", "FAMILIES", "FAM", "_FAM_WORDS", "_NUM",
       "_MATERIAL", "_WORDNUM", "_COUNT_NOUNS", "_COUNT_RX", "_NEG_RX", "CANONICAL_MAP"]  # fmt: skip
HINTS = {"_WORDNUM = {": "_WORDNUM: dict[str, int] = {",
         "CANONICAL_MAP = {": "CANONICAL_MAP: dict[str, list[str]] = {"}  # fmt: skip


def _literals(path: Path) -> set[str]:
    return {n.value for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}  # fmt: skip


@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_catalog_is_the_old_top_level_lines_cut_by_script() -> None:
    src = OLD_MODULE.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    ours = Path(catalog.__file__ or "").read_text(encoding="utf-8")
    nodes = {n.targets[0].id: n for n in ast.parse(src).body
             if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)}  # fmt: skip
    for name in CUT:
        node = nodes[name]
        text = "".join(lines[node.lineno - 1 : node.end_lineno])
        for old, new in HINTS.items():  # the type hints, nothing else
            text = text.replace(old, new)
        assert text in ours, name
    defined = [n.target.id if isinstance(n, ast.AnnAssign) else n.targets[0].id  # type: ignore[union-attr]
               for n in ast.parse(ours).body if isinstance(n, (ast.Assign, ast.AnnAssign))]  # fmt: skip
    assert defined == CUT


@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_cut_values_equal_the_old_module_values() -> None:
    import re

    tree = ast.parse(OLD_MODULE.read_text(encoding="utf-8"))
    picked = [n for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1
              and isinstance(n.targets[0], ast.Name) and n.targets[0].id in CUT]  # fmt: skip
    ns: dict[str, Any] = {"re": re}
    exec(compile(ast.Module(body=picked, type_ignores=[]), str(OLD_MODULE), "exec"), ns)  # the old assignments only
    for name in CUT:
        assert getattr(catalog, name) == ns[name], name
    assert catalog.FAMILIES[0][0] == "founder_team" and len(catalog.FAMILIES) == 18


@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_port_carries_the_old_literals_unchanged() -> None:
    old = (_literals(OLD_MODULE) | _literals(OLD / "api" / "routers" / "evaluator.py")
           | _literals(OLD / "domain" / "founder_radar" / "evidence.py"))  # fmt: skip
    for module in (catalog, core, evidence):
        src = Path(module.__file__ or "")
        tree = ast.parse(src.read_text(encoding="utf-8"))
        docs = {id(n.body[0].value) for n in ast.walk(tree)  # docstrings are commentary, not the old data
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr)}  # fmt: skip
        ours = {n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs}  # fmt: skip
        new_only = sorted(v for v in ours if v not in old)
        assert new_only == [], (src.name, new_only[:5])


def test_provenance_and_inputs_are_current() -> None:
    assert GOLDEN["provenance"]["old_revision"] == "6c739b9cb6ca2517b845e381d39a36c50eccc59e"
    assert GOLDEN["provenance"]["old_dirty"] is False
    assert GOLDEN["clock"] == CLOCK
    assert set(GOLDEN["sets"]) == set(SETS)
    for name, spec in SETS.items():
        # serialized without sort_keys: the documents' insertion order is part of the input
        assert json.dumps(GOLDEN["sets"][name]["docs"]) == json.dumps(json.loads(json.dumps(spec["docs"]()))), name
        assert GOLDEN["sets"][name]["steps"] == json.loads(json.dumps(spec["steps"])), name


def test_the_pure_routes_match_the_old_code_including_key_order() -> None:
    assert compare_goldens(GOLDEN) == []


def jsonb_order(ids: list[str]) -> list[str]:
    """How JSONB iterates an object's keys: by length, then bytes."""
    return sorted(ids, key=lambda k: (len(k.encode()), k.encode()))


def test_the_fixture_insertion_order_is_not_the_jsonb_order() -> None:
    sessions = corpus()["evaluations.json"]["sessions"]
    ids = list(sessions)
    assert ids != jsonb_order(ids)
    assert ids[0] == LONG_ID and ids[-1] == SHORT_ID and len(SHORT_ID) == min(len(i) for i in ids)
    assert sessions[LONG_ID]["created"] == sessions[SHORT_ID]["created"]  # the tie
    assert jsonb_order([LONG_ID, SHORT_ID]) == [SHORT_ID, LONG_ID]


def test_the_goldens_cover_what_the_plan_names() -> None:
    steps = expand(GOLDEN["sets"]["main"]["expected"])
    first = steps[0]
    rows = [r["id"] for r in first["view"]["body"]["sessions"]]
    assert rows.index(LONG_ID) + 1 == rows.index(SHORT_ID)  # the created tie keeps the insertion order
    assert first["session"][LONG_ID]["body"]["next"]["id"] == "q-skipped01"  # GET next includes a skipped question
    assert first["session"]["ev-unknown"] == {"code": 404, "body": {"error": "unknown session"}}
    answers = [(sp["op"], st["answer"]["body"]) for sp, st in zip(STEPS, steps, strict=True) if "answer" in st]
    errors = {b.get("error") for _, b in answers}
    assert {"unknown question", "already answered", "explicit confirmation required", "unknown claim",
            "unknown contradiction", "unknown evaluator action", "unknown session", "unknown company"} <= errors  # fmt: skip
    assert any("LinkedIn" in str(e) for e in errors) and any("search results" in str(e) for e in errors)
    assert any("trigger kind" in str(e) for e in errors) and any("trigger date" in str(e) for e in errors)
    ends = [b["ended"] for op, b in answers if op == "end"]
    assert any(e.get("already") for e in ends)
    assert any(e["call_id"] for e in ends) and any(e["call_error"] for e in ends)
    assert {e["imq"]["state"] for e in ends} >= {"NOT YET IMQ", "CONFLICT GATED", "not linked to a Conviction company"}
    final = [st for st in steps if "store" in st][-1]
    order = final["store"]["order"]
    assert order[:3] == list(corpus()["evaluations.json"]["sessions"])  # imported sessions first, new ones appended
    ledger = [c for s in final["store"]["body"]["sessions"].values() for c in s["ledger"]]
    contra = [c for c in ledger if c["state"] == "CONTRADICTION"]
    assert any(c.get("kind") == "count" for c in contra)  # deck 18 vs founder 12 paying customers
    assert any("fresh round" in c["text"] for c in contra)  # the 180-day window and the verified-funding fallback
    assert any(c.get("resolution") for c in contra)
    assert any(len(c["evidence"]) == 2 for c in ledger)  # every attach appends a row
    assert {c["state"] for c in ledger} >= {"DECK CLAIM", "FOUNDER-REPORTED", "PUBLIC SOURCED FACT",
                                            "OPERATOR VERIFIED", "CONTRADICTION", "UNKNOWN"}  # fmt: skip
    trig = [st for sp, st in zip(STEPS, steps, strict=True) if sp["op"] == "imq_trigger"]
    assert trig[-1]["signals"][0]["imq_trigger"]["by"] == "operator"
    assert all(t["signals"] == corpus()["real_data.json"]["signals"] for t in trig[:-1])  # a refusal writes nothing
    assert len(final["calls"]["order"]["calls"]) == 4
    empty = expand(GOLDEN["sets"]["empty"]["expected"])
    assert empty[1]["store"] == {"body": None, "order": None}  # an unknown session writes nothing

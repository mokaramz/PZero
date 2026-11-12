"""Review 023, offline: the catalog is the old text cut by script, the port carries only the old literals, and the pure
routes match the OLD code's goldens (``oracle_founder_calls.json``, ``python -m projectzero.ops.parity_founder_calls
goldens``), key order included."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from projectzero.founder_calls import catalog, core, routes
from projectzero.ops.parity_founder_calls import CLOCK, OBJECTS, SETS, compare_goldens, corpus, expand
from projectzero.ops.parity_ranking import OLD_REPO

GOLDEN: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "golden_v1" / "oracle_founder_calls.json").read_text(
        encoding="utf-8"
    )
)
OLD = OLD_REPO / "backend" / "src" / "projectzero"
OLD_MODULE = OLD / "domain" / "founder_calls.py"
CUT = ["FILE_NAME", "LABEL", "SUMMARY_LABEL", "UNKNOWN", "CHANNELS", "CALL_TYPES", "RECOMMENDATIONS", "CONFIDENCE",
       "OWNERS", "UPCOMING_DAYS", "TEMPLATES", "ASSESSMENT_FIELDS"]  # fmt: skip


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
        text = text.replace("TEMPLATES = {", "TEMPLATES: dict[str, dict[str, Any]] = {")  # the one type hint
        assert text in ours, name
    defined = [n.target.id if isinstance(n, ast.AnnAssign) else n.targets[0].id  # type: ignore[union-attr]
               for n in ast.parse(ours).body if isinstance(n, (ast.Assign, ast.AnnAssign))]  # fmt: skip
    assert defined == CUT


@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_port_carries_the_old_literals_unchanged() -> None:
    old = _literals(OLD_MODULE) | _literals(OLD / "api" / "routers" / "calls.py")
    for module in (catalog, core, routes):
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
        assert GOLDEN["sets"][name]["steps"] == spec["steps"], name


def test_the_pure_routes_match_the_old_code_including_key_order() -> None:
    assert compare_goldens(GOLDEN) == []


def jsonb_order(ids: list[str]) -> list[str]:
    """How JSONB iterates an object's keys: by length, then bytes."""
    return sorted(ids, key=lambda k: (len(k.encode()), k.encode()))


def test_the_fixture_insertion_order_is_not_the_jsonb_order() -> None:
    doc = corpus()["founder_calls.json"]
    for k in OBJECTS:
        ids = list(doc[k])
        assert ids != jsonb_order(ids), k
        assert len(ids[0]) > len(ids[-1]) == min(len(i) for i in ids), k  # long ids first, a short one last
    tied = [
        c
        for c in doc["calls"].values()
        if (c["date"], c["time"], c["created"]) == ("2026-11-03", "09:00", "2026-11-03 09:30:00")
    ]
    assert [c["id"] for c in tied] == ["fc-call-tiedsecond0002", "fc-call-tiedfirst00003"]
    assert jsonb_order([c["id"] for c in tied]) == ["fc-call-tiedfirst00003", "fc-call-tiedsecond0002"]


def test_the_goldens_cover_what_the_plan_names() -> None:
    steps = expand(GOLDEN["sets"]["main"]["expected"])
    first = steps[0]["view"]["body"]
    states = {c["due_state"] for st in steps for c in (st.get("view") or {}).get("body", {}).get("calls", [])}
    assert states == {"", "done", "open", "overdue", "due", "upcoming", "scheduled"}
    ids = [c["id"] for c in first["calls"]]
    assert ids.index("fc-call-tiedsecond0002") + 1 == ids.index("fc-call-tiedfirst00003")  # the tie keeps file order
    assert "fc-call-evaluatorempty8" not in [c["id"] for c in first["due"]]  # an empty evaluator session
    assert {"fc-call-evaluatoranswr9", "fc-call-evaluatorunkn10"} <= {c["id"] for c in first["due"]}
    assert first["orphan_founders"][0]["id"] == "fc-f-orphan0000000004"
    assert first["people"] and first["pipeline"][0]["slug"] == "invented-harbor-grid"
    answers = [st["answer"] for st in steps if "answer" in st]
    bodies = [a["body"] for a in answers]
    assert {"error": "founder name and company are required"} in bodies
    assert {"error": "unknown person"} in bodies and {"error": "unknown pipeline company"} in bodies
    assert {"error": "founder_id or company_id required"} in bodies and {"error": "unknown call"} in bodies
    assert {"error": "explicit confirmation required"} in bodies and {"error": "no calls for this founder"} in bodies
    assert {"ok": False, "founder_id": None} in bodies and {"ok": False, "company_id": None} in bodies
    assert any(b.get("changed") is False for b in bodies)
    assert any(b.get("pipeline_slug") for b in bodies)
    last = [st for st in steps if "doc" in st][-1]  # after the last write
    final = last["doc"]["body"]
    assert final["founders"]["fc-f-orphan0000000004"]["merged_into"] == "fc-f-personlinked00003"
    assert final["companies"]["fc-co-tiedname0000005"]["merged_into"] == "fc-co-pipelinelinked02"
    assert final["companies"]["c9"]["merged_into"] == "fc-co-radarlinkedco003"
    assert "Invented quill robotics" in final["companies"]["fc-co-pipelinelinked02"]["aliases"]
    assert final["calls"]["k1"]["founder_id"] == "fc-f-personlinked00003"  # re-pointed by the merge
    order = last["doc"]["order"]
    assert order["calls"][: len(corpus()["founder_calls.json"]["calls"])] == list(
        corpus()["founder_calls.json"]["calls"]
    )
    assert GOLDEN["sets"]["empty"]["expected"][1]["doc"] == {"body": None, "order": None}  # a refusal writes nothing
    partial = expand(GOLDEN["sets"]["partial"]["expected"])
    assert partial[2]["doc"]["order"]["top"] == ["version", "calls", "label", "companies", "founders"]

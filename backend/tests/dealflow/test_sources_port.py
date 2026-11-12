"""Review 021, offline: the catalog and the normalization are the old text, the pure view matches the OLD code's
goldens (``oracle_sources.json``), and the counter rule (decision a, Codex H-155 / H-157) in each branch."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from projectzero.dealflow.sources import catalog, counters, normalize
from projectzero.dealflow.sources.view import with_deltas
from projectzero.ops.parity_ranking import OLD_REPO
from projectzero.ops.parity_sources import STEPS, compare_goldens, corpus

GOLDEN: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "golden_v1" / "oracle_sources.json").read_text(encoding="utf-8")
)
OLD = OLD_REPO / "backend" / "src" / "projectzero" / "domain"


def _literals(path: Path) -> set[str]:
    return {n.value for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}  # fmt: skip


@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_catalog_and_normalization_carry_the_old_literals_unchanged() -> None:
    old = _literals(OLD / "connectors.py") | _literals(OLD / "sources_v2.py")
    for module in (catalog, normalize):
        src = Path(module.__file__ or "")
        tree = ast.parse(src.read_text(encoding="utf-8"))
        docs = {id(n.body[0].value) for n in ast.walk(tree)  # docstrings are commentary, not the old data
                if isinstance(n, (ast.Module, ast.FunctionDef)) and n.body and isinstance(n.body[0], ast.Expr)}  # fmt: skip
        ours = {n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs}  # fmt: skip
        new_only = sorted(v for v in ours if v not in old)
        assert new_only == [], (src.name, new_only[:5])


def test_provenance_and_inputs_are_current() -> None:
    assert GOLDEN["provenance"]["old_revision"] == "6c739b9cb6ca2517b845e381d39a36c50eccc59e"
    assert GOLDEN["provenance"]["old_dirty"] is False
    assert GOLDEN["docs"] == json.loads(json.dumps(corpus())) and GOLDEN["steps"] == STEPS


def test_the_pure_view_matches_the_old_code() -> None:
    assert compare_goldens(GOLDEN) == []
    view = GOLDEN["expected"]["view"]
    ids = [s["id"] for s in view["sources"]]
    assert {"ch-eth-dinfk", "ch-epfl-creation"} <= set(ids)  # appended by the normalization
    assert GOLDEN["unknown_reliability"]["expected"] == {"raises": "KeyError"}


def test_a_toggle_never_folds_a_delta_into_the_baseline() -> None:
    reg = {"sources": [{"id": "s1", "quality": {"radar": 3}, "yield": {"kept": 1, "research": 0, "rejected": 0}}]}
    shown = with_deltas(reg, {"s1": {"quality": {"radar": 1}, "yield": {"kept": 2}}})
    assert shown["sources"][0]["quality"]["radar"] == 4 and shown["sources"][0]["yield"]["kept"] == 3
    assert reg["sources"][0]["quality"]["radar"] == 3  # the stored form is untouched


def status(cid: str, before: str, after: str) -> dict[str, Any]:
    return {"candidate_id": cid, "from_status": before, "to_status": after}


CANDS = {
    "c1": {"source_id": "s-a", "quality_source_id": "s-q"},
    "c2": {"source_id": "s-a", "q_milestones": ["kept"]},  # credited before the import
    "c3": {"source_id": "s-b"},
}


def test_yield_votes_once_per_real_change_and_maps_research() -> None:
    out = counters.derive([status("c1", "new", "kept"), status("c1", "kept", "kept"), status("c3", "new", "reviewing"),
                           status("c3", "reviewing", "rejected"), status("c3", "archived", "rejected")],
                          [], CANDS, {})  # fmt: skip
    assert out["s-a"]["yield"] == {"kept": 1}
    assert out["s-b"]["yield"] == {"research": 1, "rejected": 1}  # archived -> rejected is no real change


def test_quality_keep_and_research_once_per_candidate_with_the_imported_guard() -> None:
    out = counters.derive([status("c1", "new", "kept"), status("c1", "kept", "new"), status("c1", "new", "kept"),
                           status("c2", "new", "kept"), status("c3", "new", "reviewing"),
                           status("c3", "reviewing", "new"), status("c3", "new", "reviewing")],
                          [], CANDS, {})  # fmt: skip
    assert out["s-q"]["quality"] == {"kept": 1}  # credited to the quality source, once
    assert "quality" not in out.get("s-a", {}) or out["s-a"]["quality"] == {}  # c2: already credited
    assert out["s-b"]["quality"] == {"researched": 1}


def test_a_name_matched_creation_earns_quality_but_no_yield_and_a_later_keep_adds_no_second_credit() -> None:
    created = [{"candidate_id": "c3", "source_id": "s-b"}]
    out = counters.derive([], created, CANDS, {})
    assert out["s-b"] == {"quality": {"kept": 1}, "yield": {}}
    later = counters.derive([status("c3", "new", "kept")], created, CANDS, {})
    assert later["s-b"] == {"quality": {"kept": 1}, "yield": {"kept": 1}}


def test_radar_credits_come_from_counted_events() -> None:
    assert counters.derive([], [], {}, {"s-r": 2})["s-r"]["quality"] == {"radar": 2}


T1, T2 = "2026-11-12T09:00:00+00:00", "2026-11-12T10:00:00+00:00"


def test_the_first_eligible_event_earns_the_quality_credit_in_time_order() -> None:
    """Codex H-159: a name-matched creation recorded source A, a later explicit Keep finds source B on the candidate."""
    cands = {"c9": {"source_id": "s-yield", "quality_source_id": "s-B"}}
    create = {"candidate_id": "c9", "source_id": "s-A", "at": T1, "id": 1}
    keep = {"candidate_id": "c9", "from_status": "new", "to_status": "kept", "at": T2, "id": 2}
    out = counters.derive([keep], [create], cands, {})
    assert out["s-A"]["quality"] == {"kept": 1} and "s-B" not in out  # the earlier creation's source, once
    assert out["s-yield"] == {"quality": {}, "yield": {"kept": 1}}  # the Keep's separate yield vote
    # the reverse order: the Keep came first, so its source earns the credit
    keep_first = counters.derive([{**keep, "at": T1}], [{**create, "at": T2}], cands, {})
    assert keep_first["s-B"]["quality"] == {"kept": 1} and "s-A" not in keep_first


def test_an_event_without_a_source_consumes_nothing() -> None:
    cands = {"c8": {}}  # no source on the candidate
    keep = {"candidate_id": "c8", "from_status": "new", "to_status": "kept", "at": T1, "id": 1}
    create = {"candidate_id": "c8", "source_id": "s-A", "at": T2, "id": 2}
    out = counters.derive([keep], [create], cands, {})
    assert out == {"s-A": {"quality": {"kept": 1}, "yield": {}}}  # the Keep credited nothing, the creation did
    research = {"candidate_id": "c8", "from_status": "new", "to_status": "reviewing", "at": T1, "id": 3}
    assert counters.derive([research], [], cands, {}) == {}


def test_a_status_event_keeps_the_sources_it_recorded_at_decision_time() -> None:
    """Codex H-161: the candidate's provenance changed to B after the decision; the vote and credit stay with A."""
    cands = {"c7": {"source_id": "s-B", "quality_source_id": "s-B"}}
    recorded = {"source_id": "s-A", "quality_source_id": "s-Aq"}
    keep = {"candidate_id": "c7", "from_status": "new", "to_status": "kept", "at": T1, "id": 1, "sources": recorded}
    out = counters.derive([keep], [], cands, {})
    assert out == {"s-A": {"quality": {}, "yield": {"kept": 1}}, "s-Aq": {"quality": {"kept": 1}, "yield": {}}}
    # an event written before the sources were recorded falls back to the candidate's current provenance
    legacy_event = {k: v for k, v in keep.items() if k != "sources"}
    assert counters.derive([legacy_event], [], cands, {}) == {"s-B": {"quality": {"kept": 1}, "yield": {"kept": 1}}}

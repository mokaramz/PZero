"""Review 026a, offline: the catalog is the old text cut by script, the port carries only the old literals, and the pure
routes match the OLD code's goldens (``oracle_founder_radar.json``, ``python -m projectzero.ops.parity_founder_radar
goldens``), key order included."""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest

from projectzero.conviction import taste
from projectzero.founder_radar import (
    boardy,
    catalog,
    companies,
    csv_import,
    evidence,
    extraction,
    identity,
    ingestion,
    leads,
    metrics,
    names,
    records,
    review,
    routes,
    scoring,
    sources,
)
from projectzero.ops.parity_founder_radar import (
    CLOCK,
    LARK,
    RHEA,
    SETS,
    STEPS,
    TEODOR,
    WENNA_A,
    WENNA_B,
    ZORVIK,
    compare_goldens,
    expand,
    research_doc,
)
from projectzero.ops.parity_ranking import OLD_REPO

GOLDEN: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "golden_v1" / "oracle_founder_radar.json").read_text(
        encoding="utf-8"
    )
)
OLD = OLD_REPO / "backend" / "src" / "projectzero"
OLD_FR = OLD / "domain" / "founder_radar"
ROOT = Path(__file__).resolve().parents[3]
PORTED = (boardy, catalog, companies, csv_import, evidence, extraction, identity, ingestion, leads, metrics, names,
          records, review, routes, scoring, sources)  # fmt: skip
# decision f's answer text, and the merge refusal for two different patent inventor ids (Codex H-213)
NEW_TEXTS = {routes.STATE_REFUSAL, "conflicting patent_inventor_id ("}


def _generator() -> Any:
    spec = importlib.util.spec_from_file_location(
        "gen_founder_radar_catalog", ROOT / "scripts" / "gen_founder_radar_catalog.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_catalog_is_the_old_top_level_lines_cut_by_script() -> None:
    gen = _generator()
    assert gen.build() == Path(catalog.__file__ or "").read_text(encoding="utf-8")  # regenerating changes nothing
    ours = ast.parse(Path(catalog.__file__ or "").read_text(encoding="utf-8"))
    defined = [n.name if isinstance(n, ast.FunctionDef) else (n.target.id if isinstance(n, ast.AnnAssign) else n.targets[0].id)  # type: ignore[union-attr]
               for n in ours.body if isinstance(n, (ast.Assign, ast.AnnAssign, ast.FunctionDef))]  # fmt: skip
    assert defined == ["__all__", *[name for _mod, names_ in gen.CUTS for name in names_]]


@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_cut_values_equal_the_old_module_values() -> None:
    for mod, cut in _generator().CUTS:
        tree = ast.parse((OLD_FR / mod).read_text(encoding="utf-8"))
        picked = [n for n in tree.body if isinstance(n, (ast.Assign, ast.FunctionDef))
                  and (n.name if isinstance(n, ast.FunctionDef) else getattr(n.targets[0], "id", None)) in cut]  # fmt: skip
        ns: dict[str, Any] = {"re": re, "taste": taste}
        exec(
            compile(ast.Module(body=picked, type_ignores=[]), str(OLD_FR / mod), "exec"), ns
        )  # the old statements only
        for name in cut:
            if name == "_theme_terms":  # decision b: the old set, sorted
                assert catalog._theme_terms() == sorted(ns[name]()) and isinstance(ns[name](), set)
            elif name == "HUMAN":
                assert set(catalog.HUMAN) == set(ns[name]) and all(
                    catalog.HUMAN[k]("x") == ns[name][k]("x") for k in ns[name]
                )
            else:
                assert getattr(catalog, name) == ns[name], (mod, name)
    assert catalog.DEFAULT_REGIONS and catalog.SOURCES_SCHEMA == 2  # the ecosystems cuts, re-exported


def _literals(path: Path) -> set[str]:
    return {n.value for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}  # fmt: skip


@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_port_carries_the_old_literals_unchanged() -> None:
    old: set[str] = set()
    for p in [*OLD_FR.glob("*.py"), OLD / "api" / "routers" / "founder_radar.py", OLD / "domain" / "people.py"]:
        old |= _literals(p)
    for module in PORTED:
        src = Path(module.__file__ or "")
        tree = ast.parse(src.read_text(encoding="utf-8"))
        docs = {id(n.body[0].value) for n in ast.walk(tree)  # docstrings are commentary, not the old data
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr)}  # fmt: skip
        ours = {n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs}  # fmt: skip
        new_only = sorted(v for v in ours if v not in old and v not in NEW_TEXTS and not v.startswith("__"))
        assert new_only == [], (src.name, new_only[:8])


def test_provenance_and_inputs_are_current() -> None:
    assert GOLDEN["provenance"]["old_revision"] == "6c739b9cb6ca2517b845e381d39a36c50eccc59e"
    assert GOLDEN["provenance"]["old_dirty"] is False
    assert GOLDEN["provenance"]["hashseed"] == "0"
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
    dom = research_doc()["domains"][LARK]
    for part in ("proposals", "pages", "pairings"):
        keys = list(dom[part])
        assert len(keys) == 1 or keys != jsonb_order(keys), part
    assert list(dom["proposals"]) != jsonb_order(list(dom["proposals"]))


def test_the_goldens_cover_what_the_plan_names() -> None:
    steps = expand(GOLDEN["sets"]["main"]["expected"])
    answers = [(sp, st["answer"]) for sp, st in zip(STEPS, steps, strict=True)]
    errors = {str((a.get("body") or {}).get("error")) for _sp, a in answers if isinstance(a.get("body"), dict)}
    for text in ("unknown person", "unknown action", "Resolve identity before promotion", "unknown proposal",
                 "only pending founder proposals can be paired", "selected record is not a founder reference of this company",
                 "company key required", "explicit confirmation required", "nothing researched for this company yet"):  # fmt: skip
        assert text in errors, text
    assert any(e.startswith("merge refused: conflicting github_id") for e in errors)
    assert any("pairing refused" in e for e in errors) and any(e.startswith("malformed founder") for e in errors)
    assert {"raises": "ValueError"} in [a for _sp, a in answers]  # (f): the old unknown state
    final = steps[-2]["answer"]["body"]  # the proposals read after the reviews
    assert (
        next(iter(final["pairings"])) == "an-earlier-pairing-with-a-long-identifier"
        and list(final["pairings"])[-1] == "fz"
    )
    assert list(final["pages"]) == list(research_doc()["domains"][LARK]["pages"])
    assert [p["id"] for p in final["proposals"]] == list(research_doc()["domains"][LARK]["proposals"])
    stored = [st for st in steps if "stored" in st][-1]["stored"]
    assert list(stored["radar_research.json"]["domains"][LARK]["proposals"]) == list(
        research_doc()["domains"][LARK]["proposals"]
    )
    people = {p["id"]: p for p in stored["people.json"]["people"]}
    assert WENNA_B not in people and WENNA_A in people  # (c) the merged person is absent
    teo = people[TEODOR]  # Codex H-204: verify_identity's evidence survives the final identity_evidence recomputation
    assert any(
        e.get("category") == "identity" and e.get("claim") == "Teodor Vanstrel heads the lab" for e in teo["evidence"]
    )
    assert not any("operator verified with public evidence" in x for x in teo["identity_evidence"])
    assert people[ZORVIK]["name"] == "Zorvik Talmadge" and people[RHEA]["identity_verified_by"] == "operator"
    review_answer = next(a["body"] for sp, a in answers if sp["op"] == "review" and a["body"].get("identity_bound"))
    assert {b["person"] for b in review_answer["identity_bound"]} == {RHEA, ZORVIK}
    assert review_answer["refused"] == ["recent_activity"]
    imports = [a["body"] for sp, a in answers if sp["op"] == "import"]
    assert {i["format"] for i in imports} == {"custom", "linkedin_connections"}
    assert imports[0]["merged"] == 1 and imports[0]["new"] == 2 and imports[0]["unresolved"] == 2
    later = expand(GOLDEN["sets"]["later"]["expected"])[0]["answer"]["body"]
    assert later["metrics"]["date"] == "2026-11-20"

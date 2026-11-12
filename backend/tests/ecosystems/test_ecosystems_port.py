"""Review 022, offline: the catalog and the ported logic carry the old literals, the shipped coverage files are the old
bytes, and the pure city / registry / coverage / adopt functions match the OLD code's goldens
(``oracle_ecosystems.json``, ``python -m projectzero.ops.parity_ecosystems goldens``)."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from projectzero.ecosystems import adopt, catalog, cities, coverage, inputs
from projectzero.ops.parity_ecosystems import CLOCK, SETS, STEPS, compare_goldens, corpus, expand
from projectzero.ops.parity_ranking import OLD_REPO

GOLDEN: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "golden_v1" / "oracle_ecosystems.json").read_text(
        encoding="utf-8"
    )
)
OLD = OLD_REPO / "backend" / "src" / "projectzero"
SHIPPED = {  # the old resources/coverage files at 6c739b9, copied byte-for-byte
    "PROJECT_ZERO_EUROPEAN_COVERAGE_AUDIT.md": "db8025daed3d02b8120b5628a34e69b5598fcf574757eb371dec0a428f39529f",
    "PROJECT_ZERO_SOURCE_REGISTRY_CANDIDATE.json": "532c3d342fb70a81163e58475199ca252dfb4f08771b552463d287798e39c396",
    "PROJECT_ZERO_SOURCE_REGISTRY_CANDIDATE_PARIS_STATIONF.json": (
        "f3cf13a185595eeb7c2fa933eb7f78cdbbb9b22b1e808d735be206c08e25e5ba"
    ),
}
ROW_KEYS = {"candidate_id", "adopted_at"}  # the coverage_adoptions row (plan revision 2): the only new names


def _literals(path: Path) -> set[str]:
    return {n.value for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}  # fmt: skip


@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_catalog_and_the_ported_logic_carry_the_old_literals_unchanged() -> None:
    domain = OLD / "domain"
    old = set().union(*(_literals(p) for p in (domain / "ecosys.py", domain / "coverage.py",
                                               domain / "founder_radar" / "sources.py",
                                               domain / "founder_radar" / "store.py",
                                               domain / "event_sources.py")))  # fmt: skip
    for module, allowed in ((catalog, set()), (cities, set()), (coverage, set()), (adopt, ROW_KEYS)):
        src = Path(module.__file__ or "")
        tree = ast.parse(src.read_text(encoding="utf-8"))
        docs = {id(n.body[0].value) for n in ast.walk(tree)  # docstrings are commentary, not the old data
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr)}  # fmt: skip
        ours = {n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs}  # fmt: skip
        new_only = sorted(v for v in ours if v not in old and v not in allowed)
        assert new_only == [], (src.name, new_only[:5])


def test_the_shipped_coverage_files_are_the_old_bytes() -> None:
    folder = inputs.RESOURCES
    assert sorted(p.name for p in folder.iterdir()) == sorted(SHIPPED)
    for name, digest in SHIPPED.items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, name
        old = OLD / "resources" / "coverage" / name
        if old.exists():
            assert old.read_bytes() == (folder / name).read_bytes(), name
    assert [n for n, _ in inputs.shipped_candidates()] == sorted(n for n in SHIPPED if n.endswith(".json"))
    assert [n for n, _ in inputs.audit_docs()] == ["PROJECT_ZERO_EUROPEAN_COVERAGE_AUDIT.md"]


def test_provenance_and_inputs_are_current() -> None:
    assert GOLDEN["provenance"]["old_revision"] == "6c739b9cb6ca2517b845e381d39a36c50eccc59e"
    assert GOLDEN["provenance"]["old_dirty"] is False
    assert GOLDEN["clock"] == CLOCK
    assert GOLDEN["sets"]["main"]["docs"] == json.loads(json.dumps(corpus()))
    assert GOLDEN["sets"]["main"]["steps"] == STEPS
    assert set(GOLDEN["sets"]) == set(SETS)


def test_the_pure_port_matches_the_old_code() -> None:
    assert compare_goldens(GOLDEN) == []


def test_the_goldens_cover_what_the_plan_names() -> None:
    main = expand(GOLDEN["sets"]["main"]["expected"])
    names = [c["name"] for c in main["registry"]["ok"]["cities"]]
    assert set(main["eco"]) == {*names, "Nowhere-on-Sea", ""}
    assert main["eco"]["Heidelberg"] == {"raises": "TypeError"}  # decision b: an unknown earliness raises
    assert any(not c["curated"] for c in main["registry"]["ok"]["cities"])  # detected cities
    cov = main["coverage"]["ok"]
    states = {f["state"] for e in cov["ecosystems"] for f in e["families"].values()}
    assert states == {"HEALTHY", "PARTIAL", "GAP", "UNKNOWN"}
    by_city = {e["city"]: e for e in cov["ecosystems"]}
    assert {"Quellbrunn", "Nordhafen"} <= set(by_city)  # coverage_registry.json and ecosystems.json
    assert by_city["Nordhafen"]["overall"] == "HEALTHY" and cov["sources_with_override"] == 3
    assert cov["new_ecosystems"][0]["place"] == "Glimmerton"
    variant = expand(GOLDEN["sets"]["variant"]["expected"])["coverage"]["ok"]["counts"]
    assert variant["GAP"] and variant["UNKNOWN"]
    assert GOLDEN["sets"]["broken_regions"]["expected"]["coverage"] == {"raises": "ValueError"}
    bodies = [s["body"]["ok"] for s in main["steps"]]
    assert bodies[7] == {"ok": True, "already": True, "source_id": "cov-legacy-historic"}  # the historical retry
    assert bodies[8] == {"ok": False, "error": "explicit confirmation required"}

"""Cut the Validation catalog from the OLD modules by exact line ranges (review 027a). Nothing is retyped.

    backend/.venv/Scripts/python.exe scripts/gen_validation_catalog.py   # PZ_OLD_REPO: the old checkout (a sibling)

Top-level constants of the old ``services/validation.py`` (the log names, ``MIN_N``, the outcome kinds and their
groups, the miss reasons and false-positive causes, the evidence classes, the stages and their labels, the miss types,
the source-value weights and the benchmark column vocabularies) and the routing ``STATES`` of the old
``services/compressor.py`` (read by ``compressor.metrics``, ported in ``validation/routing.py``) are cut whole: the
exact source lines of each assignment. Each cut is checked: its text compiles, and its syntax tree equals the old
node's (positions aside).
"""

import ast
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
OLD_REPO = pathlib.Path(os.environ.get("PZ_OLD_REPO", str(ROOT.parent / "project-zero")))
OLD = OLD_REPO / "backend" / "src" / "projectzero"
VALIDATION = OLD / "services" / "validation.py"
COMPRESSOR = OLD / "services" / "compressor.py"
NEW = ROOT / "backend" / "src" / "projectzero" / "validation"
VALIDATION_NAMES = ["OUTCOMES", "AUDITS", "SNAPSHOTS", "SCOUT_LOG", "MIN_N", "POSITIVE_KINDS", "NEGATIVE_KINDS",
                    "BENCHMARK_KINDS", "KINDS", "LEAD_KINDS", "REAL_WORLD_STRONG", "MISS_REASONS", "FP_CAUSES",
                    "EVIDENCE_CLASS", "STAGES", "STAGE_LABEL", "MISS_TYPES", "VALUE_WEIGHTS", "SMOOTH",
                    "BENCHMARK_KINDS_ALL", "_NAME_COLS", "_DATE_COLS"]  # fmt: skip
COMPRESSOR_NAMES = ["STATES"]


def _same(a: ast.AST, b: ast.AST) -> bool:
    return ast.dump(a) == ast.dump(b)  # include_attributes=False: positions are ignored


def cut(path: pathlib.Path, names: list[str]) -> str:
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    found: dict[str, str] = {}
    for node in ast.parse(src).body:
        name = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        if name in names:
            assert name not in found, name  # one top-level assignment per name
            text = "".join(lines[node.lineno - 1 : node.end_lineno])
            assert _same(ast.parse(text).body[0], node), name  # the cut compiles and is the old statement
            found[name] = text
    missing = [n for n in names if n not in found]
    assert not missing, (path.name, missing)
    return "".join(found[n] for n in names)


catalog = (
    '''# (protected gold-master data, copied by script from the old modules; see the header)
"""The Validation catalog (review 027a): constants cut MECHANICALLY from the old ``services/validation.py`` and
``services/compressor.py`` at revision 6c739b9 by exact line ranges (``scripts/gen_validation_catalog.py``); nothing
is retyped. ``tests/validation/test_validation_port.py`` checks every cut against the old modules. Pure data.

From ``validation.py`` (top level): the four log names (``OUTCOMES``, ``AUDITS``, ``SNAPSHOTS``, ``SCOUT_LOG``),
``MIN_N``, the outcome kinds (``POSITIVE_KINDS``, ``NEGATIVE_KINDS``, ``BENCHMARK_KINDS``, ``KINDS`` in that order:
the select order), ``LEAD_KINDS``, ``REAL_WORLD_STRONG``, ``MISS_REASONS``, ``FP_CAUSES``, ``EVIDENCE_CLASS``,
``STAGES`` (the table columns), ``STAGE_LABEL``, ``MISS_TYPES``, ``VALUE_WEIGHTS`` / ``SMOOTH`` (the source ranking),
``BENCHMARK_KINDS_ALL`` and the benchmark column names (``_NAME_COLS``, ``_DATE_COLS``). From ``compressor.py``: the
routing ``STATES``.
"""

from __future__ import annotations

# fmt: off
# ── from services/validation.py ──
'''
    + cut(VALIDATION, VALIDATION_NAMES)
    + "# ── from services/compressor.py ──\n"
    + cut(COMPRESSOR, COMPRESSOR_NAMES)
    + "# fmt: on\n"
)
for old, new in (  # type hints only
    ("\nEVIDENCE_CLASS = {", "\nEVIDENCE_CLASS: dict[int, str] = {"),
    ("\nVALUE_WEIGHTS = {", "\nVALUE_WEIGHTS: dict[str, float] = {"),
):
    assert catalog.count(old) == 1, old
    catalog = catalog.replace(old, new)
compile(catalog, "catalog.py", "exec")
NEW.mkdir(parents=True, exist_ok=True)
(NEW / "catalog.py").write_text(catalog, encoding="utf-8", newline="\n")
print("catalog.py", len(catalog.splitlines()), "lines")

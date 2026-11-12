"""Cut the Active Evaluator catalog from the OLD module by exact top-level line ranges (review 024). Nothing is retyped.

    backend/.venv/Scripts/python.exe scripts/gen_evaluator_catalog.py   # PZ_OLD_REPO: the old checkout (a sibling)

Top-level constants of the old ``domain/evaluator.py`` are cut whole (the exact source lines of each assignment): the
labels and states, the rubric ``FAMILIES`` (+ ``FAM``), the classification / number / count / negation patterns and
the canonical first-call mapping. ``TIMING_KINDS`` is not cut here: ``conviction.imq`` already carries it (review 011).
Annotations are added by text replacement only (type hints, no values).
"""

import ast
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
OLD_REPO = pathlib.Path(os.environ.get("PZ_OLD_REPO", str(ROOT.parent / "project-zero")))
OLD = OLD_REPO / "backend" / "src" / "projectzero" / "domain" / "evaluator.py"
NEW = ROOT / "backend" / "src" / "projectzero" / "evaluator"
NAMES = ["FILE_NAME", "STATES", "DECK_LABEL", "FOUNDER_LABEL", "UNKNOWN", "FAMILIES", "FAM", "_FAM_WORDS", "_NUM",
         "_MATERIAL", "_WORDNUM", "_COUNT_NOUNS", "_COUNT_RX", "_NEG_RX", "CANONICAL_MAP"]  # fmt: skip


def cut(path: pathlib.Path, names: list[str]) -> str:
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    found: dict[str, str] = {}
    for node in ast.parse(src).body:
        target = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else None
        if isinstance(target, ast.Name) and target.id in names:
            found[target.id] = "".join(lines[node.lineno - 1 : node.end_lineno])
    missing = [n for n in names if n not in found]
    assert not missing, (path.name, missing)
    return "".join(found[n] for n in names)


catalog = (
    '''# ruff: noqa: E501
# (protected gold-master data, copied by script from the old module; see the header)
"""The Active Evaluator catalog (review 024): constants cut MECHANICALLY from the old ``domain/evaluator.py`` at
revision 6c739b9 by exact top-level line ranges (``scripts/gen_evaluator_catalog.py``); nothing is retyped.
``tests/evaluator/test_evaluator_port.py`` checks every cut against the old module. Pure data.

``FILE_NAME``, ``STATES``, the labels (``DECK_LABEL``, ``FOUNDER_LABEL``, ``UNKNOWN``), the rubric ``FAMILIES``
``(id, label, rubric dimension, base priority, opening question, verification hint)`` and ``FAM`` (by id), the
family keyword rules ``_FAM_WORDS``, the patterns ``_NUM`` / ``_MATERIAL`` / ``_COUNT_RX`` / ``_NEG_RX`` (with
``_WORDNUM`` and ``_COUNT_NOUNS``) and ``CANONICAL_MAP`` (rubric families -> the six first-call sections).
"""

from __future__ import annotations

import re

# fmt: off
'''
    + cut(OLD, NAMES)
    + "# fmt: on\n"
)
for old, new in (
    ("\n_WORDNUM = {", "\n_WORDNUM: dict[str, int] = {"),
    ("\nCANONICAL_MAP = {", "\nCANONICAL_MAP: dict[str, list[str]] = {"),
):  # type hints only
    assert catalog.count(old) == 1, old
    catalog = catalog.replace(old, new)
(NEW / "catalog.py").write_text(catalog, encoding="utf-8", newline="\n")
print("catalog.py", len(catalog.splitlines()), "lines")

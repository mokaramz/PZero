"""Cut the Founder Radar catalog from the OLD modules by exact top-level line ranges (review 026a). Nothing is retyped.

    backend/.venv/Scripts/python.exe scripts/gen_founder_radar_catalog.py   # PZ_OLD_REPO: the old checkout (a sibling)

Top-level constants of the old ``domain/founder_radar/*.py`` are cut whole (the exact source lines of each assignment,
comments inside the range included), module by module, in the order of ``CUTS``. Each cut is checked: its text
compiles and its syntax tree equals the old node's (positions aside). One function is cut too: ``_theme_terms``
(``constants.py`` 64-89), the read-only Taste Map theme terms. Its only change (decision b of review 026a) is the last
line: ``return sorted(terms)`` instead of ``return terms``, so ``research_priority`` lists the overlapping themes in
one order in every process (a ``set`` iterated in a per-process hash order). ``DEFAULT_REGIONS``,
``DEFAULT_SOURCES`` and ``SOURCES_SCHEMA`` (``sources.py``) are already cut into ``ecosystems/catalog.py`` (review
022) and are re-exported, not cut again. Annotations are added by text replacement only (type hints, no values).
"""

import ast
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
OLD_REPO = pathlib.Path(os.environ.get("PZ_OLD_REPO", str(ROOT.parent / "project-zero")))
OLD = OLD_REPO / "backend" / "src" / "projectzero" / "domain" / "founder_radar"
NEW = ROOT / "backend" / "src" / "projectzero" / "founder_radar"
CUTS = [  # (old module, top-level names in the order they are written)
    ("constants.py", ["STATES", "NETWORK_STATES", "NEI", "RADAR_FIELDS", "_theme_terms", "_FOUNDER_CLAIM", "BUCKETS",
                      "QUEUE_LABELS", "EARLY_STAGES", "DECISION_FIELDS"]),
    ("names.py", ["_PLACEHOLDER", "_ROLE_ONLY", "_ORG_WORDS", "_HEADING_WORDS", "_HEADING_FIRST", "_NAME_NOISE"]),
    ("records.py", ["_HUMAN_KEYS"]),
    ("identity.py", ["_FOUNDED_STOP", "_FOUNDED_BY_ROUTES"]),
    ("companies.py", ["_NON_OFFICIAL"]),
    ("leads.py", ["HUMAN", "UNKNOWN_LABELS"]),
    ("sources.py", ["BATCH_SIZE", "LEGACY_GITHUB_IDS", "SOURCE_ROLE"]),
    ("extraction.py", ["_MONTHS", "_TEMPLATE_WORDS", "_DATE", "_FOUNDED", "_FUNDING", "_EARLY", "_HIRING", "_ACTIVE",
                       "_OPERATING", "_NAME", "_ROLE", "_FOUNDER_LINE", "_FOUNDER_LINE2", "_FOUNDED_BY",
                       "_NAMES_FOUNDED", "_LI_PROFILE", "_GH_ORG", "MACHINE_INFERENCE_FIELDS", "WHY_EXTRA", "WHY"]),
    ("collectors.py", ["_ENTRE", "_TRANSITION"]),
    ("fetch.py", ["MAX_BODY", "MAX_REDIRECTS", "LINK_PRIORITY"]),
    ("research.py", ["CRAWL_PATHS", "MAX_PAGES"]),
    ("store.py", ["SOURCES", "HEALTH", "METRICS", "REGIONS", "CURSOR", "MIGRATION", "COMPANIES", "RESEARCH",
                  "RESEARCH_QUEUE"]),
]  # fmt: skip
HINTS = [  # type hints only (old text -> new text), each exactly once
    ("\ndef _theme_terms():\n    terms = set()\n", "\ndef _theme_terms() -> list[str]:\n    terms: set[str] = set()\n"),
    ("\nQUEUE_LABELS = {", "\nQUEUE_LABELS: dict[str, str] = {"),
    ("\n_HEADING_WORDS = {", "\n_HEADING_WORDS: set[str] = {"),
    ("\n_HEADING_FIRST = {", "\n_HEADING_FIRST: set[str] = {"),
    ("\n_NAME_NOISE = {", "\n_NAME_NOISE: set[str] = {"),
    ("\nHUMAN = {", "\nHUMAN: dict[str, Callable[[Any], str]] = {"),
    ("\nUNKNOWN_LABELS = {", "\nUNKNOWN_LABELS: dict[str, str] = {"),
    ("\nSOURCE_ROLE = {", "\nSOURCE_ROLE: dict[str, str] = {"),
    ("\n_TEMPLATE_WORDS = {", "\n_TEMPLATE_WORDS: set[str] = {"),
    ("\nWHY_EXTRA = {", "\nWHY_EXTRA: dict[str, str] = {"),
    ("\nWHY = {", "\nWHY: dict[str, str] = {"),
]
SORTED = (
    "\n    return terms\n",
    "\n    return sorted(terms)  # decision b (review 026a): one order in every process\n",
)


def _same(a: ast.AST, b: ast.AST) -> bool:
    return ast.dump(a) == ast.dump(b)  # include_attributes=False: positions are ignored


def _name(node: ast.stmt) -> str | None:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    if isinstance(node, ast.FunctionDef):
        return node.name
    return None


def cut(path: pathlib.Path, names: list[str]) -> str:
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    found: dict[str, str] = {}
    for node in ast.parse(src).body:
        name = _name(node)
        if name in names:
            text = "".join(lines[node.lineno - 1 : node.end_lineno])
            assert _same(ast.parse(text).body[0], node), name  # the cut compiles and is the old statement
            found[name] = text + ("\n\n" if isinstance(node, ast.FunctionDef) else "")
    missing = [n for n in names if n not in found]
    assert not missing, (path.name, missing)
    return "".join(found[n] for n in names)


def build() -> str:
    body = "".join(f"# ── from domain/founder_radar/{mod} ──\n" + cut(OLD / mod, names) for mod, names in CUTS)
    catalog = (
        '''# ruff: noqa: E501, RUF001
# (protected gold-master data, copied by script from the old modules; see the header)
"""The Founder Radar catalog (review 026a): constants cut MECHANICALLY from the old ``domain/founder_radar/*.py`` at
revision 6c739b9 by exact top-level line ranges (``scripts/gen_founder_radar_catalog.py``); nothing is retyped.
``tests/founder_radar/test_founder_radar_port.py`` checks every cut against the old modules. Pure data.

``constants.py``: the states, buckets, decision fields and ``_theme_terms`` (the one function cut; it returns a SORTED
list, decision b). ``names.py``: the placeholder / role / organisation / heading patterns and word sets.
``records.py`` ``_HUMAN_KEYS``; ``identity.py`` the founded-by patterns; ``companies.py`` ``_NON_OFFICIAL``;
``leads.py`` ``HUMAN`` / ``UNKNOWN_LABELS``; ``sources.py`` ``BATCH_SIZE`` / ``LEGACY_GITHUB_IDS`` / ``SOURCE_ROLE``
(the region and source defaults are ``ecosystems.catalog``'s, re-exported here); ``extraction.py`` its patterns and
tables; ``collectors.py``, ``fetch.py`` and ``research.py`` the constants review 026b will use; ``store.py`` the
document names.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from projectzero.conviction import taste
from projectzero.ecosystems.catalog import DEFAULT_REGIONS as DEFAULT_REGIONS
from projectzero.ecosystems.catalog import RADAR_DEFAULT_SOURCES as DEFAULT_SOURCES
from projectzero.ecosystems.catalog import SOURCES_SCHEMA as SOURCES_SCHEMA

__all__ = ["DEFAULT_REGIONS", "DEFAULT_SOURCES", "SOURCES_SCHEMA"]

# fmt: off
'''
        + body
        + "# fmt: on\n"
    )
    for old, new in HINTS:
        assert catalog.count(old) == 1, old
        catalog = catalog.replace(old, new)
    assert catalog.count(SORTED[0]) == 1
    catalog = catalog.replace(*SORTED)
    compile(catalog, "catalog.py", "exec")
    return catalog


if __name__ == "__main__":
    text = build()
    NEW.mkdir(parents=True, exist_ok=True)
    (NEW / "catalog.py").write_text(text, encoding="utf-8", newline="\n")
    print("catalog.py", len(text.splitlines()), "lines")

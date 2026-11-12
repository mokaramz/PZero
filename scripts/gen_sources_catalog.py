"""Cut the Sources catalog from the OLD modules by exact top-level line ranges (review 021). Nothing is retyped.

    backend/.venv/Scripts/python.exe scripts/gen_sources_catalog.py   # PZ_OLD_REPO = the old checkout (default: a sibling)
"""

import ast
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
OLD_REPO = pathlib.Path(os.environ.get("PZ_OLD_REPO", str(ROOT.parent / "project-zero")))
OLD = OLD_REPO / "backend" / "src" / "projectzero" / "domain"
NEW = ROOT / "backend" / "src" / "projectzero" / "dealflow" / "sources"


def cut(path: pathlib.Path, names: list[str]) -> str:
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    tree = ast.parse(src)
    found: dict[str, str] = {}
    for node in tree.body:
        name = None
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        if name in names:
            start = node.lineno - 1
            if getattr(node, "decorator_list", None):
                start = min(d.lineno for d in node.decorator_list) - 1
            found[name] = "".join(lines[start : node.end_lineno])
    missing = [n for n in names if n not in found]
    assert not missing, (path.name, missing)
    return "\n\n".join(found[n].rstrip() for n in names) + "\n"


connectors = OLD / "connectors.py"
sources_v2 = OLD / "sources_v2.py"

catalog = (
    '''# ruff: noqa: E501
# (protected gold-master data and repairs, copied by script from the old modules; see the header)
"""The Deal Flow source catalog (review 021): constants and registry repairs cut MECHANICALLY from the old
``domain/connectors.py`` and ``domain/sources_v2.py`` at revision 6c739b9 by exact top-level line ranges
(``scripts/gen_sources_catalog.py``); nothing is retyped. ``tests/dealflow/test_sources_catalog.py`` checks every
string literal against the old modules. Pure data and pure functions: no I/O.

From ``connectors.py``: the hardcoded lists the old inbox served (``PRE_COMPANY_PAGES``, ``FEEDS``,
``MANUAL_SOURCES``), the coverage constants (``KIND_WEIGHT``, ``GEOS``, ``GEO_LABEL``, ``SECTORS``,
``SECTOR_LABEL``), the read-time ``_REPAIRS``. From ``sources_v2.py``: ``URL_REPAIRS``, ``URL_REPAIRS_MULTI``,
``NOTE_REPAIRS`` and ``registry_entries()``.
"""

from __future__ import annotations

from typing import Any

# fmt: off
'''
    + "# ── from domain/connectors.py ──\n"
    + cut(connectors, ["PRE_COMPANY_PAGES", "FEEDS", "MANUAL_SOURCES", "KIND_WEIGHT", "GEOS", "GEO_LABEL",
                       "SECTORS", "SECTOR_LABEL", "_REPAIRS"])
    + "\n\n# ── from domain/sources_v2.py ──\n"
    + cut(sources_v2, ["URL_REPAIRS", "URL_REPAIRS_MULTI", "NOTE_REPAIRS", "registry_entries"])
    + "# fmt: on\n"
)
catalog = catalog.replace("def registry_entries():", "def registry_entries() -> list[dict[str, Any]]:")  # a type hint only
(NEW / "catalog.py").write_text(catalog, encoding="utf-8", newline="\n")
print("catalog.py", len(catalog.splitlines()), "lines")

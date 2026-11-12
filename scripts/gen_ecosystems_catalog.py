"""Cut the Ecosystems catalog from the OLD modules by exact top-level line ranges (review 022). Nothing is retyped.

    backend/.venv/Scripts/python.exe scripts/gen_ecosystems_catalog.py   # PZ_OLD_REPO: the old checkout (a sibling)

Top-level constants are cut whole (decorators and comments inside the range included). The one constant the old code
kept INSIDE a function (the city notes of ``ecosys.city_page``) is cut from that function's ``note = {...}.get(city,
"")`` statement: the dict literal's exact source lines, dedented by the function's indentation. Annotations are added
by text replacement only (type hints, no values).
"""

import ast
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
OLD_REPO = pathlib.Path(os.environ.get("PZ_OLD_REPO", str(ROOT.parent / "project-zero")))
OLD = OLD_REPO / "backend" / "src" / "projectzero" / "domain"
NEW = ROOT / "backend" / "src" / "projectzero" / "ecosystems"


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


def cut_inner_dict(path: pathlib.Path, func: str, target: str, as_name: str) -> str:
    """``<target> = {...}.get(...)`` inside ``func``: the dict literal's exact lines, dedented, as ``as_name``."""
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == func)
    stmt = next(
        n for n in fn.body
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == target
    )
    call = stmt.value
    assert isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "get"
    d = call.func.value
    assert isinstance(d, ast.Dict) and d.lineno == stmt.lineno, (func, target)
    first = lines[d.lineno - 1][d.col_offset :]
    body = lines[d.lineno : d.end_lineno - 1]
    last = lines[d.end_lineno - 1][: d.end_col_offset]
    indent = stmt.col_offset
    assert all(ln[:indent].strip() == "" for ln in [*body, last]), "unexpected indentation"
    text = first + "".join(ln[indent:] for ln in body) + last[indent:]
    return f"{as_name} = {text}\n"


ecosys = OLD / "ecosys.py"
coverage = OLD / "coverage.py"
radar_sources = OLD / "founder_radar" / "sources.py"

catalog = (
    '''# ruff: noqa: E501
# (protected gold-master data, copied by script from the old modules; see the header)
"""The Ecosystems catalog (review 022): constants cut MECHANICALLY from the old ``domain/ecosys.py``,
``domain/coverage.py`` and ``domain/founder_radar/sources.py`` at revision 6c739b9 by exact top-level line ranges
(``scripts/gen_ecosystems_catalog.py``); nothing is retyped. ``tests/ecosystems/test_ecosystems_port.py`` checks every
string literal against the old modules. Pure data: no I/O.

From ``ecosys.py``: ``CITIES``, ``ORGS`` and ``CITY_NOTES`` (the notes dict of ``city_page``). From ``coverage.py``:
the document names, families, states, labels, thresholds, ``DEFAULT_ECOSYSTEMS``, ``COUNTRY_NAMES``, ``_ALIASES``,
``_SCOPES``, ``_CC``. From ``founder_radar/sources.py``: ``DEFAULT_REGIONS``, its ``DEFAULT_SOURCES`` (named
``RADAR_DEFAULT_SOURCES`` here) and ``SOURCES_SCHEMA`` (Founder Radar is not ported; coverage reads its documents).
"""

from __future__ import annotations

from typing import Any

# fmt: off
'''
    + "# ── from domain/ecosys.py ──\n"
    + cut(ecosys, ["CITIES", "ORGS"])
    + "\n\n"
    + cut_inner_dict(ecosys, "city_page", "note", "CITY_NOTES")
    + "\n\n# ── from domain/coverage.py ──\n"
    + cut(coverage, ["REGISTRY_FILE", "SOURCE_DECL_FILE", "ADOPTED_FILE", "_AUDIT_FAMILY", "FAMILIES", "STATES",
                     "LABEL_ZERO_HEALTHY", "LABEL_ZERO_INSUFFICIENT", "LABEL_NEW", "FRESH_DAYS", "PRODUCTIVE_DAYS",
                     "NEW_ECOSYSTEM_MIN", "DEFAULT_ECOSYSTEMS", "COUNTRY_NAMES", "_ALIASES", "_SCOPES", "_CC"])
    + "\n\n# ── from domain/founder_radar/sources.py ──\n"
    + cut(radar_sources, ["DEFAULT_REGIONS", "DEFAULT_SOURCES", "SOURCES_SCHEMA"])
    + "# fmt: on\n"
)
for old, new in (  # type hints and the one rename only
    ("\nORGS = [", "\nORGS: list[dict[str, Any]] = ["),
    ("CITY_NOTES = {", "CITY_NOTES: dict[str, str] = {"),
    ("\n_SCOPES = {", "\n_SCOPES: dict[str, set[str] | None] = {"),
    ("\nDEFAULT_REGIONS = [", "\nDEFAULT_REGIONS: list[dict[str, Any]] = ["),
    ("\nDEFAULT_SOURCES = [", "\nRADAR_DEFAULT_SOURCES: list[dict[str, Any]] = ["),
):
    assert catalog.count(old) == 1, old
    catalog = catalog.replace(old, new)
(NEW / "catalog.py").write_text(catalog, encoding="utf-8", newline="\n")
print("catalog.py", len(catalog.splitlines()), "lines")

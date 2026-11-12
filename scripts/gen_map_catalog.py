"""Cut the Map catalog from the OLD modules by exact line ranges (review 025). Nothing is retyped.

    backend/.venv/Scripts/python.exe scripts/gen_map_catalog.py   # PZ_OLD_REPO: the old checkout (a sibling)

Top-level constants of the old ``services/geo_intel.py`` and ``api/routers/home.py`` (lines 25-26) are cut whole (the
exact source lines of each assignment, comments inside the range included). The texts the old code kept INSIDE a
function (the legend of ``view``, the two notes of ``where_to_go``, ``bring_back`` and the plan note of
``sourcing_day``) are cut from that function's return-dict entry: the value's exact source lines, re-indented inside
parentheses. Each cut is checked: its text compiles, and its syntax tree equals the old node's (positions aside).
``GAZETTEER`` (``events.engine``) and ``ORGS`` / ``CITIES`` (``ecosystems.catalog``) are already ported and reused.
Annotations are added by text replacement only (type hints, no values).
"""

import ast
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
OLD_REPO = pathlib.Path(os.environ.get("PZ_OLD_REPO", str(ROOT.parent / "project-zero")))
OLD = OLD_REPO / "backend" / "src" / "projectzero"
GEO = OLD / "services" / "geo_intel.py"
HOME = OLD / "api" / "routers" / "home.py"
NEW = ROOT / "backend" / "src" / "projectzero" / "map"
GEO_NAMES = ["ACTIVITY_DAYS", "MAX_PER_SOURCE", "EVENT_DAYS", "STATES", "FAMILY_LABEL", "COVERAGE_LABEL", "COV_WORD",
             "NOTE", "COORDS", "SUBLOCAL", "_UI_TEXT", "_ABROAD", "_SCOUT_FAMILY", "_SRC_FAMILY", "_NEWS_FAMILY",
             "HOME_DEFAULT"]  # fmt: skip
HOME_NAMES = ["DEFAULT_HOME_BASE", "OPERATOR_ID"]
INNER = [  # (new name, old function, return-dict key, occurrence of that key inside the function)
    ("LEGEND", "view", "legend", 0),
    ("WHERE_TO_GO_EMPTY_NOTE", "where_to_go", "note", 0),
    ("WHERE_TO_GO_NOTE", "where_to_go", "note", 1),
    ("BRING_BACK", "sourcing_day", "bring_back", 0),
    ("PLAN_NOTE", "sourcing_day", "note", 0),
]


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
            text = "".join(lines[node.lineno - 1 : node.end_lineno])
            assert _same(ast.parse(text).body[0], node), name  # the cut compiles and is the old statement
            found[name] = text
    missing = [n for n in names if n not in found]
    assert not missing, (path.name, missing)
    return "".join(found[n] for n in names)


def cut_inner(path: pathlib.Path, func: str, key: str, occurrence: int, as_name: str) -> str:
    """The value of the ``occurrence``-th ``key: value`` dict entry inside ``func``, as ``as_name = (value)``."""
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == func)
    values = [v for d in ast.walk(fn) if isinstance(d, ast.Dict)
              for k, v in zip(d.keys, d.values, strict=True)
              if isinstance(k, ast.Constant) and k.value == key]  # fmt: skip
    values.sort(key=lambda v: (v.lineno, v.col_offset))
    v = values[occurrence]
    raw = [ln.encode("utf-8") for ln in lines]  # ast offsets count UTF-8 bytes
    first = raw[v.lineno - 1][v.col_offset :].decode("utf-8")
    if v.lineno == v.end_lineno:
        text = raw[v.lineno - 1][v.col_offset : v.end_col_offset].decode("utf-8")
    else:
        body = lines[v.lineno : v.end_lineno - 1]
        last = raw[v.end_lineno - 1][: v.end_col_offset].decode("utf-8")
        rest = [*body, last]
        indent = min(len(ln) - len(ln.lstrip()) for ln in rest if ln.strip())
        text = first + "".join("    " + ln[indent:] if ln.strip() else ln for ln in rest)
    out = f"{as_name} = (\n    {text.rstrip()}\n)\n"
    stmt = ast.parse(out).body[0]
    assert isinstance(stmt, ast.Assign) and _same(stmt.value, v), as_name  # the cut compiles and is the old value
    return out


catalog = (
    '''# ruff: noqa: E501
# (protected gold-master data, copied by script from the old modules; see the header)
"""The Map catalog (review 025): constants cut MECHANICALLY from the old ``services/geo_intel.py`` and
``api/routers/home.py`` at revision 6c739b9 by exact line ranges (``scripts/gen_map_catalog.py``); nothing is retyped.
``tests/map/test_map_port.py`` checks every cut against the old modules. Pure data.

From ``geo_intel.py`` (top level): the windows (``ACTIVITY_DAYS``, ``MAX_PER_SOURCE``, ``EVENT_DAYS``), ``STATES``,
``FAMILY_LABEL``, ``COVERAGE_LABEL``, ``COV_WORD``, ``NOTE``, ``COORDS``, ``SUBLOCAL``, the ``_UI_TEXT`` / ``_ABROAD``
patterns, the ``_SCOUT_FAMILY`` / ``_SRC_FAMILY`` / ``_NEWS_FAMILY`` maps and ``HOME_DEFAULT``; from inside its
functions: ``LEGEND`` (``view``), ``WHERE_TO_GO_EMPTY_NOTE`` / ``WHERE_TO_GO_NOTE`` (``where_to_go``), ``BRING_BACK``
and ``PLAN_NOTE`` (``sourcing_day``). From ``home.py`` (lines 25-26): ``DEFAULT_HOME_BASE`` and ``OPERATOR_ID``.
"""

from __future__ import annotations

import re
from typing import Any

# fmt: off
# ── from services/geo_intel.py ──
'''
    + cut(GEO, GEO_NAMES)
    + "".join(cut_inner(GEO, f, k, i, n) for n, f, k, i in INNER)
    + "# ── from api/routers/home.py ──\n"
    + cut(HOME, HOME_NAMES)
    + "# fmt: on\n"
)
for old, new in (  # type hints only
    ("\nFAMILY_LABEL = {", "\nFAMILY_LABEL: dict[str, str] = {"),
    ("\nCOVERAGE_LABEL = {", "\nCOVERAGE_LABEL: dict[str, str] = {"),
    ("\nSUBLOCAL = {", "\nSUBLOCAL: dict[str, str] = {"),
    ("\n_SCOUT_FAMILY = {", "\n_SCOUT_FAMILY: dict[str, str] = {"),
    ("\n_SRC_FAMILY = {", "\n_SRC_FAMILY: dict[str, str] = {"),
    ("\n_NEWS_FAMILY = {", "\n_NEWS_FAMILY: dict[str, str] = {"),
    ("\nHOME_DEFAULT = {", "\nHOME_DEFAULT: dict[str, Any] = {"),
    ("\nLEGEND = (", "\nLEGEND: dict[str, str] = ("),
    ("\nBRING_BACK = (", "\nBRING_BACK: list[str] = ("),
    ("\nDEFAULT_HOME_BASE = {", "\nDEFAULT_HOME_BASE: dict[str, Any] = {"),
):
    assert catalog.count(old) == 1, old
    catalog = catalog.replace(old, new)
compile(catalog, "catalog.py", "exec")
(NEW / "catalog.py").write_text(catalog, encoding="utf-8", newline="\n")
print("catalog.py", len(catalog.splitlines()), "lines")

"""Cut the Today catalog from the OLD modules by exact line ranges (review 030a). Nothing is retyped.

    backend/.venv/Scripts/python.exe scripts/gen_today_catalog.py   # PZ_OLD_REPO: the old checkout (a sibling)

Top-level constants of the old ``services/today.py`` (``MAX_ACTIONS``, the ten action ``TYPES`` in their old order,
``_CLEAR_CONFLICT``) and of the old ``services/compressor.py`` that ``compressor.summary`` / ``settings`` read (the
routing ``STATES`` in their count order, ``LABEL``, the attention-budget ``DEFAULTS`` and the job state ``_job``,
which no Today request ever starts: it stays idle) are cut whole: the exact source lines of each assignment. Each cut
is checked: its text compiles, and its syntax tree equals the old node's (positions aside).
"""

import ast
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
OLD_REPO = pathlib.Path(os.environ.get("PZ_OLD_REPO", str(ROOT.parent / "project-zero")))
OLD = OLD_REPO / "backend" / "src" / "projectzero"
TODAY = OLD / "services" / "today.py"
COMPRESSOR = OLD / "services" / "compressor.py"
NEW = ROOT / "backend" / "src" / "projectzero" / "today"
TODAY_NAMES = ["MAX_ACTIONS", "TYPES", "_CLEAR_CONFLICT"]
COMPRESSOR_NAMES = ["STATES", "LABEL", "DEFAULTS", "_job"]


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


assert not set(TODAY_NAMES) & set(COMPRESSOR_NAMES)  # no name is cut twice
catalog = (
    '''# (protected gold-master data, copied by script from the old modules; see the header)
"""The Today catalog (review 030a): constants cut MECHANICALLY from the old ``services/today.py`` and
``services/compressor.py`` at revision 6c739b9 by exact line ranges (``scripts/gen_today_catalog.py``); nothing is
retyped. ``tests/today/test_today_port.py`` checks every cut against the old modules. Pure data.

From ``today.py`` (top level): ``MAX_ACTIONS``, the ten action ``TYPES`` (the old order; the two retired Scout types
stay listed, decision c drops only their sections) and ``_CLEAR_CONFLICT``. From ``compressor.py``: the routing
``STATES`` (the order of ``triage.counts``), ``LABEL`` (``triage.labels``), the attention-budget ``DEFAULTS`` (read by
``settings``) and ``_job``, the job state ``summary`` reports: no compression run is ported, so it is always idle.
"""

from __future__ import annotations

from typing import Any

# fmt: off
# ── from services/today.py ──
'''
    + cut(TODAY, TODAY_NAMES)
    + "# ── from services/compressor.py ──\n"
    + cut(COMPRESSOR, COMPRESSOR_NAMES)
    + "# fmt: on\n"
)
compile(catalog, "catalog.py", "exec")
NEW.mkdir(parents=True, exist_ok=True)
(NEW / "catalog.py").write_text(catalog, encoding="utf-8", newline="\n")
print("catalog.py", len(catalog.splitlines()), "lines")

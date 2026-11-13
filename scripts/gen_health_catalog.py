"""Cut the System health catalog from the OLD modules by exact line ranges (review 032a). Nothing is retyped.

    backend/.venv/Scripts/python.exe scripts/gen_health_catalog.py   # PZ_OLD_REPO: the old checkout (a sibling)

Cut WHOLE (the exact source lines of each top-level statement; each cut compiles and its syntax tree equals the old
node's, positions aside): every body below calls no loader and no clock.

* ``services/health.py``: ``STALE_DAYS``, ``_ts``, ``_days``, ``REPAIR_RULES``, ``_EXTERNAL_CAUSES``, ``diagnose``,
  ``STALE_JOB_REPORT_H`` and ``overall_status`` (the verdict's one-line answer, every branch; ``now`` is a parameter);
* ``services/scheduler.py``: ``STALE_RUNNING_H``, ``REPEATED_FAILURES``, ``OUTCOMES`` and ``classify``;
* ``services/health_overview.py``: ``HISTORY_DAYS`` and ``run_state``.

The ``JOBS`` table is cut ROW BY ROW as data: every key of every old row except ``run`` (the runner's, 032c) with its
literal value, and the NAME of the old function for ``last`` / ``due`` (``None`` stays ``None``). Each emitted row is
checked against the old row's nodes. The four retired Scout rows stay listed; ``health.core`` drops them (decision c).
"""

import ast
import os
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
OLD_REPO = pathlib.Path(os.environ.get("PZ_OLD_REPO", str(ROOT.parent / "project-zero")))
OLD = OLD_REPO / "backend" / "src" / "projectzero" / "services"
HEALTH = OLD / "health.py"
SCHEDULER = OLD / "scheduler.py"
OVERVIEW = OLD / "health_overview.py"
NEW = ROOT / "backend" / "src" / "projectzero" / "health"
HEALTH_NAMES = [
    "STALE_DAYS",
    "_ts",
    "_days",
    "REPAIR_RULES",
    "_EXTERNAL_CAUSES",
    "diagnose",
    "STALE_JOB_REPORT_H",
    "overall_status",
]
SCHEDULER_NAMES = ["STALE_RUNNING_H", "REPEATED_FAILURES", "OUTCOMES", "classify"]
OVERVIEW_NAMES = ["HISTORY_DAYS", "run_state"]
JOB_KEYS = ("id", "label", "interval_h", "last", "due", "while_open")  # every old key but ``run``


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
            assert name not in found, name  # one top-level statement per name
            assert not getattr(node, "decorator_list", []), name
            text = "".join(lines[node.lineno - 1 : node.end_lineno])
            assert _same(ast.parse(text).body[0], node), name  # the cut compiles and is the old statement
            found[name] = text
    missing = [n for n in names if n not in found]
    assert not missing, (path.name, missing)
    # two blank lines around each function (the cut text itself is never changed)
    out = "".join("\n\n" + found[n] + "\n\n" if found[n].startswith("def ") else found[n] for n in names)
    return re.sub(r"\n{4,}", "\n\n\n", out)


def jobs_rows(path: pathlib.Path) -> list[dict[str, object]]:
    """The old ``JOBS`` rows as data: literals as they are, a function reference as its name."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if _name(n) == "JOBS")
    value = node.value
    assert isinstance(value, ast.List)
    rows: list[dict[str, object]] = []
    for elt in value.elts:
        assert isinstance(elt, ast.Dict)
        row: dict[str, object] = {}
        for k, v in zip(elt.keys, elt.values, strict=True):
            assert isinstance(k, ast.Constant) and isinstance(k.value, str)
            if k.value == "run":
                assert isinstance(v, ast.Name), k.value  # the runner's job function (032c)
                continue
            assert k.value in JOB_KEYS, k.value
            if isinstance(v, ast.Name):
                row[k.value] = v.id
            else:
                assert isinstance(v, ast.Constant), k.value
                row[k.value] = v.value
        rows.append(row)
    return rows


def render_jobs(rows: list[dict[str, object]]) -> str:
    out = ["JOBS: tuple[dict[str, Any], ...] = (\n"]
    for row in rows:
        out.append("    {" + ", ".join(f"{k!r}: {v!r}" for k, v in row.items()) + "},\n")
    out.append(")\n")
    text = "".join(out).replace("'", '"')
    assert ast.literal_eval(text.split("= ", 1)[1]) == tuple(rows)  # the rendered table is the old rows
    return text


ALL_NAMES = HEALTH_NAMES + SCHEDULER_NAMES + OVERVIEW_NAMES + ["JOBS"]
assert len(set(ALL_NAMES)) == len(ALL_NAMES)  # no name is cut twice
catalog = (
    '''# ruff: noqa: E501
# (protected gold-master data and rules, copied by script from the old modules; see the header)
"""The System health catalog (review 032a): constants and pure rules cut MECHANICALLY from the old
``services/health.py``, ``services/scheduler.py`` and ``services/health_overview.py`` at revision 6c739b9 by exact
line ranges (``scripts/gen_health_catalog.py``); nothing is retyped. ``tests/health/test_health_port.py`` checks every
cut against the old modules. No loader, no clock, no I/O.

From ``health.py``: ``STALE_DAYS``, ``_ts``, ``_days``, the source-repair ``REPAIR_RULES`` and ``_EXTERNAL_CAUSES``,
``diagnose``, ``STALE_JOB_REPORT_H`` and ``overall_status`` (the old texts: ``health.core`` uses it as it is when a
runner exists and rewords only the job-report sentences without one, decision k). From ``scheduler.py``:
``STALE_RUNNING_H``, ``REPEATED_FAILURES``, ``OUTCOMES`` and ``classify``; the ``JOBS`` rows as data (every key but
``run``; ``last`` / ``due`` name the old function, which ``health.core`` maps to the NEW readers). From
``health_overview.py``: ``HISTORY_DAYS`` and ``run_state``.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

# fmt: off
# ── from services/health.py ──
'''
    + cut(HEALTH, HEALTH_NAMES)
    + "# ── from services/scheduler.py ──\n"
    + cut(SCHEDULER, SCHEDULER_NAMES)
    + render_jobs(jobs_rows(SCHEDULER))
    + "# ── from services/health_overview.py ──\n"
    + cut(OVERVIEW, OVERVIEW_NAMES)
    + "# fmt: on\n"
)
catalog = re.sub(r"\n{4,}", "\n\n\n", catalog).rstrip("\n") + "\n"
compile(catalog, "catalog.py", "exec")
NEW.mkdir(parents=True, exist_ok=True)
(NEW / "catalog.py").write_text(catalog, encoding="utf-8", newline="\n")
print("catalog.py", len(catalog.splitlines()), "lines")

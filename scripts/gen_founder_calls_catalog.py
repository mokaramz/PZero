"""Cut the Founder Calls catalog from the OLD module by exact top-level line ranges (review 023). Nothing is retyped.

    backend/.venv/Scripts/python.exe scripts/gen_founder_calls_catalog.py   # PZ_OLD_REPO: the old checkout (a sibling)

Top-level constants of the old ``domain/founder_calls.py`` are cut whole (the exact source lines of each assignment).
Annotations are added by text replacement only (type hints, no values).
"""

import ast
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
OLD_REPO = pathlib.Path(os.environ.get("PZ_OLD_REPO", str(ROOT.parent / "project-zero")))
OLD = OLD_REPO / "backend" / "src" / "projectzero" / "domain" / "founder_calls.py"
NEW = ROOT / "backend" / "src" / "projectzero" / "founder_calls"
NAMES = ["FILE_NAME", "LABEL", "SUMMARY_LABEL", "UNKNOWN", "CHANNELS", "CALL_TYPES", "RECOMMENDATIONS", "CONFIDENCE",
         "OWNERS", "UPCOMING_DAYS", "TEMPLATES", "ASSESSMENT_FIELDS"]  # fmt: skip


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
    '''# (protected gold-master data, copied by script from the old module; see the header)
"""The Founder Calls catalog (review 023): constants cut MECHANICALLY from the old ``domain/founder_calls.py`` at
revision 6c739b9 by exact top-level line ranges (``scripts/gen_founder_calls_catalog.py``); nothing is retyped.
``tests/founder_calls/test_founder_calls_port.py`` checks every string literal against the old module. Pure data.

``FILE_NAME``, the labels (``LABEL``, ``SUMMARY_LABEL``, ``UNKNOWN``), the enums (``CHANNELS``, ``CALL_TYPES``,
``RECOMMENDATIONS``, ``CONFIDENCE``, ``OWNERS``), ``UPCOMING_DAYS``, the call ``TEMPLATES`` and ``ASSESSMENT_FIELDS``.
"""

from __future__ import annotations

from typing import Any

# fmt: off
'''
    + cut(OLD, NAMES)
    + "# fmt: on\n"
)
for old, new in (("\nTEMPLATES = {", "\nTEMPLATES: dict[str, dict[str, Any]] = {"),):  # type hints only
    assert catalog.count(old) == 1, old
    catalog = catalog.replace(old, new)
(NEW / "catalog.py").write_text(catalog, encoding="utf-8", newline="\n")
print("catalog.py", len(catalog.splitlines()), "lines")

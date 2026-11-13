"""Cut the machine-triage cascade's pure rules from the OLD ``services/shadow_triage.py`` by exact top-level line ranges
(review 035b). Nothing is retyped.

    backend/.venv/Scripts/python.exe scripts/gen_triage_cascade.py   # PZ_OLD_REPO: the old checkout (a sibling)

One generated module, ``backend/src/projectzero/dealflow/triage/cascade_rules.py``: the label vocabularies, the
system prompt (``_system_prompt``, ``system_prompt_sha``, ``messages_for``), the veto's formatting repair
(``basis_as_proposal``), the deterministic reject-support check (``reject_support_problem``), Stage 0
(``stage0_junk``), the veto's combination rule (``bases_agree``, ``_combine``) and the schema-retry constants.

Each cut is checked: its text compiles and its syntax tree equals the old node's (positions aside). The tables the
prompt and the rules read are checked against the old ones node for node: ``THEMES`` (old ``domain/themes.py`` vs
``dealflow/ranking/themes.py``), ``ARCHETYPES`` (old ``domain/taste.py`` vs ``conviction/taste.py``) and ``_MATURE``
(old ``domain/attention.py`` vs ``dealflow/ranking/attention.py``). The generated prompt's sha256 is asserted to be
the locked one (the old ``test_shadow_triage.py`` ``LOCKED_PROMPT_SHA`` and ``shadow_triage/acceptance.json``).

The ONLY change is one exact text replacement, asserted to occur once: the old ``workspaces.workspace_of(cand)`` read
the operator's workspace override from ``workspace_geos.json`` itself; the new ``workspace_of`` takes it as a
parameter, so the cut reads it from the hand-written ``OVERRIDE`` context variable the runner sets per run.

The auto-triage rules (``auto_rules.py``) are cut the same way from ``services/auto_triage.py``; see ``AUTO_HEAD``.

The validator (the old pydantic ``TriageProposal`` + ``validator_for``) is hand-ported in ``cascade.py``: the new app
has no pydantic. The oracle checks it against the old model.
"""

import ast
import hashlib
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OLD_REPO = pathlib.Path(os.environ.get("PZ_OLD_REPO", str(ROOT.parent / "project-zero")))
OLD_SRC = OLD_REPO / "backend" / "src" / "projectzero"
OLD = OLD_SRC / "services" / "shadow_triage.py"
NEW_SRC = ROOT / "backend" / "src" / "projectzero"
OUT = NEW_SRC / "dealflow" / "triage" / "cascade_rules.py"
LOCKED_PROMPT_SHA = "e0d09eb2df5b733692b2a8ef7dfd1e69bf190db4e23b4a13b8e3ced08bb8cc63"

NAMES = [
    "LABELS", "REJECT_BASES", "ENTITY_TYPES", "CAPITAL_STAGES", "_system_prompt", "system_prompt_sha", "messages_for",
    "VENTURE_ENTITY_TYPES", "_norm_token", "basis_as_proposal", "_norm_text", "reject_support_problem", "_SHORTCODE",
    "_DATE_WORDS", "stage0_junk", "COMPATIBLE_BASES", "bases_agree", "_combine", "SCHEMA_ERRORS", "NO_THINKING",
]  # fmt: skip
REPLACE = [  # (old, new, count)
    ("workspaces.workspace_of(cand)", "workspaces.workspace_of(cand, OVERRIDE.get())", 1),
]
TABLES = [  # (old module, new module, name)
    (OLD_SRC / "domain" / "themes.py", NEW_SRC / "dealflow" / "ranking" / "themes.py", "THEMES"),
    (OLD_SRC / "domain" / "taste.py", NEW_SRC / "conviction" / "taste.py", "ARCHETYPES"),
    (OLD_SRC / "domain" / "attention.py", NEW_SRC / "dealflow" / "ranking" / "attention.py", "_MATURE"),
]


def _same(a: ast.AST, b: ast.AST) -> bool:
    return ast.dump(a) == ast.dump(b)  # include_attributes=False: positions are ignored


def _name(node: ast.stmt) -> str | None:
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    return None


def nodes(path: pathlib.Path) -> tuple[list[str], list[tuple[str | None, ast.stmt]]]:
    src = path.read_text(encoding="utf-8")
    return src.splitlines(keepends=True), [(_name(n), n) for n in ast.parse(src).body]


def text_of(lines: list[str], node: ast.stmt) -> str:
    start = node.lineno - 1
    if isinstance(node, ast.FunctionDef) and node.decorator_list:
        start = node.decorator_list[0].lineno - 1
    text = "".join(lines[start : node.end_lineno])
    assert _same(ast.parse(text).body[0], node), _name(node)  # the cut compiles and is the old statement
    return text


def cut(path: pathlib.Path, names: list[str]) -> str:
    lines, found = nodes(path)
    by: dict[str, str] = {}
    for name, node in found:
        if name in names:
            assert name not in by, (path.name, name)
            by[name] = text_of(lines, node)
    missing = [n for n in names if n not in by]
    assert not missing, (path.name, missing)
    return "\n\n".join(by[n].rstrip("\n") for n in names) + "\n"


def replace(text: str, rules: list[tuple[str, str, int]]) -> str:
    for old, new, count in rules:
        assert text.count(old) == count, (old, text.count(old), count)
        text = text.replace(old, new)
    return text


def same_table(old_path: pathlib.Path, new_path: pathlib.Path, name: str) -> None:
    old = {n: node for n, node in nodes(old_path)[1]}[name]
    new = {n: node for n, node in nodes(new_path)[1]}[name]
    assert isinstance(old, ast.Assign) and isinstance(new, ast.Assign), name
    assert _same(old.value, new.value) or _equal_values(old_path, new_path, name), name


def _equal_values(old_path: pathlib.Path, new_path: pathlib.Path, name: str) -> bool:
    """A table written differently (e.g. a regex split over lines) is still equal when its VALUE is (``ast`` of the
    evaluated constant parts): only used for ``_MATURE``, compared by its compiled pattern and flags."""
    if name != "_MATURE":
        return False
    import importlib

    sys.path.insert(0, str(ROOT / "backend" / "src"))
    new = importlib.import_module("projectzero.dealflow.ranking.attention")._MATURE
    old_py = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    probe = "import sys; sys.path.insert(0, sys.argv[1]); from projectzero.domain import attention as a; " \
            "print(repr((a._MATURE.pattern, a._MATURE.flags)))"  # fmt: skip
    out = subprocess.run([str(old_py), "-c", probe, str(OLD_REPO / "backend" / "src")], capture_output=True,
                         text=True, check=True, env={**os.environ, "PZ_TESTING": "1"}).stdout.strip()  # fmt: skip
    return out == repr((new.pattern, new.flags))


HEAD = '''# ruff: noqa
# mypy: ignore-errors
# (protected triage rules, copied by script from the old module; see the header. The cut code is the old untyped
# code verbatim, so it is exempt from lint and type checks, like a vendored module.)
"""The machine-triage cascade's pure rules (review 035b), cut MECHANICALLY from the old ``services/shadow_triage.py``
(rev 6c739b9) by exact top-level line ranges (``scripts/gen_triage_cascade.py``); nothing is retyped. The system prompt
is pinned by its sha256 (``LOCKED_PROMPT_SHA``, asserted by the script and by the unit tests).

The one declared replacement: ``workspaces.workspace_of(cand)`` reads the run's workspace override from ``OVERRIDE``
(the old function read ``workspace_geos.json`` itself; the new one takes the override as a parameter).
"""

# fmt: off
import hashlib
import re
from contextvars import ContextVar
from typing import Any

from projectzero.conviction import taste
from projectzero.dealflow import workspaces
from projectzero.dealflow.ranking import attention, themes
from projectzero.dealflow.triage.card import candidate_card

LOCKED_PROMPT_SHA = "{sha}"

# ── hand-written seam (NOT cut): the workspace override the old ``workspace_of`` loaded itself ──────────────────────
OVERRIDE = ContextVar("triage_workspace_override", default=workspaces.NO_OVERRIDE)

# ── cut from services/shadow_triage.py ──
'''


AUTO_HEAD = '''# ruff: noqa
# mypy: ignore-errors
# (protected auto-triage rules, copied by script from the old module; see the header. The cut code is the old untyped
# code verbatim, so it is exempt from lint and type checks, like a vendored module.)
"""The automatic machine triage's pure rules (review 035b), cut MECHANICALLY from the old ``services/auto_triage.py``
(rev 6c739b9) by exact top-level line ranges (``scripts/gen_triage_cascade.py``); nothing is retyped: the retry
backoff and its bound, the run cap, the kept-runs count, the stop-kind fallback, one retry item (``_retry_item``), the
earliest next try, the summary sentence and ``plain`` (a run record as the UI shows it).

The one declared replacement (decision c): ``perrors.explain(`` -> ``_explain(``, the hand-written seam below that
names the NEW paid switch (``PZ_AI_PAID``) where the old text named the old kill switch.
"""

# fmt: off
from datetime import datetime, timedelta
from typing import Any

from projectzero.core.inference import errors as perrors

PAID_OFF_OLD = "(kill switch)"
PAID_OFF_NEW = "(PZ_AI_PAID is not 'on')"


# ── hand-written seam (NOT cut): the plain sentence, with the new paid switch's name (decision c) ─────────────────
def _explain(kind, raw="", provider="DeepInfra"):
    return perrors.explain(kind, raw, provider).replace(PAID_OFF_OLD, PAID_OFF_NEW)


# ── cut from services/auto_triage.py ──
'''
AUTO_OLD = OLD_SRC / "services" / "auto_triage.py"
AUTO_OUT = NEW_SRC / "dealflow" / "triage" / "auto_rules.py"
AUTO_NAMES = ["RETRY_BACKOFF_MIN", "MAX_AUTO_RETRIES", "AUTO_RUN_CAP_USD", "KEEP_RUNS", "_stop_kind", "_retry_item",
              "rs_next", "summary", "plain"]  # fmt: skip
AUTO_REPLACE = [("perrors.explain(", "_explain(", 3)]


def main() -> int:
    for old_path, new_path, name in TABLES:
        same_table(old_path, new_path, name)
    body = replace(cut(OLD, NAMES), REPLACE)
    text = HEAD.replace("{sha}", LOCKED_PROMPT_SHA) + body
    compile(text, str(OUT), "exec")
    OUT.write_text(text, encoding="utf-8", newline="\n")
    auto = AUTO_HEAD + replace(cut(AUTO_OLD, AUTO_NAMES), AUTO_REPLACE)
    compile(auto, str(AUTO_OUT), "exec")
    AUTO_OUT.write_text(auto, encoding="utf-8", newline="\n")
    sys.path.insert(0, str(ROOT / "backend" / "src"))
    import importlib

    mod = importlib.import_module("projectzero.dealflow.triage.cascade_rules")
    importlib.import_module("projectzero.dealflow.triage.auto_rules")
    sha = hashlib.sha256(mod._system_prompt().encode("utf-8")).hexdigest()
    assert sha == LOCKED_PROMPT_SHA, sha
    print(f"wrote {OUT.relative_to(ROOT)} ({len(NAMES)} cuts); system prompt sha256 {sha}")
    print(f"wrote {AUTO_OUT.relative_to(ROOT)} ({len(AUTO_NAMES)} cuts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

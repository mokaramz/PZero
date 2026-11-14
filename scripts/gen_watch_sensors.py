"""Cut the WATCH sensors from the OLD modules by exact top-level line ranges (review 037b). Nothing is retyped.

    backend/.venv/Scripts/python.exe scripts/gen_watch_sensors.py   # PZ_OLD_REPO: the old checkout (a sibling)

One generated module, ``backend/src/projectzero/watch/sensors.py``: from ``services/watch.py`` (rev 6c739b9) the
material-change thresholds, the 19 ordered ``PREDICATES``, ``LABEL``, ``CLAIM_PREDICATE``, ``HIGH_VALUE``, ``_sha``,
``_norm`` and ``classify`` (pure), and ``_fire``, ``scan_rehits`` and ``check_page`` (the sensors); from
``services/news.py`` the news bridge ``_watch_bridge``.

Each cut is checked: its text compiles and its syntax tree equals the old node's (positions aside). ``LABEL`` is
checked equal (as a value) to ``watch/view.py``'s ``LABEL`` (037a), so the view and the sensors name every predicate
alike. The ONLY changes are exact text replacements, each asserted to occur the stated number of times:

* the lazy imports: ``from projectzero.services import case_prep`` -> ``case_prep = _CASE_PREP`` (decision f: the
  high-value case refresh is case preparation's and stays deferred; the seam records the call, writes nothing),
  ``from projectzero.domain import events as evmod`` -> ``evmod = _EVMOD`` (``events/when.extract_date`` at the run's
  day), and in the bridge ``from projectzero.services import watch`` -> ``watch = _WATCH`` (this module);
* the bridge's ``load()["events"]`` -> ``_news_events()`` (the news run's events after its ingest, handed in).

Hand-written, and marked as such inside ``sensors.py``: what the old module reached outside itself, each through ONE
``Context`` the run installs for one unit of work (``watch/run.py``): ``storage`` (the trigger appends are collected,
the proposals are the run's), ``ledger.now_ts`` (the run's clock), ``connectors`` (``_lines`` / ``_uid`` are the ported
``dealflow/scan/parsers`` ones; ``_get`` answers the page the run fetched through ``core/net``; ``_load_snapshot`` /
``_save_snapshot`` over the baselines the run resolved), ``triage_review.edge`` (the ported ``dealflow/triage/view``
one), ``watched()`` and ``_fired_keys()`` (the run's current watched set and dedupe keys).
"""

import ast
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OLD_REPO = pathlib.Path(os.environ.get("PZ_OLD_REPO", str(ROOT.parent / "project-zero")))
OLD_SRC = OLD_REPO / "backend" / "src" / "projectzero"
OLD_WATCH = OLD_SRC / "services" / "watch.py"
OLD_NEWS = OLD_SRC / "services" / "news.py"
NEW_SRC = ROOT / "backend" / "src" / "projectzero"
OUT = NEW_SRC / "watch" / "sensors.py"
VIEW = NEW_SRC / "watch" / "view.py"

WATCH_NAMES = [
    "MATERIAL_MIN_LINES", "MATERIAL_SHARE", "PREDICATES", "LABEL", "CLAIM_PREDICATE", "HIGH_VALUE", "_sha", "_norm",
    "classify", "_fire", "scan_rehits", "check_page",
]  # fmt: skip
NEWS_NAMES = ["_watch_bridge"]
WATCH_REPLACE = [  # (old, new, count)
    ("            from projectzero.services import case_prep\n", "            case_prep = _CASE_PREP\n", 1),
    ("    from projectzero.domain import events as evmod\n", "    evmod = _EVMOD\n", 1),
]
NEWS_REPLACE = [
    ("    from projectzero.services import watch\n", "    watch = _WATCH\n", 1),
    ('load()["events"]', "_news_events()", 1),
]


def _same(a: ast.AST, b: ast.AST) -> bool:
    return ast.dump(a) == ast.dump(b)  # include_attributes=False: positions are ignored


def _name(node: ast.stmt) -> str | None:
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None


def cut(path: pathlib.Path, names: list[str]) -> str:
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    by: dict[str, str] = {}
    for node in ast.parse(src).body:
        name = _name(node)
        if name not in names:
            continue
        assert name not in by, (path.name, name)
        start = node.decorator_list[0].lineno - 1 if isinstance(node, ast.FunctionDef) and node.decorator_list else (
            node.lineno - 1)  # fmt: skip
        text = "".join(lines[start : node.end_lineno])
        assert _same(ast.parse(text).body[0], node), name  # the cut compiles and is the old statement
        by[name] = text
    missing = [n for n in names if n not in by]
    assert not missing, (path.name, missing)
    return "\n\n".join(by[n].rstrip("\n") for n in names) + "\n"


def replace(text: str, rules: list[tuple[str, str, int]]) -> str:
    for old, new, count in rules:
        assert text.count(old) == count, (old, text.count(old), count)
        text = text.replace(old, new)
    return text


def same_label() -> None:
    """The cut ``LABEL`` equals the 037a view's ``LABEL`` as a value (the old one is built from ``PREDICATES``)."""
    sys.path.insert(0, str(ROOT / "backend" / "src"))
    import importlib

    sensors = importlib.import_module("projectzero.watch.sensors")
    view = importlib.import_module("projectzero.watch.view")
    assert sensors.LABEL == view.LABEL and list(sensors.LABEL) == list(view.LABEL), "LABEL differs from watch/view"


HEAD = '''# ruff: noqa
# mypy: ignore-errors
# (protected WATCH sensor rules, copied by script from the old modules; see the header. The cut code is the old untyped
# code verbatim, so it is exempt from lint and type checks, like a vendored module.)
"""The WATCH sensors (review 037b), cut MECHANICALLY from the old ``services/watch.py`` (and the news bridge from
``services/news.py``) at revision 6c739b9 by exact top-level line ranges (``scripts/gen_watch_sensors.py``); nothing
is retyped. See the script's header for the cut list and the declared replacements (the two lazy imports of the
sensors, the bridge's own lazy import and its events).

Pure over what the run hands in: every outside reach goes through the ``Context`` the run installs for ONE unit of
work (one page, one company's re-hits, one news run's bridge), and nothing here touches the database or the network.
The run (``watch/run.py``) decides what is written: the collected trigger lines, the saved snapshot, the check record.
"""

# fmt: off
import hashlib
import json
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from projectzero.dealflow.scan import parsers as _parsers
from projectzero.dealflow.ranking.names import norm_company as _norm_company
from projectzero.dealflow.triage.view import edge as _edge
from projectzero.events import when as _when

log = logging.getLogger("projectzero.watch.sensors")
TRIGGERS = "watch/triggers.jsonl"


# ── hand-written seams (NOT cut): what the old module reached outside itself ───────────────────────────────────────
@dataclass
class Context:
    """One unit of work's world. ``page``: the fetched page text, or the exception the fetch raised."""

    ts: str  # the old ``ledger.now_ts()``
    today: date  # the old ``date.today()`` of ``extract_date``
    watched: dict = field(default_factory=dict)  # what ``watched()`` answers
    fired: set = field(default_factory=set)  # what ``_fired_keys()`` answers (mutated by ``_fire``, as before)
    proposals: dict = field(default_factory=dict)  # ``triage_proposals.json``'s ``proposals``
    news_events: dict = field(default_factory=dict)  # the bridge's ``load()["events"]``
    page: Any = None
    baselines: dict = field(default_factory=dict)  # snapshot name -> the lines the run resolved
    saved: dict = field(default_factory=dict)  # snapshot name -> the page's new lines
    lines: list = field(default_factory=list)  # the trigger lines ``_fire`` appended, in order
    case_refresh: list = field(default_factory=list)  # decision (f): the deferred ``on_watch_trigger`` calls


_CTX: ContextVar = ContextVar("watch_sensor_context")


@contextmanager
def context(ctx):
    token = _CTX.set(ctx)
    try:
        yield ctx
    finally:
        _CTX.reset(token)


def _ctx():
    return _CTX.get()


class _Storage:
    @staticmethod
    def append_line(name, line):
        assert name == TRIGGERS, name
        _ctx().lines.append(line)

    @staticmethod
    def load_json(name, default=None, tolerant=False):
        assert name == "triage_proposals.json", name
        return {"proposals": _ctx().proposals}


class _Ledger:
    @staticmethod
    def now_ts():
        return _ctx().ts


class _Connectors:
    _lines = staticmethod(_parsers._lines)
    _uid = staticmethod(_parsers._uid)
    norm_company = staticmethod(_norm_company)

    @staticmethod
    def _snap_path(name):
        return name  # the old ``<data>/.watch/<name>``: here the baseline's key, resolved by the run

    @staticmethod
    def _get(url):
        page = _ctx().page
        if isinstance(page, BaseException):
            raise page
        return page

    @staticmethod
    def _load_snapshot(name):
        got = _ctx().baselines.get(name)
        return list(got) if isinstance(got, list) else []

    @staticmethod
    def _save_snapshot(name, lines):
        _ctx().saved[name] = list(lines)


class _TriageReview:
    edge = staticmethod(_edge)


class _CaseRefresh:
    """Decision (f): the high-value case refresh is case preparation's (item 4): recorded, never run."""

    @staticmethod
    def on_watch_trigger(name, label):
        _ctx().case_refresh.append([name, label])


class _Events:
    @staticmethod
    def extract_date(text):
        return _when.extract_date(text, today=_ctx().today)


def watched():
    return _ctx().watched


def _fired_keys():
    return _ctx().fired


def _news_events():
    return _ctx().news_events


class _This:
    """The bridge's ``watch`` module: this one."""

    def __getattr__(self, name):
        return globals()[name]


storage, ledger, connectors, triage_review = _Storage(), _Ledger(), _Connectors(), _TriageReview()
_CASE_PREP, _EVMOD, _WATCH = _CaseRefresh(), _Events(), _This()

'''


def build() -> str:
    """The generated module's text (every cut checked against the old node)."""
    body = replace(cut(OLD_WATCH, WATCH_NAMES), WATCH_REPLACE)
    bridge = replace(cut(OLD_NEWS, NEWS_NAMES), NEWS_REPLACE)
    text = HEAD + "# ── cut from services/watch.py ──\n" + body + "\n\n# ── cut from services/news.py ──\n" + bridge
    compile(text, str(OUT), "exec")
    return text


def main() -> int:
    OUT.write_text(build(), encoding="utf-8", newline="\n")
    same_label()
    print(f"wrote {OUT.relative_to(ROOT)} ({len(WATCH_NAMES) + len(NEWS_NAMES)} cuts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

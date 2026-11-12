"""Cut the News catalog from the OLD modules by exact line ranges (review 028a). Nothing is retyped.

    backend/.venv/Scripts/python.exe scripts/gen_news_catalog.py   # PZ_OLD_REPO: the old checkout (a sibling)

Top-level constants of the old ``services/news.py`` (the store names, ``EARLY_DAYS``, the feed list, the event types
in their first-match order, the noise / digest / round / amount rules, the geo and theme words, ``SENSOR_FOR``, the
17 ``CONCEPTS``, the roundup verbs, the state labels and ``OUTCOME_KIND``), of ``services/news_sources.py`` (the store
names, the windows, the thresholds, the scopes, the press-release and Munich rules, ``PUBLICATIONS`` in its
recognition order, the citation rule, the authority priors, the hypotheses and ``BEST``) and the domain lists of
``services/claims.py`` that ``claims.classify`` reads are cut whole: the exact source lines of each assignment. Each
cut is checked: its text compiles, and its syntax tree equals the old node's (positions aside).

``news_sources.EARLY_DAYS`` ("same threshold as the News PZ check") is not cut a second time: its value is checked
equal to ``news.EARLY_DAYS``, which is cut. The shipped curated cases (``resources/news_cases/*.json``) are copied
byte for byte (the committed blob, LF) into ``backend/src/projectzero/resources/news_cases/``.
"""

import ast
import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
OLD_REPO = pathlib.Path(os.environ.get("PZ_OLD_REPO", str(ROOT.parent / "project-zero")))
OLD = OLD_REPO / "backend" / "src" / "projectzero"
NEWS = OLD / "services" / "news.py"
NEWS_SOURCES = OLD / "services" / "news_sources.py"
CLAIMS = OLD / "services" / "claims.py"
CASES = OLD / "resources" / "news_cases"
NEW = ROOT / "backend" / "src" / "projectzero" / "news"
NEW_CASES = ROOT / "backend" / "src" / "projectzero" / "resources" / "news_cases"
NEWS_NAMES = ["EVENTS", "ACTIONS", "RUNS", "RUN_STATE", "COOLDOWN", "WEEKLY", "EARLY_DAYS", "FEEDS", "EVENT_TYPES",
              "TYPE_LABEL", "_NOISE", "_DIGEST", "_ROUND", "_AMOUNT", "GEO_WORDS", "EUROPE", "GEO_LABEL",
              "THEME_WORDS", "PRIORITY_THEMES", "SENSOR_FOR", "CONCEPTS", "_EVENT_VERBS", "STATE_LABEL",
              "OUTCOME_KIND"]  # fmt: skip
SOURCES_NAMES = ["SNAPSHOT", "STATE", "LOG", "DISAGREE", "HISTORY", "EXTRA_FEEDS", "WINDOWS", "DEFAULT_WINDOW",
                 "MIN_OVERLAP", "MIN_COVERED", "SCOPES", "_MUNICH", "_PR", "CANDIDATE_MIN_EVENTS", "DATABASE_DOMAINS",
                 "PUBLICATIONS", "_CITE", "HIGH_AUTHORITY_PRIOR", "HYPOTHESES", "BEST"]  # fmt: skip
CLAIMS_NAMES = ["REGISTRY_OFFICIAL", "REGISTRY_MIRROR", "PROGRAM", "GOVERNMENT", "MEDIA", "AGGREGATOR", "SOCIAL",
                "PRESS_WIRE"]  # fmt: skip


def _same(a: ast.AST, b: ast.AST) -> bool:
    return ast.dump(a) == ast.dump(b)  # include_attributes=False: positions are ignored


def _nodes(path: pathlib.Path) -> tuple[list[str], dict[str, ast.stmt]]:
    src = path.read_text(encoding="utf-8")
    found: dict[str, ast.stmt] = {}
    for node in ast.parse(src).body:
        name = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        if name is not None:
            assert name not in found, (path.name, name)  # one top-level assignment per name
            found[name] = node
    return src.splitlines(keepends=True), found


def cut(path: pathlib.Path, names: list[str]) -> str:
    lines, found = _nodes(path)
    missing = [n for n in names if n not in found]
    assert not missing, (path.name, missing)
    out = []
    for n in names:
        node = found[n]
        text = "".join(lines[node.lineno - 1 : node.end_lineno])
        assert _same(ast.parse(text).body[0], node), n  # the cut compiles and is the old statement
        out.append(text)
    return "".join(out)


def _value(path: pathlib.Path, name: str) -> str:
    node = _nodes(path)[1][name]
    assert isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None
    return ast.dump(node.value)


assert _value(NEWS_SOURCES, "EARLY_DAYS") == _value(NEWS, "EARLY_DAYS")  # the same threshold, cut once
cut_names = set(NEWS_NAMES) | set(SOURCES_NAMES) | set(CLAIMS_NAMES)
assert len(cut_names) == len(NEWS_NAMES) + len(SOURCES_NAMES) + len(CLAIMS_NAMES)  # no name is cut twice

catalog = (
    '''# ruff: noqa: E501, RUF001
# (protected gold-master data, copied by script from the old modules; see the header)
"""The News catalog (review 028a): constants cut MECHANICALLY from the old ``services/news.py``,
``services/news_sources.py`` and ``services/claims.py`` at revision 6c739b9 by exact line ranges
(``scripts/gen_news_catalog.py``); nothing is retyped. ``tests/news/test_news_port.py`` checks every cut against the
old modules. Pure data.

From ``news.py`` (top level): the store names (``EVENTS``, ``ACTIONS``, ``RUNS``, ``RUN_STATE``, ``COOLDOWN``,
``WEEKLY``), ``EARLY_DAYS``, ``FEEDS`` (the feed order is the ingest order and the sources universe order),
``EVENT_TYPES`` (first match wins: the order is the priority) and ``TYPE_LABEL``, the noise / digest / round / amount
rules, ``GEO_WORDS`` / ``EUROPE`` / ``GEO_LABEL``, ``THEME_WORDS`` / ``PRIORITY_THEMES``, ``SENSOR_FOR``, the 17
``CONCEPTS`` (their dict order and ``sorted`` order are both used), the roundup verbs, ``STATE_LABEL`` and
``OUTCOME_KIND``. From ``news_sources.py``: the store names, ``WINDOWS`` / ``DEFAULT_WINDOW``, the thresholds,
``SCOPES``, the Munich and press-release rules, ``DATABASE_DOMAINS``, ``PUBLICATIONS`` (recognition order),
``_CITE``, ``HIGH_AUTHORITY_PRIOR``, ``HYPOTHESES`` and ``BEST``; its ``EARLY_DAYS`` is the same statement value as
News' (checked by the script, cut once). From ``claims.py``: the domain lists ``claims.classify`` reads.
"""

from __future__ import annotations

import re

# fmt: off
# ── from services/news.py ──
'''
    + cut(NEWS, NEWS_NAMES)
    + "# ── from services/news_sources.py ──\n"
    + cut(NEWS_SOURCES, SOURCES_NAMES)
    + "# ── from services/claims.py ──\n"
    + cut(CLAIMS, CLAIMS_NAMES)
    + "# fmt: on\n"
)
for old, new in (  # type hints only
    ("\nWINDOWS = {", "\nWINDOWS: dict[str, int | None] = {"),
    ("\nBEST = [", "\nBEST: list[tuple[str, str, str, str | None, int]] = ["),
    ("\nSCOPES = {", "\nSCOPES: dict[str, str] = {"),
    ("\nHYPOTHESES = {", "\nHYPOTHESES: dict[str, str] = {"),
    ("\nGEO_WORDS = {", "\nGEO_WORDS: dict[str, str] = {"),
    ("\nTHEME_WORDS = {", "\nTHEME_WORDS: dict[str, str] = {"),
    ("\nGEO_LABEL = {", "\nGEO_LABEL: dict[str, str] = {"),
    ("\nSENSOR_FOR = {", "\nSENSOR_FOR: dict[str, str] = {"),
    ("\nSTATE_LABEL = {", "\nSTATE_LABEL: dict[str, str] = {"),
    ("\nOUTCOME_KIND = {", "\nOUTCOME_KIND: dict[str, str] = {"),
):
    assert catalog.count(old) == 1, old
    catalog = catalog.replace(old, new)
compile(catalog, "catalog.py", "exec")
NEW.mkdir(parents=True, exist_ok=True)
(NEW / "catalog.py").write_text(catalog, encoding="utf-8", newline="\n")
print("catalog.py", len(catalog.splitlines()), "lines")


def blob(name: str) -> bytes:
    """The committed bytes of a shipped case (the old checkout may have CRLF in its working copy: core.autocrlf)."""
    rel = (CASES / name).relative_to(OLD_REPO).as_posix()
    raw = subprocess.run(["git", "-C", str(OLD_REPO), "show", f"HEAD:{rel}"], capture_output=True, check=True).stdout
    assert raw == (CASES / name).read_bytes().replace(b"\r\n", b"\n"), name  # the working copy: line ends only
    return raw


# the shipped curated cases: a code resource, byte for byte (the committed blob)
NEW_CASES.mkdir(parents=True, exist_ok=True)
shipped = sorted(p.name for p in CASES.glob("*.json"))
for stale in NEW_CASES.glob("*.json"):
    if stale.name not in shipped:
        stale.unlink()
for name in shipped:
    (NEW_CASES / name).write_bytes(blob(name))
print("news_cases", shipped)

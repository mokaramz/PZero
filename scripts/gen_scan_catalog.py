"""Cut the Deal Flow scan's parsers from the OLD modules by exact top-level line ranges (review 034a). Nothing is
retyped.

    backend/.venv/Scripts/python.exe scripts/gen_scan_catalog.py   # PZ_OLD_REPO: the old checkout (a sibling)

Three generated modules in ``backend/src/projectzero/dealflow/scan/``:

* ``parsers.py``: from ``domain/connectors.py`` (rev 6c739b9) the cooperative deadlines, the fetch telemetry and
  ``_get``, ``make`` (with ``strong_archetypes`` and its word lists), the headline extractor, ``feed``, the visible-text
  reader and ``page`` (the page watcher, ``page_diff``), ``parse_source_date``, ``norm_company``, ``classify_sectors``,
  ``is_interstitial``, ``is_academic``, ``entity_keys``, the cursor helpers (``_peek`` / ``_mark`` / ``_seen``), the
  structured parsers (``p_sbir``, ``p_nsf``, ``p_nih``, ``p_gtr``, ``p_cordis``, ``p_ckan``) with ``PARSERS``,
  ``_scan_one`` (one source), the batch resolution (``_resolve_batch``) and ``RUNTIME_KEYS``.
* ``sources_v2.py``: ``domain/sources_v2.py`` whole except the registry data (``URL_REPAIRS``, ``URL_REPAIRS_MULTI``,
  ``NOTE_REPAIRS``, ``registry_entries``: already cut into ``dealflow/sources/catalog.py``, review 021).
* ``taste.py``: ``domain/taste.py`` ``suggest_twins`` and ``tag_archetypes`` over the Taste Map tables already ported
  verbatim in ``conviction/taste.py`` (the script checks both tables equal the old ones, node for node).

Each cut is checked: its text compiles and its syntax tree equals the old node's (positions aside). The ONLY changes
are exact text replacements, each asserted to occur the stated number of times:

* the clock: ``date.today()`` -> ``seams.today()`` (the scan's frozen day, a parameter of the run);
* the old user agent ``net.USER_AGENT`` -> ``seams.USER_AGENT`` (the same text);
* the lazy imports: the old ``domain/entity_repair`` -> ``dealflow/triage/entity_repair`` (ported verbatim, review
  007), the old ``domain/events`` (``extract_date``) -> ``seams.evmod`` (``events/when.extract_date`` at the scan's
  day), and in ``sources_v2.py`` the old ``connectors`` -> ``dealflow/scan/parsers``.

Hand-written, and marked as such inside ``parsers.py``: the network and file seams the old module reached
(``_get_raw`` / ``_request_json`` through ``core/net`` with the fixture transport and resolver of the run, decision e:
no TLS-insecure fallback; ``_snap_path`` / ``_load_snapshot`` / ``_save_snapshot`` over the baselines the run resolved
in phase 1), and three thin wrappers (``_peek``, ``_mark``, ``make``) that only RECORD which cursor key each record
was made under, so the run can keep a refused record's key out of the cursor (revision 2).
"""

import ast
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
OLD_REPO = pathlib.Path(os.environ.get("PZ_OLD_REPO", str(ROOT.parent / "project-zero")))
OLD = OLD_REPO / "backend" / "src" / "projectzero" / "domain"
NEW = ROOT / "backend" / "src" / "projectzero" / "dealflow" / "scan"
NEW_TASTE = ROOT / "backend" / "src" / "projectzero" / "conviction" / "taste.py"

CONNECTORS = [
    "TIMEOUT", "UA", "_TL", "_set_deadline", "_remaining", "_expired", "_net_timeout", "FEED_KEYWORDS", "NOISE",
    "_uid", "_FETCH_TL", "FetchFailure", "_fetch_reset", "_fetch_stats", "_fetch_note", "_get", "AMBIGUOUS_KW",
    "strong_archetypes", "make", "_HEADLINE_LABELS", "_CITY_BASED", "_COUNTRY_POSS", "_FUNDING_VERBS", "_NAME_TOKEN",
    "_NAME_RUN", "_NAME_STOP", "_valid_company", "extract_company", "_strip", "feed", "_Text", "_lines",
    "COMPANY_HINT", "page", "_DATE_NOISE", "_date_only", "_SUFFIX", "INTERSTITIAL", "is_interstitial",
    "parse_source_date", "norm_company", "SECTOR_KEYWORDS", "_SECTOR_RE", "classify_sectors", "_ACADEMIC",
    "is_academic", "entity_keys", "_peek", "_mark", "_seen", "_mk_from", "p_sbir", "p_nsf", "p_nih",
    "_GTR_ORG_CACHE", "_gtr_org", "_GTR_ORG_RELS", "_gtr_fetch", "p_gtr", "_cordis_orgs", "p_cordis", "p_ckan",
    "PARSERS", "PARSERS.update", "_scan_one", "_BATCH_TIER", "_batch_order", "_resolve_batch", "RUNTIME_KEYS",
]  # fmt: skip
V2_SKIP = {"URL_REPAIRS", "URL_REPAIRS_MULTI", "NOTE_REPAIRS", "registry_entries"}
TASTE = ["suggest_twins", "tag_archetypes"]

CONNECTORS_REPLACE = [  # (old, new, count)
    ("UA = net.USER_AGENT\n", "UA = seams.USER_AGENT\n", 1),
    ("date.today()", "seams.today()", 6),
    (
        "    from projectzero.domain import entity_repair\n    from projectzero.domain import events as evmod\n",
        "    from projectzero.dealflow.triage import entity_repair\n    evmod = seams.evmod\n",
        1,
    ),
    (
        "            from projectzero.domain import entity_repair\n",
        "            from projectzero.dealflow.triage import entity_repair\n",
        1,
    ),
]
V2_REPLACE = [
    ("from projectzero.domain import connectors\n", "from projectzero.dealflow.scan import parsers as connectors\n", 8)
]


def _same(a: ast.AST, b: ast.AST) -> bool:
    return ast.dump(a) == ast.dump(b)  # include_attributes=False: positions are ignored


def _name(node: ast.stmt) -> str | None:
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):  # e.g. PARSERS.update(...)
        func = node.value.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            return f"{func.value.id}.{func.attr}"
    return None


def nodes(path: pathlib.Path) -> tuple[list[str], list[tuple[str | None, ast.stmt]]]:
    src = path.read_text(encoding="utf-8")
    return src.splitlines(keepends=True), [(_name(n), n) for n in ast.parse(src).body]


def text_of(lines: list[str], node: ast.stmt) -> str:
    text = "".join(lines[node.lineno - 1 : node.end_lineno])
    assert _same(ast.parse(text).body[0], node), _name(node)  # the cut compiles and is the old statement
    return text


def cut(path: pathlib.Path, names: list[str]) -> str:
    lines, found = nodes(path)
    by = {}
    for name, node in found:
        if name in names:
            assert name not in by, (path.name, name)
            by[name] = text_of(lines, node)
    missing = [n for n in names if n not in by]
    assert not missing, (path.name, missing)
    return "\n\n".join(by[n].rstrip("\n") for n in names) + "\n"


def cut_all_but(path: pathlib.Path, skip: set[str]) -> str:
    lines, found = nodes(path)
    parts = []
    for name, node in found:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):  # the module docstring
            continue
        if name in skip:
            continue
        parts.append(text_of(lines, node).rstrip("\n"))
    names = {n for n, _ in found}
    assert skip <= names, skip - names
    return "\n\n".join(parts) + "\n"


def replace(text: str, rules: list[tuple[str, str, int]]) -> str:
    for old, new, count in rules:
        assert text.count(old) == count, (old, text.count(old), count)
        text = text.replace(old, new)
    return text


def same_table(name: str) -> None:
    """The Taste Map table ``conviction/taste.py`` holds is the old one, node for node."""
    old = {n: node for n, node in nodes(OLD / "taste.py")[1]}[name]
    new = {n: node for n, node in nodes(NEW_TASTE)[1]}[name]
    assert isinstance(old, ast.Assign) and isinstance(new, ast.Assign) and _same(old.value, new.value), name


HEAD = '''# ruff: noqa
# mypy: ignore-errors
# (protected scanning rules, copied by script from the old modules; see the header. The cut code is the old untyped
# code verbatim, so it is exempt from lint and type checks, like a vendored module.)
"""{doc}"""

# fmt: off
'''

PARSERS_DOC = """The Deal Flow scan's parsers (review 034a), cut MECHANICALLY from the old ``domain/connectors.py`` at
revision 6c739b9 by exact top-level line ranges (``scripts/gen_scan_catalog.py``); nothing is retyped. See the
script's header for the cut list and the declared replacements (the clock, the user agent, the lazy imports).

Pure over fetched bytes: every request goes through ``seams`` (``core/net`` with the run's transport and resolver),
every page-watcher baseline comes from the run's phase-1 read, and nothing here touches the database. The cursor of a
structured source (``src["hwm"]``) and the baseline of a watcher are advanced on the source COPY the run hands in;
the run decides what is kept (``dealflow/scan/run.py``).
"""

SEAMS = '''
# ── hand-written seams (NOT cut): what the old module reached outside itself ───────────────────────────────────────
def _snap_path(name):
    """The old ``<data>/.watch/<name>``: here the baseline's key (``<uid(url)>.json``), resolved by the run."""
    return name


def _get_raw(url):
    """The network call behind :func:`_get`: ``core/net`` (SSRF guard, pinned addresses, verified TLS: decision e drops
    the old insecure-TLS retry) with the old browser headers and the old per-request timeout."""
    return seams.get_raw(url, _net_timeout())


def _request_json(url, data=None, headers=None):
    """JSON API call for the structured parsers (not counted in the per-source page telemetry, like v1)."""
    return seams.request_json(url, data, {"User-Agent": UA, **(headers or {})}, _net_timeout())


def _load_snapshot(path):
    return seams.load_snapshot(path)


def _save_snapshot(path, lines):
    seams.save_snapshot(path, lines)

'''

TRACKING = """

# ── hand-written tracking (NOT cut): which cursor key each record was made under (revision 2) ─────────────────────
# The old parsers mark a record's cursor key before (``_seen``, ``_seen_gate``) or after (GtR, CORDIS) making it; the
# run keeps the key of a record the intake REFUSED out of the cursor. These wrappers only record, then call the cut
# function unchanged (every caller looks the names up at call time).
_peek_cut, _mark_cut, _make_cut = _peek, _mark, make


def _peek(src, key):
    seams.note_key(key)
    return _peek_cut(src, key)


def _mark(src, key):
    seams.note_key(key)
    return _mark_cut(src, key)


def make(name, source, tier, url, dt, location, description, country, date_kind):
    c = _make_cut(name, source, tier, url, dt, location, description, country, date_kind)
    seams.note_record(c)
    return c
"""


def build() -> dict[str, str]:
    body = replace(cut(OLD / "connectors.py", CONNECTORS), CONNECTORS_REPLACE)
    parsers = (
        HEAD.format(doc=PARSERS_DOC)
        + "import contextlib\nimport hashlib\nimport html as _html\nimport json\nimport os\nimport re\n"
        + "import threading\nimport time\nimport xml.etree.ElementTree as ET\nfrom datetime import date, datetime\n"
        + "from email.utils import parsedate_to_datetime\nfrom html.parser import HTMLParser\n\n"
        + "from projectzero.dealflow.scan import seams, taste\n"
        + "from projectzero.dealflow.scan import sources_v2 as _sv2  # Deal Flow V2 Phase 2 official sources\n"
        + SEAMS
        + "\n# ── cut from domain/connectors.py ──\n"
        + body
        + TRACKING
        + "# fmt: on\n"
    )
    v2 = (
        HEAD.format(
            doc="The Deal Flow V2 official-source parsers (review 034a), cut MECHANICALLY from the old "
            "``domain/sources_v2.py``\nat revision 6c739b9 (``scripts/gen_scan_catalog.py``): the whole module but its "
            "registry data, which lives in\n``dealflow/sources/catalog.py`` (review 021). The only change: the lazy "
            "``connectors`` import names\n``dealflow/scan/parsers``.\n"
        )
        + "import html as _html\nimport re\nfrom urllib.parse import urljoin\n\n"
        + replace(cut_all_but(OLD / "sources_v2.py", V2_SKIP), V2_REPLACE)
        + "# fmt: on\n"
    )
    for table in ("ARCHETYPES", "PORTFOLIO"):
        same_table(table)
    taste = (
        HEAD.format(
            doc="Two Taste Map helpers the old scan read (review 034a), cut MECHANICALLY from the old "
            "``domain/taste.py`` at\nrevision 6c739b9 (``scripts/gen_scan_catalog.py``), over the tables "
            "``conviction/taste.py`` holds verbatim (the\nscript checks them node for node).\n"
        )
        + 'from projectzero.conviction.taste import ARCHETYPES, PORTFOLIO\n\n__all__ = ["ARCHETYPES", "PORTFOLIO", '
        + '"suggest_twins", "tag_archetypes"]\n\n'
        + cut(OLD / "taste.py", TASTE)
        + "# fmt: on\n"
    )
    out = {"parsers.py": parsers, "sources_v2.py": v2, "taste.py": taste}
    for name, text in out.items():
        compile(text, name, "exec")
    return out


if __name__ == "__main__":
    NEW.mkdir(parents=True, exist_ok=True)
    for name, text in build().items():
        (NEW / name).write_text(text, encoding="utf-8", newline="\n")
        print(name, len(text.splitlines()), "lines")

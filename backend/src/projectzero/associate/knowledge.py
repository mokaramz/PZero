# ruff: noqa: E501, RUF001
# (the index and its texts are the old module's lines, cut by script; see the header)
"""PZ Associate — the KNOWLEDGE layer (review 033a): how Project Zero works, from its own documentation.

The old ``services/associate/knowledge.py`` at revision 6c739b9. Cut WHOLE by script (``python -m
projectzero.ops.parity_associate cuts``; ``tests/associate`` checks the exact lines and the syntax trees):
``Section``, ``_WORD``, ``_STOP``, ``_tokens``, ``_lock``, ``_index``, ``_split``, ``index``, ``reset``,
``_excerpt`` and ``search`` (the BM25 index, verbatim). Hand-ported:

* ``DOCS``: the old list without ``SCOUT00_TRANSPORT.md`` (decision d); the ten documents are carried byte-identical
  under ``docs/associate/`` (``docs_dir``, still overridable with ``PZ_DOCS_DIR``);
* ``PAGES``: the old table without ``scout_intake``, ``native_scout`` and ``scout_bridge`` (decision c);
* ``_build``: the old body, with ONE change: each document's text goes through ``retire`` before ``_split``.

``retire`` (revision 2, Codex H-313) keeps every heading line and drops every PASSAGE (a paragraph, a list item, a
table row, a fenced block) of a section body that names a retired view, tool or link (``RETIRED``), or whose heading
path does. Everything else is kept line for line, so the index unit stays the old one (a section, its heading path and
its text, minus the retired passages) and the citation and offline formats are unchanged. A section left with no
passage has an empty body, which the old ``_split`` never indexes.

Documents are product knowledge, never instructions to the model: the engine wraps every excerpt as untrusted text.
"""

from __future__ import annotations

import math
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from projectzero.core.paths import REPO_ROOT

# The documents that describe the operating model, in the old order (decision d: no Scout 00 transport).
DOCS: list[tuple[str, str]] = [
    ("OPERATOR_GUIDE.md", "Operator guide"),
    ("PZ_ASSOCIATE.md", "PZ Associate"),
    ("USER_MANUAL.md", "User manual"),
    ("V1_SYSTEM.md", "System reference"),
    ("TRIAGE_COMPRESSION_AND_COMMITTEE.md", "Triage, compression & committee"),
    ("VALIDATION.md", "Validation"),
    ("product/PROJECT-ZERO-FINAL.md", "Product overview"),
    ("product/PROJECT-A-RADAR-01.md", "Project A Radar"),
    ("product/PROJECT-A-TASTE-MAP.md", "Project A Taste Map"),
    ("product/GETTING_STARTED_v1.md", "Getting started"),
]

# Where each concept lives in the app, in the old order (decision c: no Scout Intake, Native Scout or Scout Bridge).
# fmt: off
PAGES: dict[str, dict[str, str]] = {
    "investment_desk": {"path": "/", "title": "Investment Desk", "what": "orientation: what needs you, what is blocked, the best opportunity"},
    "today": {"path": "/today", "title": "Today", "what": "the daily operating brief: missions, Manager decisions, events, machine work"},
    "deal_flow": {"path": "/deal-flow", "title": "Deal Flow", "what": "discovered candidates to decide: Reject / Research / Keep, machine triage, Agent Review Queue"},
    "conviction": {"path": "/conviction", "title": "Conviction", "what": "the companies you chose to follow: prepared case, PZ Review, verification, Manager gates"},
    "radar": {"path": "/radar", "title": "Radar", "what": "Project A Radar Top 10: fully verified companies only, research queue, conflict-gated"},
    "founder_calls": {"path": "/founder-calls", "title": "Founder Calls", "what": "founder call workspace: preparation, notes, outcomes"},
    "events": {"path": "/events", "title": "Events", "what": "where to show up: scored events, Where should I go, weekend plan"},
    "network": {"path": "/network", "title": "Network", "what": "relationships, follow-ups, introductions"},
    "validation": {"path": "/validation", "title": "Validation", "what": "is Project Zero early and right: outcomes, misses, source value"},
    "system_health": {"path": "/health", "title": "System health", "what": "sources, background jobs, model budget, data integrity"},
}

# fmt: on
# ONE pattern list (revision 2): a passage naming any of these is left out of the index.
RETIRED: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.I)
    for p in (
        r"scout[\s_-]*bridge",  # the Scout Bridge view, /scout-bridge
        r"scout[\s_-]*00",  # Scout 00, scout00, SCOUT00_TRANSPORT
        r"native[\s_-]*scout",  # the native scout, native_scout
        r"scout[\s_-]*intake",  # Scout Intake, /scout-intake, the scout_intake tool
        r"scout[\s_-]*items?\b",  # the scout_item tool, a Scout Intake item
        r"native[\s_-]*signals?\b",  # the native_signals tool
        r"\bgrok\b",  # the Grok search bridge (and its chat app)
        r"search[\s_-]*bridge",  # the Grok search bridge
        r"\?item=",  # the retired ?item= context (a Scout Intake item)
    )
)

# Codex H-317: the documents' local-data claims are corrected at index time (the files stay byte-identical), so an
# offline answer agrees with the page: the data now lives in the Project Zero database. Each is (pattern, wording).
CORRECTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\ball data stays local\b", re.I), "all data is saved in the Project Zero database"),
    (re.compile(r"\bdata stays local\b", re.I), "data in your Project Zero database"),
    (re.compile(r"\bConversations are kept locally\b"), "Conversations are saved in the Project Zero database"),
)
LOCAL_CLAIM = re.compile(r"data stays local|kept locally|stays? on this machine|on this machine", re.I)


def corrected(line: str) -> str:
    for pattern, wording in CORRECTIONS:
        line = pattern.sub(wording, line)
    return line


_HEADING = re.compile(r"^(#{1,4})\s+(.*)")  # the old ``_split``'s heading rule
_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
_FENCE = re.compile(r"^\s*```")


def retired(text: str) -> bool:
    return any(p.search(text) for p in RETIRED)


def passages(lines: list[str]) -> list[list[str]]:
    """A section body as its passages, line for line: each paragraph, list item (with its wrapped lines), table row
    and fenced block is one group; each blank line is a group of its own (never retired)."""
    groups: list[list[str]] = []
    growing: str | None = None  # the group the next line may continue: "text" (a paragraph or a list item), "fence"
    for line in lines:
        if growing == "fence":
            groups[-1].append(line)
            if _FENCE.match(line):
                growing = None
        elif not line.strip():
            groups.append([line])
            growing = None
        elif _FENCE.match(line):
            groups.append([line])
            growing = "fence"
        elif line.lstrip().startswith("|"):
            groups.append([line])
            growing = None
        elif _ITEM.match(line) or growing is None:
            groups.append([line])
            growing = "text"
        else:
            groups[-1].append(line)
    return groups


def retire(text: str, title: str = "") -> str:
    """The document without its retired passages: headings are walked exactly as the old ``_split`` walks them, and a
    passage is dropped when it, or its section's heading path, names a retired view, tool or link."""
    out: list[str] = []
    path: list[str] = []
    body: list[str] = []

    def flush() -> None:
        heading = " › ".join(path) or title
        for group in passages(body):
            if not (retired(heading) or retired("\n".join(group))):
                out.extend(corrected(line) for line in group)  # Codex H-317
        body.clear()

    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            flush()
            out.append(line)
            level = len(m.group(1))
            path = [*path[: level - 1], m.group(2).strip()]
        else:
            body.append(line)
    flush()
    return "\n".join(out)


# fmt: off
# ── cut from services/associate/knowledge.py: Section, _WORD, _STOP, _tokens ──
@dataclass
class Section:
    doc: str
    doc_title: str
    heading: str
    text: str
    tokens: list[str]


_WORD = re.compile(r"[a-z0-9][a-z0-9\-]+")
_STOP = set(
    ["the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are", "be", "it", "this", "that", "as", "by", "at", "from", "your", "you", "we", "our", "i", "what", "how", "do", "does", "can", "which", "when", "where", "why", "who", "into", "than", "then", "there", "their", "them", "they", "its", "if", "not", "no", "yes", "only", "also", "all", "any", "each", "per", "via", "one"]
)


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1]
# ── end of cut ──
# fmt: on


def docs_dir() -> Path:
    override = os.environ.get("PZ_DOCS_DIR")
    if override:
        return Path(override)
    return REPO_ROOT / "docs" / "associate"


# fmt: off
# ── cut from services/associate/knowledge.py: _lock, _index, _split ──
_lock = threading.Lock()
_index: dict[str, Any] | None = None


def _split(doc: str, title: str, text: str) -> list[Section]:
    out: list[Section] = []
    path: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            heading = " › ".join(path) or title
            out.append(Section(doc, title, heading, body, _tokens(heading + " " + heading + " " + body)))

    for line in text.splitlines():
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            flush()
            buf = []
            level = len(m.group(1))
            path = [*path[:level - 1], m.group(2).strip()]
        else:
            buf.append(line)
    flush()
    return out
# ── end of cut ──
# fmt: on


def _build() -> dict[str, Any]:
    root = docs_dir()
    sections: list[Section] = []
    missing: list[str] = []
    for rel, title in DOCS:
        p = root / rel
        try:
            sections.extend(_split(rel, title, retire(p.read_text(encoding="utf-8"), title)))  # (d) the one change
        except OSError:
            missing.append(rel)
    df: dict[str, int] = {}
    for s in sections:
        for t in set(s.tokens):
            df[t] = df.get(t, 0) + 1
    avg = sum(len(s.tokens) for s in sections) / max(1, len(sections))
    return {"sections": sections, "df": df, "avg": avg, "missing": missing, "root": str(root)}


# fmt: off
# ── cut from services/associate/knowledge.py: index, reset, _excerpt, search ──
def index() -> dict[str, Any]:
    global _index
    with _lock:
        if _index is None:
            _index = _build()
        return _index


def reset() -> None:
    global _index
    with _lock:
        _index = None


def _excerpt(text: str, terms: set[str], limit: int = 900) -> str:
    """The most relevant paragraph(s) of a section, bounded."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    scored = sorted(paras, key=lambda p: -len(terms & set(_tokens(p))))
    out = ""
    for p in scored:
        if len(out) + len(p) > limit:
            break
        out = (out + "\n\n" + p) if out else p
    return (out or text)[:limit]


def search(query: str, k: int = 4) -> dict[str, Any]:
    ix = index()
    q = _tokens(query)
    if not ix["sections"]:
        return {"available": False, "results": [], "note": f"documentation not found at {ix['root']}"}
    if not q:
        return {"available": True, "results": [], "note": "empty query"}
    n = len(ix["sections"])
    scores: list[tuple[float, Section]] = []
    for s in ix["sections"]:
        tf: dict[str, int] = {}
        for t in s.tokens:
            tf[t] = tf.get(t, 0) + 1
        score = 0.0
        for t in set(q):
            if t not in tf:
                continue
            idf = math.log(1 + (n - ix["df"][t] + 0.5) / (ix["df"][t] + 0.5))
            f = tf[t]
            score += idf * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * len(s.tokens) / ix["avg"]))
        if score > 0:
            scores.append((score, s))
    scores.sort(key=lambda x: -x[0])
    terms = set(q)
    results = [
        {"doc": s.doc, "doc_title": s.doc_title, "section": s.heading, "excerpt": _excerpt(s.text, terms), "score": round(sc, 2)}
        for sc, s in scores[:k]
    ]
    return {"available": True, "results": results, "missing_docs": ix["missing"]}
# ── end of cut ──
# fmt: on

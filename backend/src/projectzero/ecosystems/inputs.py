"""What the coverage read and the adoption are computed from (review 022, plan revisions 2 and 3).

``CoverageInputs`` gathers everything the old ``domain/coverage.py`` read from the data folder, as plain values: the
route layer loads them (one consistent read) and the pure functions compute. The imported documents are the
BASELINE and are never rewritten; the ``coverage_adoptions`` rows (adoptions made here) overlay them:

* ``merged_overrides``: the imported ``coverage_sources.json`` ``sources`` (audit overrides by source id, adopted or
  not), then each row's declaration ``{families, countries, cities, note}`` under its own ``source_id`` (as the old
  adopt wrote it into that file);
* ``merged_adoptions``: the imported ``coverage_adopted.json`` ``adopted`` (each with its original ``source_id``,
  ``on`` and ``by``), then each row for a candidate NOT already adopted there, as ``{source_id, on, by}`` with ``on``
  the Berlin wall time of ``adopted_at`` in the old ``%Y-%m-%d %H:%M`` form. A row never replaces an imported
  adoption; an EMPTY imported record (``{}``) is the one exception, because the old code did not count it as adopted
  and its adopt then overwrote it.

The shipped candidate registries and the audit report (``resources/coverage``, copied byte-for-byte from the old
repository) are read once per process; tests may pass their own.
"""

from __future__ import annotations

import copy
import functools
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from projectzero.network.view import berlin_now

RESOURCES = Path(__file__).resolve().parents[1] / "resources" / "coverage"  # the old DOCS_COVERAGE


@functools.cache
def shipped_candidates() -> tuple[tuple[str, Any], ...]:
    """The shipped ``PROJECT_ZERO_SOURCE_REGISTRY_CANDIDATE*.json`` as ``(file name, body)``, in the old sorted order;
    an unreadable file reads as ``{}`` (the old tolerant read)."""
    out = []
    for p in sorted(RESOURCES.glob("PROJECT_ZERO_SOURCE_REGISTRY_CANDIDATE*.json"), key=str):
        try:
            body = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            body = {}
        out.append((p.name, body))
    return tuple(out)


@functools.cache
def audit_docs() -> tuple[tuple[str, str], ...]:
    """The shipped ``*.md`` audit reports as ``(file name, text)``, sorted by name (unreadable ones skipped)."""
    out = []
    for fn in sorted(p.name for p in RESOURCES.iterdir()) if RESOURCES.is_dir() else []:
        if not fn.endswith(".md"):
            continue
        try:
            out.append((fn, (RESOURCES / fn).read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    return tuple(out)


@dataclass(frozen=True)
class CoverageInputs:
    """Everything coverage needs. A document is its stored JSON body, or ``None`` when it does not exist (read as the
    old default, in memory only: decision a). Record lists are in the old file order."""

    sources: list[dict[str, Any]] = field(default_factory=list)  # the NORMALIZED Deal Flow registry (load_registry)
    event_health: Any = None  # event_health.json
    radar_regions: Any = None  # radar_regions.json
    radar_sources: Any = None  # radar_sources.json
    radar_health: Any = None  # radar_health.json
    inbox: Any = None  # the inbox candidate records (old inbox.json "candidates")
    signals: Any = None  # the Conviction records (old real_data.json "signals")
    people: Any = None  # the person records (old people.json "people")
    events: Any = None  # the event records (old events.json "events")
    coverage_sources: Any = None  # coverage_sources.json
    coverage_adopted: Any = None  # coverage_adopted.json
    coverage_registry: Any = None  # coverage_registry.json
    coverage_candidates: Any = None  # coverage_candidates.json (the data-folder candidate registry)
    ecosystems_doc: Any = None  # ecosystems.json
    adoptions: list[dict[str, Any]] = field(default_factory=list)  # coverage_adoptions rows, by adopted_at
    candidate_files: tuple[tuple[str, Any], ...] = field(default_factory=shipped_candidates)
    audit_files: tuple[tuple[str, str], ...] = field(default_factory=audit_docs)


def _doc(body: Any, default: Any) -> Any:
    """The old tolerant read: a missing document is (a copy of) the default."""
    return copy.deepcopy(default) if body is None else body


def adopted_on(at: Any) -> str:
    """A row's ``adopted_at`` (a datetime or ISO text) as the old ``on``: Berlin wall time ``%Y-%m-%d %H:%M``."""
    when = at if isinstance(at, datetime) else datetime.fromisoformat(str(at))
    return berlin_now(when).strftime("%Y-%m-%d %H:%M")


def merged_overrides(inputs: CoverageInputs) -> Any:
    """Source declarations by source id: the imported overrides, overlaid by each adoption row's declaration."""
    base = _doc(inputs.coverage_sources, {}).get("sources", {})
    if not inputs.adoptions:
        return base
    out = dict(base)
    for row in inputs.adoptions:
        out[row["source_id"]] = {
            "families": list(row["families"]),
            "countries": list(row["countries"]),
            "cities": list(row["cities"]),
            "note": row["note"],
        }
    return out


def merged_adoptions(inputs: CoverageInputs) -> Any:
    """Adoptions by candidate id: the imported ones, then the rows for candidates not already adopted."""
    base = _doc(inputs.coverage_adopted, {}).get("adopted", {})
    if not inputs.adoptions:
        return base
    out = dict(base)
    for row in inputs.adoptions:
        if out.get(row["candidate_id"]):  # a row never replaces an imported adoption (an EMPTY one did not count)
            continue
        out[row["candidate_id"]] = {"source_id": row["source_id"], "on": adopted_on(row["adopted_at"]), "by": row["by"]}
    return out

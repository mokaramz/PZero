"""Per-source counter DELTAS since the import (review 021, decision a, Codex H-155 / H-157).

The imported ``sources.json`` holds every increment the old app made (``registry_quality`` / ``registry_yield``). The
rewrite did not port those increments; it records the events instead, and this module derives what the old app would
have added since, with the old rules:

* ``yield.kept / research / rejected``: +1 per live candidate status event that changes the OLD decision
  (``STATUS_TO_DECISION``: ``reviewing`` is research, ``archived`` reads as rejected) to one of the three, credited to
  the ``source_id`` the event recorded at decision time (``detail.sources``, Codex H-161). A repeated decision is no
  vote (the old ``target.decision != decision``). Conviction creations without a status event cast no vote (the old
  yield needed an explicit ``inbox_id``). Status-earned quality credits use the recorded ``quality_source_id`` too.
* ``quality.kept``: ONCE per candidate, earned by the FIRST eligible event in time order (Codex H-159): a live status
  event to kept, credited to its ``quality_source_id`` (else ``source_id``), or a live Conviction ``create`` event
  whose record carries an ``inbox_id`` (explicit or name-matched; the old ``milestone(cx, "kept")``), credited to the
  entry's recorded ``source_id``; not at all when the imported ``q_milestones`` already carries ``kept``. An event
  with no source credits nothing and consumes nothing (the old milestone returned before marking).
* ``quality.researched``: once per candidate, its first live status event to research, the same guard.
* ``quality.radar``: the Conviction ``radar_milestone`` events with ``counted: true`` (review 019), by ``source_id``.
* ``quality.candidates_found`` (review 034a): the Deal Flow scan's candidates carry the old milestone's ``q_found``
  in their scan record (``attrs.scan_record``, every source the record was credited to, once each): +1 per entry.
* ``attention_queue``, ``sent_to_omar``, ``omar_positive``, ``omar_negative``: no delta; their producing flows (the
  inbox read credit, the Manager handoff) are not ported yet.

``deltas`` READS only; the totals exist only in the view (``view.apply``). The stored records keep the baseline.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from projectzero.core.db import schema_ident
from projectzero.dealflow.ranking.service import STATUS_TO_DECISION, ranking_input

YIELD_OF = {"kept": "kept", "research": "research", "rejected": "rejected"}
Deltas = dict[str, dict[str, dict[str, int]]]  # source_id -> {"quality": {...}, "yield": {...}}

_STATUS = """
    select e.id, e.candidate_id, e.from_status, e.to_status, e.at, e.detail->'sources' as sources
    from {s}.candidate_events e
    where e.action = 'status' and e.actor <> 'import' order by e.at, e.id
"""
_CREATES = """
    select id, after->>'inbox_id' as candidate_id, after->>'source_id' as source_id, at from {s}.conviction_events
    where action = 'create' and coalesce(after->>'inbox_id', '') <> '' order by at, id
"""
_FOUND = """
    select attrs->'scan_record'->'q_found' as found from {s}.candidates
    where jsonb_typeof(attrs->'scan_record'->'q_found') = 'array' order by id
"""
_RADAR = """
    select detail->>'source_id' as source_id, count(*) as n from {s}.conviction_events
    where action = 'radar_milestone' and (detail->>'counted')::boolean group by 1
"""


def _bump(out: Deltas, sid: Any, group: str, key: str) -> None:
    if isinstance(sid, str) and sid:
        out.setdefault(sid, {"quality": {}, "yield": {}})
        out[sid][group][key] = out[sid][group].get(key, 0) + 1


def _key(v: Any) -> tuple[int, str]:
    """A sort key for a timestamp or id that may be missing: missing first, then by value."""
    return (0, "") if v is None else (1, v.isoformat() if hasattr(v, "isoformat") else f"{v!s:>20}")


def _sources_at_decision(e: Mapping[str, Any], c: Mapping[str, Any]) -> dict[str, Any]:
    """The sources a status event credits: the ones it recorded at decision time (``detail.sources``, Codex H-161);
    for an event written before they were recorded, the candidate's current provenance (the fallback: no such event
    exists in production, whose writes start after the import)."""
    rec = e.get("sources")
    if isinstance(rec, Mapping):
        return {"source_id": rec.get("source_id"), "quality_source_id": rec.get("quality_source_id")}
    return {"source_id": c.get("source_id"), "quality_source_id": c.get("quality_source_id") or c.get("source_id")}


def derive(
    status_events: Iterable[Mapping[str, Any]],
    creates: Iterable[Mapping[str, Any]],
    candidates: Mapping[str, Mapping[str, Any]],
    radar: Mapping[str, int],
    found: Iterable[Any] = (),
) -> Deltas:
    """The pure rule. ``candidates``: id -> the candidate's ranking record (``source_id``, ``quality_source_id``,
    ``q_milestones``). Status events and Conviction creations are taken in their RELATIVE time order (``at``, then a
    creation before a status event of the same instant, then id: an explicit Keep writes both in one transaction and
    the old save credited the milestone first), so the first eligible event earns the quality credit (Codex H-159)."""
    out: Deltas = {}
    milestone_done: dict[str, set[str]] = defaultdict(set)  # candidate -> metrics credited (imported or live)
    for cid, c in candidates.items():
        milestone_done[cid] |= {m for m in (c.get("q_milestones") or []) if isinstance(m, str)}

    def quality_credit(cid: str, metric: str, sid: Any) -> None:
        """The old ``milestone``: no source, nothing credited and nothing consumed; else once per candidate."""
        if not (isinstance(sid, str) and sid) or metric in milestone_done[cid]:
            return
        milestone_done[cid].add(metric)
        _bump(out, sid, "quality", metric)

    stream = sorted(
        [(e.get("at"), 1, e.get("id"), "status", e) for e in status_events]
        + [(c.get("at"), 0, c.get("id"), "create", c) for c in creates],
        key=lambda t: (_key(t[0]), t[1], _key(t[2])),
    )
    for _at, _rank, _id, kind, e in stream:
        if (
            kind == "create"
        ):  # a creation carrying an inbox_id (explicit or name-matched): the old milestone(cx, "kept")
            quality_credit(str(e["candidate_id"]), "kept", e.get("source_id"))
            continue
        src = _sources_at_decision(e, candidates.get(str(e["candidate_id"])) or {})
        before = STATUS_TO_DECISION.get(str(e.get("from_status")))
        after = STATUS_TO_DECISION.get(str(e.get("to_status")))
        if after in YIELD_OF and before != after:
            _bump(out, src["source_id"], "yield", YIELD_OF[after])
        if after == "kept":
            quality_credit(str(e["candidate_id"]), "kept", src["quality_source_id"])
        elif after == "research":
            quality_credit(str(e["candidate_id"]), "researched", src["quality_source_id"])
    for sid, n in radar.items():
        for _ in range(int(n)):
            _bump(out, sid, "quality", "radar")
    for sid in found:  # review 034a: the scan's candidates_found milestones (each record's ``q_found``)
        _bump(out, sid, "quality", "candidates_found")
    return out


def deltas(conn: psycopg.Connection[Any], schema: str) -> Deltas:
    s = schema_ident(schema)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL(_STATUS).format(s=s))
        status = list(cur.fetchall())
        cur.execute(sql.SQL(_CREATES).format(s=s))
        creates = list(cur.fetchall())
        cur.execute(sql.SQL(_RADAR).format(s=s))
        radar = {r["source_id"]: int(r["n"]) for r in cur.fetchall() if r["source_id"]}
        cur.execute(sql.SQL(_FOUND).format(s=s))
        found = [sid for r in cur.fetchall() for sid in r["found"] or [] if isinstance(sid, str)]
        ids = sorted({str(e["candidate_id"]) for e in status} | {str(c["candidate_id"]) for c in creates})
        candidates: dict[str, dict[str, Any]] = {}
        if ids:
            cur.execute(sql.SQL("select * from {s}.candidates where id = any(%s)").format(s=s), (ids,))
            candidates = {str(r["id"]): ranking_input(r)[0] for r in cur.fetchall()}
    return derive(status, creates, candidates, radar, found)

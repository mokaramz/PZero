"""The Network read model (review 013): the old ``people.listing``, ``ecosys.talent_tree`` and watchlist, verbatim.

Pure functions over the person records in the old ``people.json`` order (the store reads them: the archived file
order, then people created here by ``created_at``, then ``id``). The clock is a parameter: ``today`` is the
Europe/Berlin date of the request's clock (the old local ``date.today()``). Reads never write.

Old source (rev 6c739b9): ``domain/people.py`` ``get`` / ``chain_of`` / ``listing`` (:196-224), ``domain/ecosys.py``
``talent_tree`` (:526-561), ``api/routers/network.py`` (``/people``, ``/watchlist``), ``api/routers/home.py``
(``/graph``). Every quirk is kept, among them:

* ``get`` is the FIRST record whose ``id`` equals (``==``) the asked id; a record without an id is never listed;
* ``introduced_by_name``: the introducer's ``name`` (``None`` when the introducer has no name key value), else the
  stored free-text ``introduced_by_name``, else ``""``;
* ``chain``: at most 6 introducer names upwards, stopping at a cycle or an unknown id; ``recommended_names``: the
  names of the RESOLVED recommended ids only (a string ``recommended`` is iterated character by character, as in the
  old code); either raising empties both;
* ``days_since_touch``: days since ``last_interaction`` (``None`` when it does not parse; negative in the future);
* ``due``: a next action whose date is today or earlier; an unparseable or missing date is due only when it is
  missing / empty (``not next_action_date``);
* the sort: due first, then the stalest (no date reads as 9999 days), stable (ties keep the record order);
* the graph: roots are the people without an introducer, depth 0..6, ONE ``seen`` set per root (a shared descendant is
  drawn once per root, under the first branch that reaches it); people in an introduction cycle have no root and are
  not drawn. Malformed link types raise, as they did in the old code.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
STRENGTHS = {"met_once": "Met once", "warm": "Warm", "strong": "Strong", "close": "Close"}
POTENTIAL = {"none": "—", "maybe": "Maybe", "high": "High", "building": "Building now"}
CHAIN_DEPTH = 6
TREE_DEPTH = 6


def berlin_now(now: datetime) -> datetime:
    """The request clock as Europe/Berlin wall time (a naive clock already is Berlin wall time, as in the old app)."""
    return now.astimezone(BERLIN) if now.tzinfo is not None else now


def berlin_today(now: datetime) -> date:
    return berlin_now(now).date()


def records(people: Any) -> list[dict[str, Any]]:
    """The old ``compat.records(people, ..., ("id",))``: dict records (of a list, or a dict's values) with an id."""
    if isinstance(people, dict):
        people = list(people.values())
    if not isinstance(people, list):
        return []
    return [r for r in people if isinstance(r, dict) and r.get("id") not in (None, "")]


class Index:
    """The old ``people.get(d, pid)`` (the first record whose id ``==`` pid) without its linear scan per call.

    A dict keeps the FIRST record per hashable id; ``==`` and dict lookup agree for hashable values. An unhashable id
    (a list or object in a legacy record) can only equal an unhashable value, so those fall back to the scan."""

    def __init__(self, people: Iterable[dict[str, Any]]) -> None:
        self.people = list(people)
        self.by_id: dict[Any, dict[str, Any]] = {}
        self.unhashable: list[dict[str, Any]] = []
        for p in self.people:
            pid = p.get("id")
            if isinstance(pid, Hashable):
                try:
                    self.by_id.setdefault(pid, p)
                    continue
                except TypeError:  # a tuple-like hashable that is not (cannot come from JSON, but stay faithful)
                    pass
            self.unhashable.append(p)

    def get(self, pid: Any) -> dict[str, Any] | None:
        if isinstance(pid, Hashable):
            try:
                return self.by_id.get(pid)
            except TypeError:
                pass
        return next((p for p in self.unhashable if p.get("id") == pid), None)


def chain_of(idx: Index, pid: Any, max_depth: int = CHAIN_DEPTH) -> list[Any]:
    """The old ``people.chain_of``, verbatim."""
    names: list[Any] = []
    seen: set[Any] = set()
    p = idx.get(pid)
    while p and p.get("introduced_by") and p["introduced_by"] not in seen and len(names) < max_depth:
        seen.add(p["id"])
        parent = idx.get(p["introduced_by"])
        if not parent:
            break
        names.append(parent.get("name", "?"))
        p = parent
    return names


def _iso_day(value: Any) -> date:
    return date.fromisoformat(value)  # the old ``date.fromisoformat``: raises on anything else (None, "", text)


def listing(people: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """The old ``people.listing()``: every person with its derived fields, due first, then the stalest."""
    recs = records(people)
    idx = Index(recs)
    out = []
    for p in recs:
        q = dict(p)
        intro = idx.get(p.get("introduced_by", "")) if p.get("introduced_by") else None
        q["introduced_by_name"] = intro.get("name") if intro else (p.get("introduced_by_name") or "")
        try:
            q["chain"] = chain_of(idx, p["id"])
            q["recommended_names"] = [
                rec.get("name") for r in p.get("recommended") or [] if (rec := idx.get(r)) is not None and rec
            ]
        except Exception:  # a legacy introduction chain never hides the person
            q["chain"], q["recommended_names"] = [], []
        try:
            q["days_since_touch"] = (today - _iso_day(p.get("last_interaction", ""))).days
        except Exception:
            q["days_since_touch"] = None
        try:
            q["due"] = bool(p.get("next_action")) and _iso_day(p.get("next_action_date", "")) <= today
        except Exception:
            q["due"] = bool(p.get("next_action")) and not p.get("next_action_date")
        out.append(q)
    out.sort(key=lambda x: (not x["due"], -(x["days_since_touch"] if x["days_since_touch"] is not None else 9999)))
    return out


def people_view(people: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """The old ``GET /api/people``."""
    return {"people": listing(people, today), "strengths": dict(STRENGTHS), "potential": dict(POTENTIAL)}


def watchlist_view(people: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """The old ``GET /api/watchlist``: the listing (same order) filtered to the watched people."""
    return {"people": [x for x in listing(people, today) if x.get("watch")]}


def talent_tree(people: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The old ``ecosys.talent_tree()``, verbatim: introduction / recommendation chains as a forest."""
    recs = records(people)
    by_id = {p["id"]: p for p in recs}  # the old dict: the LAST record per id (the import blocks repeated ids)
    children: dict[Any, list[Any]] = {}
    for p in recs:
        for rid in p.get("recommended", []):
            children.setdefault(p["id"], []).append(rid)
        if p.get("introduced_by") and p["id"] not in children.get(p["introduced_by"], []):
            children.setdefault(p["introduced_by"], []).append(p["id"])
    roots = [p["id"] for p in recs if not p.get("introduced_by")]

    def node(pid: Any, depth: int = 0, seen: set[Any] | None = None) -> dict[str, Any] | None:
        seen = seen or set()
        if pid in seen or depth > TREE_DEPTH or pid not in by_id:
            return None
        seen.add(pid)
        p = by_id[pid]
        kids = [node(c, depth + 1, seen) for c in dict.fromkeys(children.get(pid, []))]
        return {
            "id": pid,
            "name": p.get("name", "?"),
            "role": p.get("role", ""),
            "company": p.get("company", ""),
            "founder_potential": p.get("founder_potential", "none"),
            "strength": p.get("relationship_strength", ""),
            "startups": p.get("startups", []),
            "watch": bool(p.get("watch")),
            "children": [k for k in kids if k],
        }

    forest = [node(r) for r in roots]
    return [f for f in forest if f]


def graph_view(people: list[dict[str, Any]]) -> dict[str, Any]:
    """The old ``GET /api/graph``."""
    return {"forest": talent_tree(people)}

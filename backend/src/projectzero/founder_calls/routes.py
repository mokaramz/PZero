"""The old ``api/routers/calls.py`` (rev 6c739b9) as pure functions over the founder_calls document (review 023).

Each function answers what the old route answered (status + body; a refusal is ``{"error": msg}`` with the old code).
The writes never change their input: they work on a deep copy and return an ``Outcome`` whose ``doc`` is the document
as the old route left ``founder_calls.json`` (the input object itself when the old route saved nothing or the saved
content is identical), and ``changed``: the ids of the records that differ from the input (added or modified), per
object, in document order. The old ``case_prep.request`` after a save is a no-op (decision a); its ``pipeline_slug``
is still added to the answer.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from projectzero.conviction.records import records
from projectzero.dealflow.ranking.names import slug as radar_slug
from projectzero.founder_calls import core
from projectzero.founder_calls.catalog import LABEL
from projectzero.network import view

OBJECTS = ("companies", "founders", "calls")
UNKNOWN_CALL = "unknown call"


def _no_changes() -> dict[str, list[str]]:
    return {k: [] for k in OBJECTS}


@dataclass(frozen=True)
class Outcome:
    status: int  # the old HTTP status
    body: dict[str, Any]  # the old answer
    doc: Any  # the document after the request (the input object when nothing changed)
    changed: dict[str, list[str]] = field(default_factory=_no_changes)  # {companies, founders, calls}: changed ids


def _working(doc: Any) -> dict[str, Any]:
    return copy.deepcopy(core.loaded(doc))


def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a == b and list(a) == list(b) and all(list(a[k]) == list(b[k]) for k in OBJECTS)


def _outcome(before: Any, after: dict[str, Any] | None, status: int, body: dict[str, Any]) -> Outcome:
    """``after``: the document the old route saved, or ``None`` when it saved nothing."""
    if after is None:
        return Outcome(status, body, before)
    base = core.loaded(before)
    if isinstance(before, dict) and _same(after, base):
        return Outcome(status, body, before)
    changed = {k: [i for i, r in after[k].items() if i not in base[k] or base[k][i] != r] for k in OBJECTS}
    return Outcome(status, body, after, changed)


def _refused(before: Any, status: int, message: str) -> Outcome:
    return Outcome(status, {"error": message}, before)


# ------------------------------------------------------------------ the pickers (old GET /api/calls)
def people_picker(people: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """``people``: the person records (``network.store.load_people``), in the old ``people.json`` order."""
    return [
        {"id": x["id"], "name": x.get("name", ""), "company": x.get("company", ""), "role": x.get("role", "")}
        for x in view.listing(people, today)
    ]


def pipeline_picker(pipeline: Any) -> list[dict[str, Any]]:
    """``pipeline``: the stored Conviction records (the old ``real_data.json`` ``signals``), in their order."""
    return [
        {
            "slug": radar_slug(e["company"]),
            "company": e["company"],
            "founders": [f.get("name", "") for f in (e.get("founders") or []) if isinstance(f, dict)],
        }
        for e in records(pipeline, ("company",))
    ]


# ------------------------------------------------------------------ reads
def workspace(
    doc: Any, *, people: list[dict[str, Any]], pipeline: Any, evaluations: Any, today: date
) -> dict[str, Any]:
    """``GET /api/calls``. ``evaluations``: the ``evaluations.json`` body ({} when missing or unreadable)."""
    return core.workspace(
        core.loaded(doc), evaluations, today, people=people_picker(people, today), pipeline=pipeline_picker(pipeline)
    )


def call_view(doc: Any, call_id: Any, *, today: date) -> dict[str, Any] | None:
    """``GET /api/call?id=``; ``None`` -> 404 ``{"error": "unknown call"}``."""
    d = core.loaded(doc)
    c = d["calls"].get(call_id)
    if not c:
        return None
    return core.call_view(d, c, today)


def memo(doc: Any, call_id: Any, *, today: date) -> dict[str, Any] | None:
    """``GET /api/call_memo?id=``: ``{markdown, label}``; ``None`` -> 404 ``{"error": "unknown call"}``."""
    md = core.memo_markdown(core.loaded(doc), call_id, today)
    if md is None:
        return None
    return {"markdown": md, "label": LABEL}


def briefing(doc: Any, body: dict[str, Any], *, today: date) -> tuple[int, dict[str, Any]]:
    """``POST /api/call_briefing``: explicit request only — generated on demand, never stored, never sent."""
    if not body.get("confirm"):
        return 400, {"error": "explicit confirmation required"}
    md = core.briefing_markdown(core.loaded(doc), body.get("founder_id", ""), today)
    if md is None:
        return 404, {"error": "no calls for this founder"}
    return 200, {"markdown": md, "label": LABEL}


# ------------------------------------------------------------------ writes
def save(
    doc: Any, body: dict[str, Any], *, today: date, now: datetime, new_id: Callable[[str], str] | None = None
) -> Outcome:
    """``POST /api/call_save``. ``new_id(prefix)``: the old ``_id`` (default ``prefix + uuid4().hex[:12]``)."""
    d = _working(doc)
    r = core.save_call(d, core.clock(now, today, new_id), body)
    if r.get("error"):
        return Outcome(400, r, doc)
    stored = d if r["changed"] else core.loaded(doc)
    r["call"] = core.call_view(stored, r["call"], today)
    co = (stored.get("companies") or {}).get((r["call"] or {}).get("company_id") or "") or {}
    if co.get("linked_pipeline_slug"):  # the old case_prep.request(slug, ...) is a no-op here (decision a)
        r["pipeline_slug"] = co["linked_pipeline_slug"]
    return _outcome(doc, d if r["changed"] else None, 200, r)


def followup(doc: Any, body: dict[str, Any], *, today: date, now: datetime) -> Outcome:
    """``POST /api/call_followup {id, done}``."""
    d = _working(doc)
    c, saved = core.set_followup(d, core.clock(now, today), body.get("id", ""), bool(body.get("done", True)))
    if not c:
        return _refused(doc, 404, UNKNOWN_CALL)
    stored = d if saved else core.loaded(doc)
    return _outcome(doc, d if saved else None, 200, {"ok": True, "call": core.call_view(stored, c, today)})


def link(
    doc: Any, body: dict[str, Any], *, people: list[dict[str, Any]], pipeline: Any, today: date, now: datetime
) -> Outcome:
    """``POST /api/call_link``: a founder to a person (``founder_id`` + ``person_id``), else a company to a pipeline
    company (``company_id`` + ``pipeline_slug`` / ``radar_key``); a link to an already linked record merges."""
    ck = core.clock(now, today)
    if body.get("founder_id"):
        pname = ""
        if body.get("person_id"):
            pname = next((x.get("name", "") for x in view.listing(people, today) if x["id"] == body["person_id"]), "")
            if not pname:
                return _refused(doc, 404, "unknown person")
        d = _working(doc)
        fid = core.link_founder(
            d, ck, body["founder_id"], person_id=body.get("person_id", ""), person_name=pname,
            company_id=body.get("company_id", ""),
        )  # fmt: skip
        return _outcome(doc, d if fid else None, 200, {"ok": bool(fid), "founder_id": fid})
    if body.get("company_id"):
        nm = ""
        if body.get("pipeline_slug"):
            nm = next(
                (
                    e["company"]
                    for e in records(pipeline, ("company",))
                    if radar_slug(e["company"]) == body["pipeline_slug"]
                ),
                "",
            )
            if not nm:
                return _refused(doc, 404, "unknown pipeline company")
        d = _working(doc)
        cid = core.link_company(
            d, ck, body["company_id"], pipeline_slug=body.get("pipeline_slug", ""), radar_key=body.get("radar_key", ""),
            name=nm,
        )  # fmt: skip
        return _outcome(doc, d if cid else None, 200, {"ok": bool(cid), "company_id": cid})
    return _refused(doc, 400, "founder_id or company_id required")

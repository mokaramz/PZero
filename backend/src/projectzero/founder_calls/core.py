# ruff: noqa: E501
# (the memo / briefing texts are the old lines, verbatim)
"""The old ``domain/founder_calls.py`` (rev 6c739b9), ported line for line over the document dict (review 023).

Every function works on ``d`` = the founder_calls document ``{version, label, companies, founders, calls}`` exactly
as the old ``load()`` returned it (``loaded``). The mutating ones change ``d`` IN PLACE, as the old code changed its
freshly loaded copy; ``routes`` hands them a deep copy and decides, as the old routes did, whether that copy was
"saved". Nothing here reads a file, a clock or a random source:

* the old ``_now()`` / ``_today()`` / ``_id()`` are the ``Clock`` fields ``now`` (Berlin wall clock,
  ``%Y-%m-%d %H:%M:%S``), ``today`` (ISO day) and ``new_id(prefix)`` (default: ``prefix + uuid4().hex[:12]``);
* ``due_state`` / the views take ``today`` (a ``date``) instead of reading ``date.today()``;
* the Active Evaluator filter (``is_conversation`` / ``conversations``) is the already ported
  ``conviction.operator`` one (identical code), fed the ``evaluations.json`` body instead of reading the file;
* ``storage.state_lock`` / ``load`` / ``save`` are gone (the route layer owns the transaction).

Dict insertion order is the old one throughout: new records are appended (``d[...][k] = ...``), a merge keeps both
records in place, keys added to a record (``merged_into``, ``aliases`` via ``setdefault``) go last, exactly where the
old code put them.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from projectzero.conviction.operator import conversations as _conversations
from projectzero.founder_calls.catalog import (
    ASSESSMENT_FIELDS,
    CALL_TYPES,
    CHANNELS,
    CONFIDENCE,
    LABEL,
    OWNERS,
    RECOMMENDATIONS,
    SUMMARY_LABEL,
    TEMPLATES,
    UNKNOWN,
    UPCOMING_DAYS,
)
from projectzero.network.view import berlin_now


# ------------------------------------------------------------------ the clock and ids (old _now / _today / _id)
def random_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:12]


@dataclass(frozen=True)
class Clock:
    now: str  # the old _now(): "%Y-%m-%d %H:%M:%S", Berlin wall clock
    today: str  # the old _today(): the Berlin day, ISO
    new_id: Callable[[str], str] = random_id  # the old _id(prefix)


def clock(now: datetime, today: date, new_id: Callable[[str], str] | None = None) -> Clock:
    return Clock(berlin_now(now).strftime("%Y-%m-%d %H:%M:%S"), today.isoformat(), new_id or random_id)


def empty() -> dict[str, Any]:
    return {"version": 1, "label": LABEL, "companies": {}, "founders": {}, "calls": {}}


def loaded(doc: Any) -> dict[str, Any]:
    """The old ``load()`` over a stored body: not a dict -> empty; missing top-level keys appended (a shallow copy)."""
    if not isinstance(doc, dict):
        return empty()
    d = dict(doc)
    for k, v in empty().items():
        d.setdefault(k, v)
    return d


def conversations(d: dict[str, Any], evaluations: Any) -> dict[str, dict[str, Any]]:
    """The old ``conversations(d)``; ``evaluations``: the ``evaluations.json`` body ({} when missing or unreadable)."""
    return _conversations(d, evaluations)


def norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


# ------------------------------------------------------------------ identity: companies and founders
def resolve_company(d: dict[str, Any], cid: Any) -> Any:
    seen: set[Any] = set()
    while cid and cid in d["companies"] and d["companies"][cid].get("merged_into") and cid not in seen:
        seen.add(cid)
        cid = d["companies"][cid]["merged_into"]
    return cid if cid in d["companies"] else None


def resolve_founder(d: dict[str, Any], fid: Any) -> Any:
    seen: set[Any] = set()
    while fid and fid in d["founders"] and d["founders"][fid].get("merged_into") and fid not in seen:
        seen.add(fid)
        fid = d["founders"][fid]["merged_into"]
    return fid if fid in d["founders"] else None


def ensure_company(
    d: dict[str, Any], ck: Clock, name: Any = "", pipeline_slug: Any = "", radar_key: Any = "", company_id: Any = ""
) -> Any:
    """Find or create a company record — by id, by linked pipeline slug / radar key, then by normalized name."""
    cid = resolve_company(d, company_id)
    if cid:
        return cid
    live = [(k, c) for k, c in d["companies"].items() if not c.get("merged_into")]
    if pipeline_slug:
        for k, c in live:
            if c.get("linked_pipeline_slug") == pipeline_slug:
                return k
    if radar_key:
        for k, c in live:
            if c.get("linked_radar_key") == radar_key:
                return k
    n = norm(name)
    if n:
        for k, c in live:
            if norm(c.get("name")) == n:
                if pipeline_slug and not c.get("linked_pipeline_slug"):
                    c["linked_pipeline_slug"] = pipeline_slug
                    c["updated"] = ck.now
                if radar_key and not c.get("linked_radar_key"):
                    c["linked_radar_key"] = radar_key
                    c["updated"] = ck.now
                return k
    if not (name or pipeline_slug or radar_key):
        return None
    k = ck.new_id("fc-co-")
    d["companies"][k] = {
        "id": k,
        "name": name or pipeline_slug or radar_key,
        "linked_pipeline_slug": pipeline_slug or "",
        "linked_radar_key": radar_key or "",
        "external": not (pipeline_slug or radar_key),
        "aliases": [],
        "created": ck.now,
        "updated": ck.now,
    }
    return k


def ensure_founder(
    d: dict[str, Any], ck: Clock, name: Any = "", company_id: Any = "", person_id: Any = "", founder_id: Any = ""
) -> Any:
    """Find or create a founder record — by id, by linked Project Zero person id, then by (normalized name, company)."""
    fid = resolve_founder(d, founder_id)
    if fid:
        return fid
    live = [(k, f) for k, f in d["founders"].items() if not f.get("merged_into")]
    if person_id:
        for k, f in live:
            if f.get("linked_person_id") == person_id:
                return k
    n = norm(name)
    if n:
        for k, f in live:
            if norm(f.get("name")) == n and (
                not company_id or f.get("company_id") == company_id or not f.get("company_id")
            ):
                if company_id and not f.get("company_id"):
                    f["company_id"] = company_id
                    f["updated"] = ck.now
                if person_id and not f.get("linked_person_id"):
                    f["linked_person_id"] = person_id
                    f["updated"] = ck.now
                return k
    if not name:
        return None
    k = ck.new_id("fc-f-")
    d["founders"][k] = {
        "id": k,
        "name": name,
        "company_id": company_id or "",
        "linked_person_id": person_id or "",
        "external": not person_id,
        "aliases": [],
        "created": ck.now,
        "updated": ck.now,
    }
    return k


def _merge_founders(d: dict[str, Any], ck: Clock, loser: str, winner: str) -> None:
    """Re-point every call of `loser` to `winner`; keep `loser` as an alias that still resolves."""
    for c in d["calls"].values():
        if c.get("founder_id") == loser:
            c["founder_id"] = winner
    lf, wf = d["founders"][loser], d["founders"][winner]
    for a in [lf.get("name", ""), *list(lf.get("aliases") or [])]:
        if a and norm(a) != norm(wf.get("name")) and a not in wf.setdefault("aliases", []):
            wf["aliases"].append(a)
    if not wf.get("company_id") and lf.get("company_id"):
        wf["company_id"] = lf["company_id"]
    lf["merged_into"] = winner
    lf["updated"] = ck.now
    wf["updated"] = ck.now


def link_founder(
    d: dict[str, Any], ck: Clock, founder_id: Any, person_id: Any = "", person_name: Any = "", company_id: Any = ""
) -> Any:
    """Link a founder to a Project Zero person (merging into a record that already links that person). ``None``: an
    unknown founder (the old code then saved nothing); otherwise the old code saved ``d``."""
    fid = resolve_founder(d, founder_id)
    if not fid:
        return None
    f = d["founders"][fid]
    if person_id:
        other = next(
            (
                k
                for k, x in d["founders"].items()
                if k != fid and not x.get("merged_into") and x.get("linked_person_id") == person_id
            ),
            None,
        )
        if other:
            _merge_founders(d, ck, fid, other)
            fid = other
            f = d["founders"][fid]
        f["linked_person_id"] = person_id
        f["external"] = False
        if person_name and norm(person_name) != norm(f.get("name")) and person_name not in f.setdefault("aliases", []):
            f["aliases"].append(person_name)
    if company_id:
        f["company_id"] = resolve_company(d, company_id) or f.get("company_id", "")
    f["updated"] = ck.now
    return fid


def link_company(
    d: dict[str, Any], ck: Clock, company_id: Any, pipeline_slug: Any = "", radar_key: Any = "", name: Any = ""
) -> Any:
    """Link a company to a pipeline company / radar lead (merging into an already linked record). ``None``: an
    unknown company (nothing saved); otherwise the old code saved ``d``."""
    cid = resolve_company(d, company_id)
    if not cid:
        return None
    c = d["companies"][cid]
    other = None
    if pipeline_slug:
        other = next(
            (
                k
                for k, x in d["companies"].items()
                if k != cid and not x.get("merged_into") and x.get("linked_pipeline_slug") == pipeline_slug
            ),
            None,
        )
    if not other and radar_key:
        other = next(
            (
                k
                for k, x in d["companies"].items()
                if k != cid and not x.get("merged_into") and x.get("linked_radar_key") == radar_key
            ),
            None,
        )
    if other:
        for f in d["founders"].values():
            if f.get("company_id") == cid:
                f["company_id"] = other
        for call in d["calls"].values():
            if call.get("company_id") == cid:
                call["company_id"] = other
        oc = d["companies"][other]
        if c.get("name") and norm(c["name"]) != norm(oc.get("name")) and c["name"] not in oc.setdefault("aliases", []):
            oc["aliases"].append(c["name"])
        c["merged_into"] = other
        c["updated"] = ck.now
        cid = other
        c = oc
    if pipeline_slug:
        c["linked_pipeline_slug"] = pipeline_slug
    if radar_key:
        c["linked_radar_key"] = radar_key
    if name and norm(name) != norm(c.get("name")) and name not in c.setdefault("aliases", []):
        c["aliases"].append(name)
    c["external"] = not (c.get("linked_pipeline_slug") or c.get("linked_radar_key"))
    c["updated"] = ck.now
    return cid


# ------------------------------------------------------------------ calls
def _clean_list(v: Any) -> list[str]:
    if isinstance(v, str):
        v = [x.strip() for x in re.split(r"[\n;]+", v)]
    return [str(x).strip() for x in (v or []) if str(x).strip()]


def _normalize_answers(call_type: Any, raw: Any) -> dict[str, Any]:
    """{section_id: {"a": text, "unknown": bool, "followups": {index: text}}} — unknown answers stay visibly UNKNOWN."""
    t = TEMPLATES.get(call_type) or TEMPLATES["first"]
    out: dict[str, Any] = {}
    raw = raw if isinstance(raw, dict) else {}
    for s in t["sections"]:
        r = raw.get(s["id"]) if isinstance(raw.get(s["id"]), dict) else {"a": raw.get(s["id"], "")}
        a = str(r.get("a") or "").strip()
        fu: dict[str, str] = {}
        for i, _ in enumerate(s.get("followups") or []):
            v = str((r.get("followups") or {}).get(str(i)) or (r.get("followups") or {}).get(i) or "").strip()
            if v:
                fu[str(i)] = v
        out[s["id"]] = {"a": a, "unknown": (not a) or bool(r.get("unknown")), "followups": fu}
    return out


def _content(call: dict[str, Any]) -> str:
    """Everything that counts as content (timestamps excluded) — an identical edit is a no-op."""
    return json.dumps(
        {k: v for k, v in call.items() if k not in ("created", "updated")}, sort_keys=True, ensure_ascii=False
    )


def save_call(d: dict[str, Any], ck: Clock, body: dict[str, Any]) -> dict[str, Any]:
    """Create or update one call. The old code saved ``d`` exactly when the answer carries ``changed: True``."""
    call_id = str(body.get("id") or "")
    existing = d["calls"].get(call_id)
    if existing:
        company_id = resolve_company(d, body.get("company_id") or existing.get("company_id")) or existing.get(
            "company_id", ""
        )
        founder_id = resolve_founder(d, body.get("founder_id") or existing.get("founder_id")) or existing.get(
            "founder_id", ""
        )
    else:
        company_id = ensure_company(
            d,
            ck,
            name=body.get("company", ""),
            pipeline_slug=body.get("pipeline_slug", ""),
            radar_key=body.get("radar_key", ""),
            company_id=body.get("company_id", ""),
        )
        founder_id = ensure_founder(
            d,
            ck,
            name=body.get("founder", "") or body.get("name", ""),
            company_id=company_id or "",
            person_id=body.get("person_id", ""),
            founder_id=body.get("founder_id", ""),
        )
        if not company_id or not founder_id:
            return {"error": "founder name and company are required"}
        if body.get("person_id"):  # an existing Project Zero founder — link stays in this store only
            d["founders"][founder_id]["linked_person_id"] = body["person_id"]
            d["founders"][founder_id]["external"] = False
        call_id = call_id or ck.new_id("fc-call-")
    ct = body.get("call_type") if body.get("call_type") in CALL_TYPES else (existing or {}).get("call_type", "first")
    base = dict(existing) if existing else {"id": call_id, "created": ck.now}
    base.update({"founder_id": founder_id, "company_id": company_id, "call_type": ct})
    for k in ("date", "time", "channel", "discovery_origin", "intro_path", "objective", "observations"):
        if k in body:
            base[k] = str(body.get(k) or "").strip()
    base.setdefault("date", ck.today)
    base.setdefault("time", "")
    base.setdefault("channel", "video")
    for k in ("discovery_origin", "intro_path", "objective", "observations"):
        base.setdefault(k, "")
    if base["channel"] not in CHANNELS:
        base["channel"] = "other"
    if "participants" in body:
        base["participants"] = _clean_list(body.get("participants"))
    base.setdefault("participants", [])
    if "answers" in body or not existing:
        base["answers"] = _normalize_answers(ct, body.get("answers") or (existing or {}).get("answers") or {})
    elif existing and existing.get("call_type") != ct:
        base["answers"] = _normalize_answers(ct, existing.get("answers") or {})
    if "claims" in body:
        base["claims"] = [{"text": t, "label": LABEL} for t in _clean_list(body.get("claims"))]
    base.setdefault("claims", [])
    for k in ("risks", "open_questions"):
        if k in body:
            base[k] = _clean_list(body.get(k))
        base.setdefault(k, [])
    if "next_action" in body:
        na: Any = (
            body.get("next_action") if isinstance(body.get("next_action"), dict) else {"text": body.get("next_action")}
        )
        prev = (existing or {}).get("next_action") or {}
        base["next_action"] = {
            "text": str(na.get("text") or "").strip(),
            "owner": str(na.get("owner") or prev.get("owner") or "Mohamed").strip(),
            "due": str(na.get("due") or "").strip()[:10],
            "done": bool(na.get("done", prev.get("done", False))),
        }
    base.setdefault("next_action", {"text": "", "owner": "Mohamed", "due": "", "done": False})
    if "assessment" in body:
        a: Any = body.get("assessment") if isinstance(body.get("assessment"), dict) else {}
        prev = (existing or {}).get("assessment") or {}
        asm: dict[str, Any] = {}
        for k, _ in ASSESSMENT_FIELDS:
            asm[k] = str(a.get(k, prev.get(k, "")) or "").strip()
        asm["recommendation"] = (
            a.get("recommendation")
            if a.get("recommendation") in RECOMMENDATIONS
            else (prev.get("recommendation") or "")
        )
        asm["confidence"] = a.get("confidence") if a.get("confidence") in CONFIDENCE else (prev.get("confidence") or "")
        asm["next_action"] = str(a.get("next_action", prev.get("next_action", "")) or "").strip()
        base["assessment"] = asm
    base.setdefault(
        "assessment",
        {**{k: "" for k, _ in ASSESSMENT_FIELDS}, "recommendation": "", "confidence": "", "next_action": ""},
    )
    base["label"] = LABEL
    if existing and _content(existing) == _content(base):
        return {"ok": True, "call": existing, "changed": False, "founder_id": founder_id, "company_id": company_id}
    base["updated"] = ck.now
    d["calls"][call_id] = base
    if founder_id in d["founders"]:
        d["founders"][founder_id]["updated"] = ck.now
    return {"ok": True, "call": base, "changed": True, "founder_id": founder_id, "company_id": company_id}


def set_followup(d: dict[str, Any], ck: Clock, call_id: Any, done: bool = True) -> tuple[dict[str, Any] | None, bool]:
    """(the call or None, whether the old code saved ``d``). The call may carry a defaulted ``next_action`` that the
    old code added in memory only (no change -> no save), as its answer showed it."""
    c = d["calls"].get(call_id)
    if not c:
        return None, False
    na = c.setdefault("next_action", {"text": "", "owner": "Mohamed", "due": "", "done": False})
    saved = False
    if bool(na.get("done")) != bool(done):
        na["done"] = bool(done)
        na["done_on"] = ck.today if done else ""
        c["updated"] = ck.now
        saved = True
    return c, saved


# ------------------------------------------------------------------ views
def _sort_key(c: dict[str, Any]) -> tuple[str, str, str]:
    return (c.get("date") or "", c.get("time") or "", c.get("created") or "")


def due_state(call: dict[str, Any], today: date) -> str:
    na = call.get("next_action") or {}
    if not na.get("text") and not na.get("due"):
        return ""
    if na.get("done"):
        return "done"
    due = na.get("due") or ""
    if not due:
        return "open"
    t = today.isoformat()
    if due < t:
        return "overdue"
    if due == t:
        return "due"
    try:
        if (date.fromisoformat(due) - date.fromisoformat(t)).days <= UPCOMING_DAYS:
            return "upcoming"
    except ValueError:
        return "open"
    return "scheduled"


def summary(call: dict[str, Any], founder: dict[str, Any] | None = None, company: dict[str, Any] | None = None) -> str:
    """Concise, deterministic summary built ONLY from the stored fields. No inference."""
    t = TEMPLATES.get(call.get("call_type")) or TEMPLATES["first"]  # type: ignore[arg-type]
    ans = call.get("answers") or {}
    answered = [s["q"] for s in t["sections"] if not (ans.get(s["id"]) or {}).get("unknown")]
    unknown = [s["q"] for s in t["sections"] if (ans.get(s["id"]) or {}).get("unknown", True)]
    na = call.get("next_action") or {}
    asm = call.get("assessment") or {}
    parts = [
        "{} ({}) — {} on {} via {}.".format(
            (founder or {}).get("name", "founder"),
            (company or {}).get("name", "company"),
            CALL_TYPES.get(call.get("call_type"), "call"),  # type: ignore[arg-type]
            call.get("date", ""),
            call.get("channel", ""),
        )
    ]
    if call.get("objective"):
        parts.append("Objective: {}.".format(call["objective"].rstrip(".")))
    parts.append(
        "Answered {} of {} sections{}.".format(
            len(answered), len(t["sections"]), ("; UNKNOWN: " + "; ".join(unknown)) if unknown else ""
        )
    )
    parts.append("{} founder-reported claim(s) recorded ({}).".format(len(call.get("claims") or []), LABEL))
    if call.get("risks"):
        parts.append("Risks: {}.".format("; ".join(call["risks"])))
    if call.get("open_questions"):
        parts.append("Unanswered: {}.".format("; ".join(call["open_questions"])))
    if na.get("text"):
        parts.append(
            "Next action: {} ({}{}).".format(
                na["text"], na.get("owner") or "Mohamed", (", due " + na["due"]) if na.get("due") else ""
            )
        )
    if asm.get("recommendation"):
        parts.append(
            "Recommendation: {} (confidence {}).".format(asm["recommendation"], asm.get("confidence") or UNKNOWN)
        )
    return " ".join(parts)


def call_view(d: dict[str, Any], call: dict[str, Any], today: date) -> dict[str, Any]:
    f = d["founders"].get(resolve_founder(d, call.get("founder_id")) or "", {})
    c = d["companies"].get(resolve_company(d, call.get("company_id")) or "", {})
    return {
        **call,
        "founder_id": f.get("id", call.get("founder_id")),
        "company_id": c.get("id", call.get("company_id")),
        "founder_name": f.get("name", ""),
        "company_name": c.get("name", ""),
        "linked_person_id": f.get("linked_person_id", ""),
        "call_type_label": CALL_TYPES.get(call.get("call_type"), ""),  # type: ignore[arg-type]
        "due_state": due_state(call, today),
        "summary": summary(call, f, c),
        "summary_label": SUMMARY_LABEL,
    }


def history(d: dict[str, Any], today: date, founder_id: Any = None, company_id: Any = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for c in d["calls"].values():
        fid = resolve_founder(d, c.get("founder_id"))
        cid = resolve_company(d, c.get("company_id"))
        if founder_id and fid != resolve_founder(d, founder_id):
            continue
        if company_id and cid != resolve_company(d, company_id):
            continue
        rows.append(call_view(d, c, today))
    rows.sort(key=_sort_key)
    return rows


def due_followups(d: dict[str, Any], evaluations: Any, today: date) -> list[dict[str, Any]]:
    rows = [call_view(d, c, today) for c in conversations(d, evaluations).values()]
    rows = [r for r in rows if r["due_state"] in ("overdue", "due", "upcoming", "open")]
    order = {"overdue": 0, "due": 1, "upcoming": 2, "open": 3}
    rows.sort(key=lambda r: (order[r["due_state"]], (r.get("next_action") or {}).get("due") or "9999", _sort_key(r)))
    return rows


def workspace(
    d: dict[str, Any],
    evaluations: Any,
    today: date,
    people: list[dict[str, Any]] | None = None,
    pipeline: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Everything the workspace page needs. `people` / `pipeline` are the read-only picker listings."""
    calls = history(d, today)
    companies: list[dict[str, Any]] = []
    for cid, c in d["companies"].items():
        if c.get("merged_into"):
            continue
        founders: list[dict[str, Any]] = []
        for fid, f in d["founders"].items():
            if f.get("merged_into") or f.get("company_id") != cid:
                continue
            fc = [x for x in calls if x["founder_id"] == fid]
            founders.append({**f, "calls": fc, "last_call": fc[-1]["date"] if fc else ""})
        founders.sort(key=lambda f: f.get("name", "").lower())
        companies.append({**c, "founders": founders, "call_count": sum(len(f["calls"]) for f in founders)})
    companies.sort(key=lambda c: c.get("name", "").lower())
    orphan = [
        f
        for fid, f in d["founders"].items()
        if not f.get("merged_into") and not resolve_company(d, f.get("company_id"))
    ]
    return {
        "label": LABEL,
        "summary_label": SUMMARY_LABEL,
        "companies": companies,
        "orphan_founders": orphan,
        "calls": calls,
        "due": due_followups(d, evaluations, today),
        "templates": TEMPLATES,
        "call_types": CALL_TYPES,
        "channels": CHANNELS,
        "recommendations": RECOMMENDATIONS,
        "confidence": CONFIDENCE,
        "owners": OWNERS,
        "assessment_fields": ASSESSMENT_FIELDS,
        "people": people or [],
        "pipeline": pipeline or [],
        "today": today.isoformat(),
        "counts": {
            "companies": len(companies),
            "founders": sum(len(c["founders"]) for c in companies),
            "calls": len(calls),
            "due": sum(1 for r in due_followups(d, evaluations, today) if r["due_state"] in ("overdue", "due")),
        },
    }


# ------------------------------------------------------------------ exports (private research notes)
def _md_answer(a: str) -> str:
    return a if a else f"_{UNKNOWN} — not answered_"


def memo_markdown(d: dict[str, Any], call_id: Any, today: date) -> str | None:
    call = d["calls"].get(call_id)
    if not call:
        return None
    v = call_view(d, call, today)
    t = TEMPLATES.get(call.get("call_type")) or TEMPLATES["first"]
    ans = call.get("answers") or {}
    na = call.get("next_action") or {}
    asm = call.get("assessment") or {}
    L = [
        "# Founder call memo — {} · {}".format(v["founder_name"], v["company_name"]),
        "",
        f"_Private research note. Everything below that came from the founder is **{LABEL}**. It does not verify identity or founder status and changes no Gold/Strong bucket, ranking or evidence gate. Public verification stays in the sourced-evidence workflow._",
        "",
        "- **Date:** {} {}".format(call.get("date", ""), call.get("time", "")),
        "- **Type:** {}".format(v["call_type_label"]),
        "- **Channel:** {}".format(call.get("channel", "")),
        "- **Participants:** %s" % (", ".join(call.get("participants") or []) or UNKNOWN),
        "- **Discovery origin:** %s" % (call.get("discovery_origin") or UNKNOWN),
        "- **Introduction path:** %s" % (call.get("intro_path") or UNKNOWN),
        "- **Objective:** %s" % (call.get("objective") or UNKNOWN),
        "",
        "## Summary",
        "",
        f"_{SUMMARY_LABEL}_",
        "",
        v["summary"],
        "",
        f"## Questions and answers ({LABEL})",
        "",
    ]
    for i, s in enumerate(t["sections"], 1):
        r = ans.get(s["id"]) or {}
        L.append("### {}. {}".format(i, s["q"]))
        L.append("")
        L.append(_md_answer(r.get("a") if not r.get("unknown") else ""))  # type: ignore[arg-type]
        L.append("")
        for j, fq in enumerate(s.get("followups") or []):
            fa = (r.get("followups") or {}).get(str(j))
            if fa:
                L.append(f"- {fq} — {fa}")
        if any((r.get("followups") or {}).values()):
            L.append("")
    L += (
        [f"## Exact founder claims ({LABEL})", ""]
        + (['- "{}"'.format(c["text"]) for c in call.get("claims") or []] or ["_none recorded_"])
        + [""]
    )
    L += ["## Private observations (Mohamed)", "", call.get("observations") or "_none_", ""]
    L += ["## Risks", ""] + (["- " + r for r in call.get("risks") or []] or ["_none recorded_"]) + [""]
    L += (
        ["## Unanswered questions", ""]
        + (["- " + q for q in call.get("open_questions") or []] or ["_none recorded_"])
        + [""]
    )
    L += [
        "## Next action",
        "",
        (
            "{} — owner {}{}{}".format(
                na.get("text"),
                na.get("owner") or "Mohamed",
                (", due " + na["due"]) if na.get("due") else "",
                " (done)" if na.get("done") else "",
            )
        )
        if na.get("text")
        else "_none set_",
        "",
    ]
    L += ["## Post-call judgment (private)", ""]
    for k, label in ASSESSMENT_FIELDS:
        L.append(f"- **{label}:** {asm.get(k) or UNKNOWN}")
    L += [
        "- **Recommendation:** %s" % (asm.get("recommendation") or UNKNOWN),
        "- **Confidence:** %s" % (asm.get("confidence") or UNKNOWN),
        "- **Next action:** %s" % (asm.get("next_action") or na.get("text") or UNKNOWN),
        "",
    ]
    return "\n".join(L)


def briefing_markdown(d: dict[str, Any], founder_id: Any, today: date) -> str | None:
    """Omar / Project A briefing — produced ONLY when explicitly requested; never stored, never sent."""
    fid = resolve_founder(d, founder_id)
    if not fid:
        return None
    f = d["founders"][fid]
    c = d["companies"].get(resolve_company(d, f.get("company_id")) or "", {})
    calls = history(d, today, founder_id=fid)
    if not calls:
        return None
    prep = [x for x in calls if x["call_type"] == "intro_prep"]
    src = prep[-1] if prep else calls[-1]
    ans = src.get("answers") or {}
    asm = next(
        (x["assessment"] for x in reversed(calls) if (x.get("assessment") or {}).get("recommendation")),
        src.get("assessment") or {},
    )
    perm = (ans.get("permission") or {}).get("a") if src["call_type"] == "intro_prep" else ""
    L = [
        "# Project A briefing — {} · {}".format(f.get("name", ""), c.get("name", "")),
        "",
        "_Prepared on Mohamed's explicit request from private call notes ({} call(s), {} → {}). Everything the founder said is **{}**; nothing has been publicly verified through this document. Permission to introduce: {}._".format(
            len(calls), calls[0]["date"], calls[-1]["date"], LABEL, perm or (UNKNOWN + " — not asked")
        ),
        "",
    ]
    for s in TEMPLATES["intro_prep"]["sections"]:
        a = (ans.get(s["id"]) or {}).get("a") if src["call_type"] == "intro_prep" else ""
        L.append("- **{}:** {}".format(s["q"], a or UNKNOWN))
    L += ["", "## Mohamed's judgment (private)", ""]
    for k, label in ASSESSMENT_FIELDS:
        L.append(f"- **{label}:** {asm.get(k) or UNKNOWN}")
    L += (
        [
            "- **Recommendation:** %s" % (asm.get("recommendation") or UNKNOWN),
            "- **Confidence:** %s" % (asm.get("confidence") or UNKNOWN),
            "",
            "## Conversation history",
            "",
        ]
        + ["- {} — {} ({})".format(x["date"], x["call_type_label"], x["channel"]) for x in calls]
        + [""]
    )
    claims = [cl["text"] for x in calls for cl in (x.get("claims") or [])]
    L += (
        [f"## Founder claims to verify before any introduction ({LABEL})", ""]
        + (["- " + t for t in claims] or ["_none recorded_"])
        + [""]
    )
    return "\n".join(L)

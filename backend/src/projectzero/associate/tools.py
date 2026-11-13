# ruff: noqa: E501
# (the registry, its validation and its texts are the old module's lines, cut by script; see the header)
"""PZ Associate — the TOOL layer (review 033a): a closed, READ-ONLY set of capabilities over Project Zero's read views.

The old ``services/associate/tools.py`` at revision 6c739b9. Cut WHOLE by script (``python -m
projectzero.ops.parity_associate cuts``; ``tests/associate`` checks the exact lines and the syntax trees):
``MAX_LIMIT``, ``_t``, ``_list``, ``_ref``, ``_company_link``, ``_cand_link``, ``_gated``, ``_company_row``,
``catalogue``, ``ToolRejected`` and ``run`` (every argument check, verbatim). ``search_docs`` is the old function.

Hand-ported (decision c: no ``scout_intake``, ``scout_item`` or ``native_signals``, no ``_scout_link`` /
``_scout_row``):

* each registry function keeps its old name, signature, defaults and docstring (the model's catalogue is unchanged)
  and reads through the bound ``Reader``: one method per tool read, so the domain stays pure;
* ``ViewReader`` is the old tool bodies line for line over a ``Views`` (the old read handlers, one method each): the
  database implements ``Views`` with the NEW read models (``associate.reader``), the parity with the OLD answers;
* the two (c) additions: ``candidate_detail`` resolves an id it does not find (an absorbed record's, a Scout Intake or
  Native Scout item's) through ``Views.resolve`` to the surviving candidate, and ``find_records`` adds that candidate
  for a query that is such an id. ``find_records`` no longer lists Scout Intake items: the merged Deal Flow holds them.

Text from records (company descriptions, scout packets, research, evidence) is UNTRUSTED DATA: the engine hands it to
the model inside an <untrusted_records> envelope and the system prompt forbids following instructions found in it.
"""

from __future__ import annotations

import contextvars
import logging
import re
from collections.abc import Callable
from typing import Any, Protocol, TypedDict
from urllib.parse import quote

from projectzero.associate import knowledge

log = logging.getLogger(__name__)

# fmt: off
# ── cut from services/associate/tools.py: MAX_LIMIT, _t, _list, _ref, _company_link, _cand_link ──
MAX_LIMIT = 10


def _t(v: Any, n: int = 280) -> str:
    """A bounded single string (records are untrusted and can be long)."""
    s = re.sub(r"\s+", " ", str(v or "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _list(v: Any, n: int = 4, each: int = 160) -> list[str]:
    if isinstance(v, str):
        v = [v]
    return [_t(x, each) for x in (v or [])[:n] if str(x or "").strip()]


def _ref(kind: str, rid: str, label: str, link: str) -> dict[str, str]:
    return {"kind": kind, "id": rid, "label": _t(label, 80), "link": link}


def _company_link(slug: str) -> str:
    return f"/conviction?company={quote(slug)}"


def _cand_link(cid: str) -> str:
    return f"/deal-flow?candidate={quote(cid)}"
# ── end of cut ──
# fmt: on


class Views(Protocol):
    """The read handlers the old tools called, one method each (the old payloads, key for key)."""

    def pipeline(self) -> dict[str, Any]:
        """The old ``GET /api/pipeline`` (``{..., signals}``)."""
        ...

    def inbox(self) -> dict[str, Any]:
        """The old ``GET /api/inbox`` (``{..., candidates}``)."""
        ...

    def today(self) -> dict[str, Any]:
        """The old ``GET /api/today``."""
        ...

    def radar(self) -> dict[str, Any]:
        """The old Radar view (``high``, ``emerging``, ``wildcard``, ``research_queue``, ``gated``, ``watch``)."""
        ...

    def events(self) -> dict[str, Any]:
        """The old ``GET /api/events``."""
        ...

    def case(self, slug: str) -> dict[str, Any]:
        """The old ``case_prep.view(slug)``."""
        ...

    def analysis(self, id: str) -> dict[str, Any] | None:
        """The old ``GET /api/analysis?id=`` (``{state, ..., analysis}``)."""
        ...

    def resolve(self, id: str) -> str | None:
        """(c) An id no current candidate carries, through the candidate aliases: the surviving candidate's id."""
        ...


class Reader(Protocol):
    """One method per tool read (the old tool's answer, key for key)."""

    def today_missions(self) -> dict[str, Any]: ...
    def conviction_companies(self, segment: str) -> dict[str, Any]: ...
    def manager_decisions(self) -> dict[str, Any]: ...
    def company_detail(self, slug: str) -> dict[str, Any]: ...
    def deal_flow_candidates(self, view: str, limit: int) -> dict[str, Any]: ...
    def candidate_detail(self, id: str) -> dict[str, Any]: ...
    def radar(self) -> dict[str, Any]: ...
    def upcoming_events(self, limit: int) -> dict[str, Any]: ...
    def find_records(self, query: str) -> dict[str, Any]: ...


# fmt: off
# ── cut from services/associate/tools.py: _gated, _company_row ──
def _gated(e: dict[str, Any]) -> bool:
    return e.get("conflict") == "potential_conflict" or (e.get("op") or {}).get("status") == "CONFLICT GATED"


def _company_row(e: dict[str, Any]) -> dict[str, Any]:
    sc = e.get("sc") or {}
    op = e.get("op") or {}
    return {
        "ref": _ref("company", e.get("slug", ""), e.get("company", ""), _company_link(e.get("slug", ""))),
        "one_liner": _t(e.get("one_liner"), 160),
        "location": _t(e.get("location"), 60),
        "state": _t(op.get("status") or e.get("status"), 60),
        "next_action": _t(op.get("action") if op.get("source") != "score band" else e.get("next_action"), 160),
        "verified_score": sc.get("verified"),
        "provisional_score": sc.get("provisional"),
        "fully_verified": bool(sc.get("fully_verified")),
        "unverified": _list(sc.get("missing"), 6, 40),
        "manager_gated": _gated(e),
    }
# ── end of cut ──
# fmt: on


# fmt: off
class ViewReader:
    """The old tool bodies, line for line, over ``views`` (the old ``_pipeline()`` / ``_inbox()`` and the router calls
    become ``views`` methods). Each instance reads ONE consistent state: the database reader makes one per tool call,
    inside that call's snapshot."""

    def __init__(self, views: Views) -> None:
        self.views = views

    def _pipeline(self) -> list[dict[str, Any]]:
        return [e for e in (self.views.pipeline().get("signals") or []) if e.get("status") != "dropped"]

    def _inbox(self) -> list[dict[str, Any]]:
        return list(self.views.inbox().get("candidates") or [])

    def today_missions(self) -> dict[str, Any]:
        d = self.views.today()
        rows = [
            {
                "type": a.get("type"),
                "title": _t(a.get("title"), 160),
                "why": _t(a.get("why"), 240),
                "next_step": _t(a.get("next_step"), 160),
                "urgency": a.get("urgency"),
                "ref": _ref("mission", a.get("type", ""), a.get("subject") or a.get("title", ""), a.get("link") or "/today"),
            }
            for a in (d.get("actions") or [])[:MAX_LIMIT]
        ]
        t = d.get("triage") or {}
        return {"date": d.get("date"), "missions": rows, "more": d.get("more", 0), "machine_handled": t.get("total"), "link": "/today"}

    def conviction_companies(self, segment: str = "all") -> dict[str, Any]:
        rows = self._pipeline()
        seg = (segment or "all").lower()
        if seg == "gated":
            rows = [e for e in rows if _gated(e)]
        elif seg == "watch":
            rows = [e for e in rows if "watch" in str(e.get("status", "")).lower()]
        elif seg in ("investigate", "active"):
            rows = [e for e in rows if not _gated(e) and "watch" not in str(e.get("status", "")).lower()]
        out = [_company_row(e) for e in rows]
        out.sort(key=lambda r: -(r["verified_score"] or 0))
        return {"segment": seg, "count": len(out), "companies": out[:15], "link": "/conviction"}

    def manager_decisions(self) -> dict[str, Any]:
        rows = [e for e in self._pipeline() if _gated(e)]
        return {
            "count": len(rows),
            "companies": [{**_company_row(e), "possible_overlap_with": _t(e.get("twin"), 80)} for e in rows[:MAX_LIMIT]],
            "rule": "Conflict-gated companies are not forwarded until the Manager / Project A confirms. The Associate never contacts the Manager.",
            "link": "/conviction?seg=gated",
        }

    def company_detail(self, slug: str) -> dict[str, Any]:
        rows = {e.get("slug"): e for e in self._pipeline()}
        e = rows.get(slug)
        if e is None:
            return {"error": f"no Conviction company with slug {slug!r}", "hint": "use find_records to look it up by name"}
        out: dict[str, Any] = {
            **_company_row(e),
            "founders": [_t(f.get("name"), 60) for f in (e.get("founders") or [])[:6] if isinstance(f, dict)],
            "earliness": e.get("earliness"),
            "funding_status": _t(e.get("funding_status"), 160),
            "why_project_a": _t(e.get("why_project_a"), 280),
            "why_now": _t(e.get("why_now_text"), 280),
            "founder_signal": _t(e.get("founder_signal"), 240),
            "bull": _t(e.get("bull"), 240),
            "bear": _t(e.get("bear"), 240),
            "to_verify": _list(e.get("verify_list"), 6),
            "sources": _list(e.get("sources"), 6, 120),
            "discovered": {"source": _t(e.get("discovery_source"), 80), "date": e.get("discovery_date")},
            "manager": {"sent": e.get("sent_to_omar") or None, "feedback": _t(e.get("omar_feedback"), 200) or None},
        }
        try:
            v = self.views.case(slug)
            card = v.get("card") or {}
            fact: Callable[[dict[str, Any]], dict[str, Any]] = lambda f: {"label": _t(f.get("label"), 60), "text": _t(f.get("text"), 200), "state": f.get("state")}  # noqa: E731
            out["case"] = {
                "state": v.get("state"),
                "prepared_at": v.get("prepared_at"),
                "why_pz_cares": _list(card.get("why_pz_cares"), 4),
                "known": [fact(f) for f in (card.get("known") or [])[:6]],
                "unknown": [fact(f) for f in (card.get("unknown") or [])[:6]],
                "contradictions": [fact(f) for f in (card.get("contradictions") or [])[:4]],
                "blockers": _list(card.get("blockers"), 4),
                "next_action": {k: _t((card.get("next_action") or {}).get(k), 200) for k in ("label", "why", "link")} if card else None,
                "contact": {"state": (card.get("contact") or {}).get("state"), "label": _t((card.get("contact") or {}).get("label"), 80)} if card.get("contact") else None,
                "last_call_outcome": _t(((card.get("human") or {}).get("last_outcome")), 120) or None,
            }
        except Exception as ex:  # the case view is optional context; the record above stands on its own
            log.info("associate: case view unavailable for %s: %s", slug, ex)
            out["case"] = {"unavailable": True}
        return out

    def deal_flow_candidates(self, view: str = "attention", limit: int = 8) -> dict[str, Any]:
        limit = max(1, min(MAX_LIMIT, int(limit or 8)))
        cands = self._inbox()
        v = (view or "attention").lower()
        if v in ("attention", "to_decide", "new"):
            rows = [c for c in cands if c.get("decision") == "new" and not ((c.get("attention_v2") or {}).get("gated"))]
        elif v in ("researching", "research"):
            rows = [c for c in cands if c.get("decision") == "research"]
        elif v in ("watch", "kept", "rejected"):
            rows = [c for c in cands if c.get("decision") == v]
        else:
            return {"error": f"unknown view {view!r}", "views": ["attention", "researching", "watch", "kept", "rejected"]}
        rows.sort(key=lambda c: -(((c.get("attention_v2") or {}).get("final")) or 0))
        return {
            "view": v,
            "count": len(rows),
            "candidates": [
                {
                    "ref": _ref("candidate", c.get("id", ""), c.get("name", ""), _cand_link(c.get("id", ""))),
                    "description": _t(c.get("description"), 200),
                    "decision": c.get("decision"),
                    "source": _t(c.get("source"), 60),
                    "tier": c.get("discovery_tier"),
                    "attention": (c.get("attention_v2") or {}).get("final"),
                    "first_seen": c.get("first_seen") or c.get("detected_on"),
                    "location": _t(c.get("location") or c.get("country"), 60),
                    "analysis": c.get("analysis_state"),
                }
                for c in rows[:limit]
            ],
            "link": "/deal-flow",
        }

    def candidate_detail(self, id: str) -> dict[str, Any]:
        cands = self._inbox()
        c = next((x for x in cands if x.get("id") == id), None)
        if c is None:  # (c) an old id (an absorbed record, a Scout Intake / Native Scout item): the surviving candidate
            rid = self.views.resolve(id)
            c = next((x for x in cands if x.get("id") == rid), None) if rid else None
        if c is None:
            return {"error": f"no Deal Flow candidate with id {id!r}"}
        out = {
            "ref": _ref("candidate", c.get("id", ""), c.get("name", ""), _cand_link(c.get("id", ""))),
            "description": _t(c.get("description"), 400),
            "why_surfaced": _list(c.get("why"), 5),
            "decision": c.get("decision"),
            "source": _t(c.get("source"), 80),
            "source_url": c.get("source_url"),
            "source_date": c.get("source_date"),
            "also_seen": [_t(s.get("source"), 60) for s in (c.get("also_seen") or [])[:5] if isinstance(s, dict)],
            "tier": c.get("discovery_tier"),
            "attention": (c.get("attention_v2") or {}).get("final"),
            "location": _t(c.get("location") or c.get("country"), 60),
            "themes": _list(c.get("themes"), 4, 40),
            "first_seen": c.get("first_seen") or c.get("detected_on"),
            "notes": _t(c.get("notes"), 200) or None,
            "analysis_state": c.get("analysis_state"),
        }
        if c.get("analysis_state") == "ANALYZED":
            cid = str(c.get("id") or id)
            try:
                a = (self.views.analysis(cid) or {}).get("analysis") or {}
                out["analysis"] = {
                    "recommendation": _t(a.get("recommendation"), 60),
                    "thesis": _t(a.get("thesis"), 300),
                    "for": _list(a.get("for") or a.get("strengths"), 4),
                    "against": _list(a.get("against") or a.get("risks"), 4),
                    "note": "machine proposal — never a decision",
                }
            except Exception as ex:
                log.info("associate: analysis unavailable for %s: %s", cid, ex)
        return out

    def radar(self) -> dict[str, Any]:
        v = self.views.radar()
        names: Callable[[Any], list[Any]] = lambda xs: [_company_row(e)["ref"] for e in (xs or [])][:MAX_LIMIT]  # noqa: E731
        return {
            "high_confidence": names(v.get("high")),
            "emerging": names(v.get("emerging")),
            "wildcard": names(v.get("wildcard")),
            "research_queue": names(v.get("research_queue")),
            "gated": names(v.get("gated")),
            "rule": "Radar slots hold fully verified companies only (ranked by verified score); empty slots stay empty.",
            "link": "/radar",
        }

    def upcoming_events(self, limit: int = 5) -> dict[str, Any]:
        limit = max(1, min(MAX_LIMIT, int(limit or 5)))
        d = self.views.events()
        today = str(d.get("today") or "")
        evs = [e for e in (d.get("events") or []) if str(e.get("start") or "") >= today]
        evs.sort(key=lambda e: str(e.get("start") or "9999"))
        return {
            "events": [
                {
                    "ref": _ref("event", e.get("id", ""), e.get("name", ""), f"/events?event={quote(str(e.get('id', '')))}"),
                    "start": e.get("start"),
                    "city": _t(e.get("city"), 40),
                    "status": e.get("status"),
                    "score": (e.get("sc") or {}).get("total"),
                }
                for e in evs[:limit]
            ],
            "link": "/events",
        }

    def find_records(self, query: str) -> dict[str, Any]:
        q = (query or "").strip().lower()
        if len(q) < 2:
            return {"error": "query too short"}
        hits: list[dict[str, Any]] = []

        def match(name: Any) -> bool:
            n = str(name or "").lower()
            return bool(n) and (q in n or n in q)

        try:
            hits += [{**_company_row(e)["ref"], "where": "Conviction"} for e in self._pipeline() if match(e.get("company"))][:5]
        except Exception:
            log.info("associate: pipeline unavailable for find")
        try:
            cands = self._inbox()
            found = [
                {**_ref("candidate", c.get("id", ""), c.get("name", ""), _cand_link(c.get("id", ""))), "where": f"Deal Flow ({c.get('decision')})"}
                for c in cands
                if match(c.get("name"))
            ][:5]
            rid = self.views.resolve((query or "").strip())  # (c) the query is an old id: its surviving candidate
            c = next((x for x in cands if x.get("id") == rid), None) if rid else None
            if c is not None and not any(h["id"] == rid for h in found):
                found.append({**_ref("candidate", c.get("id", ""), c.get("name", ""), _cand_link(c.get("id", ""))), "where": f"Deal Flow ({c.get('decision')})"})
            hits += found
        except Exception:
            log.info("associate: inbox unavailable for find")
        return {"query": query, "count": len(hits), "matches": hits[:12]}


# fmt: on
# ---------------------------------------------------------------- the bound reader (one per question)
_READER: contextvars.ContextVar[Reader] = contextvars.ContextVar("associate_reader")


def _reader() -> Reader:
    return _READER.get()  # unbound: LookupError, which ``run`` reports as "unavailable"


def runner(reader: Reader) -> Callable[[str, Any], dict[str, Any]]:
    """The engine's ``run_tool``: the old ``run`` with every tool reading through ``reader``."""

    def run_tool(name: str, args: Any) -> dict[str, Any]:
        token = _READER.set(reader)
        try:
            return run(name, args)
        finally:
            _READER.reset(token)

    return run_tool


# ---------------------------------------------------------------- tools (old names, signatures and docstrings)
def search_docs(query: str) -> dict[str, Any]:
    """How Project Zero works: relevant sections of the operator guide, manual, methodology and product docs."""
    r = knowledge.search(query, k=4)
    return {**r, "pages": knowledge.PAGES}


def today_missions() -> dict[str, Any]:
    """Today's deterministic human actions (the same list as the Today page)."""
    return _reader().today_missions()


def conviction_companies(segment: str = "all") -> dict[str, Any]:
    """Companies in Conviction (the ones the Smooth Operator chose to follow), with state, next action and scores."""
    return _reader().conviction_companies(segment)


def manager_decisions() -> dict[str, Any]:
    """What waits on the Manager: conflict-gated companies (portfolio overlap) — the Manager answers, never the Associate."""
    return _reader().manager_decisions()


def company_detail(slug: str) -> dict[str, Any]:
    """One Conviction company: the record, its prepared case (known · unknown · contradictions · blockers · next action)."""
    return _reader().company_detail(slug)


def deal_flow_candidates(view: str = "attention", limit: int = 8) -> dict[str, Any]:
    """Deal Flow candidates: 'attention' (undecided, by attention), 'researching', 'watch', 'kept'."""
    return _reader().deal_flow_candidates(view, limit)


def candidate_detail(id: str) -> dict[str, Any]:
    """One Deal Flow candidate: description, why it surfaced, sources, decision and any machine analysis."""
    return _reader().candidate_detail(id)


def radar() -> dict[str, Any]:
    """Project A Radar: fully verified companies in the Top 10, the research queue, conflict-gated companies."""
    return _reader().radar()


def upcoming_events(limit: int = 5) -> dict[str, Any]:
    """Upcoming events with their evidence score (the Events page)."""
    return _reader().upcoming_events(limit)


def find_records(query: str) -> dict[str, Any]:
    """Find companies / candidates / scout items / native signals by name (case-insensitive)."""
    return _reader().find_records(query)


# ---------------------------------------------------------------- registry: the ONLY tools that exist (all read-only)
# fmt: off
ToolFn = Callable[..., dict[str, Any]]


class ToolSpec(TypedDict):
    fn: ToolFn
    args: dict[str, type]
    required: list[str]
    category: str


TOOLS: dict[str, ToolSpec] = {
    "search_docs": {"fn": search_docs, "args": {"query": str}, "required": ["query"], "category": "READ"},
    "today_missions": {"fn": today_missions, "args": {}, "required": [], "category": "READ"},
    "conviction_companies": {"fn": conviction_companies, "args": {"segment": str}, "required": [], "category": "READ"},
    "manager_decisions": {"fn": manager_decisions, "args": {}, "required": [], "category": "READ"},
    "company_detail": {"fn": company_detail, "args": {"slug": str}, "required": ["slug"], "category": "READ"},
    "deal_flow_candidates": {"fn": deal_flow_candidates, "args": {"view": str, "limit": int}, "required": [], "category": "READ"},
    "candidate_detail": {"fn": candidate_detail, "args": {"id": str}, "required": ["id"], "category": "READ"},
    "radar": {"fn": radar, "args": {}, "required": [], "category": "READ"},
    "upcoming_events": {"fn": upcoming_events, "args": {"limit": int}, "required": [], "category": "READ"},
    "find_records": {"fn": find_records, "args": {"query": str}, "required": ["query"], "category": "READ"},
}

# fmt: on
# fmt: off
# ── cut from services/associate/tools.py: catalogue, ToolRejected, run ──
def catalogue() -> list[dict[str, Any]]:
    """The tool list the model sees (name · purpose · arguments)."""
    return [
        {"name": n, "purpose": (t["fn"].__doc__ or "").strip(), "args": {k: v.__name__ for k, v in t["args"].items()}, "required": t["required"]}
        for n, t in TOOLS.items()
    ]


class ToolRejected(Exception):
    pass


def run(name: str, args: Any) -> dict[str, Any]:
    """Validate and run one tool. Unknown tools, extra / missing / mistyped arguments are rejected server-side."""
    spec = TOOLS.get(str(name))
    if spec is None:
        raise ToolRejected(f"tool {name!r} does not exist; the Associate has read-only tools only: {', '.join(TOOLS)}")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ToolRejected("tool arguments must be an object")
    extra = set(args) - set(spec["args"])
    if extra:
        raise ToolRejected(f"unknown argument(s) for {name}: {', '.join(sorted(extra))}")
    clean: dict[str, Any] = {}
    for k, typ in spec["args"].items():
        if k not in args or args[k] is None:
            if k in spec["required"]:
                raise ToolRejected(f"{name} needs {k!r}")
            continue
        v = args[k]
        try:
            clean[k] = int(v) if typ is int else _t(v, 200)
        except (TypeError, ValueError) as e:
            raise ToolRejected(f"{name}.{k} must be {typ.__name__}") from e
    try:
        return spec["fn"](**clean)
    except ToolRejected:
        raise
    except Exception as e:  # a data source failing is reported, never hidden
        log.warning("associate tool %s failed: %s", name, e)
        return {"error": f"{name} is unavailable right now ({type(e).__name__})", "unavailable": True}
# ── end of cut ──
# fmt: on

# ruff: noqa: E501
# (the question, challenge and summary texts are the old lines, verbatim)
"""The old ``domain/evaluator.py`` (rev 6c739b9), ported line for line over one SESSION dict (review 024).

Every function works on ``s`` = one session of the evaluations document ``{sessions: {<id>: session}}``, exactly as
the old code did. The mutating ones change ``s`` (and, for ``start``, ``d["sessions"]``) IN PLACE, as the old code
changed its freshly loaded copy; ``routes`` hands them a copy and decides what changed. Nothing here reads a file, a
clock or a random source:

* the old ``_now()`` / ``datetime.now()`` / ``date.today()`` / ``uuid.uuid4().hex`` are the ``Clock`` fields
  ``stamp()`` (the Berlin wall clock, ``%Y-%m-%d %H:%M``), ``now``, ``today`` and ``new_hex()``;
* the old ``_load_pipeline()`` signals are the ``conviction`` argument (the stored Conviction records, old
  ``real_data.json`` ``signals`` order), ``people.json`` is ``people`` (the records, old order) and
  ``founder_radar.load_companies()`` is ``radar_companies`` (the ``radar_companies.json`` body; ``None``: missing);
* ``taste.suggest_twins`` is ``dealflow.triage.portfolio_check.suggest_twins``, ``founder_radar.verified_facts`` is
  ``conviction.pipeline.verified_facts``, ``founder_radar.add_evidence`` / ``is_recent`` are ``evaluator.evidence``,
  ``imq.evaluate(e, contradictions=...)`` is ``conviction.imq.evaluate(e, people, None, contradictions)`` (no
  research, the people records: the old call's defaults, decision b);
* ``end`` writes the founder call through ``founder_calls.routes.save`` (the pure Founder Calls write) and returns the
  changed Conviction records instead of saving ``real_data.json``.

Dict insertion order is the old one throughout (keys are added where the old code added them).
"""

from __future__ import annotations

import copy
import hashlib
import re
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from projectzero.conviction import imq, taste
from projectzero.conviction.pipeline import verified_facts
from projectzero.conviction.records import records
from projectzero.dealflow.ranking.names import slug as radar_slug
from projectzero.dealflow.triage.portfolio_check import suggest_twins
from projectzero.evaluator.catalog import (
    _COUNT_NOUNS,
    _COUNT_RX,
    _FAM_WORDS,
    _MATERIAL,
    _NEG_RX,
    _NUM,
    _WORDNUM,
    CANONICAL_MAP,
    DECK_LABEL,
    FAM,
    FAMILIES,
    FOUNDER_LABEL,
    STATES,
    UNKNOWN,
)
from projectzero.evaluator.evidence import add_evidence, is_recent
from projectzero.founder_calls import routes as founder_calls_routes
from projectzero.network.view import berlin_now


# ------------------------------------------------------------------ the clock and ids (old _now / uuid4)
def random_hex() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True)
class Clock:
    now: datetime  # the Berlin wall clock (naive): the old datetime.now()
    today: date  # the Berlin day: the old date.today()
    new_hex: Callable[[], str] = random_hex  # the old uuid.uuid4().hex (32 hex digits)

    def stamp(self) -> str:
        """The old ``_now()``."""
        return self.now.strftime("%Y-%m-%d %H:%M")


def clock(now: datetime, today: date, new_hex: Callable[[], str] | None = None) -> Clock:
    return Clock(berlin_now(now).replace(tzinfo=None), today, new_hex or random_hex)


@dataclass(frozen=True)
class ConvictionChange:
    """One stored Conviction record a write changed: its position in the ``conviction`` list given, the radar slug it
    was matched by, and the WHOLE new record (the old code saved ``real_data.json`` with it)."""

    index: int
    slug: str
    record: dict[str, Any]


def _fold(s: Any) -> str:
    return re.sub(
        r"[^a-z0-9 ]", "", unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    ).strip()


def _cid(text: str) -> str:
    return "cl-" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def classify(text: Any) -> str:
    """Best-matching rubric family for a statement (keyword rules, deterministic)."""
    t = str(text or "").lower()
    best, score = "evidence_gaps", 0
    for fid, rx in _FAM_WORDS.items():
        n = len(re.findall(rx, t))
        if n > score:
            best, score = fid, n
    return best


# ------------------------------------------------------------------ context from existing Project Zero records
def _entry(conviction: Any, slug: Any) -> dict[str, Any] | None:
    for e in records(conviction):
        if radar_slug(e.get("company", "")) == slug:
            return e
    return None


def _indexed(conviction: Any) -> list[tuple[int, dict[str, Any]]]:
    """The old ``compat.records(dd["signals"], ...)`` with each record's position in the list given."""
    return [(i, e) for i, e in enumerate(conviction if isinstance(conviction, list) else []) if isinstance(e, dict)]


def context_for(subject: dict[str, Any], conviction: Any, radar_companies: Any) -> dict[str, Any]:
    """Existing Project Zero context (read-only): pipeline judgment, verified flags, conflict, twin, research facts, known adjacent companies."""
    ctx: dict[str, Any] = {
        "kind": subject.get("kind", "external"),
        "name": subject.get("name", ""),
        "founder": subject.get("founder", ""),
        "slug": "",
        "person_id": subject.get("person_id", ""),
    }
    e = _entry(conviction, subject.get("slug", "")) if subject.get("slug") else None
    if e is None and subject.get("name"):
        e = _entry(conviction, radar_slug(subject["name"]))
    if e is not None:
        sc = taste.score(e)
        ctx.update(
            {
                "slug": radar_slug(e["company"]),
                "name": e["company"],
                "one_liner": e.get("one_liner", ""),
                "scores": dict(e.get("scores") or {}),
                "verified": dict(e.get("verified") or {}),
                "provisional": sc["provisional"],
                "verified_score": sc["verified"],
                "conflict": e.get("conflict", "none"),
                "twin": e.get("twin", ""),
                "why_now_text": e.get("why_now_text", ""),
                "funding_status": e.get("funding_status", ""),
                "earliness": e.get("earliness", "unknown"),
                "fundraising_timing": e.get("fundraising_timing", "unknown"),
                "founders": imq.founder_names(e),
                "verify_list": list(e.get("verify_list") or []),
                "sources": list(e.get("sources") or []),
            }
        )
    adj = suggest_twins(" ".join([ctx.get("one_liner", ""), ctx.get("name", "")]))
    ctx["adjacent"] = [{"name": n, "what": w} for n, w, _ in adj]
    if ctx.get("twin") and not any(_fold(a["name"]) == _fold(ctx["twin"]) for a in ctx["adjacent"]):
        ctx["adjacent"].insert(0, {"name": ctx["twin"], "what": "recorded portfolio twin"})
    try:
        comps = ({"companies": {}} if radar_companies is None else radar_companies).get("companies", {})
        key = next((k for k, v in comps.items() if _fold(v.get("name")) == _fold(ctx["name"])), "")
        if key:
            vf = verified_facts(comps[key])
            ctx["research_facts"] = {
                k: {"claim": v.get("claim"), "url": v.get("source_url"), "date": v.get("activity_date", "")}
                for k, v in vf.items()
            }
    except Exception:
        ctx["research_facts"] = {}
    return ctx


# ------------------------------------------------------------------ sessions
def start(
    d: dict[str, Any], ck: Clock, subject: dict[str, Any], conviction: Any, radar_companies: Any
) -> dict[str, Any]:
    ctx = context_for(subject, conviction, radar_companies)
    sid = "ev-" + ck.now.strftime("%Y%m%d%H%M%S") + "-" + ck.new_hex()[:6]
    s: dict[str, Any] = {
        "id": sid,
        "created": ck.stamp(),
        "updated": ck.stamp(),
        "status": "open",
        "subject": {**subject, "name": ctx["name"] or subject.get("name", ""), "slug": ctx["slug"]},
        "context": ctx,
        "deck": {"text": "", "imported_at": "", "claims": []},
        "ledger": [],
        "questions": [],
        "queue": [],
        "covered": [],
        "provisional": {},
        "tasks": [],
        "memo_deltas": [],
        "ended": {},
    }
    # seed the ledger with what Project Zero already holds — labelled by its real evidence state, never upgraded
    for f in ctx.get("founders") or []:
        _add_claim(
            s,
            ck,
            "founder_team",
            f"Founder named on the pipeline record: {f}",
            "FOUNDER-REPORTED" if not ctx.get("verified", {}).get("founders") else "OPERATOR VERIFIED",
            "pipeline record",
        )
    for k, v in (ctx.get("research_facts") or {}).items():
        _add_claim(
            s,
            ck,
            {
                "funding": "fundraising",
                "recent_activity": "why_now",
                "founded": "founder_team",
                "status": "product",
                "stage": "fundraising",
            }.get(k, "evidence_gaps"),
            "{}: {}".format(k, v.get("claim")),
            "PUBLIC SOURCED FACT",
            v.get("url", ""),
        )
    d["sessions"][sid] = s
    _plan(s)
    return s


def _add_claim(
    s: dict[str, Any],
    ck: Clock,
    family: str,
    text: Any,
    state: str,
    source: Any = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return None
    c = {
        "id": _cid(family + "|" + text.lower()),
        "family": family,
        "text": text,
        "state": state,
        "source": source,
        "created": ck.stamp(),
        "resolved": False,
        "evidence": [],
        "related": [],
    }
    if extra:
        c.update(extra)
    if any(x["id"] == c["id"] for x in s["ledger"]):
        return next(x for x in s["ledger"] if x["id"] == c["id"])  # type: ignore[no-any-return]
    s["ledger"].append(c)
    return c


def import_deck(s: dict[str, Any], ck: Clock, text: Any) -> dict[str, Any]:
    """Extract material statements from a pasted pitch deck (operator-supplied text). Every statement starts as DECK CLAIM — UNVERIFIED."""
    text = str(text or "")
    s["deck"]["text"] = text
    s["deck"]["imported_at"] = ck.stamp()
    s["deck"]["claims"] = []
    parts = [p.strip(" -•*·\t") for p in re.split(r"[\n\r]+|(?<=[.!?])\s+(?=[A-Z€$])", text) if p.strip(" -•*·\t")]
    n = 0
    for p in parts:
        if len(p) < 12 or not _MATERIAL.search(p):
            continue
        fam = classify(p)
        c = _add_claim(s, ck, fam, p, "DECK CLAIM", "pitch deck", {"label": DECK_LABEL})
        if c and c["id"] not in s["deck"]["claims"]:
            s["deck"]["claims"].append(c["id"])
            n += 1
        if n >= 40:
            break
    _detect_contradictions(s, ck)
    _plan(s)
    return {"ok": True, "claims": n, "label": DECK_LABEL}


# ------------------------------------------------------------------ question engine
def _priority(s: dict[str, Any], fid: str) -> int:
    _lab, dim, base = FAM[fid][1], FAM[fid][2], FAM[fid][3]
    ctx = s.get("context") or {}
    sc = ctx.get("scores") or {}
    ver = ctx.get("verified") or {}
    p = base
    if dim == "founder" and not ver.get("founders"):
        p += 3
    if fid in ("traction", "retention") and not ver.get("traction"):
        p += 3
    if fid == "fundraising" and not ver.get("funding"):
        p += 3
    if dim and sc.get(dim) is not None and int(sc.get(dim) or 0) <= 8:
        p += 2  # weak / unknown rubric dimension
    if fid == "why_now" and ctx.get("why_now_text"):
        p -= 2
    if fid == "conflict" and ctx.get("conflict") in ("potential_conflict", "unclear"):
        p += 5
    if fid == "competition" and ctx.get("adjacent"):
        p += 2
    p += min(3, sum(1 for c in s["ledger"] if c["family"] == fid and c["state"] == "DECK CLAIM"))  # deck claims to test
    return p


def _plan(s: dict[str, Any]) -> list[dict[str, Any]]:
    """Uncovered families ordered by priority; pending follow-ups / challenges always come first."""
    covered = set(s.get("covered") or []) | set(s.get("skipped_families") or [])
    order = sorted([f[0] for f in FAMILIES if f[0] not in covered], key=lambda fid: -_priority(s, fid))
    s["plan"] = [{"family": fid, "label": FAM[fid][1], "priority": _priority(s, fid)} for fid in order]
    return s["plan"]  # type: ignore[no-any-return]


def skip(s: dict[str, Any], ck: Clock, qid: Any) -> dict[str, Any]:
    """Pre-GO: Skip really skips — the question is parked (asked again only as an end-of-call follow-up), the next family comes up."""
    q = next((x for x in s["questions"] if x["id"] == qid), None)
    if q is None:
        return {"ok": False, "error": "unknown question"}
    if q.get("answer") is not None:
        return {"ok": False, "error": "already answered"}
    q["skipped"] = ck.stamp()
    if q.get("kind") == "opening":
        s.setdefault("skipped_families", []).append(q["family"])
    _plan(s)
    s["updated"] = ck.stamp()
    nq = next_question(s, ck)
    return {"ok": True, "next": nq, "session": s}


def next_question(s: dict[str, Any], ck: Clock) -> dict[str, Any] | None:
    """The next best question: a queued follow-up / challenge first, else the highest-priority uncovered family."""
    if s.get("status") == "ended":
        return None
    open_q = next((q for q in s["questions"] if q.get("answer") is None and not q.get("skipped")), None)
    if open_q:
        return open_q  # type: ignore[no-any-return]
    if s["queue"]:
        q = s["queue"].pop(0)
    else:
        plan = _plan(s)
        if not plan:
            return None
        fid = plan[0]["family"]
        deck = [c for c in s["ledger"] if c["family"] == fid and c["state"] == "DECK CLAIM"]
        why = "highest-priority open family" + ("; the deck claims: “{}”".format(deck[0]["text"][:90]) if deck else "")
        q = {"family": fid, "text": FAM[fid][4], "kind": "opening", "reason": why, "verification_hint": FAM[fid][5]}
    q.update({"id": "q-" + ck.new_hex()[:8], "asked_at": ck.stamp(), "answer": None})
    s["questions"].append(q)
    s["updated"] = ck.stamp()
    return q  # type: ignore[no-any-return]


def _numbers(text: Any) -> list[float]:
    out = []
    for m in _NUM.finditer(str(text or "")):
        try:
            v = (
                float(m.group("n").replace(".", "").replace(",", "."))
                if m.group("n").count(",") == 1 and m.group("n").count(".") == 0
                else float(m.group("n").replace(",", ""))
            )
        except Exception:
            continue
        mag = (m.group("mag") or "").lower()
        v *= {"k": 1e3, "m": 1e6, "mio": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9, "b": 1e9}.get(mag, 1)
        if m.group("cur") or mag:
            out.append(v)
    return out


def _counts(text: Any) -> list[tuple[str, int]]:
    """[(canonical noun, value)] for every counted thing in a statement; a negated mention ("not 18 paying customers") is skipped."""
    out = []
    t = str(text or "")
    for m in _COUNT_RX.finditer(t):
        if _NEG_RX.search(t[max(0, m.start() - 24) : m.start()]):
            continue
        raw = m.group("n").lower()
        v = _WORDNUM.get(raw) or (int(raw) if raw.isdigit() else None)
        if v is None:
            continue
        noun = m.group("noun").lower()
        key = next((k for k, rx in _COUNT_NOUNS if re.fullmatch(rx, noun, re.I)), None)
        if key:
            out.append((key, v))
    return out


def _challenges(
    s: dict[str, Any], fid: str, text: Any, today: date
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Smart follow-ups / contradictions driven by the answer and by what Project Zero already knows."""
    t = str(text or "").lower()
    ctx = s.get("context") or {}
    fu = []
    contra = []
    if re.search(r"\b(arr|mrr|recurring revenue|revenue|umsatz)\b", t) and _NUM.search(t):
        fu.append(
            {
                "family": "traction",
                "kind": "challenge",
                "text": "Is that figure signed recurring revenue, annualized MRR, contracted-but-not-yet-live revenue, or does it include pilots / non-recurring services? Which customers make up the top 50 %?",
                "reason": "revenue figure needs a definition before it can be verified",
                "verification_hint": "contracts / invoices",
            }
        )
    if re.search(r"\b(no competition|no competitors?|nobody else|no one else|there is no alternative)\b", t):
        adj = ctx.get("adjacent") or []
        fu.append(
            {
                "family": "competition",
                "kind": "challenge",
                "text": "What do customers use today instead — spreadsheets, an incumbent, an internal tool? "
                + (
                    "Project Zero already knows adjacent companies: {}. How are you different?".format(
                        ", ".join(a["name"] for a in adj[:3])
                    )
                    if adj
                    else "Who is closest?"
                ),
                "reason": "'no competition' vs the status quo customers actually use",
                "verification_hint": "competitor list, portfolio twins",
            }
        )
        if adj:
            contra.append(
                {
                    "family": "competition",
                    "text": "Founder says 'no competition' but Project Zero knows adjacent companies: {}".format(
                        ", ".join(a["name"] for a in adj[:3])
                    ),
                    "against": [a["name"] for a in adj[:3]],
                }
            )
    if re.search(r"\b(customers? (love|adore)|love it|love the product|great feedback|very happy customers?)\b", t):
        fu.append(
            {
                "family": "retention",
                "kind": "challenge",
                "text": "What is the evidence — retention after 90 days, weekly usage, renewals, expansion? Which customer could we call?",
                "reason": "'customers love it' is not evidence",
                "verification_hint": "cohort / renewal data, reference call",
            }
        )
    m = re.search(
        r"\b(rais(e|ing)|next round)\b[^.]{0,60}\b(in|within)\s+(\d+|one|two|three|four|five|six|nine|twelve)\s+(months?|weeks?)",
        t,
    )
    if m:
        fresh = _fresh_round(ctx, today)
        if fresh:
            contra.append(
                {
                    "family": "fundraising",
                    "text": f"Founder says a round is {m.group(4)} months away, but existing evidence documents a fresh round: {fresh}",
                    "against": [fresh],
                }
            )
        fu.append(
            {
                "family": "fundraising",
                "kind": "challenge",
                "text": "What is the runway until then, what is already soft-committed, and who would lead?",
                "reason": "round timing drives Omar's timing",
                "verification_hint": "registry filing / term sheet",
            }
        )
    if re.search(r"\bpatent", t):
        fu.append(
            {
                "family": "moat",
                "kind": "challenge",
                "text": "Granted or filed? Which jurisdictions, and who owns it — the company or a university?",
                "reason": "patent claims are often filings, not grants",
                "verification_hint": "EPO / patent register",
            }
        )
    if re.search(r"\bpilots?\b", t) and not re.search(r"paid pilots?|paying pilots?", t):
        fu.append(
            {
                "family": "traction",
                "kind": "challenge",
                "text": "Are the pilots paid? Contract value, duration and the conversion terms to a full contract?",
                "reason": "unpaid pilots are not traction",
                "verification_hint": "pilot agreements",
            }
        )
    if re.search(r"\b(don'?t know|not sure|no idea|can'?t say|unknown|haven'?t measured)\b", t):
        fu.append(
            {
                "family": fid,
                "kind": "unknown",
                "text": "Noted as UNKNOWN. What would you need to measure or find out, and by when?",
                "reason": "an honest unknown stays UNKNOWN",
                "verification_hint": "—",
            }
        )
    return fu, contra


def _fresh_round(ctx: dict[str, Any], today: date) -> str:
    fs = str(ctx.get("funding_status") or "")
    rf = (ctx.get("research_facts") or {}).get("funding") or {}
    if rf.get("date") and is_recent(rf.get("date"), today, 180):
        return "{} ({})".format(rf.get("claim"), rf.get("date"))
    if (
        ctx.get("verified", {}).get("funding")
        and re.search(r"\b(raised|closed|round)\b", fs, re.I)
        and ctx.get("earliness") in ("pre_seed", "seed", "series_a_plus")
    ):
        return fs
    return ""


def _detect_contradictions(s: dict[str, Any], ck: Clock) -> None:
    """Deck vs founder vs public: conflicting numbers inside one family, deck 'no competition' vs known adjacent companies."""
    fams: dict[str, list[tuple[float, dict[str, Any]]]] = {}
    for c in s["ledger"]:
        if c["state"] in ("DECK CLAIM", "FOUNDER-REPORTED", "PUBLIC SOURCED FACT"):
            fk = (
                classify(c["text"])
                if re.search(
                    r"\b(arr|mrr|revenue|raised|raising|round|valuation|margin|churn|retention)\b", c["text"], re.I
                )
                else c["family"]
            )
            for v in _numbers(c["text"]):
                fams.setdefault(fk, []).append((v, c))
    for fid, vals in fams.items():
        if fid not in ("traction", "fundraising", "economics", "growth", "retention"):
            continue
        seen: dict[float, dict[str, Any]] = {}
        for v, c in vals:
            for v2, c2 in seen.items():
                if (
                    c2["id"] != c["id"]
                    and c2["state"] != c["state"]
                    and max(v, v2) > 0
                    and abs(v - v2) / max(v, v2) > 0.25
                ):
                    text = "{}: '{}' ({}) vs '{}' ({})".format(
                        FAM[fid][1],
                        c["text"][:70],
                        c["state"],
                        c2["text"][:70],
                        c2["state"],
                    )
                    cc = _add_claim(s, ck, fid, text, "CONTRADICTION", "evaluator", {"against": [c["id"], c2["id"]]})
                    if cc and cc["id"] not in c["related"]:
                        c["related"].append(cc["id"])
            seen[v] = c
    # counted things: deck vs founder (vs public) — "18 paying customers" (deck) vs "12 paying customers" (founder)
    counted: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for c in s["ledger"]:
        if c["state"] in ("DECK CLAIM", "FOUNDER-REPORTED", "PUBLIC SOURCED FACT"):
            for key, v in _counts(c["text"]):
                counted.setdefault(key, []).append((v, c))
    for key, cvals in counted.items():
        for i, (v, c) in enumerate(cvals):
            for v2, c2 in cvals[:i]:
                if c2["id"] != c["id"] and c2["state"] != c["state"] and v != v2:
                    dup = next(
                        (
                            x
                            for x in s["ledger"]
                            if x["state"] == "CONTRADICTION"
                            and x.get("kind") == "count"
                            and x.get("noun") == key
                            and set(x.get("values") or []) == {v, v2}
                        ),
                        None,
                    )
                    if dup:  # the same discrepancy restated → one contradiction, both claims linked
                        for x in (c, c2):
                            if x["id"] not in dup["against"]:
                                dup["against"].append(x["id"])
                            if dup["id"] not in x["related"]:
                                x["related"].append(dup["id"])
                        continue
                    a, b = ((c2, v2), (c, v)) if c2["state"] == "DECK CLAIM" else ((c, v), (c2, v2))

                    def who(x: dict[str, Any]) -> str:
                        return {
                            "DECK CLAIM": "deck",
                            "FOUNDER-REPORTED": "founder",
                            "PUBLIC SOURCED FACT": "public source",
                        }[x["state"]]

                    text = "{} — {}: {} says {}, {} says {} ('{}' vs '{}')".format(
                        FAM[c["family"]][1] if c["family"] in FAM else "Traction",
                        key,
                        who(a[0]),
                        a[1],
                        who(b[0]),
                        b[1],
                        a[0]["text"][:70],
                        b[0]["text"][:70],
                    )
                    cc = _add_claim(
                        s,
                        ck,
                        c["family"]
                        if c["family"] in ("traction", "retention", "growth", "founder_team", "moat", "market")
                        else "traction",
                        text,
                        "CONTRADICTION",
                        "evaluator",
                        {"against": [a[0]["id"], b[0]["id"]], "kind": "count", "noun": key, "values": sorted([v, v2])},
                    )
                    for x in (c, c2):
                        if cc and cc["id"] not in x["related"]:
                            x["related"].append(cc["id"])
    adj = (s.get("context") or {}).get("adjacent") or []
    for c in list(s["ledger"]):
        if (
            c["state"] == "DECK CLAIM"
            and re.search(r"no competition|no competitors?|nobody else", c["text"], re.I)
            and adj
        ):
            _add_claim(
                s,
                ck,
                "competition",
                "Deck says '{}' but Project Zero knows adjacent companies: {}".format(
                    c["text"][:60], ", ".join(a["name"] for a in adj[:3])
                ),
                "CONTRADICTION",
                "evaluator",
                {"against": [c["id"]]},
            )


def answer(s: dict[str, Any], ck: Clock, qid: Any, text: Any) -> dict[str, Any]:
    """Record the founder's answer as FOUNDER-REPORTED, queue adaptive follow-ups, detect contradictions. Never verifies anything."""
    q = next((x for x in s["questions"] if x["id"] == qid), None)
    if q is None:
        return {"ok": False, "error": "unknown question"}
    text = str(text or "").strip()
    q["answer"] = text
    q["answered_at"] = ck.stamp()
    unknown = (not text) or (
        len(text) < 80
        and bool(
            re.search(
                r"\b(unknown|don'?t know|do not know|not sure|no idea|n/?a|haven'?t measured|can'?t say)\b", text, re.I
            )
        )
    )
    fam = (
        classify(text)
        if re.search(r"\b(arr|mrr|revenue|raised|raising|round|runway|valuation)\b", text, re.I)
        else q["family"]
    )  # a revenue / round statement is ledgered under its own family
    c = _add_claim(
        s,
        ck,
        fam if fam in FAM else q["family"],
        text if text else "No answer given",
        "UNKNOWN" if unknown else "FOUNDER-REPORTED",
        "founder (live)",
        {"label": UNKNOWN if unknown else FOUNDER_LABEL, "question_id": qid, "asked_family": q["family"]},
    )
    if q["family"] not in s["covered"] and q.get("kind") == "opening":
        s["covered"].append(q["family"])
    fu, contra = _challenges(s, q["family"], text, ck.today)
    if q.get("kind") == "unknown":
        fu = [
            f for f in fu if f.get("kind") != "unknown"
        ]  # Pre-GO: an UNKNOWN answered with 'unknown' does not queue another UNKNOWN follow-up (was an endless loop)
    for f in fu:
        if not any(x["text"] == f["text"] for x in s["queue"] + s["questions"]):
            s["queue"].append(f)
    for k in contra:
        cc = _add_claim(
            s,
            ck,
            k["family"],
            k["text"],
            "CONTRADICTION",
            "evaluator",
            {"against": k.get("against", []), "claim_id": c["id"] if c else ""},
        )
        if c and cc and cc["id"] not in c["related"]:
            c["related"].append(cc["id"])
    _detect_contradictions(s, ck)
    _plan(s)
    s["updated"] = ck.stamp()
    nq = next_question(s, ck)
    return {"ok": True, "claim": c, "followups": len(fu), "contradictions": len(contra), "next": nq, "session": s}


def attach_evidence(
    s: dict[str, Any],
    ck: Clock,
    claim_id: Any,
    url: Any,
    label: Any,
    note: Any,
    kind: Any = "public",
    confirm: bool = False,
) -> dict[str, Any]:
    """Evidence for ONE claim: PUBLIC SOURCED FACT (public URL, existing evidence rules) or OPERATOR VERIFIED (explicit confirmation).
    Touches only that claim — never the pipeline verified flags, never other claims."""
    c = next((x for x in s["ledger"] if x["id"] == claim_id), None)
    if c is None:
        return {"ok": False, "error": "unknown claim"}
    if kind == "operator":
        if not confirm:
            return {"ok": False, "error": "explicit confirmation required"}
        c["state"] = "OPERATOR VERIFIED"
        c["evidence"].append({"kind": "operator", "note": note, "on": ck.stamp(), "by": "operator"})
    else:
        ev = add_evidence("operator", url, label or "public source", note or c["text"], now=ck.now, today=ck.today)
        if not ev["ok"]:
            return ev
        c["state"] = "PUBLIC SOURCED FACT"
        c["evidence"].append({"kind": "public", "url": url, "label": label, "note": note, "on": ck.stamp()})
    c["resolved"] = True
    c.pop("label", None)
    s["updated"] = ck.stamp()
    return {"ok": True, "claim": c}


def resolve_contradiction(s: dict[str, Any], ck: Clock, claim_id: Any, note: Any) -> dict[str, Any]:
    c = next((x for x in s["ledger"] if x["id"] == claim_id and x["state"] == "CONTRADICTION"), None)
    if c is None:
        return {"ok": False, "error": "unknown contradiction"}
    c["resolved"] = True
    c["resolution"] = {"note": str(note or ""), "on": ck.stamp(), "by": "operator"}
    s["updated"] = ck.stamp()
    return {"ok": True, "claim": c}


# ------------------------------------------------------------------ live panel + end of evaluation
def panel(s: dict[str, Any], conviction: Any, people: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """Right-hand panel: what the existing judgment model knows / still lacks, per family group — claims only, no score changes."""
    ctx = s.get("context") or {}
    L = s["ledger"]

    def fam_rows(fids: list[str]) -> dict[str, Any]:
        rows = [c for c in L if c["family"] in fids]
        return {
            "claims": len(rows),
            "states": {st: sum(1 for c in rows if c["state"] == st) for st in STATES},
            "covered": all(f in s["covered"] for f in fids) if fids else False,
            "latest": [c["text"][:100] for c in rows[-3:]],
        }

    groups = {
        "founder": ["founder_team"],
        "market": ["market", "customer_budget", "competition", "moat"],
        "why_now": ["why_now"],
        "product": ["product", "problem"],
        "traction": ["traction", "retention", "growth", "economics", "sales_cycle"],
        "timing": ["fundraising"],
        "conflict": ["conflict", "project_a_fit"],
    }
    gaps = [
        FAM[f[0]][1]
        for f in FAMILIES
        if f[0] not in s["covered"]
        and not any(c["family"] == f[0] and c["state"] in ("PUBLIC SOURCED FACT", "OPERATOR VERIFIED") for c in L)
    ]
    contras = [c for c in L if c["state"] == "CONTRADICTION" and not c.get("resolved")]
    movement = []
    for dim, lab in (
        ("founder", "Founder"),
        ("venture_scale", "Venture scale"),
        ("why_now", "Why now"),
        ("taste", "Taste"),
        ("insight", "Insight"),
    ):
        fids = [f[0] for f in FAMILIES if f[2] == dim]
        rows = [c for c in L if c["family"] in fids]
        ver = sum(1 for c in rows if c["state"] in ("PUBLIC SOURCED FACT", "OPERATOR VERIFIED"))
        rep = sum(1 for c in rows if c["state"] in ("FOUNDER-REPORTED", "DECK CLAIM"))
        con = sum(1 for c in rows if c["state"] == "CONTRADICTION" and not c.get("resolved"))
        movement.append(
            {
                "dimension": lab,
                "current": (ctx.get("scores") or {}).get(dim),
                "verified_flag": (ctx.get("verified") or {}).get(
                    {"founder": "founders", "insight": "traction", "why_now": "funding"}.get(dim, "")
                ),
                "provisional_direction": "↓ contradiction"
                if con
                else (
                    "→ founder-reported only (no score change)"
                    if rep and not ver
                    else ("↑ evidence attached — re-score manually" if ver else "→ no new input")
                ),
                "reported": rep,
                "verified": ver,
                "contradictions": con,
            }
        )
    readiness = None
    e = _entry(conviction, ctx.get("slug", "")) if ctx.get("slug") else None
    if e is not None:
        readiness = imq.evaluate(e, people, None, contras, today=today)
    return {
        "groups": {k: fam_rows(v) for k, v in groups.items()},
        "evidence_gaps": gaps,
        "contradictions": [{"id": c["id"], "text": c["text"]} for c in contras],
        "provisional_movement": movement,
        "imq": {"state": readiness["state"], "blockers": readiness["blockers"]}
        if readiness
        else {"state": "not linked to a Conviction company", "blockers": []},
        "unknowns": [c["text"][:100] for c in L if c["state"] == "UNKNOWN"],
        "next_plan": (s.get("plan") or [])[:5],
    }


def canonical_answers(ledger: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{section: {"a": mapped founder-reported text, "unknown": bool, "mapped_from": [claim ids]}} — text keeps the family label and the
    'founder-reported — unverified' provenance; a section without any founder-reported claim stays UNKNOWN."""
    out = {}
    for sec, fams in CANONICAL_MAP.items():
        rows = [c for c in ledger if c["state"] == "FOUNDER-REPORTED" and c["family"] in fams]
        rows = sorted(rows, key=lambda c: fams.index(c["family"]))
        if rows:
            out[sec] = {
                "a": " | ".join("{}: {}".format(FAM[c["family"]][1], c["text"]) for c in rows)
                + f" [{FOUNDER_LABEL} — mapped from the Active Evaluator]",
                "unknown": False,
                "mapped_from": [c["id"] for c in rows],
            }
        else:
            unk = [c for c in ledger if c["state"] == "UNKNOWN" and c["family"] in fams]
            out[sec] = {"a": "", "unknown": True, "mapped_from": [c["id"] for c in unk]}
    return out


@dataclass(frozen=True)
class Ended:
    """What ``end`` produced besides the session change: the old answer ``ended``, the Founder Calls write (``None``:
    no call was saved, as no founder answer was recorded, or the session had already ended) and the changed
    Conviction records (empty: none linked, or already ended)."""

    ended: dict[str, Any]
    founder_calls: founder_calls_routes.Outcome | None
    conviction: tuple[ConvictionChange, ...]


def end(
    s: dict[str, Any],
    ck: Clock,
    extra: dict[str, Any] | None,
    *,
    conviction: Any,
    people: list[dict[str, Any]],
    founder_calls: Any,
) -> Ended:
    """End evaluation: Founder Call record, structured founder-reported claims, UNKNOWNs, contradictions, verification tasks, provisional notes,
    follow-up questions, memo deltas, IMQ readiness. Verified score untouched; nothing sent to Omar."""
    if s.get("status") == "ended" and s.get("ended"):
        return Ended(dict(s["ended"], already=True), None, ())  # RC1.1: ending twice has no second side effect
    extra = extra or {}
    ctx = s.get("context") or {}
    L = s["ledger"]
    reported = [c for c in L if c["state"] == "FOUNDER-REPORTED"]
    deck = [c for c in L if c["state"] == "DECK CLAIM"]
    unknowns = [c for c in L if c["state"] == "UNKNOWN"]
    contras = [c for c in L if c["state"] == "CONTRADICTION" and not c.get("resolved")]
    tasks = []
    for c in reported + deck:
        if _MATERIAL.search(c["text"]) and c["family"] != "evidence_gaps":
            tasks.append(
                {
                    "id": "vt-" + c["id"][3:],
                    "claim_id": c["id"],
                    "family": c["family"],
                    "text": "Verify ({}): {}".format(FAM[c["family"]][1], c["text"][:140]),
                    "how": FAM[c["family"]][5],
                    "state": "open",
                    "created": ck.stamp(),
                }
            )
    for c in contras:
        tasks.append(
            {
                "id": "vt-" + c["id"][3:],
                "claim_id": c["id"],
                "family": c["family"],
                "text": "Resolve contradiction: {}".format(c["text"][:160]),
                "how": "public source or founder document",
                "state": "open",
                "created": ck.stamp(),
            }
        )
    pending = [
        q for q in s["questions"] if q.get("answer") is None
    ]  # unanswered live + skipped questions become follow-ups
    s["questions"] = [q for q in s["questions"] if q.get("answer") is not None]
    followups: list[str] = []
    for t in (
        [q["text"] for q in pending]
        + [q["text"] for q in s["queue"]]
        + [FAM[p["family"]][4] for p in (s.get("plan") or [])[:4] if p["family"] not in {q["family"] for q in pending}]
    ):
        if t not in followups:
            followups.append(t)  # Pre-GO AE-04: one follow-up per question text
    provisional = {}
    for dim, lab in (
        ("founder", "Founder"),
        ("venture_scale", "Venture scale"),
        ("why_now", "Why now"),
        ("taste", "Taste"),
        ("insight", "Insight"),
    ):
        fids = [f[0] for f in FAMILIES if f[2] == dim]
        notes = [
            "{}: {} [{}]".format(FAM[c["family"]][1], c["text"][:120], c["state"])
            for c in L
            if c["family"] in fids and c["state"] in ("FOUNDER-REPORTED", "CONTRADICTION", "UNKNOWN", "DECK CLAIM")
        ]
        if notes:
            provisional[lab] = notes[:6]
    memo = (
        ["Founder-reported (unverified): " + c["text"][:120] for c in reported[:6]]
        + ["UNKNOWN: " + c["text"][:100] for c in unknowns[:4]]
        + ["CONTRADICTION: " + c["text"][:120] for c in contras[:4]]
    )
    # Founder Call record through the existing workspace (claims stay 'Founder-reported — unverified')
    body = {
        "founder": ctx.get("founder")
        or (s["subject"].get("founder") or "")
        or (ctx.get("founders") or ["Founder (name UNKNOWN)"])[0],
        "company": ctx.get("name") or s["subject"].get("name", "") or "UNKNOWN company",
        "call_type": extra.get("call_type", "first"),
        "date": ck.today.isoformat(),
        "channel": extra.get("channel", "video"),
        "participants": "Mohamed, " + (ctx.get("founder") or s["subject"].get("founder") or "founder"),
        "objective": "Active Evaluator session {}".format(s["id"]),
        "claims": "\n".join(c["text"] for c in reported),
        "observations": "\n".join("CONTRADICTION: " + c["text"] for c in contras),
        "risks": "\n".join(c["text"] for c in L if c["family"] == "risks" and c["state"] == "FOUNDER-REPORTED"),
        "open_questions": "\n".join(followups[:8]),
        "answers": canonical_answers(L),
        "next_action": {
            "text": f"{len(tasks)} verification task(s) from the Active Evaluator",
            "owner": "Mohamed",
            "due": "",
        },
        "pipeline_slug": ctx.get("slug", ""),
        "person_id": ctx.get("person_id", ""),
    }
    answers_n = sum(1 for q in s["questions"] if q.get("answer") is not None)
    # a Founder Call record only when the founder answered something: a session used to prepare or inspect a case
    # (no answer recorded) is not a conversation and must never read as "you spoke to the founders"
    fc: founder_calls_routes.Outcome | None = None
    if answers_n:
        fc = founder_calls_routes.save(
            founder_calls, body, today=ck.today, now=ck.now, new_id=lambda prefix: prefix + ck.new_hex()[:12]
        )
        call: dict[str, Any] = fc.body
    else:
        call = {"error": "no founder answer recorded — no Founder Call logged"}
    e = _entry(conviction, ctx.get("slug", "")) if ctx.get("slug") else None
    readiness = None
    changes: list[ConvictionChange] = []
    if e is not None:
        for i, x0 in _indexed(conviction):  # the old code re-read real_data.json: x is a fresh copy
            if radar_slug(x0.get("company", "")) == ctx["slug"]:
                x = copy.deepcopy(x0)
                vl = x.setdefault("verify_list", [])
                for t in tasks:
                    if t["text"] not in vl:
                        vl.append(t["text"])
                x["evaluator_provisional"] = {
                    "session": s["id"],
                    "on": ck.stamp(),
                    "notes": provisional,
                    "memo_deltas": memo,
                    "note": "provisional — Verified score unchanged until evidence is verified",
                }
                readiness = imq.evaluate(x, people, None, contras, today=ck.today)
                x["evaluator_last"] = {"session": s["id"], "on": ck.stamp(), "imq_state": readiness["state"]}
                changes.append(ConvictionChange(i, ctx["slug"], x))
    s["tasks"] = tasks
    s["memo_deltas"] = memo
    s["provisional"] = provisional
    s["status"] = "ended"
    s["ended"] = {
        "on": ck.stamp(),
        "call_id": ((call or {}).get("call") or {}).get("id", "") if isinstance(call, dict) else "",
        "call_error": (call or {}).get("error", "") if isinstance(call, dict) else "",
        "founder_reported": len(reported),
        "deck_claims": len(deck),
        "unknowns": len(unknowns),
        "answers": answers_n,
        "ledger_items": len(L),
        "canonical_answered": sum(1 for v in canonical_answers(L).values() if not v["unknown"]),
        "canonical_sections": len(CANONICAL_MAP),
        "count_note": "answers = questions the founder answered; founder-reported claims = founder answers ledgered as claims (one per answer, UNKNOWN answers excluded) plus unverified founder names carried in from the Conviction record; deck claims = statements extracted from the pasted deck; ledger items = all of these plus UNKNOWNs, contradictions and evidence-backed claims",
        "contradictions": len(contras),
        "tasks": len(tasks),
        "followups": followups[:8],
        "imq": {"state": readiness["state"], "blockers": readiness["blockers"]}
        if readiness
        else {"state": "not linked to a Conviction company", "blockers": []},
        "verified_score_changed": False,
        "sent_to_omar": False,
    }
    s["updated"] = ck.stamp()
    return Ended(s["ended"], fc, tuple(changes))


def session_row(s: dict[str, Any]) -> dict[str, Any]:
    """One sessions-strip row; the same counts the ended summary uses (Pre-GO AE-03 / AE-05)."""
    L = s["ledger"]
    return {
        "id": s["id"],
        "created": s["created"],
        "status": s["status"],
        "subject": s["subject"],
        "claims": len(L),
        "ledger_items": len(L),
        "questions": len(s["questions"]),
        "answers": sum(1 for q in s["questions"] if q.get("answer") is not None),
        "founder_reported": sum(1 for c in L if c["state"] == "FOUNDER-REPORTED"),
        "deck_claims": sum(1 for c in L if c["state"] == "DECK CLAIM"),
        "unknowns": sum(1 for c in L if c["state"] == "UNKNOWN"),
        "contradictions": sum(1 for c in L if c["state"] == "CONTRADICTION" and not c.get("resolved")),
    }


def workspace(d: dict[str, Any]) -> dict[str, Any]:
    rows = sorted(d["sessions"].values(), key=lambda s: s["created"], reverse=True)
    return {
        "sessions": [session_row(s) for s in rows],
        "states": STATES,
        "families": [{"id": f[0], "label": f[1], "dimension": f[2]} for f in FAMILIES],
        "deck_label": DECK_LABEL,
        "founder_label": FOUNDER_LABEL,
    }

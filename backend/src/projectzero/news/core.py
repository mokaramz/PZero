# ruff: noqa: E501
# (the old expressions and message templates are kept verbatim, long lines included)
"""The News read model (review 028a): the old ``services/news.py`` at revision 6c739b9, ported line for line as pure
functions over ONE explicit ``NewsInputs``, with the Berlin clock as parameters (decision f: ``today`` is the
request's Berlin day, for the 7-day window, the concept-of-the-day ordinal and the week ending; ``now`` the request
instant, formatted as the old naive ``ledger.now_ts()`` Berlin wall time for a seeded case's ``ingested_at``).

Only mechanical changes: every store read is a field of the inputs (``inputs_model``); the old GET-time
``seed_cases()`` WRITE is applied IN MEMORY under the same guard to a copy of the stored document (decision a:
``seed_cases`` returns the document the old ``_save`` would have written, round-tripped through JSON exactly as the
old ``load()`` read it back; storing it is 028b's import); ``validation.entities(today)`` is the request's ONE entity
build passed in (decision b); the refresh job is idle (decision c: ``refresh_status`` answers the old idle ``_JOB``
keys with ``running: false``). Nothing here writes, fetches or calls a model (ingest, the run, the cards and the
writes are 028b-d's).
"""

from __future__ import annotations

import copy
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from projectzero.conviction.records import list_, records
from projectzero.dealflow.ranking.names import norm_company
from projectzero.news import sources as news_sources
from projectzero.news.catalog import (
    _AMOUNT,
    _DIGEST,
    _EVENT_VERBS,
    _NOISE,
    _ROUND,
    CONCEPTS,
    EARLY_DAYS,
    EUROPE,
    EVENT_TYPES,
    GEO_LABEL,
    GEO_WORDS,
    OUTCOME_KIND,
    PRIORITY_THEMES,
    SENSOR_FOR,
    STATE_LABEL,
    THEME_WORDS,
    TYPE_LABEL,
)
from projectzero.news.inputs_model import NewsInputs
from projectzero.validation.core import observations as observations  # the old ``news.observations()`` (027a)
from projectzero.validation.core import ts

DEFAULT_PZ_START = "2026-09-27"  # the old ``_pz_start`` default
# decision (c): the old ``refresh_status`` job keys, in their order; no refresh runs in 028a
JOB_KEYS = (
    "running",
    "run_id",
    "stage",
    "trigger",
    "started_at",
    "feeds_done",
    "feeds_total",
    "ingested",
    "new",
    "merged",
)


# ------------------------------------------------------------------------------------------- classification rules
def is_noise(headline: str) -> bool:
    return bool(_NOISE.search(headline) or _DIGEST.search(headline)) or is_roundup(headline)


def _concepts_for(e: dict[str, Any]) -> list[str]:
    t = (e.get("headline", "") + " " + e.get("summary", "")).lower()
    out = []
    rnd = (e.get("round") or "").lower()
    if e["event_type"] == "valuation":
        out += ["valuation", "unicorn"] + (["secondary"] if "secondary" in t else [])
    if e["event_type"] == "funding":
        out += [
            {"pre-seed": "pre_seed", "preseed": "pre_seed", "seed": "seed", "series a": "series_a"}.get(
                rnd, "series_b" if rnd.startswith("series") else "seed"
            )
        ]
        if re.search(r"\bled by\b", t):
            out.append("lead_investor")
    if "secondary" in t and "secondary" not in out:
        out.append("secondary")
    if e["event_type"] == "acquisition":
        out.append("acquisition")
    if e["event_type"] == "shutdown":
        out.append("shutdown")
    if e["event_type"] in ("customer", "partnership"):
        out.append("pilot_vs_contract")
    if e["event_type"] == "grant":
        out.append("grant")
    if e["event_type"] == "accelerator":
        out.append("accelerator")
    if re.search(r"spin-?off|spinout|university|research", t):
        out.append("spinout")
    if "robotics" in e.get("themes", []):
        out.append("physical_ai")
    if "defence" in e.get("themes", []):
        out.append("dual_use")
    if re.search(r"\bu\.?s\.? (market|expansion)|moves to (the )?us|expands? to the us", t):
        out.append("us_expansion")
    return list(dict.fromkeys(out))[:3]


# ------------------------------------------------------------------------------------------------ parsing helpers
def amount_m(text: str) -> float | None:
    """First money amount in millions (handles k / M / bn)."""
    m = _AMOUNT.search(text or "")
    if not m:
        return None
    num = (m.group(2) or m.group(4) or "").replace(",", ".")
    unit = (m.group(3) or m.group(5) or "").lower()
    try:
        v = float(num)
    except ValueError:
        return None
    if unit in ("bn", "billion", "b", "milliarde", "milliarden", "milliard", "milliards"):
        v *= 1000
    elif unit == "k":
        v /= 1000
    elif not unit and v > 1000:
        v /= 1_000_000
    return round(v, 3)


def is_roundup(headline: str) -> bool:
    """ "X raises $100M, SAP buys Y, and European startups …": several events in one headline is a digest, not an event."""
    return len(_EVENT_VERBS.findall(headline)) >= 2 and ("," in headline or ";" in headline)


def classify(headline: str, summary: str = "") -> dict[str, Any]:
    text = f"{headline} {summary}"
    etype = next((k for k, _lab, rx in EVENT_TYPES if rx.search(headline)), None) or next(
        (k for k, _lab, rx in EVENT_TYPES if rx.search(summary[:300])), "other"
    )
    rnd = (_ROUND.search(text) or [None])[0]
    amt = amount_m(headline) or amount_m(summary[:400])
    geo = [g for g, rx in GEO_WORDS.items() if re.search(rx, text, re.I)]
    themes = [t for t, rx in THEME_WORDS.items() if re.search(rx, text, re.I)]
    return {
        "event_type": etype,
        "round": rnd.lower() if rnd else "",
        "amount_m": amt,
        "geo": geo,
        "themes": themes,
        "noise": is_noise(headline),
    }


def materiality(e: dict[str, Any]) -> tuple[str, list[str]]:
    """Deterministic: (HIGH | MEDIUM | LOW | NOISE, reasons)."""
    if e.get("noise"):
        return "NOISE", ["opinion / listicle / event / newsletter format"]
    t, amt, rnd = e["event_type"], e.get("amount_m"), e.get("round") or ""
    if t == "fund":
        return "LOW", ["investor / fund news — VC market context, not a company event"]
    if t == "valuation" or (amt and amt >= 1000 and t in ("funding", "valuation")):
        return "HIGH", ["valuation milestone"]
    if t in ("acquisition", "shutdown"):
        return "HIGH", [TYPE_LABEL[t].lower()]
    if t == "funding":
        if (amt and amt >= 20) or re.match(r"series [b-f]", rnd):
            return "HIGH", [f"large round ({amt:g}M)" if amt else f"{rnd} round"]
        if (amt and amt >= 1) or rnd in ("seed", "pre-seed", "preseed", "series a"):
            return "MEDIUM", [f"{rnd or 'funding'} round" + (f" ({amt:g}M)" if amt else "")]
        return "LOW", ["small or unspecified financing"]
    if t in ("customer", "regulatory"):
        return "MEDIUM", [TYPE_LABEL[t].lower()]
    if t == "grant" and amt and amt >= 1:
        return "MEDIUM", ["significant grant"]
    if t in ("founder", "accelerator", "grant"):
        return "MEDIUM" if t == "founder" else "LOW", [TYPE_LABEL[t].lower()]
    return "LOW", ["routine company news"]


def _key(name: str) -> str:
    return norm_company(name or "") or ""


# ------------------------------------------------------------------------------------------------------ stores
def load(doc: Any) -> Any:
    """The old ``load()`` over the stored document: ``or {}`` already applied by the reader, then the two
    ``setdefault`` on a shallow COPY (a non-object raises ``AttributeError`` as it did)."""
    d = dict(doc) if isinstance(doc, dict) else doc
    d.setdefault("events", {})
    d.setdefault("seeded", [])
    return d


def _rows(raw: str) -> list[dict[str, Any]]:
    """The old ``_rows(name)`` over the log's text: every line that is a JSON object, in line order."""
    out = []
    for line in raw.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


def seed_cases(doc: Any, cases: Any, now: datetime) -> tuple[Any, int]:
    """The old ``seed_cases()`` IN MEMORY (decision a): ``(document, added)``. With ``added`` the document is what
    the old ``_save(d)`` wrote and the next ``load()`` read back (a JSON round trip of a COPY); without, the stored
    document unchanged (the old code saved nothing). The inputs are never modified."""
    d = copy.deepcopy(load(doc))
    added = 0
    for _name, raw in cases if cases is not None else ():
        case = json.loads(raw)
        if case["event_id"] in d["seeded"] or case["event_id"] in d["events"]:
            ev = d["events"].get(case["event_id"])
            mine = [s for s in (ev or {}).get("backcast") or [] if s.get("added_by")]
            fresh = (case.get("backcast") or []) + mine
            if (
                ev
                and ev.get("curated")
                and (ev.get("precursor_sources") != case.get("precursor_sources") or ev.get("backcast") != fresh)
            ):
                ev["precursor_sources"] = (
                    case.get("precursor_sources") or []
                )  # curated research updates; Mohamed's signals kept
                ev["backcast"] = fresh
                added += 1
            continue
        case.setdefault("ingested_at", ts(now))
        case.setdefault("card", None)
        case["entity_key"] = _key(case["company"])
        case["materiality"], case["materiality_why"] = materiality(case)
        d["events"][case["event_id"]] = case
        d["seeded"].append(case["event_id"])
        added += 1
    if added:
        return json.loads(json.dumps(d, ensure_ascii=False)), added  # the old ``_save`` then ``load``
    return doc, 0


def _seeded(inputs: NewsInputs, now: datetime) -> Any:
    """The old view's guard, then its ``load()``: the curated cases are seeded (in memory) only while fewer case ids
    are recorded as seeded than case files exist (``len(seeded) < len(files)``, the legacy count guard)."""
    doc = inputs.events
    if inputs.cases is not None and len(load(doc)["seeded"]) < len(inputs.cases):
        doc, _added = seed_cases(doc, inputs.cases, now)  # curated learning cases are visible before the first refresh
    return load(doc)


# ----------------------------------------------------------------------------------------------------- the run
def refresh_status(inputs: NewsInputs) -> dict[str, Any]:
    """The old ``refresh_status()`` with no job in this process (decision c): the old idle ``_JOB`` keys, ``running``
    false; ``last`` / ``last_ok`` from the runs archive (a line without ``status`` counts as ok)."""
    runs = _rows(inputs.runs_log)
    job: dict[str, Any] = dict.fromkeys(JOB_KEYS)
    job["running"] = False
    ok = [r for r in runs if r.get("status", "ok") in ("ok", "partial")]
    return {
        "job": job,
        "last": runs[-1] if runs else None,
        "last_ok": ok[-1] if ok else None,  # stale data is obvious when the last ATTEMPT failed
        "events_total": len(load(inputs.events)["events"]),
    }


# ------------------------------------------------------------------------------------------------- the PZ check
def _pz_start(scan_history: Any) -> str:
    scans = (scan_history or {}).get("scans") or []
    first = min((str(s.get("run_id") or "")[:10] for s in scans if s.get("run_id")), default="")
    return first or DEFAULT_PZ_START


def _relevant(e: dict[str, Any]) -> bool:
    geo_ok = bool(set(e.get("geo") or []) & EUROPE)
    theme_ok = bool(set(e.get("themes") or []) & PRIORITY_THEMES)
    return geo_ok and theme_ok


def check(e: dict[str, Any], ents: dict[str, dict[str, Any]], pz_start: str) -> dict[str, Any]:
    """Did Project Zero know this company before this news? Deterministic; UNKNOWN until evidence says more."""
    ent = ents.get(e["entity_key"]) if e["entity_key"] else None
    known = bool(ent and ent.get("first_seen") and "discovered" in ent.get("stages", []))
    out: dict[str, Any] = {"known": known, "pz_first_seen": ent.get("first_seen") if ent else None}
    if known:
        assert ent is not None
        lead = (date.fromisoformat(e["event_date"]) - date.fromisoformat(ent["first_seen"][:10])).days
        via_this = ent.get("first_tier") == "announcement" and abs(lead) <= EARLY_DAYS
        out.update(
            lead_days=lead,
            first_source=ent.get("source_id") or "",
            first_tier=ent.get("first_tier") or "",
            stages=ent.get("stages", []),
            machine=ent.get("machine"),
            mohamed=(ent.get("mohamed") or {}).get("verdict"),
            capital_stage=ent.get("capital_stage"),
            state="CAUGHT_EARLY" if lead >= EARLY_DAYS and not via_this else "KNOWN_LATE",
        )
        return out
    signals = [s for s in e.get("backcast") or [] if s.get("kind") == "known_early_signal" and s.get("date")]
    if e["event_type"] == "fund" or (not _relevant(e) and not signals):
        out["state"] = "NOT_RELEVANT"
        return out
    if signals:
        in_window = [s for s in signals if pz_start <= s["date"][:10] < e["event_date"]]
        out["state"] = "MISSED" if in_window else "HISTORICAL"
        out["miss_window_signals"] = in_window
        return out
    out["state"] = "UNKNOWN"
    out["possible_miss"] = bool(e["entity_key"]) and e["materiality"] in ("HIGH", "MEDIUM")
    return out


def backcast_summary(e: dict[str, Any], pz_start: str) -> dict[str, Any] | None:
    sig = sorted((s for s in e.get("backcast") or [] if s.get("date")), key=lambda s: s["date"])
    if not sig:
        return None
    known = [s for s in sig if s.get("kind") == "known_early_signal"]
    first = known[0] if known else None
    fam = first.get("family") if first else None
    return {
        "timeline": sig,
        "earliest_plausible_signal": first,
        "best_sensor": SENSOR_FOR.get(fam or "", "unknown — no early signal family identified yet"),
        "before_pz": bool(first and first["date"] < pz_start),
        "learning": e.get("learning")
        or (
            f"The earliest public signal was a {fam.replace('_', ' ')} signal ({first['date'][:7]}). Today this is covered by: "  # type: ignore[union-attr]
            f"{SENSOR_FOR.get(fam or '', '—')}."
            if first
            else "No early signal is documented yet."
        ),
    }


def _decisions(actions_log: str) -> dict[str, dict[str, Any]]:
    out = {}
    for r in _rows(actions_log):
        if r.get("kind") == "outcome_decision":
            out[r["event_id"]] = r
    return out


# ------------------------------------------------------------------------------------------------------- views
def _themes(events: list[Any], ents: dict[str, dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """WHAT SEEMS TO BE MOVING — only with ≥ 3 distinct companies in 30 days (2 articles are not a trend)."""
    since = (today - timedelta(days=30)).isoformat()
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for e in records(events):
        if (
            str(e.get("event_date") or "") < since
            or e.get("materiality") not in ("HIGH", "MEDIUM")
            or not e.get("entity_key")
        ):
            continue
        for th in list_(e.get("themes")):
            for g in list_(e.get("geo")) or ["EU"]:
                if g in EUROPE:
                    groups[(th, g)].append(e)
    out = []
    for (th, g), evs in groups.items():
        cos = {e["entity_key"] for e in evs}
        if len(cos) < 3:
            continue
        types = Counter(e["event_type"] for e in evs).most_common(2)
        related = sum(
            1
            for en in ents.values()
            if "discovered" in en.get("stages", []) and th in [x.lower() for x in en.get("themes") or []]
        )
        conf = "early signal" if len(cos) < 5 else "moderate" if len(cos) < 8 else "strong"
        out.append(
            {
                "theme": th,
                "geo": g,
                "companies": len(cos),
                "confidence": conf,
                "observation": f"{len(cos)} {th} companies in {GEO_LABEL.get(g, g)} with {', '.join(TYPE_LABEL[t].lower() for t, _ in types)} in the last 30 days",
                "why_it_matters": "Repeated activity can mean investor attention (and later competition for deals) is building in this area — "
                "useful context, never a reason to change sourcing on its own.",
                "stories": [
                    {"event_id": e["event_id"], "headline": e["headline"]}
                    for e in sorted(evs, key=lambda e: e["event_date"], reverse=True)[:5]
                ],
                "pz_related": related,
            }
        )
    out.sort(key=lambda x: -x["companies"])  # type: ignore[operator]
    return out[:8]


def _entities(inputs: NewsInputs) -> dict[str, dict[str, Any]]:
    if inputs.entities is None:
        raise ValueError("NewsInputs.entities: the request's Validation entities are required (inputs_from_docs)")
    return inputs.entities


def view(inputs: NewsInputs, today: date, now: datetime) -> dict[str, Any]:
    """The old ``GET /api/news`` payload, key for key and in the old order. ``today``: the Berlin day of ``now``.
    Reads only: the curated cases are seeded in memory (decision a)."""
    d = _seeded(inputs, now)
    ents = _entities(inputs)  # decision (b): the request's ONE Validation entity build
    pz_start = _pz_start(inputs.scan_history)
    decisions = _decisions(inputs.actions_log)
    audits = {r["event_id"]: r.get("audit_id") for r in _rows(inputs.actions_log) if r.get("kind") == "miss_audit"}
    snap = news_sources.cached(inputs.source_metrics)
    rows = []
    for e in d["events"].values():
        try:
            chk = check(e, ents, pz_start)
            bc = backcast_summary(e, pz_start)
            ent = ents.get(e["entity_key"]) if e["entity_key"] else None
            proposal = None
            if (
                chk["known"]
                and OUTCOME_KIND.get(e["event_type"])
                and e["materiality"] != "NOISE"
                and e["event_id"] not in decisions
            ):
                proposal = {
                    "kind": OUTCOME_KIND[e["event_type"]],
                    "effect": f"Project Zero first saw {e['company']} {chk.get('lead_days')} day(s) before this event"
                    if chk.get("lead_days") is not None
                    else "",
                }
            rows.append(
                {
                    **{
                        k: e.get(k)
                        for k in (
                            "event_id",
                            "company",
                            "headline",
                            "summary",
                            "event_type",
                            "round",
                            "amount_m",
                            "event_date",
                            "geo",
                            "themes",
                            "materiality",
                            "materiality_why",
                            "card",
                        )
                    },
                    "type_label": TYPE_LABEL.get(e["event_type"], e["event_type"]),
                    "sources": e["sources"],
                    "independent_sources": sum(1 for s in e["sources"] if s["independence"] != "syndicated"),
                    "check": chk,
                    "state": chk["state"],
                    "state_label": STATE_LABEL[chk["state"]],
                    "backcast": bc,
                    "concepts": [{"id": c, **CONCEPTS[c]} for c in _concepts_for(e)],
                    "my_company": bool(
                        ent
                        and ("conviction" in ent.get("stages", []) or ent.get("mohamed") or ent.get("inbox_decision"))
                    ),
                    "in_deal_flow": bool(chk["known"]),
                    "outcome_proposal": proposal,
                    "outcome_decision": (decisions.get(e["event_id"]) or {}).get("decision"),
                    "audit_id": audits.get(e["event_id"]),
                    "source_notes": [
                        n
                        for n in dict.fromkeys(news_sources.source_note(s["publisher"], snap) for s in e["sources"])
                        if n
                    ][:2],
                    "disagreements": [x for x in news_sources.disagreements([e]) if x["status"] != "AGREE"],
                }
            )
        except Exception:  # one unreadable story never hides the News page (the old ``compat._skip`` count: a log line)
            continue
    rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "NOISE": 3}
    rows.sort(key=lambda r: str(r.get("event_date") or ""), reverse=True)
    rows.sort(key=lambda r: (rank.get(r.get("materiality"), 9), r.get("state") == "NOT_RELEVANT"))  # type: ignore[arg-type]
    top = [r for r in rows if r["materiality"] in ("HIGH", "MEDIUM") and r["state"] != "NOT_RELEVANT"]
    events = list(d["events"].values())
    by_state = Counter(r["state"] for r in rows if r["materiality"] != "NOISE")
    leads = [r["check"]["lead_days"] for r in rows if r["state"] == "CAUGHT_EARLY"]
    concept_counts = Counter(c["id"] for r in top[:10] for c in r["concepts"])
    concept_of_day = (concept_counts.most_common(1) or [(sorted(CONCEPTS)[today.toordinal() % len(CONCEPTS)], 0)])[0][0]
    latest_learning = next((r["backcast"]["learning"] for r in rows if r["backcast"]), None)
    runs = _rows(inputs.runs_log)
    return {
        "date": today.isoformat(),
        "pz_start": pz_start,
        "today": [r for r in top if r["event_date"] >= (today - timedelta(days=7)).isoformat()][:5],
        "stories": [r for r in rows if r["materiality"] != "NOISE"][:60],
        "caught_early": [r for r in rows if r["state"] == "CAUGHT_EARLY"],
        "known_late": [r for r in rows if r["state"] == "KNOWN_LATE"][:20],
        "misses": [
            r for r in rows if r["state"] == "MISSED" or (r["state"] == "UNKNOWN" and r["check"].get("possible_miss"))
        ][:30],
        "historical": [r for r in rows if r["state"] == "HISTORICAL"],
        "my_companies": [r for r in rows if r["in_deal_flow"] and r["materiality"] != "NOISE"],
        "themes": _themes(events, ents, today),
        "counts": {
            "events": len(events),
            "noise_hidden": sum(1 for r in rows if r["materiality"] == "NOISE"),
            "low_hidden_from_top": sum(1 for r in rows if r["materiality"] == "LOW"),
            **dict(by_state),
        },
        "metrics": {"median_lead_days": statistics.median(leads) if leads else None, "caught_early": len(leads)},
        "concept_of_the_day": {"id": concept_of_day, **CONCEPTS[concept_of_day]},
        "notice_earlier": latest_learning,
        "last_run": runs[-1] if runs else None,
        "state_labels": dict(STATE_LABEL),
        "signal_families": sorted(SENSOR_FOR),
        "note": "News is context and a benchmark — not sourcing alpha. Learnings are proposals; nothing here changes scores, "
        "sources, themes, Radar or IMQ.",
    }


def weekly_review(inputs: NewsInputs, today: date, now: datetime) -> dict[str, Any]:
    """The old ``weekly_review(today, record=False)`` (``GET /api/news_weekly``): never recorded here (the old
    scheduler's ``record=True`` append is the background jobs port's)."""
    v = view(inputs, today, now)
    since = (today - timedelta(days=7)).isoformat()
    week = [r for r in v["stories"] if r["event_date"] >= since]
    top = [r for r in week if r["materiality"] in ("HIGH", "MEDIUM") and r["state"] != "NOT_RELEVANT"][:10]
    caught = [r for r in week if r["state"] == "CAUGHT_EARLY"]
    missed = [r for r in week if r["state"] == "MISSED"]
    sensors = Counter(
        (r["backcast"] or {}).get("best_sensor")
        for r in v["stories"]
        if r["backcast"] and r["state"] in ("MISSED", "HISTORICAL")
    )
    lesson = (
        f"Most documented early signals pointed to: {sensors.most_common(1)[0][0]}."
        if sensors
        else "Too few backcasts yet for a sourcing lesson — add a backcast to one important story this week."
    )
    concept = Counter(c["id"] for r in top for c in r["concepts"]).most_common(1)
    return {
        "week_ending": today.isoformat(),
        "top": [{"event_id": r["event_id"], "headline": r["headline"], "state": r["state_label"]} for r in top],
        "caught_early": [r["company"] for r in caught],
        "missed": [r["company"] for r in missed],
        "pattern": v["themes"][0]["observation"] if v["themes"] else "No pattern with enough evidence this week.",
        "sourcing_lesson": lesson,
        "vc_lesson": dict(CONCEPTS[concept[0][0]]) if concept else v["concept_of_the_day"],
    }


def learnings(inputs: NewsInputs, today: date, now: datetime) -> list[dict[str, Any]]:
    """Facts for the Scout 00 packet: caught early, misses, historical cases (with earliest signal + best sensor)."""
    v = view(inputs, today, now)
    out = []
    for r in v["caught_early"]:
        out.append(
            {
                "type": "SUCCESS",
                "company": r["company"],
                "fact": f"first seen {r['check']['pz_first_seen']} via "
                f"{r['check'].get('first_source') or '?'}, {r['check']['lead_days']} days before: {r['headline']}",
            }
        )
    for r in v["misses"]:
        if r["state"] == "MISSED":
            bc = r["backcast"] or {}
            out.append(
                {
                    "type": "MISS",
                    "company": r["company"],
                    "fact": f"{r['headline']} — earliest signal during PZ operation: "
                    f"{((bc.get('earliest_plausible_signal') or {}).get('text') or '?')}; sensor: {bc.get('best_sensor')}",
                }
            )
    for r in v["historical"]:
        bc = r["backcast"] or {}
        out.append(
            {
                "type": "HISTORICAL",
                "company": r["company"],
                "fact": f"{r['headline']} — earliest signal "
                f"{((bc.get('earliest_plausible_signal') or {}).get('date') or '?')[:7]} predates Project Zero; "
                f"today's sensor: {bc.get('best_sensor')}",
            }
        )
    return out

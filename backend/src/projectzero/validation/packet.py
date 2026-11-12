# ruff: noqa: E501, RUF001
# (the old packet text is kept verbatim: long lines and typographic apostrophes included)
"""The Scout 00 feedback packet (review 027a): the old ``services/validation.py::scout_packet`` and its helpers at
revision 6c739b9, ported line for line, READ ONLY (decision c): ``mark`` (the old POST that appended the Scout log)
is 027b's.

Decision (c): the packet's News and source-network learnings are deferred behind the News reason. The old packet
built them from ``news.learnings()`` (News), ``source_network.scout_lines()`` and ``news_sources.scout_lines()`` (the
NEWS LEARNING, SOURCE NETWORK and NEWS SOURCE LEARNING sections: each now one ``- not available: <reason>`` line,
their machine-readable lists empty) and, per card, ``_evidence_learning`` (whether an evidence domain is monitored by
PZ or a source-network candidate: now ``not available: <reason>``; a card without an evidence URL still says
``no evidence URL``). Everything else is the old text; ``Generated`` is the request instant as the old naive Berlin
``ledger.now_ts()``, so ``sha`` changes with it, as before.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

from projectzero.conviction.records import records
from projectzero.dealflow.triage.view import decisions as read_jsonl
from projectzero.validation.catalog import MIN_N
from projectzero.validation.core import (
    NEWS_REASON,
    _classify,
    _live,
    _progression,
    _sources,
    entities,
    source_alpha,
    ts,
)
from projectzero.validation.inputs_model import ValidationInputs

DEFERRED = f"not available: {NEWS_REASON}"  # decision (c)


def _lane_learning(ents: dict[str, dict[str, Any]]) -> list[str]:
    """Per Scout lane: only stated when the lane has >= MIN_N items with a known outcome."""
    lanes: dict[str, Counter[str]] = defaultdict(Counter)
    for e in ents.values():
        for s in e["scouts"]:
            for lane in s["scouts"]:
                lanes[lane][_classify(e)] += 1
    out = []
    for lane, c in sorted(lanes.items()):
        resolved = c["SUCCESS"] + c["PROGRESSING"] + c["DID NOT HOLD UP"]
        if resolved >= MIN_N:
            out.append(
                f"{lane}: {c['SUCCESS']} success · {c['PROGRESSING']} progressing · {c['DID NOT HOLD UP']} did not hold up "
                f"(of {resolved} with an outcome; {c['PENDING']} pending)"
            )
        else:
            out.append(f"{lane}: not enough evidence yet ({resolved} item(s) with an outcome, {sum(c.values())} total)")
    return out


def _source_learning(ents: dict[str, dict[str, Any]], inputs: ValidationInputs) -> dict[str, list[str]]:
    rows = [r for r in source_alpha(ents, inputs) if r["discoveries"] >= MIN_N]
    best = [
        f"{r['source']} — value/found {r['value_per_discovery']:.2f}, {r['discoveries']} found, "
        f"{r['pre_company']} pre-company, {r['mohamed_accepted']} accepted by Mohamed"
        for r in rows[:3]
    ]
    late = [
        f"{r['source']} — {r['at_announcement']}/{r['discoveries']} first seen only through their own funding news"
        for r in rows
        if r["at_announcement"] >= 0.8 * r["discoveries"]
    ]
    names = _sources(inputs.sources)
    tally: dict[str, Counter[str]] = defaultdict(Counter)
    for c in records(inputs.inbox, ("id",)):
        sid = c.get("quality_source_id") or c.get("source_id")
        if sid:
            tally[sid]["n"] += 1
            tally[sid]["noise"] += 1 if (c.get("noise") or c.get("decision") == "baseline") else 0
    noisy = [
        f"{names.get(k, k)} — {t['noise']}/{t['n']} noise or baseline"
        for k, t in tally.items()
        if t["n"] >= 10 and t["noise"] >= 0.6 * t["n"]
    ]
    return {"best": best, "late_only": late[:5], "noisy": noisy[:5]}


def _domain(url: str) -> str:
    h = (urlparse(str(url or "")).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _evidence_learning(domains: list[str]) -> str:
    """Factual: is the evidence publisher already a Project Zero source, a source under test, or not monitored?
    Decision (c): the monitoring check (the source network, the News feeds) arrives with News & Learning."""
    if not domains:
        return "no evidence URL"
    return DEFERRED


def scout_packet(inputs: ValidationInputs, cycle: str, today: date, now: datetime) -> dict[str, Any]:
    """Scout 00 feedback packet v1 — factual downstream outcomes only, beginner-readable + a JSON block for machines.
    Manual copy/paste into grok.com; nothing is sent. Machine opinions are labelled and never counted as validation.
    Read only: the old ``mark`` (the Scout log append) is 027b's."""
    ents = entities(inputs, today)
    names = _sources(inputs.sources)
    rows = [(e, s) for e in ents.values() for s in e["scouts"] if not cycle or s["cycle_id"] == cycle]
    audits = _live(read_jsonl(inputs.audits_log))
    fp = {a.get("entity_key"): a for a in audits if a.get("type") == "false_positive"}
    misses = [a for a in audits if a.get("type") == "miss"]

    def card(e: dict[str, Any], s: dict[str, Any]) -> dict[str, Any]:
        fb = s["feedback"] or {}
        lead = e.get("lead") or {}
        doms = list(dict.fromkeys(_domain(u) for u in s.get("evidence_urls") or [] if _domain(u)))[:4]
        return {
            "company": e["name"],
            "scout_cycle": s["cycle_id"],
            "scout_lane": ", ".join(s["scouts"]) or "—",
            "initial_signal": names.get(e["source_id"], e["source_id"]) or "Scout intake",
            "initial_recommendation": s["recommended_action"] or "—",
            "mohamed_decision": (e.get("mohamed") or {}).get("verdict") or fb.get("outcome") or s["status"] or "—",
            "pz_progression": _progression(e),
            "outcome_evidence": e["strength"],
            "what_proved_right": [
                o["label"] + (f" ({o['date']})" if o.get("date") else "") for o in e["outcomes"] if o.get("positive")
            ],
            "what_proved_wrong": [
                o["label"] for o in e["outcomes"] if o.get("negative") or o["kind"] in ("dropped", "omar_negative")
            ]
            + (fp[e["key"]].get("causes") or [] if e["key"] in fp else []),
            "machine_opinion_not_validation": e["machine"],
            "classification": _classify(e),
            "original_sources": doms,
            "lead_days": lead.get("days") if lead.get("kind") != "found_at_announcement" else 0,
            "lead_basis": lead.get("event") or "",
            "source_learning": _evidence_learning(doms),
        }

    cards = [card(e, s) for e, s in sorted(rows, key=lambda r: (r[1]["cycle_id"] or "", r[0]["name"]))]
    good = [c for c in cards if c["classification"] in ("SUCCESS", "PROGRESSING")]
    weak = [c for c in cards if c["classification"] == "DID NOT HOLD UP"]
    pending = [c for c in cards if c["classification"] == "PENDING"]
    src = _source_learning(ents, inputs)
    lanes = _lane_learning(ents)
    L = [
        "PROJECT ZERO → CHIEF SCOUT 00 · FEEDBACK PACKET v1",
        f"Generated {ts(now)} · cycle {cycle or 'all'} · facts only — no instructions, no machine opinions as evidence.",
        "Scale: SUCCESS = verified real-world outcome or Omar positive · PROGRESSING = Mohamed moved it forward "
        "(Conviction / verification / gate) · DID NOT HOLD UP = dropped, negative outcome or audited false positive · "
        "PENDING = too early or no outcome yet.",
        "",
        f"== SUCCESSFUL DISCOVERIES ({len(good)}) ==",
    ]
    for c in good:
        L += [
            f"- {c['company']} [{c['classification']}] · cycle {c['scout_cycle']} · lane {c['scout_lane']}",
            f"  initial signal: {c['initial_signal']} · your recommendation: {c['initial_recommendation']}",
            f"  Mohamed: {c['mohamed_decision']} · PZ progression: {c['pz_progression']}",
            f"  what proved right: {'; '.join(c['what_proved_right']) or 'progressed on Mohamed’s judgment; no external outcome yet'}",
            f"  original sources: {', '.join(c['original_sources']) or '—'} · lead time: "
            + (
                f"{c['lead_days']} days before {c['lead_basis']}"
                if c["lead_days"] is not None
                else "not measurable yet"
            ),
            f"  source learning: {c['source_learning']}",
        ]
    if not good:
        L.append("- none yet")
    L += ["", f"== WEAK DISCOVERIES ({len(weak)}) =="]
    for c in weak:
        L += [
            f"- {c['company']} · lane {c['scout_lane']} · why weak: {'; '.join(c['what_proved_wrong']) or 'did not hold up'}",
            f"  what was misleading: initial recommendation {c['initial_recommendation']} vs outcome {c['outcome_evidence']}",
        ]
    if not weak:
        L.append("- none recorded")
    L += ["", f"== MISSES ({len(misses)}) — strong companies Project Zero did not catch early =="]
    for a in misses[-10:]:
        L.append(
            f"- {a['company']} · type {a.get('miss_type') or '—'} · earliest discoverable signal: {a.get('earliest_signal') or '—'} "
            f"({a.get('earliest_signal_date') or 'date ?'}, {a.get('signal_source') or 'source ?'}) · preventable: {a.get('preventable')} "
            f"· should have been found by: {a.get('should_have_found') or '—'}"
        )
    if not misses:
        L.append("- none recorded")
    L += ["", "== SOURCE LEARNING ==", "Best-performing sources (value per discovery, ≥ 5 found):"]
    L += [f"- {x}" for x in src["best"]] or ["- not enough evidence yet"]
    L += ["Late-only sources (companies first seen only in their own funding news):"]
    L += [f"- {x}" for x in src["late_only"]] or ["- none"]
    L += ["Noisy sources (mostly noise / baseline):"]
    L += [f"- {x}" for x in src["noisy"]] or ["- none"]
    L += ["", "== QUERY / LANE LEARNING ==", *(f"- {x}" for x in lanes or ["no lanes yet"])]
    # decision (c): News (``news.learnings()``), the source network (``source_network.scout_lines()``) and the News
    # sources (``news_sources.scout_lines()``) arrive with News & Learning
    news_facts: list[dict[str, Any]] = []
    L += ["", "== NEWS LEARNING (benchmarks from public news: facts and proposals, not commands) =="]
    L += [f"- {DEFERRED}"]
    net_lines: list[str] = []
    L += ["", "== SOURCE NETWORK (new sources PZ is testing; evidence, not commands) =="]
    L += [f"- {DEFERRED}"]
    news_src_lines: list[str] = []
    L += ["", "== NEWS SOURCE LEARNING (which publications help sourcing; PZ keeps trust decisions) =="]
    L += [f"- {DEFERRED}"]
    L += [
        "",
        f"== STILL PENDING ({len(pending)}) ==",
        *(f"- {c['company']} · lane {c['scout_lane']} · Mohamed: {c['mohamed_decision']}" for c in pending[:20]),
    ]
    machine = {
        "packet": "pz-scout00-feedback-v1",
        "cycle": cycle or "all",
        "successful": good,
        "weak": weak,
        "pending": [c["company"] for c in pending],
        "misses": [
            {
                k: a.get(k)
                for k in (
                    "company",
                    "miss_type",
                    "earliest_signal",
                    "earliest_signal_date",
                    "signal_source",
                    "preventable",
                    "should_have_found",
                    "why_missed",
                )
            }
            for a in misses[-10:]
        ],
        "source_learning": src,
        "lane_learning": lanes,
        "news_learning": news_facts[:12],
        "source_network": net_lines[:10],
        "news_source_learning": news_src_lines[:10],
    }
    L += ["", "== MACHINE-READABLE (JSON) ==", json.dumps(machine, ensure_ascii=False, sort_keys=True)]
    text = "\n".join(L).rstrip() + "\n"
    sha = hashlib.sha256(text.encode()).hexdigest()[:16]
    return {
        "cycle": cycle or "all",
        "companies": len(rows),
        "text": text,
        "sha": sha,
        "counts": {"successful": len(good), "weak": len(weak), "misses": len(misses), "pending": len(pending)},
    }

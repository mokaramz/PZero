# ruff: noqa: E501
# (the old expressions and message templates are kept verbatim, long lines included)
"""The Validation read model (review 027a): the old ``services/validation.py`` at revision 6c739b9, ported line for
line as pure functions over ONE explicit ``ValidationInputs``, with the Berlin clock as parameters (decision g:
``today`` is the request's Berlin day, also for the old ``date.today()`` of ``_ai_cost``; ``now`` the request
instant, formatted as the old naive ``ledger.now_ts()`` Berlin wall time).

Only mechanical changes: every store read is a field of the inputs (``inputs_model``); the old ``_snapshot`` WRITE is
the in-memory ``snapshot_series`` (decision a: the old last-row rule, the row appended to the log text exactly as
``storage.append_line`` did, then the last 60); ``news.observations()`` is ported over the archived
``news/events.json`` (decision b); the News panel (old ``_news_metrics``) reads the News port (review 028a) over the
inputs' ``news_inputs`` completed with THIS view's entity build (the old ``news.view()`` rebuilt the entities: the
values are the same, decision b of 028a); the native-bridge panel answers ``{available: false, reason}`` (decision
d); ``compressor.metrics`` is ported pure in ``validation/routing.py``. Nothing here writes.

The pure parts the write side (027b) and News (028) reuse are importable: ``entities`` / ``build``, ``read_jsonl``,
``_live``, ``_date``, ``_valid``, ``_key``, ``miss_context`` (the old ``_miss_context`` over given entities),
``source_alpha``, ``_sources`` and ``ValidationError``.
"""

from __future__ import annotations

import copy
import json
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any

from projectzero.conviction import taste
from projectzero.conviction.radar import compose_radar
from projectzero.conviction.records import readable, records
from projectzero.dealflow.ranking.names import norm_company
from projectzero.dealflow.triage.view import decisions as read_jsonl
from projectzero.dealflow.triage.view import edge
from projectzero.network.view import berlin_now
from projectzero.validation import routing
from projectzero.validation.catalog import (
    BENCHMARK_KINDS,
    BENCHMARK_KINDS_ALL,
    EVIDENCE_CLASS,
    FP_CAUSES,
    KINDS,
    LEAD_KINDS,
    MIN_N,
    MISS_REASONS,
    NEGATIVE_KINDS,
    POSITIVE_KINDS,
    REAL_WORLD_STRONG,
    SMOOTH,
    STAGE_LABEL,
    STAGES,
    VALUE_WEIGHTS,
)
from projectzero.validation.inputs_model import ValidationInputs

TS_FORMAT = "%Y-%m-%dT%H:%M:%S"  # the old ``ledger.TS_FORMAT``
SNAPSHOT_WINDOW = 60  # the old ``_read_jsonl(SNAPSHOTS)[-60:]``
# decision (d): what is not ported answers with a visible reason
NATIVE_BRIDGE_REASON = "The native search bridge pilot is not part of the rewrite"


class ValidationError(ValueError):
    pass


def ts(now: datetime) -> str:
    """The old ``ledger.now_ts()``: the naive Berlin wall time of the request instant."""
    return berlin_now(now).strftime(TS_FORMAT)


def native_bridge_deferred() -> dict[str, Any]:
    """Decision (d): the native-bridge panel (old ``_native_bridge``)."""
    return {"available": False, "reason": NATIVE_BRIDGE_REASON}


# --------------------------------------------------------------------------------------------------------- ledgers
def _live(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows minus retracted / superseded ones. History stays in the file."""
    dead = {r.get("retracts") for r in rows if r.get("retracts")} | {
        r.get("supersedes") for r in rows if r.get("supersedes")
    }
    return [r for r in rows if not r.get("retracts") and r.get("id") not in dead]


def _date(s: Any) -> str:
    s = str(s or "").strip()[:10]
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        return ""


def _valid(d: str, today: date) -> str:
    """A derived date is usable only if it parses and is not in the future (bad source dates are never used)."""
    return d if d and d <= today.isoformat() else ""


def _key(name: Any) -> str:
    return norm_company(str(name or "")) or ""


def miss_context(ents: dict[str, dict[str, Any]], key: str, outcome_date: str = "") -> dict[str, Any]:
    """The old ``_miss_context`` over the given entities (the old one rebuilt them with ``entities()``): classify the
    miss from what Project Zero knew, and freeze that state on the audit (history is never rewritten)."""
    e = ents.get(key)
    if not e or "discovered" not in e["stages"]:
        return {"miss_type": "never_found", "pz_state_at_audit": None}
    verdict = (e.get("mohamed") or {}).get("verdict")
    late = e["lead"] and e["lead"]["kind"] == "found_at_announcement"
    if outcome_date and e["first_seen"] and e["first_seen"] >= outcome_date:
        late = True
    if late:
        t = "found_too_late"
    elif verdict == "WATCH" or e["inbox_decision"] == "watch":
        t = "watch_not_followed"
    elif e["machine"] == "REJECT" or verdict == "REJECT" or e["inbox_decision"] == "rejected":
        t = "found_early_but_rejected"
    else:
        t = "found_early_not_progressed"
    state = {
        "first_seen": e["first_seen"],
        "first_tier": e["first_tier"],
        "source_id": e["source_id"],
        "machine_proposal": e["machine"],
        "mohamed_verdict": verdict,
        "inbox_decision": e["inbox_decision"],
        "stages": e["stages"],
    }
    return {"miss_type": t, "pz_state_at_audit": state}


# --------------------------------------------------------------------------------------------------- entity model
def _days(a: str, b: str) -> int | None:
    try:
        return (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days
    except ValueError:
        return None


def _sources(sources: Any) -> dict[Any, Any]:
    """The old ``_sources()`` over the stored ``sources.json`` ``sources`` list."""
    return {s.get("id"): s.get("name") or s.get("id") for s in sources if isinstance(s, dict)}


def _with_defaults(d: Any, *defaults: tuple[str, Any]) -> dict[str, Any]:
    """The old ``load()`` then ``d.setdefault(k, v)``, on a shallow COPY (raises as it did for a non-object)."""
    if not isinstance(d, dict):
        raise TypeError(type(d).__name__)
    out = dict(d)
    for k, v in defaults:
        out.setdefault(k, v)
    return out


def observations(news_doc: Any) -> dict[str, dict[str, str]]:
    """The old ``news.observations()`` over the archived News document (decision b): for Validation, the earliest
    MATERIAL news publication per company (a deterministic external observation)."""
    out: dict[str, dict[str, str]] = {}
    for e in _with_defaults(news_doc, ("events", {}), ("seeded", []))["events"].values():
        if not e["entity_key"] or e["materiality"] in ("NOISE", "LOW") or e.get("curated"):
            continue
        cur = out.get(e["entity_key"])
        if not cur or e["event_date"] < cur["date"]:
            out[e["entity_key"]] = {
                "date": e["event_date"],
                "source": e["sources"][0]["publisher"],
                "url": e["sources"][0]["url"],
                "headline": e["headline"],
            }
    return out


def _pipeline_rows(signals: Any) -> list[dict[str, Any]]:
    """Conviction entries as copies, with the frozen deterministic score and Radar membership (read-only)."""
    sig = copy.deepcopy(records(signals, ("company",)))
    try:  # readable copies: one legacy value never empties the Radar membership of every company
        r = compose_radar([readable(e) for e in copy.deepcopy(sig)])  # the Radar Top 10 = high + emerging + wildcard
        radar_keys = {_key(e.get("company")) for k in ("high", "emerging", "wildcard") for e in r.get(k) or []}
    except Exception:
        radar_keys = set()
    out = []
    for e in sig:
        try:
            sc = taste.score(copy.deepcopy(e))
        except Exception:
            sc = taste.score(readable(e))
        out.append({**e, "_sc": sc, "_radar": _key(e.get("company")) in radar_keys})
    return out


def entities(inputs: ValidationInputs, today: date) -> dict[str, dict[str, Any]]:
    """One record per company (normalized name), joining every store. Read-only."""
    return build(inputs, today)[0]


def build(inputs: ValidationInputs, today: date) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Entities plus the data-quality issues found while joining (e.g. future dates that were ignored)."""
    props = inputs.proposals
    verdicts = {}
    for d in read_jsonl(inputs.decisions_log):
        if d.get("candidate_id"):
            verdicts[d["candidate_id"]] = d
    ents: dict[str, dict[str, Any]] = {}
    issues: list[str] = []

    def ent(name: str) -> dict[str, Any]:
        k = _key(name) or name.lower()
        return ents.setdefault(
            k,
            {
                "key": k,
                "name": name,
                "candidate_ids": [],
                "first_seen": "",
                "first_tier": "",
                "source_id": "",
                "source_ids": set(),
                "country": "",
                "machine": None,
                "capital_stage": None,
                "themes": [],
                "mohamed": None,
                "inbox_decision": None,
                "stages": set(),
                "outcomes": [],
                "observed_news": None,
                "scouts": [],
                "conviction_status": None,
                "founder_call": None,
            },
        )

    for c in records(inputs.inbox, ("id",)):
        if not c.get("id") or not c.get("name"):
            continue
        e = ent(c["name"])
        e["candidate_ids"].append(c["id"])
        raw_fs = _date(c.get("first_seen") or c.get("detected_on"))
        fs = _valid(raw_fs, today)
        if raw_fs and not fs:
            issues.append(f"{c.get('name')}: first-seen date {raw_fs} is in the future — ignored")
        if fs and (not e["first_seen"] or fs < e["first_seen"]):
            e["first_seen"], e["first_tier"] = fs, c.get("discovery_tier") or ""
            e["source_id"] = c.get("quality_source_id") or c.get("source_id") or ""
            e["country"] = c.get("country") or ""
        e["source_ids"].update(c.get("all_source_ids") or [c.get("source_id")])
        e["source_ids"].update(a.get("source_id") for a in c.get("also_seen") or [])  # merged provenance
        e["stages"].add("discovered")
        if c.get("decision") not in (None, "new", "baseline"):
            if c.get("noise") and c.get("decision") == "rejected":
                e["noise_filtered"] = True  # the scan's noise rule — a machine rule, never Mohamed's decision
            else:
                e["inbox_decision"] = c.get("decision")
        p = props.get(c["id"]) or {}
        if p.get("status") in ("proposed", "needs_human") and p.get("proposal"):
            e["machine"] = p["proposal"]
            e["capital_stage"] = p.get("capital_stage")
            e["themes"] = p.get("themes") or []
            if p["proposal"] in ("KEEP", "RESEARCH"):
                e["stages"].add("machine_keep_research")
        v = verdicts.get(c["id"])
        if v:
            e["mohamed"] = {
                "verdict": v.get("verdict"),
                "machine": v.get("machine"),
                "agreed": v.get("agreed"),
                "ts": v.get("ts"),
            }
        if (v and v.get("verdict") in ("KEEP", "RESEARCH")) or c.get("decision") in ("kept", "research"):
            e["stages"].add("mohamed_accepted")
        # deterministic external observation: found early (pre-company / grant), later seen in funding news
        if c.get("discovery_tier") in ("pre_company", "grant"):
            for a in c.get("also_seen") or []:
                if a.get("discovery_tier") == "announcement":
                    observed = _valid(_date(a.get("first_seen")), today)
                    published = _valid(_date(a.get("source_date")), today)
                    seen = min(x for x in (observed, published) if x) if (observed or published) else ""
                    if seen and (not e["observed_news"] or seen < e["observed_news"]["date"]):
                        e["observed_news"] = {
                            "date": seen,
                            "date_basis": "publication date"
                            if seen == published
                            else "date a scan observed it (upper bound)",
                            "source": a.get("source") or "",
                            "url": a.get("url") or "",
                        }

    for p in _pipeline_rows(inputs.signals):
        if not p.get("company"):
            continue
        e = ent(p["company"])
        status = p.get("status") or "new"
        e["conviction_status"] = status
        if not e["first_tier"]:
            e["first_tier"] = p.get("discovery_tier") or ""
        if not e["source_id"]:
            e["source_id"] = p.get("source_id") or ""
        pfs = _valid(_date(p.get("discovered_first_seen")), today)
        if pfs and (not e["first_seen"] or pfs < e["first_seen"]):
            e["first_seen"] = pfs
        if status != "dropped":
            e["stages"].update({"discovered", "conviction"})
            if (p["_sc"] or {}).get("fully_verified"):
                e["stages"].add("verified")
            if p["_radar"]:
                e["stages"].add("radar")
            if ((p.get("imq") or {}).get("state") or "").startswith("IMQ — QUALIFIED"):
                e["stages"].add("imq")
            if p.get("sent_to_omar"):
                e["stages"].add("omar")
        else:
            e["outcomes"].append(
                {"kind": "dropped", "class": 2, "positive": False, "date": "", "label": "Dropped from Conviction"}
            )
        if p.get("omar_outcome") in ("positive", "negative"):
            e["outcomes"].append(
                {
                    "kind": "omar_" + p["omar_outcome"],
                    "class": 2,
                    "positive": p["omar_outcome"] == "positive",
                    "date": _date(p.get("sent_to_omar")),
                    "label": f"Omar {p['omar_outcome']}",
                }
            )

    calls = inputs.founder_calls
    cos = calls.get("companies") or {}
    for call in (calls.get("calls") or {}).values():
        co = cos.get(call.get("company_id")) or {}
        if co.get("name"):
            e = ent(co["name"])
            rec = ((call.get("assessment") or {}).get("recommendation")) or ""
            e["founder_call"] = {"date": call.get("date"), "recommendation": rec}

    for it in inputs.scout_items or []:
        if it.get("entity_name"):
            e = ent(it["entity_name"])
            e["scouts"].append(
                {
                    "item_id": it.get("id"),
                    "cycle_id": it.get("cycle_id"),
                    "scouts": it.get("source_scouts") or [],
                    "recommended_action": it.get("recommended_action"),
                    "status": it.get("status"),
                    "feedback": it.get("feedback") or {},
                    "signal_date": _date(it.get("signal_date")),
                    "date_discovered": _date(it.get("date_discovered_effective") or it.get("date_discovered")),
                    "evidence_urls": list(it.get("evidence_urls") or [])[:8],
                }
            )
            sd = _valid(_date(it.get("date_discovered_effective") or it.get("date_discovered")), today)
            if sd and (not e["first_seen"] or sd < e["first_seen"]):
                e["first_seen"] = sd
            e["stages"].add("discovered")

    for o in _live(read_jsonl(inputs.outcomes_log)):
        if o.get("kind") not in KINDS:
            continue
        e = ents.get(o.get("entity_key") or "") or ent(o.get("company") or "?")
        cls = (
            1
            if (
                o["kind"] in REAL_WORLD_STRONG
                or o["kind"] in BENCHMARK_KINDS
                or o["kind"] in ("accelerator", "mainstream_press")
            )
            and o.get("evidence_url")
            else 2
        )
        e["outcomes"].append(
            {
                "id": o.get("id"),
                "kind": o["kind"],
                "class": cls,
                "positive": o["kind"] in POSITIVE_KINDS,
                "negative": o["kind"] in NEGATIVE_KINDS,
                "date": o.get("event_date") or "",
                "label": KINDS[o["kind"]],
                "url": o.get("evidence_url") or "",
                "benchmark_system": o.get("benchmark_system") or "",
            }
        )

    try:
        for k, ob in observations(inputs.news).items():
            e = ents.get(k)  # type: ignore[assignment]
            d = _valid(ob["date"], today)  # type: ignore[assignment]
            if not e or not e["first_seen"] or not d:
                continue  # News never creates an entity; it only dates a later public event for one PZ already knows
            if not e["observed_news"] or d < e["observed_news"]["date"]:
                e["observed_news"] = {
                    "date": d,
                    "date_basis": "news publication",
                    "source": ob["source"],
                    "url": ob["url"],
                }
    except Exception:  # News is optional: a broken news store never breaks Validation
        issues.append("news observations could not be read")
    for e in ents.values():
        e["source_ids"] = sorted(x for x in e["source_ids"] if x)
        e["stages"] = [s for s in STAGES if s in e["stages"]]
        e.update(_strength(e))
        e.update(_lead(e))
        age = _days(e["first_seen"], today.isoformat()) if e["first_seen"] else None
        e["age_days"] = age
        e["horizon"] = (
            "unknown"
            if age is None
            else "immediate"
            if age < 30
            else "30-90 days"
            if age < 90
            else "3-6 months"
            if age < 180
            else "6-18 months"
        )
    return ents, issues


def _strength(e: dict[str, Any]) -> dict[str, Any]:
    """Outcome strength from the strongest evidence class available. Machine judgments never count."""
    pos = [o for o in e["outcomes"] if o.get("positive")]
    neg = [
        o
        for o in e["outcomes"]
        if o.get("negative") or (o.get("positive") is False and o["kind"] in ("dropped", "omar_negative"))
    ]
    if any(o["class"] == 1 and o["kind"] in REAL_WORLD_STRONG for o in pos):
        level = "STRONG_VERIFIED"
    elif any(o["kind"] in ("omar_positive", "omar_interested", "project_a_invested") for o in pos):
        level = "STRONG_HUMAN"
    elif any(s in e["stages"] for s in ("radar", "imq", "verified")):
        level = "PROMISING_GATED"
    elif "conviction" in e["stages"] or (e.get("founder_call") or {}).get("recommendation") in (
        "Follow up",
        "Consider for Omar",
    ):
        level = "PROMISING_HUMAN"
    elif e.get("observed_news") or any(o["class"] == 1 for o in pos):
        level = "EXTERNAL_SIGNAL"
    elif neg:
        level = "NEGATIVE"
    else:
        level = "UNKNOWN"
    if neg and level != "NEGATIVE" and level not in ("STRONG_VERIFIED", "STRONG_HUMAN"):
        level = "NEGATIVE"
    return {"strength": level}


def _lead(e: dict[str, Any]) -> dict[str, Any]:
    """Signal lead time: PZ first sighting vs the earliest important later public event (positive = we were early)."""
    events = [
        (o["date"], o["label"], "recorded") for o in e["outcomes"] if o.get("kind") in LEAD_KINDS and o.get("date")
    ]
    if e.get("observed_news"):
        events.append(
            (
                e["observed_news"]["date"],
                "Funding news seen by a later scan (" + e["observed_news"]["source"] + ")",
                "observed",
            )
        )
    if not e["first_seen"]:
        return {"lead": None}
    if not events:
        if e["first_tier"] == "announcement":
            return {
                "lead": {
                    "days": 0,
                    "event": "found through the funding/news announcement itself",
                    "kind": "found_at_announcement",
                }
            }
        return {"lead": None}
    d, label, how = min(events)
    return {"lead": {"days": _days(e["first_seen"], d), "event": label, "event_date": d, "kind": how}}


# ------------------------------------------------------------------------------------------------------- metrics
def _rate(a: int, n: int) -> float | None:
    return round(a / n, 3) if n >= MIN_N else None


def _review_minutes(rows: list[dict[str, Any]]) -> float:
    """Estimated Mohamed review time from decision timestamps: gaps <= 15 min are one session, +2 min per session.
    The recorded ``ts`` are the old naive Berlin wall times (decision g), parsed as stored."""
    ts_ = sorted(r["ts"] for r in rows if r.get("ts"))
    if not ts_:
        return 0.0
    mins, start, prev = 0.0, None, None
    for t in ts_:
        try:
            cur = datetime.fromisoformat(str(t).replace(" ", "T"))
        except ValueError:
            continue
        if prev is None or (cur - prev).total_seconds() > 900:
            if start is not None and prev is not None:
                mins += (prev - start).total_seconds() / 60 + 2
            start = cur
        prev = cur
    if start is not None and prev is not None:
        mins += (prev - start).total_seconds() / 60 + 2
    return round(mins, 1)


def lifecycle_map(network_doc: Any) -> dict[str, str]:
    """The old ``source_network.lifecycle_map()`` over the archived source-network document: registry source id →
    lifecycle state (for Validation's source table)."""
    cs = list(_with_defaults(network_doc, ("candidates", {}))["candidates"].values())
    out = {c["registry_source_id"]: c["state"] for c in cs if c.get("registry_source_id")}
    out.update({"news:" + c["news_feed"]: c["state"] for c in cs if c.get("news_feed")})
    return out


def source_alpha(ents: dict[str, dict[str, Any]], inputs: ValidationInputs) -> list[dict[str, Any]]:
    names = _sources(inputs.sources)
    decisions_by_cand = defaultdict(list)
    for d in read_jsonl(inputs.decisions_log):
        decisions_by_cand[d.get("candidate_id")].append(d)
    rows: dict[str, dict[str, Any]] = {}
    for e in ents.values():
        if not e["source_ids"] and not e["source_id"]:
            continue
        for sid in e["source_ids"] or [e["source_id"]]:
            r = rows.setdefault(
                sid,
                {
                    "source_id": sid,
                    "source": names.get(sid, sid),
                    "discoveries": 0,
                    "unique": 0,
                    "pre_company": 0,
                    "pre_funding": 0,
                    "machine_keep_research": 0,
                    "mohamed_accepted": 0,
                    "conviction": 0,
                    "strong": 0,
                    "leads": [],
                    "review_min": 0.0,
                    "at_announcement": 0,
                },
            )
            r["discoveries"] += 1
            if len(e["source_ids"]) == 1:
                r["unique"] += 1
            first = sid == (e["source_id"] or sid)  # earliness is credited to the source that saw it first
            if first and e["first_tier"] == "pre_company":
                r["pre_company"] += 1
            if edge(e["capital_stage"]) == "PRE_FUNDING_EDGE":
                r["pre_funding"] += 1
            for s in ("machine_keep_research", "mohamed_accepted", "conviction"):
                if s in e["stages"]:
                    r[s] += 1
            if e["strength"] in ("STRONG_VERIFIED", "STRONG_HUMAN"):
                r["strong"] += 1
            if first and e["lead"] and e["lead"]["kind"] == "found_at_announcement":
                r["at_announcement"] += 1
            elif first and e["lead"] and e["lead"]["days"] is not None:
                r["leads"].append(e["lead"]["days"])
            r["review_min"] += _review_minutes(
                [d for cid in e["candidate_ids"] for d in decisions_by_cand.get(cid, [])]
            )
    out = []
    for r in rows.values():
        n = r["discoveries"]
        out.append(
            {
                **{k: v for k, v in r.items() if k != "leads"},
                "duplicate_rate": _rate(n - r["unique"], n),
                "pre_funding_share": _rate(r["pre_funding"], n),
                "keep_research_rate": _rate(r["machine_keep_research"], n),
                "median_lead_days": statistics.median(r["leads"]) if r["leads"] else None,
                "lead_n": len(r["leads"]),
                "review_min": round(r["review_min"], 1),
            }
        )
    try:
        life = lifecycle_map(inputs.network)
    except Exception:  # the source network is optional context, never a reason to fail Validation
        life = {}
    for r in out:
        r["value_per_discovery"] = value_per_discovery(r)
        r["lifecycle"] = life.get(r["source_id"], "ESTABLISHED")
    out.sort(key=lambda r: (-r["value_per_discovery"], r["source"]))
    return out


def value_per_discovery(r: dict[str, Any]) -> float:
    v = sum(w * float(r.get(k) or 0) for k, w in VALUE_WEIGHTS.items())
    return round(v / (float(r.get("discoveries") or 0) + SMOOTH), 3)


def conversion(ents: dict[str, dict[str, Any]], dim: str, sources: Any) -> list[dict[str, Any]]:
    names = _sources(sources)
    groups: dict[str, Counter[str]] = defaultdict(Counter)
    for e in ents.values():
        if dim == "source":
            keys = [names.get(e["source_id"], e["source_id"]) or "unknown"]
        elif dim == "tier":
            keys = [e["first_tier"] or "unknown"]
        elif dim == "capital_stage":
            keys = [e["capital_stage"] or "unknown"]
        elif dim == "pre_funding":
            keys = [edge(e["capital_stage"])]
        elif dim == "theme":
            keys = e["themes"] or ["none"]
        elif dim == "ecosystem":
            keys = [e["country"] or "unknown"]
        elif dim == "scout":
            keys = sorted({s for x in e["scouts"] for s in x["scouts"]}) or []
        else:
            raise ValidationError("unknown dimension")
        for k in keys:
            for s in e["stages"]:
                groups[k][s] += 1
    rows: list[dict[str, Any]] = [{"group": k, **{s: c.get(s, 0) for s in STAGES}} for k, c in groups.items()]
    rows.sort(key=lambda r: (-r["conviction"], -r["mohamed_accepted"], -r["machine_keep_research"], -r["discovered"]))
    return rows


def calibration(ents: dict[str, dict[str, Any]], decisions_log: str) -> dict[str, Any]:
    """Machine vs Mohamed on REAL operating decisions only (dev / holdout labels are never read)."""
    latest = {}
    for d in read_jsonl(decisions_log):
        if d.get("candidate_id"):
            latest[d["candidate_id"]] = d
    by_cand = {cid: e for e in ents.values() for cid in e["candidate_ids"]}
    n = len(latest)
    agreed = sum(1 for d in latest.values() if d.get("agreed"))
    matrix: dict[str, Counter[str]] = defaultdict(Counter)
    by_tier: dict[str, Counter[str]] = defaultdict(Counter)
    who_right: Counter[str] = Counter()
    disagreements = []
    for cid, d in latest.items():
        m, v = str(d.get("machine")), str(d.get("verdict"))
        matrix[m][v] += 1
        e = by_cand.get(cid) or {}
        tier = e.get("first_tier") or "unknown"
        by_tier[tier]["n"] += 1
        by_tier[tier]["agreed"] += 1 if d.get("agreed") else 0
        if not d.get("agreed"):
            strong = e.get("strength") in ("STRONG_VERIFIED", "STRONG_HUMAN", "PROMISING_GATED")
            negative = e.get("strength") == "NEGATIVE"
            pos_v = v in ("KEEP", "RESEARCH")
            pos_m = m in ("KEEP", "RESEARCH")
            if not (strong or negative):
                verdict = "pending"
            elif (strong and pos_v) or (negative and not pos_v):
                verdict = "mohamed"
            elif (strong and pos_m) or (negative and not pos_m):
                verdict = "machine"
            else:
                verdict = "neither"
            who_right[verdict] += 1
            disagreements.append(
                {
                    "name": d.get("name"),
                    "machine": m,
                    "mohamed": v,
                    "outcome": e.get("strength", "UNKNOWN"),
                    "right": verdict,
                }
            )
    false_rejects = sum(c for v, c in matrix.get("REJECT", {}).items() if v in ("KEEP", "RESEARCH"))
    false_keeps = sum(c for v, c in matrix.get("KEEP", {}).items() if v == "REJECT")
    return {
        "decisions": n,
        "agreement": _rate(agreed, n),
        "agreed": agreed,
        "machine_rejects_overturned": false_rejects,
        "machine_keeps_rejected": false_keeps,
        "matrix": {k: dict(v) for k, v in matrix.items()},
        "by_tier": {k: {"n": c["n"], "agreement": _rate(c["agreed"], c["n"])} for k, c in by_tier.items()},
        "who_was_right": dict(who_right),
        "disagreements": disagreements[-20:],
        "review_minutes_est": _review_minutes(list(latest.values())),
        "note": "Real operating decisions only — the development and holdout labels are excluded on purpose.",
    }


def patterns(ents: dict[str, dict[str, Any]]) -> list[str]:
    """Descriptive judgment patterns. Only stated when both groups have >= MIN_N resolved outcomes."""
    groups: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for e in ents.values():
        if not e.get("mohamed"):
            continue
        g = (e["mohamed"]["verdict"], e["first_tier"] or "unknown")
        resolved = e["strength"] in ("STRONG_VERIFIED", "STRONG_HUMAN", "PROMISING_GATED", "NEGATIVE")
        groups[g]["n"] += 1
        if resolved:
            groups[g]["resolved"] += 1
            groups[g]["good"] += 1 if e["strength"] != "NEGATIVE" else 0
    out = []
    for (verdict, tier), c in sorted(groups.items()):
        if c["resolved"] >= MIN_N:
            out.append(
                f"Your {verdict} calls on {tier.replace('_', '-')} companies: {c['good']}/{c['resolved']} resolved cases turned out promising or strong ({c['n']} decisions in total)."
            )
    return out


def _headline(ents: dict[str, dict[str, Any]], today: date, audits_log: str) -> dict[str, Any]:
    month = today.isoformat()[:7]
    this_month = [e for e in ents.values() if e["first_seen"][:7] == month]
    pf = [e for e in this_month if edge(e["capital_stage"]) == "PRE_FUNDING_EDGE"]
    leads = [
        e["lead"]["days"]
        for e in ents.values()
        if e["lead"] and e["lead"]["days"] is not None and e["lead"]["kind"] != "found_at_announcement"
    ]
    at_ann = sum(1 for e in ents.values() if e["lead"] and e["lead"]["kind"] == "found_at_announcement")
    strong = [e for e in ents.values() if e["strength"] in ("STRONG_VERIFIED", "STRONG_HUMAN")]
    found = [e for e in strong if "discovered" in e["stages"]]
    strong_early = [e for e in found if e["lead"] and (e["lead"]["days"] or 0) > 0]
    strong_late = [e for e in found if e["lead"] and (e["lead"]["days"] or 0) <= 0]
    fn = [
        e
        for e in found
        if e["machine"] == "REJECT"
        or (e.get("mohamed") or {}).get("verdict") in ("REJECT", "WATCH")
        or e["inbox_decision"] == "rejected"
    ]
    strong_keys = {e["key"] for e in strong}
    misses = [a for a in _live(read_jsonl(audits_log)) if a.get("type") == "miss"]
    never_seen = {e["key"] for e in strong if "discovered" not in e["stages"]} | {
        a.get("entity_key") for a in misses if a.get("entity_key") not in strong_keys
    }
    universe = len(strong_keys | never_seen)
    unique = sum(1 for e in this_month if len(e["source_ids"]) == 1)
    return {
        "found_this_month": len(this_month),
        "pre_funding_share": _rate(len(pf), len(this_month)),
        "pre_funding_this_month": len(pf),
        "median_lead_days": statistics.median(leads) if leads else None,
        "lead_n": len(leads),
        "found_at_announcement": at_ann,
        "strong_cases": len(strong),
        "strong_found_early": len(strong_early),
        "strong_found_late": len(strong_late),
        "exceptional_recall": _rate(len(found) - len(fn), universe),
        "strong_universe": universe,
        "strong_found_and_kept": len(found) - len(fn),
        "false_negatives": len(fn),
        "never_seen": len(never_seen),
        "unique_source_this_month": unique,
        "conviction": sum(1 for e in ents.values() if "conviction" in e["stages"]),
    }


# ------------------------------------------------------------------------------------------ external benchmarks
def benchmarks(ents: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Per benchmark system: how many companies PZ saw before / after the external visibility date."""
    by_sys: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in ents.values():
        if not e["first_seen"] or (not e["candidate_ids"] and "conviction" not in e["stages"]):
            continue
        evs = [
            (o.get("benchmark_system") or KINDS.get(o["kind"], o["kind"]), o["date"])
            for o in e["outcomes"]
            if o["kind"] in BENCHMARK_KINDS_ALL and o.get("date")
        ]
        if e.get("observed_news"):
            evs.append(("Public funding news (seen by a scan)", e["observed_news"]["date"]))
        firsts: dict[str, str] = {}
        for sysname, d in evs:
            if sysname not in firsts or d < firsts[sysname]:
                firsts[sysname] = d
        for sysname, d in firsts.items():
            by_sys[sysname].append(
                {"name": e["name"], "days": _days(e["first_seen"], d), "event_date": d, "first_seen": e["first_seen"]}
            )
    out = []
    for sysname, rows in sorted(by_sys.items()):
        days = [r["days"] for r in rows if r["days"] is not None]
        out.append(
            {
                "system": sysname,
                "companies": len(rows),
                "pz_earlier": sum(1 for d in days if d > 0),
                "pz_later_or_same": sum(1 for d in days if d <= 0),
                "median_days": statistics.median(days) if len(days) >= MIN_N else None,
                "examples": [
                    f"PZ first saw {r['name']} {r['days']} days {'before' if r['days'] > 0 else 'after'} the {sysname} event ({r['event_date']})"
                    for r in sorted(rows, key=lambda r: -(r["days"] or 0))[:5]
                    if r["days"] is not None
                ],
            }
        )
    return {
        "systems": out,
        "note": "Only dates we actually hold: scan observations, outcomes you recorded, exports you imported. "
        "No private database access is assumed and no date is estimated.",
    }


def _ai_cost(ledger: list[Any], today: date) -> dict[str, Any]:
    """Validation itself never calls a model; this reports the existing ledger spend for context. The month is the
    Berlin request day's (decision g; the old ``date.today()``), compared with the ledger's Berlin wall time."""
    month = today.isoformat()[:7]
    total = 0.0
    for r in ledger:
        if str(r.get("ts", ""))[:7] == month:
            total += float(r.get("usd") or 0)
    return {"month": month, "ai_usd_this_month": round(total, 4), "validation_usd": 0.0}


def snapshot_series(
    snapshots_log: str, head: dict[str, Any], cal: dict[str, Any], today: date, now: datetime
) -> list[dict[str, Any]]:
    """Decision (a): the old ``_snapshot`` append, IN MEMORY. The old code compared today with the date of the LAST
    stored row only and, when it was not today, appended today's point (``json.dumps(..., sort_keys=True)``, one line
    through ``storage.append_line``); the view then read the whole log back. The same row is appended to the log TEXT
    here, exactly as the file would have grown, and the series is read back from it. Nothing is stored."""
    rows = read_jsonl(snapshots_log)
    if rows and rows[-1].get("date") == today.isoformat():
        return rows
    line = json.dumps(
        {
            "date": today.isoformat(),
            "at": ts(now),
            **head,
            "decisions": cal["decisions"],
            "agreement": cal["agreement"],
        },
        sort_keys=True,
    )
    return read_jsonl(snapshots_log + line.replace("\n", " ") + "\n")


def _routing(ents: dict[str, dict[str, Any]], inputs: ValidationInputs) -> dict[str, Any] | None:
    """Triage Queue Compressor outcomes (human attention per serious opportunity, calibration, false negatives)."""
    try:
        return routing.metrics(
            {k: {"stages": e["stages"]} for k, e in ents.items()}, inputs.queue_routing, inputs.decisions_log
        )
    except Exception:  # a routing store problem never hides Validation
        return None


def _verification_calibration(verification_log: str) -> dict[str, Any]:
    """Mohamed's accept / reject decisions on deterministic founder and funding verification proposals."""
    out: dict[str, Any] = {}
    for d in read_jsonl(verification_log):
        f = out.setdefault(d.get("flag") or "?", {"accepted": 0, "rejected": 0})
        f["accepted" if d.get("decision") == "accept" else "rejected"] += 1
    return out


def measurement(head: dict[str, Any], cal: dict[str, Any], ents: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """For each core metric: is it KNOWN, still COLLECTING (with n), or NOT YET MEASURABLE (and what it needs)."""

    def st(n: int, needs: str, min_n: int = MIN_N) -> dict[str, Any]:
        if n >= min_n:
            return {"state": "KNOWN", "n": n, "needs": ""}
        return {"state": "COLLECTING" if n else "NOT YET MEASURABLE", "n": n, "needs": needs}

    # funnel decisions on companies PZ discovered (hand-entered Conviction entries never went through the funnel)
    decided = sum(1 for e in ents.values() if e["candidate_ids"] and (e.get("mohamed") or e["inbox_decision"]))
    return [
        {
            "metric": "Exceptional recall",
            "meaning": "Of the companies that later proved strong, how many did we catch?",
            **st(head["strong_universe"], "real-world outcomes (rounds, customers) and miss audits — months, not days"),
        },
        {
            "metric": "Signal lead time",
            "meaning": "How many days before a later public event did we first see the company?",
            **st(head["lead_n"], "dated later events: recorded outcomes, or scans seeing early finds in funding news"),
        },
        {
            "metric": "Quality conversion",
            "meaning": "How many discoveries progress to your acceptance, Conviction, verification?",
            **st(decided, "about 20 of your decisions on discovered companies, so group rates mean something", 20),
        },
        {
            "metric": "Misses",
            "meaning": "Strong companies we rejected, watched passively, or never saw.",
            **st(head["strong_universe"], "outcomes and miss audits"),
        },
        {
            "metric": "Source alpha",
            "meaning": "Which sources produce early, unique, high-value companies (not the most companies)?",
            "state": "PARTLY KNOWN",
            "n": head["found_this_month"],
            "needs": "volume, uniqueness and pre-funding share are known; downstream value needs your decisions and outcomes",
        },
        {
            "metric": "Your leverage",
            "meaning": "Serious opportunities per hour of your attention; you vs the machine.",
            **st(cal["decisions"], "your triage decisions (time is estimated from decision timestamps)"),
        },
    ]


# ---------------------------------------------------------------------------------------------- Scout 00 feedback
def _classify(e: dict[str, Any]) -> str:
    if e["strength"] in ("STRONG_VERIFIED", "STRONG_HUMAN"):
        return "SUCCESS"
    if e["strength"] in ("PROMISING_GATED", "PROMISING_HUMAN"):
        return "PROGRESSING"
    if e["strength"] == "NEGATIVE":
        return "DID NOT HOLD UP"
    return "PENDING"


def _progression(e: dict[str, Any]) -> str:
    human = [s for s in e["stages"] if s != "machine_keep_research"]
    return STAGE_LABEL[human[-1]] if human else "not in Project Zero"


def scout_summary(ents: dict[str, dict[str, Any]], inputs: ValidationInputs) -> dict[str, Any]:
    items = [(e, s) for e in ents.values() for s in e["scouts"]]
    seen = {s["cycle_id"] for _, s in items if s["cycle_id"]}
    order = list(inputs.scout_cycles or {})  # import order (the archive's KEY order)
    cycles = [c for c in order if c in seen] + sorted(seen - set(order))
    cls = Counter(_classify(e) for e, _ in items)
    log = read_jsonl(inputs.scout_log)
    return {
        "cycles": cycles,
        "items": len(items),
        "classification": dict(cls),
        "last_packet": log[-1] if log else None,
    }


# ------------------------------------------------------------------------------------------------------- the view
def news_inputs(inputs: ValidationInputs, ents: dict[str, dict[str, Any]]) -> Any:
    """Review 028a: the News inputs Validation carries, completed with ITS entity build (one build per request)."""
    from projectzero.news.inputs_model import NewsInputs, with_entities  # local: News imports Validation

    return with_entities(inputs.news_inputs or NewsInputs(), ents)


def _news_metrics(
    inputs: ValidationInputs, ents: dict[str, dict[str, Any]], today: date, now: datetime
) -> dict[str, Any]:
    """News learning, integrated here so there is ONE place for lead time / misses (no competing News score)."""
    try:
        from projectzero.news import core as news

        v = news.view(news_inputs(inputs, ents), today, now)
    except Exception:
        return {"available": False}
    misses = [
        a
        for a in _live(read_jsonl(inputs.audits_log))
        if a.get("type") == "miss" and "from News" in (a.get("note") or "")
    ]
    causes = Counter(a.get("why_missed") for a in misses)
    sensors = Counter(r["check"].get("first_source") for r in v["caught_early"] if r["check"].get("first_source"))
    return {
        "available": True,
        "reviewed": sum(v["counts"].get(k, 0) for k in ("CAUGHT_EARLY", "KNOWN_LATE", "MISSED", "HISTORICAL")),
        "caught_early": v["counts"].get("CAUGHT_EARLY", 0),
        "known_late": v["counts"].get("KNOWN_LATE", 0),
        "operational_misses": v["counts"].get("MISSED", 0),
        "historical_cases": v["counts"].get("HISTORICAL", 0),
        "not_yet_reviewed": sum(1 for r in v["misses"] if r["state"] == "UNKNOWN"),
        "median_lead_days": v["metrics"]["median_lead_days"],
        "preventable_misses": sum(1 for a in misses if a.get("preventable") == "yes"),
        "most_common_miss_cause": causes.most_common(1)[0][0] if causes else None,
        "early_discovery_sources": [k for k, _ in sensors.most_common(3)],
    }


def view(inputs: ValidationInputs, today: date, now: datetime) -> dict[str, Any]:
    """The old ``GET /api/validation`` payload, key for key and in the old order. ``today``: the Berlin day of
    ``now`` (the router passes ``berlin_today(now)``). Reads only (decision a)."""
    ents, issues = build(inputs, today)
    head = _headline(ents, today, inputs.audits_log)
    cal = calibration(ents, inputs.decisions_log)
    series = snapshot_series(inputs.snapshots_log, head, cal, today, now)
    audits = _live(read_jsonl(inputs.audits_log))
    outcomes = [o for o in _live(read_jsonl(inputs.outcomes_log)) if o.get("kind")]
    leads: list[dict[str, Any]] = sorted(
        (
            {"name": e["name"], **e["lead"]}
            for e in ents.values()
            if e["lead"] and e["lead"]["kind"] != "found_at_announcement"
        ),
        key=lambda r: -(r["days"] or 0),
    )
    strength = Counter(e["strength"] for e in ents.values())
    horizon = Counter(e["horizon"] for e in ents.values())
    fp_watch = [
        {"name": e["name"], "stages": e["stages"], "strength": e["strength"]}
        for e in ents.values()
        if e["strength"] == "NEGATIVE" and ("conviction" in e["stages"] or e["machine"] == "KEEP")
    ]
    return {
        "date": today.isoformat(),
        "headline": head,
        "sources": source_alpha(ents, inputs)[:25],
        "conversion": {
            d: conversion(ents, d, inputs.sources)[:12]
            for d in ("tier", "pre_funding", "capital_stage", "theme", "ecosystem", "scout")
        },
        "stage_labels": dict(STAGE_LABEL),
        "lead_times": leads[:20],
        "strength": dict(strength),
        "horizon": dict(horizon),
        "calibration": cal,
        "patterns": patterns(ents),
        "misses": [a for a in audits if a.get("type") == "miss"][-30:],
        "false_positive_audits": [a for a in audits if a.get("type") == "false_positive"][-30:],
        "false_positive_watch": fp_watch[:20],
        "outcomes": outcomes[-30:],
        "scout": scout_summary(ents, inputs),
        "snapshots": series[-SNAPSHOT_WINDOW:],
        "measurement": measurement(head, cal, ents),
        "benchmarks": benchmarks(ents),
        "news": _news_metrics(inputs, ents, today, now),
        "verification_calibration": _verification_calibration(inputs.verification_log),
        "data_issues": issues[:20],
        "cost": _ai_cost(inputs.inference_ledger, today),
        "routing": _routing(ents, inputs),
        "native_bridge": native_bridge_deferred(),
        "vocab": {
            "kinds": dict(KINDS),
            "miss_reasons": MISS_REASONS,
            "fp_causes": FP_CAUSES,
            "evidence_class": dict(EVIDENCE_CLASS),
            "min_n": MIN_N,
        },
    }

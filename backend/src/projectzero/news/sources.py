# ruff: noqa: E501
# (the old expressions and message templates are kept verbatim, long lines included)
"""News source intelligence, the read side (review 028a): the pure part of the old ``services/news_sources.py`` at
revision 6c739b9, ported line for line over ONE explicit ``NewsInputs`` (which news sources are best for Project
Zero, FOR WHICH PURPOSE, proven by observed data; never one universal score).

Only mechanical changes: every store read is a field of the inputs (the events, the runs log, the live Validation
outcomes, the metric cache, the source state, the extra feeds, the source network); ``_deal_flow_alpha`` reads the
source-alpha rows computed from the request's ONE Validation entity build (decision b); ``today`` is the request's
Berlin day (decision f). Decision (e): the Swiss ticker's TECHNICAL row read the old ``health.source_health()``
(System health, not ported): it answers ``UNKNOWN`` as the old code did without a matching source-health row, with
the visible reason ``HEALTH_REASON``. ``evaluate`` (the cache, the source state, the logs, the nominations) is 028c's.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from projectzero.dealflow.triage.view import decisions as read_jsonl
from projectzero.news import claims
from projectzero.news.catalog import (
    _CITE,
    _DIGEST,
    _MUNICH,
    _PR,
    _ROUND,
    BEST,
    CANDIDATE_MIN_EVENTS,
    DATABASE_DOMAINS,
    DEFAULT_WINDOW,
    EARLY_DAYS,
    EUROPE,
    FEEDS,
    HIGH_AUTHORITY_PRIOR,
    HYPOTHESES,
    MIN_COVERED,
    MIN_OVERLAP,
    PUBLICATIONS,
    SCOPES,
    WINDOWS,
)
from projectzero.news.inputs_model import NewsInputs
from projectzero.validation.core import _live, _sources

HEALTH_REASON = "System health arrives with its port"  # decision (e)


# ---------------------------------------------------------------------------------------------------- helpers
def wilson_lb(k: int, n: int, z: float = 1.645) -> float:
    """Lower bound of the Wilson interval: 2/2 ranks below 41/60."""
    if n <= 0:
        return 0.0
    p = k / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / den)


def sample_label(n: int) -> str:
    return "INSUFFICIENT DATA" if n < 8 else "EARLY READ" if n < 30 else "MORE RELIABLE"


def _rate(k: int, n: int) -> dict[str, Any]:
    return {
        "k": k,
        "n": n,
        "rate": round(k / n, 3) if n else None,
        "lb": round(wilson_lb(k, n), 3),
        "label": sample_label(n),
    }


def _host(url: str) -> str:
    h = (urlparse(url or "").hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _rows(raw: str) -> list[Any]:
    """The old ``news_sources._rows``: every line that parses as JSON (any value, unlike ``news._rows``)."""
    out = []
    for ln in raw.splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def _d(s: str) -> date | None:
    try:
        return date.fromisoformat(str(s or "")[:10])
    except ValueError:
        return None


def _europe(e: dict[str, Any]) -> bool:
    return bool(set(e.get("geo") or []) & EUROPE)


def scopes_of(e: dict[str, Any]) -> set[str]:
    out = set()
    if _europe(e):
        out.add("EUROPE")
    out |= set(e.get("geo") or []) & {"DE", "FR", "UK", "CH", "NORDICS"}
    text = " ".join([e.get("headline") or "", e.get("summary") or ""] + [s.get("headline") or "" for s in e["sources"]])
    if _MUNICH.search(text):
        out |= {"MUNICH", "DE"}
    th = set(e.get("themes") or [])
    if "ai" in th:
        out.add("AI")
    if th & {"robotics", "deeptech", "industrial", "defence"}:
        out.add("DEEPTECH")
    return out


def is_benchmark(e: dict[str, Any]) -> bool:
    """A MATERIAL, PZ-relevant canonical event: identified company, Europe, HIGH / MEDIUM, not fund news / noise.
    Curated historical cases are excluded (their sources were collected by research, not observed by feeds)."""
    return bool(
        not e.get("curated")
        and e.get("entity_key")
        and e.get("materiality") in ("HIGH", "MEDIUM")
        and e.get("event_type") != "fund"
        and not e.get("noise")
        and _europe(e)
    )


def _when(s: dict[str, Any]) -> tuple[datetime, str]:
    """Publication time and its precision ('hour' with a feed timestamp, else 'day')."""
    ts = s.get("published_ts") or ""
    if ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None), "hour"
        except ValueError:
            pass
    return datetime.fromisoformat(str(s.get("published") or "1970-01-01")[:10]), "day"


def _external_domain(publisher: str, events: list[dict[str, Any]]) -> str:
    """'Reuters (via The Star)' is Reuters: a recognised publication name wins over the hosting domain."""
    for rx, (_disp, dom) in PUBLICATIONS.items():
        if re.search(rx, publisher):
            return dom
    return _host(next((s["url"] for e in events for s in e["sources"] if s["publisher"] == publisher), ""))


def universe(inputs: NewsInputs) -> dict[str, dict[str, Any]]:
    """Monitored news sources: the News feeds, startupticker (reused from Deal Flow), publications added through the
    Adaptive Source Network. Everything else that appears in events is EXTERNAL (benchmark / confirmation only)."""
    out: dict[str, dict[str, Any]] = {}
    for f in FEEDS:
        out[f["name"]] = {
            "name": f["name"],
            "kind": "feed",
            "geo": f.get("geo", "EU"),
            "city": f.get("city", ""),
            "url": f["url"],
            "domain": _host(f["url"]),
            "lifecycle": "ESTABLISHED",
        }
    out["startupticker.ch"] = {
        "name": "startupticker.ch",
        "kind": "deal_flow_reuse",
        "geo": "CH",
        "city": "",
        "url": "https://www.startupticker.ch/",
        "domain": "startupticker.ch",
        "lifecycle": "ESTABLISHED",
    }
    for f in extra_feeds(inputs):
        out[f["name"]] = {
            "name": f["name"],
            "kind": "feed",
            "geo": f.get("geo", "EU"),
            "city": "",
            "url": f["feed_url"],
            "domain": _host(f.get("site_url") or f["feed_url"]),
            "lifecycle": f.get("state", "PROBATION"),
            "enabled": f.get("enabled", True),
        }
    return out


def extra_feeds(inputs: NewsInputs) -> list[dict[str, Any]]:
    return (inputs.feeds_extra or {}).get("feeds") or []


def _prior(domain: str, kind: str) -> str:
    if not domain:
        return "UNKNOWN"
    if any(domain == d or domain.endswith("." + d) for d in HIGH_AUTHORITY_PRIOR):
        return "HIGH-QUALITY INDEPENDENT MEDIA"
    if any(domain == d or domain.endswith("." + d) for d in DATABASE_DOMAINS):
        return "AGGREGATOR"
    pc = claims.classify("https://" + domain + "/")["publisher_class"]
    return {
        "media": "SPECIALIST MEDIA",
        "state": "PRIMARY / OFFICIAL",
        "program": "PRIMARY / OFFICIAL",
        "aggregator": "AGGREGATOR",
        "company": "PRESS RELEASE",
        "social": "LOW QUALITY",
    }.get(pc, "SPECIALIST MEDIA" if kind != "external" else "UNKNOWN")


# ------------------------------------------------------------------------------------------- disagreements
def disagreements(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Where independent reports of ONE canonical event state different amounts or round types. Never reconciled
    silently: OPEN until a primary source or a majority of ≥ 2 agreeing independent sources settles it."""
    from projectzero.news.core import amount_m

    out = []
    for e in events:
        srcs = [s for s in e["sources"] if s.get("independence") != "syndicated"]
        if len({s["publisher"] for s in srcs}) < 2:
            continue
        for field in ("amount_m", "round"):
            vals: dict[str, Any] = {}
            prim: set[str] = set()
            for s in srcs:
                v: Any
                if field == "amount_m":
                    v = amount_m(s.get("headline") or "")
                else:
                    m = _ROUND.search(s.get("headline") or "")
                    v = m.group(0).lower().replace("-", "") if m else None
                if v is not None and s["publisher"] not in vals:
                    vals[s["publisher"]] = v
                    if s.get("independence") == "primary":
                        prim.add(s["publisher"])
            if len(vals) < 2:
                continue
            groups: list[list[str]] = []
            for pub, v in vals.items():
                for g in groups:
                    w = vals[g[0]]
                    same = (abs(v - w) / max(v, w) <= 0.15) if field == "amount_m" else v == w
                    if same:
                        g.append(pub)
                        break
                else:
                    groups.append([pub])
            row = {
                "event_id": e["event_id"],
                "company": e.get("company"),
                "field": field,
                "values": vals,
                "event_date": e["event_date"],
            }
            if len(groups) == 1:
                out.append({**row, "status": "AGREE", "agree": groups[0], "contradicted": []})
                continue
            groups.sort(key=len, reverse=True)
            settled = next((g for g in groups if set(g) & prim), None) or (
                groups[0] if len(groups[0]) >= 2 and len(groups[0]) > len(groups[1]) else None
            )
            if settled:
                basis = "primary source" if set(settled) & prim else f"{len(settled)} independent sources agree"
                out.append(
                    {
                        **row,
                        "status": "RESOLVED",
                        "basis": basis,
                        "agree": settled,
                        "contradicted": [p for g in groups if g is not settled for p in g],
                    }
                )
            else:
                out.append({**row, "status": "OPEN", "agree": [], "contradicted": []})
    return out


# ------------------------------------------------------------------------------------------------- metrics
def _technical(name: str, src: dict[str, Any], runs: list[Any], start: str) -> dict[str, Any]:
    if src["kind"] == "deal_flow_reuse":
        # decision (e): the old ``health.source_health()`` row (System health, not ported) -> the old answer
        # without a matching row (``st = {}``), with the reason
        st: dict[str, Any] = {}
        return {
            "basis": "Deal Flow source health",
            "state": st.get("state") or "UNKNOWN",
            "runs": None,
            "ok_share": None,
            "streak": st.get("failures_in_row") or 0,
            "last_ok": st.get("last_ok"),
            "last_error": st.get("last_error") or "",
            "ok": None,
            "lb": None,
            "label": "—",
            "reason": HEALTH_REASON,
        }
    if src["kind"] == "external":
        return {"basis": "external — not fetched", "state": "NOT FETCHED", "runs": None, "ok_share": None, "streak": 0}
    attempts: list[tuple[str, bool, str]] = []
    for r in runs:
        if str(r.get("at") or "")[:10] < start:
            continue
        pf = (r.get("per_feed") or {}).get(name)
        if pf is not None:
            attempts.append((r["at"], bool(pf.get("ok")), str(pf.get("error") or "")))
            continue
        if not (r.get("sources_ok") or r.get("sources_failed")) or src["lifecycle"] != "ESTABLISHED":
            continue  # a run without fetching, or a publication that was not in the feed list yet
        err = next((x for x in r.get("sources_failed") or [] if x.startswith(name + ":")), "")
        attempts.append((r["at"], not err, err))
    ok = sum(1 for a in attempts if a[1])
    streak = 0
    for a in reversed(attempts):
        if a[1]:
            break
        streak += 1
    last_err = next((a[2] for a in reversed(attempts) if not a[1]), "")
    blocked = bool(re.search(r"\b(401|403|paywall|login|captcha)\b", last_err, re.I)) and streak > 0
    state = (
        "FAILING"
        if streak >= 3
        else "BLOCKED"
        if blocked
        else "DEGRADED"
        if streak
        else "HEALTHY"
        if attempts
        else "NEVER RUN"
    )
    return {
        "basis": "News run log",
        "state": state,
        "runs": len(attempts),
        "ok": ok,
        "ok_share": round(ok / len(attempts), 3) if attempts else None,
        "lb": round(wilson_lb(ok, len(attempts)), 3),
        "label": sample_label(len(attempts)),
        "streak": streak,
        "last_ok": next((a[0] for a in reversed(attempts) if a[1]), None),
        "last_error": last_err[:160],
    }


def _deal_flow_alpha(inputs: NewsInputs) -> dict[str, Any]:
    """Validation Source Alpha row of the Deal Flow source startupticker (reused, no competing lead time): over the
    rows computed from the request's ONE entity build (decision b)."""
    try:
        if inputs.source_alpha is None:
            raise LookupError("source alpha unavailable")  # the old ``try`` failed
        names = _sources(inputs.sources)
        for r in inputs.source_alpha:
            if "startupticker" in (names.get(r["source_id"], "") + r["source_id"]).lower():
                return r
    except Exception:  # source alpha unavailable for news sources (the old ``log.exception``)
        pass
    return {}


def compute(
    window: str, today: date, events: list[dict[str, Any]], inputs: NewsInputs, alpha: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Pure: every dimension per source for one rolling window. No writes."""
    days = WINDOWS.get(window, 90)
    start = (today - timedelta(days=days)).isoformat() if days else "0000-00-00"
    uni = universe(inputs)
    runs = _rows(inputs.runs_log)
    # article level: every source entry of every canonical event
    pubs_of = {e["event_id"]: {s["publisher"] for s in e["sources"]} for e in events}
    externals = sorted({p for ps in pubs_of.values() for p in ps} - set(uni))
    srcs = {
        **uni,
        **{
            p: {
                "name": p,
                "kind": "external",
                "geo": "",
                "city": "",
                "url": "",
                "lifecycle": "EXTERNAL",
                "domain": _external_domain(p, events),
            }
            for p in externals
        },
    }
    bench_all = [e for e in events if is_benchmark(e)]
    bench = [e for e in bench_all if e["event_date"] >= start]
    scopes = {e["event_id"]: scopes_of(e) for e in events}
    # mentions per company (any materiality, all time) for sourcing earliness
    mentions: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for e in events:
        if e.get("entity_key") and not e.get("curated"):
            for s in e["sources"]:
                mentions[e["entity_key"]].append(
                    (s["publisher"], str(s.get("published") or e["event_date"])[:10], e["event_type"])
                )
    funding_dates: dict[str, str] = {}
    for e in events:
        if e.get("entity_key") and e["event_type"] in ("funding", "valuation") and not e.get("curated"):
            k = e["entity_key"]
            funding_dates[k] = min(funding_dates.get(k, "9999"), e["event_date"])
    first_bench: dict[str, dict[str, Any]] = {}
    for e in sorted(bench, key=lambda x: x["event_date"]):
        first_bench.setdefault(e["entity_key"], e)
    dis = disagreements(events)
    dis_w = [x for x in dis if x["event_date"] >= start]
    multi = sum(1 for e in bench if len(pubs_of[e["event_id"]]) >= 2)
    overlap_ok = (
        multi >= MIN_OVERLAP and multi / max(1, len(bench)) >= 0.2
    )  # "unique" means something only with overlap
    outcomes = [
        o for o in _live(read_jsonl(inputs.outcomes_log)) if o.get("entity_key") and o.get("event_date", "") >= start
    ]
    sa_rows = alpha if alpha is not None else _deal_flow_alpha(inputs)
    # early mentions per (source, company): ≥ EARLY_DAYS before the company's first material event in the window
    early_by: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for k, e in first_bench.items():
        d0 = _d(e["event_date"])
        for pub, day, etype in mentions[k]:
            dd = _d(day)
            if dd and (d0 - dd).days >= EARLY_DAYS:  # type: ignore[operator]
                cur = early_by[pub].get(k)
                if not cur or day < cur["first_mention"]:
                    early_by[pub][k] = {
                        "company": e.get("company"),
                        "first_mention": day,
                        "lead_days": (d0 - dd).days,  # type: ignore[operator]
                        "precursor": etype,
                        "pre_funding": day < funding_dates.get(k, "9999"),
                        "event": e["headline"],
                    }

    rows: dict[str, dict[str, Any]] = {}
    for name, src in srcs.items():
        arts = [
            (s, e)
            for e in events
            for s in e["sources"]
            if s["publisher"] == name
            and str(s.get("published") or e["event_date"])[:10] >= start
            and not e.get("curated")
        ]
        cat: Counter[str] = Counter()
        for _s, e in arts:
            if e.get("noise") or e["event_type"] == "fund":
                cat["noise"] += 1
            elif not _europe(e):
                cat["not_pz"] += 1
            elif e["materiality"] == "HIGH" and e.get("entity_key"):
                cat["high"] += 1
            elif e["materiality"] in ("HIGH", "MEDIUM") and e.get("entity_key"):
                cat["relevant"] += 1
            else:
                cat["minor"] += 1
        n_art = len(arts)
        useful = cat["high"] + cat["relevant"]
        digests = sum(1 for s, _e in arts if _DIGEST.search(s.get("headline") or ""))
        articles = {
            "n": n_art,
            "digests": digests,
            **dict(cat),
            "precision": _rate(useful, n_art),
            "noise": _rate(cat["noise"] + cat["not_pz"], n_art),
        }
        # coverage: leave-one-out recall per scope
        recall = {}
        if src["kind"] != "external":
            for sc in SCOPES:
                b = [e for e in bench if sc in scopes[e["event_id"]] and (pubs_of[e["event_id"]] - {name})]
                if b:
                    recall[sc] = _rate(sum(1 for e in b if name in pubs_of[e["event_id"]]), len(b))
        # speed vs the earliest report of the same event
        delays: list[float] = []
        precs: set[str] = set()
        for e in bench:
            if name not in pubs_of[e["event_id"]] or len(pubs_of[e["event_id"]]) < 2:
                continue
            times = [(_when(s), s) for s in e["sources"]]
            mine = min(t[0][0] for t in times if t[1]["publisher"] == name)
            first = min(t[0][0] for t in times)
            precs |= {t[0][1] for t in times}
            delays.append((mine - first).total_seconds() / 3600)
        speed: dict[str, Any] = {
            "n": len(delays),
            "label": sample_label(len(delays)),
            "precision": "day" if "day" in precs else "hour",
        }
        if delays:
            q = sorted(delays)
            speed.update(
                median_h=round(statistics.median(q), 1),
                p25_h=round(q[len(q) // 4], 1) if len(q) >= 8 else None,
                p75_h=round(q[(3 * len(q)) // 4], 1) if len(q) >= 8 else None,
                within_24h=_rate(sum(1 for x in q if x <= 24), len(q)),
                within_72h=_rate(sum(1 for x in q if x <= 72), len(q)),
                first=_rate(sum(1 for x in q if x <= 0), len(q)),
            )
        # sourcing earliness: mention ≥ 14 days before the company's first material event in the window
        early = early_by.get(name, {})
        home = (
            "MUNICH"
            if src.get("city") == "Munich"
            else {"EU": "EUROPE"}.get(src.get("geo") or "", src.get("geo") or "EUROPE")
        )
        important = {e["entity_key"] for e in bench if home in scopes[e["event_id"]]}
        earliness = {
            "companies": len(early),
            "median_lead_days": statistics.median([x["lead_days"] for x in early.values()]) if early else None,
            "pre_funding": sum(1 for x in early.values() if x["pre_funding"]),
            "precursor_types": dict(Counter(x["precursor"] for x in early.values())),
            "share_of_important": _rate(len(set(early) & important), len(important)),
            "examples": sorted(early.values(), key=lambda x: -x["lead_days"])[:5],
            "deal_flow": {
                k: sa_rows.get(k) for k in ("discoveries", "median_lead_days", "lead_n", "pre_company", "strong")
            }
            if src["kind"] == "deal_flow_reuse" and sa_rows
            else None,
        }
        # originality (headline-level)
        synd = sum(1 for s, _e in arts if s.get("independence") == "syndicated")
        prl = sum(
            1
            for s, e in arts
            if _PR.search((s.get("headline") or "") + " " + (e.get("summary") or "" if e["sources"][0] is s else ""))
        )
        originality = {
            "n": n_art,
            "syndicated": _rate(synd, n_art),
            "press_release": _rate(prl, n_art),
            "original": _rate(max(0, n_art - synd - prl), n_art),
            "confidence": "headline-level estimate" + ("" if n_art >= 30 else " — low confidence (small sample)"),
        }
        # unique value
        uniq = [e for e in bench if pubs_of[e["event_id"]] == {name}]
        others_early = {k for n2, ks in early_by.items() if n2 != name for k in ks}
        unique = {
            "events": len(uniq),
            "companies": len({e["entity_key"] for e in uniq}),
            "early_companies": len(set(early) - others_early),
            "by_scope": dict(Counter(sc for e in uniq for sc in scopes[e["event_id"]])),
            "of_covered": _rate(len(uniq), sum(1 for e in bench if name in pubs_of[e["event_id"]])),
        }
        # authority: prior, then observed agreement
        agree = sum(1 for x in dis_w if name in x["agree"])
        contra = sum(1 for x in dis_w if name in x["contradicted"])
        opened = sum(1 for x in dis_w if x["status"] == "OPEN" and name in x["values"])
        prior = _prior(src.get("domain") or "", src["kind"])
        obs = _rate(agree, agree + contra)
        authority = {
            "prior": prior,
            "agree": agree,
            "contradicted": contra,
            "open": opened,
            "observed": obs,
            "basis": "observed" if agree + contra >= 8 else "prior (observations collecting)",
        }
        # independent benchmark: Validation outcomes recorded by Mohamed (not from this feed set)
        cov_out = sum(1 for o in outcomes if any(_near(m, name, o) for m in mentions.get(o["entity_key"], [])))
        row = {
            "name": name,
            "kind": src["kind"],
            "geo": src.get("geo") or "",
            "home_scope": home if src["kind"] != "external" else "",
            "lifecycle": src["lifecycle"],
            "domain": src.get("domain") or "",
            "articles": articles,
            "recall": recall,
            "speed": speed,
            "earliness": earliness,
            "originality": originality,
            "unique": unique,
            "authority": authority,
            "technical": _technical(name, src, runs, start),
            "independent": {"outcomes": len(outcomes), "covered": cov_out},
            "hypothesis": next((v for k, v in HYPOTHESES.items() if name.lower().startswith(k.lower())), ""),
        }
        row["sample"] = sample_label(n_art)
        row["roles"] = roles(row, overlap_ok)
        row["best_use"], row["not_for"], row["limitations"] = _explain(row)
        rows[name] = row
    bias = benchmark_bias(bench, pubs_of, uni, outcomes, rows)
    bias["overlap_ok"] = overlap_ok
    return {
        "window": window,
        "start": start,
        "today": today.isoformat(),
        "benchmark_events": len(bench),
        "sources": rows,
        "bias": bias,
        "best": best_by_purpose(rows, bias),
        "disagreements": dis_w[-30:],
    }


def _near(m: tuple[str, str, str], name: str, o: dict[str, Any]) -> Any:
    """The old inline test: a mention by ``name`` within 21 days of the outcome (``_d`` may be ``None``: it raises
    for a mention whose date parses against an outcome whose date does not, as before)."""
    return m[0] == name and _d(m[1]) and abs((_d(m[1]) - _d(o["event_date"])).days) <= 21  # type: ignore[operator]


def _min_n(scope: str) -> int:
    """Same minimum sample as the best-by-purpose ranking for that scope (roles and rankings never disagree)."""
    return next((b[4] for b in BEST if b[3] == scope), 8)


def roles(r: dict[str, Any], overlap_ok: bool = True) -> list[dict[str, str]]:
    """Several roles per source, each with its evidence. Empty = collecting data (never a guess)."""
    out: list[dict[str, str]] = []
    if r["kind"] == "external":
        prior = r["authority"]["prior"]
        out.append(
            {
                "role": "CONFIRMATION / AUTHORITY"
                if prior == "HIGH-QUALITY INDEPENDENT MEDIA"
                else "OUTCOME BENCHMARK",
                "basis": "prior",
                "evidence": f"external publication ({prior.lower()}); seen in {r['articles']['n']} "
                "curated / cited report(s) — not fetched, not a sourcing signal",
            }
        )
        return out
    a = r["authority"]
    if a["basis"] == "observed" and a["observed"]["lb"] >= 0.75:
        out.append(
            {
                "role": "CONFIRMATION / AUTHORITY",
                "basis": "observed",
                "evidence": f"facts agreed with other reports {a['agree']}/{a['agree'] + a['contradicted']}",
            }
        )
    eu = r["recall"].get("EUROPE")
    if r["home_scope"] == "EUROPE" and eu and eu["n"] >= 15 and eu["lb"] >= 0.25:
        out.append(
            {
                "role": "CORE EUROPEAN INTELLIGENCE",
                "basis": "observed",
                "evidence": f"covered {eu['k']}/{eu['n']} material European events reported elsewhere",
            }
        )
    home = r["recall"].get(r["home_scope"])
    if r["home_scope"] not in ("EUROPE", "") and home and home["n"] >= _min_n(r["home_scope"]) and home["lb"] >= 0.25:
        out.append(
            {
                "role": "REGIONAL INTELLIGENCE",
                "basis": "observed",
                "evidence": f"covered {home['k']}/{home['n']} {SCOPES.get(r['home_scope'], r['home_scope'])} events reported elsewhere",
            }
        )
    ea = r["earliness"]
    if ea["companies"] >= 3:
        out.append(
            {
                "role": "EARLY SIGNAL",
                "basis": "observed",
                "evidence": f"mentioned {ea['companies']} companies ≥ {EARLY_DAYS} days before their material event "
                f"(median {ea['median_lead_days']} days)",
            }
        )
    u = r["unique"]
    if overlap_ok and r["home_scope"] not in ("EUROPE", "") and u["by_scope"].get(r["home_scope"], 0) >= 3:
        out.append(
            {
                "role": "ECOSYSTEM SENSOR",
                "basis": "observed",
                "evidence": f"{u['by_scope'][r['home_scope']]} material {SCOPES.get(r['home_scope'])} event(s) no other source had",
            }
        )
    sp = r["speed"]
    if sp["n"] >= 8 and sp["first"]["lb"] >= 0.4:
        out.append(
            {
                "role": "OUTCOME BENCHMARK",
                "basis": "observed",
                "evidence": f"first (or co-first) report on {sp['first']['k']}/{sp['n']} shared events",
            }
        )
    o = r["originality"]
    if (o["n"] >= 15 and o["syndicated"]["rate"] >= 0.5) or (
        overlap_ok and u["of_covered"]["n"] >= 15 and (u["of_covered"]["rate"] or 0) <= 0.05
    ):
        out.append(
            {
                "role": "SECONDARY COVERAGE",
                "basis": "observed",
                "evidence": f"syndicated {o['syndicated']['k']}/{o['n']} · unique {u['events']} of {u['of_covered']['n']} covered events",
            }
        )
    pr, no = r["articles"]["precision"], r["articles"]["noise"]
    if r["articles"]["n"] >= 30 and (pr["rate"] or 0) < 0.15 and (no["rate"] or 0) >= 0.5:
        out.append(
            {
                "role": "LOW VALUE / NOISY",
                "basis": "observed",
                "evidence": f"{pr['k']}/{pr['n']} articles were material European events; {no['k']} noise / off-scope",
            }
        )
    return out


def _explain(r: dict[str, Any]) -> tuple[str, str, list[str]]:
    lim = []
    if r["kind"] == "deal_flow_reuse":
        lim.append("articles come from the Deal Flow scan and are dated by scan day (speed is approximate)")
    if r["speed"].get("precision") == "day":
        lim.append("publication times are day-precision for older articles")
    if r["kind"] == "external":
        lim.append("not fetched — observed only through curated cases and citations")
    if r["articles"]["n"] < 8:
        lim.append(f"only {r['articles']['n']} article(s) in this window")
    if r["articles"]["n"] and r["articles"].get("digests", 0) / r["articles"]["n"] >= 0.3:
        lim.append(
            f"{r['articles']['digests']} of its {r['articles']['n']} articles are digests / columns — deals inside a "
            "digest are not counted as single events, so its relevance and coverage are understated"
        )
    not_for = ""
    if r["home_scope"] and r["home_scope"] != "EUROPE":
        not_for = f"Europe-wide recall — it is a {SCOPES.get(r['home_scope'], r['home_scope'])} source by design"
    elif r["kind"] == "external":
        not_for = "sourcing alpha (too late) and continuous monitoring"
    if r["roles"]:
        best = "; ".join(f"{x['role'].lower()} ({x['evidence']})" for x in r["roles"][:2])
    else:
        best = "Collecting data" + (f" — hypothesis to test: {r['hypothesis']}" if r["hypothesis"] else "")
    return best, not_for, lim


def benchmark_bias(
    bench: list[dict[str, Any]],
    pubs_of: dict[str, set[str]],
    uni: dict[str, dict[str, Any]],
    outcomes: list[dict[str, Any]],
    rows: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Disclose how circular the benchmark is: events only one feed reported, origin concentration, overlap."""
    n = len(bench)
    multi = sum(1 for e in bench if len(pubs_of[e["event_id"]]) >= 2)
    origin: Counter[str] = Counter()
    for e in bench:
        first = min(e["sources"], key=lambda s: _when(s)[0])
        origin[first["publisher"]] += 1
    top, top_n = (origin.most_common(1) or [("", 0)])[0]
    warnings = []
    if n and top_n / n > 0.5 and n >= 8:
        warnings.append(
            f"{top_n}/{n} benchmark events were first (or only) reported by {top} — recall is measured "
            "leave-one-out, but the event universe itself leans on that source"
        )
    if n and multi / n < 0.2:
        warnings.append(
            f"only {multi}/{n} benchmark events were reported by two or more sources: cross-source "
            "comparisons (recall, speed) rest on that small overlap"
        )
    warnings.append(
        "the benchmark is the union of Project Zero's monitored feeds: an event none of them covered is "
        "invisible here (independent checks: Validation outcomes, miss audits, curated cases)"
    )
    return {
        "events": n,
        "multi_source": multi,
        "origin_top": {"source": top, "events": top_n},
        "warnings": warnings,
        "independent_outcomes": len(outcomes),
        "concentrated": bool(n and top_n / n > 0.5 and n >= 8),
    }


def best_by_purpose(rows: dict[str, dict[str, Any]], bias: dict[str, Any]) -> list[dict[str, Any]]:
    """Contextual answers, never one universal #1. Without enough data: COLLECTING DATA with what is missing."""
    out = []
    mon = {k: r for k, r in rows.items() if r["kind"] != "external"}
    for cid, label, metric, scope, min_n in BEST:
        cands: list[tuple[float, str, str, int]] = []
        for r in mon.values():
            if (
                metric == "recall"
                and bias.get("overlap_ok")
                and scope in r["recall"]
                and r["recall"][scope]["n"] >= min_n
                and r["recall"][scope]["k"] >= MIN_COVERED
            ):
                x = r["recall"][scope]
                cands.append(
                    (x["lb"], r["name"], f"covered {x['k']}/{x['n']} {SCOPES[scope]} events reported elsewhere", x["n"])  # type: ignore[index]
                )
            elif metric == "early" and r["earliness"]["companies"] >= min_n:
                ea = r["earliness"]
                cands.append(
                    (
                        ea["companies"] + (ea["median_lead_days"] or 0) / 1000,
                        r["name"],
                        f"{ea['companies']} companies mentioned ≥ {EARLY_DAYS} days before their material event "
                        f"(median {ea['median_lead_days']} days)",
                        ea["companies"],
                    )
                )
            elif metric == "authority" and r["authority"]["basis"] == "observed":
                x = r["authority"]["observed"]
                cands.append((x["lb"], r["name"], f"facts agreed with other reports {x['k']}/{x['n']}", x["n"]))
            elif metric == "unique" and bias.get("overlap_ok") and r["unique"]["events"] >= min_n:
                u = r["unique"]
                cands.append(
                    (
                        u["events"] + u["early_companies"],
                        r["name"],
                        f"{u['events']} material events and {u['early_companies']} early companies no other source had",
                        u["events"],
                    )
                )
            elif metric == "technical" and (r["technical"].get("runs") or 0) >= min_n:
                t = r["technical"]
                cands.append((t["lb"], r["name"], f"fetched {t['ok']}/{t['runs']} runs", t["runs"]))
        cands.sort(key=lambda c: (-c[0], c[1]))
        item: dict[str, Any] = {"id": cid, "label": label}
        if not cands:
            need = f"needs ≥ {min_n} observations for at least one source"
            if metric in ("recall", "unique") and not bias.get("overlap_ok"):
                need = (
                    f"sources overlap on only {bias.get('multi_source', 0)} events — coverage comparisons need "
                    f"≥ {MIN_OVERLAP} events reported by two or more sources"
                )
            elif metric == "recall":
                need = (
                    f"needs ≥ {min_n} {SCOPES[scope]} events reported by other sources, and a source covering "  # type: ignore[index]
                    f"≥ {MIN_COVERED} of them"
                )
            item.update(state="COLLECTING DATA", need=need)
        else:
            item.update(
                state="RANKED",
                leader={"source": cands[0][1], "why": cands[0][2], "n": cands[0][3]},
                runner_up={"source": cands[1][1], "why": cands[1][2]} if len(cands) > 1 else None,
                confidence=sample_label(cands[0][3]),
            )
            if metric == "recall" and bias.get("concentrated"):
                item["warning"] = bias["warnings"][0]
        out.append(item)
    return out


# --------------------------------------------------------------------------------------- missing publications
def missing_publications(events: list[dict[str, Any]], inputs: NewsInputs) -> list[dict[str, Any]]:
    """Unmonitored publications with repeated evidence: cited by monitored articles on material events, or present
    as sources of material events (curated / added). Databases are never news-source candidates."""
    uni = universe(inputs)
    mon_domains = {u["domain"] for u in uni.values()}
    seen: dict[str, dict[str, Any]] = {}
    for e in events:
        if e.get("materiality") not in ("HIGH", "MEDIUM") or not _europe(e):
            continue
        texts = " ".join(
            [e.get("headline") or "", e.get("summary") or ""] + [s.get("headline") or "" for s in e["sources"]]
        )
        found: dict[str, str] = {}
        for rx, (_disp, dom) in PUBLICATIONS.items():
            if re.search(rf"{_CITE}\W+(?:\w+\s+){{0,2}}(?:{rx})|\((?:{rx})\)", texts):
                found[dom] = "cited"
        for s in e["sources"]:
            if s["publisher"] not in uni:
                dom = _host(s.get("url") or "")
                for rx, (_disp, d2) in PUBLICATIONS.items():
                    if re.search(rx, s["publisher"]):
                        dom = d2
                if dom:
                    found.setdefault(dom, "reported")
        for dom, how in found.items():
            if dom in mon_domains:
                continue
            disp = next((v[0] for v in PUBLICATIONS.values() if v[1] == dom), dom)
            r = seen.setdefault(dom, {"domain": dom, "name": disp, "events": [], "how": Counter()})
            if e["event_id"] not in [x["event_id"] for x in r["events"]]:
                r["events"].append(
                    {
                        "event_id": e["event_id"],
                        "company": e.get("company"),
                        "date": e["event_date"],
                        "headline": e["headline"],
                        "how": how,
                    }
                )
                r["how"][how] += 1
    out = []
    for r in seen.values():
        db = any(r["domain"] == d or r["domain"].endswith("." + d) for d in DATABASE_DOMAINS)
        out.append(
            {
                **r,
                "how": dict(r["how"]),
                "n": len(r["events"]),
                "database": db,
                "ready": len(r["events"]) >= CANDIDATE_MIN_EVENTS and not db,
            }
        )
    out.sort(key=lambda r: (-r["n"], r["name"]))
    return out


# ------------------------------------------------------------------------------------------------------ views
def normal_window(window: Any) -> str:
    """Decision (d): the window is 30, 90, 180 or all; anything else is 90 (the old ``view``)."""
    return window if window in WINDOWS else DEFAULT_WINDOW


def view(inputs: NewsInputs, window: Any, today: date) -> dict[str, Any]:
    """The old ``GET /api/news_sources?window=`` payload (``news_sources.view``), computed live as before, key for
    key and in the old order. Reads only."""
    from projectzero.news.core import load

    window = normal_window(window)
    events = list(load(inputs.events)["events"].values())
    m = compute(window, today, events, inputs)
    st = _state(inputs)
    net = [c for c in _network(inputs)["candidates"].values() if c.get("family") == "news_publication"]
    for name, r in m["sources"].items():
        s = st.get(name) or {}
        r["status"] = (
            r["lifecycle"] if r["lifecycle"] in ("PROBATION", "TRUSTED", "EXTERNAL") else s.get("state", "ACTIVE")
        )
        r["status_reasons"] = s.get("reasons") or []
    srcs = sorted(m["sources"].values(), key=lambda r: (r["kind"] == "external", -r["articles"]["n"], r["name"]))
    return {
        **{k: m[k] for k in ("window", "start", "today", "benchmark_events", "bias", "best", "disagreements")},
        "sources": srcs,
        "declining": [{"name": r["name"], "reasons": r["status_reasons"]} for r in srcs if r["status"] == "DEGRADED"],
        "missing": [x for x in missing_publications(events, inputs)][:15],
        "candidates": [{"id": c["id"], "name": c["name"], "url": c["url"], "state": c["state"]} for c in net],
        "windows": list(WINDOWS),
        "scopes": dict(SCOPES),
        "note": "Each source is measured per purpose — coverage, speed, early signal, originality, unique value, "
        "relevance, authority and technical health — never one universal score. Fewer than 8 observations = "
        "INSUFFICIENT DATA.",
        "evaluated_at": (inputs.source_metrics or {}).get("at"),
    }


def _state(inputs: NewsInputs) -> Any:
    return inputs.source_state or {}


def _network(inputs: NewsInputs) -> Any:
    """The old ``source_network.load()``: the stored document with ``setdefault("candidates", {})`` (on a copy)."""
    d = dict(inputs.network) if isinstance(inputs.network, dict) else inputs.network
    d.setdefault("candidates", {})
    return d


def cached(source_metrics: Any) -> Any:
    """The old ``cached()``: the stored metric cache (``or {}`` applied by the reader)."""
    return source_metrics or {}


def source_note(publisher: str, snap: Any) -> str:
    """One short line for a story card: why this source matters (evidence-based roles only)."""
    r = ((snap.get("windows") or {}).get(DEFAULT_WINDOW) or {}).get("sources", {}).get(publisher)
    if not r:
        return ""
    if r["kind"] == "external":
        return f"{publisher} is used here as {r['roles'][0]['role'].lower()} ({r['authority']['prior'].lower()}), not as an early signal."
    if not r["roles"]:
        return ""
    x = r["roles"][0]
    return f"{publisher}: {x['role'].lower()} — {x['evidence']}."


def scout_lines(snap: Any) -> list[str]:
    """NEWS SOURCE LEARNING for the Scout 00 packet: evidence-based findings only (facts, not commands)."""
    w = (snap.get("windows") or {}).get(DEFAULT_WINDOW) or {}
    out = []
    for r in (w.get("sources") or {}).values():
        if r["kind"] == "external":
            continue
        for x in r["roles"]:
            use = {
                "EARLY SIGNAL": "early-signal source worth scouting from",
                "ECOSYSTEM SENSOR": "regional early-signal source",
                "SECONDARY COVERAGE": "low early-sourcing value (mostly duplicates)",
                "LOW VALUE / NOISY": "low sourcing value",
            }.get(x["role"])
            if use:
                out.append(f"{r['name']}: {x['evidence']} → Scout use: {use}")
    if not out and w:
        out.append(
            f"collecting data ({w.get('benchmark_events', 0)} material events in the last 90 days; no source has enough evidence yet)"
        )
    return out

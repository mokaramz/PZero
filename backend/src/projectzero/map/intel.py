# ruff: noqa: E501
# (protected gold-master logic: texts and templates are kept byte-for-byte)
"""Ground sourcing & ecosystem intelligence (review 025): the old ``services/geo_intel.py`` (:142-1085) at revision
6c739b9, ported line for line as PURE functions over ``MapInputs``.

WHERE is opportunity forming, WHERE should Mohamed go, WHO / WHAT is there, and WHERE is Project Zero blind? Nothing
here is an investment score: a city's state describes Project Zero's ACTIVITY / OPPORTUNITY SIGNALS there (and how
well Project Zero can see it), never the quality of its companies. Geography is never guessed: an item is placed
only when its OWN location text names a known city (or a known sub-locality such as Garching -> Munich).

The only changes:

* **Inputs are a parameter** (``MapInputs``): each old store read is a field (see ``inputs_model``); the per-layer
  tolerance (``_rows``) moved to the adapter, the per-record tolerance (``try`` per record) stays here.
* **One clock** (decision g): ``today`` is the Berlin request day (the old ``date.today()``, machine-local);
  ``built_at`` is the caller's Berlin wall time (old ``time.strftime("%Y-%m-%dT%H:%M:%S")``), and ``build_s`` is
  ``0.0`` (nothing is timed; the oracle freezes ``time.time`` so the old value is ``0.0`` too). No cache: each call
  computes ``build`` (the old mtime-keyed ``_CACHE`` and its lock are not ported).
* **The source network** comes from ``network.check_candidates`` (decision f, revision 2): only the usable candidates
  are read, and when records were left out the ``view`` / ``detail`` ``note`` gains ``network.skip_note`` (the old
  ``compat._skip`` wording). The old code answered 500 there.
* The skip counters (``compat._skip``) and the log lines are not ported (in-memory diagnostics only).

Errors are the old ones: ``detail`` / ``sourcing_day`` raise ``KeyError("unknown or unplaced ecosystem: <city>")``
(the old routes answered 404 for ``geo_ecosystem`` and 400 for ``sourcing_day``, with ``str(e).strip("'")``), and
``sourcing_day`` raises ``ValueError("date as YYYY-MM-DD")`` for a bad date (400); the city is checked first.

Reused ports: ``events.engine.GAZETTEER``, ``conviction.taste.score``, ``dealflow.triage.view.edge`` (the old
``triage_review.edge``), ``dealflow.triage.entity_repair.broken_name_reason``, ``conviction.operator.provenance_records``
and ``conviction.records.records`` (the old ``compat.records``). Pure: no I/O.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

from projectzero.conviction import taste
from projectzero.conviction.operator import provenance_records
from projectzero.conviction.records import records
from projectzero.dealflow.triage import entity_repair
from projectzero.dealflow.triage.view import edge as triage_edge
from projectzero.events.engine import GAZETTEER
from projectzero.map import catalog
from projectzero.map.inputs_model import MapInputs
from projectzero.map.network import READ_STATES, skip_note

ACTIVITY_DAYS = catalog.ACTIVITY_DAYS
MAX_PER_SOURCE = catalog.MAX_PER_SOURCE
EVENT_DAYS = catalog.EVENT_DAYS
STATES = catalog.STATES
FAMILY_LABEL = catalog.FAMILY_LABEL
COVERAGE_LABEL = catalog.COVERAGE_LABEL
COV_WORD = catalog.COV_WORD
NOTE = catalog.NOTE
COORDS = catalog.COORDS
SUBLOCAL = catalog.SUBLOCAL
HOME_DEFAULT = catalog.HOME_DEFAULT
_UI_TEXT = catalog._UI_TEXT
_ABROAD = catalog._ABROAD
_SCOUT_FAMILY = catalog._SCOUT_FAMILY
_SRC_FAMILY = catalog._SRC_FAMILY
_NEWS_FAMILY = catalog._NEWS_FAMILY


def _fold(s: Any) -> str:
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()


def _cities(inputs: MapInputs) -> dict[str, dict[str, Any]]:
    """Canonical city → {lat, lng, country, aliases, hours} from the coverage registry + events gazetteer."""
    out: dict[str, dict[str, Any]] = {}
    canon = {"München": "Munich", "Zurich": "Zürich", "Köln": "Cologne", "Kraków": "Krakow"}
    for city, (lat, lng, hrs) in GAZETTEER.items():
        c = canon.get(city, city)
        out.setdefault(c, {"city": c, "lat": lat, "lng": lng, "country": "", "aliases": set(), "hours": hrs})
        out[c]["aliases"].add(city)
    ecos = inputs.coverage_ecosystems  # the old ``coverage.ecosystems()`` ([] when it raised: in the adapter)
    for e in ecos:
        c = canon.get(e["city"], e["city"])
        row = out.get(c)
        if row is None:
            ll = COORDS.get(c)
            if not ll:
                continue  # no coordinates: never placed by guessing
            row = out[c] = {"city": c, "lat": ll[0], "lng": ll[1], "country": "", "aliases": set(), "hours": None}
        row["country"] = row["country"] or e["country"]
        row["aliases"] |= {e["city"], *e.get("aliases", [])}
    for c, ll in COORDS.items():
        out.setdefault(c, {"city": c, "lat": ll[0], "lng": ll[1], "country": "", "aliases": set(), "hours": None})
    out.setdefault(
        "Cottbus", {"city": "Cottbus", "lat": 51.7563, "lng": 14.3329, "country": "DE", "aliases": set(), "hours": None}
    )
    for c, r in out.items():
        r["aliases"] = sorted({_fold(a) for a in r["aliases"] | {c}})
    return out


class _Placer:
    def __init__(self, cities: dict[str, dict[str, Any]]):
        names = [(a, c) for c, r in cities.items() for a in r["aliases"]] + [(k, v) for k, v in SUBLOCAL.items()]
        names.sort(key=lambda x: -len(x[0]))
        self.rx = [(re.compile(r"(?<![a-z])" + re.escape(_fold(a)) + r"(?![a-z])"), c) for a, c in names]

    def city(self, location: str) -> str:
        """The city named in a location string (earliest mention wins); '' when only a country or abroad."""
        t = _fold(location)
        if not t.strip() or _ABROAD.search(t):
            return ""
        hits = [(m.start(), c) for rx, c in self.rx for m in [rx.search(t)] if m]
        return min(hits)[1] if hits else ""


def _rows(v: Any) -> list[Any]:
    """The tail of the old ``_rows``: a dict's values, else the sequence (an unusable value empties the layer)."""
    try:
        return list(v.values()) if isinstance(v, dict) else list(v or [])
    except Exception:
        return []


def scout_cycles(value: Any) -> str:
    """The old ``scout_intake.scout_cycles``: every Scout cycle id the provenance names, oldest first, no duplicates."""
    return ", ".join(
        dict.fromkeys(str(r.get("scout_cycle_id")) for r in provenance_records(value) if r.get("scout_cycle_id"))
    )


def _collect(inputs: MapInputs, today: date) -> dict[str, Any]:
    cities = _cities(inputs)
    place = _Placer(cities)
    bad: Counter[str] = Counter()
    since = (today - timedelta(days=ACTIVITY_DAYS)).isoformat()
    units: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unplaced: Counter[str] = Counter()
    hidden: Counter[str] = Counter()

    def add(city: str, **u: Any) -> None:
        if city:
            units[city].append(u)

    # Deal Flow (machine proposals are labelled as proposals, never decisions)
    src_fam: dict[str, list[str]] = {}
    for s in inputs.declared_sources:
        src_fam[s["id"]] = s.get("families") or []
    reg = {s["id"]: s for s in inputs.sources if isinstance(s, dict) and s.get("id")}
    props = inputs.proposals
    for c in records(inputs.inbox, ("id",)):
        try:
            if c.get("decision") in ("baseline", "rejected") or c.get("noise"):
                continue
            city = place.city(c.get("location") or "")
            if not city:
                unplaced["deal_flow"] += 1
                continue
            seen = str(c.get("first_seen") or c.get("first_seen_run") or "")[:10]
            p: Any = props.get(c["id"]) if isinstance(props.get(c["id"]), dict) else {}
            # page-watcher lines that are not companies (event titles, navigation, dates): hidden on the Map, never deleted
            if (
                p.get("entity_type") in ("NOT_AN_ENTITY", "NON_VENTURE")
                or entity_repair.broken_name_reason(c)
                or _UI_TEXT.search(str(c.get("name") or ""))
            ):
                hidden[city] += 1
                continue
            edge = triage_edge(p.get("capital_stage")) if p else "UNKNOWN"
            fams = [_SRC_FAMILY[f] for f in src_fam.get(c.get("source_id") or "", []) if f in _SRC_FAMILY]
            stage = (reg.get(c.get("source_id") or "") or {}).get("stage", "")
            early = p.get("proposal") != "REJECT" and (  # a machine REJECT is never counted as an early signal
                edge in ("PRE_FUNDING_EDGE", "ROUND_FORMING")
                or (edge == "UNKNOWN" and stage == "pre_company" and bool(fams))
            )
            late = edge in ("ALREADY_FUNDED", "FIRST_INSTITUTIONAL")
            add(
                city,
                kind="company",
                id=c["id"],
                entity=c.get("name"),
                label=c.get("name"),
                family=(fams or ["company_formation"])[0],
                early=early,
                late=late,
                recent=seen >= since,
                date=seen,
                source=c.get("source") or "",
                pz_state=f"Deal Flow · {c.get('decision')}",
                machine=(f"machine proposal: {p.get('proposal')} (not a decision)" if p else ""),
                stage_text=edge.replace("_", " ").lower() if p else "stage unknown",
                why=(c.get("why") or [""])[0][:160],
                watch=c.get("decision") == "watch",
                link=f"/deal-flow?candidate={c['id']}",
                location=c.get("location") or "",
            )
        except Exception:  # one unreadable record never hides the rest of the layer
            bad["Map: Deal Flow"] += 1
    # Conviction (Mohamed's decisions) — the official / verified score is shown only when verified
    for s in records(inputs.signals):
        try:
            if s.get("status") == "dropped":
                continue
            city = place.city(s.get("location") or "")
            if not city:
                unplaced["conviction"] += 1
                continue
            sc = taste.score(s)
            add(
                city,
                kind="company",
                id="cv-" + s["company"],
                entity=s["company"],
                label=s["company"],
                family="pz_conviction",
                early=False,
                late=False,
                recent=True,
                date=str(s.get("discovery_date") or "")[:10],
                source=s.get("discovery_source") or "",
                pz_state="Conviction",
                score=(
                    f"verified score {sc['verified']}"
                    if sc.get("fully_verified")
                    else f"provisional {sc['provisional']} (not verified)"
                ),
                stage_text=str(s.get("earliness") or s.get("stage") or "stage unknown"),
                why=(s.get("why_found") or s.get("one_liner") or "")[:160],
                scout=scout_cycles(s.get("scout_provenance")),
                link="/conviction?company=" + s["company"],
                location=s.get("location") or "",
            )
        except Exception:  # one unreadable record never hides the rest of the layer
            bad["Map: Conviction"] += 1
    # Scout 00 discoveries
    for it in inputs.scout_items:
        try:
            if it["status"] in ("REJECTED", "ARCHIVED"):
                continue
            city = place.city(it.get("location") or "")
            if not city:
                unplaced["scout"] += 1
                continue
            fams = ["scout00"] + [
                f for t in it.get("signal_types") or [] for k, f in _SCOUT_FAMILY.items() if k in str(t).lower()
            ]
            late = bool(re.search(r"series [b-z]|already (raised|funded)|late", str(it.get("stage") or ""), re.I))
            for f in dict.fromkeys(fams):
                add(
                    city,
                    kind="scout",
                    id=it["id"],
                    entity=it["entity_name"],
                    label=it["entity_name"],
                    family=f,
                    early=not late,
                    late=late,
                    recent=True,
                    date=it.get("date_discovered_effective") or "",
                    source=f"Scout 00 cycle {it['cycle_id']}",
                    pz_state=f"Scout Intake · {it['status']}",
                    scout=it["cycle_id"],
                    stage_text=str(it.get("stage") or "")[:80],
                    why=str(it.get("key_fact") or "")[:160],
                    founders=it.get("founders") or [],
                    link=f"/scout-intake?{urlencode({'item': it['id']})}" if inputs.scout_links else "/scout-intake",
                    location=it.get("location") or "",
                )
        except Exception:  # one unreadable record never hides the rest of the layer
            bad["Map: Scout Intake"] += 1
    # News (canonical events: five articles about one round are ONE unit)
    for e in _rows(inputs.news_events):
        try:
            if e.get("curated") or e.get("noise") or e.get("materiality") not in ("HIGH", "MEDIUM"):
                continue
            city = place.city(" ".join([e.get("headline") or "", e.get("summary") or ""]))
            if not city:
                continue
            late = e["event_type"] in ("funding", "valuation", "acquisition")
            add(
                city,
                kind="news",
                id=e["event_id"],
                entity=e.get("company") or e["event_id"],
                label=e["headline"][:120],
                family=_NEWS_FAMILY.get(e["event_type"], "news"),
                early=e["event_type"] in ("grant", "accelerator", "founder"),
                late=late,
                recent=e["event_date"] >= since,
                date=e["event_date"],
                source=e["sources"][0]["publisher"],
                themes=e.get("themes") or [],
                link="/news",
            )
        except Exception:  # one unreadable record never hides the rest of the layer
            bad["Map: News"] += 1
    # Founder Radar people (only what is recorded; no inferred relationships)
    for p in inputs.people:
        try:
            city = place.city(p.get("location") or "")
            if not city:
                continue
            pot = str(p.get("founder_potential") or "none").lower()
            add(
                city,
                kind="person",
                id=p["id"],
                entity=p.get("name"),
                label=p.get("name"),
                family="founder_formation" if pot in ("high", "medium") else "people",
                early=pot in ("high", "medium"),
                late=False,
                recent=True,
                date="",
                role=p.get("role") or "",
                org=p.get("company") or "",
                why=p.get("why_interesting") or "",
                relationship=p.get("relationship_strength") or "none recorded",
                next_action=p.get("next_action") or "",
                link=f"/network?person={p['id']}",
            )
        except Exception:  # one unreadable record never hides the rest of the layer
            bad["Map: people"] += 1
    # Upcoming events
    evs = inputs.events
    horizon = (today + timedelta(days=EVENT_DAYS)).isoformat()
    for e in evs:
        try:
            w = e.get("when") or {}
            start = w.get("start_date") or str(e.get("start") or "")[:10]
            if e.get("past") or not start or start > horizon or (w.get("end_date") or start) < today.isoformat():
                continue
            if (e.get("sc") or {}).get("band") == "REJECTED" or e.get("status") == "skipped":
                continue  # rejected by the Events engine or skipped by Mohamed: never a Map opportunity
            city = place.city(e.get("city") or "")
            if not city:
                continue
            a = e.get("assessment") or {}
            add(
                city,
                kind="event",
                id=e["id"],
                entity=e["id"],
                label=e["name"],
                family="event",
                early=False,
                late=False,
                recent=True,
                date=start,
                time=w.get("start_time") or "",
                band=(e.get("sc") or {}).get("band") or "",
                why=(e.get("sc") or {}).get("why") or "",
                audience=(a.get("founder") and f"founders: {a.get('founder')}") or "",
                registration=(e.get("action") or {}).get("state") or "unknown",
                price=e.get("price_state") or "price unknown",
                url=e.get("url") or "",
                status=e.get("status") or "",
                type=e.get("type") or "",
                link=f"/events?event={e['id']}",
            )
        except Exception:  # one unreadable record never hides the rest of the layer
            bad["Map: events"] += 1
    # WATCH triggers (open)
    wnames = {}
    try:
        for t in inputs.watch_open:
            wnames[str(t.get("name") or t.get("key") or "")] = t
    except Exception:
        pass
    # institutions (curated, verified)
    orgs = inputs.institutions
    org_by_city: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for o in orgs:
        try:
            city = place.city(o.get("city") or "")
            if city:
                org_by_city[city].append({k: o.get(k) for k in ("name", "kind", "why", "url")})
        except Exception:  # one unreadable record never hides the rest of the layer
            bad["Map: institutions"] += 1
    # coverage per ecosystem (Coverage Health — reused)
    cov: dict[str, dict[str, str]] = {}
    try:
        for e in inputs.coverage_all:
            cc = place.city(e["city"]) or e["city"]
            cov[cc] = {f: (e.get("families") or {}).get(f) or "UNKNOWN" for f in COVERAGE_LABEL}
    except Exception:
        pass
    net = [c for c in inputs.network if c["state"] in READ_STATES]
    return {
        "cities": cities,
        "units": units,
        "orgs": org_by_city,
        "coverage": cov,
        "watch": wnames,
        "network": net,
        "unplaced": dict(unplaced),
        "hidden": dict(hidden),
    }


# ------------------------------------------------------------------------------------------------- analysis
def convergence(units: list[dict[str, Any]]) -> dict[str, Any]:
    """Independent signal families: ≥ 3 different families from ≥ 4 independent units about ≥ 3 different entities.
    Late funding news and duplicate reports never create convergence (one canonical event = one unit)."""
    fams: dict[str, set[str]] = defaultdict(set)
    entities: set[str] = set()
    per_src: Counter[str] = Counter()
    for u in units:
        if u.get("late") or not u.get("recent") or u["family"] in ("pz_conviction", "people"):
            continue
        uid = u["kind"] + ":" + u["id"]
        src = (u.get("source") or u["kind"]) + "|" + u["family"]
        if uid not in fams[u["family"]]:
            if per_src[src] >= MAX_PER_SOURCE:  # a long list from one source adds no independence
                continue
            per_src[src] += 1
        fams[u["family"]].add(uid)
        entities.add(_fold(u.get("entity") or u["id"]))
    n_units = len({x for s in fams.values() for x in s})
    ok = len(fams) >= 3 and n_units >= 4 and len(entities) >= 3
    return {
        "converging": ok,
        "families": sorted(fams),
        "family_labels": [FAMILY_LABEL.get(f, f) for f in sorted(fams)],
        "signals": n_units,
        "entities": len(entities),
    }


def _coverage_view(cov: dict[str, str] | None) -> dict[str, Any]:
    if not cov:
        return {"assessed": False, "families": {}, "strong": 0, "weak": [], "visibility": "NOT ASSESSED"}
    fam = {COVERAGE_LABEL[k]: COV_WORD.get(v, v) for k, v in cov.items()}
    strong = sum(1 for v in cov.values() if v == "HEALTHY")
    weak = [COVERAGE_LABEL[k] for k, v in cov.items() if v in ("GAP", "UNKNOWN")]
    vis = "GOOD" if strong >= 5 else "LIMITED" if strong >= 3 else "POOR"
    return {"assessed": True, "families": fam, "strong": strong, "weak": weak, "visibility": vis}


def _state(early: int, conv: dict[str, Any], actionable: bool, total_recent: int, cov: dict[str, Any]) -> str:
    blind = cov["visibility"] in ("POOR", "NOT ASSESSED")
    if conv["converging"] and early >= 3:
        return "VERY ACTIVE"
    if early >= 2 or conv["converging"] or (early >= 1 and actionable):
        return "INTERESTING"
    if early == 0 and len(conv["families"]) <= 1:
        return "UNDER-COVERED" if blind else "LOW SIGNAL" if total_recent <= 3 else "NORMAL"
    return "NORMAL"


def _travel(city: dict[str, Any], home: dict[str, Any]) -> dict[str, Any]:
    km = _km(city["lat"], city["lng"], home["lat"], home["lng"])
    hrs = city.get("hours") if _fold(home.get("city") or "") == "karlsruhe" else None
    if hrs is not None:
        bucket = "NEARBY" if hrs <= 1 else "DAY TRIP" if hrs <= 3.5 else "OVERNIGHT"
        text = f"~{hrs:g} h from {home.get('city')} (approximate city table)"
    else:
        bucket = "NEARBY" if km <= 80 else "DAY TRIP" if km <= 300 else "OVERNIGHT"
        text = f"{round(km)} km from {home.get('city') or 'home'} — travel time not calculated"
    return {"bucket": bucket, "km": round(km), "text": text}


def _km(a1: float, o1: float, a2: float, o2: float) -> float:
    p = math.pi / 180
    h = 0.5 - math.cos((a2 - a1) * p) / 2 + math.cos(a1 * p) * math.cos(a2 * p) * (1 - math.cos((o2 - o1) * p)) / 2
    return 12742 * math.asin(math.sqrt(h))


def _summarise(name: str, data: dict[str, Any], home: dict[str, Any]) -> dict[str, Any]:
    city = data["cities"][name]
    us = data["units"].get(name, [])
    recent = [u for u in us if u.get("recent")]
    early_all = {u["kind"] + u["id"]: u for u in recent if u.get("early")}
    per_src: Counter[str] = Counter()
    early = set()
    for k, u in early_all.items():  # one long list from ONE source is volume, not breadth: at most 3 count per source
        src = u.get("source") or u["kind"]
        if per_src[src] < MAX_PER_SOURCE:
            per_src[src] += 1
            early.add(k)
    late = {u["kind"] + u["id"] for u in recent if u.get("late")}
    events = sorted({u["id"]: u for u in us if u["kind"] == "event"}.values(), key=lambda u: u["date"])
    hi_events = [e for e in events if e.get("band") == "HIGH-SIGNAL"]
    conv = convergence(us)
    covv = _coverage_view(data["coverage"].get(name))
    st = _state(len(early), conv, bool(hi_events), len({u["kind"] + u["id"] for u in recent}), covv)
    companies = {u["id"]: u for u in us if u["kind"] in ("company", "scout")}
    reasons = []
    if early:
        more = len(early_all) - len(early)
        reasons.append(
            f"{len(early)} early signal(s) from {len(per_src)} source(s) — pre-funding companies, research / programme / "
            "Scout 00 finds" + (f" (+{more} more from the same lists)" if more else "")
        )
    scouts = {u["id"] for u in us if u["kind"] == "scout"}
    if scouts:
        reasons.append(f"{len(scouts)} Scout 00 discover{'y' if len(scouts) == 1 else 'ies'}")
    conv_n = sum(1 for u in us if u["family"] == "pz_conviction")
    if conv_n:
        reasons.append(f"{conv_n} Conviction compan{'y' if conv_n == 1 else 'ies'}")
    if hi_events:
        reasons.append(f"{len(hi_events)} high-signal event(s) in the next {EVENT_DAYS} days")
    elif events:
        reasons.append(f"{len(events)} upcoming event(s)")
    watch_n = sum(1 for u in companies.values() if u.get("watch"))
    if watch_n:
        reasons.append(f"{watch_n} WATCH compan{'y' if watch_n == 1 else 'ies'}")
    themes = Counter(t for u in recent if u["kind"] == "news" for t in u.get("themes") or [])
    if themes:
        t, n = themes.most_common(1)[0]
        if n >= 2:
            reasons.append(f"{n} news stories on {t} recently")
    if late:
        reasons.append(f"{len(late)} late / already-funded item(s) — context, not an early edge")
    hid = data.get("hidden", {}).get(name, 0)
    if hid:
        reasons.append(f"{hid} page item(s) that are not companies (event titles, navigation) hidden — not signals")
    if covv["weak"]:
        reasons.append("Weak visibility: " + ", ".join(covv["weak"][:3]).lower())
    return {
        "city": name,
        "lat": city["lat"],
        "lng": city["lng"],
        "country": city.get("country") or "",
        "state": st,
        "early": len(early),
        "late": len(late),
        "companies": len(companies),
        "events": len(events),
        "high_signal_events": len(hi_events),
        "convergence": conv,
        "coverage": covv,
        "reasons": reasons,
        "travel": _travel(city, home),
        "hidden_non_companies": data.get("hidden", {}).get(name, 0),
        "scout": len(scouts),
        "conviction": conv_n,
    }


def _home(inputs: MapInputs) -> dict[str, Any]:
    h = inputs.home_base or HOME_DEFAULT
    return h if isinstance(h, dict) and "lat" in h else HOME_DEFAULT


def build(inputs: MapInputs, today: date, built_at: str | None = None) -> dict[str, Any]:
    """Summary of every placed ecosystem. ``built_at``: the caller's Berlin wall time ``%Y-%m-%dT%H:%M:%S`` (default:
    midnight of ``today``); ``build_s`` is ``0.0``."""
    data = _collect(inputs, today)
    home = _home(inputs)
    names = [c for c in data["cities"] if c in data["units"] or c in data["coverage"]]
    eco = [_summarise(n, data, home) for n in names]
    order = {s: i for i, s in enumerate(STATES)}
    eco.sort(key=lambda e: (order[e["state"]], -e["early"], -len(e["convergence"]["families"]), e["city"]))
    return {
        "ecosystems": eco,
        "data": data,
        "home": home,
        "built_at": built_at if built_at is not None else f"{today.isoformat()}T00:00:00",
        "build_s": 0.0,
        "today": today.isoformat(),
    }


# ------------------------------------------------------------------------------------------------------ views
def where_to_go(eco: list[dict[str, Any]]) -> dict[str, Any]:
    """Practical geographic opportunities (not company scoring). Empty when the data is too weak to rank."""
    cands = [
        e
        for e in eco
        if e["state"] in ("VERY ACTIVE", "INTERESTING") and (e["high_signal_events"] or e["early"] >= 2 or e["scout"])
    ]
    trav = {"NEARBY": 0, "DAY TRIP": 1, "OVERNIGHT": 2}
    cands.sort(
        key=lambda e: (
            e["state"] != "VERY ACTIVE",
            -len(e["convergence"]["families"]) if e["convergence"]["converging"] else 0,
            -(e["early"] + 2 * e["high_signal_events"] + e["scout"]),
            trav[e["travel"]["bucket"]],
        )
    )
    if not cands:
        return {
            "ranked": [],
            "note": catalog.WHERE_TO_GO_EMPTY_NOTE,
        }
    return {
        "ranked": [
            {"city": e["city"], "state": e["state"], "why": e["reasons"][:4], "travel": e["travel"]} for e in cands[:5]
        ],
        "note": catalog.WHERE_TO_GO_NOTE,
    }


def view(inputs: MapInputs, today: date, built_at: str | None = None) -> dict[str, Any]:
    """``GET /api/map/intel`` (the old ``GET /api/geo_intel``)."""
    b = build(inputs, today, built_at)
    eco = b["ecosystems"]
    by_state = Counter(e["state"] for e in eco)
    conv = [e for e in eco if e["convergence"]["converging"]]
    gaps = sorted(
        [e for e in eco if e["coverage"]["weak"] and e["coverage"]["assessed"] and (e["companies"] or e["events"])],
        key=lambda e: (-(e["companies"] + e["events"]), -len(e["coverage"]["weak"])),
    )
    home = b["home"]
    near = [e for e in eco if e["travel"]["bucket"] == "NEARBY"]
    wtg = where_to_go(eco)
    cards = []
    if wtg["ranked"]:
        w = wtg["ranked"][0]
        cards.append(
            {
                "id": "go",
                "title": "Where to go",
                "text": f"{w['city']} — {w['why'][0] if w['why'] else w['state'].lower()}",
                "city": w["city"],
            }
        )
    if near:
        cards.append(
            {
                "id": "nearby",
                "title": f"Happening near {home.get('city')}",
                "text": f"{sum(e['events'] for e in near)} upcoming event(s) · {sum(e['early'] for e in near)} early signal(s)",
                "city": near[0]["city"],
            }
        )
    if gaps:
        g = gaps[0]
        cards.append(
            {
                "id": "gap",
                "title": "Coverage gap",
                "text": f"{g['city']}: {', '.join(g['coverage']['weak'][:2]).lower()} weak",
                "city": g["city"],
            }
        )
    if conv:
        c = conv[0]
        cards.append(
            {
                "id": "conv",
                "title": "Signal convergence",
                "text": f"{c['city']} — {c['convergence']['signals']} signals across {len(c['convergence']['families'])} families",
                "city": c["city"],
            }
        )
    return {
        "ecosystems": [{k: v for k, v in e.items()} for e in eco],
        "counts": dict(by_state),
        "where_to_go": wtg,
        "cards": cards,
        "unplaced": b["data"]["unplaced"],
        "home": home,
        "built_at": b["built_at"],
        "build_s": b["build_s"],
        "note": NOTE + skip_note(inputs.network_problems),
        "legend": dict(catalog.LEGEND),
    }


def detail(inputs: MapInputs, city: str, today: date) -> dict[str, Any]:
    """``GET /api/map/ecosystem?city=`` (the old ``GET /api/geo_ecosystem``): the WHY HERE? panel for one ecosystem.
    Raises ``KeyError("unknown or unplaced ecosystem: <city>")``."""
    return _detail(build(inputs, today), city, inputs.network_problems)


def _detail(b: dict[str, Any], city: str, problems: list[str]) -> dict[str, Any]:
    data = b["data"]
    e = next((x for x in b["ecosystems"] if _fold(x["city"]) == _fold(city)), None)
    if e is None:
        raise KeyError(f"unknown or unplaced ecosystem: {city}")
    us = data["units"].get(e["city"], [])
    comp: dict[str, dict[str, Any]] = {}
    for u in us:
        if u["kind"] in ("company", "scout"):
            row = comp.setdefault(u["id"], dict(u, families=[]))
            row["families"].append(FAMILY_LABEL.get(u["family"], u["family"]))
    news_by_entity = defaultdict(list)
    for u in us:
        if u["kind"] == "news":
            news_by_entity[_fold(u.get("entity") or "")].append(u["label"])
    companies = []
    for c in sorted(
        comp.values(),
        key=lambda c: (not c.get("early"), c["kind"] != "scout", c.get("late", False), c.get("label") or ""),
    ):
        companies.append(
            {
                "name": c["label"],
                "kind": c["kind"],
                "pz_state": c.get("pz_state"),
                "first_seen": c.get("date") or "unknown",
                "stage": c.get("stage_text") or "unknown",
                "why": c.get("why") or "",
                "early": c.get("early"),
                "late": c.get("late"),
                "score": c.get("score") or "",
                "machine": c.get("machine") or "",
                "scout": c.get("scout") or "",
                "watch": bool(c.get("watch")) or any(_fold(k) == _fold(c["label"]) for k in data["watch"]),
                "news": news_by_entity.get(_fold(c.get("entity") or ""), [])[:2],
                "families": sorted(set(c["families"])),
                "link": c.get("link"),
                "founders": c.get("founders") or [],
                "next_action": "Open the record and decide"
                if "Deal Flow · new" in str(c.get("pz_state"))
                else "Review the Scout 00 card"
                if c["kind"] == "scout"
                else "See the workspace",
            }
        )
    people = [
        {k: u.get(k) for k in ("label", "role", "org", "why", "relationship", "next_action", "link")}
        for u in us
        if u["kind"] == "person"
    ]
    events = sorted([u for u in us if u["kind"] == "event"], key=lambda u: (u["date"], u.get("time") or ""))
    news_items = [u for u in us if u["kind"] == "news" and u.get("recent")]
    country = e["country"]
    gaps = e["coverage"]["weak"]
    fam_for_gap = {
        "Universities / research": "university_lab",
        "Accelerators": "accelerator",
        "Grants": "grant",
        "New companies": "incorporation",
        "Founder formation": "founder_move",
        "Events": "event",
    }
    want = {fam_for_gap[g] for g in gaps if g in fam_for_gap}
    tld = {"GB": "uk"}.get(country, country.lower())
    srcs = [
        {"name": c["name"], "state": c["state"], "family": c.get("family"), "url": c["url"]}
        for c in data["network"]
        if tld and (c["url"].split("/")[2].endswith("." + tld) or c.get("family") in want)
    ][:6]
    if events and any(ev.get("band") == "HIGH-SIGNAL" for ev in events):
        ev0 = next(ev for ev in events if ev.get("band") == "HIGH-SIGNAL")
        nba = f"Decide on {ev0['label']} ({ev0['date']}) — registration is yours to do."
    elif any(c["early"] for c in companies):
        top = next(c for c in companies if c["early"])
        nba = f"Research {top['name']} before anything else here."
    elif gaps:
        nba = f"Visibility is weak for {', '.join(gaps[:2]).lower()} — check System health → New sources before concluding anything."
    else:
        nba = "Nothing urgent here right now."
    return {
        **e,
        "why_here": e["reasons"] or ["No current Project Zero signals here."],
        "companies": companies[:12],
        "people": people[:10],
        "events": [
            {
                k: u.get(k)
                for k in (
                    "label",
                    "date",
                    "time",
                    "band",
                    "why",
                    "audience",
                    "registration",
                    "price",
                    "url",
                    "type",
                    "link",
                )
            }
            for u in events
        ][:10],
        "news": [
            {"headline": u["label"], "date": u["date"], "source": u["source"], "themes": u.get("themes")}
            for u in news_items
        ][:8],
        "institutions": data["orgs"].get(e["city"], [])[:10],
        "source_candidates": srcs,
        "scout": [c for c in companies if c["kind"] == "scout"],
        "next_best_action": nba,
        "note": NOTE
        + " Machine proposals and provisional scores are labelled as such; only verified scores are official."
        + skip_note(problems),
    }


def sourcing_day(inputs: MapInputs, city: str, day: str, today: date) -> dict[str, Any]:
    """``POST /api/map/sourcing_day {city, date}``: a PROPOSED ground-sourcing mission. Nothing is sent, registered or
    booked; no times or meetings are invented. Raises ``KeyError`` (unknown city, checked first) / ``ValueError``."""
    d = _detail(build(inputs, today), city, inputs.network_problems)
    try:
        when = date.fromisoformat(day)
    except ValueError as exc:
        raise ValueError("date as YYYY-MM-DD") from exc
    themes: Counter[str] = Counter()
    for c in d["companies"]:
        themes.update(f for f in c["families"])
    for n in d["news"]:
        themes.update(n.get("themes") or [])
    objective = ", ".join(t for t, _ in themes.most_common(2)) or "general ecosystem reconnaissance"
    on_day = [e for e in d["events"] if e["date"] == when.isoformat()]
    stops = []
    for o in d["institutions"][:3]:
        stops.append(
            {
                "time": "you choose (opening hours not checked)",
                "what": f"{o['name']} ({o['kind']})",
                "why": o.get("why") or "",
                "kind": "institution",
            }
        )
    early_cos = [c for c in d["companies"] if c["early"]][:3]
    for c in early_cos[:2]:
        stops.append(
            {
                "time": "only if you arrange it",
                "what": f"Possible founder meeting: {c['name']}",
                "why": c["why"] or c["stage"],
                "kind": "meeting",
            }
        )
    for e in on_day:
        stops.append(
            {
                "time": e.get("time") or "time not listed",
                "what": e["label"],
                "why": e.get("why") or "",
                "kind": "event",
                "registration": e.get("registration"),
                "url": e.get("url"),
            }
        )
    stops.sort(key=lambda s: (s["kind"] != "institution", s["kind"] == "event", s["time"]))
    people = [
        {
            "name": p["label"],
            "role": p.get("role"),
            "org": p.get("org"),
            "relationship": p.get("relationship"),
            "why": p.get("why") or p.get("next_action") or "",
        }
        for p in records(d["people"], ("id",))
    ][:5]
    for c in early_cos:
        for f in c.get("founders") or []:
            people.append(
                {
                    "name": f,
                    "role": "founder",
                    "org": c["name"],
                    "relationship": "none recorded — needs a warm path",
                    "why": "founder of a company you are researching",
                }
            )
    return {
        "city": d["city"],
        "date": when.isoformat(),
        "weekday": when.strftime("%A"),
        "objective": objective,
        "travel": d["travel"],
        "before_you_go": [
            {"name": c["name"], "why": c["why"] or c["stage"], "link": c["link"]}
            for c in (early_cos or d["companies"][:3])
        ],
        "people": people[:6],
        "stops": stops,
        "events_other_days": [e for e in d["events"] if e["date"] != when.isoformat()][:4],
        "bring_back": list(catalog.BRING_BACK),
        "coverage_caveat": d["coverage"]["weak"],
        "note": catalog.PLAN_NOTE,
        "empty": not (stops or d["companies"]),
    }


def search(inputs: MapInputs, q: str, today: date) -> list[dict[str, Any]]:
    """``GET /api/map/search?q=`` (the old ``geo_search``; the route wraps it as ``{"results": ...}``): cities,
    companies, people, events and institutions → the ecosystem they belong to."""
    q = _fold(q).strip()
    if len(q) < 2:
        return []
    rx = re.compile(r"(?<![a-z0-9])" + re.escape(q))  # word-start match: "tum" finds TUM, not "InSituMetrix"
    b = build(inputs, today)
    out = []
    for e in b["ecosystems"]:
        if rx.search(_fold(e["city"])):
            out.append({"kind": "city", "label": e["city"], "city": e["city"], "state": e["state"]})
    for city, us in b["data"]["units"].items():
        for u in us:
            if u["kind"] != "news" and rx.search(_fold(u.get("label") or "")):
                out.append({"kind": u["kind"], "label": u["label"], "city": city, "link": u.get("link")})
    for city, orgs in b["data"]["orgs"].items():
        for o in orgs:
            if rx.search(_fold(o["name"])):
                out.append({"kind": "institution", "label": o["name"], "city": city})
    seen, uniq = set(), []
    for r in out:
        k = (r["kind"], r["label"], r["city"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq[:20]

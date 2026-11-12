# ruff: noqa: E501
# (protected gold-master logic: texts and templates are kept byte-for-byte)
"""European Ecosystem Coverage (review 022): the old ``domain/coverage.py`` (:298-1041) at revision 6c739b9, ported
line for line, plus the three Founder Radar readers it used (``founder_radar/sources.py`` ``load_regions``,
``city_sources``, ``migrate_sources``, ``load_sources``; ``founder_radar/store.py`` ``load_health``) and the Events
``event_sources.load_health``.

The only changes:

* **Inputs are parameters** (``inputs.CoverageInputs``): the normalized Deal Flow registry, the documents and the
  records. The adoptions and source overrides are the imported documents overlaid by the ``coverage_adoptions`` rows
  (``inputs.merged_adoptions`` / ``merged_overrides``, plan revision 2).
* **No writes, ever** (decision a): the old reads wrote ``radar_regions.json`` / ``radar_sources.json`` when they were
  missing (or unusable); here such a document is read as the same defaults, in memory. The Founder Radar migration
  log is not written either.
* **One clock** (decision c): ``now`` for ``generated`` (Berlin wall time) and ``today`` (its Berlin day) for the
  45 / 120-day windows; the old code used the machine's local clock.
* **The ecosystem registry is built ONCE per call** (decision d) and passed to ``place_of``; the old code rebuilt it
  for every record and every source city. Nothing changes between those rebuilds, so the result is unchanged.

Kept quirk (decision b): an event source is never "productive": the ``event_health`` rows carry no ``count``.
Reused ports: ``events.registry.DEFAULT_SOURCES`` (the old ``event_sources.DEFAULT_SOURCES``) and the city registry
of ``ecosystems.cities``. Pure: no I/O.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from functools import lru_cache
from typing import Any

from projectzero.conviction.records import records
from projectzero.ecosystems import catalog, cities
from projectzero.ecosystems.inputs import CoverageInputs, _doc, merged_adoptions, merged_overrides
from projectzero.events import registry as event_sources
from projectzero.network.view import berlin_now

FAMILIES = catalog.FAMILIES
STATES = catalog.STATES
FRESH_DAYS = catalog.FRESH_DAYS
PRODUCTIVE_DAYS = catalog.PRODUCTIVE_DAYS
COUNTRY_NAMES = catalog.COUNTRY_NAMES
_ALIASES = catalog._ALIASES
_SCOPES = catalog._SCOPES
_CC = catalog._CC

Registry = list[dict[str, Any]]


def _fold(s: Any) -> str:
    return _fold_text(str(s or ""))


@lru_cache(maxsize=65536)
def _fold_text(t: str) -> str:
    """The fold of one text, cached: it is pure, and the coverage report folds the same names hundreds of thousands of
    times per request (review 025: the Map computes coverage on every intelligence request)."""
    return re.sub(
        r"[^a-z0-9 ]", "", unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    ).strip()


@lru_cache(maxsize=4096)
def _word(folded: str) -> re.Pattern[str]:
    """The whole-word pattern of a folded name (the old per-call ``re.search`` pattern, unchanged), compiled once."""
    return re.compile(r"\b" + re.escape(folded) + r"\b")


def _days_ago(iso: Any, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(str(iso)[:10])).days
    except Exception:
        return None


# ------------------------------------------------------------------ the Founder Radar and Events documents (read only)
def load_regions(doc: Any) -> list[dict[str, Any]]:
    """founder_radar ``load_regions``: the region registry, or the defaults (never written here)."""
    d = doc
    if d is not None:
        try:
            if d.get("regions"):
                return [{"region": r["region"], "cities": [tuple(c) for c in r["cities"]]} for r in d["regions"]]
        except Exception:
            pass
    return list(catalog.DEFAULT_REGIONS)


def city_sources(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One bounded GitHub source per registry city (data-driven; no city is hard-coded in the scan itself)."""
    out = []
    for r in regions:
        for city, cc in r["cities"]:
            out.append(
                {
                    "id": "gh-" + re.sub(r"[^a-z0-9]+", "-", _fold(city)),
                    "name": f"GitHub — builders in {city}",
                    "kind": "github_users",
                    "query": f'location:"{city}" repos:>15 followers:>40',
                    "city": city,
                    "country": cc,
                    "region": r["region"],
                }
            )
    return out


def migrate_sources(d: Any) -> tuple[Any, bool]:
    """radar_sources.json v1 -> v2 (the old migration, without its log write): legacy github_users entries removed."""
    srcs = d.get("sources") or []
    if d.get("schema") == catalog.SOURCES_SCHEMA and not any(x.get("kind") == "github_users" for x in srcs):
        return d, False
    kept = [x for x in srcs if x.get("kind") != "github_users"]
    d2 = {"schema": catalog.SOURCES_SCHEMA, "sources": kept}
    return d2, True


def load_sources(doc: Any) -> list[dict[str, Any]]:
    """founder_radar ``load_sources``: the configured radar sources, or the defaults (never written here)."""
    d = doc
    if d is not None:
        try:
            d, _changed = migrate_sources(d)
            if d.get("sources"):
                return [
                    x for x in d["sources"] if x.get("kind") != "github_users"
                ]  # defence in depth: never a static GitHub city source
        except Exception:
            pass
    return list(catalog.RADAR_DEFAULT_SOURCES)


def radar_health(doc: Any) -> Any:
    """founder_radar ``load_health``."""
    d = doc
    if isinstance(d, dict):
        return d
    return {"scan_time": "", "totals": {}, "sources": [], "note": "No founder scan yet — press Scan founder signals."}


def event_health(doc: Any) -> Any:
    """event_sources ``load_health``."""
    d = doc
    if d is not None:
        return d
    return {"scan_time": "", "totals": {}, "sources": [], "note": "No event scan yet — press Scan sources."}


# ------------------------------------------------------------------ ecosystem registry
def ecosystems(inputs: CoverageInputs) -> Registry:
    """Registry rows {id, city, country, country_name, region, aliases, source}. Data-driven: radar regions + ecosys cities + defaults + coverage_registry.json."""
    rows: Registry = []
    seen: dict[str, dict[str, Any]] = {}

    def add(city: Any, cc: Any, region: Any = "", src: str = "registry", aliases: Any = ()) -> None:
        city = str(city or "").strip()
        cc = str(cc or "").strip().upper()
        if not city:
            return
        key = _fold(city)
        if key in seen:
            r = seen[key]
            if not r["country"] and cc:
                r["country"] = cc
            if region and not r["region"]:
                r["region"] = region
            for a in aliases:
                if a and a not in r["aliases"]:
                    r["aliases"].append(a)
            return
        r = {
            "id": "eco-" + re.sub(r"[^a-z0-9]+", "-", key).strip("-"),
            "city": city,
            "country": cc,
            "country_name": COUNTRY_NAMES.get(cc, cc),
            "region": region,
            "aliases": list(aliases),
            "source": src,
        }
        seen[key] = r
        rows.append(r)

    for r in load_regions(inputs.radar_regions):
        for city, cc in r["cities"]:
            add(city, cc, r["region"], "radar_regions.json")
    eco_cities, _orgs = cities.registry(inputs.ecosystems_doc)
    for c in eco_cities:
        add(c["name"], c.get("country", ""), "", "ecosystems.json")
    for city, cc in catalog.DEFAULT_ECOSYSTEMS:
        add(city, cc, "", "default probe")
    for x in _doc(inputs.coverage_registry, {}).get("ecosystems", []):
        add(x.get("city"), x.get("country"), x.get("region", ""), "coverage_registry.json", x.get("aliases") or [])
    for r in rows:  # canonical alias forms (Munich/München …)
        for a, b in _ALIASES.items():
            if _fold(b) == _fold(r["city"]) and a not in [x.lower() for x in r["aliases"]]:
                r["aliases"].append(a)
    return rows


def place_of(text: Any, registry: Registry) -> tuple[str, str]:
    """(city, country_code) mentioned in a free-text location, matched against the registry. Never guesses."""
    t = _fold(text)
    if not t:
        return "", ""
    cc = ""
    for tok in re.split(r"[,/·|]", str(text or "")):
        k = _fold(tok)
        if k in _ALIASES and len(_ALIASES[k]) == 2 and _ALIASES[k].isupper():
            cc = _ALIASES[k]
        elif len(k) == 2 and k.upper() in COUNTRY_NAMES:
            cc = k.upper()
    for r in registry:
        names = [r["city"], *r["aliases"]]
        if any(_word(_fold(n)).search(t) for n in names if _fold(n)):
            return r["city"], r["country"] or cc
    return "", cc


# ------------------------------------------------------------------ source declarations (derived + Grok-audit overrides)
def families_of(src: dict[str, Any]) -> list[str]:
    """Signal families a configured source serves, from its own metadata (never invented): stage / parser / kind / name."""
    n = " ".join(str(src.get(k, "")) for k in ("name", "notes", "parser", "kind", "url")).lower()
    st = str(src.get("stage", "")).lower()
    fam = set()
    if src.get("kind") in ("github_users", "openalex_works", "orcid", "epo") or "talent" in n or "founder" in n:
        fam.add("founder_formation")
    if st in ("pre_seed_seed", "announcement") or "funding" in n or "seed" in n:
        fam.add("emerging_companies")
    if any(
        k in n
        for k in (
            "spin",
            "epfl",
            "helmholtz",
            "mpg",
            "max planck",
            "fraunhofer",
            "univers",
            "tum",
            "eth",
            "kit",
            "transfer",
            "cordis",
            "research",
        )
    ):
        fam.add("spinouts")
    if st == "grant" or any(
        k in n for k in ("grant", "sbir", "nsf", "nih", "gtr", "sprind", "eic", "cordis", "innovat")
    ):
        fam.add("grants")
    if any(
        k in n
        for k in (
            "accelerator",
            "incubator",
            "cohort",
            "program",
            "diana",
            "eudis",
            "batch",
            "portfolio",
            "startup autobahn",
            "station f",
            "yes!delft",
        )
    ):
        fam.add("programs")
    if str(src.get("id", "")).startswith("ev-") or src.get("_event_source"):
        fam.add("events")
    if st in ("announcement", "mixed") or src.get("kind") in ("rss",) or "news" in n or "announce" in n or "press" in n:
        fam.add("general")
    if not fam:
        fam.add("general")
    return sorted(fam)


def countries_of(src: dict[str, Any], registry: Registry) -> set[str] | None:
    """Country codes / scopes a configured source declares (geo list, country, geo_scope, city). None = global."""
    out: set[str] = set()
    vals = [*list(src.get("geo") or []), src.get("country", ""), src.get("geo_scope", ""), src.get("location", "")]
    for v in vals:
        k = str(v or "").strip().lower()
        if not k:
            continue
        if k in _CC:
            k = _CC[k]
        if k in _SCOPES:
            if _SCOPES[k] is None:
                return None
            out |= _SCOPES[k]  # type: ignore[arg-type]
            continue
        if k.startswith("region-"):
            k2 = k[7:]
            if k2 in _SCOPES:
                if _SCOPES[k2] is None:
                    return None
                out |= _SCOPES[k2]  # type: ignore[arg-type]
            continue
        if len(k) == 2 and k.upper() in COUNTRY_NAMES:
            out.add(k.upper())
        if k in _ALIASES and len(_ALIASES[k]) == 2 and _ALIASES[k].isupper():
            out.add(_ALIASES[k])
    if src.get("city"):
        _city, cc = place_of(src["city"], registry)
        if cc:
            out.add(cc)
    return out


# ------------------------------------------------------------------ Grok coverage audit: candidate sources (declared, provenance kept, never auto-activated)
def cand_id(c: dict[str, Any]) -> str:
    return "cand-" + re.sub(r"[^a-z0-9]+", "-", _fold(c.get("source_name") or c.get("url") or "")).strip("-")[:48]


def candidate_sources(inputs: CoverageInputs) -> list[dict[str, Any]]:
    """Candidate watchers from the coverage audit registry JSON(s). Audit artifact = implementation INPUT: each row keeps its provenance
    (registry id / version, access mode, limitations, reliability, freshness). A candidate is NOT a configured source until Mohamed adopts it
    explicitly (adopt_candidate) — it never contributes to HEALTHY / PARTIAL; it only names the proposed watcher pack for a GAP / UNKNOWN family."""
    out: list[dict[str, Any]] = []
    seen = set()
    files = [("coverage_candidates.json", _doc(inputs.coverage_candidates, {})), *inputs.candidate_files]
    for name, d in files:
        if not d.get("sources"):
            continue
        origin = {
            "registry_id": d.get("registry_id", ""),
            "version": d.get("version", ""),
            "generated_at": d.get("generated_at", ""),
            "file": name,
        }
        for c in d["sources"]:
            cid = cand_id(c)
            if cid in seen:
                continue
            seen.add(cid)
            cc = (
                _ALIASES.get(_fold(c.get("country")), "")
                if len(_ALIASES.get(_fold(c.get("country")), "")) == 2
                else (str(c.get("country") or "")[:2].upper() if len(str(c.get("country") or "")) == 2 else "")
            )
            fam = catalog._AUDIT_FAMILY.get(str(c.get("signal_family") or "").lower(), "general")
            if str(c.get("source_type") or "") == "accelerator":  # noqa: SIM108  (the old form)
                fam2 = "programs"
            else:
                fam2 = ""
            city = "" if str(c.get("city") or "").lower() in ("national", "", "none") else str(c.get("city"))
            out.append(
                {
                    "id": cid,
                    "name": c.get("source_name", ""),
                    "url": c.get("url", ""),
                    "country": cc,
                    "country_name": c.get("country", ""),
                    "city": city,
                    "families": sorted({fam} | ({fam2} if fam2 else set())),
                    "source_type": c.get("source_type", ""),
                    "stage": c.get("expected_stage_visibility", ""),
                    "why": c.get("why_it_matters", ""),
                    "access_mode": c.get("access_mode", ""),
                    "reliability": c.get("expected_reliability", ""),
                    "freshness": c.get("likely_freshness", ""),
                    "access_limitations": c.get("access_limitations", ""),
                    "origin": origin,
                    "status": "CANDIDATE — not activated",
                }
            )
    adopted = merged_adoptions(inputs)
    for c in out:
        if c["id"] in adopted:
            c["status"] = "ADOPTED — configured as watcher ({})".format(adopted[c["id"]].get("on", ""))
            c["adopted"] = adopted[c["id"]]
    return out


def declared_sources(inputs: CoverageInputs, registry: Registry, today: date) -> list[dict[str, Any]]:
    """Every configured source (discovery registry + event sources + Founder Radar city/country sources) with its coverage declaration and
    recorded run facts: configured · last_scan · retrieved(last_ok) · records(last_result_count) · failing · families · countries · cities."""
    overrides = merged_overrides(inputs)
    out: list[dict[str, Any]] = []

    def push(
        src: dict[str, Any],
        sid: Any,
        name: Any,
        kind: Any,
        last_scan: Any,
        last_ok: Any,
        count: Any,
        failing: Any,
        city: Any = "",
        enabled: Any = True,
        origin: str = "discovery",
    ) -> None:
        d: dict[str, Any] = {
            "id": sid,
            "name": name,
            "kind": kind,
            "origin": origin,
            "enabled": bool(enabled),
            "configured": True,
            "last_scan": last_scan or "",
            "last_ok": last_ok or "",
            "records": count,
            "failing": bool(failing),
            "families": families_of(src),
            "countries": countries_of(src, registry),
            "cities": [city] if city else [],
        }
        o = overrides.get(sid) or {}
        if o.get("families"):
            d["families"] = list(o["families"])
        if o.get("countries") is not None:
            d["countries"] = (
                None if o["countries"] in ("global", ["global"]) else {str(c).upper() for c in o["countries"]}
            )
        if o.get("cities"):
            d["cities"] = list(o["cities"])
        if o.get("note"):
            d["note"] = o["note"]
        d["declared_by"] = "coverage_sources.json" if o else "source metadata"
        d["retrieved"] = bool(d["last_ok"])
        d["productive"] = bool(count) and count > 0
        d["last_ok_days"] = _days_ago(d["last_ok"], today) if d["last_ok"] else None
        out.append(d)

    for s in inputs.sources:  # the old connectors.load_registry().get("sources", [])
        push(
            s,
            s["id"],
            s.get("name", s["id"]),
            s.get("kind", ""),
            s.get("last_scan"),
            s.get("last_ok"),
            s.get("last_result_count"),
            (s.get("failures_in_row") or 0) > 0,
            enabled=s.get("enabled", True),
        )
    eh = {r.get("id"): r for r in event_health(inputs.event_health).get("sources", [])}
    for s in event_sources.DEFAULT_SOURCES:
        h = eh.get(s["id"]) or {}
        push(
            dict(s, _event_source=True),
            s["id"],
            s["name"],
            s.get("kind", ""),
            h.get("attempted_at") or h.get("last_scan"),
            h.get("last_ok"),
            h.get("count", h.get("events")),
            h.get("status") in ("failed", "error"),
            city=s.get("city", ""),
            origin="events",
        )
    fh = {r.get("id"): r for r in radar_health(inputs.radar_health).get("sources", [])}
    try:
        cs = city_sources(load_regions(inputs.radar_regions))
    except Exception:
        cs = []
    for s in cs + [x for x in load_sources(inputs.radar_sources) if x.get("kind") != "github_users"]:
        h = fh.get(s["id"]) or {}
        push(
            dict(s, kind=s.get("kind")),
            s["id"],
            s.get("name", s["id"]),
            s.get("kind", ""),
            h.get("attempted_at"),
            h.get("last_ok"),
            h.get("raw"),
            h.get("status") == "failed",
            city=s.get("city", ""),
            origin="founder_radar",
        )
    return out


# ------------------------------------------------------------------ findings (records actually seen per ecosystem)
def records_by_place(inputs: CoverageInputs, registry: Registry) -> list[dict[str, Any]]:
    """Records Project Zero actually holds, grouped by (city, country): inbox candidates, pipeline companies, people, events — with their sources and dates."""
    recs: list[dict[str, Any]] = []
    for c in records(inputs.inbox, ("id",)):
        city, cc = place_of(c.get("location") or c.get("country") or "", registry)
        recs.append(
            {
                "kind": "candidate",
                "city": city,
                "cc": cc or str(c.get("country") or "")[:2].upper(),
                "when": c.get("detected_on") or c.get("first_seen") or "",
                "sources": [c.get("source_id"), *list(c.get("source_ids") or [])],
                "name": c.get("name", ""),
                "raw_loc": c.get("location", ""),
            }
        )
    for e in records(inputs.signals):
        city, cc = place_of(e.get("location") or e.get("country") or "", registry)
        recs.append(
            {
                "kind": "company",
                "city": city,
                "cc": cc,
                "when": e.get("discovery_date") or "",
                "sources": [e.get("source_id")],
                "name": e.get("company", ""),
                "raw_loc": e.get("location", ""),
            }
        )
    for p in records(inputs.people, ("id",)):
        city, cc = place_of(p.get("location") or p.get("country") or "", registry)
        recs.append(
            {
                "kind": "person",
                "city": city,
                "cc": cc or str(p.get("country") or "")[:2].upper(),
                "when": p.get("last_observed") or p.get("created") or "",
                "sources": [s.get("source_id") for s in p.get("sources") or []],
                "name": p.get("name", ""),
                "raw_loc": p.get("location", ""),
            }
        )
    try:
        for e in [] if inputs.events is None else inputs.events:
            city, cc = place_of(e.get("city") or "", registry)
            recs.append(
                {
                    "kind": "event",
                    "city": city,
                    "cc": cc,
                    "when": e.get("start") or "",
                    "sources": [
                        str(s.get("source_id") or s.get("source") or "")
                        for s in (e.get("sources") or [])
                        if isinstance(s, dict)
                    ]
                    + [e.get("source") or ""],
                    "name": e.get("name", ""),
                    "raw_loc": e.get("city", ""),
                }
            )
    except Exception:
        pass
    return recs


def family_state(
    eco: dict[str, Any], fam: str, sources: list[dict[str, Any]], recs: list[dict[str, Any]], today: date
) -> dict[str, Any]:
    """Coverage state of ONE family for ONE ecosystem from configured sources + recorded runs + records actually seen there."""
    cc = eco["country"]
    city_k = _fold(eco["city"])
    conf = [
        s
        for s in sources
        if fam in s["families"]
        and s["enabled"]
        and (s["countries"] is None or (cc and cc in s["countries"]) or any(_fold(c) == city_k for c in s["cities"]))
    ]
    if not conf:
        return {
            "state": "GAP",
            "why": "no configured source covers this family for %s" % (eco["country_name"] or eco["city"]),
            "sources": [],
        }
    run = [s for s in conf if s["last_scan"] or s["last_ok"]]
    if not run:
        return {"state": "UNKNOWN", "why": f"{len(conf)} source(s) configured, none run yet", "sources": conf}
    ok = [s for s in run if s["retrieved"]]
    fresh = [s for s in ok if s["last_ok_days"] is not None and s["last_ok_days"] <= FRESH_DAYS]
    src_ids = {s["id"] for s in conf}
    seen = [
        r
        for r in recs
        if ((r["city"] and _fold(r["city"]) == city_k) or (not r["city"] and cc and r["cc"] == cc))
        and any(x in src_ids for x in r["sources"] if x)
        and (_days_ago(r["when"], today) is None or _days_ago(r["when"], today) <= PRODUCTIVE_DAYS)  # type: ignore[operator]
    ]
    city_specific = [s for s in fresh if any(_fold(c) == city_k for c in s["cities"]) and s["productive"]]
    if fresh and (seen or city_specific):
        return {
            "state": "HEALTHY",
            "why": f"{len(fresh)} fresh retrieval(s); {len(seen) + len(city_specific)} record(s) from {eco['city']} in {PRODUCTIVE_DAYS} days",
            "sources": conf,
        }
    if ok:
        why = (
            ("retrieval succeeded but produced no record from {} (zero useful records ≠ coverage)".format(eco["city"]))
            if fresh
            else f"last successful retrieval is stale (> {FRESH_DAYS} days)"
        )
        return {"state": "PARTIAL", "why": why, "sources": conf}
    return {"state": "PARTIAL", "why": "configured, every recorded retrieval failed", "sources": conf}


def candidates_for(eco: dict[str, Any], fam: str, cands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cc = eco["country"]
    city_k = _fold(eco["city"])
    return [
        c
        for c in cands
        if fam in c["families"]
        and not c.get("adopted")
        and ((c["city"] and _fold(c["city"]) == city_k) or (not c["city"] and cc and c["country"] == cc))
    ]


def ecosystem_report(
    eco: dict[str, Any],
    sources: list[dict[str, Any]],
    recs: list[dict[str, Any]],
    today: date,
    cands: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    fams: dict[str, dict[str, Any]] = {}
    cands = cands if cands is not None else []
    for fid, _lab in FAMILIES:
        fams[fid] = family_state(eco, fid, sources, recs, today)
        fams[fid]["candidates"] = [
            {
                "id": c["id"],
                "name": c["name"],
                "url": c["url"],
                "access_mode": c["access_mode"],
                "access_limitations": c["access_limitations"],
                "source_type": c["source_type"],
                "status": c["status"],
            }
            for c in candidates_for(eco, fid, cands)
        ]
    states = [f["state"] for f in fams.values()]
    healthy = states.count("HEALTHY")
    partial = states.count("PARTIAL")
    gap = states.count("GAP")
    unknown = states.count("UNKNOWN")
    overall = (
        "HEALTHY"
        if healthy == len(FAMILIES)
        else (
            "PARTIAL"
            if healthy or partial
            else ("UNKNOWN" if unknown and gap != len(FAMILIES) and unknown >= gap else "GAP")
        )
    )
    city_k = _fold(eco["city"])
    findings = [r for r in recs if r["city"] and _fold(r["city"]) == city_k]
    n = len(findings)
    if n == 0:
        label = catalog.LABEL_ZERO_HEALTHY if overall == "HEALTHY" else catalog.LABEL_ZERO_INSUFFICIENT
    else:
        label = f"{n} FINDING{'' if n == 1 else 'S'} — COVERAGE {overall}"
    missing = [lab for fid, lab in FAMILIES if fams[fid]["state"] in ("GAP", "UNKNOWN")]
    covered = [lab for fid, lab in FAMILIES if fams[fid]["state"] == "HEALTHY"]
    last_ok = max([s["last_ok"] for f in fams.values() for s in f["sources"] if s.get("last_ok")] or [""])
    return {
        **{k: eco[k] for k in ("id", "city", "country", "country_name", "region")},
        "overall": overall,
        "label": label,
        "findings": n,
        "families": {
            fid: {
                "state": f["state"],
                "why": f["why"],
                "configured": len(f["sources"]),
                "retrieved": sum(1 for s in f["sources"] if s["retrieved"]),
                "productive": sum(1 for s in f["sources"] if s["productive"]),
                "sources": [
                    {
                        "id": s["id"],
                        "name": s["name"],
                        "origin": s["origin"],
                        "retrieved": s["retrieved"],
                        "productive": s["productive"],
                        "last_ok": s["last_ok"],
                        "failing": s["failing"],
                        "declared_by": s["declared_by"],
                    }
                    for s in f["sources"]
                ],
                "candidates": f["candidates"],
            }
            for fid, f in fams.items()
        },
        "candidate_watchers": sum(len(f["candidates"]) for f in fams.values()),
        "healthy": healthy,
        "partial": partial,
        "gap": gap,
        "unknown": unknown,
        "families_covered": covered,
        "families_missing": missing,
        "last_successful_retrieval": last_ok,
    }


def new_ecosystem_candidates(recs: list[dict[str, Any]], registry: Registry) -> list[dict[str, Any]]:
    """Repeated credible signals from a place NOT in the registry → NEW ECOSYSTEM — COVERAGE REVIEW (never auto-registered)."""
    known = {_fold(r["city"]) for r in registry} | {_fold(a) for r in registry for a in r["aliases"]}
    buckets: dict[str, dict[str, Any]] = {}
    for r in recs:
        if r["city"]:
            continue  # matched a registered ecosystem
        loc = str(r.get("raw_loc") or "").strip()
        head = re.split(r"[,/·|(]", loc)[0].strip() if loc else ""
        if (
            not head
            or _fold(head) in known
            or len(_fold(head)) < 3
            or _fold(head) in ("unknown", "remote", "europe", "eu", "n a")
        ):
            continue
        if _fold(head) in _ALIASES and len(_ALIASES[_fold(head)]) == 2:
            continue  # a bare country name is not a city signal
        b = buckets.setdefault(
            _fold(head), {"place": head, "country": r["cc"], "signals": 0, "kinds": set(), "names": []}
        )
        b["signals"] += 1
        b["kinds"].add(r["kind"])
        if r["name"] and r["name"] not in b["names"]:
            b["names"].append(r["name"])
    out = [
        {
            "label": catalog.LABEL_NEW,
            "place": b["place"],
            "country": b["country"],
            "signals": b["signals"],
            "kinds": sorted(b["kinds"]),
            "examples": b["names"][:5],
            "action": "review: add to coverage_registry.json (city, country) if this is a real ecosystem — nothing is registered automatically",
        }
        for b in buckets.values()
        if len(set(b["names"])) >= catalog.NEW_ECOSYSTEM_MIN
    ]
    return sorted(out, key=lambda x: -x["signals"])


def audit_matrix(audit_files: tuple[tuple[str, str], ...]) -> dict[str, Any]:
    """The Chief Scout audit's own coverage matrix (docs/coverage/*.md, table with 'Current status'), keyed by country code — shown as the
    audit's OPINION next to the evidence-based state, never used to compute it. ``audit_files``: (name, text), sorted by name."""
    out: dict[str, Any] = {}
    for fn, text in audit_files:
        if not fn.endswith(".md"):
            continue
        lines = text.splitlines()
        hdr = None
        for ln in lines:
            if ln.startswith("|") and "Ecosystem" in ln and "Current status" in ln:
                hdr = [h.strip() for h in ln.strip("|").split("|")]
                continue
            if hdr and ln.startswith("|") and not ln.startswith("|---"):
                cells = [c.strip() for c in ln.strip("|").split("|")]
                if len(cells) != len(hdr):
                    continue
                row = dict(zip(hdr, cells, strict=False))
                cc = row.get("Country", "").upper().replace("UK", "GB")
                if cc:
                    out[cc] = {
                        "status": row.get("Current status", ""),
                        "ecosystem": row.get("Ecosystem", ""),
                        "blind_spot": row.get("Biggest blind spot", ""),
                        "source": fn,
                        "families": {
                            k: v
                            for k, v in row.items()
                            if k not in ("Ecosystem", "Country", "Current status", "Biggest blind spot")
                        },
                    }
    return out


def coverage_view(inputs: CoverageInputs, now: datetime) -> dict[str, Any]:
    """The old ``report()`` (``GET /api/coverage``) at the request clock ``now``."""
    today = berlin_now(now).date()
    registry = ecosystems(inputs)
    sources = declared_sources(inputs, registry, today)
    recs = records_by_place(inputs, registry)
    cands = candidate_sources(inputs)
    am = audit_matrix(inputs.audit_files)
    ecos = [ecosystem_report(e, sources, recs, today, cands) for e in registry]
    for e in ecos:
        e["audit"] = am.get(e["country"], {})
    ecos.sort(key=lambda e: (e["country_name"], e["city"]))
    counts = {s: sum(1 for e in ecos if e["overall"] == s) for s in STATES}
    return {
        "generated": berlin_now(now).strftime("%Y-%m-%d %H:%M"),
        "families": FAMILIES,
        "states": STATES,
        "ecosystems": ecos,
        "counts": counts,
        "sources_declared": len(sources),
        "sources_with_override": sum(1 for s in sources if s["declared_by"] == "coverage_sources.json"),
        "new_ecosystems": new_ecosystem_candidates(recs, registry),
        "registry_size": len(registry),
        "candidates": {
            "total": len(cands),
            "adopted": sum(1 for c in cands if c.get("adopted")),
            "origins": sorted(
                {"{} {}".format(c["origin"].get("registry_id"), c["origin"].get("version")) for c in cands}
            ),
            "by_country": {
                k: sum(1 for c in cands if c["country"] == k) for k in sorted({c["country"] for c in cands})
            },
            "rows": cands,
            "note": "Grok coverage audit candidates — declared with their access mode and limitations; a candidate never counts as coverage until Mohamed adopts it (one explicit click per source) and a scan actually retrieves productive records.",
        },
        "note": "Coverage describes what Project Zero can see, never ecosystem quality. A successful retrieval with zero useful records is PARTIAL, not HEALTHY. "
        "Extend ecosystems in coverage_registry.json; declare or correct source coverage per source id in coverage_sources.json (Grok coverage audit target).",
        "labels": {
            "zero_healthy": catalog.LABEL_ZERO_HEALTHY,
            "zero_insufficient": catalog.LABEL_ZERO_INSUFFICIENT,
            "new": catalog.LABEL_NEW,
        },
    }

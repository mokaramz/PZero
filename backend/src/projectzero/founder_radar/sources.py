"""The old ``domain/founder_radar/sources.py`` (rev 6c739b9), the read side, ported line for line (review 026a):
``source_coverage``, ``geo_options``, ``next_batch`` and ``region_health``. Read only (decision a): the regions,
sources and cursor documents are parameters, and a missing / empty / malformed regions or sources document reads as
the built-in defaults IN MEMORY, never written back (the old ``load_regions`` / ``load_sources`` wrote them). The
loaders are Ecosystems' ports (``ecosystems/coverage.py``: ``load_regions``, ``load_sources``, ``city_sources``);
the defaults are ``ecosystems/catalog.py``'s."""

from __future__ import annotations

import re
from typing import Any

from projectzero.ecosystems.coverage import city_sources as _city_sources
from projectzero.ecosystems.coverage import load_regions as load_regions
from projectzero.ecosystems.coverage import load_sources as load_sources
from projectzero.founder_radar.catalog import BATCH_SIZE, SOURCE_ROLE
from projectzero.founder_radar.names import _fold

__all__ = ["city_sources", "geo_options", "load_regions", "load_sources", "next_batch", "region_health"]


def load_cursor(doc: Any) -> dict[str, Any]:
    """The old ``store.load_cursor``: tolerant, ``{"next": 0, "batches_completed": 0}`` when missing / not an object."""
    return doc if isinstance(doc, dict) else {"next": 0, "batches_completed": 0}


def city_sources(regions_doc: Any) -> list[dict[str, Any]]:
    """One bounded GitHub source per registry city."""
    return _city_sources(load_regions(regions_doc))


def next_batch(regions_doc: Any, cursor_doc: Any, size: int = BATCH_SIZE) -> tuple[list[dict[str, Any]], int]:
    """Rotating window over the city sources (the cursor itself is written by the scan, review 026b)."""
    cs = city_sources(regions_doc)
    if not cs:
        return [], 0
    cur = load_cursor(cursor_doc)
    start = cur.get("next", 0) % len(cs)
    batch = [cs[(start + i) % len(cs)] for i in range(min(size, len(cs)))]
    return batch, start


def source_coverage(health: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Live discovery · enrichment · manual/authorized · configuration required · failed · not attempted."""
    groups: dict[str, list[dict[str, Any]]] = {
        "live discovery": [],
        "enrichment": [],
        "manual / authorized": [],
        "configuration required": [],
        "failed": [],
        "not attempted": [],
    }
    for r in health.get("sources", []):
        role = SOURCE_ROLE.get(
            r.get("kind") if r.get("kind") in ("github_users", "openalex_works", "pz_data") else r.get("id"), ""
        )
        entry = {
            "name": r["name"],
            "role": role,
            "status": r["status"],
            "note": r.get("note", ""),
            "last_ok": r.get("last_ok", ""),
        }
        if r["status"] == "failed":
            groups["failed"].append(entry)
        elif r["status"] == "config_required":
            groups["manual / authorized" if r.get("id") in ("linkedin", "boardy") else "configuration required"].append(
                entry
            )
        elif r.get("id") == "apollo":
            groups["enrichment"].append(entry)
        else:
            groups["live discovery"].append(entry)
    for rg in health.get("regions", []):
        for c in rg["cities"]:
            if not c["attempted"]:
                groups["not attempted"].append(
                    {
                        "name": "GitHub — {} ({})".format(c["city"], rg["region"]),
                        "role": SOURCE_ROLE["github_users"],
                        "status": c["status"],
                        "note": c["next"],
                        "last_ok": c.get("last_ok", ""),
                    }
                )
    return groups


def geo_options(people_rows: list[dict[str, Any]], health: dict[str, Any], regions_doc: Any) -> dict[str, Any]:
    """Complete European coverage registry as filter options with counts and last-scan status — zero-result
    countries stay visible."""
    regs = load_regions(regions_doc)
    rh = {c["source_id"]: c for r in health.get("regions", []) for c in r["cities"]}
    out: dict[str, Any] = {"regions": [], "countries": {}, "cities": []}
    for r in regs:
        cities = []
        for city, cc in r["cities"]:
            sid = "gh-" + re.sub(r"[^a-z0-9]+", "-", _fold(city))
            st = rh.get(sid, {})
            n = sum(
                1
                for p in people_rows
                if _fold(p.get("location", "")).startswith(_fold(city))
                or (p.get("region") == r["region"] and _fold(city) in _fold(p.get("location", "")))
            )
            cities.append(
                {
                    "city": city,
                    "country": cc,
                    "people": n,
                    "status": st.get("status", "not attempted yet"),
                    "last_attempt": st.get("last_attempt", ""),
                    "last_ok": st.get("last_ok", ""),
                }
            )
            out["countries"].setdefault(
                cc, {"country": cc, "region": r["region"], "people": 0, "cities": 0, "attempted": 0}
            )
            out["countries"][cc]["cities"] += 1
            out["countries"][cc]["attempted"] += 1 if st.get("attempted") or st.get("last_ok") else 0
        out["regions"].append(
            {
                "region": r["region"],
                "people": sum(1 for p in people_rows if p.get("region") == r["region"]),
                "cities": cities,
            }
        )
        out["cities"] += cities
    for p in people_rows:
        cc = p.get("country")
        if cc in out["countries"]:
            out["countries"][cc]["people"] += 1
    out["countries"] = sorted(out["countries"].values(), key=lambda x: x["country"])
    return out


def region_health(
    rows_by_id: dict[str, Any], prev_regions: list[Any], regions_doc: Any, cursor_doc: Any
) -> list[dict[str, Any]]:
    """Per-region / per-city status: attempted this scan, success/failure, last success, and whether it waits for a
    later batch. A city that was not attempted is never reported as scanned."""
    cs = city_sources(regions_doc)
    cur = load_cursor(cursor_doc)
    n = len(cs)
    nxt = cur.get("next", 0) % n if n else 0
    order = {c["id"]: (i - nxt) % n for i, c in enumerate(cs)}
    prevc = {c.get("source_id"): c for r in prev_regions for c in r.get("cities", []) if c.get("source_id")}
    out = []
    for r in load_regions(regions_doc):
        cities = []
        for city, cc in r["cities"]:
            sid = "gh-" + re.sub(r"[^a-z0-9]+", "-", _fold(city))
            row = rows_by_id.get(sid)
            pc = prevc.get(sid, {})
            if row and row["status"] == "not attempted — rate limited":
                st = {
                    "status": row["status"],
                    "attempted": False,
                    "last_attempt": pc.get("last_attempt", ""),
                    "last_ok": pc.get("last_ok", ""),
                    "raw": 0,
                    "note": row["note"],
                }
            elif row:
                st = {
                    "status": row["status"],
                    "attempted": True,
                    "last_attempt": row.get("attempted_at", ""),
                    "last_ok": row.get("last_ok", ""),
                    "raw": row["raw"],
                    "note": row["note"],
                }
            else:
                st = {
                    "status": "not attempted this scan",
                    "attempted": False,
                    "last_attempt": pc.get("last_attempt", ""),
                    "last_ok": pc.get("last_ok", ""),
                    "raw": 0,
                    "note": "",
                }
            pos = order.get(sid, 0)
            st["next"] = "next scan" if pos < BATCH_SIZE else "in %d scan(s)" % (pos // BATCH_SIZE + 1)  # noqa: UP031
            cities.append({"city": city, "country": cc, "source_id": sid, **st})
        att = [c for c in cities if c["attempted"]]
        out.append(
            {
                "region": r["region"],
                "cities": cities,
                "attempted": len(att),
                "ok": sum(1 for c in att if c["status"] == "ok"),
                "failed": sum(1 for c in att if c["status"] == "failed"),
                "ever_ok": sum(1 for c in cities if c["last_ok"]),
                "coverage_note": (
                    "covered in this scan" if att else "not attempted this scan — waits for a later batch"
                ),
            }
        )
    return out

"""The event-source collectors (review 017): the old ``domain/connectors.py`` ``_uid`` / ``_lead`` / ``_ics_events`` /
``_fetch_ics`` / ``_walk_json`` / ``_fetch_luma`` / ``_fetch_devpost`` / ``_date_only`` / ``_Text`` / ``_lines`` /
``_fetch_watch_page`` and ``domain/event_sources.py`` ``parse_jsonld_events`` / ``_collect`` (rev 6c739b9), ported
VERBATIM apart from:

* **the network**: every fetch goes through a ``Fetcher`` (``get_text(url) -> str``); production uses
  ``core.net`` (pinned, verified TLS, no insecure fallback), tests and the oracle a recorded one;
* **the clock**: one Berlin ``now`` per scan (``detected_on``, ``retrieved_at``, the watcher's past-date filter);
* **the watcher baseline**: passed in and returned (``WatchResult.lines``) instead of a ``.watch/`` file written
  BEFORE the leads were computed; the scan stores it only after a successful fetch, so a failed fetch keeps the last
  good baseline (Codex H-113).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any, Protocol

from projectzero.events.engine import GAZETTEER
from projectzero.events.when import BERLIN, extract_date


class Fetcher(Protocol):
    def get_text(self, url: str) -> str: ...


def uid(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def stamp(now: datetime) -> str:
    return now.astimezone(BERLIN).strftime("%Y-%m-%d %H:%M")


def lead(
    title: str,
    source: str,
    url: str,
    city: str,
    etype: str,
    date_iso: str,
    confidence: str,
    today: date,
    note: str = "",
) -> dict[str, Any]:
    return {
        "id": uid("evlead", source, title, date_iso),
        "title": title[:160],
        "source": source,
        "url": url,
        "city": city or "",
        "type": etype,
        "date": date_iso,
        "confidence": confidence,
        "detected_on": today.isoformat(),
        "decision": "new",
        "note": note,
    }


# ── ICS ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def ics_events(text: str) -> list[tuple[str, str, str, str]]:
    """Minimal ICS parser: (summary, dtstart_iso, location, url)."""
    out: list[dict[str, str]] = []
    cur: dict[str, str] | None = None
    for raw in text.replace("\r\n ", "").replace("\r", "").split("\n"):
        line = raw.strip()
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT" and cur is not None:
            out.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            k, v = line.split(":", 1)
            k = k.split(";")[0].upper()
            if k in ("SUMMARY", "LOCATION", "URL", "DTSTART"):
                cur[k] = v.strip()
    res = []
    for e in out:
        dt = e.get("DTSTART", "")
        iso = f"{dt[0:4]}-{dt[4:6]}-{dt[6:8]}" if len(dt) >= 8 and dt[:8].isdigit() else ""
        res.append((e.get("SUMMARY", ""), iso, e.get("LOCATION", ""), e.get("URL", "")))
    return res


def fetch_ics(src: dict[str, Any], fetcher: Fetcher, today: date) -> list[dict[str, Any]]:
    leads = []
    for name, iso, loc, url in ics_events(fetcher.get_text(src["url"])):
        if not name:
            continue
        city = src.get("city") or next((c for c in GAZETTEER if c.lower() in (loc or "").lower()), "")
        leads.append(
            lead(
                name,
                src["name"] + " (ICS)",
                url or src["url"],
                city,
                src.get("type", "founder_meetup"),
                iso,
                "VERIFIED" if iso else "LIKELY",
                today,
            )
        )
    return leads


# ── Luma (secondary route) ──────────────────────────────────────────────────────────────────────────────────────
def walk_json(o: Any, hits: list[dict[str, Any]], depth: int = 0) -> None:
    if depth > 8 or len(hits) > 120:
        return
    if isinstance(o, dict):
        keys = set(o.keys())
        if "name" in keys and ("start_at" in keys or "start_date" in keys or "startAt" in keys):
            hits.append(o)
        for v in o.values():
            walk_json(v, hits, depth + 1)
    elif isinstance(o, list):
        for v in o:
            walk_json(v, hits, depth + 1)


def fetch_luma(src: dict[str, Any], fetcher: Fetcher, today: date) -> list[dict[str, Any]]:
    """Luma city pages embed event data in a JSON <script>. Parse defensively; layout can change."""
    html = fetcher.get_text(src["url"])
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("no embedded JSON (page layout changed)")
    hits: list[dict[str, Any]] = []
    walk_json(json.loads(m.group(1)), hits)
    leads, seen = [], set()
    for h in hits:
        name = str(h.get("name", ""))[:160]
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        iso = str(h.get("start_at") or h.get("start_date") or h.get("startAt") or "")[:10]
        url = (
            "https://lu.ma/" + str(h.get("url") or h.get("api_id") or "").lstrip("/")
            if (h.get("url") or h.get("api_id"))
            else src["url"]
        )
        ld = lead(
            name,
            src["name"],
            url,
            src.get("city", ""),
            src.get("type", "founder_meetup"),
            iso,
            "VERIFIED" if len(iso) == 10 else "LIKELY",
            today,
        )
        desc = h.get("description_mirror") or h.get("description") or h.get("description_md") or h.get("summary") or ""
        if isinstance(desc, dict):
            desc = desc.get("text") or desc.get("plain") or ""
        if desc:
            ld["description"] = re.sub(r"\s+", " ", str(desc))[:1200]
        if h.get("audience"):
            ld["audience"] = str(h.get("audience"))[:300]
        leads.append(ld)
    if not leads:
        raise ValueError("embedded JSON had no events")
    return leads


# ── Devpost API ─────────────────────────────────────────────────────────────────────────────────────────────────
def fetch_devpost(src: dict[str, Any], fetcher: Fetcher, today: date) -> list[dict[str, Any]]:
    data = json.loads(fetcher.get_text(src["url"]))
    leads = []
    for h in (data.get("hackathons") or [])[:40]:
        name = h.get("title", "")
        loc = (
            (h.get("displayed_location") or {}).get("location", "")
            if isinstance(h.get("displayed_location"), dict)
            else str(h.get("displayed_location") or "")
        )
        city = next((c for c in GAZETTEER if c.lower() in loc.lower()), "")
        iso = extract_date(str(h.get("submission_period_dates", "")), today=today)
        leads.append(
            lead(
                name,
                "Devpost (API)",
                h.get("url", src["url"]),
                city,
                "hackathon",
                iso,
                "VERIFIED" if iso else "LIKELY",
                today,
                note=loc,
            )
        )
    if not leads:
        raise ValueError("API returned no hackathons")
    return leads


# ── page watcher ────────────────────────────────────────────────────────────────────────────────────────────────
EV_WORD = re.compile(
    r"hackathon|meetup|pitch|demo\s?day|summit|conference|night|weekend|bootcamp|workshop|founder|startup|entrepreneur",
    re.I,
)
EV_STRONG = re.compile(
    r"hackathon|demo\s?day|pitch\s?(night|event|day)|summit|bootcamp|meetup|founders?\s(night|event|meetup|dinner)",
    re.I,
)
_DATE_NOISE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|mon|tue|wed|thu|fri|sat|sun)[a-zäöüé]*\.?|\b(am|pm)\b", re.I
)


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.skip = 0
        self.out: list[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("script", "style", "noscript", "nav", "footer", "header"):
            self.skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "nav", "footer", "header") and self.skip:
            self.skip -= 1

    def handle_data(self, d: str) -> None:
        if not self.skip:
            d = re.sub(r"\s+", " ", d).strip()
            if d:
                self.out.append(d)


def lines(html: str, dedupe: bool = True) -> list[str]:
    p = _Text()
    with contextlib.suppress(Exception):
        p.feed(html)
    seen, out = set(), []
    for ln in p.out:
        if 5 <= len(ln) <= 240 and (ln not in seen or not dedupe):
            seen.add(ln)
            out.append(ln)
    return out


def date_only(ln: str, today: date) -> bool:
    """A short line that is just a date / time range: no words left once month, weekday and AM/PM are removed."""
    return (
        len(ln) <= 80
        and bool(extract_date(ln, today=today))
        and not re.search(r"[^\W\d_]{3,}", _DATE_NOISE.sub(" ", ln))
    )


@dataclass
class WatchResult:
    leads: list[dict[str, Any]]
    first: bool
    lines: list[str]  # the new baseline (stored by the scan only after this succeeded)


def fetch_watch_page(src: dict[str, Any], fetcher: Fetcher, baseline: list[str] | None, today: date) -> WatchResult:
    """HTML watcher fallback. The FIRST run (no baseline) also surfaces current / future event lines as leads (NEEDS
    REVIEW); later runs surface only lines that are new since the baseline. An EMPTY saved baseline is a baseline."""
    new_lines = lines(fetcher.get_text(src["url"]))
    old = list(baseline or [])
    # an EMPTY saved baseline is a baseline (Codex H-113; the old ``first = not old`` re-flooded a page whose last
    # scan saw no lines); only a source with no saved baseline at all is a first scan
    first = baseline is None
    iso_today = today.isoformat()

    def not_historical(ln: str) -> str | None:
        iso = extract_date(ln, today=today)
        if iso and iso < iso_today:
            return None  # explicit past date -> never a lead
        if not iso:
            ym = re.search(r"\b(19\d\d|20\d\d)\b", ln)
            if ym and int(ym.group(1)) < today.year:
                return None  # bare past year -> never a lead
        return iso or ""

    paired, used = [], set()
    for i, ln in enumerate(new_lines[:-1]):
        nxt = new_lines[i + 1]
        if not extract_date(ln, today=today) and date_only(nxt, today):
            paired.append((ln, nxt))
            used.add(i)
    seen_old = set(old)
    pool: list[tuple[str, str]]
    if first:
        pool = [(t, d) for t, d in paired if not_historical(d) is not None]
        for i, ln in enumerate(new_lines):
            if i in used or not EV_WORD.search(ln):
                continue
            iso = not_historical(ln)
            if iso is None:
                continue
            if EV_STRONG.search(ln) or iso:
                pool.append((ln, ln))
    else:
        pool = [(t, d) for t, d in paired if t not in seen_old and not_historical(d) is not None]
        pool += [
            (ln, ln)
            for i, ln in enumerate(new_lines)
            if i not in used and ln not in seen_old and EV_WORD.search(ln) and not_historical(ln) is not None
        ]
    leads = []
    for ln, dl in pool[:25]:
        iso = extract_date(dl, today=today)
        leads.append(
            lead(
                " ".join(ln.split()[:14]),
                src["name"] + (" (first scan)" if first else ""),
                src["url"],
                src.get("city", ""),
                src.get("type", "community"),
                iso,
                "NEEDS REVIEW",
                today,
                note="Watcher text — open the source and confirm before planning around it.",
            )
        )
    return WatchResult(leads, first, new_lines)


# ── schema.org JSON-LD ──────────────────────────────────────────────────────────────────────────────────────────
_LD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)


def _walk(node: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(node, list):
        for x in node:
            _walk(x, out)
    elif isinstance(node, dict):
        t = node.get("@type")
        types = t if isinstance(t, list) else [t]
        if any(isinstance(x, str) and x.endswith("Event") for x in types):
            out.append(node)
        for k in ("@graph", "itemListElement", "item", "subEvent"):
            if k in node:
                _walk(node[k], out)


def _txt(v: Any) -> str:
    if isinstance(v, dict):
        return str(v.get("name") or v.get("@id") or "")
    if isinstance(v, list):
        return ", ".join(_txt(x) for x in v if _txt(x))
    return str(v or "")


def _place(ev: dict[str, Any]) -> tuple[str, str, str]:
    loc = ev.get("location")
    if isinstance(loc, list):
        loc = loc[0] if loc else None
    if not isinstance(loc, dict):
        return _txt(loc), "", ""
    addr = loc.get("address")
    city = ""
    if isinstance(addr, dict):
        city = addr.get("addressLocality") or ""
    elif isinstance(addr, str):
        city = addr.split(",")[-1].strip() if "," in addr else ""
    fmt = "virtual" if "Virtual" in str(loc.get("@type", "")) else ""
    return loc.get("name") or "", city, fmt


def parse_jsonld_events(html: str | None, src: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """schema.org Event objects from <script type=application/ld+json> (plain, arrays, @graph, ItemList)."""
    items = []
    for m in _LD.finditer(html or ""):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:  # the old parser: a broken block is skipped
            continue
        found: list[dict[str, Any]] = []
        _walk(data, found)
        for ev in found:
            name = _txt(ev.get("name")).strip()
            start = str(ev.get("startDate") or "")
            if not name or not start:
                continue
            venue, city, fmt = _place(ev)
            loc = ev.get("location")
            loc = loc[0] if isinstance(loc, list) and loc else loc
            addr = loc.get("address") if isinstance(loc, dict) else None
            street = (
                addr.get("streetAddress", "") if isinstance(addr, dict) else (addr if isinstance(addr, str) else "")
            )
            country = addr.get("addressCountry", "") if isinstance(addr, dict) else ""
            country = country.get("name", "") if isinstance(country, dict) else country
            off = ev.get("offers")
            off = off[0] if isinstance(off, list) and off else (off if isinstance(off, dict) else {})
            price = (
                {
                    "amount": off.get("price", ""),
                    "low": off.get("lowPrice", ""),
                    "high": off.get("highPrice", ""),
                    "currency": off.get("priceCurrency", ""),
                    "availability": str(off.get("availability", "")),
                    "url": off.get("url", ""),
                }
                if off
                else {}
            )
            mode = str(ev.get("eventAttendanceMode", ""))
            items.append(
                {
                    "title": name,
                    "date": start,
                    "end": str(ev.get("endDate") or ""),
                    "url": ev.get("url") or src["url"],
                    "registration_url": (off.get("url") if off else "") or "",
                    "venue": venue,
                    "city": city or src.get("city", ""),
                    "address": street,
                    "country": country,
                    "format": fmt
                    or (
                        "hybrid"
                        if "Mixed" in mode
                        else "virtual"
                        if "Online" in mode
                        else "physical"
                        if "Offline" in mode
                        else ""
                    ),
                    "organizer": _txt(ev.get("organizer")) or src.get("organizer") or "UNKNOWN",
                    "event_status": str(ev.get("eventStatus", "")),
                    "description": _txt(ev.get("description"))
                    if isinstance(ev.get("description"), (dict, list))
                    else str(ev.get("description") or ""),
                    "keywords": _txt(ev.get("keywords")),
                    "audience": _txt(ev.get("audience")),
                    "price": price,
                    "source": src["name"],
                    "source_id": src["id"],
                    "provenance": "json-ld",
                    "confidence": "high",
                    "retrieved_at": stamp(now),
                }
            )
    return items


# ── one source ──────────────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Collected:
    status: str  # ok | config_required (a raised exception is "failed", decided by the scan)
    items: list[dict[str, Any]]
    note: str
    route: str
    watch_lines: list[str] | None = None  # a watcher's new baseline


def _tag(
    leads: list[dict[str, Any]], src: dict[str, Any], provenance: str, confidence: str, now: datetime
) -> list[dict[str, Any]]:
    return [
        dict(
            {k: v for k, v in ld.items() if k != "type"},
            source_id=src["id"],
            provenance=provenance,
            confidence=confidence,
            organizer=src.get("organizer") or "UNKNOWN",
            retrieved_at=stamp(now),
        )
        for ld in leads
    ]


def collect(src: dict[str, Any], fetcher: Fetcher, now: datetime, baseline: list[str] | None) -> Collected:
    """The old ``_collect`` for one source. Raises on a failed fetch (the scan records it as ``failed``)."""
    today = now.astimezone(BERLIN).date()
    kind = src.get("kind")
    if kind == "optional" or (kind == "ics" and not src.get("url")):
        return Collected("config_required", [], src.get("requires_config") or "Requires configuration.", "")
    if kind == "ics":
        return Collected("ok", _tag(fetch_ics(src, fetcher, today), src, "ics", "high", now), "", "ics")
    if kind == "api":
        return Collected("ok", _tag(fetch_devpost(src, fetcher, today), src, "api", "high", now), "", "api")
    if kind in ("jsonld", "luma"):
        html = fetcher.get_text(src["url"])
        items = parse_jsonld_events(html, src, now)
        route = "json-ld"
        if not items and kind == "luma":  # secondary route only, never the sole assumption
            try:
                items = _tag(fetch_luma(src, fetcher, today), src, "luma-next-data", "medium", now)
                route = "luma-next-data"
            except Exception as e:  # the old code: the secondary route's failure is a note, not a failed source
                note = f"page fetched, no JSON-LD Event data; secondary route failed ({type(e).__name__})"
                return Collected("ok", [], note, "json-ld")
        if not items:
            return Collected("ok", [], "page fetched, but no schema.org Event data found — watch-only", route)
        return Collected("ok", items, "", route)
    if kind == "watcher":
        w = fetch_watch_page(src, fetcher, baseline, today)
        items = [
            dict(
                ld,
                id=ld.get("id")
                or ("lead-" + src["id"] + "-" + re.sub(r"[^a-z0-9]+", "-", str(ld.get("title", "")).lower())[:40]),
                source_id=src["id"],
                provenance="watcher",
                confidence="low",
            )
            for ld in w.leads
        ]
        return Collected("ok", items, "", "watcher", w.lines)
    return Collected("config_required", [], "unknown source kind", "")

# ruff: noqa: E501, RUF001
# (the old expressions, regexes and message templates are kept verbatim, long lines and typographic quotes included)
"""The News refresh run (review 028c, no model): the old ``services/news.py`` run (``_fetch_feed`` / ``_feed_item``,
``_fetch_one``, ``ingest``, ``_run_locked``, ``start_refresh`` / ``refresh_status``, ``_deterministic_card`` and the
card selection of ``_make_cards``) at revision 6c739b9, split into the three phases of the 026b pattern:

1. ``plan(inputs, today, now, run_id=...)`` -> ``FetchPlan``: the feeds (the 10 ``FEEDS`` plus the enabled extra
   feeds), the feeds still in their 429 cooldown (skipped, the old note), the allowed hosts. Reads only
   ``inputs.feeds_extra`` and ``inputs.feed_cooldown``.
2. ``fetch_all(plan, fetch)`` -> ``FetchResults``: every feed to fetch, in FEED order (sequential), through the ONE
   ``FeedFetch`` (``news.fetching``: the News policy on ``core.net``); per feed the parsed items (the old
   ``_fetch_feed``: junk after ``</rss>`` / ``</feed>`` cut, the guarded parse and its undeclared-entity repair
   (``news.xmlsafe``), at most 40 items, a bad item skipped) and the old ``_fetch_one`` outcome (``ok``, ``items``,
   ``seconds``, ``latest``, ``stale_days`` / ``error``, ``http``, ``rate_limited``). No transaction is open.
3. ``apply(inputs_current, results, today=..., now=..., run_id=...)`` -> ``RunOutcome``: over the CURRENT stored
   inputs (re-read by the caller under the News write lock, so a write committed during the fetch is part of what the
   run sees and keeps): the cooldown, the Swiss ticker items (the Deal Flow inbox, no fetch), the ingest (match in
   ``events`` key order, merge, syndication, the new-id rule with its collision suffix, the future-date clamp to
   ``today``), the old ``seed_cases`` (a no-op once the store seeded), the re-derivation pass over EVERY stored event
   (decision c), the deterministic ``rules`` cards (decision b), the source evaluation (``news.evaluate``) and the run
   record. Everything it would write is returned.

Mechanical changes only, besides the declared decisions:

* (a) / (f): the fetch is ``news.fetching`` (allowlisted hosts, every hop re-checked, no insecure TLS fallback: a
  certificate error is a failed feed with its reason; the project User-Agent);
* (b) no model: ``_make_cards`` selects as before and writes ``_deterministic_card`` for each (the old answer when
  the gateway refused): ``cards`` counts them, ``usd`` is 0.0;
* (d) the watch bridge is deferred (``WATCH_REASON``): ``watch_triggers`` is 0 (no watch targets in the data) and the
  reason is in ``RunOutcome.deferred``; the nominations are deferred inside the evaluation;
* (e) the run completes inside the request: the answer is the old ``{started: true, run_id, **refresh_status()}``
  computed AFTER the run (``job.running`` false, ``stage`` "done");
* (h) one Berlin clock: ``_pubdate`` reads a feed time in Europe/Berlin (the old code used the machine's zone);
  ``_pubts`` stays naive UTC; ``ts(now)`` is the old ``ledger.now_ts()``; the cooldown end and the run id are Berlin
  wall time;
* (i) the run id is the old ``news-YYYYmmdd-HHMMSS-<4 hex>`` with the 4 hex from the ``new_hex`` seam.

The elapsed times (``seconds``, ``timings``, ``duration_s``) are read from an injected ``clock`` (``time.monotonic``
in production) exactly where the old code read ``time.time()``.

What ``apply`` reads FRESH (``RunInputs``): from ``news`` the events document, ``runs_log`` (the evaluation's
technical rows, ``last_ok``), ``feed_cooldown``, ``cases`` (the old in-run ``seed_cases``), and the evaluation's inputs
(``disagreements_log``, ``source_state``, ``source_history_log``, ``feeds_extra``, ``outcomes_log``, ``sources``);
from ``validation`` the Deal Flow inbox (the known names and the Swiss ticker items), the Conviction records and the
Scout Intake items (the known names), and the whole Validation inputs for the entity build behind the Deal Flow
source-alpha row (over the events AFTER the run, as the old evaluation read them).
"""

from __future__ import annotations

import contextlib
import copy
import email.utils
import hashlib
import html
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urljoin

from projectzero.conviction.records import records
from projectzero.dealflow.triage import entity_repair
from projectzero.network.view import BERLIN, berlin_now
from projectzero.news import claims
from projectzero.news.catalog import CONCEPTS, COOLDOWN, FEEDS, RUN_STATE, SNAPSHOT, STATE
from projectzero.news.core import (
    JOB_KEYS,
    _concepts_for,
    _key,
    _relevant,
    _rows,
    classify,
    is_noise,
    load,
    materiality,
    seed_cases,
)
from projectzero.news.evaluate import EvalOutcome, evaluate
from projectzero.news.fetching import FeedFetch, allowed_hosts
from projectzero.news.inputs_model import NewsInputs
from projectzero.news.xmlsafe import feed_root
from projectzero.validation.core import entities as validation_entities
from projectzero.validation.core import ts
from projectzero.validation.inputs_model import ValidationInputs
from projectzero.validation.writes import NewHex

RATE_LIMIT_COOLDOWN_MIN = 30
STALE_FEED_DAYS = 14  # newest item older than this: the feed works but has stopped publishing
MAX_CARDS_PER_RUN = 12
MAX_ITEMS_PER_FEED = 40
COOLDOWN_NOTE = "asked us to slow down — paused politely, checked again later"
ALREADY_RUNNING = "A news refresh is already running."  # the old 409 answer's reason
WATCH_REASON = "watch triggers arrive with the Watch port"  # decision (d)

Clock = Callable[[], float]


# ------------------------------------------------------------------------------------------------ parsing helpers
def _pubts(s: str) -> str:
    """Full publication timestamp (UTC, ISO) when the feed gives one — for news-speed comparisons."""
    s = (s or "").strip()
    if not s:
        return ""
    try:
        dt = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.isoformat(timespec="minutes") if (dt.hour or dt.minute) else ""


def _pubdate(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    try:
        dt = email.utils.parsedate_to_datetime(s)
        # the operator's day: "23:30 -07:00" is already tomorrow in Europe (decision h: Europe/Berlin, pinned)
        return (dt.astimezone(BERLIN) if dt.tzinfo else dt).date().isoformat()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return (dt.astimezone(BERLIN) if dt.tzinfo else dt).date().isoformat()
    except ValueError:
        pass
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else ""


def _sha(*p: Any) -> str:
    return hashlib.sha1("|".join(str(x) for x in p).encode("utf-8")).hexdigest()[:12]


def _norm_text(s: str) -> str:
    return re.sub(r"\W+", " ", (s or "").lower()).strip()


def _strip(html_text: str) -> str:
    """The old ``connectors._strip``."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_text or "")).strip()


# --------------------------------------------------------------------------------------------------- ingestion
_COMMON = {
    "automate",
    "robotics",
    "startup",
    "venture",
    "capital",
    "energy",
    "health",
    "quantum",
    "europe",
    "german",
    "munich",
    "berlin",
    "paris",
    "london",
    "series",
    "funding",
    "labs",
    "group",
    "global",
    "digital",
    "systems",
}
# lower-case brand names ("finmid holt sich 17 Millionen Euro") before a funding verb
_LEAD_VERB_LC = re.compile(
    r"^([a-z][\w&.'-]{2,})\s+(?:raises|secures|bags|lands|gets|erhält|holt sich|holt|sichert sich|sammelt|lève)\b"
)
_LEAD_VERB = re.compile(
    r"^((?:[A-Z][\w&.'-]*|[A-Z]{2,})(?:\s+(?:[A-Z][\w&.'-]*|[A-Z]{2,})){0,3})\s+(?:signs|launches|unveils|acquires|"
    r"partners|expands|enters|opens|wins|secures|raises|bags|lands|closes|hits|passes|reaches|appoints|"
    r"hires|files|shuts|starts|teams|joins|gets|receives|completes|announces|erhält|holt|sichert|sammelt|"
    r"übernimmt|lève|rachète)\b"
)


def known_names(validation: ValidationInputs) -> dict[str, str]:
    """Companies Project Zero already holds (inbox, Conviction, Scout Intake): matching them is the point of News."""
    names: dict[str, str] = {}
    pool = [c.get("name") for c in records(validation.inbox) if not entity_repair.broken_name_reason(c)]
    pool += [e.get("company") for e in records(validation.signals)]
    pool += [it.get("entity_name") for it in validation.scout_items or []]
    for n in pool:
        n = (n or "").strip()
        if len(n) < 4 or n.lower() in _COMMON or (" " not in n and len(n) < 5):
            continue
        names[n] = _key(n)
    return names


_ACQ = re.compile(r"^.+?\s+(?:acquires|buys|has acquired|snaps up|übernimmt|kauft|rachète|acquiert)\s+(.+)$")
# "the Berlin startup Kontext", "robotics startup Torqan", "Münchner Startup Gripwerk" → strip the descriptor
_ACQ_LEAD = re.compile(r"^(?:the\s+)?(?:[\w-]+\s+){0,2}?(?:startup|start-up|scale-up|company|firm)\s+", re.I)
_CAPS = re.compile(r"^([A-Z0-9][\w&.'’-]*(?:\s+[A-Z0-9][\w&.'’-]*){0,3})")


def _known_patterns(known: dict[str, str]) -> list[tuple[str, re.Pattern[str]]]:
    """The old per-name-set cache, without the cache: longest names first (a stable sort)."""
    names = sorted(known, key=len, reverse=True)
    return [(n, re.compile(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])")) for n in names]


def _company(headline: str, summary: str, patterns: list[tuple[str, re.Pattern[str]]] | None = None) -> tuple[str, str]:
    for n, rx in patterns or []:  # a company PZ knows, named exactly in the headline (longest first)
        if rx.search(headline):
            return n, "known to Project Zero"
    p = re.match(
        r"^(.+?)\s+(?:is\s+|has been\s+|gets\s+)?(?:acquired|bought|übernommen)\s+(?:by|von)\s", headline.strip()
    )
    if p:
        c = _CAPS.match(_ACQ_LEAD.sub("", p.group(1)))
        if c and c.group(1).lower() not in _COMMON and len(c.group(1)) >= 3:
            return c.group(1), "headline (acquired company)"
    m = _ACQ.match(headline.strip())
    if m:  # "Siemens acquires Gripwerk": the startup story is about the company being acquired, not the buyer
        c = _CAPS.match(_ACQ_LEAD.sub("", m.group(1).strip()))
        target = re.split(r"\s+(?:For|In|To|From|With|Zu|Für|Pour|Dans)\b", c.group(1))[0].strip(" .,'’") if c else ""
        if target and target.lower() not in _COMMON and len(target) >= 3:
            return target, "headline (acquired company)"
    name = entity_repair.extract_company(headline)
    if name and name != "UNKNOWN":
        return name, "headline"
    ents = entity_repair.extract_entities({"name": headline, "description": summary[:600]}, limit=1)
    if ents:
        return ents[0]["name"], "article text"
    m = _LEAD_VERB.match(headline.strip()) or _LEAD_VERB_LC.match(headline.strip())
    if m and m.group(1).lower() not in _COMMON and len(m.group(1)) >= 3:
        return m.group(1), "headline"
    return "", ""


_ATOM = "{http://www.w3.org/2005/Atom}"


def parse_feed(xml: str, f: dict[str, Any]) -> list[dict[str, Any]]:
    """The old ``_fetch_feed`` after its ``connectors._get``: the junk cut, the GUARDED parse and its repair, at most
    40 items, a malformed item skipped."""
    for end in ("</rss>", "</feed>"):  # some feeds append junk after the document (ad / tracking markup)
        if end in xml:
            xml = xml[: xml.rindex(end) + len(end)]
            break
    root = feed_root(xml)
    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    out = []
    for it in items[:MAX_ITEMS_PER_FEED]:
        try:
            row = _feed_item(it, f)
        except Exception:  # one malformed item never kills the feed
            continue
        if row:
            out.append(row)
    return out


def _feed_item(it: Any, f: dict[str, Any]) -> dict[str, Any] | None:
    """One RSS 2.0 / Atom item → article. Relative links resolve against the feed; Atom ``published`` wins over
    ``updated`` (an edit never re-dates an article); a permalink GUID stands in for a missing link."""
    title = html.unescape(_strip(it.findtext("title") or it.findtext(_ATOM + "title") or "")).strip()
    link = (it.findtext("link") or "").strip()
    if not link:
        ln = next((x for x in it.findall(_ATOM + "link") if x.get("rel") in (None, "alternate")), None)
        link = (ln.get("href") or "").strip() if ln is not None else ""
    if not link:
        guid = (it.findtext("guid") or "").strip()
        link = guid if guid.startswith(("http://", "https://")) else ""
    link = urljoin(f["url"], link) if link else ""
    desc = html.unescape(
        _strip(it.findtext("description") or it.findtext(_ATOM + "summary") or it.findtext(_ATOM + "content") or "")
    )
    raw_pub = it.findtext("pubDate") or it.findtext(_ATOM + "published") or it.findtext(_ATOM + "updated") or ""
    if not (title and link.startswith(("http://", "https://"))):
        return None
    return {
        "headline": title,
        "summary": desc[:700],
        "url": link,
        "published": _pubdate(raw_pub),
        "published_ts": _pubts(raw_pub),
        "publisher": f["name"],
        "feed_geo": f.get("geo", "EU"),
        "probation": bool(f.get("probation")),
    }


def swiss_items(validation: ValidationInputs) -> list[dict[str, Any]]:
    """Reuse what the Deal Flow scan already collected from startupticker.ch (no second fetch)."""
    out = []
    for c in records(validation.inbox, ("id",)):
        if "startupticker" not in str(c.get("source") or "").lower():
            continue
        title = (
            c.get("raw_title") if c.get("raw_title") and not re.match(r"^\d", c["raw_title"]) else c.get("description")
        )
        if not title or re.match(r"^\W*\d{1,2}\.\d{1,2}\.\d{4}", title):
            continue
        out.append(
            {
                "headline": title[:220],
                "summary": "",
                "url": c.get("source_url") or "",
                "published": str(c.get("first_seen") or "")[:10],
                "publisher": "startupticker.ch",
                "feed_geo": "CH",
                "company_hint": c.get("name"),
            }
        )
    return out


def _independence(item: dict[str, Any], company: str) -> str:
    pc = claims.classify(item.get("url") or "", company)["publisher_class"]
    return "primary" if pc in ("company", "state", "registry", "program") else "independent"


def ingest(
    d: dict[str, Any], items: list[dict[str, Any]], *, today: date, now: datetime, known: dict[str, str]
) -> dict[str, int]:
    """The old ``ingest`` over the document ``d`` (modified IN PLACE: the caller passes its own copy) and the run's
    ``items`` (their ``published`` clamped in place, as before); returns the counters."""
    ev = d["events"]
    new = merged = skipped = material_new = noise_new = reclassified = 0
    patterns = _known_patterns(known)
    for it in items:
        if not it.get("published") or it["published"] > today.isoformat():
            it["published"] = today.isoformat()
        cls = classify(it["headline"], it.get("summary", ""))
        company, how = _company(it["headline"], it.get("summary", ""), patterns)
        if (
            not company
            and it.get("company_hint")
            and it["company_hint"] != "UNKNOWN"
            and not entity_repair.broken_name_reason({"name": it["company_hint"]})
        ):  # never a headline / date as a company
            company, how = it["company_hint"], "Deal Flow scan"
        geo = cls["geo"] or [it.get("feed_geo", "EU")]
        ck = _key(company)
        src = {
            "publisher": it["publisher"],
            "url": it["url"],
            "published": it["published"],
            "headline": it["headline"],
            "text_sha": _sha(_norm_text(it["headline"])),
            "independence": _independence(it, company),
        }
        if it.get("published_ts"):
            src["published_ts"] = it["published_ts"]
        if it.get("probation"):
            src["probation"] = True  # from a PROBATION publication (Adaptive Source Network): limited trust
        # same event = same company + same event type within 10 days (or the very same URL)
        match = None
        for eid, e in ev.items():
            if any(s["url"] == it["url"] for s in e["sources"]):
                match = eid
                break
            near = abs((date.fromisoformat(e["event_date"]) - date.fromisoformat(it["published"])).days) <= 10
            if ck and e["entity_key"] == ck and e["event_type"] == cls["event_type"] and near:
                match = eid
                break
            if near and not e.get("curated") and any(s["text_sha"] == src["text_sha"] for s in e["sources"]):
                match = eid  # the same headline on another site within 10 days: a syndicated copy, not a new event
                break
        if match:
            e = ev[match]
            if any(s["url"] == it["url"] for s in e["sources"]):
                skipped += 1
                continue
            if any(s["text_sha"] == src["text_sha"] for s in e["sources"]):
                src["independence"] = "syndicated"  # the same text elsewhere is not independent confirmation
            e["sources"].append(src)
            e["event_date"] = min(e["event_date"], it["published"])
            e["amount_m"] = e.get("amount_m") or cls["amount_m"]
            merged += 1
            continue
        eid = "nw-" + _sha(ck or it["headline"], cls["event_type"], it["published"][:7])
        n = 2
        while eid in ev:  # e.g. a second round of the same company in the same month: never overwrite an event
            eid = "nw-" + _sha(ck or it["headline"], cls["event_type"], it["published"][:7], n)
            n += 1
        e = {
            "event_id": eid,
            "company": company,
            "entity_key": ck,
            "company_from": how,
            "headline": it["headline"],
            "summary": it.get("summary", ""),
            "event_type": cls["event_type"],
            "round": cls["round"],
            "amount_m": cls["amount_m"],
            "event_date": it["published"],
            "geo": geo,
            "themes": cls["themes"],
            "noise": cls["noise"],
            "sources": [src],
            "ingested_at": ts(now),
            "backcast": [],
            "card": None,
        }
        e["materiality"], e["materiality_why"] = materiality(e)
        ev[e["event_id"]] = e
        new += 1
        if e["materiality"] in ("HIGH", "MEDIUM") and not e["noise"]:
            material_new += 1
        else:
            noise_new += 1
    return {
        "new": new,
        "merged": merged,
        "duplicates_skipped": skipped,
        "material_new": material_new,
        "noise_new": noise_new,
        "reclassified": reclassified,
    }


def rederive(d: dict[str, Any], known: dict[str, str]) -> int:
    """The old re-derivation pass at the end of ``ingest`` (decision c): over EVERY stored event, with the CURRENT
    rules (noise, an ``other`` type re-typed, a missing company filled, a broken one cleared; materiality for all,
    curated included). Modifies ``d`` in place; returns ``reclassified``."""
    reclassified = 0
    patterns = _known_patterns(known)
    for e in d[
        "events"
    ].values():  # re-derive with the CURRENT rules (sidecar = derived: rule fixes apply to stored events too)
        before = (e.get("noise"), e.get("event_type"), e.get("company"), e.get("materiality"))
        if not e.get("curated"):
            e["noise"] = is_noise(e["headline"])
            if e["event_type"] == "other":  # an unclassified story may be classified by improved rules (never re-typed)
                cls = classify(e["headline"], e.get("summary", ""))
                if cls["event_type"] != "other":
                    e.update(
                        event_type=cls["event_type"], round=cls["round"], amount_m=e.get("amount_m") or cls["amount_m"]
                    )
            if not e.get("company") and not e["noise"]:
                comp, how = _company(e["headline"], e.get("summary", ""), patterns)
                if comp and not entity_repair.broken_name_reason({"name": comp}):
                    e["company"], e["entity_key"], e["company_from"] = comp, _key(comp), how
            if e.get("company") and entity_repair.broken_name_reason({"name": e["company"]}):
                e["company"], e["entity_key"], e["company_from"] = "", "", ""
        e["materiality"], e["materiality_why"] = materiality(e)
        if before != (e.get("noise"), e.get("event_type"), e.get("company"), e.get("materiality")):
            reclassified += 1
    return reclassified


# ---------------------------------------------------------------------------------------------------- cards
def _deterministic_card(e: dict[str, Any]) -> dict[str, Any]:
    t = e["event_type"]
    why = {
        "valuation": "A valuation milestone shows how much investors now pay for this market — a benchmark for similar companies.",
        "acquisition": "It shows who values this technology and how the market consolidates.",
        "shutdown": "Failures show which assumptions broke — useful when judging similar companies.",
        "funding": "Investors committed money: a signal about the market and the stage the company has reached.",
        "customer": "A customer or contract is evidence that someone values the product enough to commit.",
        "regulatory": "Regulatory approval removes a major barrier to selling.",
        "grant": "Public money is an early, non-dilutive validation of the technology.",
        "accelerator": "Selection by a programme is an early public filter on the team.",
    }.get(t, "Context for the market Project Zero watches.")
    concept: str | None = (_concepts_for(e) or [None])[0]  # type: ignore[list-item]
    return {
        "what_happened": (e.get("summary") or e["headline"])[:400],
        "why_it_matters": why,
        "the_company": "",
        "vc_lesson": CONCEPTS[concept]["text"] if concept else "",
        "watch_next": [],
        "generated_by": "rules",
    }


def card_todo(d: dict[str, Any]) -> list[dict[str, Any]]:
    """The old ``_make_cards`` selection: no card or a ``rules`` card, HIGH / MEDIUM, relevant; HIGH first, then
    newest; at most ``MAX_CARDS_PER_RUN``."""
    return sorted(
        (
            e
            for e in d["events"].values()
            if (not e.get("card") or (e["card"] or {}).get("generated_by") == "rules")
            and e["materiality"] in ("HIGH", "MEDIUM")
            and _relevant(e)
        ),
        key=lambda e: (e["materiality"] != "HIGH", -date.fromisoformat(e["event_date"]).toordinal()),
        reverse=False,
    )[:MAX_CARDS_PER_RUN]


def make_cards(d: dict[str, Any]) -> tuple[int, float]:
    """Decision (b): ``_make_cards`` without the model: every selected story gets the deterministic card (the old
    answer when the gateway refused), set in place on ``d``. Returns ``(made, usd)``."""
    todo = card_todo(d)
    cards = [(e["event_id"], _deterministic_card(e)) for e in todo]  # each from the document as it was loaded
    for eid, card in cards:
        if eid in d["events"]:
            d["events"][eid]["card"] = card
    return len(todo), round(0.0, 6)


# ------------------------------------------------------------------------------------------------------ the run
def new_run_id(now: datetime, new_hex: NewHex) -> str:
    """The old ``new_run_id``: Berlin wall time, the 4 hex from the seam (decision i)."""
    return "news-" + berlin_now(now).strftime("%Y%m%d-%H%M%S-") + new_hex()[:4]


def active_extra_feeds(inputs: NewsInputs) -> list[dict[str, Any]]:
    """The old ``news_sources.active_extra_feeds``: probation / trusted publications that are enabled."""
    return [
        {"name": f["name"], "url": f["feed_url"], "geo": f.get("geo", "EU"), "probation": f.get("state") == "PROBATION"}
        for f in (inputs.feeds_extra or {}).get("feeds") or []
        if f.get("enabled", True) and f.get("state") in ("PROBATION", "TRUSTED", "DEGRADED")
    ]


@dataclass(frozen=True)
class FetchPlan:
    run_id: str
    trigger: str
    today: date
    started_at: str  # ``ts(now)``: the run record's ``at`` / ``started_at`` and the cooldown comparison time
    feeds: tuple[dict[str, Any], ...]  # FEEDS + the active extra feeds, in order
    todo: tuple[dict[str, Any], ...]  # the feeds to fetch, in feed order
    waiting: tuple[tuple[str, str], ...]  # (name, until) of the feeds in their cooldown, in feed order
    hosts: frozenset[str]  # the allowed hosts (decision a)
    t0: float  # ``clock()`` at the start (the old ``t0 = time.time()``)


@dataclass(frozen=True)
class FeedResult:
    feed: dict[str, Any]
    items: tuple[dict[str, Any], ...]
    res: dict[str, Any]  # the old ``_fetch_one`` outcome


@dataclass(frozen=True)
class FetchResults:
    plan: FetchPlan
    feeds: tuple[FeedResult, ...]  # in ``plan.todo`` order


@dataclass(frozen=True)
class RunInputs:
    """The CURRENT stored inputs ``apply`` runs against (re-read under the News write lock, after ``ensure_seeded``)."""

    news: NewsInputs
    validation: ValidationInputs = field(default_factory=ValidationInputs)


@dataclass(frozen=True)
class EventChange:
    event_id: str
    record: dict[str, Any]  # the stored record after the run (its key order)
    passes: tuple[str, ...]  # the passes that changed it, in order: ingest | seed | rederive | card
    # each pass's RESULTING record, in ``passes`` order (Codex H-261: the history keeps every intermediate state; the
    # last one equals ``record``)
    states: tuple[tuple[str, dict[str, Any]], ...] = ()


@dataclass(frozen=True)
class RunOutcome:
    run_id: str
    record: dict[str, Any]  # the run record (the old ``_JOB.last``, insertion order)
    run_line: str  # the exact old ``news/runs.jsonl`` line (sorted keys), without its line end
    new_events: tuple[EventChange, ...]  # appended at the end of the archive order, in this order
    changed_events: tuple[EventChange, ...]  # stored events the run changed, in document order
    events_doc: dict[str, Any]  # the whole events document after the run
    rest: dict[str, Any] | None  # the document's other top-level keys when the in-run seeding changed them
    documents: dict[str, Any]  # path -> body, in the old save order; the store writes the ones that changed
    appends: tuple[
        tuple[str, str], ...
    ]  # (log, line) in the old order: disagreements / source_log / source_history, then runs
    evaluation: EvalOutcome | None
    answer: dict[str, Any]  # the old ``POST /api/news_refresh`` answer after the run
    deferred: tuple[str, ...] = (WATCH_REASON,)


def plan(
    inputs: NewsInputs,
    today: date,
    now: datetime,
    *,
    run_id: str,
    trigger: str = "manual",
    clock: Clock = time.monotonic,
) -> FetchPlan:
    """Phase 1: the feeds and the cooldowns (the old ``_run_locked`` up to the fetch)."""
    t0 = clock()
    extra = active_extra_feeds(inputs)
    feeds = FEEDS + extra
    now_s = ts(now)
    cool = inputs.feed_cooldown or {}
    waiting = [f for f in feeds if (cool.get(f["name"]) or "") > now_s]  # a publisher that asked us to slow down
    todo = [f for f in feeds if f not in waiting]
    return FetchPlan(
        run_id=run_id,
        trigger=trigger,
        today=today,
        started_at=now_s,
        feeds=tuple(copy.deepcopy(feeds)),
        todo=tuple(copy.deepcopy(todo)),
        waiting=tuple((f["name"], cool[f["name"]]) for f in waiting),
        hosts=allowed_hosts(extra),
        t0=t0,
    )


def fetch_one(f: dict[str, Any], fetch: FeedFetch, p: FetchPlan) -> FeedResult:
    """The old ``_fetch_one`` through ``fetch`` (never raises)."""
    t0 = fetch.clock()
    try:
        got = parse_feed(fetch.get(f["url"], p.hosts), f)
        latest = max((it.get("published_ts") or it.get("published") or "" for it in got), default="")
        res: dict[str, Any] = {"ok": True, "items": len(got), "seconds": round(fetch.clock() - t0, 1), "latest": latest}
        try:  # fetched fine but publishing nothing new: a stale feed (editorial stop / moved feed)
            age = (p.today - date.fromisoformat(latest[:10])).days if latest else None
        except ValueError:
            age = None
        if not got or (age is not None and age >= STALE_FEED_DAYS):
            res["stale_days"] = age
        return FeedResult(f, tuple(got), res)
    except Exception as e:  # one failing feed never stops the others (or the app)
        msg = f"{type(e).__name__}: {str(e)[:100]}"
        code = re.search(r"HTTP Error (\d{3})", msg)
        return FeedResult(
            f,
            (),
            {
                "ok": False,
                "error": msg,
                "http": int(code.group(1)) if code else None,
                "rate_limited": bool(code and code.group(1) == "429"),
                "seconds": round(fetch.clock() - t0, 1),
            },
        )


def fetch_all(p: FetchPlan, fetch: FeedFetch) -> FetchResults:
    """Phase 2: every feed of ``p.todo`` in feed order, through ``fetch`` only (no store, no transaction)."""
    return FetchResults(p, tuple(fetch_one(f, fetch, p) for f in p.todo))


def _text(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def _roundtrip(v: Any) -> Any:
    return json.loads(json.dumps(v, ensure_ascii=False))  # the old ``_save`` then ``load``


def refresh_status(runs_log: str, job: dict[str, Any], events_total: int) -> dict[str, Any]:
    """The old ``refresh_status()`` after the run: the job's keys (``running`` false), ``last`` / ``last_ok`` from the
    runs log (a line without ``status`` counts as ok)."""
    runs = _rows(runs_log)
    out = {k: job.get(k) for k in JOB_KEYS}
    out["running"] = False
    ok = [r for r in runs if r.get("status", "ok") in ("ok", "partial")]
    return {
        "job": out,
        "last": runs[-1] if runs else None,
        "last_ok": ok[-1] if ok else None,
        "events_total": events_total,
    }


def apply(
    inputs_current: RunInputs,
    results: FetchResults,
    *,
    today: date,
    now: datetime,
    run_id: str,
    clock: Clock = time.monotonic,
) -> RunOutcome:
    """Phase 3, pure: the old ``_run_locked`` from the fetched results on, against the CURRENT inputs. Returns every
    write (module docstring); ``inputs_current`` is never modified."""
    p = results.plan
    if run_id != p.run_id:
        raise ValueError("the run id is not the plan's")
    news, validation = inputs_current.news, inputs_current.validation
    at = ts(now)
    feeds = list(p.feeds)
    rec: dict[str, Any] = {
        "run_id": run_id,
        "at": p.started_at,
        "started_at": p.started_at,
        "trigger": p.trigger,
        "sources_ok": 0,
        "sources_failed": [],
        "items": 0,
        "per_feed": {},
        "timings": {},
    }
    job: dict[str, Any] = {
        "running": True,
        "run_id": run_id,
        "trigger": p.trigger,
        "started_at": rec["started_at"],
        "stage": "fetching",
        "feeds_total": len(feeds),
        "feeds_done": 0,
        "ingested": False,
    }
    documents: dict[str, Any] = {}
    items: list[dict[str, Any]] = []
    if feeds:
        cool = copy.deepcopy(news.feed_cooldown or {})
        now_s = p.started_at
        for name, until in p.waiting:
            rec["per_feed"][name] = {"ok": None, "cooldown_until": until, "note": COOLDOWN_NOTE}
        for r in results.feeds:  # feed order, not completion order: deterministic ingest
            f, got, res = r.feed, [dict(it) for it in r.items], dict(r.res)
            items += got
            rec["per_feed"][f["name"]] = res
            if res["ok"]:
                rec["sources_ok"] += 1
                cool.pop(f["name"], None)
            else:
                rec["sources_failed"].append(f"{f['name']}: {res['error']}")
                if res.get("rate_limited"):
                    until = (
                        berlin_now(now).replace(tzinfo=None) + timedelta(minutes=RATE_LIMIT_COOLDOWN_MIN)
                    ).isoformat(timespec="seconds")
                    cool[f["name"]] = res["cooldown_until"] = until
        job["feeds_done"] = len(p.waiting) + len(results.feeds)
        rec["cooldown"] = sorted(name for name, _until in p.waiting)
        documents[COOLDOWN] = {k: v for k, v in cool.items() if v > now_s}
    rec["timings"]["fetch_s"] = round(clock() - p.t0, 1)
    try:
        swiss = swiss_items(validation)
        items += swiss
        rec["per_feed"]["startupticker.ch"] = {"ok": True, "items": len(swiss), "reused": "Deal Flow scan (no fetch)"}
    except Exception as e:
        rec["per_feed"]["startupticker.ch"] = {"ok": False, "error": f"{type(e).__name__}", "reused": "Deal Flow scan"}
    rec["items"] = len(items)
    job["stage"] = "ingesting"
    t1 = clock()
    # the ingest, the in-run seeding and the re-derivation, each pass traced (decision c: every change recorded)
    before_doc = load(news.events)
    stored = {eid: _text(e) for eid, e in before_doc["events"].items()}
    d = copy.deepcopy(before_doc)
    known = known_names(validation)
    counters = ingest(d, items, today=today, now=now, known=known)
    passes: dict[str, list[str]] = {}
    states: dict[str, list[tuple[str, dict[str, Any]]]] = {}

    def trace(name: str, before: dict[str, str], after: dict[str, Any]) -> None:
        for eid, e in after["events"].items():
            if eid not in before or before[eid] != _text(e):
                passes.setdefault(eid, []).append(name)
                states.setdefault(eid, []).append((name, json.loads(_text(e))))  # this pass's resulting record

    trace("ingest", stored, d)
    snap = {eid: _text(e) for eid, e in d["events"].items()}
    counters["reclassified"] = rederive(d, known)
    trace("rederive", snap, d)
    d = _roundtrip(d)  # the old ``_save(d)``; the in-run ``seed_cases()`` then reads it back
    rec.update(counters)
    snap = {eid: _text(e) for eid, e in d["events"].items()}
    rest_before = _text({k: v for k, v in d.items() if k != "events"})
    d, rec["seeded"] = seed_cases(d, news.cases, now)
    d = copy.deepcopy(d)
    trace("seed", snap, d)
    rest_after = {k: v for k, v in d.items() if k != "events"}
    rec["events_total"] = len(d["events"])
    rec["timings"]["ingest_s"] = round(clock() - t1, 2)
    job.update(stage="watch", ingested=True, new=rec["new"], merged=rec["merged"])
    rec["watch_triggers"] = 0  # decision (d): the watch bridge is deferred (WATCH_REASON)
    job["stage"] = "cards"
    t2 = clock()
    snap = {eid: _text(e) for eid, e in d["events"].items()}
    rec["cards"], rec["usd"] = make_cards(d)
    d = _roundtrip(d)
    trace("card", snap, d)
    rec["timings"]["cards_s"] = round(clock() - t2, 1)
    job["stage"] = "metrics"
    t3 = clock()
    evaluation: EvalOutcome | None = None
    try:  # refresh news-source observations (deterministic, cheap) over the events AFTER the run
        evaluation = evaluate(evaluation_inputs(news, validation, d, today), today=today, now=now)
        ev = evaluation.result
        rec["source_eval"] = {
            k: ev.get(k) for k in ("benchmark_events", "new_disagreements", "lifecycle_changes", "nominated")
        }
    except Exception:  # the old ``log.exception``: the run continues without the evaluation
        evaluation = None
    rec["timings"]["metrics_s"] = round(clock() - t3, 1)
    latest = [v.get("latest") for v in rec["per_feed"].values() if v.get("latest")]
    rec["latest_published"] = max(latest) if latest else ""
    rec["feeds_checked"] = len(feeds)
    rec["stale_feeds"] = sorted(n for n, v in rec["per_feed"].items() if "stale_days" in v)
    fetched = len(feeds) - len(rec.get("cooldown") or [])
    rec["status"] = "failed" if fetched and rec["sources_ok"] == 0 else "partial" if rec["sources_failed"] else "ok"
    rec["completed_at"] = at
    rec["duration_s"] = round(clock() - p.t0, 1)
    run_line = json.dumps(rec, ensure_ascii=False, sort_keys=True)
    job.update(running=False, stage="done")
    if evaluation is not None:
        documents.update(evaluation.documents)
    documents[RUN_STATE] = {"running": False}
    appends = [*(evaluation.appends if evaluation is not None else ()), ("runs", run_line)]
    runs_after = news.runs_log + run_line + "\n"
    answer = {"started": True, "run_id": run_id, **refresh_status(runs_after, job, len(d["events"]))}
    new_events = tuple(
        EventChange(eid, d["events"][eid], tuple(passes[eid]), tuple(states[eid]))
        for eid in d["events"]
        if eid not in stored
    )
    changed = tuple(
        EventChange(eid, d["events"][eid], tuple(passes[eid]), tuple(states[eid]))
        for eid in d["events"]
        if eid in stored and eid in passes
    )
    return RunOutcome(
        run_id=run_id,
        record=_roundtrip(rec),
        run_line=run_line,
        new_events=new_events,
        changed_events=changed,
        events_doc=d,
        rest=rest_after if _text(rest_after) != rest_before else None,
        documents=documents,
        appends=tuple(appends),
        evaluation=evaluation,
        answer=_roundtrip(answer),
    )


def evaluation_inputs(news: NewsInputs, validation: ValidationInputs, doc: Any, today: date) -> NewsInputs:
    """The evaluation's inputs over the events document ``doc``: the Deal Flow source-alpha row from the Validation
    entities built over THAT document (the old ``_deal_flow_alpha`` called ``validation.entities(today)`` after the
    run's writes)."""
    from projectzero.news.inputs_model import with_entities

    v = replace(validation, news=doc, news_inputs=replace(validation.news_inputs or news, events=doc))
    base = replace(news, events=doc)
    ents: dict[str, Any] = {}
    with contextlib.suppress(Exception):  # the old ``_deal_flow_alpha`` ``try``: no alpha row
        ents = validation_entities(v, today)
        return with_entities(base, ents, v)
    return replace(base, source_alpha=None)


def remeasure(inputs: RunInputs, *, today: date, now: datetime, record_history: bool = False) -> EvalOutcome:
    """``Re-measure now`` (old ``POST /api/news_sources_evaluate``): the evaluation alone over the CURRENT inputs."""
    return evaluate(
        evaluation_inputs(inputs.news, inputs.validation, inputs.news.events, today),
        today=today,
        now=now,
        record_history=record_history,
    )


__all__ = [
    "ALREADY_RUNNING",
    "COOLDOWN",
    "SNAPSHOT",
    "STATE",
    "WATCH_REASON",
    "EventChange",
    "FeedResult",
    "FetchPlan",
    "FetchResults",
    "RunInputs",
    "RunOutcome",
    "apply",
    "fetch_all",
    "new_run_id",
    "plan",
    "remeasure",
]

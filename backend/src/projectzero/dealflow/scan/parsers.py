# ruff: noqa
# mypy: ignore-errors
# (protected scanning rules, copied by script from the old modules; see the header. The cut code is the old untyped
# code verbatim, so it is exempt from lint and type checks, like a vendored module.)
"""The Deal Flow scan's parsers (review 034a), cut MECHANICALLY from the old ``domain/connectors.py`` at
revision 6c739b9 by exact top-level line ranges (``scripts/gen_scan_catalog.py``); nothing is retyped. See the
script's header for the cut list and the declared replacements (the clock, the user agent, the lazy imports).

Pure over fetched bytes: every request goes through ``seams`` (``core/net`` with the run's transport and resolver),
every page-watcher baseline comes from the run's phase-1 read, and nothing here touches the database. The cursor of a
structured source (``src["hwm"]``) and the baseline of a watcher are advanced on the source COPY the run hands in;
the run decides what is kept (``dealflow/scan/run.py``).
"""

# fmt: off
import contextlib
import hashlib
import html as _html
import json
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

from projectzero.dealflow.scan import seams, taste
from projectzero.dealflow.scan import sources_v2 as _sv2  # Deal Flow V2 Phase 2 official sources

# ── hand-written seams (NOT cut): what the old module reached outside itself ───────────────────────────────────────
def _snap_path(name):
    """The old ``<data>/.watch/<name>``: here the baseline's key (``<uid(url)>.json``), resolved by the run."""
    return name


def _get_raw(url):
    """The network call behind :func:`_get`: ``core/net`` (SSRF guard, pinned addresses, verified TLS: decision e drops
    the old insecure-TLS retry) with the old browser headers and the old per-request timeout."""
    return seams.get_raw(url, _net_timeout())


def _request_json(url, data=None, headers=None):
    """JSON API call for the structured parsers (not counted in the per-source page telemetry, like v1)."""
    return seams.request_json(url, data, {"User-Agent": UA, **(headers or {})}, _net_timeout())


def _load_snapshot(path):
    return seams.load_snapshot(path)


def _save_snapshot(path, lines):
    seams.save_snapshot(path, lines)


# ── cut from domain/connectors.py ──
TIMEOUT = int(os.environ.get("PZ_TIMEOUT", 20))

UA = seams.USER_AGENT

_TL = threading.local()

def _set_deadline(ts):
    _TL.deadline = ts

def _remaining():
    dl = getattr(_TL, "deadline", None)
    return None if dl is None else dl - time.time()

def _expired():
    r = _remaining()
    return r is not None and r <= 0

def _net_timeout():
    r = _remaining()
    if r is None:
        return TIMEOUT
    if r <= 0:
        raise TimeoutError("source deadline reached")
    return max(1, min(TIMEOUT, int(r) + 1))

FEED_KEYWORDS = [
    "pre-seed",
    "preseed",
    "seed",
    "raises",
    "secures",
    "closes",
    "sammelt",
    "finanzierung",
    "spin-off",
    "spinout",
    "founded",
]

NOISE = [
    "holding",
    "immobilien",
    "real estate",
    "consulting",
    "beratung",
    "verwaltung",
    "gastro",
    "restaurant",
    "friseur",
    "praxis",
    "physio",
    "handel ",
    "beteiligung",
    "invest ag",
]

def _uid(*parts):
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]

_FETCH_TL = threading.local()

class FetchFailure(Exception):
    """A parser attempted fetches but retrieved nothing (every request failed) — the source is NOT healthy."""

def _fetch_reset():
    _FETCH_TL.stats = {"attempts": 0, "ok": 0, "failed": 0, "errors": []}

def _fetch_stats():
    st = getattr(_FETCH_TL, "stats", None)
    if st is None:
        _fetch_reset()
        st = _FETCH_TL.stats
    return st

def _fetch_note(ok, err=""):
    st = _fetch_stats()
    st["attempts"] += 1
    if ok:
        st["ok"] += 1
    else:
        st["failed"] += 1
        st["errors"] = (st["errors"] + [err])[-3:]

def _get(url):
    """Every network fetch of the scanning engine passes through here — success/failure is counted per thread."""
    try:
        body = _get_raw(url)
    except Exception as e:
        _fetch_note(False, f"{type(e).__name__}: {str(e)[:90]}")
        raise
    _fetch_note(True)
    return body

AMBIGUOUS_KW = {
    "chemical",
    "chemicals",
    "packaging",
    "procurement",
    "credit",
    "financing",
    "financial",
    "finance",
    "insurance",
    "banking",
    "payments",
    "compliance",
    "logistics",
    "industrial",
    "manufacturing",
    "materials",
    "software",
    "platform",
    "infrastructure",
    "automation",
    "energy",
    "mobility",
    "healthcare",
    "pharma",
    "commerce",
    "retail",
    "construction",
    "agriculture",
    "security",
    "enterprise",
    "operations",
    "maintenance",
}

def strong_archetypes(text):
    """Stricter than taste.tag_archetypes (which stays untouched): word-boundary matching, and an
    archetype is assigned only on (a) a multi-word phrase hit, (b) a DISTINCTIVE single keyword
    (>=8 chars and not a broad industry word), or (c) two independent keyword hits. A lone broad
    word like "chemical" or "procurement" never tags."""
    t = " " + (text or "").lower() + " "
    out = []
    for aid, name, _test, kws in taste.ARCHETYPES:
        hits = [k for k in kws if re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", t)]
        strong_single = any((" " in k) or (len(k) >= 8 and k not in AMBIGUOUS_KW) for k in hits)
        if strong_single or len(hits) >= 2:
            out.append((len(hits), aid, name))
    return [(aid, name, n) for n, aid, name in sorted(out, reverse=True)[:3]]

def make(name, source, tier, url, dt, location, description, country, date_kind):
    text = name + " " + description
    arche = strong_archetypes(text)
    twins = taste.suggest_twins(text)
    noisy = any(n in (" " + text.lower() + " ") for n in NOISE)
    why = []
    if arche:
        why.append("Archetype keyword match: " + "; ".join(f"#{a} {n}" for a, n, _ in arche))
    if tier == "pre_company":
        why.append("Pre-company channel — this is where the sourcing edge is")
    if tier == "announcement":
        why.append("Announcement feed — discovery only; probably recently funded")
    if twins:
        why.append("Possible portfolio twin(s): " + ", ".join(t[0] for t in twins) + " → run conflict check")
    if noisy:
        why.append("⚠ Looks like holding/consulting/services — likely noise")
    return {
        "id": _uid(source, name),
        "name": name[:120],
        "source": source,
        "discovery_tier": tier,
        "source_url": url,
        "date": dt,
        "date_kind": date_kind,
        "detected_on": seams.today().isoformat(),
        "location": location,
        "country": country,
        "description": description[:600],
        "why": why,
        "archetype_hits": [a for a, _, _ in arche],
        "twins": [t[0] for t in twins],
        "noise": noisy,
        "decision": "rejected" if noisy else "new",
        "notes": "auto-rejected: looks like noise — bring back if wrong" if noisy else "",
        "priority": (3 if tier == "pre_company" else 1) + 2 * len(arche) + (1 if twins else 0) - (10 if noisy else 0),
    }

_HEADLINE_LABELS = re.compile(
    r"^\s*(exclusive|breaking|interview|podcast|analysis|opinion|update|watch|meet|report)\s*[:\u2014\-–]\s*", re.I
)

_CITY_BASED = re.compile(r"^\s*[A-ZÀ-Ž][\w.\-]*(?:\s[A-ZÀ-Ž][\w.\-]*)?[\-\u2011]based\s+", re.I)

_COUNTRY_POSS = re.compile(r"^\s*[A-ZÀ-Ž][\w]*(?:\s[A-Z][\w]*)?[\u2019']s\s+")

_FUNDING_VERBS = r"(?:raises?|raised|secures?|secured|closes?|closed|lands?|bags?|nabs?|gets?|receives?|announces?|launches?|sammelt|erh[äa]lt|sichert(?:\s+sich)?|schlie[ßs]s?t)"

_NAME_TOKEN = r"[A-ZÀ-Ž0-9][\w&.\u2019'\-]*"

_NAME_RUN = _NAME_TOKEN + r"(?:\s+" + _NAME_TOKEN + r"){0,3}"

_NAME_STOP = {
    "exclusive",
    "breaking",
    "interview",
    "podcast",
    "analysis",
    "opinion",
    "startupnews",
    "startbase",
    "week",
    "weekly",
    "roundup",
    "review",
    "the",
    "this",
    "how",
    "why",
    "what",
    "meet",
    "inside",
    "from",
    "sweden",
    "germany",
    "deutschland",
    "switzerland",
    "schweiz",
    "france",
    "austria",
    "denmark",
    "norway",
    "finland",
    "netherlands",
    "belgium",
    "spain",
    "italy",
    "poland",
    "estonia",
    "europe",
    "eu",
    "munich",
    "münchen",
    "berlin",
    "hamburg",
    "zurich",
    "zürich",
    "geneva",
    "genf",
    "vienna",
    "wien",
    "stockholm",
    "copenhagen",
    "helsinki",
    "oslo",
    "amsterdam",
    "paris",
    "london",
    "madrid",
    "milan",
    "startup",
    "startups",
    "start-up",
    "start-ups",
    "report",
    "state",
    "top",
    "these",
    "here",
    "agtech",
    "fintech",
    "biotech",
    "medtech",
    "deeptech",
    "insurtech",
    "proptech",
    "healthtech",
    "cleantech",
    "climatetech",
    "regtech",
    "spacetech",
    "foodtech",
    "edtech",
    "saas",
    "company",
    "firm",
    "dutch",
    "german",
    "french",
    "swiss",
    "austrian",
    "british",
    "irish",
    "swedish",
    "danish",
    "norwegian",
    "finnish",
    "belgian",
    "spanish",
    "italian",
    "portuguese",
    "polish",
    "czech",
    "estonian",
    "european",
    "american",
    "canadian",
}

def _valid_company(name):
    if not name:
        return False
    toks = name.strip().split()
    if not toks or len(toks) > 4:
        return False
    low = name.strip().lower()
    if low in _NAME_STOP or (toks[0].lower() in _NAME_STOP and len(toks) == 1):
        return False
    if all(t.lower() in _NAME_STOP for t in toks):
        return False
    return not (len(name.strip()) < 2 or (name.isupper() and len(name) > 12))

def extract_company(title):
    """Actual company name from a news headline — UNKNOWN when the evidence is not there.
    Never invents: label words, cities, countries and site names are rejected."""
    t = re.sub(r"\s+[|\u2013\u2014-]\s+[\w .]{3,30}$", "", (title or "").strip())  # strip trailing site suffix
    for _ in range(2):
        t = _HEADLINE_LABELS.sub("", t).strip()
    core = _CITY_BASED.sub("", t)
    core = _COUNTRY_POSS.sub("", core)
    core = re.sub(
        r"^(?:das\s+|the\s+)?(?:startup|start-?up|jungunternehmen|spin-?off|scale-?up)\s+", "", core, flags=re.I
    )
    # "Dutch AgTech Gravity Gardens secures..." -> nationality is stripped ONLY together with a sector
    # word (protects real names like "German Bionic"); a lone leading sector word is also stripped.
    _NATS = r"(?:dutch|german|french|swiss|austrian|british|uk|irish|swedish|danish|norwegian|finnish|belgian|spanish|italian|portuguese|polish|czech|estonian|latvian|lithuanian|european|us|american|canadian)"
    _SECT = r"(?:agtech|fintech|biotech|medtech|deeptech|insurtech|proptech|healthtech|cleantech|climatetech|regtech|spacetech|foodtech|edtech|adtech|legaltech|robotics|ai|saas|software|startup|scale-?up|company|firm)"
    core = re.sub(r"^" + _NATS + r"\s+" + _SECT + r"\s+(?=[A-ZÀ-Ž0-9])", "", core, flags=re.I)
    core = re.sub(r"^" + _SECT + r"\s+(?=[A-ZÀ-Ž][\w&.\u2019'\-]*\s)", "", core, flags=re.I)
    m = re.match(r"^(" + _NAME_RUN + r")\s+" + _FUNDING_VERBS + r"\b", core)
    if m and _valid_company(m.group(1)):
        return m.group(1).strip()
    m = re.search(
        r"\b(?:startup|start-up|jungunternehmen|spin-?off)\s+(" + _NAME_TOKEN + r"(?:\s+" + _NAME_TOKEN + r"){0,2})", t
    )
    if m and _valid_company(m.group(1)):
        return m.group(1).strip()
    m = re.match(r"^(" + _NAME_RUN + r")\s*:", core)
    if m and _valid_company(m.group(1)):
        return m.group(1).strip()
    m = re.match(r"^(" + _NAME_RUN + r")\b", core)
    if m and _valid_company(m.group(1)) and re.search(_FUNDING_VERBS, core, re.I):
        return m.group(1).strip()
    return "UNKNOWN"

def _strip(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()

def feed(f, days):
    xml = _get(f["url"])
    root = ET.fromstring(xml.encode("utf-8", errors="replace"))
    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    out = []
    for it in items:
        title = (it.findtext("title") or it.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if not link:
            ln = it.find("{http://www.w3.org/2005/Atom}link")
            link = ln.get("href") if ln is not None else ""
        desc = _strip(it.findtext("description") or it.findtext("{http://www.w3.org/2005/Atom}summary") or "")
        pub = (it.findtext("pubDate") or it.findtext("{http://www.w3.org/2005/Atom}updated") or "")[:31]
        text = (title + " " + desc).lower()
        if not any(k in text for k in FEED_KEYWORDS):
            continue
        name = extract_company(title)
        recovered = None
        if name == "UNKNOWN":  # the headline does not name the company — the summary often does (deterministic)
            from projectzero.dealflow.triage import entity_repair

            ents = entity_repair.extract_entities({"name": title, "description": desc[:600]}, limit=1)
            recovered = ents[0] if ents else None
        c = make(
            recovered["name"] if recovered else name,
            f["name"] + " (feed)",
            "announcement",
            link,
            pub,
            "Europe",
            title + " — " + desc[:300],
            "EU",
            "published",
        )
        if recovered:
            c["id"] = _uid(f["name"], title)  # same id as the UNKNOWN path → no duplicate of an earlier record
            c["raw_title"] = title
            c["name_method"] = "entity_repair: " + recovered["method"]
            c["why"] = (c.get("why") or []) + [f"Company name recovered from the article text: “{recovered['evidence'][:120]}”"]
        elif name == "UNKNOWN":
            c["id"] = _uid(f["name"], title)
            c["why"] = (c.get("why") or []) + [
                "Company name not extractable from the headline — read the source before judging"
            ]
        out.append(c)
    return out

class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.out = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "nav", "footer", "header"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "nav", "footer", "header") and self.skip:
            self.skip -= 1

    def handle_data(self, d):
        if not self.skip:
            d = re.sub(r"\s+", " ", d).strip()
            if d:
                self.out.append(d)

def _lines(html, dedupe=True):
    """Visible text lines. ``dedupe=False`` keeps repeated lines (a team page where two people are both "Co-Founder")."""
    p = _Text()
    with contextlib.suppress(Exception):
        p.feed(html)
    seen, out = set(), []
    for ln in p.out:
        if 5 <= len(ln) <= 240 and (ln not in seen or not dedupe):
            seen.add(ln)
            out.append(ln)
    return out

COMPANY_HINT = re.compile(
    r"\b(GmbH|UG|AG|Ltd|Inc|SE|Spin-?off|Startup|Start-up|Ausgründung|gegründet|founded|founder|Gründer|selected|wins|receives|cohort)\b",
    re.I,
)

def page(src):
    snap = _snap_path(_uid(src["url"]) + ".json")
    lines = _lines(_get(src["url"]))
    old = _load_snapshot(snap)
    _save_snapshot(snap, lines)
    first = not old
    fresh = (
        set(ln for ln in lines if ln not in set(old))
        if not first
        else set(ln for ln in lines if COMPANY_HINT.search(ln) or taste.tag_archetypes(ln))
    )
    items, i = [], 0
    while i < len(lines):
        if lines[i] in fresh:
            name, desc = lines[i], ""
            if i + 1 < len(lines) and lines[i + 1] in fresh and len(lines[i + 1]) > len(name):
                desc = lines[i + 1]
                i += 1
            items.append((name, desc))
        i += 1
    from projectzero.dealflow.triage import entity_repair
    evmod = seams.evmod

    # News lists put a timestamp line before each title ("09.10.2026 15:09" / "Ascento opens NY office"): the
    # timestamp is never a company. Use the paired title instead; a timestamp with no title is not a candidate.
    titled = []
    for name, desc in items:
        if _date_only(name, evmod):
            if not desc or _date_only(desc, evmod):
                continue
            name, desc = desc, ""
        titled.append((name, desc))
    items = titled
    out = []
    for name, desc in items[:60]:
        label = " ".join(re.split(r"\s[–\-:|]\s", name)[0].split()[:8])
        # A timestamp / UNKNOWN / headline / event line is not a company: name the companies the text clearly names
        # (one candidate each, max 3, same source provenance); otherwise keep the line exactly as before.
        ents = entity_repair.extract_entities({"name": name, "description": desc}, limit=3) if (
            entity_repair.broken_name_reason({"name": label})
        ) else []
        for ent in ents or [None]:
            c = make(
                ent["name"] if ent else label,
                src["name"],
                "pre_company",
                src["url"],
                seams.today().isoformat(),
                src["location"],
                desc or name,
                src["country"],
                "detected",
            )
            if ent:
                c["raw_title"] = name
                c["name_method"] = "entity_repair: " + ent["method"]
                if len(ents) > 1:
                    c["split_from"] = name  # one article, several companies — each keeps the article provenance
            if first:
                c["decision"] = "baseline"
            out.append(c)
    return out, first

_DATE_NOISE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|mon|tue|wed|thu|fri|sat|sun)[a-zäöüé]*\.?|\b(am|pm)\b", re.I
)

def _date_only(ln, evmod):
    """A short line that is just a date / time range ("Oct 6, 2026, 8:30 AM – 12:00 PM"): no words left once month,
    weekday and AM/PM tokens are removed."""
    return len(ln) <= 80 and bool(evmod.extract_date(ln)) and not re.search(r"[^\W\d_]{3,}", _DATE_NOISE.sub(" ", ln))

_SUFFIX = {
    "gmbh",
    "ug",
    "ag",
    "se",
    "kg",
    "ohg",
    "ev",
    "inc",
    "llc",
    "corp",
    "co",
    "ltd",
    "plc",
    "limited",
    "oy",
    "oyj",
    "ab",
    "as",
    "aps",
    "bv",
    "nv",
    "sas",
    "sarl",
    "srl",
    "sl",
    "spa",
    "sa",
    "spzoo",
    "mbh",
    "gbr",
}

INTERSTITIAL = re.compile(
    r"(activate|enable|accept|allow)\s+(the\s+)?cookies|cookie\s+(settings|policy|banner|consent)|"
    r"consent\s+(manager|required)|we\s+use\s+cookies|diese\s+website\s+verwendet\s+cookies|"
    r"enable\s+javascript|javascript\s+(is\s+)?(required|disabled)|javascript\s+has\s+been\s+disabled|"
    r"are\s+you\s+a\s+(robot|human)|verify\s+you\s+are|captcha|access\s+denied|error\s+403|"
    r"log\s?in\s+to\s+continue|sign\s+in\s+to\s+continue|subscribe\s+to\s+(read|continue)|"
    r"browser\s+(is\s+)?(out\s?dated|not\s+supported|update)|your\s+browser|please\s+update\s+your",
    re.I,
)

def is_interstitial(text):
    """Cookie banners, consent pages, bot checks, login walls, JS notices — page plumbing, never a company."""
    return bool(INTERSTITIAL.search(text or ""))

def parse_source_date(raw):
    """Actual source/publication date as ISO, or None (=UNKNOWN). Never guesses."""
    if not raw:
        return None
    raw = str(raw).strip()
    try:
        return parsedate_to_datetime(raw).date().isoformat()
    except Exception:
        pass
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        return m.group(0)
    m = re.fullmatch(r"(19|20)\d{2}", raw)
    if m:
        return raw + "-01-01"
    return None

def norm_company(name):
    n = " " + re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip() + " "
    for a, b in (
        (" b v ", " bv "),
        (" n v ", " nv "),
        (" a s ", " as "),
        (" s a ", " sa "),
        (" sp z o o ", " spzoo "),
        (" e v ", " ev "),
    ):
        n = n.replace(a, b)
    toks = n.split()
    while toks and toks[-1] in _SUFFIX:
        toks.pop()
    return " ".join(toks[:5])

SECTOR_KEYWORDS = {
    "bio": r"\b(biotech\w*|bio-?pharm\w*|pharma\w*|drug|therapeut\w*|clinical|oncolog\w*|antibod\w*|vaccine\w*|genomic\w*|proteom\w*|cell therap\w*|medtech|medical device|diagnostic\w*|biomarker\w*|molecular biolog\w*)\b",
    "space": r"\b(satellite\w*|orbital|launch vehicle|space(craft|port| debris| station)?|in-orbit|earth observation|lunar|cubesat\w*|rocket\w*)\b",
    "defence": r"\b(defen[cs]e|dual-?use|military|nato|isr|battlefield|c4isr|counter-?uas|munition\w*)\b",
    "robotics": r"\b(robot\w*|autonomous (system\w*|vehicle\w*|driving|navigation|inspection)|drone\w*|uav|ugv|manipulat\w*|slam|humanoid\w*)\b",
    "climate": r"\b(climate|carbon|decarboni\w*|renewable\w*|solar|wind energy|geothermal|hydrogen|batter(y|ies)|energy storage|grid|fusion energy|e-?fuel\w*)\b",
    "semis_quantum": r"\b(semiconductor\w*|chip(let)?s?|photonic\w*|quantum|wafer\w*|lithograph\w*|asic|fpga|rf front|gan|sic power)\b",
    "deeptech": r"\b(deep-?tech|advanced material\w*|advanced manufactur\w*|additive manufactur\w*|3d print\w*|nanotech\w*|sensor\w*|catalys\w*|superconduct\w*|cryogenic\w*|spinoff|spin-?out|ausgründung)\b",
    "ai_sw": r"\b(ai|artificial intelligence|machine learning|llm\w*|foundation model\w*|computer vision|software|saas|api platform|agentic|data platform)\b",
}

_SECTOR_RE = {k: re.compile(v, re.I) for k, v in SECTOR_KEYWORDS.items()}

def classify_sectors(text):
    """Sectors of the CANDIDATE from its own text — source sectors are context, never copied."""
    t = " " + (text or "") + " "
    return [k for k, rx in _SECTOR_RE.items() if rx.search(t)]

_ACADEMIC = re.compile(
    r"\b(universit|università|universidad|universität|college|institut|instituto|centre|center|hospital|school|academy|akademi|council|foundation|max.planck|fraunhofer|helmholtz|cnrs|tno\b|vtt\b)",
    re.I,
)

def is_academic(name):
    return bool(_ACADEMIC.search(name or ""))

def entity_keys(c):
    """Stable identifiers first (UEI, DUNS, org id, domain), normalized name as fallback."""
    keys = []
    ids = c.get("entity_ids") or {}
    for k in ("uei", "duns", "org_id", "domain"):
        if ids.get(k):
            keys.append(k + ":" + str(ids[k]).lower())
    n = norm_company(c.get("name"))
    if n and n != "unknown":
        keys.append("nm:" + n)
    return keys

def _peek(src, key):
    """True if this record was seen in a previous scan (no recording)."""
    return key in src.setdefault("hwm", {"seen": []})["seen"]

def _mark(src, key):
    hw = src.setdefault("hwm", {"seen": []})
    if key not in hw["seen"]:
        hw["seen"] = ([key] + hw["seen"])[:800]

def _seen(src, key):
    """Peek + mark in one step — ONLY for sources where the record itself is the candidate
    (SBIR/NSF/NIH). GtR/CORDIS must use _peek and _mark AFTER resolution succeeds, so a
    transient failure never permanently loses a project."""
    if _peek(src, key):
        return True
    _mark(src, key)
    return False

def _mk_from(src, name, desc, url=None, location=None, country=None):
    c = make(
        name,
        src["name"],
        src.get("stage", "grant") if src.get("stage") in ("pre_company", "grant") else "announcement",
        url or src["url"],
        seams.today().isoformat(),
        location or src.get("location", ""),
        desc,
        country or src.get("country", ""),
        "detected",
    )
    return c

def p_sbir(src):
    Y = seams.today().year
    base_ok, first = None, None
    for base in (
        f"https://api.www.sbir.gov/public/api/awards?year={Y}",
        f"https://api.sbir.gov/public/api/awards?year={Y}",
    ):
        try:
            json.loads(_get(base + "&rows=1"))
            base_ok = base
            break
        except Exception as e:
            first = first or e  # report the CURRENT endpoint's reason, not the retired fallback's DNS error
    if base_ok is None:
        raise first
    out = []
    src["last_truncated"] = False
    max_pages = int(src.get("max_pages") or 10)
    pg = 0
    while True:
        if _expired():
            src["last_truncated"] = True  # deadline: stop paginating; nothing marked beyond processed rows
            break
        if pg >= max_pages:  # safety limit hit with fresh data still flowing
            src["last_truncated"] = True
            break
        data = json.loads(_get(f"{base_ok}&rows=50&start={pg * 50}"))
        rows = data if isinstance(data, list) else data.get("results") or data.get("awards") or []
        if not rows:
            break
        fresh = 0
        for r in rows:
            firm = r.get("firm") or r.get("company_name") or ""
            key = str(r.get("award_id") or r.get("contract") or (firm + str(r.get("award_title", ""))[:40]))
            if not firm or _seen(src, "sbir:" + key):
                continue
            fresh += 1
            ph = str(r.get("phase", ""))
            desc = f"{r.get('award_title', '')} — {r.get('agency', '')} SBIR{(' Phase ' + ph) if ph else ''}, {r.get('award_year', Y)}"
            loc = ", ".join(x for x in (r.get("city", ""), r.get("state", "")) if x) or "USA"
            c = _mk_from(src, firm, desc, r.get("award_link") or None, loc, "USA")
            ad = r.get("proposal_award_date") or r.get("award_year")
            if ad:
                c["date"] = str(ad)
                c["date_kind"] = "award"
            c["entity_ids"] = {
                k: v
                for k, v in (
                    ("uei", r.get("uei")),
                    ("duns", r.get("duns")),
                    (
                        "domain",
                        (r.get("company_url") or "").replace("https://", "").replace("http://", "").split("/")[0]
                        or None,
                    ),
                )
                if v
            }
            out.append(c)
        if fresh == 0:
            break
        pg += 1
    return out

def p_nsf(src):
    out = []
    src["last_truncated"] = False
    max_pages = int(src.get("max_pages") or 6)
    for q in (src.get("queries") or ["robotics"])[:3]:
        for pg in range(max_pages + 1):
            if _expired():
                src["last_truncated"] = True
                return out
            if pg == max_pages:
                src["last_truncated"] = True
                break
            u = (
                src["url"]
                + "?keyword="
                + q.replace(" ", "%20")
                + "&printFields=id,title,awardee,date,fundProgramName&offset="
                + str(pg * 25 + 1)
            )
            data = json.loads(_get(u))
            rows = data.get("response", {}).get("award") or []
            if not rows:
                break
            fresh = 0
            for a in rows:
                name, prog = a.get("awardee") or "", a.get("fundProgramName") or ""
                if not name or _seen(src, "nsf:" + str(a.get("id"))):
                    continue
                fresh += 1
                sbir = "SBIR" in prog.upper() or "STTR" in prog.upper()
                commercial = (
                    not is_academic(name)
                    and (norm_company(name) != re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()[:80] or True)
                    and bool(re.search(r"\b(inc|llc|corp|co|ltd)\b\.?", name, re.I))
                )
                if not (sbir or (commercial and not is_academic(name))):
                    continue  # generic university research award — not a startup
                out.append(
                    _mk_from(src, name, f"NSF {prog or 'award'}: {a.get('title', '')[:120]}", None, "USA", "USA")
                )
            if fresh == 0:
                break
    return out

def p_nih(src):
    Y = seams.today().year
    out = []
    src["last_truncated"] = False
    max_pages = int(src.get("max_pages") or 6)
    for pg in range(max_pages + 1):
        if _expired():
            src["last_truncated"] = True
            break
        if pg == max_pages:
            src["last_truncated"] = True
            break
        body = json.dumps(
            {
                "criteria": {"fiscal_years": [Y], "activity_codes": ["R43", "R44", "U43", "U44"]},
                "include_fields": ["Organization", "ProjectTitle", "ApplId"],
                "limit": 50,
                "offset": pg * 50,
            }
        ).encode()
        data = _request_json(src["url"], data=body, headers={"Content-Type": "application/json"})
        rows = data.get("results") or []
        if not rows:
            break
        fresh = 0
        for r in rows:
            org = r.get("organization") or {}
            name = org.get("org_name") or ""
            if not name or _seen(src, "nih:" + str(r.get("appl_id") or name)):
                continue
            fresh += 1
            c = _mk_from(src, name.title(), f"NIH SBIR: {r.get('project_title', '')[:120]}", None, "USA", "USA")
            ids = {}
            if org.get("org_uei"):
                ids["uei"] = org["org_uei"][0] if isinstance(org["org_uei"], list) else org["org_uei"]
            if org.get("org_duns"):
                ids["duns"] = org["org_duns"][0] if isinstance(org["org_duns"], list) else org["org_duns"]
            if ids:
                c["entity_ids"] = ids
            out.append(c)
        if fresh == 0:
            break
    return out

_GTR_ORG_CACHE = {}

def _gtr_org(href):
    if href in _GTR_ORG_CACHE:
        return _GTR_ORG_CACHE[href]
    o = _request_json(href, headers={"Accept": "application/json"})
    name = (
        o.get("name")
        or (o.get("organisationOverview") or {}).get("name")
        or (o.get("organisation") or {}).get("name")
        or ""
    )
    oid = o.get("id") or (o.get("organisationOverview") or {}).get("id") or href.rstrip("/").split("/")[-1]
    _GTR_ORG_CACHE[href] = (name, oid)
    return _GTR_ORG_CACHE[href]

_GTR_ORG_RELS = {"LEAD_ORG", "LEAD_RO", "PARTICIPANT_ORG", "PP_ORG", "PROJECT_PARTNER", "COLLAB_ORG", "FELLOW_ORG"}

def _gtr_fetch(src, q, pg):
    """New search API first (gtr.ukri.org/api/search/project), legacy /gtr/api/projects as fallback."""
    attempts = [
        (src["url"] + "?term=" + q + "&page=" + str(pg) + "&size=20", {"Accept": "application/json", "User-Agent": UA}),
        (src["url"] + "?q=" + q + "&page=" + str(pg) + "&size=20", {"Accept": "application/json", "User-Agent": UA}),
        (
            src["url"] + "?searchText=" + q + "&page=" + str(pg) + "&size=20",
            {"Accept": "application/json", "User-Agent": UA},
        ),
        (
            "https://gtr.ukri.org/gtr/api/projects?q=" + q + "&p=" + str(pg) + "&s=20",
            {"Accept": "application/vnd.rcuk.gtr.json-v7", "User-Agent": UA},
        ),
    ]
    for u, hdr in attempts:  # every variant is tried; a failing one just falls through to the next
        try:
            data = _request_json(u, headers=hdr)
            rows = (
                data.get("project")
                or data.get("results")
                or (data.get("searchResult") or {}).get("results")
                or (data.get("res") or {}).get("results")
                or []
            )
            if rows:
                return [r.get("project", r) if isinstance(r, dict) else r for r in rows]
        except Exception:
            continue
    if pg == 1 and not (src.get("hwm") or {}).get("seen"):
        raise ValueError(
            "0 records from every GtR endpoint variant on a first scan — params may have changed; see gtr.ukri.org/resources/api.html"
        )
    return []

def p_gtr(src):
    out, resolved, projects_seen = [], 0, 0
    src["last_truncated"] = False
    max_pages = int(src.get("max_pages") or 5)
    for q in (src.get("queries") or ["autonomous"])[:2]:
        pg = 1
        while True:
            if _expired() or pg > max_pages:
                src["last_truncated"] = True
                break
            rows = _gtr_fetch(src, q, pg)
            if not rows:
                break
            fresh = 0
            for pr in rows:
                pid = "gtr:" + str(pr.get("id") or pr.get("grantReference") or pr.get("title", ""))[:60]
                if _peek(src, pid):
                    continue
                fresh += 1
                projects_seen += 1
                title, cat = pr.get("title", ""), pr.get("grantCategory", "")
                links = (pr.get("links") or {}).get("link") or []
                org_hrefs = [
                    ln.get("href")
                    for ln in links
                    if ((ln.get("rel") or "").upper() in _GTR_ORG_RELS or "ORG" in (ln.get("rel") or "").upper())
                    and ln.get("href")
                ]
                fetch_failed = False
                for href in org_hrefs[:4]:
                    if _expired():
                        fetch_failed = True  # unresolved -> project stays retryable, HWM untouched
                        break
                    try:
                        name, oid = _gtr_org(href)
                    except Exception:
                        fetch_failed = True
                        continue
                    if not name or is_academic(name):
                        continue
                    c = _mk_from(src, name, f"UKRI project participant: {title[:110]} ({cat})", None, "UK", "UK")
                    c["entity_ids"] = {"org_id": "gtr-" + str(oid)}
                    out.append(c)
                    resolved += 1
                if not fetch_failed:
                    _mark(src, pid)
            if fresh == 0:
                break
            pg += 1
    if projects_seen and not resolved:
        raise ValueError(
            f"{projects_seen} projects fetched but no commercial organisations resolved — check GtR org links"
        )
    return out

def _cordis_orgs(link):
    """Verified 2026-09: project pages offer structured XML at <project-url>?format=xml with
    legalName / country / activityType per organisation. HTML legalName-JSON was the OLD format."""
    xml = _get(link.rstrip("/") + "?format=xml")
    orgs = []
    for m in re.finditer(r"<legalName>([^<]{2,90})</legalName>", xml):
        nxt = xml.find("<legalName>", m.end())
        window = xml[m.end() : nxt if nxt > 0 else m.end() + 4000][:4000]  # this organisation only
        cm = re.search(r"<country[^>]*>([A-Za-z]{2})<", window) or re.search(r'isoCode="([A-Za-z]{2})"', window)
        # 2026-10 format: <category classification="organizationActivityType"> ... <title>Private for-profit ...
        am = re.search(r"<activityType[^>]*>([^<]{2,80})<", window) or re.search(
            r'classification="organizationActivityType".*?<title>([^<]{2,120})</title>', window, re.S
        )
        orgs.append((m.group(1).strip(), (cm.group(1).upper() if cm else ""), (am.group(1) if am else "")))
    if not orgs:  # fall back to the older embedded-JSON page format
        page_html = _get(link)
        orgs = [(n, "", "") for n in dict.fromkeys(re.findall(r'"legalName"\s*:\s*"([^"]{2,80})"', page_html))]
    return orgs[:8]

def p_cordis(src):
    q = (src.get("queries") or [""])[0]
    qq = q.replace(" ", "%20").replace("'", "%27")
    xml, errs = None, []
    for u in (
        "https://cordis.europa.eu/search/rss?q=" + qq,
        "https://cordis.europa.eu/search/en/rss?q=" + qq,
        "https://cordis.europa.eu/search?format=rss&q=" + qq,
    ):
        try:
            xml = _get(u)
            if "<rss" in xml[:2000] and "<item>" in xml:  # a real feed (the web app's HTML also contains "<item")
                break
            errs.append(
                ("web page instead of an RSS feed" if "<html" in xml[:500].lower() else "no items")
                + " at "
                + u.split("cordis.europa.eu")[1][:28]
            )
        except Exception as e:
            errs.append(type(e).__name__ + " at " + u.split("cordis.europa.eu")[1][:28])
    if xml is None or "<rss" not in xml[:2000] or "<item>" not in xml:
        if errs and all(e.startswith("web page instead") or "HTTPError" in e for e in errs):
            raise ValueError(
                "CORDIS no longer offers its search RSS feed (the site became a web app) — external change; "
                "this source needs a new data path (CORDIS open-data exports)"
            )
        raise ValueError("all CORDIS RSS variants failed: " + "; ".join(errs)[:120])
    items = re.findall(r"<item>\s*<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>.*?<link>(.*?)</link>", xml, re.S)[:12]
    out, resolved, attempted = [], 0, 0
    for title, raw_link in items:
        if _expired():
            break  # remaining items untouched -> retryable next scan
        # feed links carry tracking parameters (?WT.mc_id=RSS-Feed&amp;...): the project page is the part before "?"
        link = _html.unescape(raw_link).strip().split("?", 1)[0]
        key = "cordis:" + link.strip()[:120]
        if not title.strip() or _peek(src, key):
            continue
        attempted += 1
        try:
            orgs = _cordis_orgs(link.strip())
        except Exception:
            continue  # transient -> retry next scan, do NOT mark
        if not orgs:
            continue  # reachable but unparseable -> keep retryable
        for name, ctry, atype in orgs:
            commercial = ("for-profit" in atype.lower()) if atype else (not is_academic(name))
            if not commercial or is_academic(name):
                continue
            c = _mk_from(
                src,
                name.title() if name.isupper() else name,
                f"CORDIS project participant: {title.strip()[:110]}",
                link.strip(),
                ctry or "",
                ctry or "",
            )
            out.append(c)
            resolved += 1
        _mark(src, key)  # orgs extracted (even academic-only) -> done
    if attempted and not resolved and not out:
        raise ValueError("CORDIS items fetched but no commercial participants resolved (page format may have changed)")
    return out

def p_ckan(src):
    if not src.get("resource_id"):
        raise ValueError(
            "resource_id not set — open the dataset once and paste its datastore resource id into sources.json"
        )
    u = src["url"] + "?resource_id=" + src["resource_id"] + "&limit=25"
    data = json.loads(_get(u))
    out = []
    for r in (data.get("result", {}).get("records") or [])[:25]:
        name = r.get("recipient_legal_name") or r.get("legal_name") or r.get("recipient") or ""
        if name:
            out.append(
                _mk_from(
                    src,
                    name,
                    "NRC IRAP contribution: " + str(r.get("description_en", r.get("prog_name_en", "")))[:120],
                    None,
                    "Canada",
                    "Canada",
                )
            )
    return out

PARSERS = {
    "page_diff": None,
    "rss": None,
    "sbir": p_sbir,
    "nsf": p_nsf,
    "nih": p_nih,
    "gtr": p_gtr,
    "cordis": p_cordis,
    "ckan": p_ckan,
}

PARSERS.update(_sv2.PARSERS_V2)

def _scan_one(src, days, now):
    """Scan a single source dict IN PLACE (health stamps, hwm). Returns (candidates, report_row)."""
    if not src.get("enabled"):
        return [], {
            "source": src["name"],
            "tier": src["kind"],
            "status": "off",
            "note": src.get("notes", "disabled"),
            "geo": src.get("geo", []),
        }
    src["last_scan"] = now
    _fetch_reset()
    try:
        if src["parser"] == "page_diff":
            c, first = page(src)
            note = f"baseline saved ({len(c)} existing, NOT new)" if first else f"{len(c)} new item(s)"
        elif src["parser"] == "rss":
            c = feed(src, days)
            note = f"{len(c)} item(s) in feed"
        else:
            c = PARSERS[src["parser"]](src)
            note = f"{len(c)} record(s) (structured)"
            if src.get("last_truncated"):
                note += " · SAFETY LIMIT reached — coverage incomplete this scan; raise max_pages in sources.json to go deeper"
        ft = dict(_fetch_stats())
        if (
            not c and ft["attempts"] and ft["ok"] == 0
        ):  # the parser swallowed every failure: zero pages retrieved is a FAILED scan, never "ok 0"
            raise FetchFailure(
                f"all {ft['attempts']} fetch attempt(s) failed — {ft['errors'][-1] if ft['errors'] else 'no response'}"
            )
        if ft["failed"]:  # partial retrieval stays successful but discloses the failed attempts
            last_err = (ft["errors"][-1] if ft["errors"] else "")[:60]
            note += f" · {ft['failed']} of {ft['attempts']} fetch attempt(s) failed ({last_err})"
        n_raw = len(c)  # raw records retrieved from this source (before any filter)
        n_inter = len(c)
        c = [x for x in c if not is_interstitial((x.get("name", "") + " " + x.get("description", ""))[:400])]
        n_inter -= len(c)
        n_base = sum(1 for x in c if x.get("decision") == "baseline")
        for x in c:
            x["source_id"] = src["id"]
            x["geo"] = src.get("geo", [])
            x["first_seen"] = x.get("detected_on") or seams.today().isoformat()
            x["source_date"] = (
                parse_source_date(x.get("date")) if x.get("date_kind") in ("published", "award") else None
            )
            x["src_quality"] = {"high": 2, "medium": 1, "low": 0}[src.get("reliability", "low")]
            x["geo_scope"] = src.get("geo_scope", "region-eu")
            if x["geo_scope"] == "global":
                if x.get("country", "") == src.get("country", ""):
                    x["country"] = ""
                if x.get("location", "") == src.get("location", ""):
                    x["location"] = ""
            x["source_sectors"] = src.get("sectors", [])
            x["sectors"] = classify_sectors(x.get("name", "") + " " + x.get("description", ""))
            if "bio" in x["sectors"]:
                x["opportunistic"] = True
                x["why"] = (x.get("why") or []) + [
                    "OPPORTUNISTIC — candidate text is bio/pharma; outside core themes, #15 outlier route only"
                ]
            x["priority"] = (x.get("priority") or 5) + {"high": 2, "medium": 1, "low": 0}[src.get("reliability", "low")]
            if src.get("probation"):  # adaptive source network: visible marker only, no scoring change
                x["probation_source"] = True
                x["why"] = (x.get("why") or []) + ["From a PROBATION source — new, limited trust, still being measured"]
        if n_inter:
            note += f" · {n_inter} cookie/interstitial line(s) dropped (never candidates)"
        src["last_ok"] = now
        src["last_result_count"] = len(c)
        src["failures_in_row"] = 0
        src["total_results"] = int(src.get("total_results") or 0) + len(c)
        return c, {
            "source": src["name"],
            "tier": src["kind"],
            "status": "ok",
            "note": note,
            "geo": src.get("geo", []),
            "source_id": src["id"],
            "url": src.get("url", ""),
            "raw": n_raw,
            "count": len(c),
            "baseline": n_base,
            "interstitial": n_inter,
            "fetch": {k: ft[k] for k in ("attempts", "ok", "failed")},
        }
    except Exception as e:
        src["failures_in_row"] = (
            int(src.get("failures_in_row") or 0) + 1
        )  # last_ok / last_result_count stay as they were
        ft = dict(_fetch_stats())
        return [], {
            "source": src["name"],
            "tier": src["kind"],
            "status": "failed",
            "note": (str(e)[:110] if isinstance(e, FetchFailure) else f"{type(e).__name__}: {str(e)[:70]}"),
            "geo": src.get("geo", []),
            "source_id": src["id"],
            "url": src.get("url", ""),
            "raw": 0,
            "count": 0,
            "fetch": {k: ft[k] for k in ("attempts", "ok", "failed")},
        }

_BATCH_TIER = {"pre_company": 0, "grant": 1, "announcement": 2}

def _batch_order(c):
    """Deterministic host selection for cross-source merging, independent of thread completion order:
    a live record beats a first-run baseline, earlier channel beats later, then stable source id / id."""
    return (
        1 if c.get("decision") == "baseline" else 0,
        _BATCH_TIER.get(c.get("discovery_tier"), 3),
        str(c.get("source_id") or ""),
        str(c.get("id") or ""),
    )

def _resolve_batch(cands, report):
    merged, by_key, dupes = [], {}, 0
    cands = sorted(cands, key=_batch_order)
    for c in cands:
        keys = entity_keys(c)
        host = next((by_key[k] for k in keys if k in by_key), None)
        if host is not None:
            host.setdefault("also_seen", [])
            if c["source"] != host["source"] and c["source"] not in [a["source"] for a in host["also_seen"]]:
                host["also_seen"].append(
                    {
                        "source": c["source"],
                        "url": c.get("source_url", ""),
                        "source_id": c.get("source_id", ""),
                        "discovery_tier": c.get("discovery_tier", ""),
                        "source_date": c.get("source_date") or "",
                    }
                )
                host["priority"] = (host.get("priority") or 5) + 2
                host["why"] = (host.get("why") or []) + [f"Cross-source signal: also seen on {c['source']}"]
            for k in keys:
                by_key[k] = host
            hi = host.setdefault("entity_ids", {})
            for ik, iv in (c.get("entity_ids") or {}).items():
                hi.setdefault(ik, iv)
            dupes += 1
            continue
        for k in keys:
            by_key[k] = c
        merged.append(c)
    if dupes:
        report.append(
            {
                "source": "Entity resolution",
                "tier": "system",
                "status": "ok",
                "geo": ["ALL"],
                "merged": dupes,
                "note": f"{dupes} cross-source duplicate(s) merged — provenance kept, priority raised",
            }
        )
    return merged

RUNTIME_KEYS = (
    "last_scan",
    "last_ok",
    "last_result_count",
    "failures_in_row",
    "total_results",
    "last_truncated",
    "hwm",
)


# ── hand-written tracking (NOT cut): which cursor key each record was made under (revision 2) ─────────────────────
# The old parsers mark a record's cursor key before (``_seen``, ``_seen_gate``) or after (GtR, CORDIS) making it; the
# run keeps the key of a record the intake REFUSED out of the cursor. These wrappers only record, then call the cut
# function unchanged (every caller looks the names up at call time).
_peek_cut, _mark_cut, _make_cut = _peek, _mark, make


def _peek(src, key):
    seams.note_key(key)
    return _peek_cut(src, key)


def _mark(src, key):
    seams.note_key(key)
    return _mark_cut(src, key)


def make(name, source, tier, url, dt, location, description, country, date_kind):
    c = _make_cut(name, source, tier, url, dt, location, description, country, date_kind)
    seams.note_record(c)
    return c
# fmt: on

"""The Events engine (read model): the old ``domain/events.py`` (rev 6c739b9) score ladders, canonical date view,
RC2 evidence assessment / eligibility / ranking and ``listing``, ported VERBATIM with the clock as a parameter.

Old source lines: ``EVENT_TYPES`` .. ``_ADMIN_WORDS`` :68-259, ``city_hours`` / ``suggest`` / ``score_of`` :261-337,
``weekend_window`` / ``event_when`` / ``event_span`` / ``overlaps`` / ``actionable`` :496-623, ``classify`` ..
``canonical`` :728-1051, ``listing`` :1054-1088. Held to the old code by ``ops.parity_events_read`` (goldens and the
real snapshot).

Changed on purpose (review 015, approved by Codex H-101):

* **One Berlin clock.** Every function takes ``today`` (the Berlin date of the request instant). The old code mixed
  ``berlin_today()`` with the machine's ``date.today()``; on the operator's machine in Berlin they agreed.
* **The imported year of a year-less date is kept.** Review 014 resolved "Sept 20" once, at the import clock, into
  ``events.start_date`` / ``end_date``. ``pins`` carries those persisted dates for values written as free text; the
  engine uses them instead of re-reading the raw words with today's year (the old page rolled such a date forward a
  year once it had passed). The raw wording stays in the record for display.
* **A value the old code crashed on is unparseable.** The old ``parse_when`` raised on a non-text value (the whole
  page failed) and ``event_span`` on a time such as ``24:00`` (the weekend planner failed). Here such a value reads as
  no date, for that event only.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

from projectzero.events import place as event_place
from projectzero.events.when import _aware, parse_when

Pins = Mapping[str, date | None]  # side ("start" / "end") -> the STORED result of a free-text value (None: no date)

EVENT_TYPES = {
    "hackathon": "Hackathon",
    "founder_meetup": "Founder meetup / pitch night",
    "demo_day": "Demo day",
    "university": "University entrepreneurship",
    "technical": "Technical / research conference",
    "developer": "Developer event",
    "corporate": "Corporate innovation (Google, NVIDIA, SAP, ...)",
    "consulting": "Consulting-firm innovation event",
    "accelerator": "Accelerator event",
    "vc": "VC / investor event",
    "community": "Deeptech/AI/robotics/energy community",
    "community_founder": "Outdoor / community founder event",
    "UNKNOWN": "Type not evidenced",
}

# City gazetteer: coordinates + rough rail/road hours from Karlsruhe (evidence for Accessibility)
GAZETTEER: dict[str, tuple[float, float, float]] = {
    "Karlsruhe": (49.0069, 8.4037, 0.0),
    "Stuttgart": (48.7758, 9.1829, 0.8),
    "Frankfurt": (50.1109, 8.6821, 1.1),
    "Darmstadt": (49.8728, 8.6512, 0.9),
    "Heidelberg": (49.3988, 8.6724, 0.5),
    "Mannheim": (49.4875, 8.4660, 0.4),
    "Munich": (48.1351, 11.5820, 3.0),
    "München": (48.1351, 11.5820, 3.0),
    "Zürich": (47.3769, 8.5417, 3.0),
    "Zurich": (47.3769, 8.5417, 3.0),
    "Lausanne": (46.5197, 6.6323, 4.5),
    "Basel": (47.5596, 7.5886, 2.0),
    "Berlin": (52.5200, 13.4050, 5.5),
    "Paris": (48.8566, 2.3522, 2.5),
    "Amsterdam": (52.3676, 4.9041, 4.5),
    "Eindhoven": (51.4416, 5.4697, 3.8),
    "Delft": (52.0116, 4.3571, 4.8),
    "London": (51.5074, -0.1278, 6.0),
    "St. Gallen": (47.4245, 9.3767, 3.8),
    "Cologne": (50.9375, 6.9603, 2.5),
    "Köln": (50.9375, 6.9603, 2.5),
    "Hamburg": (53.5511, 9.9937, 5.5),
    "Copenhagen": (55.6761, 12.5683, 8.0),
    "Helsinki": (60.1699, 24.9384, 12.0),
}

# Evidence-based score ladders: (points, evidence label). The label IS the visible reasoning.
DIMS: dict[str, dict[str, Any]] = {
    "founder_density": {
        "label": "Founder / pre-founder density",
        "max": 25,
        "ladder": [
            (2, "General audience, founders unlikely"),
            (8, "Some founders probably present"),
            (16, "Founder-focused audience (pitch night, accelerator, demo day)"),
            (25, "Dense pre-founder crowd: hackathon / entrepreneurial researchers / builders before incorporation"),
        ],
    },
    "tech_talent": {
        "label": "Technical talent density",
        "max": 20,
        "ladder": [
            (2, "Non-technical crowd"),
            (7, "Mixed, some engineers"),
            (14, "Mostly engineers / PhDs / researchers"),
            (20, "Elite technical crowd (ETH/KIT/EPFL/TUM level, research groups, top-company engineers)"),
        ],
    },
    "earliness": {
        "label": "Earliness of the people there",
        "max": 15,
        "ladder": [
            (2, "Established companies, late stage"),
            (6, "Mostly existing startups"),
            (11, "Mix of pre-company and very early teams"),
            (15, "People BEFORE company formation (students, researchers, side-project builders)"),
        ],
    },
    "domain_fit": {
        "label": "Domain fit to Project A themes",
        "max": 15,
        "ladder": [
            (2, "Unrelated domain"),
            (6, "Broad tech"),
            (11, "Adjacent (AI, deeptech, B2B software)"),
            (15, "Core themes: defence, industrial, robotics, energy, regulated, security"),
        ],
    },
    "network_value": {
        "label": "Network value (organizers, investors, community)",
        "max": 10,
        "ladder": [
            (1, "One-off, unknown organizer"),
            (4, "Decent organizer"),
            (7, "Strong organizer / investors present"),
            (10, "Recurring community with strong organizers and investor presence"),
        ],
    },
    "accessibility": {
        "label": "Accessibility from Karlsruhe",
        "max": 10,
        "ladder": [
            (2, "Far: flight or >6h travel"),
            (4, "Long day-trip (4-6h)"),
            (7, "Reachable (1.5-3.5h: Munich, Zürich, Frankfurt, Paris)"),
            (10, "Local (Karlsruhe / <1h)"),
        ],
    },
    "serendipity": {
        "label": "Serendipity potential",
        "max": 5,
        "ladder": [
            (1, "Scripted program, little mingling"),
            (3, "Some open networking"),
            (5, "Long unstructured time (hackathon weekend, open community)"),
        ],
    },
}
DIM_ORDER = [
    "founder_density",
    "tech_talent",
    "earliness",
    "domain_fit",
    "network_value",
    "accessibility",
    "serendipity",
]

_KEY: dict[str, dict[str, int]] = {
    "hackathon": {"founder_density": 25, "tech_talent": 14, "earliness": 15, "serendipity": 5},
    "founder_meetup": {"founder_density": 16, "earliness": 11, "serendipity": 3},
    "demo_day": {"founder_density": 16, "earliness": 6, "network_value": 7},
    "university": {"tech_talent": 14, "earliness": 15, "founder_density": 8},
    "technical": {"tech_talent": 14, "earliness": 11, "founder_density": 8},
    "developer": {"tech_talent": 14, "earliness": 11},
    "corporate": {"network_value": 7, "founder_density": 8},
    "consulting": {"network_value": 7, "founder_density": 8},
    "accelerator": {"founder_density": 16, "earliness": 11, "network_value": 7},
    "vc": {"network_value": 10, "founder_density": 16, "earliness": 6},
    "community": {"tech_talent": 14, "earliness": 11, "serendipity": 5},
}
_DOMAIN_WORDS = [
    "defence", "defense", "robotic", "industrial", "energy", "security", "drone", "space", "manufactur",
    "semiconductor", "quantum", "ai ", " ai", "machine learning", "deeptech", "deep tech", "climate", "hardware",
]  # fmt: skip
_CORE_DOMAIN_WORDS = [
    "defence", "defense", "robotic", "industrial", "energy", "security", "semiconductor", "quantum", "manufactur",
]  # fmt: skip
_ELITE = ["eth", "kit", "epfl", "tum", "lmu", "max planck", "fraunhofer", "dlr", "cern", "mit"]
_FOUNDER_WORDS = [
    "hackathon", "founder", "startup", "pitch", "demo day", "venture", "entrepreneur", "incubat", "accelerat",
    "spin-off", "spinoff", "build",
]  # fmt: skip
_ADMIN_WORDS = [
    "administrat", "alumni reunion", "info session", "information session", "open day", "career fair", "orientation",
    "graduation", "faculty meeting", "seminar series", "colloquium", "lecture series", "verwaltung",
    "infoveranstaltung", "tag der offenen",
]  # fmt: skip


def city_hours(city: Any) -> float | None:
    c = (city or "").strip()
    if c in GAZETTEER:
        return GAZETTEER[c][2]
    return None


def suggest(ev: Mapping[str, Any]) -> dict[str, int]:
    """Propose ladder selections from type / city / organizer / name. The operator overrides them in the UI."""
    text = " ".join(str(ev.get(k, "")) for k in ("name", "organizer", "domains", "notes")).lower()
    sel = {
        "founder_density": 8,
        "tech_talent": 7,
        "earliness": 6,
        "domain_fit": 6,
        "network_value": 4,
        "accessibility": 4,
        "serendipity": 3,
    }
    sel.update(_KEY.get(ev.get("type", ""), {}))
    if any(w in text for w in _DOMAIN_WORDS):
        sel["domain_fit"] = 15 if any(w in text for w in _CORE_DOMAIN_WORDS) else 11
    founderish = any(w in text for w in _FOUNDER_WORDS) or ev.get("type") in (
        "hackathon",
        "founder_meetup",
        "demo_day",
        "accelerator",
    )
    adminish = any(w in text for w in _ADMIN_WORDS)
    if any(w in text for w in _ELITE) and founderish and not adminish:
        # elite institution only lifts the score when the EVENT itself is founder/technical-builder content
        sel["tech_talent"] = 20
        sel["network_value"] = max(sel["network_value"], 7)
    if adminish:
        sel["founder_density"] = min(sel["founder_density"], 8)
        sel["earliness"] = min(sel["earliness"], 6)
        sel["tech_talent"] = min(sel["tech_talent"], 7)
        sel["serendipity"] = min(sel["serendipity"], 3)
    h = city_hours(ev.get("city", ""))
    if h is not None:
        sel["accessibility"] = 10 if h <= 1 else 7 if h <= 3.5 else 4 if h <= 6 else 2
    return sel


def score_of(ev: Mapping[str, Any]) -> dict[str, Any]:
    parts = ev.get("score_parts") or suggest(ev)
    total, evidence = 0, []
    for k in DIM_ORDER:
        pts = int(parts.get(k, 0))
        ladder = DIMS[k]["ladder"]
        step = min(ladder, key=lambda s: abs(s[0] - pts))  # snap to the nearest ladder step
        total += step[0]
        evidence.append((DIMS[k]["label"], step[0], DIMS[k]["max"], step[1]))
    band = (
        "HIGH PRIORITY" if total >= 75 else "WORTH ATTENDING" if total >= 55 else "OPTIONAL" if total >= 40 else "SKIP"
    )
    top = sorted(evidence, key=lambda e: -(e[1] / e[2]))[:3]
    why = "; ".join(e[3] for e in top)
    return {"total": total, "band": band, "evidence": evidence, "why": why}


# ── WHEN: the canonical date view ───────────────────────────────────────────────────────────────────────────────
def read_when(e: Mapping[str, Any], side: str, today: date, pins: Pins | None = None) -> tuple[date | None, str, str]:
    """``parse_when`` of ``e[side]``: the stored result when the value is pinned (free text, a date or no date), and
    no date for a value the old ``parse_when`` crashed on."""
    if pins is not None and side in pins:
        return pins[side], "", ""
    raw = e.get(side)
    if raw is not None and not isinstance(raw, str):
        return None, "", ""
    try:
        return parse_when(raw, today=today)
    except (ValueError, OverflowError):
        return None, "", ""


def weekend_window(today: date) -> tuple[date, date]:
    """The Saturday-Sunday interval relevant to today: Mon-Fri -> the upcoming weekend, Sat/Sun -> the current one."""
    wd = today.weekday()  # Mon=0 .. Sun=6
    sat = today + timedelta(days=(5 - wd)) if wd < 5 else today - timedelta(days=(wd - 5))
    return sat, sat + timedelta(days=1)


def event_when(e: Mapping[str, Any], today: date, pins: Pins | None = None) -> dict[str, Any]:
    """Normalised, classification-ready view of an event's dates. Never invents a time or a venue.
    group: 'weekend' | 'next7' | 'later' | 'past' | 'undated' (mutually exclusive, in that priority)."""
    sd, st, tz_note = read_when(e, "start", today, pins)
    ed, et, _ = read_when(e, "end", today, pins)
    if sd is None:
        return {
            "start_date": "",
            "end_date": "",
            "start_time": "",
            "end_time": "",
            "tz": "",
            "weekday": "",
            "weekend": False,
            "ongoing": False,
            "days_until": None,
            "group": "undated",
            "multi_day": False,
        }
    if ed is None or ed < sd:
        ed = sd
    sat, sun = weekend_window(today)
    weekend = sd <= sun and ed >= sat
    ongoing = sd <= today <= ed
    if ed < today:
        group = "past"
    elif weekend:
        group = "weekend"
    elif sd <= today + timedelta(days=7):
        group = "next7"
    else:
        group = "later"
    return {
        "start_date": sd.isoformat(),
        "end_date": ed.isoformat(),
        "start_time": st,
        "end_time": et,
        "tz": tz_note,
        "weekday": sd.strftime("%A"),
        "end_weekday": ed.strftime("%A"),
        "weekend": weekend,
        "ongoing": ongoing,
        "days_until": (sd - today).days,
        "group": group,
        "multi_day": ed > sd,
        "weekend_window": [sat.isoformat(), sun.isoformat()],
    }


def event_span(e: Mapping[str, Any], today: date, pins: Pins | None = None) -> tuple[datetime | None, datetime | None]:
    """-> (start, exclusive end), Berlin-aware, or (None, None). A date-only event spans its whole calendar day(s)."""
    sd, st, _ = read_when(e, "start", today, pins)
    if sd is None:
        return None, None
    ed, et, _ = read_when(e, "end", today, pins)
    if ed is None or ed < sd:
        ed, et = sd, (et if ed == sd else "")
    try:
        start_dt = _aware(sd, st)
        end_dt = _aware(ed, et, end=True) if not et else _aware(ed, et)
        if end_dt <= start_dt:  # e.g. same-day event with only a start time: assume it ends that day
            end_dt = _aware(sd, "", end=True)
    except (ValueError, OverflowError):  # the old code raised here (a "24:00" time): no span, for this event only
        return None, None
    return start_dt, end_dt


def overlaps(e: Mapping[str, Any], start_iso: str, end_iso: str, today: date, pins: Pins | None = None) -> bool:
    """Half-open overlap: event_end > window_start AND event_start < window_end (Europe/Berlin). The window is
    calendar-inclusive: 00:00 on ``start_iso`` to 00:00 the day after ``end_iso``."""
    s, en = event_span(e, today, pins)
    if s is None or en is None:
        return False
    try:
        ws = _aware(date.fromisoformat(start_iso[:10]), "")
        we = _aware(date.fromisoformat(end_iso[:10]), "", end=True)
    except ValueError:
        return False
    return en > ws and s < we


def price_state(e: Mapping[str, Any]) -> str:
    p = e.get("price") if isinstance(e.get("price"), dict) else {}
    if not p or (p.get("amount") in (None, "") and p.get("low") in (None, "") and not p.get("availability")):
        return "price unknown"
    if str(p.get("availability", "")).lower().endswith("soldout"):
        return "sold out"
    try:
        amt = float(p.get("amount")) if p.get("amount") not in (None, "") else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        amt = None
    if p.get("low") not in (None, "") and p.get("high") not in (None, ""):
        return "price range"
    if amt is None:
        return "price unknown"
    return "free" if amt == 0 else "paid"


def actionable(e: Mapping[str, Any]) -> dict[str, Any]:
    """Registration actionability from persisted availability: sold out is never 'Register'."""
    st = price_state(e)
    p = e.get("price") if isinstance(e.get("price"), dict) else {}
    assert isinstance(p, dict)
    if st == "sold out":
        wl = (
            p.get("waitlist_url")
            or e.get("waitlist_url")
            or (
                ""
                if "waitlist" not in str(p.get("availability", "")).lower() + str(e.get("notes", "")).lower()
                else (e.get("registration_url") or e.get("url") or "")
            )
        )
        return {
            "state": "waitlist" if wl else "sold_out",
            "label": "Sold out — check waitlist" if wl else "Sold out",
            "url": wl,
            "recommendable": bool(wl),
        }
    url = e.get("registration_url") or e.get("url") or ""
    return {
        "state": "open" if url else "unknown",
        "label": "Register / details ↗" if url else "No registration link",
        "url": url,
        "recommendable": True,
    }


# ── RC2: evidence-based type, assessment, eligibility and ranking ───────────────────────────────────────────────
NEI = "NOT ENOUGH INFORMATION"
_EXCL = re.compile(
    r"\b(writing (party|club|session)|write-?in|run(ners?|ning) club|running|jogging|5k|10k|marathon|karaoke|quiz night|pub quiz|hikes?|"
    r"party|brunch|wine tasting|beer tasting|comedy|concert|dj set|open mic|yoga|pilates|meditation|wellness|breathwork|fitness|"
    r"workout|bootcamp class|language exchange|conversation club|tandem|book club|salsa|dance class|hiking|bike ride|cycling|"
    r"football|padel|tennis|tourism|sightseeing|walking tour|church|mass|prayer|bible study|dating|singles|speed dating|"
    r"dinner club|supper club|potluck|picnic|film screening|movie night|board games|gaming night|trivia|cocktail)\b",
    re.I,
)
_FOUNDER = re.compile(
    r"\b(founders?|co-?founders?|start-?ups?|pitch(es|ing)?|pitch (night|competition|day)|demo day|hackathon|hack day|"
    r"accelerator|incubator|venture (lab|builder|studio)|cohort|spin-?(off|out)s?|commerciali[sz]ation|pre-?seed|seed round|"
    r"angel|venture capital|\bvcs?\b|investors?|office hours|founder-led|entrepreneur(s|ship)?|gründer|startup weekend|operators?)\b",
    re.I,
)
_TECH = re.compile(
    r"\b(deep ?tech|robotics?|autonomous|ai|artificial intelligence|machine learning|llm|industrial|manufacturing|semiconductor|"
    r"chips?|quantum|photonic|space|satellite|defen[cs]e|dual-?use|resilience|energy|climate|battery|hydrogen|grid|infrastructure|"
    r"developer|open source|research|laboratory|lab|phd|engineering|hardware|materials|biotech|medtech|cyber(security)?)\b",
    re.I,
)
_RESEARCH_ORG = re.compile(
    r"\b(eth|epfl|kit|tum|tu (munich|münchen|darmstadt|delft|eindhoven|berlin)|max planck|fraunhofer|helmholtz|cern|"
    r"universit(y|ät|é|eit)|institute of technology|dlr|inria|cnrs|imperial|oxford|cambridge)\b",
    re.I,
)
_CANCEL = re.compile(r"cancel|abgesagt|postponed|verschoben|rescheduled", re.I)
_TYPE_RULES = [
    ("hackathon", r"\b(hackathon|hack day|hack week|buildathon)\b"),
    ("demo_day", r"\bdemo ?day\b"),
    ("accelerator", r"\b(accelerator|incubator|cohort|venture (lab|builder|studio)|fellowship|batch)\b"),
    (
        "university",
        r"\b(spin-?(off|out)s?|commerciali[sz]ation|tech transfer|research-to-industry|university|universität)\b",
    ),
    ("conference", r"\b(conference|summit|congress|forum|symposium|kongress)\b"),
    ("founder_meetup", r"\b(founders?|start-?ups?|pitch|entrepreneur|gründer|office hours)\b"),
]
_ACTIVITY = re.compile(
    r"\b(hike|hiking|walk|run|running|ride|cycling|climb|swim|sauna|picnic|bbq|brunch|breakfast|dinner|drinks|beers?|coffee walk)\b",
    re.I,
)
_AUDIENCE = re.compile(
    r"\b(founders?|co-?founders?|operators?|entrepreneurs?|gründer|start-?ups?)\b", re.I
)  # 'builders' alone is not founder context
_NETWORK = re.compile(
    r"\b(networking|network with|meet (other )?(founders|investors|operators|builders|researchers)|introductions?|intros?|connect with|community (of|for)|mingle|1:1s?|matchmaking|office hours|drinks with|meet the (team|organi[sz]ers?)|peer (group|circle))\b",
    re.I,
)
_PITCHY = re.compile(r"\b(pitch(es|ing)?|demo ?day|hackathon|accelerator|incubator|investors?|vcs?|angel)\b", re.I)
_STRONG_FOUNDER = re.compile(r"demo day|hackathon|accelerator|incubator|spin|pitch|cohort", re.I)
_ECO_ORG = re.compile(
    r"\b(accelerator|incubator|venture|ventures|vc|capital|entrepreneur|founders?|startup|innovation|tech transfer|spin-?off)\b",
    re.I,
)
_FOUNDER_NAME = re.compile(
    r"\b(founders?|start-?ups?|pitch(es|ing)?|demo ?day|hackathon|accelerator|incubator|spin-?(off|out)s?|entrepreneurs?|gründer)\b",
    re.I,
)
_FOUNDER_NAME_NO_GRUNDER = re.compile(
    r"\b(founders?|start-?ups?|pitch(es|ing)?|demo ?day|hackathon|accelerator|incubator|spin-?(off|out)s?|entrepreneurs?)\b",
    re.I,
)
_BUILDERS = re.compile(r"\bbuilders?\b", re.I)


def _etext(e: Mapping[str, Any]) -> str:
    return " ".join(
        str(e.get(k) or "")
        for k in ("name", "description", "keywords", "audience", "organizer", "domains", "topics", "notes_source")
    )


def _body(e: Mapping[str, Any]) -> str:
    return " ".join(str(e.get(k) or "") for k in ("description", "audience", "keywords"))


def classify(e: Mapping[str, Any]) -> tuple[str, list[dict[str, str]]]:
    """Evidence-based event type. A source-level / inherited type is NEVER evidence. A hike / run / dinner explicitly
    for founders / operators is an 'outdoor / community founder event', not a pitch night."""
    t = _etext(e)
    ev: list[dict[str, str]] = []
    body = _body(e)
    activity, audience = _ACTIVITY.search(t), _AUDIENCE.search(body)
    if activity and audience and not _PITCHY.search(t):
        ev.append(
            {
                "field": "description/audience",
                "quote": activity.group(0) + " … " + audience.group(0),
                "supports": "type:community_founder",
            }
        )
        return "community_founder", ev
    for typ, rx in _TYPE_RULES:
        m = re.search(rx, t, re.I)
        if m:
            ev.append({"field": "text", "quote": m.group(0), "supports": "type:" + typ})
            return typ, ev
    return "UNKNOWN", ev


def assess(e: Mapping[str, Any]) -> dict[str, Any]:
    """Bands from SOURCE evidence only; every factor carries the quoted evidence. Human score_parts never feed this."""
    t = _etext(e)
    f: list[dict[str, Any]] = []
    founder_hits = [m.group(0) for m in _FOUNDER.finditer(t)][:4]
    tech_hits = [m.group(0) for m in _TECH.finditer(t)][:4]
    org_hits = [m.group(0) for m in _RESEARCH_ORG.finditer(t)][:3]
    strong = sum(1 for h in founder_hits if _STRONG_FOUNDER.search(h))
    founder = "HIGH" if (strong >= 2 or (strong >= 1 and org_hits)) else "MEDIUM" if founder_hits else NEI
    passage, passage_field = "", ""
    for fld in ("audience", "description", "keywords"):
        ft = str(e.get(fld) or "")
        m0 = _FOUNDER.search(ft) or _AUDIENCE.search(ft)
        if m0:
            s0, e0 = max(0, m0.start() - 70), min(len(ft), m0.end() + 90)
            passage = ("…" if s0 else "") + ft[s0:e0].strip() + ("…" if e0 < len(ft) else "")
            passage_field = fld
            break
    if founder_hits:
        f.append(
            {
                "dimension": "founder",
                "band": founder,
                "evidence": sorted(set(founder_hits + org_hits)),
                "passage": passage,
                "passage_field": passage_field,
            }
        )
    n_tech = len(set(h.lower() for h in tech_hits))
    pa = "HIGH" if n_tech >= 2 else "MEDIUM" if n_tech == 1 else NEI
    if tech_hits:
        f.append({"dimension": "project_a", "band": pa, "evidence": sorted(set(tech_hits))})
    org = (e.get("organizer") or "UNKNOWN").strip()
    eco_org = org != "UNKNOWN" and bool(_RESEARCH_ORG.search(org) or _ECO_ORG.search(org))
    net_hits = [
        m.group(0)
        for m in _NETWORK.finditer(
            " ".join(str(e.get(k) or "") for k in ("description", "audience", "keywords", "name"))
        )
    ][:3]
    if eco_org and e.get("type") in ("demo_day", "accelerator", "university", "conference", "hackathon"):
        net = "HIGH"
        net_ev = ["ecosystem-organizer rule: " + org + " hosts a " + str(e.get("type"))]
    elif net_hits:
        net = "MEDIUM"
        net_ev = ["explicit networking evidence: " + ", ".join(net_hits)]
    else:
        net, net_ev = NEI, []
    if net != NEI:
        f.append({"dimension": "networking", "band": net, "evidence": net_ev})
    route = e.get("route") or ""
    loc_known = bool(e.get("city") or e.get("venue") or e.get("format") in ("virtual", "hybrid"))
    if route in ("api", "ics", "json-ld") and org != "UNKNOWN" and loc_known:
        conf = "STRUCTURED, COMPLETE"
    elif route in ("api", "ics", "json-ld", "luma-next-data", "structured"):
        conf = "STRUCTURED"
    elif route in ("watcher",):
        conf = "UNSTRUCTURED"
    else:
        conf = "UNRESOLVED"
    return {
        "founder": founder,
        "project_a": pa,
        "networking": net,
        "confidence": conf,
        "source_data": conf,
        "passage": passage,
        "passage_field": passage_field,
        "relevance_status": "operator verified" if e.get("human_verified") else "needs review",
        "factors": f,
    }


def eligibility(e: Mapping[str, Any], a: Mapping[str, Any], today: date, pins: Pins | None = None) -> dict[str, Any]:
    """HIGH-SIGNAL (auto-recommendable) · NEEDS REVIEW (incomplete) · REJECTED (general / cancelled / past)."""
    t = _etext(e)
    w = e.get("when") or event_when(e, today, pins)
    if _CANCEL.search(str(e.get("event_status") or "")) or _CANCEL.search(str(e.get("name") or "")):
        return {
            "tier": "REJECTED",
            "label": "CANCELLED",
            "reasons": ["event status: " + str(e.get("event_status") or "cancelled in title")],
        }
    if w.get("group") == "past":
        return {"tier": "REJECTED", "label": "PAST", "reasons": ["end date has passed"]}
    if w.get("group") == "undated":
        return {"tier": "NEEDS REVIEW", "label": "NO DATE", "reasons": ["no parseable start date"]}
    excl = _EXCL.search(t)
    body = _body(e)
    founder_ev = _FOUNDER.search(body) or _AUDIENCE.search(body) or _FOUNDER_NAME.search(str(e.get("name") or ""))
    tech_ev = _TECH.search(t) or _RESEARCH_ORG.search(t)
    if excl and not founder_ev:
        if _BUILDERS.search(str(e.get("name") or "") + " " + body):
            return {
                "tier": "NEEDS REVIEW",
                "label": "NEEDS REVIEW",
                "reasons": [
                    "audience passage unavailable — 'builders' alone does not establish founder relevance; verify the source page"
                ],
            }
        return {
            "tier": "REJECTED",
            "label": "GENERAL EVENT",
            "reasons": ["general-public / lifestyle signal: '" + excl.group(0) + "' and no founder/startup evidence"],
        }
    if e.get("human_verified") or e.get("status") == "planned":
        return {"tier": "HIGH-SIGNAL", "label": "VERIFIED BY YOU", "reasons": ["manually verified / GO"]}
    missing = []
    if not str(e.get("url") or "").startswith("http"):
        missing.append("source URL")
    if not (e.get("city") or e.get("venue")) and e.get("format") not in ("virtual", "hybrid"):
        missing.append("location / format")
    if e.get("type") in (None, "", "UNKNOWN"):
        missing.append("event type not supported by evidence")
    if not (founder_ev or tech_ev):
        missing.append("no founder / startup / technical / research signal")
    if a["confidence"] not in ("STRUCTURED, COMPLETE", "STRUCTURED"):
        missing.append("source data " + a["confidence"])
    if a["founder"] == NEI and a["project_a"] == NEI:
        missing.append("founder potential and Project A relevance both unknown")
    if a["founder"] != NEI and not a.get("passage") and not _FOUNDER_NAME_NO_GRUNDER.search(str(e.get("name") or "")):
        missing.append("audience passage unavailable (no description/audience text) — founder relevance not verifiable")
    if missing:
        return {"tier": "NEEDS REVIEW", "label": "NEEDS REVIEW", "reasons": missing}
    return {
        "tier": "HIGH-SIGNAL",
        "label": "HIGH-SIGNAL",
        "reasons": ["future, sourced, located, typed by evidence, founder/technical signal present"],
    }


def rank_score(a: Mapping[str, Any], el: Mapping[str, Any]) -> tuple[int | None, list[dict[str, Any]]]:
    """Sorting number ONLY for HIGH-SIGNAL events with real evidence; exposes factors. Otherwise None."""
    if el["tier"] != "HIGH-SIGNAL" or (a["founder"] == NEI and a["project_a"] == NEI):
        return None, []
    v = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, NEI: 0}
    parts = [
        ("founder potential", v[a["founder"]] * 12),
        ("Project A relevance", v[a["project_a"]] * 10),
        ("networking value", v[a["networking"]] * 5),
        ("source data quality", {"STRUCTURED, COMPLETE": 15, "STRUCTURED": 8}.get(a["confidence"], 0)),
    ]
    return sum(p for _, p in parts), [{"factor": k, "points": p} for k, p in parts]


def canonical(e: Mapping[str, Any], today: date, source_city: str = "", pins: Pins | None = None) -> dict[str, Any]:
    """Additive canonical view (never mutates stored user judgments). ``source_city``: the configured city of the
    event's first source (only used to infer a missing country for the readable place label)."""
    typ, tev = classify(e)
    ce = dict(e)
    ce["type"] = typ if typ != "UNKNOWN" or not e.get("type_human") else e.get("type_human")
    city, cc, orig = event_place.normalize_city(e.get("city", ""), e.get("country", ""))
    ce.update(
        {
            "city": city,
            "country": cc,
            "city_original": orig,
            "organizer": (e.get("organizer") or "").strip() or "UNKNOWN",
            "format": e.get("format") or "UNKNOWN",
            "price_state": price_state(e),
            "route": e.get("route")
            or ((e.get("sources") or [{}])[0].get("provenance") if e.get("sources") else "")
            or ("manual" if not e.get("auto_promoted") else ""),
            "when": event_when(e, today, pins),
            "type_evidence": tev,
        }
    )
    ce["unknowns"] = [
        k
        for k, v in (
            ("time", not ce["when"].get("start_time")),
            ("venue", not e.get("venue")),
            ("organizer", ce["organizer"] == "UNKNOWN"),
            ("price", ce["price_state"] == "price unknown"),
            ("format", ce["format"] == "UNKNOWN"),
        )
        if v
    ]
    a = assess(ce)
    if a["confidence"] == "STRUCTURED, COMPLETE" and ce["unknowns"]:
        a["confidence"] = a["source_data"] = "STRUCTURED"  # same completeness definition as the rendered card
    el = eligibility(ce, a, today, pins)
    rs, factors = rank_score(a, el)
    if el["tier"] == "HIGH-SIGNAL":
        a["relevance_status"] = "operator verified" if e.get("human_verified") else "high-signal (evidence)"
    ce["assessment"] = a
    ce["eligibility"] = el
    ce["rank_score"] = rs
    ce["rank_factors"] = factors
    ce["days_until"] = ce["when"].get("days_until")
    ce["travel_hours"] = city_hours(city)  # date countdown and travel time are separate facts
    ce["action"] = actionable(ce)
    if not ce.get("domains") and (e.get("keywords") or e.get("topics")):
        ce["domains"] = e.get("keywords") or e.get("topics")
    ce["human"] = {"score_parts": e.get("score_parts"), "label": "HUMAN JUDGMENT"} if e.get("score_parts") else None
    ce["place"] = event_place.place(ce, source_city)  # display + filter only
    ce["themes"] = event_place.themes(ce)  # evidenced in the event's own text; never feeds eligibility / ranking
    return ce


def listing(
    events: list[dict[str, Any]],
    today: date,
    source_city: Mapping[Any, str] | None = None,
    pins: Mapping[str, Pins] | None = None,
) -> list[dict[str, Any]]:
    """Canonical events with ``sc`` / ``past``, in the old order: not past first, then start, then the score.
    ``events`` are the current records in their stored order (the sort is stable); ``pins`` maps an event id to its
    persisted free-text dates."""
    src_city = source_city or {}
    pinned = pins or {}
    out = []
    for e in events:
        q = dict(e)
        first = (e.get("sources") or [{}])[0] if isinstance(e.get("sources"), list) else {}
        q.update(canonical(e, today, src_city.get((first or {}).get("source_id"), ""), pinned.get(e.get("id", ""))))
        if e.get("score_parts"):  # operator's own ladder scores: kept, labelled, never turned into facts
            q["sc"] = dict(
                score_of(e),
                human=True,
                why="Your own scoring (human judgment) — see evidence panel for source-backed facts.",
            )
        else:
            rs = q["rank_score"]
            q["sc"] = {
                "total": rs,
                "band": (q["eligibility"]["tier"]),
                "human": False,
                "evidence": [],
                "why": "; ".join(
                    f["dimension"].replace("_", " ") + ": " + f["band"] + " (" + ", ".join(f["evidence"][:3]) + ")"
                    for f in q["assessment"]["factors"]
                )
                or "No source evidence beyond the listing itself.",
            }
        q["past"] = q["when"]["group"] == "past"  # end-aware: an ongoing multi-day event is not past
        out.append(q)

    def start_key(x: dict[str, Any]) -> str:
        pin = pinned.get(x.get("id", ""), {}).get("start")
        return pin.isoformat() if pin else str(x.get("start") or "9999")  # a null start never breaks the sort

    out.sort(key=lambda x: (x["past"], start_key(x), -(x["sc"]["total"] or 0)))
    return out

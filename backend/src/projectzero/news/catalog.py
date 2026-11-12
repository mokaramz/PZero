# ruff: noqa: E501, RUF001
# (protected gold-master data, copied by script from the old modules; see the header)
"""The News catalog (review 028a): constants cut MECHANICALLY from the old ``services/news.py``,
``services/news_sources.py`` and ``services/claims.py`` at revision 6c739b9 by exact line ranges
(``scripts/gen_news_catalog.py``); nothing is retyped. ``tests/news/test_news_port.py`` checks every cut against the
old modules. Pure data.

From ``news.py`` (top level): the store names (``EVENTS``, ``ACTIONS``, ``RUNS``, ``RUN_STATE``, ``COOLDOWN``,
``WEEKLY``), ``EARLY_DAYS``, ``FEEDS`` (the feed order is the ingest order and the sources universe order),
``EVENT_TYPES`` (first match wins: the order is the priority) and ``TYPE_LABEL``, the noise / digest / round / amount
rules, ``GEO_WORDS`` / ``EUROPE`` / ``GEO_LABEL``, ``THEME_WORDS`` / ``PRIORITY_THEMES``, ``SENSOR_FOR``, the 17
``CONCEPTS`` (their dict order and ``sorted`` order are both used), the roundup verbs, ``STATE_LABEL`` and
``OUTCOME_KIND``. From ``news_sources.py``: the store names, ``WINDOWS`` / ``DEFAULT_WINDOW``, the thresholds,
``SCOPES``, the Munich and press-release rules, ``DATABASE_DOMAINS``, ``PUBLICATIONS`` (recognition order),
``_CITE``, ``HIGH_AUTHORITY_PRIOR``, ``HYPOTHESES`` and ``BEST``; its ``EARLY_DAYS`` is the same statement value as
News' (checked by the script, cut once). From ``claims.py``: the domain lists ``claims.classify`` reads.
"""

from __future__ import annotations

import re

# fmt: off
# ── from services/news.py ──
EVENTS = "news/events.json"
ACTIONS = "news/actions.jsonl"
RUNS = "news/runs.jsonl"
RUN_STATE = "news/run_state.json"  # marker of the run in progress (for interrupted-run recovery after a restart)
COOLDOWN = "news/feed_cooldown.json"  # feeds that answered 429: skipped until the time stored here
WEEKLY = "news/weekly.jsonl"
EARLY_DAYS = 14  # first seen at least this long before the event = caught early
FEEDS: list[dict[str, str]] = [
    {"name": "Sifted", "url": "https://sifted.eu/feed", "geo": "EU"},
    {"name": "Tech.eu", "url": "https://tech.eu/feed/", "geo": "EU"},
    {"name": "EU-Startups", "url": "https://www.eu-startups.com/feed/", "geo": "EU"},
    {"name": "Silicon Canals", "url": "https://www.siliconcanals.com/feed/", "geo": "EU"},
    {"name": "Startbase", "url": "https://www.startbase.com/feed/", "geo": "DE"},
    {"name": "deutsche-startups.de", "url": "https://www.deutsche-startups.de/feed/", "geo": "DE"},
    {"name": "Munich Startup", "url": "https://www.munich-startup.de/feed/", "geo": "DE", "city": "Munich"},
    {"name": "Maddyness", "url": "https://www.maddyness.com/feed/", "geo": "FR"},
    {"name": "UKTN", "url": "https://www.uktech.news/feed", "geo": "UK"},
    {"name": "ArcticStartup", "url": "https://arcticstartup.com/feed/", "geo": "NORDICS"},
]
EVENT_TYPES: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "fund",
        "VC fund news",
        re.compile(
            r"\b(fund (i{1,3}|iv|v|vi|\d)\b|closes? .{0,40}\bfund\b|new fund\b|first close|final close|"
            r"launches .{0,30}\bfund\b|fund of funds|venture fund\b)",
            re.I,
        ),
    ),
    (
        "valuation",
        "Valuation milestone",
        re.compile(
            r"\b(unicorn|decacorn|\$?\d+(\.\d+)?\s?(bn|billion|milliarde)\b.{0,30}valuation|valuation of|milliardenbewertung|valued at)\b",
            re.I,
        ),
    ),
    (
        "acquisition",
        "Acquisition",
        re.compile(r"\b(acquires?|acquired|acquisition|takes over|übernimmt|übernahme|rachète|buys)\b", re.I),
    ),
    (
        "shutdown",
        "Shutdown / insolvency",
        re.compile(
            r"\b(insolven\w*|shuts? down|shutting down|bankrupt\w*|winds? down|closes its doors|liquidation)\b", re.I
        ),
    ),
    (
        "funding",
        "Funding round",
        re.compile(
            r"\b(raises?|raised|secures?|secured|closes?|bags|lands|nets|funding|financing|finanzierungsrunde|sammelt|lève|levée|series [a-f]|pre-?seed|seed round)\b"
            # German / French funding phrasing ("Finches erhält 2 Millionen Euro", "X lève 5 millions d'euros")
            r"|\b(erhält|erhalten|holt sich|holt|sichert sich|bekommt|lèvent|a levé|boucle)\b.{0,40}?\d.{0,12}?"
            r"(millionen|mio\.?|milliarden?|millions?|milliards?|euro|€|\$|£|chf)"
            r"|\b(levée de fonds|tour de table|seed-runde|series-[a-f]-runde|wachstumsfinanzierung)\b",
            re.I,
        ),
    ),
    (
        "customer",
        "Customer / contract",
        re.compile(
            r"\b(contract|signs? (a |an )?(deal|agreement)|wins? (a )?tender|customer|framework agreement|order from|selected by)\b",
            re.I,
        ),
    ),
    (
        "regulatory",
        "Regulatory approval",
        re.compile(r"\b(fda|ce mark|approval|approved|certification|zulassung)\b", re.I),
    ),
    ("grant", "Grant", re.compile(r"\b(grant|eic accelerator|horizon europe|förderung|subsid)\w*\b", re.I)),
    (
        "accelerator",
        "Accelerator / programme",
        re.compile(r"\b(accelerator|cohort|y combinator|techstars|batch|fellowship|incubator)\b", re.I),
    ),
    ("partnership", "Partnership", re.compile(r"\b(partners? with|partnership|collaborat\w+|teams up)\b", re.I)),
    (
        "founder",
        "Founder move",
        re.compile(
            r"\b(co-?founder|founder) .{0,30}\b(leaves|steps down|departs|launches|starts|new startup)\b|\bex-\w+ (founders?|team|lead)\b",
            re.I,
        ),
    ),
    ("launch", "Product launch", re.compile(r"\b(launch(es|ed)?|unveils?|introduces?|releases?)\b", re.I)),
    (
        "expansion",
        "Expansion",
        re.compile(r"\b(expands?|expansion|enters|opens (an? )?(office|hub)|us market|new market)\b", re.I),
    ),
    ("hire", "Hire", re.compile(r"\b(appoints?|hires?|names .{0,20}(ceo|cto|cfo)|joins as)\b", re.I)),
]
TYPE_LABEL = {k: lab for k, lab, _ in EVENT_TYPES} | {"other": "Other news", "manual": "Story"}
_NOISE = re.compile(
    r"\b(top \d+|\d+ (startups|companies|tools) (to|that)|how to|podcast|webinar|newsletter|jobs?\b|"
    r"week in|weekly|recap|roundup|round-up|opinion|op-ed|sponsored|partner content|event:|tickets|"
    r"giveaway|deal of the day|\bwhat we learned\b|lps’|lps'|report:)",
    re.I,
)
_DIGEST = re.compile(
    r"^#(startupticker|dealmonitor|wochenrückblick|gastbeitrag|dhdl|startupstowatch|interview|podcast)\b|"
    r"wochenrückblick|startupnews zum wochenende|\bkw \d{1,2}/\d{4}|cette semaine",
    re.I,
)
_ROUND = re.compile(r"\b(pre-?seed|seed|series [a-f]|growth round|bridge round)\b", re.I)
_AMOUNT = re.compile(
    r"(?:(€|\$|£|eur|usd|chf|gbp)\s?(\d+(?:[.,]\d+)?)\s?(bn|billion|b\b|m|million|mio|k)?|"
    r"(\d+(?:[.,]\d+)?)\s?(bn|billion|milliarden?|milliards?|m|millions?|millionen|mio)\.?\s?(?:d['’]|de )?"
    r"(€|\$|£|eur|euros?|usd|chf|dollars?|pounds?|pfund|franken|francs?))",
    re.I,
)
GEO_WORDS: dict[str, str] = {
    "DE": r"german|germany|deutsch|munich|münchen|berlin|hamburg|cologne|köln|frankfurt|stuttgart|karlsruhe|dresden|heidelberg|darmstadt|aachen",
    "CH": r"swiss|switzerland|schweiz|zurich|zürich|lausanne|geneva|genf|basel|eth\b|epfl",
    "FR": r"french|france|paris|lyon|grenoble|toulouse|station f",
    "UK": r"\buk\b|british|britain|london|cambridge|oxford|edinburgh|manchester|england",
    "NORDICS": r"finnish|finland|helsinki|swedish|sweden|stockholm|danish|denmark|copenhagen|norway|oslo|estonia|tallinn",
    "US": r"\bu\.s\.|american|silicon valley|san francisco|new york|boston",
}
EUROPE = {"DE", "CH", "FR", "UK", "NORDICS", "EU"}
GEO_LABEL: dict[str, str] = {
    "DE": "Germany",
    "CH": "Switzerland",
    "FR": "France",
    "UK": "the UK",
    "NORDICS": "the Nordics",
    "EU": "Europe",
}
THEME_WORDS: dict[str, str] = {
    "ai": r"\bai\b|artificial intelligence|machine learning|\bllm|agentic|genai|foundation model",
    "robotics": r"robot\w*|physical ai|humanoid|automation|drone",
    "deeptech": r"deep ?tech|quantum|semiconductor|chip|photonic|materials|fusion|biotech|spin-?off|spinout|research",
    "industrial": r"industrial|manufactur\w*|factory|supply chain|logistics|energy|grid|battery|infrastructure",
    "defence": r"defen[cs]e|dual-use|military|security|nato",
    "climate": r"climate|carbon|cleantech|decarboni|renewable|hydrogen",
    "enterprise": r"\bsaas\b|enterprise|b2b|software|cyber",
}
PRIORITY_THEMES = {"ai", "robotics", "deeptech", "industrial", "defence", "climate", "enterprise"}
SENSOR_FOR: dict[str, str] = {
    "university_lab": "university spinout lists (TUM Venture Labs, UnternehmerTUM, ETH / EPFL, HIGHEST) + Scout 00 research lanes",
    "research_paper": "Founder Radar (OpenAlex / papers) + Scout 00 research lanes",
    "incorporation": "official registers (Handelsregister paste, Zefix, Companies House) on watched names",
    "accelerator": "accelerator / programme watchers (XPRENEURS, Venture Kick, CDL, EIC)",
    "grant": "grant sources (EXIST, Innosuisse, EIC, UKRI, NIH/NSF)",
    "early_funding": "funding-news feeds (Tech.eu, EU-Startups, Startbase, Munich Startup) — usually too late for edge",
    "founder_move": "Founder Radar + Network watchlist (talent exits)",
    "github": "Founder Radar (GitHub)",
    "patent": "Founder Radar (patent inventors)",
    "customer": "WATCH page checks on the company's news page",
    "event": "Events (demo days, competitions)",
    "ecosystem": "Ecosystems coverage (city × signal family)",
}
CONCEPTS: dict[str, dict[str, str]] = {
    "pre_seed": {
        "title": "What is pre-seed?",
        "text": "The very first outside money, usually €0.2–2M from angels or small funds, often before a product or revenue. Investors bet mostly on the founders and the insight.",
    },
    "seed": {
        "title": "What is a seed round?",
        "text": "Typically €1–5M to find product-market fit: first customers, first team. Investors want proof the problem is real and the team can sell.",
    },
    "series_a": {
        "title": "What is Series A?",
        "text": "Usually €5–20M once a repeatable way to win customers exists. The question changes from 'is this real?' to 'can this scale?'.",
    },
    "series_b": {
        "title": "What is Series B and later?",
        "text": "Larger rounds (€20M+) to scale something that already works: more markets, more sales, more product. Early-stage edge is mostly gone by now.",
    },
    "valuation": {
        "title": "What does a valuation mean?",
        "text": "The price of the whole company implied by a deal. A $1B 'unicorn' valuation is a market signal, not cash in the bank — and a small share sale can set it.",
    },
    "secondary": {
        "title": "What is a secondary sale?",
        "text": "Existing shareholders (often employees or early investors) sell shares to new investors. The company receives no new money, but the price sets a new valuation.",
    },
    "unicorn": {
        "title": "Why can a company become a unicorn without a normal round?",
        "text": "A valuation can be set by any priced transaction — including a secondary sale. So 'unicorn' says what buyers paid per share, not how much the company raised.",
    },
    "spinout": {
        "title": "What is a spinout?",
        "text": "A company created from university research, often by PhDs or researchers. The technology is deep, but the team must learn to sell — and IP terms with the university matter.",
    },
    "physical_ai": {
        "title": "Why do investors care about physical AI?",
        "text": "AI that acts in the physical world (robots, machines). Labour shortages and cheaper sensors make automation of small factories newly economical — a large, under-served market.",
    },
    "pilot_vs_contract": {
        "title": "Why is a customer announcement important?",
        "text": "A paid contract proves someone values the product enough to pay; a free pilot only proves interest. Ask: paid or not, and what converts it?",
    },
    "acquisition": {
        "title": "What does an acquisition tell an investor?",
        "text": "It shows who values the technology and at what price. Small acquisitions are often acqui-hires (buying the team); large ones signal a strategic market.",
    },
    "shutdown": {
        "title": "What can a shutdown teach?",
        "text": "Failures show which assumptions broke: market too small, sales cycle too long, money ran out before traction. They are the best free lessons in venture.",
    },
    "grant": {
        "title": "Why do grants matter early?",
        "text": "Grants are non-dilutive money (no shares given). For deep-tech teams they are often the first external validation — and a public, dated signal.",
    },
    "accelerator": {
        "title": "What does an accelerator signal?",
        "text": "Selection by a strong programme is an early, public filter on the team. Cohort lists are among the earliest places a company appears.",
    },
    "lead_investor": {
        "title": "What is a lead investor?",
        "text": "The fund that sets the terms and usually invests the most. Who leads tells you who did the deepest diligence.",
    },
    "dual_use": {
        "title": "What is dual-use?",
        "text": "Technology with both civil and defence applications. It opens public procurement budgets but brings export rules and reputational questions.",
    },
    "us_expansion": {
        "title": "Why do European startups expand to the US?",
        "text": "Larger single market, faster enterprise buying and bigger later rounds. It is also a sign the company is moving beyond early stage.",
    },
}
_EVENT_VERBS = re.compile(
    r"\b(raises?|secures?|bags|lands|closes|acquires|buys|launches|signs|partners|expands|hires)\b", re.I
)
STATE_LABEL: dict[str, str] = {
    "CAUGHT_EARLY": "Caught early",
    "KNOWN_LATE": "Known, but late",
    "MISSED": "Missed",
    "HISTORICAL": "Historical learning case",
    "NOT_RELEVANT": "Not relevant to Project Zero",
    "UNKNOWN": "Not seen by Project Zero — not yet reviewed",
}
OUTCOME_KIND: dict[str, str] = {
    "funding": "institutional_round",
    "valuation": "institutional_round",
    "acquisition": "acquisition",
    "customer": "commercial_milestone",
    "accelerator": "accelerator",
    "shutdown": "shutdown",
}
# ── from services/news_sources.py ──
SNAPSHOT = "news/source_metrics.json"
STATE = "news/source_state.json"
LOG = "news/source_log.jsonl"
DISAGREE = "news/disagreements.jsonl"
HISTORY = "news/source_history.jsonl"
EXTRA_FEEDS = "news/feeds_extra.json"
WINDOWS: dict[str, int | None] = {"30": 30, "90": 90, "180": 180, "all": None}
DEFAULT_WINDOW = "90"
MIN_OVERLAP = 8  # shared events needed before "unique" / "secondary" mean anything
MIN_COVERED = 3  # a "best for coverage" leader must have covered at least this many events
SCOPES: dict[str, str] = {
    "EUROPE": "Europe",
    "DE": "Germany",
    "FR": "France",
    "UK": "UK",
    "CH": "Switzerland",
    "NORDICS": "Nordics",
    "MUNICH": "Munich",
    "AI": "AI",
    "DEEPTECH": "Physical AI / deeptech",
}
_MUNICH = re.compile(r"munich|münchen|garching|\btum\b|unternehmertum", re.I)
_PR = re.compile(
    r"\b(press release|pressemitteilung|prnewswire|business wire|globenewswire|\(ots\)|sponsored|"
    r"communiqué|announced today)\b",
    re.I,
)
CANDIDATE_MIN_EVENTS = 3  # one interesting article is not a source
DATABASE_DOMAINS = ("dealroom.co", "crunchbase.com", "pitchbook.com", "tracxn.com", "cbinsights.com")
PUBLICATIONS: dict[str, tuple[str, str]] = {
    r"Reuters": ("Reuters", "reuters.com"),
    r"Bloomberg": ("Bloomberg", "bloomberg.com"),
    r"Financial Times|\bFT\b": ("Financial Times", "ft.com"),
    r"Handelsblatt": ("Handelsblatt", "handelsblatt.com"),
    r"TechCrunch": ("TechCrunch", "techcrunch.com"),
    r"Gründerszene|Gruenderszene": ("Gründerszene", "gruenderszene.de"),
    r"The Information": ("The Information", "theinformation.com"),
    r"Les Echos": ("Les Echos", "lesechos.fr"),
    r"Business Insider": ("Business Insider", "businessinsider.com"),
    r"Frankfurter Allgemeine|\bFAZ\b": ("FAZ", "faz.net"),
    r"Süddeutsche": ("Süddeutsche Zeitung", "sueddeutsche.de"),
    r"Tagesspiegel": ("Tagesspiegel", "tagesspiegel.de"),
    r"\bNZZ\b|Neue Zürcher": ("NZZ", "nzz.ch"),
    r"Handelszeitung": ("Handelszeitung", "handelszeitung.ch"),
    r"Usine Digitale": ("L'Usine Digitale", "usine-digitale.fr"),
    r"Breakit": ("Breakit", "breakit.se"),
    r"Børsen|Borsen": ("Børsen", "borsen.dk"),
    r"WirtschaftsWoche|\bWiWo\b": ("WirtschaftsWoche", "wiwo.de"),
    r"Manager Magazin": ("Manager Magazin", "manager-magazin.de"),
    r"Wall Street Journal|\bWSJ\b": ("Wall Street Journal", "wsj.com"),
    r"Le Monde": ("Le Monde", "lemonde.fr"),
    r"Trending Topics": ("Trending Topics", "trendingtopics.eu"),
    r"Brutkasten": ("Brutkasten", "brutkasten.com"),
    r"FinSMEs": ("FinSMEs", "finsmes.com"),
    r"The Next Web|\bTNW\b": ("The Next Web", "thenextweb.com"),
    r"Dealroom": ("Dealroom", "dealroom.co"),
    r"Crunchbase": ("Crunchbase", "crunchbase.com"),
}
_CITE = r"(?i:first reported by|reported by|according to|as reported by|citing|via|laut|selon|d'après|berichtet(?:e)?)"
HIGH_AUTHORITY_PRIOR = (
    "reuters.com",
    "bloomberg.com",
    "ft.com",
    "wsj.com",
    "handelsblatt.com",
    "lesechos.fr",
    "nzz.ch",
)
HYPOTHESES: dict[str, str] = {
    "Sifted": "likely strong Europe-wide startup intelligence",
    "Tech.eu": "likely strong broad European coverage",
    "Munich Startup": "potentially strong regional / early Munich signal",
    "Startbase": "potentially useful Germany ecosystem coverage",
    "deutsche-startups.de": "potential Germany specialist coverage",
    "Maddyness": "potential strong France signal",
    "UKTN": "potential strong UK specialist coverage",
    "ArcticStartup": "potential Nordic / Baltic regional value",
    "EU-Startups": "potential broad coverage — test originality / noise",
    "Silicon Canals": "test current startup relevance — editorial positioning may have broadened",
    "startupticker.ch": "potential strong Swiss regional intelligence",
    "Reuters": "potential confirmation / benchmark role, not necessarily sourcing alpha",
}
BEST: list[tuple[str, str, str, str | None, int]] = [
    ("EUROPE", "Best for Europe-wide coverage", "recall", "EUROPE", 15),
    ("DE", "Best for Germany", "recall", "DE", 8),
    ("FR", "Best for France", "recall", "FR", 8),
    ("UK", "Best for the UK", "recall", "UK", 8),
    ("CH", "Best for Switzerland", "recall", "CH", 8),
    ("NORDICS", "Best for the Nordics", "recall", "NORDICS", 8),
    ("MUNICH", "Best for Munich", "recall", "MUNICH", 5),
    ("EARLY", "Best for early signals", "early", None, 3),
    ("CONFIRM", "Best for fact confirmation", "authority", None, 8),
    ("UNIQUE", "Best for unique discovery", "unique", None, 3),
    ("DEEPTECH", "Best for physical AI / deeptech", "recall", "DEEPTECH", 8),
    ("TECH", "Best technical reliability", "technical", None, 7),
]
# ── from services/claims.py ──
REGISTRY_OFFICIAL = ("virk.dk", "cvr.dk", "handelsregister.de", "unternehmensregister.de", "companieshouse.gov.uk",
                     "company-information.service.gov.uk", "zefix.ch", "zefix.admin.ch", "bolagsverket.se",
                     "ariregister.rik.ee", "kvk.nl", "infogreffe.fr", "registroimprese.it", "ytj.fi", "prh.fi",
                     "brreg.no", "firmenbuch.at", "registrucentras.lt", "lursoft.lv", "kbopub.economie.fgov.be")
REGISTRY_MIRROR = ("northdata.com", "northdata.de", "profiler.dk", "ownr.dk", "proff.dk", "proff.se", "proff.no",
                   "opencorporates.com", "pappers.fr", "firmenwissen.de", "allabolag.se", "companycheck.co.uk",
                   "endole.co.uk", "moneyhouse.ch", "companyhouse.de", "firmenabc.at", "unternehmensverzeichnis.org")
PROGRAM = ("venturekick.ch", "bayern-innovativ.de", "highest-darmstadt.de", "unternehmertum.de", "esa.int",
           "eitdigital.eu", "eitinnoenergy.com", "ycombinator.com", "entrepreneurfirst.com", "stationf.co",
           "deeptechfounders.com", "inriastartupstudio.fr", "climate-kic.org", "techstars.com", "seedcamp.com",
           "masschallenge.org", "plugandplaytechcenter.com", "venture.ch", "swissparks.ch", "epfl.ch", "ethz.ch",
           "tum.de", "kit.edu", "rwth-aachen.de", "tudelft.nl", "kth.se", "aalto.fi", "imperial.ac.uk", "ox.ac.uk",
           "cam.ac.uk", "ucl.ac.uk")
GOVERNMENT = ("cordis.europa.eu", "europa.eu", "gtr.ukri.org", "ukri.org", "sbir.gov", "nih.gov", "nsf.gov",
              "diana.nato.int", "nato.int", "sprind.org", "innosuisse.ch", "bmwk.de", "exist.de", "foerderdatenbank.de",
              "bpifrance.fr", "eifo.dk", "business-finland.fi", "vinnova.se", "gov.uk", "bund.de", "admin.ch")
MEDIA = ("tech.eu", "sifted.eu", "techcrunch.com", "eu-startups.com", "techfundingnews.com", "arcticstartup.com",
         "munich-startup.de", "startupticker.ch", "gruenderszene.de", "handelsblatt.com", "altinget.dk", "di.se",
         "fintech.garden", "businessinsider.com", "reuters.com", "bloomberg.com", "ft.com", "finsmes.com",
         "siliconcanals.com", "maddyness.com", "deutsche-startups.de", "trendingtopics.eu", "startupvalley.news",
         "breakit.se", "borsen.dk", "berlingske.dk", "theinformation.com", "venturebeat.com", "thenextweb.com",
         "wamda.com", "uktech.news", "businesscloud.co.uk", "insurtechinsights.com", "via.ritzau.dk", "ritzau.dk")
AGGREGATOR = ("crunchbase.com", "dealroom.co", "pitchbook.com", "tracxn.com", "cbinsights.com")
SOCIAL = ("linkedin.com", "x.com", "twitter.com", "facebook.com", "instagram.com", "youtube.com", "medium.com")
PRESS_WIRE = ("prnewswire.com", "businesswire.com", "globenewswire.com", "einpresswire.com", "presseportal.de")
# fmt: on

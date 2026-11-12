# ruff: noqa: E501
# (protected gold-master data and repairs, copied by script from the old modules; see the header)
"""The Deal Flow source catalog (review 021): constants and registry repairs cut MECHANICALLY from the old
``domain/connectors.py`` and ``domain/sources_v2.py`` at revision 6c739b9 by exact top-level line ranges
(``scripts/gen_sources_catalog.py``); nothing is retyped. ``tests/dealflow/test_sources_catalog.py`` checks every
string literal against the old modules. Pure data and pure functions: no I/O.

From ``connectors.py``: the hardcoded lists the old inbox served (``PRE_COMPANY_PAGES``, ``FEEDS``,
``MANUAL_SOURCES``), the coverage constants (``KIND_WEIGHT``, ``GEOS``, ``GEO_LABEL``, ``SECTORS``,
``SECTOR_LABEL``), the read-time ``_REPAIRS``. From ``sources_v2.py``: ``URL_REPAIRS``, ``URL_REPAIRS_MULTI``,
``NOTE_REPAIRS`` and ``registry_entries()``.
"""

from __future__ import annotations

from typing import Any

# fmt: off
# ── from domain/connectors.py ──
PRE_COMPANY_PAGES = [
    {
        "name": "NATO DIANA — cohort & news",
        "url": "https://www.diana.nato.int/connect.html",
        "location": "NATO",
        "country": "EU",
        "archetypes": [5, 6, 8],
    },
    {
        "name": "Palladion Defence Accelerator (UniBw Munich)",
        "url": "https://www.unibw.de/diana",
        "location": "Munich",
        "country": "DE",
        "archetypes": [5, 6],
    },
    {
        "name": "TUM Venture Labs",
        "url": "https://www.tum-venture-labs.de/",
        "location": "Munich",
        "country": "DE",
        "archetypes": [5, 6, 7, 10, 14],
    },
    {
        "name": "UnternehmerTUM / XPRENEURS",
        "url": "https://xpreneurs.io/",
        "location": "Munich",
        "country": "DE",
        "archetypes": [1, 5, 6, 7, 10],
    },
    {
        "name": "EUDIS — EU Defence Innovation Scheme",
        "url": "https://eudis.europa.eu/",
        "location": "EU",
        "country": "EU",
        "archetypes": [5, 6],
    },
    {
        "name": "EIC — European Innovation Council news",
        "url": "https://eic.ec.europa.eu/news_en",
        "location": "EU",
        "country": "EU",
        "archetypes": [7, 8, 10, 14],
    },
    {
        "name": "Venture Kick — weekly winners",
        "url": "https://www.venturekick.ch/index.cfm?page=135425&backpage=135422&jumptoanchor=news-box",
        "location": "Switzerland",
        "country": "CH",
        "archetypes": [7, 10, 14],
    },
    {
        "name": "ETH Zurich spin-offs",
        "url": "https://ethz.ch/en/industry/entrepreneurship/spin-offs.html",
        "location": "Zürich",
        "country": "CH",
        "archetypes": [6, 7, 10, 14],
    },
    {
        "name": "EXIST — news",
        "url": "https://www.exist.de/EXIST/Navigation/DE/Aktuelles/Meldungen/meldungen.html",
        "location": "Germany",
        "country": "DE",
        "archetypes": [6, 7, 10, 14],
    },
    {
        "name": "Fraunhofer Venture",
        "url": "https://www.fraunhoferventure.de/",
        "location": "Germany",
        "country": "DE",
        "archetypes": [6, 7, 10],
    },
    {
        "name": "HIGHEST (TU Darmstadt registry)",
        "url": "https://highest-darmstadt.de/en/fuer-unternehmen/start-ups-1/",
        "location": "Darmstadt",
        "country": "DE",
        "archetypes": [4, 13],
    },
]

FEEDS = [
    {"name": "Tech.eu", "url": "https://tech.eu/feed/"},
    {"name": "EU-Startups", "url": "https://www.eu-startups.com/feed/"},
    {"name": "ArcticStartup", "url": "https://arcticstartup.com/feed/"},
    {"name": "Startbase", "url": "https://www.startbase.com/feed/"},
    {"name": "Munich Startup", "url": "https://www.munich-startup.de/feed/"},
    {"name": "startupticker.ch", "url": "https://www.startupticker.ch/en/rss"},
]

MANUAL_SOURCES = [
    {
        "name": "LinkedIn stealth watchlist (re-targeted)",
        "url": "https://www.linkedin.com/search/results/people/?keywords=stealth%20founder",
        "how": "Alumni of Helsing, Quantum Systems, ARX, STARK, Isar Aerospace; senior people at Siemens, Bosch, TRUMPF, DB Schenker, Kühne+Nagel, DHL, Allianz, Munich Re, BASF; ex-McKinsey/BCG industrial & defence practices; ex-officers. Manual by design — scraping is unreliable and against LinkedIn's terms.",
    },
    {
        "name": "Project A Resilience Tech newsletter — jobs board",
        "url": "https://resiliencetech.project-a.com/",
        "how": "Where defence talent is hiring = where the next spinouts come from. Read weekly.",
    },
    {
        "name": "Transfer-office coffees",
        "url": "https://www.tum-venture-labs.de/",
        "how": "One conversation per week: TUM Venture Labs, Palladion, ETH, HIGHEST. Ask 'who spins out next quarter?'",
    },
    {
        "name": "German Handelsregister",
        "url": "https://www.handelsregister.de/rp_web/erweitertesuche.xhtml",
        "how": "No API. Ask Omar for startupdetector/NorthData access. Manual only for a specific name.",
    },
    {
        "name": "Omar (the learning loop)",
        "url": "https://www.project-a.vc/team",
        "how": "Friday: 'Which of these would you take a call with, and why?'",
    },
]

KIND_WEIGHT = {"api": 3.0, "dataset": 3.0, "ics": 3.0, "rss": 1.5, "watcher": 1.0, "manual": 0.5}

GEOS = ["DACH", "CH", "NORD", "BNL", "FR", "UK", "SEU", "EU", "US", "CA"]

GEO_LABEL = {
    "DACH": "DACH",
    "CH": "Switzerland",
    "NORD": "Nordics",
    "BNL": "Benelux",
    "FR": "France",
    "UK": "UK/Ireland",
    "SEU": "South/CEE",
    "EU": "EU-wide",
    "US": "USA",
    "CA": "Canada",
}

SECTORS = ["ai_sw", "deeptech", "defence", "robotics", "space", "climate", "semis_quantum", "bio"]

SECTOR_LABEL = {
    "ai_sw": "AI/SW",
    "deeptech": "Industrial/Deeptech",
    "defence": "Defence",
    "robotics": "Robotics",
    "space": "Space",
    "climate": "Climate/Energy",
    "semis_quantum": "Semis/Quantum",
    "bio": "Bio (opp.)",
}

_REPAIRS = [
    (
        lambda s: "DIANA" in s["name"].upper() and s["kind"] == "watcher",
        {
            "url": "https://www.diana.nato.int/about-diana/2026-cohort-of-companies.html",
            "notes": "Yearly cohort URL (new .../20XX-cohort... each December). Real scan saw HTTP 403: the site runs bot protection; the scanner now sends a normal browser user-agent, which often passes. If 403 persists in your scans, this one is a 5-minute manual check each December when the cohort drops — the failure stays visible here either way.",
        },
    ),
    (
        lambda s: (
            s["kind"] == "watcher"
            and "ETH" in s["name"]
            and ("transfer" in s["name"].lower() or "spin" in s["name"].lower() or "Entrepreneurship" in s["name"])
        ),
        {
            "url": "https://entrepreneurship.ethz.ch/startup-stories/explore-startup-portraits-and-success-stories/spinoff/uebersicht-eth-spin-offs.html",
            "name": "ETH Zurich spin-offs (official list — MANUAL)",
            "enabled": False,
            "notes": "Verified 2026-09: the official list is JavaScript-rendered (the table is empty without JS), so a plain-HTTP watcher can never see it — that is why the baseline was 0. Cannot be automated reliably from this tool: 2-minute manual check monthly. Automated coverage of ETH flow continues via Venture Kick and the static D-INFK list below.",
        },
    ),
    (lambda s: False, {}),
    (
        lambda s: "startupticker" in s["name"].lower(),
        {
            "url": "https://www.startupticker.ch/en/news",
            "kind": "watcher",
            "parser": "page_diff",
            "name": "startupticker.ch — news page (Swiss)",
            "notes": "Repaired 2026-09: the RSS feed was retired (old URL now redirects to a welcome page); watching the server-rendered news list instead.",
        },
    ),
    (
        lambda s: s["id"] == "uk-gtr",
        {
            "url": "https://gtr.ukri.org/api/search/project",
            "notes": "Repaired 2026-09: GtR search API moved to /api/search/project (official notice); parser falls back to the legacy /gtr/api/projects if needed.",
        },
    ),
    (
        lambda s: s["id"] == "eu-cordis",
        {
            "notes": "Parser tries three CORDIS RSS URL variants; if all fail the report names them — the search-RSS route has changed format before."
        },
    ),
    (
        lambda s: s["id"] == "eu-eic-acc",
        {
            "url": "https://eic.ec.europa.eu/news_en",
            "name": "EIC news — funded rounds (Accelerator / Pathfinder / Transition)",
            "sectors": ["deeptech", "climate", "semis_quantum", "bio"],
            "notes": "Repaired 2026-09: the per-programme funded-projects pages were retired; every funding round is announced on the EIC news stream (company names on the round pages).",
        },
    ),
    (
        lambda s: s["id"] in ("eu-eic-path", "eu-eic-trans"),
        {
            "enabled": False,
            "notes": "Consolidated 2026-09 into the EIC news watcher above (old funded-projects pages retired). Kept here, disabled, for transparency — not silently dropped.",
        },
    ),
    (
        lambda s: s["id"].startswith("legacy-") and s["name"].strip().upper().startswith("EIC"),
        {"enabled": False, "notes": "Consolidated 2026-09: superseded by the Tier-1 EIC news watcher (eu-eic-acc)."},
    ),
    (
        lambda s: s["id"] == "fr-ilab",
        {
            "url": "https://www.enseignementsup-recherche.gouv.fr/fr/i-lab-laureats-du-concours-d-innovation",
            "name": "i-Lab laureates (ministry list, operated by Bpifrance)",
            "notes": "Repaired 2026-09: laureates are published on the ministry page (new edition each June); the old Bpifrance URL had moved to /concours-dinnovation-i-lab.",
        },
    ),
]


# ── from domain/sources_v2.py ──
URL_REPAIRS = {
    "eu-ellis-signal": (
        "https://ellis.eu/news",
        "https://institute-tue.ellis.eu/en/news",
        "ELLIS Institute Tübingen - news (official)",
    ),
    "de-insurtech-hub-munich": (
        "https://www.insurtech-munich.com/startups",
        "https://www.insurtech-munich.com/en/news/",
        "InsurTech Hub Munich - News Hub (official, EN)",
    ),
}

URL_REPAIRS_MULTI = {
    "de-insurtech-hub-munich": (
        ("https://www.insurtech-munich.com/startups", "https://www.insurtech-munich.com/news"),
        "https://www.insurtech-munich.com/en/news/",
        "InsurTech Hub Munich - News Hub (official, EN)",
    )
}

NOTE_REPAIRS = {
    "de-sprind-projects": "Static directory parser currently has partial coverage because the official site lazy-loads additional projects."
}

def registry_entries() -> list[dict[str, Any]]:
    base = {
        "kind": "structured",
        "enabled": True,
        "last_scan": None,
        "last_ok": None,
        "last_result_count": None,
        "failures_in_row": 0,
        "yield": {"kept": 0, "research": 0, "rejected": 0},
        "_repair_v": 2,
        "geo_scope": "country",
    }
    return [
        {
            **base,
            "id": "ch-epfl-creation",
            "name": "EPFL - startups in creation (official)",
            "url": "https://www.epfl.ch/innovation/startup/discover-our-startups/epfl-startup-in-creation/",
            "parser": "epfl_creation",
            "geo": ["CH"],
            "sectors": ["deeptech", "ai_sw", "robotics"],
            "stage": "pre_company",
            "reliability": "high",
            "freshness": "weekly",
            "location": "Lausanne, Switzerland",
            "country": "Switzerland",
            "notes": "Table rows per category (Project | Description | Project Leader(s) | Executive Summary). First scan surfaces the current list as NEW (bootstrap).",
        },
        {
            **base,
            "id": "de-helmholtz-enterprise",
            "name": "Helmholtz Enterprise - batch projects (official)",
            "url": "https://www.helmholtz.de/en/transfer/helmholtz-association-transfer-instruments/helmholtz-enterprise/",
            "parser": "helmholtz_enterprise",
            "geo": ["DACH"],
            "sectors": ["deeptech"],
            "stage": "pre_company",
            "reliability": "high",
            "freshness": "monthly",
            "location": "Germany",
            "country": "Germany",
            "notes": "Projects inside 'Batch I 2026'-style sections only. Latest batch surfaces as NEW (bootstrap), older batches as baseline.",
        },
        {
            **base,
            "id": "de-sprind-projects",
            "name": "SPRIND - supported projects (official)",
            "url": "https://www.sprind.org/en/actions/projects",
            "parser": "sprind_projects",
            "geo": ["DACH"],
            "sectors": ["deeptech"],
            "stage": "grant",
            "reliability": "high",
            "freshness": "monthly",
            "location": "Germany",
            "country": "Germany",
            "notes": "Static directory parser currently has partial coverage because the official site lazy-loads additional projects. Portraits, filters, challenges never emitted; historical directory -> baseline on first scan.",
        },
        {
            **base,
            "id": "de-mpg-startups",
            "name": "Max Planck - start-ups & entrepreneurs (official)",
            "url": "https://www.mpg.de/24759717/start-ups-entrepreneurs",
            "parser": "mpg_startups",
            "geo": ["DACH"],
            "sectors": ["deeptech"],
            "stage": "announcement",
            "reliability": "high",
            "freshness": "monthly",
            "location": "Germany",
            "country": "Germany",
            "notes": "Company link inside the heading is preserved. Historical list -> baseline on first scan.",
        },
        {
            **base,
            "id": "eu-ellis-signal",
            "name": "ELLIS Institute Tübingen - news (official)",
            "url": "https://institute-tue.ellis.eu/en/news",
            "parser": "ellis_signal",
            "geo": ["DACH"],
            "sectors": ["ai_sw", "deeptech"],
            "stage": "announcement",
            "reliability": "high",
            "freshness": "weekly",
            "location": "Tübingen, Germany",
            "country": "Germany",
            "notes": "Signal-only: an article must explicitly announce/name a startup or spinout. Explicit spinouts surface as NEW (bootstrap).",
        },
        {
            **base,
            "id": "de-insurtech-hub-munich",
            "name": "InsurTech Hub Munich - News Hub (official)",
            "url": "https://www.insurtech-munich.com/en/news/",
            "parser": "insurtech_hub",
            "geo": ["DACH"],
            "sectors": ["fintech"],
            "stage": "announcement",
            "reliability": "medium",
            "freshness": "monthly",
            "location": "Munich, Germany",
            "country": "Germany",
            "notes": "English News Hub, pages 1-3. Only the 'The startups of the Venture Client Program ...' section of relevant articles is parsed; section labels, insurers and programme names are never startups. Current cohort surfaces as NEW (bootstrap).",
        },
    ]
# fmt: on

# ruff: noqa: E501
# (protected gold-master data, copied by script from the old modules; see the header)
"""The Map catalog (review 025): constants cut MECHANICALLY from the old ``services/geo_intel.py`` and
``api/routers/home.py`` at revision 6c739b9 by exact line ranges (``scripts/gen_map_catalog.py``); nothing is retyped.
``tests/map/test_map_port.py`` checks every cut against the old modules. Pure data.

From ``geo_intel.py`` (top level): the windows (``ACTIVITY_DAYS``, ``MAX_PER_SOURCE``, ``EVENT_DAYS``), ``STATES``,
``FAMILY_LABEL``, ``COVERAGE_LABEL``, ``COV_WORD``, ``NOTE``, ``COORDS``, ``SUBLOCAL``, the ``_UI_TEXT`` / ``_ABROAD``
patterns, the ``_SCOUT_FAMILY`` / ``_SRC_FAMILY`` / ``_NEWS_FAMILY`` maps and ``HOME_DEFAULT``; from inside its
functions: ``LEGEND`` (``view``), ``WHERE_TO_GO_EMPTY_NOTE`` / ``WHERE_TO_GO_NOTE`` (``where_to_go``), ``BRING_BACK``
and ``PLAN_NOTE`` (``sourcing_day``). From ``home.py`` (lines 25-26): ``DEFAULT_HOME_BASE`` and ``OPERATOR_ID``.
"""

from __future__ import annotations

import re
from typing import Any

# fmt: off
# ── from services/geo_intel.py ──
ACTIVITY_DAYS = 120  # signals older than this are context, not current activity
MAX_PER_SOURCE = 3  # early signals counted per source (volume from one list never dominates)
EVENT_DAYS = 45  # upcoming-event horizon
STATES = ("VERY ACTIVE", "INTERESTING", "NORMAL", "LOW SIGNAL", "UNDER-COVERED")
FAMILY_LABEL: dict[str, str] = {
    "research": "University / research spinout",
    "founder_formation": "Founder formation",
    "grants": "Grants",
    "accelerator": "Accelerator / ecosystem programme",
    "scout00": "Scout 00 discovery",
    "news": "News",
    "company_formation": "Company formation",
    "hiring": "Hiring",
    "customer_pilot": "Customer / pilot",
    "funding_preparation": "Funding preparation",
    "event": "Event",
}
COVERAGE_LABEL: dict[str, str] = {
    "spinouts": "Universities / research",
    "programs": "Accelerators",
    "events": "Events",
    "grants": "Grants",
    "emerging_companies": "New companies",
    "founder_formation": "Founder formation",
    "general": "General / news",
}
COV_WORD = {"HEALTHY": "STRONG", "PARTIAL": "PARTIAL", "GAP": "WEAK", "UNKNOWN": "NOT COVERED"}
NOTE = "This shows Project Zero activity / opportunity signals and visibility — not company investment scores."
COORDS: dict[str, tuple[float, float]] = {
    "Heilbronn": (49.1427, 9.2109),
    "Hamburg": (53.5511, 9.9937),
    "Vienna": (48.2082, 16.3738),
    "Cambridge": (52.2053, 0.1218),
    "Oxford": (51.7520, -1.2577),
    "Manchester": (53.4808, -2.2426),
    "Edinburgh": (55.9533, -3.1883),
    "Dublin": (53.3498, -6.2603),
    "Lyon": (45.7640, 4.8357),
    "Grenoble": (45.1885, 5.7245),
    "Brussels": (50.8503, 4.3517),
    "Luxembourg": (49.6116, 6.1319),
    "Stockholm": (59.3293, 18.0686),
    "Oslo": (59.9139, 10.7522),
    "Gothenburg": (57.7089, 11.9746),
    "Reykjavik": (64.1466, -21.9426),
    "Milan": (45.4642, 9.1900),
    "Turin": (45.0703, 7.6869),
    "Rome": (41.9028, 12.4964),
    "Bologna": (44.4949, 11.3426),
    "Barcelona": (41.3874, 2.1686),
    "Madrid": (40.4168, -3.7038),
    "Valencia": (39.4699, -0.3763),
    "Lisbon": (38.7223, -9.1393),
    "Porto": (41.1579, -8.6291),
    "Warsaw": (52.2297, 21.0122),
    "Krakow": (50.0647, 19.9450),
    "Prague": (50.0755, 14.4378),
    "Brno": (49.1951, 16.6068),
    "Zagreb": (45.8150, 15.9819),
    "Tallinn": (59.4370, 24.7536),
    "Riga": (56.9496, 24.1052),
    "Vilnius": (54.6872, 25.2797),
    "Budapest": (47.4979, 19.0402),
    "Bucharest": (44.4268, 26.1025),
    "Ljubljana": (46.0569, 14.5058),
    "Bratislava": (48.1486, 17.1077),
    "Tartu": (58.3776, 26.7290),
    "Kaunas": (54.8985, 23.9036),
    "Wrocław": (51.1079, 17.0385),
    "Geneva": (46.2044, 6.1432),
    "Bristol": (51.4545, -2.5879),
    "Tübingen": (48.5216, 9.0576),
    "Mainz": (49.9929, 8.2473),
    "Aachen": (50.7753, 6.0839),
    "Dresden": (51.0504, 13.7373),
}
SUBLOCAL: dict[str, str] = {
    "garching": "Munich",
    "ottobrunn": "Munich",
    "ecublens": "Lausanne",
    "epfl": "Lausanne",
    "schlieren": "Zürich",
    "opfikon": "Zürich",
    "dübendorf": "Zürich",
    "issy-les-moulineaux": "Paris",
    "station f": "Paris",
    "kronberg": "Frankfurt",
    "rödermark": "Frankfurt",
    "eschborn": "Frankfurt",
    "cottbus": "Cottbus",
    "senftenberg": "Cottbus",
}
_UI_TEXT = re.compile(
    r"^\s*((show|load|view|see|read|watch|learn|apply)\s+(\d+\s+)?(more|all|now)\b|"
    r".*\b(summit|conference|masterclass|meetup|festival|demo day|career fair)\b|.*\b20\d\d\s*$)",
    re.I,
)
_ABROAD = re.compile(
    r"\b(usa|u\.s\.|united states|canada|massachusetts|california|\bma\b|israel|singapore|china|india)\b", re.I
)
_SCOUT_FAMILY: dict[str, str] = {
    "round_forming": "funding_preparation",
    "accelerator_pitch": "accelerator",
    "accelerator": "accelerator",
    "research": "research",
    "spinout": "research",
    "university": "research",
    "grant": "grants",
    "registry": "company_formation",
    "incorporation": "company_formation",
    "formation": "founder_formation",
    "stealth": "founder_formation",
    "founder_exit": "founder_formation",
    "hiring": "hiring",
    "customer": "customer_pilot",
    "pilot": "customer_pilot",
    "press_radar": "news",
    "funding": "news",
}
_SRC_FAMILY: dict[str, str] = {
    "spinouts": "research",
    "programs": "accelerator",
    "grants": "grants",
    "emerging_companies": "company_formation",
    "founder_formation": "founder_formation",
    "events": "event",
}
_NEWS_FAMILY: dict[str, str] = {
    "grant": "grants",
    "accelerator": "accelerator",
    "founder": "founder_formation",
    "customer": "customer_pilot",
    "partnership": "customer_pilot",
    "hire": "hiring",
    "regulatory": "customer_pilot",
    "launch": "company_formation",
}
HOME_DEFAULT: dict[str, Any] = {"city": "Karlsruhe", "lat": 49.0069, "lng": 8.4037}  # same default as the Map / home base
LEGEND: dict[str, str] = (
    {
        "VERY ACTIVE": "early signals from several independent families",
        "INTERESTING": "early signals, or one early signal plus something actionable",
        "NORMAL": "activity, but little that is early",
        "LOW SIGNAL": "little activity although Project Zero can see this area reasonably well",
        "UNDER-COVERED": "little detected AND weak visibility — we do not know, it is not 'cold'",
    }
)
WHERE_TO_GO_EMPTY_NOTE = (
    "Not enough grounded evidence to recommend a trip yet — no area combines early signals "
    "with something actionable. Check Coverage gaps: absence may mean blind spots."
)
WHERE_TO_GO_NOTE = (
    "Ranked by early signals, actionable events, Scout 00 finds and independent signal families — not by volume."
)
BRING_BACK: list[str] = (
    [
        "new companies (add them to Deal Flow)",
        "founder claims (record after the call — they stay unverified)",
        "ecosystem contacts (Network)",
        "source candidates (System health → New sources)",
        "event intelligence (Events → debrief)",
        "founder-formation signals (who is leaving where)",
    ]
)
PLAN_NOTE = (
    "PLAN ONLY — Project Zero does not message anyone, register you or book travel. Times are only shown when "
    "the event lists them; meetings exist only if you arrange them."
)
# ── from api/routers/home.py ──
DEFAULT_HOME_BASE: dict[str, Any] = {"city": "Karlsruhe", "lat": 49.0069, "lng": 8.4037}
OPERATOR_ID = "p-omar-hedeya"  # the investor himself is never a pin on the map
# fmt: on

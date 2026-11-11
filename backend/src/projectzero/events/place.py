"""Event geography: the old ``domain/geo_alias.py`` and ``domain/event_place.py`` (rev 6c739b9), ported VERBATIM.

* ``normalize_city`` (geo_alias:96-113): the canonical city alias layer. Country-aware: aliases merge only when the
  stated country agrees or is unknown; different cities that share a name are never merged; an unknown label passes
  through (its part before ``,`` / ``(`` / ``/``).
* ``place`` (event_place:89-131): readable geography for display and filtering only: the canonical city, the metro
  ``area`` a suburb belongs to ("Zürich" for Egg), the country (inferred from the configured source's city when the
  record has none) and the labels.
* ``themes`` (event_place:134-137): the Project-A themes an event's OWN text evidences (never the organizer). It never
  feeds eligibility, ranking or any score.

Pure functions; held to the old code by the review 015 oracle goldens.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# ── geo_alias ───────────────────────────────────────────────────────────────────────────────────────────────────
# canonical -> (country, [aliases])
_CANON: dict[str, tuple[str, list[str]]] = {
    "Munich": ("DE", ["münchen", "munchen", "muenchen", "munich"]),
    "Frankfurt": (
        "DE",
        ["frankfurt", "frankfurt am main", "frankfurt a. m.", "frankfurt a.m.", "frankfurt/main", "frankfurt (main)"],
    ),
    "Zürich": ("CH", ["zurich", "zürich", "zuerich"]),
    "Cologne": ("DE", ["köln", "koln", "koeln", "cologne"]),
    "Vienna": ("AT", ["wien", "vienna"]),
    "Geneva": ("CH", ["genève", "geneve", "genf", "geneva"]),
    "Basel": ("CH", ["basel", "bâle", "bale"]),
    "Lisbon": ("PT", ["lisboa", "lisbon"]),
    "Milan": ("IT", ["milano", "milan"]),
    "Copenhagen": ("DK", ["københavn", "kobenhavn", "copenhagen"]),
    "Prague": ("CZ", ["praha", "prague"]),
    "Warsaw": ("PL", ["warszawa", "warsaw"]),
    "Nuremberg": ("DE", ["nürnberg", "nurnberg", "nuremberg"]),
    "Brussels": ("BE", ["bruxelles", "brussel", "brussels"]),
    "The Hague": ("NL", ["den haag", "'s-gravenhage", "the hague"]),
    "Gothenburg": ("SE", ["göteborg", "goteborg", "gothenburg"]),
    "Hanover": ("DE", ["hannover", "hanover"]),
    "Karlsruhe": ("DE", ["karlsruhe"]),
    "Stuttgart": ("DE", ["stuttgart"]),
    "Berlin": ("DE", ["berlin"]),
    "Darmstadt": ("DE", ["darmstadt"]),
    "Lausanne": ("CH", ["lausanne"]),
    "Paris": ("FR", ["paris"]),
    "Amsterdam": ("NL", ["amsterdam"]),
    "Delft": ("NL", ["delft"]),
    "Eindhoven": ("NL", ["eindhoven"]),
    "London": ("GB", ["london"]),
    "Heidelberg": ("DE", ["heidelberg"]),
    "Mannheim": ("DE", ["mannheim"]),
}
_ALIAS = {a: (c, cc) for c, (cc, al) in _CANON.items() for a in al}
_COUNTRY_ALIAS = {
    "germany": "DE", "deutschland": "DE", "de": "DE",
    "switzerland": "CH", "schweiz": "CH", "suisse": "CH", "ch": "CH",
    "austria": "AT", "österreich": "AT", "at": "AT",
    "france": "FR", "fr": "FR",
    "netherlands": "NL", "nederland": "NL", "nl": "NL",
    "united kingdom": "GB", "uk": "GB", "gb": "GB", "england": "GB",
    "portugal": "PT", "pt": "PT",
    "italy": "IT", "italia": "IT", "it": "IT",
    "denmark": "DK", "dk": "DK",
    "czech republic": "CZ", "czechia": "CZ", "cz": "CZ",
    "poland": "PL", "polska": "PL", "pl": "PL",
    "belgium": "BE", "be": "BE",
    "sweden": "SE", "se": "SE",
    "usa": "US", "united states": "US", "us": "US",
}  # fmt: skip


def _alias_fold(s: object) -> str:
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower().strip()


def norm_country(c: Any) -> str:
    return _COUNTRY_ALIAS.get(_alias_fold(c), (c or "").strip().upper()[:2] if c else "")


def normalize_city(label: Any, country: Any = "") -> tuple[str, str, str]:
    """-> (canonical_city, country_code, original_label). Unknown labels pass through unchanged."""
    original = (label or "").strip()
    if not original:
        return "", norm_country(country), original
    key = original.lower().strip()
    key2 = _alias_fold(original)
    cc = norm_country(country)
    hit = _ALIAS.get(key) or _ALIAS.get(key2)
    if not hit:
        base = re.split(r"[,(/]", original)[0].strip()  # "Munich, Germany" / "Frankfurt (Main)"
        hit = _ALIAS.get(base.lower()) or _ALIAS.get(_alias_fold(base))
        if not hit:
            return base or original, cc, original
    canon, canon_cc = hit
    if cc and canon_cc and cc != canon_cc:
        return original, cc, original  # same name, different country: never merged
    return canon, cc or canon_cc, original


# ── event_place ─────────────────────────────────────────────────────────────────────────────────────────────────
COUNTRY_NAMES = {
    "DE": "Germany", "CH": "Switzerland", "FR": "France", "NL": "Netherlands", "AT": "Austria", "BE": "Belgium",
    "GB": "United Kingdom", "FI": "Finland", "SE": "Sweden", "DK": "Denmark", "NO": "Norway", "EE": "Estonia",
    "PT": "Portugal", "ES": "Spain", "IT": "Italy", "PL": "Poland", "CZ": "Czechia", "IE": "Ireland",
    "LU": "Luxembourg", "US": "United States",
}  # fmt: skip

# metro area -> (country, [municipalities / districts that belong to it]); folded, lower-case
_METRO: dict[str, tuple[str, list[str]]] = {
    "Zürich": ("CH", ["egg", "schlieren", "opfikon", "dubendorf", "duebendorf", "wallisellen", "kloten", "dietikon",
                      "glattbrugg", "rumlang", "zollikon", "kusnacht", "thalwil", "adliswil", "regensdorf", "uster"]),
    "Paris": ("FR", ["ivry-sur-seine", "pantin", "bobigny", "issy-les-moulineaux", "nanterre", "boulogne-billancourt",
                     "saint-denis", "montreuil", "levallois-perret", "neuilly-sur-seine", "la defense", "puteaux",
                     "courbevoie", "vincennes", "saint-ouen", "clichy", "palaiseau", "saclay", "gif-sur-yvette",
                     "massy", "cachan", "gentilly", "malakoff", "vanves", "romainville", "aubervilliers"]),
    "Amsterdam": ("NL", ["zaandam", "amstelveen", "halfweg", "diemen", "schiphol", "hoofddorp", "badhoevedorp"]),
    "Frankfurt": ("DE", ["kronberg im taunus", "rodermark", "offenbach", "offenbach am main", "eschborn",
                         "bad homburg", "bad homburg vor der hohe", "oberursel", "neu-isenburg", "dreieich"]),
    "Munich": ("DE", ["garching", "garching bei munchen", "martinsried", "planegg", "unterfohring", "ismaning",
                      "oberpfaffenhofen", "ottobrunn", "taufkirchen", "unterschleissheim", "grasbrunn"]),
    "Berlin": ("DE", ["potsdam", "adlershof"]),
    "Helsinki": ("FI", ["espoo", "vantaa", "otaniemi", "keilaniemi"]),
    "Stockholm": ("SE", ["solna", "kista", "sundbyberg", "nacka", "hagersten", "bromma", "liljeholmen", "johanneshov",
                         "lidingo", "sodermalm", "huddinge"]),
    "Copenhagen": ("DK", ["frederiksberg", "lyngby", "kongens lyngby", "hellerup"]),
    "Lausanne": ("CH", ["ecublens", "renens", "epalinges"]),
    "Basel": ("CH", ["allschwil", "muttenz", "pratteln"]),
    "London": ("GB", ["shoreditch", "canary wharf", "white city"]),
    "Karlsruhe": ("DE", ["ettlingen", "eggenstein-leopoldshafen"]),
}  # fmt: skip
_SUBURB = {s: (metro, cc) for metro, (cc, subs) in _METRO.items() for s in subs}
# canonical cities normalize_city does not know (passed through unchanged there) and their country
_CITY_CC = {"Helsinki": "FI", "Espoo": "FI", "Stockholm": "SE", "Oslo": "NO", "Tallinn": "EE", "Dublin": "IE",
            "Madrid": "ES", "Barcelona": "ES", "Luxembourg": "LU", "Wiesbaden": "DE", "Heilbronn": "DE",
            "Mainz": "DE", "Aachen": "DE", "Dresden": "DE", "Leipzig": "DE", "Bern": "CH", "Lucerne": "CH",
            "Zug": "CH", "St. Gallen": "CH", "Rotterdam": "NL", "Utrecht": "NL", "Lyon": "FR", "Grenoble": "FR"}  # fmt: skip


def _place_fold(s: object) -> str:
    folded = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", folded).lower().strip()


def country_name(cc: str) -> str:
    return COUNTRY_NAMES.get((cc or "").upper(), (cc or "").upper())


def place(e: dict[str, Any], source_city: str = "") -> dict[str, str]:
    """Readable geography for one event. ``source_city``: the configured city of the event's first source."""
    city, cc, _original = normalize_city(e.get("city", ""), e.get("country", ""))
    area, area_cc = city, cc
    hit = _SUBURB.get(_place_fold(city))
    if hit:
        area, area_cc = hit
    if not cc:
        cc = area_cc or _CITY_CC.get(city, "")
    if not cc and source_city:
        _sc, scc, _ = normalize_city(source_city, "")
        cc = scc or _CITY_CC.get(_sc, "")
    if not cc and area:
        _a, acc, _ = normalize_city(area, "")
        cc = acc
    fmt = str(e.get("format") or "").lower()
    if not city:
        label = "Online" if fmt == "virtual" else "Location not stated"
        return {"city": "", "area": "", "country": cc, "country_name": country_name(cc), "label": label,
                "area_label": label}  # fmt: skip
    cn = country_name(cc)
    area_label = f"{area}, {cn}" if cn else area  # the filter groups a metro area: "Zürich, Switzerland" includes Egg
    label = f"{city} · {area} area, {cn}" if hit else area_label
    return {"city": city, "area": area, "country": cc, "country_name": cn, "label": label, "area_label": area_label}


# theme label -> evidence pattern (word-bounded; matched on the event's OWN text only)
THEMES = [
    ("AI", r"\b(ai|a\.i\.|artificial intelligence|machine learning|ml|llms?|agents?|agentic|genai|gen ai|deep learning|"
           r"neural|claude|openai|gpt|data science)\b"),
    ("Robotics", r"\b(robot(s|ics)?|drones?|autonomous|humanoids?|automation)\b"),
    ("Industrial & manufacturing", r"\b(industrial|industry 4\.0|manufactur\w*|factory|supply chain|logistics|"
                                   r"mobility|automotive|construction)\b"),
    ("Energy & climate", r"\b(energy|climate|cleantech|clean tech|battery|batteries|hydrogen|grid|solar|carbon|"
                         r"sustainab\w*|circular|electrification)\b"),
    ("Defence & security", r"\b(defen[cs]e|dual-?use|security|cyber\w*|resilience|military)\b"),
    ("Health & bio", r"\b(health\w*|medtech|biotech|bio|life sciences?|pharma|medical|clinical)\b"),
    ("Quantum & deeptech", r"\b(quantum|deep ?tech|photonics?|semiconductors?|chips?|materials|nanotech)\b"),
    ("Space", r"\b(space|satellites?|orbit\w*|new space|aerospace)\b"),
    ("Fintech", r"\b(fintech|payments?|banking|insurtech|crypto|web3|blockchain)\b"),
    ("Developer & open source", r"\b(developers?|open source|devtools?|coding|hackathon|software engineering)\b"),
]  # fmt: skip
_THEME_RX = [(lab, re.compile(rx, re.I)) for lab, rx in THEMES]


def themes(e: dict[str, Any]) -> list[str]:
    # NOT the organizer: "Heat Sink: Community Sauna" by "Helsinki Robotics Week" is not a robotics event
    text = " ".join(str(e.get(k) or "") for k in ("name", "description", "keywords", "domains", "audience"))
    return [lab for lab, rx in _THEME_RX if rx.search(text)]

# ruff: noqa: E501, RUF001
# (the fixture sites and the step scripts: one case per line)
"""Founder Radar fetch parity: the founder scan and company research against the OLD code as oracle, over FIXTURE
sites, with a FIXED clock and NO network (review 026b).

    python -m projectzero.ops.parity_founder_radar_fetch goldens   # (re)generates golden_v1/oracle_founder_radar_fetch.json

The oracle (``scripts/oracle/founder_radar_fetch_oracle.py``) runs the old route functions ``radar_scan``,
``radar_research``, ``radar_research_queue`` (and ``radar_review`` between two research runs) over a scratch data
folder, with the old fetch entry points fed by the fixture sites below (the collectors' ``_get_json``; the REAL old
``_fetch_public`` with a fixture connector and the fixture resolver), and records each answer, the stored documents
(key order included) and every request it sent. The new side is the pure port (``founder_radar.scanning`` /
``research``) with a ``fetching.Fetch`` over ``FixtureTransport`` (the same sites) and the same resolver table; each
outcome's documents become the next step's inputs.

The fixtures (invented names only): eight registry cities; GitHub search / user / repository answers (a login-only
user, an organisation account, a user found again in a later scan, an empty search), a 403 with ``X-RateLimit-Reset``
on a city search (the GitHub token set), a 429 with ``Retry-After`` on a user lookup (no token), OpenAlex works
(authors merged by id, a first author, an author without a name, a 500), the pipeline founders (placeholders
skipped); company sites with team / about / news pages, a link-discovered order, ``robots.txt`` disallowing a page,
a ``text/plain`` robots.txt (the old quirk: ignored), a login wall, a cross-origin redirect, a redirect to http, a
``www.`` redirect (followed), a redirect loop (too many), a non-HTML page, an oversize body (cut at 400 000 bytes),
a transport error, a 404, a host resolving to a private address, a candidate domain, a company without a domain, a
public GitHub organisation page (redirected on github.com); a review between a research run and its refresh; the
resumable queue.

Planned differences (review 026b), declared and normalised; everything else must be identical, key order included:
* the User-Agent (plan revision 2 §4): every request's ``User-Agent`` is compared as ``<user-agent>`` (``Host`` is set
  by the transport, not the caller, and is dropped);
* (b) the GitHub hint of a rate-limited source names ``PZ_GITHUB_TOKEN`` (``scanning.TOKEN_HINT``; the old text named
  ``config.json``): compared as the old text. The token is ``config.json`` ``github_token`` on the old side and the
  ``token`` parameter on the new side;
* the reset clock: the oracle's ``datetime.fromtimestamp`` gives the Berlin wall time (the new ``reset_text``);
* durations (``seconds``): wall-clock measurements, compared as 0;
* (d) the guard on GitHub / OpenAlex: no fixture is refused by it (they are unit-tested), so nothing to normalise;
* review 026a decision a: the research route's ``companies_queue`` no longer persists founder references; the stored
  companies are compared with their references derived (``normalized_companies``) and the new side may write fewer
  documents, never more;
* review 026a decision b: the oracle pins the old person id hash to ``int(sha1(str(key)))`` (the new ``allocate_id``,
  no collision in the fixtures).
Identical recorded values are stored once (``compact`` of review 026a). Exit 1 on any difference.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import urllib.parse
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from projectzero.core import net
from projectzero.core.paths import REPO_ROOT
from projectzero.ecosystems.catalog import RADAR_DEFAULT_SOURCES
from projectzero.founder_radar import research, routes, scanning
from projectzero.founder_radar.fetching import Fetch
from projectzero.founder_radar.names import hashlib_sha
from projectzero.network.view import berlin_today
from projectzero.ops.parity_founder_calls import utc_instant
from projectzero.ops.parity_founder_radar import check_outcome, compact, expand, normalized_companies, radar_person
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js

ORACLE = REPO_ROOT / "scripts" / "oracle" / "founder_radar_fetch_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_founder_radar_fetch.json"
CLOCK = "2026-11-12T10:00:00"
LATER = "2026-11-12T11:30:00"
NEXT_DAY = "2026-11-13T09:15:00"
DOCS = ("people.json", "radar_companies.json", "radar_research.json", "radar_metrics.json", "radar_cursor.json",
        "radar_health.json", "radar_research_queue.json")  # fmt: skip
FIXTURE_IP = "93.184.216.34"  # the old research.FIXTURE_RESOLVER answer
TOKEN = "fixture-github-token-0000"  # invented, never a real credential
UA = "<user-agent>"
NOT_FOUND = {"status": 404, "headers": {"Content-Type": "text/html"}, "body": ""}

# ------------------------------------------------------------------ fixture sites (invented names only)
# fmt: off
REGIONS = {"regions": [{"region": "DACH", "cities": [["Aldermoor", "DE"], ["Brisenthal", "DE"], ["Corvath", "AT"], ["Dunmarrow", "CH"]]},
                       {"region": "Nordics", "cities": [["Eskerholm", "SE"], ["Fjellvik", "NO"], ["Grenmouth", "DK"], ["Halvardby", "FI"]]}]}
CITIES = [c for r in REGIONS["regions"] for c, _cc in r["cities"]]


def gh_search(city: str) -> str:
    q = urllib.parse.quote(f'location:"{city}" repos:>15 followers:>40')
    return f"https://api.github.com/search/users?q={q}&sort=repositories&order=desc&per_page=6"


def gh_user(login: str) -> str:
    return f"https://api.github.com/users/{login}"


def gh_repos(login: str) -> str:
    return f"https://api.github.com/users/{login}/repos?sort=pushed&per_page=5"


def oa_works(src: dict[str, Any], year: int = 2026) -> str:
    flt = f"publication_year:{year}" + (f",institutions.country_code:{src['country']}" if src.get("country") else ",institutions.continent:europe")
    return f"https://api.openalex.org/works?search={urllib.parse.quote(src['query'])}&filter={flt}&sort=publication_date:desc&per-page=25&mailto=projectzero@example.org"


def ok_json(value: Any, **headers: str) -> dict[str, Any]:
    return {"status": 200, "headers": {"Content-Type": "application/json; charset=utf-8", **headers}, "json": value}


def html(body: str, status: int = 200, ctype: str = "text/html; charset=utf-8", **kw: Any) -> dict[str, Any]:
    return {"status": status, "headers": {"Content-Type": ctype}, "body": body, **kw}


def redirect(location: str, status: int = 301) -> dict[str, Any]:
    return {"status": status, "headers": {"Location": location, "Content-Type": "text/html"}, "body": ""}


def github_users() -> dict[str, Any]:
    return {
        gh_user("orinthal"): ok_json({"id": 70101, "login": "orinthal", "name": "Orin Thalweg", "html_url": "https://github.com/orinthal", "public_repos": 34, "followers": 160,
                                      "bio": "Co-founder building warehouse robotics. Previously at an invented lab.", "company": "@Larkspur Analytics", "location": "Aldermoor", "blog": "https://larkspur.example"}),
        gh_repos("orinthal"): ok_json([{"name": "motion-kit", "pushed_at": "2026-11-03T10:00:00Z", "stargazers_count": 40, "description": "robotics motion planning", "language": "Rust"},
                                       {"name": "grid-sim", "pushed_at": "2026-11-01T08:00:00Z", "stargazers_count": 25, "description": "energy infrastructure simulator", "language": "Python"},
                                       {"name": "old-notes", "pushed_at": "2025-02-01T08:00:00Z", "stargazers_count": 1, "description": None, "language": None}]),
        gh_user("kestrel42"): ok_json({"id": 70102, "login": "kestrel42", "name": None, "html_url": "https://github.com/kestrel42", "public_repos": 12, "followers": 55, "bio": "open to new projects", "company": None, "location": "Aldermoor", "blog": ""}),
        gh_repos("kestrel42"): ok_json([]),
        gh_user("brightwater-sys"): ok_json({"id": 70103, "login": "brightwater-sys", "name": "Brightwater Systems GmbH", "html_url": "https://github.com/brightwater-sys", "public_repos": 80, "followers": 900, "bio": "", "company": "", "location": "Aldermoor", "blog": ""}),
        gh_repos("brightwater-sys"): ok_json([{"name": "sdk", "pushed_at": "2026-11-10T08:00:00Z", "stargazers_count": 300, "description": "industrial sdk", "language": "Go"}]),
        gh_user("selkie-dev"): ok_json({"id": 70201, "login": "selkie-dev", "name": "Maren Solvik", "html_url": "https://github.com/selkie-dev", "public_repos": 21, "followers": 130, "bio": "stealth startup, machine learning for climate", "company": "", "location": "Grenmouth", "blog": ""}),
        gh_repos("selkie-dev"): ok_json([{"name": "tide", "pushed_at": "2026-11-09T08:00:00Z", "stargazers_count": 70, "description": "applied ai for climate", "language": "Python"}]),
    }


OA_WORKS = {"results": [
    {"id": "https://openalex.org/W9001", "title": "Autonomous robotics for industrial inspection", "publication_date": "2026-10-20",
     "concepts": [{"display_name": "Robotics"}, {"display_name": "Machine learning"}],
     "authorships": [{"author": {"id": "https://openalex.org/A7001", "display_name": "Sabine Orlaith", "orcid": "https://orcid.org/0000-0000-0000-7001"}, "author_position": "first", "institutions": [{"display_name": "Invented Institute of Robotics"}]},
                     {"author": {"id": "https://openalex.org/A7002", "display_name": "Jorund Vael"}, "author_position": "middle", "institutions": [{"display_name": "Invented Institute of Robotics"}, {"display_name": None}]},
                     {"author": {"display_name": ""}, "author_position": "middle", "institutions": []},
                     {"author": {"id": "https://openalex.org/A7004", "display_name": "Never Counted"}, "author_position": "last", "institutions": []}]},
    {"id": "https://openalex.org/W9002", "display_name": "Grid-scale storage scheduling", "publication_date": "2026-09-02", "concepts": [],
     "authorships": [{"author": {"id": "https://openalex.org/A7002", "display_name": "Jorund Vael"}, "author_position": "first", "institutions": []}]},
]}

SIGNALS = [
    {"company": "Larkspur Analytics", "website": "https://larkspur.example", "stage": "pre-seed", "archetype": "Industrial AI", "location": "Porto",
     "founders": [{"name": "Rhea Quintaval", "role": "CEO"}, "TBD", {"name": "Founders TBD"}, {"name": "Tomas Eidervik"}]},
    {"company": "Quillbright Robotics", "website": "https://www.quillbright.example", "earliness": "seed", "founders": ["Ilsa Marrowfield"]},
    {"company": "Pellucid Grid", "website": "https://pellucid.example", "founders": []},
]


def health_doc() -> dict[str, Any]:
    return {"scan_time": "2026-11-05 09:00", "totals": {"raw": 3}, "note": "",
            "sources": [{"id": "gh-aldermoor", "name": "GitHub — builders in Aldermoor", "kind": "github_users", "status": "ok", "note": "", "last_ok": "2026-11-05 09:00"},
                        {"id": "oa-de-robotics", "name": "OpenAlex", "kind": "openalex_works", "status": "ok", "note": "", "last_ok": "2026-11-04 08:00"}],
            "regions": [{"region": "DACH", "cities": [{"city": "Aldermoor", "country": "DE", "source_id": "gh-aldermoor", "status": "ok", "attempted": True, "last_attempt": "2026-11-05 09:00", "last_ok": "2026-11-05 09:00"},
                                                      {"city": "Dunmarrow", "country": "CH", "source_id": "gh-dunmarrow", "status": "failed", "attempted": True, "last_attempt": "2026-11-05 09:00", "last_ok": "2026-10-01 09:00"}]}]}


def metrics_doc() -> dict[str, Any]:
    return {"history": [{"date": "2026-11-05", "gold_now": 0, "research_talent": 1}], "latest": {"date": "2026-11-05", "gold_now": 0, "research_talent": 1}}


def scan_people() -> list[dict[str, Any]]:
    gh_src = [{"source": "GitHub — builders in Aldermoor", "source_id": "gh-aldermoor", "url": "https://github.com/kestrel42", "retrieved": "2026-11-05 09:00", "route": "github-api"}]
    return [
        radar_person("p-kestrel42-0102", "kestrel42", github_id="70102", name_attributed=False, aliases=["kestrel42"], location="Aldermoor", country="DE", region="DACH",
                     profile_urls=["https://github.com/kestrel42"], sources=gh_src),
        radar_person("p-sabine-orlaith-7001", "Sabine Orlaith", openalex_id="https://openalex.org/A7001", identity_status="resolved", institutions=["Invented Institute of Robotics"],
                     country="DE", profile_urls=["https://openalex.org/A7001"],
                     evidence=[{"category": "technical", "claim": "earlier work", "source": "OpenAlex", "source_url": "https://openalex.org/W8001", "retrieved": "2026-11-04 08:00"}]),
        {"id": "p-oskar-fenwright", "name": "Oskar Fenwright", "created": "2026-03-02", "provenance": "user_provided", "recommended": [], "startups": [], "company": "Pellucid Grid", "watch": True},
    ]


def scan_403_docs() -> dict[str, Any]:
    return {"people.json": {"people": scan_people()}, "radar_regions.json": REGIONS, "radar_sources.json": {"schema": 2, "sources": copy.deepcopy(RADAR_DEFAULT_SOURCES)},
            "radar_cursor.json": {"next": 0, "batches_completed": 2, "last": "2026-11-05 09:00", "rate_limited": False, "note": ""},
            "radar_health.json": health_doc(), "radar_metrics.json": metrics_doc(), "real_data.json": {"signals": SIGNALS}, "config.json": {"github_token": TOKEN}}


def scan_403_sites() -> dict[str, Any]:
    oa = [s for s in RADAR_DEFAULT_SOURCES if s["kind"] == "openalex_works"]
    return {
        gh_search("Aldermoor"): ok_json({"total_count": 3, "items": [{"login": "orinthal"}, {"login": "kestrel42"}, {"login": "brightwater-sys"}]}),
        gh_search("Brisenthal"): ok_json({"total_count": 0, "items": []}),
        gh_search("Corvath"): {"status": 403, "headers": {"Content-Type": "application/json", "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1794474000"}, "json": {"message": "API rate limit exceeded"}},
        **github_users(),
        oa_works(oa[0]): ok_json(OA_WORKS),
        oa_works(oa[1]): ok_json({"results": []}),
        oa_works(oa[2]): {"status": 500, "headers": {"Content-Type": "application/json"}, "json": {"error": "invented outage"}},
    }


def scan_429_docs() -> dict[str, Any]:
    sources = [s for s in copy.deepcopy(RADAR_DEFAULT_SOURCES) if s["id"] in ("oa-de-robotics", "pz-data", "linkedin")]
    return {"people.json": {"people": scan_people()}, "radar_regions.json": REGIONS, "radar_sources.json": {"schema": 2, "sources": sources},
            "radar_cursor.json": {"next": 6, "batches_completed": 1}, "radar_metrics.json": metrics_doc(), "real_data.json": {"signals": SIGNALS}}


def scan_429_sites() -> dict[str, Any]:
    oa = [s for s in RADAR_DEFAULT_SOURCES if s["id"] == "oa-de-robotics"]
    sites = {
        gh_search("Grenmouth"): ok_json({"items": [{"login": "selkie-dev"}]}),
        gh_search("Halvardby"): ok_json({"items": [{"login": "tarnwick"}]}),
        gh_user("tarnwick"): {"status": 429, "headers": {"Content-Type": "application/json", "Retry-After": "120"}, "json": {"message": "secondary rate limit"}},
        gh_search("Aldermoor"): ok_json({"items": [{"login": "selkie-dev"}, {"login": "kestrel42"}]}),
        **github_users(),
        oa_works(oa[0]): ok_json(OA_WORKS),
    }
    for city in ("Brisenthal", "Corvath", "Dunmarrow", "Eskerholm", "Fjellvik"):
        sites[gh_search(city)] = ok_json({"items": []})
    return sites


LARK, QUILL, PELL, FERN, MARROW = "dom:larkspur.example", "dom:quillbright.example", "dom:pellucid.example", "name:fernhollow ai", "name:marrowgate labs"
PAD = 400_000  # the oversize /news page: its tail lies beyond the old read(MAX_BODY)


def research_sites() -> dict[str, Any]:
    home = ("<html><head><title>Larkspur Analytics</title><script>var x = 1;</script></head><body><nav>Home About Team News</nav><h1>Larkspur Analytics</h1>"
            "<p>Larkspur Analytics builds industrial machine learning for energy infrastructure and robotics. We are currently operating with three utilities. Our customers include regional grid operators. We're hiring!</p>"
            "<a href='/about'>About</a> <a href=\"/team/\">Team</a> <a href='/company'>Company deck</a> <a href='/news'>News</a> <a href='/press'>Press</a> <a href='/blog'>Blog</a> "
            "<a href='/careers'>Careers</a> <a href='/contact'>Contact</a> <a href='/logo.png'>logo</a> <a href='https://elsewhere.example/partner'>partner</a> "
            "<a href='https://github.com/larkspur-labs'>GitHub</a> <a href='https://www.linkedin.com/in/rhea-quintaval-0/'>Rhea on LinkedIn</a> <p>Write to hello@larkspur.example</p></body></html>")
    quill_home = ("<html><body><h1>Quillbright Robotics</h1><p>Quillbright Robotics is a spin-off building autonomous inspection robots, founded in 2024.</p>"
                  "<a href='/team'>Team</a> <a href='/about'>About</a> <a href='/news'>News</a> <a href='https://github.com/quillbright'>code</a></body></html>")
    return {
        "https://larkspur.example/robots.txt": html("User-agent: other-bot\nDisallow: /\nUser-agent: *\nDisallow: /careers/\n", ctype="text/html"),
        "https://larkspur.example/": html(home),
        "https://larkspur.example/about": html("<html><body><p>Larkspur Analytics was founded in 2025 by Rhea Quintaval and Tomas Eidervik in Porto. Since 2025 we deploy on the grid.</p></body></html>"),
        "https://larkspur.example/team": html("<html><body><h2>Our team</h2><p>Rhea Quintaval, Co-Founder & CEO.</p><p>Tomas Eidervik – Co-founder & CTO.</p><p>Read more</p></body></html>"),
        "https://larkspur.example/company": html("%PDF-1.4 invented", ctype="application/pdf"),
        "https://larkspur.example/news": html("<html><body><p>2026-10-28 — Larkspur Analytics raised a €2.5m seed round from an invented fund.</p><p>March 2026 — first pilot.</p><p>2027-01-01 — a planned launch.</p>",
                                              pad=PAD, tail="<p>Hidden Personname, Co-Founder & CEO.</p></body></html>"),
        "https://larkspur.example/press": redirect("https://press.elsewhere.example/larkspur"),
        "https://larkspur.example/blog": redirect("http://larkspur.example/blog", 302),
        "https://larkspur.example/contact": html("<html><body><p>Please sign in to continue.</p></body></html>"),
        "https://github.com/larkspur-labs": html("<html><body><p>larkspur-labs has 7 repositories. Rhea Quintaval, Co-Founder.</p></body></html>"),
        # served as HTML so the old code honours it too (a text/plain robots.txt is the 026b change, unit-tested)
        "https://quillbright.example/robots.txt": html("User-agent: *\nDisallow: /team\n", ctype="text/html"),
        "https://quillbright.example/": redirect("https://www.quillbright.example/"),
        "https://www.quillbright.example/": html(quill_home),
        "https://quillbright.example/team": html("<html><body><p>Co-founder Ilsa Marrowfield leads hardware.</p></body></html>"),
        "https://quillbright.example/about": redirect("https://quillbright.example/about-1", 302),
        "https://quillbright.example/about-1": redirect("https://quillbright.example/about-2", 302),
        "https://quillbright.example/about-2": redirect("https://quillbright.example/about-3", 307),
        "https://quillbright.example/about-3": redirect("https://quillbright.example/about-4", 308),
        "https://quillbright.example/news": {"status": 200, "error": "connection reset by the fixture"},
        "https://github.com/quillbright": redirect("https://github.com/quillbright-robotics"),
        "https://github.com/quillbright-robotics": html("<html><body><p>quillbright-robotics: 3 repositories.</p></body></html>"),
        "https://fernhollow.example/robots.txt": html("", status=404),
        "https://fernhollow.example/": html("<html><body><p>Fernhollow AI was founded in 2026. Contact team@fernhollow.example.</p></body></html>"),
    }


NAMES = {"pellucid.example": ["10.0.0.7"]}


def research_people() -> list[dict[str, Any]]:
    pz = [{"source": "Project Zero pipeline", "source_id": "pz-data", "url": "", "route": "pz-data"}]
    return [
        radar_person("p-rhea-quintaval-0042", "Rhea Quintaval", company="Larkspur Analytics", identity_status="resolved", founder_status="claimed (named in pipeline entry) — unverified", sources=pz, location="Porto", country="PT"),
        radar_person("p-ilsa-marrowfield-4410", "Ilsa Marrowfield", company="Quillbright Robotics", github_id="4410", sources=pz),
        radar_person("p-maelis-dorwent-2201", "Maelis Dorwent", company="Pellucid Grid", sources=pz),
        radar_person("p-wenna-calloway-5101", "Wenna Calloway", company="Fernhollow AI", profile_urls=["https://fernhollow.example/team", "https://github.com/wenna"], sources=pz),
        radar_person("p-corin-ashvale-3301", "Corin Ashvale", company="Marrowgate Labs", sources=pz),
    ]


def research_docs() -> dict[str, Any]:
    return {"people.json": {"people": research_people()}, "real_data.json": {"signals": SIGNALS},
            "radar_research.json": {"domains": {"name:old record": {"domain": "", "pages": {}, "pending": [], "done": False, "proposals": {}, "history": [], "note": "kept as it was"}}}}


def pid(field: str, value: str, url: str) -> str:
    return hashlib_sha(field + "|" + value + "|" + url)


FOUNDED = pid("founded", "2025", "https://larkspur.example/about")
HIRING = pid("hiring_signal", "open roles / hiring", "https://larkspur.example")

SETS: dict[str, Any] = {
    "scan_403": {"docs": scan_403_docs, "sites": scan_403_sites, "names": {}, "token": TOKEN,
                 "steps": [{"op": "scan"}]},
    "scan_429": {"docs": scan_429_docs, "sites": scan_429_sites, "names": {}, "token": None,
                 "steps": [{"op": "scan"}, {"op": "scan", "at": LATER}]},
    "research": {"docs": research_docs, "sites": research_sites, "names": NAMES, "token": None,
                 "steps": [{"op": "research", "body": {"key": LARK}},
                           {"op": "research", "body": {"key": LARK}},
                           {"op": "review", "body": {"key": LARK, "confirm": [FOUNDED], "reject": [HIRING]}},
                           {"op": "research", "body": {"key": LARK, "refresh": True}, "at": LATER},
                           {"op": "queue", "body": {"batch": 2}},
                           {"op": "queue", "body": {"batch": 2}},
                           {"op": "queue", "body": {}},
                           {"op": "research", "body": {}, "at": NEXT_DAY},
                           {"op": "research", "body": {"keys": [QUILL, FERN, "dom:unknown.example"], "refresh": True}}]},
}
# fmt: on


# ------------------------------------------------------------------ the fixture transport and resolver (new side)
def site_body(spec: Mapping[str, Any]) -> bytes:
    if "json" in spec:
        return json.dumps(spec["json"]).encode("utf-8")
    return str(spec.get("body", "") + " " * int(spec.get("pad", 0)) + spec.get("tail", "")).encode("utf-8")


class FixtureTransport:
    """Answers from the fixture sites and records every request it was asked to send (URL, headers, address)."""

    def __init__(self, sites: Mapping[str, Any]) -> None:
        self.sites = sites
        self.requests: list[dict[str, Any]] = []

    def send(
        self,
        target: net.Target,
        method: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
        max_bytes: int,
        deadline: float | None = None,
        *,
        truncate: bool = False,
    ) -> net.Response:
        default = 443 if target.scheme == "https" else 80
        url = f"{target.scheme}://{target.host}{'' if target.port == default else f':{target.port}'}{target.path}"
        self.requests.append({"url": url, "headers": dict(headers), "ip": target.ip, "method": method,
                              "max_bytes": max_bytes, "truncate": truncate})  # fmt: skip
        spec = self.sites.get(url, NOT_FOUND)
        if spec.get("error"):
            raise OSError(spec["error"])
        data = site_body(spec)
        if truncate:  # the transport reads only the prefix (core.net's truncating read)
            data = data[:max_bytes]
        if len(data) > max_bytes:
            raise net.ResponseTooLargeError(f"response exceeds the {max_bytes}-byte cap")
        return net.Response(
            url, int(spec.get("status", 200)), {k.lower(): v for k, v in (spec.get("headers") or {}).items()}, data
        )


def fixture_resolver(names: Mapping[str, list[str]]) -> net.Resolver:
    return lambda host: list(names.get(host, [FIXTURE_IP]))


# ------------------------------------------------------------------ the oracle
def _files(docs: dict[str, Any]) -> dict[str, bytes]:
    return {k: json.dumps(v, ensure_ascii=False, indent=2).encode("utf-8") for k, v in docs.items()}


def run_oracle(inp: dict[str, Any], files: dict[str, bytes]) -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-founder-radar-fetch-oracle-") as tmp:
        data = Path(tmp) / "data"
        data.mkdir(parents=True)
        for rel, raw in files.items():
            target = (data / rel).resolve()
            if data.resolve() not in target.parents:
                raise SystemExit(f"refusing a path outside the scratch folder: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        srcf, dst = Path(tmp) / "io" / "in.json", Path(tmp) / "io" / "out.json"
        srcf.parent.mkdir(parents=True, exist_ok=True)
        srcf.write_text(json.dumps(inp, ensure_ascii=False), encoding="utf-8")
        env = {
            k: v for k, v in os.environ.items() if not (k == "SUPABASE_DB_URL" or k.endswith(("_API_KEY", "_TOKEN")))
        }
        env |= {
            "PZ_DATA": str(data),
            "PZ_TESTING": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONPATH": str(OLD_REPO / "backend" / "src"),
        }
        run = subprocess.run([str(python), str(ORACLE), str(srcf), str(dst)], env=env, capture_output=True, text=True)
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_text(encoding="utf-8"))
        return out


# ------------------------------------------------------------------ the new side
class Store:
    """The new side's state between steps: what the DB layer would hold."""

    def __init__(self, docs: dict[str, Any]) -> None:
        self.docs = copy.deepcopy(docs)

    def inputs(self) -> routes.Inputs:
        d = self.docs
        people = (d.get("people.json") or {}).get("people") or []
        signals = (d.get("real_data.json") or {}).get("signals", [])
        return routes.Inputs(
            people=list(people), companies=d.get("radar_companies.json"), research=d.get("radar_research.json"),
            health=d.get("radar_health.json"), regions=d.get("radar_regions.json"), metrics=d.get("radar_metrics.json"),
            signals=signals,
        )  # fmt: skip

    def write(self, name: str, doc: Any, wrote: list[str]) -> None:
        if doc is not None:
            self.docs[name] = doc
            wrote.append(name)

    def apply(self, o: routes.Outcome, wrote: list[str]) -> None:
        if o.people is not None:
            body = dict(self.docs.get("people.json") or {})
            body["people"] = o.people
            self.write("people.json", body, wrote)
        self.write("radar_companies.json", o.companies, wrote)
        self.write("radar_research.json", o.research, wrote)
        self.write("radar_metrics.json", o.metrics, wrote)

    def stored(self) -> dict[str, Any]:
        return {n: js(self.docs.get(n)) for n in DOCS}


def _frozen(inp: routes.Inputs) -> str:
    return json.dumps(
        {k: (sorted(v) if isinstance(v, frozenset) else v) for k, v in inp.__dict__.items()}, ensure_ascii=False
    )


def new_side(spec: dict[str, Any], docs: dict[str, Any], clock: str) -> tuple[list[dict[str, Any]], list[str]]:
    """(the rows, the invariant problems)."""
    st = Store(docs)
    wall = clock
    out: list[dict[str, Any]] = []
    problems: list[str] = []
    sites = spec["sites"]
    for i, step in enumerate(spec["steps"]):
        wall = step.get("at") or wall
        now = utc_instant(wall)
        today = berlin_today(now)
        transport = FixtureTransport(sites)
        fetch = Fetch(transport=transport, resolver=fixture_resolver(spec.get("names") or {}))
        body = copy.deepcopy(step.get("body") or {})
        before = st.inputs()
        frozen = _frozen(before)
        wrote: list[str] = []
        try:
            o: routes.Outcome
            if step["op"] == "scan":
                so = scanning.scan(before, sources_doc=st.docs.get("radar_sources.json"), cursor_doc=st.docs.get("radar_cursor.json"),
                                   fetch=fetch, now=now, today=today, token=spec.get("token"), clock=lambda: 0.0)  # fmt: skip
                o = so.outcome
                st.apply(o, wrote)
                st.write("radar_cursor.json", so.cursor, wrote)
                st.write("radar_health.json", so.health, wrote)
            elif step["op"] == "research":
                o = research.research(before, body, fetch=fetch, now=now, today=today).outcome
                st.apply(o, wrote)
            elif step["op"] == "queue":
                ro = research.research_queue(
                    before, st.docs.get("radar_research_queue.json"), body, fetch=fetch, now=now, today=today
                )
                o = ro.outcome
                st.apply(o, wrote)
                st.write("radar_research_queue.json", ro.queue, wrote)
            else:
                fn: Callable[..., routes.Outcome] = {"review": routes.review, "pair": routes.pair}[step["op"]]
                o = fn(before, body, today=today, now=now)
                st.apply(o, wrote)
            row: dict[str, Any] = {"answer": {"code": o.status, "body": js(o.body)}}
            problems += [f"/steps[{i}]: {p}" for p in check_outcome(before, o)]
        except Exception as exc:
            row = {"answer": {"raises": type(exc).__name__}}
        if _frozen(before) != frozen:
            problems.append(f"/steps[{i}]: the input was mutated")
        row["wrote"] = wrote
        row["stored"] = st.stored()
        row["requests"] = transport.requests
        out.append(row)
    return out, problems


# ------------------------------------------------------------------ the comparison (declared differences normalised)
def normalized(value: Any) -> Any:
    """Durations as 0, the (b) GitHub hint as the old text."""
    if isinstance(value, dict):
        return {k: (0 if k == "seconds" and isinstance(v, (int, float)) else normalized(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [normalized(v) for v in value]
    if isinstance(value, str):
        return value.replace(scanning.TOKEN_HINT, scanning.OLD_TOKEN_HINT)
    return value


def normalized_requests(reqs: list[dict[str, Any]], with_ip: list[bool]) -> list[dict[str, Any]]:
    out = []
    for r, ip in zip(reqs, with_ip, strict=False):
        h = {
            k: (UA if k.lower() == "user-agent" else v)
            for k, v in (r.get("headers") or {}).items()
            if k.lower() != "host"
        }
        row = {"url": r["url"], "headers": dict(sorted(h.items()))}
        if ip:
            row["ip"] = r.get("ip")
        out.append(row)
    return out


def _key(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def compare_steps(
    s: dict[str, Any], expected: list[dict[str, Any]], got: list[dict[str, Any]], clock: str
) -> list[str]:
    problems: list[str] = []
    if len(expected) != len(got):
        return [f": {len(expected)} steps != {len(got)}"]
    signals = (s["docs"].get("real_data.json") or {}).get("signals", [])
    wall = clock
    for i, (step, a, b) in enumerate(zip(s["steps"], expected, got, strict=True)):
        wall = step.get("at") or wall
        x, y = normalized(a.get("answer")), normalized(b.get("answer"))
        if _key(x) != _key(y):
            problems += [f"/steps[{i}]/answer{p}" for p in diff({"x": x}, {"x": y})] or [
                f"/steps[{i}]/answer: key order differs"
            ]
        sa, sb = a["stored"], b["stored"]
        for n in DOCS:
            x, y = normalized(sa.get(n)), normalized(sb.get(n))
            if n == "radar_companies.json":  # 026a decision a: the references as a read derives them
                x = normalized_companies(
                    x or {"companies": {}}, sa.get("people.json"), signals, sa.get("radar_research.json"), wall
                )
                y = normalized_companies(
                    y or {"companies": {}}, sb.get("people.json"), signals, sb.get("radar_research.json"), wall
                )
            if _key(x) != _key(y):
                problems += [f"/steps[{i}]/stored/{n}{p}" for p in diff({"x": x}, {"x": y})] or [
                    f"/steps[{i}]/stored/{n}: key order differs"
                ]
        extra = set(b.get("wrote") or []) - set(a.get("wrote") or [])
        if extra:
            problems.append(f"/steps[{i}]/wrote: the new side wrote {sorted(extra)} that the old route did not")
        old_reqs = a.get("requests") or []
        with_ip = ["ip" in r for r in old_reqs]
        ra = normalized_requests(old_reqs, with_ip)
        rb = normalized_requests(b.get("requests") or [], with_ip + [False] * len(b.get("requests") or []))
        if len(old_reqs) != len(b.get("requests") or []) or _key(ra) != _key(rb):
            problems += [f"/steps[{i}]/requests{p}" for p in diff({"x": ra}, {"x": rb})] or [
                f"/steps[{i}]/requests differ"
            ]
    return problems


def _inputs_of(name: str) -> dict[str, Any]:
    spec = SETS[name]
    return {
        "docs": spec["docs"](),
        "sites": spec["sites"](),
        "names": spec["names"],
        "token": spec["token"],
        "steps": spec["steps"],
    }


def compare_goldens(golden: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for name, s in golden["sets"].items():
        expected = expand(s["expected"])
        got, invariants = new_side(s, s["docs"], golden["clock"])
        problems += [f"/{name}{p}" for p in invariants]
        problems += [f"/{name}{p}" for p in compare_steps(s, expected, got, golden["clock"])]
    return problems


def write_goldens() -> int:
    sets: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    for name in SETS:
        s = _inputs_of(name)
        oracle = run_oracle(
            {"clock": CLOCK, "sites": s["sites"], "names": s["names"], "steps": s["steps"]}, _files(s["docs"])
        )
        meta = oracle.pop("meta")
        sets[name] = {**s, "expected": compact(oracle["steps"])}
    golden = {"provenance": meta, "clock": CLOCK, "sets": sets}
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    # NOT sort_keys: the documents' insertion order is part of the input (and of what the oracle recorded)
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=None) + "\n", encoding="utf-8", newline="\n")
    problems = compare_goldens(json.loads(GOLDEN.read_text(encoding="utf-8")))
    print(
        json.dumps(
            {"golden": str(GOLDEN), "bytes": GOLDEN.stat().st_size, "old": meta, "summary": summary(golden)},
            indent=1,
            ensure_ascii=False,
        )
    )
    for p in problems[:80]:
        print("  DIFF", p[:400])
    print(
        "FOUNDER RADAR FETCH GOLDENS MATCH" if not problems else f"FOUNDER RADAR FETCH GOLDENS DIFFER ({len(problems)})"
    )
    return 1 if problems else 0


def summary(golden: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, s in golden["sets"].items():
        rows = []
        for st in s["expected"]:
            a = st.get("answer") or {}
            rows.append(
                {
                    "answer": a.get("raises") or a.get("code"),
                    "requests": len(st.get("requests") or []),
                    "wrote": st.get("wrote"),
                }
            )
        out[name] = rows
    return out


def main(argv: list[str]) -> int:
    if argv[1:] == ["goldens"]:
        return write_goldens()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

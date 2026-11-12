# ruff: noqa: E501
# (the old collector lines, verbatim)
"""The old ``domain/founder_radar/collectors.py`` (rev 6c739b9), ported line for line (review 026b): bounded public
collectors — GitHub REST, OpenAlex and the Project Zero pipeline (claims only).

Changes:
* The requests go through the injected ``Fetch`` (``fetching.github_json`` / ``openalex_json``: ``core.net``'s
  public-address guard, one origin each, at most 2 redirects, the default body cap; decision d). The old
  ``_get_json`` was plain ``urllib`` with no guard and no cap.
* The optional GitHub token is the ``token`` parameter (the caller reads ``PZ_GITHUB_TOKEN``, decision b); it is sent
  to ``https://api.github.com`` only. The old ``_gh_headers`` read ``config.json`` ``github_token``.
* The User-Agent is ``fetching.USER_AGENT`` (plan revision 2 §4; the old one was ``ProjectZero-FounderRadar``).
* The clock (decision f): ``now`` stamps ``retrieved`` (the old ``datetime.now()``), ``today`` is the OpenAlex
  ``publication_year`` and the GitHub "pushed this month" window (the old ``date.today()``).
* ``collect_pz_data`` takes the pipeline signals and returns ``(people, skipped)``; the old one read
  ``store.pipeline_signals()`` and left ``skipped`` on a function attribute.
"""

from __future__ import annotations

import urllib.parse
from datetime import date, datetime
from typing import Any

from projectzero.founder_radar.catalog import _ENTRE, _TRANSITION, _theme_terms
from projectzero.founder_radar.evidence import _ev
from projectzero.founder_radar.fetching import Fetch, github_json, openalex_json
from projectzero.founder_radar.names import is_person_name


def collect_github(
    src: dict[str, Any], fetch: Fetch, budget: int = 6, *, now: datetime, today: date, token: str | None = None
) -> list[dict[str, Any]]:
    """Bounded: 1 user search + ≤budget profile+repo lookups. Evidence only from the user's own public profile/repos."""

    q = urllib.parse.quote(src["query"])
    res = github_json(
        fetch, f"https://api.github.com/search/users?q={q}&sort=repositories&order=desc&per_page={budget}", token
    )
    out = []
    for u in (res.get("items") or [])[:budget]:
        prof = github_json(fetch, "https://api.github.com/users/{}".format(u["login"]), token)
        repos = github_json(fetch, "https://api.github.com/users/{}/repos?sort=pushed&per_page=5".format(u["login"]), token)  # fmt: skip
        name = (prof.get("name") or "").strip()
        human_name = bool(name) and is_person_name(name)
        if not human_name:
            name = u["login"]  # login only — flagged below as an unattributed name
        purl = prof.get("html_url", "")
        ev = []
        if prof.get("public_repos", 0) >= 10:
            ev.append(_ev("builder", "%d public repositories on GitHub" % prof["public_repos"], purl, src["name"], now=now))  # noqa: UP031  # fmt: skip
        stars = sum(r.get("stargazers_count", 0) for r in repos if isinstance(r, dict))
        if stars >= 50:
            ev.append(_ev("builder", "recently pushed repos hold %d stars" % stars, purl, src["name"], now=now))  # noqa: UP031
        recent = [
            r
            for r in repos
            if isinstance(r, dict) and str(r.get("pushed_at", ""))[:7] >= (today.replace(day=1)).isoformat()[:7]
        ]
        if recent:
            ev.append(
                _ev(
                    "trajectory",
                    "%d repositories pushed this month (%s)" % (len(recent), ", ".join(r["name"] for r in recent[:3])),  # noqa: UP031
                    purl,
                    src["name"],
                    activity_date=max(str(r.get("pushed_at", ""))[:10] for r in recent),
                    now=now,
                )
            )
        if prof.get("followers", 0) >= 100:
            ev.append(_ev("talent_magnet", "%d GitHub followers" % prof["followers"], purl, src["name"], now=now))  # noqa: UP031
        bio = str(prof.get("bio") or "")
        if _ENTRE.search(bio):
            ev.append(_ev("entrepreneurial", "profile bio: " + bio[:120], purl, src["name"], now=now))
        if _TRANSITION.search(bio):
            ev.append(_ev("trajectory", "bio signals a transition: " + bio[:120], purl, src["name"], now=now))
        blob = (
            bio
            + " "
            + " ".join(
                str(r.get("description") or "") + " " + str(r.get("language") or "")
                for r in repos
                if isinstance(r, dict)
            )
        ).lower()
        themes = sorted({t for t in _theme_terms() if t in blob})[:5]
        if themes:
            ev.append(_ev("project_a", "repo/bio themes: " + ", ".join(themes), purl, src["name"], now=now))
        out.append(
            {
                "name": name,
                "aliases": [u["login"]],
                "name_attributed": human_name,
                "location": prof.get("location") or "",
                "country": src.get("country", ""),
                "company": (prof.get("company") or "").lstrip("@"),
                "profile_urls": [x for x in [purl, prof.get("blog") or ""] if x],
                "github_id": str(prof.get("id", "")),
                "role": "",
                "evidence": ev,
                "sources": [
                    {
                        "source": src["name"],
                        "source_id": src["id"],
                        "url": purl,
                        "retrieved": now.strftime("%Y-%m-%d %H:%M"),
                        "route": "github-api",
                    }
                ],
                "why_surfaced": "GitHub search '{}': {}".format(
                    src["query"], "; ".join(x["claim"] for x in ev[:2]) or "matched the query"
                ),
            }
        )
    return out


def collect_openalex(
    src: dict[str, Any], fetch: Fetch, budget: int = 25, *, now: datetime, today: date
) -> list[dict[str, Any]]:

    flt = "publication_year:%d" % today.year + (  # noqa: UP031
        ",institutions.country_code:{}".format(src["country"])
        if src.get("country")
        else ",institutions.continent:europe"
    )
    url = (
        "https://api.openalex.org/works?search=%s&filter=%s&sort=publication_date:desc&per-page=%d&mailto=projectzero@example.org"  # noqa: UP031
        % (urllib.parse.quote(src["query"]), flt, budget)
    )
    res = openalex_json(fetch, url)
    out: dict[str, Any] = {}
    for w in res.get("results") or []:
        for au in (w.get("authorships") or [])[:3]:
            a = au.get("author") or {}
            if not a.get("display_name"):
                continue
            inst = [i.get("display_name") for i in (au.get("institutions") or []) if i.get("display_name")]
            key = a.get("id") or a["display_name"]
            p = out.setdefault(
                key,
                {
                    "name": a["display_name"],
                    "aliases": [],
                    "location": "",
                    "country": src.get("country", ""),
                    "company": "",
                    "institutions": inst,
                    "profile_urls": [a.get("id", "")],
                    "openalex_id": a.get("id", ""),
                    "orcid": a.get("orcid") or "",
                    "evidence": [],
                    "sources": [
                        {
                            "source": src["name"],
                            "source_id": src["id"],
                            "url": a.get("id", ""),
                            "retrieved": now.strftime("%Y-%m-%d %H:%M"),
                            "route": "openalex-api",
                        }
                    ],
                    "why_surfaced": "OpenAlex search '{}': recent work".format(src["query"]),
                },
            )
            p["evidence"].append(
                _ev(
                    "technical",
                    "{} ({})".format(
                        str(w.get("title") or w.get("display_name") or "work")[:90],
                        str(w.get("publication_date") or "")[:10],
                    ),
                    w.get("id", ""),
                    src["name"],
                    now=now,
                )
            )
            if au.get("author_position") == "first":
                p["evidence"].append(
                    _ev(
                        "trajectory",
                        "first author on a {} work".format(str(w.get("publication_date") or "")[:4]),
                        w.get("id", ""),
                        src["name"],
                        activity_date=str(w.get("publication_date") or "")[:10],
                        now=now,
                    )
                )
            blob = (
                str(w.get("title") or "")
                + " "
                + " ".join(str(c.get("display_name") or "") for c in (w.get("concepts") or [])[:8])
            ).lower()
            th = sorted({t for t in _theme_terms() if t in blob})[:4]
            if th:
                p["evidence"].append(
                    _ev(
                        "technical_theme",
                        "technical theme overlap in published work: " + ", ".join(th),
                        w.get("id", ""),
                        src["name"],
                        now=now,
                    )
                )
    return list(out.values())


def collect_pz_data(src: dict[str, Any], signals: Any, *, now: datetime) -> tuple[list[dict[str, Any]], list[str]]:
    """Founders named in existing Project Zero data (pipeline entries, events organizers/people, institutions) —
    provenance kept. Returns (candidates, the skipped placeholder / aggregate founder values)."""
    out = []
    sig = signals if isinstance(signals, list) else []  # the old store.pipeline_signals(): tolerant
    skipped = []
    for e in sig:
        for f in e.get("founders") or []:
            nm = (f.get("name") if isinstance(f, dict) else str(f)) or ""
            if not is_person_name(nm):  # placeholders / aggregates never become people
                if nm.strip():
                    skipped.append(nm.strip())
                continue
            # a name in a pipeline record is a SOURCE CLAIM — reviewable evidence, not verification
            ev = [
                _ev(
                    "entrepreneurial",
                    "claimed founder of {} ({}) — pipeline entry, unverified".format(
                        e.get("company"), e.get("stage") or e.get("earliness") or "pipeline entry"
                    ),
                    e.get("website") or "",
                    "Project Zero pipeline (claim)",
                    now=now,
                )
            ]
            if e.get("archetype"):
                ev.append(
                    _ev(
                        "project_a",
                        "company archetype {} (company-level, not person-level)".format(e["archetype"]),
                        e.get("website") or "",
                        "Project Zero pipeline (claim)",
                        now=now,
                    )
                )
            out.append(
                {
                    "name": nm.strip(),
                    "aliases": [],
                    "location": e.get("location", ""),
                    "country": "",
                    "company": e.get("company", ""),
                    "companies": [e.get("company", "")],
                    "role": (f.get("role") if isinstance(f, dict) else "") or "founder (claimed)",
                    "founder_status": "claimed (named in pipeline entry) — unverified",
                    "profile_urls": [],
                    "identity_status": "needs identity resolution",
                    "evidence": ev,
                    "sources": [
                        {
                            "source": "Project Zero pipeline",
                            "source_id": src["id"],
                            "url": e.get("website") or "",
                            "retrieved": now.strftime("%Y-%m-%d %H:%M"),
                            "route": "pz-data",
                            "claim": True,
                        }
                    ],
                    "why_surfaced": "named in pipeline entry for {} (claim — identity not yet verified)".format(
                        e.get("company")
                    ),
                }
            )
    return out, skipped

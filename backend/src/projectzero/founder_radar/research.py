"""Company research (``POST /api/radar_research`` and ``POST /api/radar_research_queue``): the old
``domain/founder_radar/research.py`` (rev 6c739b9) ``research_company`` / ``_crawl`` / ``research_company_queue`` and
the two router functions, ported line for line in the three phases of ``events/scan.py`` (review 026b, plan §2):

1. **plan** (pure, from the READ transaction): ``research_plan(inputs, body, ...)`` — the router's company list
   (``companies_queue`` over the listed people; ``keys`` / ``key`` / the first 5 un-researched, in queue order) — or
   ``queue_plan(inputs, queue_doc, body, ...)`` — the old queue state initialised or resumed and the next ``batch``
   keys taken off ``pending`` (``int(body["batch"] or 3)``; a non-integer raises ``ValueError`` as before).
2. **fetch** (``research_fetch(plan, fetch, ...)``, NO transaction): per company, in order, the old
   ``research_company`` first half on a WORKING copy of the read research document (the record set up, the candidate
   ``official_domain`` proposal, the refresh reset, the cached answer), then the bounded crawl (``_crawl``: robots.txt,
   the homepage, links discovered by ``LINK_PRIORITY``, the ``CRAWL_PATHS`` fallbacks, at most ``MAX_PAGES``
   same-domain requests, one public GitHub organisation page) through ``fetching.research_page`` and
   ``extraction.extract_proposals``; the result is merged into the working copy, so a later company of the same run
   sees it (as the old sequential saves did). The deadline (plan (a)): a company whose crawl cannot start, or that the
   deadline cuts off, is "not finished" (``DEADLINE_NOTE``): nothing of it is kept, and the later companies are not
   fetched either (their crawls cannot start).
3. **apply** (``research_apply(current, fetched, queue_doc=, ...)``, pure, in the WRITE transaction): each finished
   company is merged onto the CURRENT (re-read) research record exactly as the old second half did: ``pages``, the
   refresh's ``previous_runs`` / ``refreshed_at``, ``pending`` [], ``done``, ``last_research``, the working record's
   proposals and the new ones only ADDED by id (decisions, pairings, history and every proposal's status recorded
   meanwhile are kept). A company without a domain stores its ``note``; a cached one its ``last_research``.

What the store writes (``ResearchOutcome``), in one transaction: ``outcome.research`` (the whole
``radar_research.json`` body, key order significant; None when unchanged) with ``outcome.research_changed`` (the
changed domain keys, one ``radar_events`` row each), and for the queue ``queue`` (the whole
``radar_research_queue.json`` body; None when unchanged). ``outcome.body`` is the old answer.

Changes (each a plan decision): the clock (decision f: ``now`` stamps ``fetched`` / ``last_research`` /
``refreshed_at`` / ``previous_runs`` / ``retrieved`` / the queue's ``started`` / ``last_run``); the deadline; the
queue state is read in the read phase and written in the write phase under the run's session lock (the old code
mutated it outside its lock: a lost update when two runs overlapped); a deadline-cut company stays at the head of the
queue's ``pending`` (resumed by the next run) instead of being recorded as failed; an exception inside a crawl (none
is expected: every fetch failure is a page record) is that company's ``{ok: false, error}`` in ``radar_research``
(the old route answered 500); the founder references ``companies_queue`` derives are not written (review 026a
decision a). Changed (Codex H-221): robots.txt is read under the page controls but with its own media types, so one
served as ``text/plain`` is honoured (the old code blocked it as non-HTML and read it as "no rule")."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

from projectzero.founder_radar import fetching
from projectzero.founder_radar.catalog import CRAWL_PATHS, MAX_PAGES
from projectzero.founder_radar.clock import Clock
from projectzero.founder_radar.companies import companies_queue
from projectzero.founder_radar.extraction import _GH_ORG, _login_gated, _proposal, extract_proposals
from projectzero.founder_radar.fetching import _norm_host, _robots_disallowed, discover_links, safe_url
from projectzero.founder_radar.review import loaded_research
from projectzero.founder_radar.routes import Inputs, Outcome
from projectzero.network.view import listing

RESEARCH_DEADLINE_S = 60.0  # plan (a): one research batch, wall clock
DEADLINE_NOTE = "research deadline reached — this company was not researched; run it again"
NO_DOMAIN = "no canonical official domain — add a sourced domain/URL first"


def _new_domain_record(domain: str) -> dict[str, Any]:
    return {"domain": domain, "pages": {}, "pending": [], "done": False, "proposals": {}, "history": []}


def _key(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


def _js(v: Any) -> Any:
    return json.loads(json.dumps(v, ensure_ascii=False, default=str))


@dataclass
class Job:
    """One company of a run. ``kind``: ``no_domain`` | ``cached`` | ``crawl``."""

    company: dict[str, Any]
    domain: str
    refresh: bool
    kind: str = "crawl"
    candidate: dict[str, Any] | None = None  # the candidate official_domain proposal
    work: dict[str, Any] | None = None  # the crawled working record
    proposals: list[dict[str, Any]] = field(default_factory=list)
    cut: bool = False  # the deadline: not finished, nothing kept
    error: BaseException | None = None  # an exception inside the crawl

    @property
    def key(self) -> str:
        return str(self.company["key"])

    @property
    def finished(self) -> bool:
        return not self.cut and self.error is None


@dataclass(frozen=True)
class ResearchPlan:
    route: str  # "research" | "queue"
    companies: list[dict[str, Any]]  # the companies to research, in order
    refresh: bool
    research: Any  # the radar_research.json body read in phase 1
    queue: dict[str, Any] | None = None  # the queue state after this batch was taken (route "queue")


@dataclass(frozen=True)
class ResearchFetched:
    plan: ResearchPlan
    jobs: list[Job]


@dataclass(frozen=True)
class ResearchOutcome:
    outcome: Outcome  # body: the old answer; research / research_changed (None: unchanged)
    queue: dict[str, Any] | None = None  # radar_research_queue.json (route "queue"; None: unchanged)


def _companies(inputs: Inputs, ck: Clock) -> list[dict[str, Any]]:
    comps, _refs = companies_queue(
        listing(inputs.people, ck.today), companies_doc=inputs.companies, research_doc=inputs.research,
        signals=inputs.signals, now=ck.now, today=ck.today,
    )  # fmt: skip
    return comps


# ------------------------------------------------------------------ phase 1: plan
def research_plan(inputs: Inputs, body: dict[str, Any], *, today: date, now: datetime) -> ResearchPlan:
    """The old ``radar_research`` route's list: ``keys`` | [``key``] | the first 5 un-researched, in queue order."""
    ck = Clock.at(now, today)
    comps = _companies(inputs, ck)
    keys = body.get("keys") or (
        [body["key"]] if body.get("key") else [c["key"] for c in comps if not c.get("researched")][:5]
    )
    targets = [c for c in comps if c["key"] in keys]
    return ResearchPlan("research", copy.deepcopy(targets), bool(body.get("refresh")), copy.deepcopy(inputs.research))


def queue_plan(inputs: Inputs, queue_doc: Any, body: dict[str, Any], *, today: date, now: datetime) -> ResearchPlan:
    """The old ``research_company_queue`` first half: resumable, ``batch`` companies per call."""
    ck = Clock.at(now, today)
    batch = int(body.get("batch") or 3)
    companies = _companies(inputs, ck)
    st = copy.deepcopy(queue_doc) if isinstance(queue_doc, dict) else {}  # the old load_research_queue: tolerant
    eligible = [c for c in companies if c.get("domain") not in (None, "", "UNKNOWN")]
    if not st.get("pending") and not st.get("in_progress"):
        st = {
            "pending": [c["key"] for c in eligible if not c.get("researched")],
            "done": st.get("done", []),
            "failed": st.get("failed", {}),
            "skipped_no_domain": [c["name"] for c in companies if c.get("domain") in (None, "", "UNKNOWN")],
            "started": ck.minute(),
            "in_progress": True,
        }
    targets = []
    for key in list(st["pending"])[:batch]:
        c = next((x for x in companies if x["key"] == key), None)
        st["pending"].remove(key)
        if not c:
            continue
        targets.append(c)
    return ResearchPlan("queue", copy.deepcopy(targets), False, copy.deepcopy(inputs.research), st)


# ------------------------------------------------------------------ phase 2: fetch
def _prepare(res: dict[str, Any], c: dict[str, Any], refresh: bool, ck: Clock) -> Job:
    """The old ``research_company`` first half, on ``res`` (the working copy)."""
    domain = c.get("domain") if c.get("domain") not in (None, "", "UNKNOWN") else ""
    domain = str(domain or "")
    job = Job(copy.deepcopy(c), domain, refresh)
    dom = res["domains"].setdefault(c["key"], _new_domain_record(domain))
    dom.setdefault("history", [])
    dom.setdefault("proposals", {})
    if not domain:
        job.kind = "no_domain"
        return job
    if c.get("domain_source", "").startswith("candidate"):
        dp = _proposal(
            "official_domain",
            domain,
            "domain linked to the claimed founders' public profiles / evidence",
            "https://" + domain,
            c["name"] + " candidate domain",
            "candidate domain",
            "low",
            "confirm that this is the company's official domain",
            now=ck.now,
        )
        dom["proposals"].setdefault(dp["id"], dp)
        job.candidate = dp
    if refresh:
        dom["previous_runs"] = [
            *dom.get("previous_runs", []),
            {"at": ck.minute(), "pages": len(dom.get("pages") or {})},
        ]
        dom["pages"] = {}
        dom["pending"] = []
        dom["done"] = False
        dom["refreshed_at"] = ck.minute()
    if dom["done"] and not refresh:
        job.kind = "cached"
        return job
    job.work = copy.deepcopy(dom)
    return job


def _crawl(
    c: dict[str, Any], dom: dict[str, Any], domain: str, fetch: fetching.Fetch, max_pages: int, ck: Clock
) -> list[dict[str, Any]]:
    """The bounded crawl on the working record ``dom`` (pages / pending are updated in place). Returns new
    proposals. ``fetching.DeadlineReached`` propagates (the company is not finished)."""

    def page(u: str) -> dict[str, Any]:
        return fetching.research_page(fetch, u, domain)

    dis = _robots_disallowed(domain, lambda u: fetching.research_robots(fetch, u, domain))
    home = f"https://{domain}"
    fallbacks = [f"https://{domain}{p}" for p in CRAWL_PATHS if p]
    if not dom["pending"]:
        dom["pending"] = [home]
    proposals: list[dict[str, Any]] = []
    attempted = sum(1 for u in dom["pages"] if "github.com" not in u)
    gh_done = any("github.com" in u for u in dom["pages"])
    while (
        dom["pending"] or fallbacks
    ) and attempted < max_pages:  # bound applies to same-domain REQUESTS, not only successes
        url = dom["pending"].pop(0) if dom["pending"] else fallbacks.pop(0)
        if url in dom["pages"]:
            continue
        attempted += 1
        path = url.split(domain, 1)[-1] or "/"
        if any(path.startswith(d) for d in dis):
            dom["pages"][url] = {
                "requested_url": url,
                "final_url": url,
                "status": "skipped",
                "content_type": "",
                "reason": "skipped: robots.txt disallows",
                "fetched": ck.minute(),
            }
            continue
        ok, why, _u, _ips = safe_url(url, domain, fetch.resolve, require_https=False)
        if not ok:
            dom["pages"][url] = {
                "requested_url": url,
                "final_url": url,
                "status": "blocked",
                "content_type": "",
                "reason": "blocked: " + why,
                "fetched": ck.minute(),
            }
            continue
        rec = page(url)
        entry = {k: rec.get(k, "") for k in ("requested_url", "final_url", "status", "content_type", "reason")}
        entry["fetched"] = ck.minute()
        entry["chars"] = len(rec.get("body") or "")
        if (
            rec["status"] == 200
            and not rec.get("reason")
            and _norm_host(urlparse(rec["final_url"]).hostname or "") != _norm_host(domain)
        ):
            entry["reason"] = "blocked: final URL off the canonical host"
            entry["status"] = "blocked"
        if entry["status"] == 200 and not entry["reason"] and _login_gated(rec.get("body")):
            entry["reason"] = "skipped: login / access restricted"
            entry["status"] = "skipped"
        dom["pages"][url] = entry
        if entry["status"] != 200 or entry["reason"]:
            continue
        proposals += extract_proposals(rec["final_url"], rec["body"], c["name"], domain, now=ck.now, today=ck.today)
        for link in discover_links(rec["final_url"], rec["body"], domain):
            if link not in dom["pages"] and link not in dom["pending"] and link != home:
                dom["pending"].append(link)
        if not gh_done:
            for gh in list(dict.fromkeys(m.group(1) for m in _GH_ORG.finditer(rec["body"])))[
                :1
            ]:  # first linked org (v1: arbitrary set order)
                gurl = "https://github.com/" + gh
                gh_done = True
                okg, whyg, _, _ = safe_url(gurl, "github.com", fetch.resolve, require_https=False)
                if not okg:
                    dom["pages"][gurl] = {
                        "requested_url": gurl,
                        "final_url": gurl,
                        "status": "blocked",
                        "content_type": "",
                        "reason": "blocked: " + whyg,
                        "fetched": ck.minute(),
                    }
                    continue
                grec = fetching.research_page(fetch, gurl, fetching.GITHUB_WEB, exact=True)
                ge = {k: grec.get(k, "") for k in ("requested_url", "final_url", "status", "content_type", "reason")}
                ge["fetched"] = ck.minute()
                dom["pages"][gurl] = ge
                if grec["status"] == 200 and not grec.get("reason"):
                    proposals += extract_proposals(
                        gurl, grec["body"], c["name"], "github.com/" + gh, stype="public GitHub organisation",
                        now=ck.now, today=ck.today,
                    )  # fmt: skip
    return proposals


def research_fetch(
    plan: ResearchPlan, fetch: fetching.Fetch, *, now: datetime, today: date | None = None, max_pages: int = MAX_PAGES
) -> ResearchFetched:
    ck = Clock.at(now, today)
    res = loaded_research(plan.research)  # the working copy: later companies see earlier merges
    jobs: list[Job] = []
    for c in plan.companies:
        job = _prepare(res, c, plan.refresh, ck)
        jobs.append(job)
        if job.kind == "crawl":
            assert job.work is not None
            if fetch.expired():
                job.cut = True
                continue
            try:
                job.proposals = _crawl(job.company, job.work, job.domain, fetch, max_pages, ck)  # network
            except fetching.DeadlineReached:
                job.cut = True
                continue
            except Exception as e:
                job.error = e
                continue
        _merge(res, job, ck)
    return ResearchFetched(plan, jobs)


# ------------------------------------------------------------------ phase 3: apply
def _merge(res: dict[str, Any], job: Job, ck: Clock) -> dict[str, Any]:
    """The old ``research_company`` answer for ``job``, merged onto ``res`` (the old second half; for a record
    without a domain and a cached one, what the first half saved)."""
    dom = res["domains"].setdefault(job.key, _new_domain_record(job.domain))
    dom.setdefault("history", [])
    dom.setdefault("proposals", {})
    if job.kind == "no_domain":
        dom["note"] = NO_DOMAIN
        return {"ok": False, "error": dom["note"], "proposals": []}
    if job.candidate is not None:
        dom["proposals"].setdefault(job.candidate["id"], copy.deepcopy(job.candidate))
    if job.kind == "cached":
        dom["last_research"] = dom.get("last_research", "")
        return {
            "ok": True,
            "pages": len(dom["pages"]),
            "proposals": list(dom["proposals"].values()),
            "cached": True,
        }
    work = copy.deepcopy(job.work or {})
    dom["pages"] = work["pages"]
    for k in ("previous_runs", "refreshed_at"):
        if k in work:
            dom[k] = work[k]
    for pid, p in work["proposals"].items():  # e.g. the candidate official_domain proposal
        dom["proposals"].setdefault(pid, p)
    dom["pending"] = []
    dom["done"] = True
    new = 0
    for p in copy.deepcopy(job.proposals):
        if p["id"] not in dom["proposals"]:
            dom["proposals"][p["id"]] = p
            new += 1
    dom["last_research"] = ck.minute()
    return {
        "ok": True,
        "pages": len(dom["pages"]),
        "proposals": list(dom["proposals"].values()),
        "new": new,
        "cached": False,
    }


def _doc(before: Any, after: dict[str, Any]) -> tuple[Any, list[str]]:
    if _key(before) == _key(after):
        return None, []
    b = before.get("domains") if isinstance(before, dict) else None
    b = b if isinstance(b, dict) else {}
    return after, [k for k, v in after["domains"].items() if k not in b or _key(b[k]) != _key(v)]


def research_apply(
    current: Inputs, fetched: ResearchFetched, *, queue_doc: Any = None, now: datetime, today: date | None = None
) -> ResearchOutcome:
    """Onto the CURRENT research document (re-read in the write transaction). ``current`` is never changed."""
    ck = Clock.at(now, today)
    res = loaded_research(current.research)
    plan = fetched.plan
    if plan.route == "research":
        out = []
        for job in fetched.jobs:
            if job.cut:
                r: dict[str, Any] = {"ok": False, "error": DEADLINE_NOTE}
            elif job.error is not None:
                r = {"ok": False, "error": f"{type(job.error).__name__}: {str(job.error)[:120]}"}
            else:
                r = _merge(res, job, ck)
            out.append(
                {
                    "key": job.key,
                    "name": job.company["name"],
                    **{k: r.get(k) for k in ("ok", "error", "pages", "new", "cached")},
                    "proposals": len(r.get("proposals") or []),
                }
            )
        doc, changed = _doc(current.research, res)
        return ResearchOutcome(
            Outcome(200, _js({"ok": True, "researched": out}), research=doc, research_changed=changed)
        )
    st = copy.deepcopy(plan.queue or {})
    processed = []
    cut = []
    for job in fetched.jobs:
        c = job.company
        if job.cut:
            cut.append(job.key)
            processed.append({"name": c["name"], "ok": False, "error": DEADLINE_NOTE})
            continue
        if job.error is not None:
            st["failed"][job.key] = str(job.error)[:120]
            processed.append({"name": c["name"], "ok": False, "error": str(job.error)[:120]})
            continue
        r = _merge(res, job, ck)
        if r.get("ok"):
            st["done"].append(job.key)
            processed.append(
                {"name": c["name"], "ok": True, "pages": r.get("pages"), "proposals": len(r.get("proposals") or [])}
            )
        else:
            st["failed"][job.key] = r.get("error", "failed")
            processed.append({"name": c["name"], "ok": False, "error": r.get("error")})
    st["pending"] = cut + st["pending"]  # a deadline-cut company is resumed first by the next run
    st["in_progress"] = bool(st["pending"])
    st["last_run"] = ck.minute()
    answer = {
        "ok": True,
        "processed": processed,
        "remaining": len(st["pending"]),
        "done": len(st["done"]),
        "failed": st["failed"],
        "skipped_no_domain": st.get("skipped_no_domain", []),
        "in_progress": st["in_progress"],
        "resume": bool(st["pending"]),
    }
    doc, changed = _doc(current.research, res)
    queue = None if _key(st) == _key(queue_doc) else _js(st)
    return ResearchOutcome(Outcome(200, _js(answer), research=doc, research_changed=changed), queue)


def research(
    inputs: Inputs, body: dict[str, Any], *, fetch: fetching.Fetch, now: datetime, today: date
) -> ResearchOutcome:
    """``radar_research``: the three phases on one set of inputs (tests, parity)."""
    plan = research_plan(inputs, body, today=today, now=now)
    return research_apply(inputs, research_fetch(plan, fetch, now=now, today=today), now=now, today=today)


def research_queue(
    inputs: Inputs, queue_doc: Any, body: dict[str, Any], *, fetch: fetching.Fetch, now: datetime, today: date
) -> ResearchOutcome:
    """``radar_research_queue``: the three phases on one set of inputs (tests, parity)."""
    plan = queue_plan(inputs, queue_doc, body, today=today, now=now)
    fetched = research_fetch(plan, fetch, now=now, today=today)
    return research_apply(inputs, fetched, queue_doc=queue_doc, now=now, today=today)

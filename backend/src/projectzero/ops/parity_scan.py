# ruff: noqa: E501, RUF001
# (the corpus: one record per line; the watcher lines keep the typographic dash the old page split reads)
"""Deal Flow scan parity: the NEW scan against the OLD ``run_registry_concurrent`` + ``ingest_scan`` as oracle, with
the SAME recorded bytes on both sides and a FIXED clock (review 034a). Nothing touches the network.

    python -m projectzero.ops.parity_scan goldens   # (re)generates golden_v1/oracle_scan.json (needs the old repo)
    python -m projectzero.ops.parity_scan check     # the pure parts against the stored golden (no oracle, no database)
    python -m projectzero.ops.parity_scan hosted    # the whole new scan in a throw-away pz_itest_* schema
    python -m projectzero.ops.parity_scan real <old scratch data dir> <old app url>   # the imported scan state read back

The world (``world()``) is a registry of INVENTED sources (an RSS feed and a second one, two page watchers, one with an
archived ``.watch/`` baseline, a watcher that fails then recovers, an RSS source whose connection fails, a disabled
source, the structured SBIR / NSF / NIH / UKRI GtR / CORDIS / CKAN parsers on invented records) plus the registry's own
six V2 official sources over the old golden SYNTHETIC pages (``fixtures/golden/sources_v2_pages.json``), an imported
inbox with one candidate, the Conviction pipeline with one company, and an imported scan history. Two scans run at
two clocks; the second sees new lines, a strong-key merge into a scanned company, the known ones again and the
recovered source. The oracle (``scripts/oracle/scan_oracle.py``) runs the old code; the old ``_get_raw`` /
``_request_json`` answer from the same responses (``FixtureTransport`` is the new side's: same keys, same bytes).

``check``: for each step, the cut ``fetch`` (phase 2: ``_scan_one`` per source, the cut ``_resolve_batch``) over the
registry and baselines as the OLD side had them before the step, compared with the old pure output (the batch and the
report). ``hosted``: the world imported with the PRODUCTION importer into a scratch schema, then each step through
``dealflow.scan.run.scan`` with the fixture transport; compared after each step: the report rows, the summary, every
candidate record (names, tiers, decisions, flags, provenance, merges: the whole old inbox record), the sources'
runtime keys and cursors (``hwm``) and ``quality.candidates_found``, every watch baseline, and the scan history.

Declared differences, ALL applied by ``normalise`` (the ONE place):

* **(a) the imported record is never rewritten:** the old scan folded a known candidate's provenance into the inbox
  record (``absorb``); an IMPORTED candidate keeps its imported record (the count is the old one).
* **(a) a created candidate's id:** the summary's ``new_companies`` / ``baseline_companies`` carry the NEW candidate id;
  the collection maps it back to the record's old id (``attrs.scan_record.id``) before comparing.
* **(d) machine triage:** the summary gains ``triage`` ("machine triage arrives with the triage port").
* **revision 2, refusals:** the summary gains ``refused`` (0 here: this world holds no refused record; the hosted tests
  cover refusals and replays).
* **(e) the network errors:** an HTTP error status is ``core/net``'s ``FetchError: HTTP Error <n>`` where the old
  urllib said ``HTTPError: HTTP Error <n>: <reason>``.

The world holds INVENTED names only. Exit 1 on any difference.
"""

from __future__ import annotations

import copy
import functools
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from projectzero.core import net
from projectzero.core.paths import REPO_ROOT
from projectzero.dealflow.scan import ingest
from projectzero.dealflow.sources.catalog import registry_entries
from projectzero.dealflow.sources.normalize import load_registry
from projectzero.network.view import BERLIN
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js

ORACLE = REPO_ROOT / "scripts" / "oracle" / "scan_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_scan.json"
V2_PAGES = OLD_REPO / "backend" / "tests" / "fixtures" / "golden" / "sources_v2_pages.json"
CLOCKS = ("2026-11-13T09:00:00", "2026-11-20T09:00:00")
FIXTURE_IP = "93.184.216.34"


def uid(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]  # the old connectors._uid (an id, not security)


# ------------------------------------------------------------------ the fixture network (the new side)
class FixtureTransport:
    """Answers from the recorded responses (the oracle's keys: the URL, a POST as ``"POST <url> <body>"``) and records
    every request. A spec is ``{"body"}``, ``{"status"}`` or ``{"error"}`` (an ``OSError``); unknown keys are 404."""

    def __init__(self, responses: Mapping[str, Any], *, delay: float = 0.0) -> None:
        self.responses = responses
        self.delay = delay
        self.asked: list[str] = []

    def send(self, target: net.Target, method: str, headers: Mapping[str, str], body: bytes | None, timeout: float,
             max_bytes: int, deadline: float | None = None, *, truncate: bool = False) -> net.Response:  # fmt: skip
        default = 443 if target.scheme == "https" else 80
        url = f"{target.scheme}://{target.host}{'' if target.port == default else f':{target.port}'}{target.path}"
        key = url if method == "GET" else f"POST {url} {(body or b'').decode('utf-8')}"
        self.asked.append(key)
        if self.delay:
            import time

            time.sleep(self.delay)
        spec = self.responses.get(key) or {"status": 404}
        if "error" in spec:
            raise OSError(spec["error"])
        data = str(spec.get("body", "")).encode("utf-8")
        return net.Response(url, int(spec.get("status", 200)), {}, data)


def fixture_resolver(host: str) -> list[str]:
    return [FIXTURE_IP]


# ------------------------------------------------------------------ the world (invented names only)
FEED = "https://feed.invented.example/rss.xml"
FEED2 = "https://feed2.invented.example/rss.xml"
PAGE = "https://page.invented.example/spinoffs"
FIRST = "https://cohort.invented.example/members"
DOWN = "https://down.invented.example/list"
RESET = "https://reset.invented.example/rss.xml"
SBIR = "https://api.www.sbir.gov/public/api/awards"
NSF = "https://nsf.invented.example/awards.json"
NIH = "https://nih.invented.example/v2/projects/search"
GTR = "https://gtr.invented.example/api/search/project"
CKAN = "https://ckan.invented.example/api/3/action/datastore_search"
CORDIS_RSS = "https://cordis.europa.eu/search/rss?q=robotics"


def src(sid: str, name: str, url: str, kind: str, parser: str, stage: str, geo: list[str], **kw: Any) -> dict[str, Any]:
    return {"id": sid, "name": name, "url": url, "kind": kind, "parser": parser, "geo": geo,
            "sectors": ["ai_sw", "deeptech"], "stage": stage, "reliability": kw.pop("reliability", "medium"),
            "freshness": "daily", "enabled": kw.pop("enabled", True), "last_scan": None, "last_ok": None,
            "last_result_count": None, "failures_in_row": 0, "yield": {"kept": 0, "research": 0, "rejected": 0},
            "location": kw.pop("location", "Berlin, Germany"), "country": kw.pop("country", "Germany"),
            "geo_scope": kw.pop("geo_scope", "country"), "notes": "invented fixture source", **kw}  # fmt: skip


def rss(items: list[tuple[str, str, str, str]]) -> str:
    body = "".join(
        f"<item><title>{t}</title><link>{u}</link><description>{d}</description><pubDate>{p}</pubDate></item>"
        for t, u, d, p in items
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>Invented</title>{body}</channel></rss>'


def html(lines: list[str]) -> str:
    return (
        "<html><head><title>x</title></head><body><nav>Home About</nav>"
        + "".join(f"<p>{x}</p>" for x in lines)
        + "<footer>Imprint</footer></body></html>"
    )


def item(
    name: str,
    what: str = "raises €2M seed round for industrial autonomy software",
    pub: str = "Mon, 19 Oct 2026 09:00:00 +0000",
    host: str = "feed.invented.example",
) -> tuple[str, str, str, str]:
    return (
        f"{name} {what}",
        f"https://{host}/news/{name.lower().replace(' ', '-')}",
        f"{name} builds proprietary robotics software for factories.",
        pub,
    )


def nih_body(offset: int) -> str:
    return json.dumps({"criteria": {"fiscal_years": [2026], "activity_codes": ["R43", "R44", "U43", "U44"]},
                       "include_fields": ["Organization", "ProjectTitle", "ApplId"], "limit": 50, "offset": offset})  # fmt: skip


def registry() -> list[dict[str, Any]]:
    v2 = [e for e in registry_entries()]
    return [
        src("fx-feed", "Invented Feed", FEED, "rss", "rss", "mixed", ["DACH"]),
        src("fx-feed2", "Invented Feed Two", FEED2, "rss", "rss", "mixed", ["DACH"]),
        src("fx-page", "Invented Spin-off Page", PAGE, "watcher", "page_diff", "pre_company", ["DACH"]),
        src(
            "fx-cohort",
            "Invented Accelerator Cohort",
            FIRST,
            "watcher",
            "page_diff",
            "pre_company",
            ["CH"],
            location="Zurich, Switzerland",
            country="Switzerland",
        ),
        src(
            "fx-down",
            "Invented Lab Listing",
            DOWN,
            "watcher",
            "page_diff",
            "pre_company",
            ["NORD"],
            location="Oslo, Norway",
            country="Norway",
        ),
        src("fx-reset", "Invented Wire", RESET, "rss", "rss", "mixed", ["EU"], country="EU", geo_scope="region-eu"),
        src(
            "fx-off",
            "Invented Dormant Feed",
            "https://off.invented.example/rss.xml",
            "rss",
            "rss",
            "mixed",
            ["DACH"],
            enabled=False,
            notes="disabled by the operator",
        ),
        src(
            "fx-sbir",
            "Invented SBIR mirror",
            SBIR,
            "api",
            "sbir",
            "grant",
            ["US"],
            location="USA",
            country="USA",
            reliability="high",
        ),
        src(
            "fx-nsf",
            "Invented NSF mirror",
            NSF,
            "api",
            "nsf",
            "grant",
            ["US"],
            location="USA",
            country="USA",
            queries=["robotics"],
        ),
        src("fx-nih", "Invented NIH mirror", NIH, "api", "nih", "grant", ["US"], location="USA", country="USA"),
        src(
            "uk-gtr",
            "Invented UKRI mirror",
            GTR,
            "api",
            "gtr",
            "grant",
            ["UK"],
            location="UK",
            country="UK",
            queries=["autonomous"],
        ),
        src(
            "fx-cordis",
            "Invented CORDIS mirror",
            "https://cordis.europa.eu/",
            "api",
            "cordis",
            "grant",
            ["EU"],
            country="EU",
            geo_scope="region-eu",
            queries=["robotics"],
        ),
        src(
            "fx-ckan",
            "Invented CKAN mirror",
            CKAN,
            "dataset",
            "ckan",
            "grant",
            ["CA"],
            location="Canada",
            country="Canada",
            resource_id="res-invented-1",
        ),
        {
            **src(
                "ch-eth-dinfk",
                "ETH D-INFK spin-offs (static departmental list)",
                "https://inf.ethz.ch/department/spin-offs/spin-offs-list.html",
                "watcher",
                "page_diff",
                "pre_company",
                ["CH"],
            ),
            "enabled": False,
        },
        *v2,
    ]


def world_docs() -> dict[str, Any]:
    """The imported files of the world (the old data folder before the first scan)."""
    delta_id = uid("Invented Feed (feed)", "Delta Grid")
    delta = {"id": delta_id, "name": "Delta Grid", "source": "Invented Feed (feed)", "discovery_tier": "announcement",
             "source_url": "https://feed.invented.example/news/delta-grid", "date": "Thu, 01 Oct 2026 09:00:00 +0000",
             "date_kind": "published", "detected_on": "2026-10-01", "location": "Europe", "country": "EU",
             "description": "Delta Grid secures €1M pre-seed for grid software — Delta Grid builds grid software.",
             "why": ["Announcement feed — discovery only; probably recently funded"], "archetype_hits": [8], "twins": [],
             "noise": False, "decision": "new", "notes": "", "priority": 4, "source_id": "fx-feed", "geo": ["DACH"],
             "first_seen": "2026-10-01", "source_date": "2026-10-01", "src_quality": 1, "geo_scope": "country",
             "source_sectors": ["ai_sw", "deeptech"], "sectors": ["ai_sw", "climate"], "run_id": "2026-10-01 08:00:00",
             "first_seen_run": "2026-10-01 08:00:00", "last_observed": "2026-10-01 08:00:00", "seen_runs": 1,
             "all_source_ids": ["fx-feed"], "quality_source_id": "fx-feed", "q_found": ["fx-feed"]}  # fmt: skip
    old_scan = {"new": 1, "baseline": 0, "noise": 0, "pre_company_new": 0, "run_id": "2026-10-01 08:00:00",
                "scan_started": "2026-10-01 08:00:00", "scan_finished": "2026-10-01 08:00:30", "sources_attempted": 1,
                "sources_ok": 1, "sources_failed": 0, "sources_off": 0, "raw_records": 1, "records_after_source_filters": 1,
                "merged_cross_source": 0, "merged_into_existing": 0, "provenance_added": 0, "known_skipped": 0,
                "known_skipped_names": [], "known_pipeline": 0, "known_pipeline_names": [],
                "pipeline_label": "Existing pipeline — not discovered in this scan",
                "new_companies": [{"id": delta_id, "name": "Delta Grid", "source": "Invented Feed (feed)", "source_id": "fx-feed",
                                   "source_url": "https://feed.invented.example/news/delta-grid", "source_date": "2026-10-01",
                                   "first_seen": "2026-10-01", "decision": "new"}],
                "baseline_companies": [], "merged_names": []}  # fmt: skip
    report = [{"source": "Invented Feed", "tier": "rss", "status": "ok", "note": "1 item(s) in feed", "geo": ["DACH"],
               "source_id": "fx-feed", "url": FEED, "raw": 1, "count": 1, "baseline": 0, "interstitial": 0,
               "fetch": {"attempts": 1, "ok": 1, "failed": 0}}]  # fmt: skip
    hist = {"scans": [{**old_scan, "sources": [{"source": "Invented Feed", "source_id": "fx-feed", "status": "ok", "raw": 1,
                                               "count": 1, "baseline": 0, "url": FEED, "note": "1 item(s) in feed"}]}]}  # fmt: skip
    pipeline = {"signals": [{"company": "Kyrok Systems", "website": "https://www.kyrok.example.com/", "status": "new",
                             "one_liner": "Invented pipeline company", "source": "Founder call"}]}  # fmt: skip
    page_uid = uid(PAGE)
    return {
        "sources.json": {"sources": registry()},
        "inbox.json": {
            "candidates": [delta],
            "last_run": "2026-10-01 08:00:00",
            "reprocess_v": 3,
            "report": report,
            "last_summary": old_scan,
        },
        "real_data.json": pipeline,
        "scan_history.json": hist,
        f".watch/{page_uid}.json": [
            "Golf Sensors GmbH – photonic spin-off founded 2025",
            "Contact the transfer office team",
        ],
    }


def responses(step: int, v2_pages: Mapping[str, str]) -> dict[str, Any]:
    feed = [item("Aurora Robotics"), item("Delta Grid", "secures €1M pre-seed for grid software"),
            item("Kyrok Systems", "raises seed for supply-chain automation"),
            item("Alpha Holding", "raises seed for real estate consulting services"),
            ("Weekly roundup: what we read", "https://feed.invented.example/news/roundup", "Nothing about funding.", "Mon, 19 Oct 2026 09:00:00 +0000")]  # fmt: skip
    feed2 = [item("Aurora Robotics", "secures €2M seed round", "Tue, 20 Oct 2026 09:00:00 +0000", "feed2.invented.example"),
             item("Echo Photonics", "closes pre-seed for photonic chips", host="feed2.invented.example")]  # fmt: skip
    page = ["Golf Sensors GmbH – photonic spin-off founded 2025", "Contact the transfer office team",
            "Hotel Robotics GmbH – robotics spin-off founded 2026", "09.10.2026 15:09", "India Quantum opens Munich office"]  # fmt: skip
    cohort = ["Juliet AI GmbH – selected for the 2026 cohort", "Kilo Drives Startup wins the founders prize",
              "About the programme team"]  # fmt: skip
    sbir_rows = [{"firm": "Lima Robotics Inc", "award_id": "A-1001", "award_title": "Autonomous inspection drones", "agency": "DOD",
                  "phase": "1", "award_year": 2026, "city": "Austin", "state": "TX", "award_link": "https://www.sbir.gov/award/1001",
                  "proposal_award_date": "2026-03-02", "uei": "UEILIMA00001", "duns": "123456789", "company_url": "https://lima-robotics.example.com/about"},
                 {"firm": "Mike Sensors LLC", "award_id": "A-1002", "award_title": "Quantum sensor fabrication", "agency": "DOE",
                  "phase": "2", "award_year": 2026, "city": "Boulder", "state": "CO"}]  # fmt: skip
    if step == 1:
        feed.append(item("Sierra Drones", "raises €3M seed for drone swarms"))
        page.append("Tango Lidar GmbH – lidar spin-off founded 2026")
        cohort.append("Uniform Materials GmbH – spin-off founded 2026")
        sbir_rows.append({"firm": "Lima Robotics, Inc.", "award_id": "A-1003", "award_title": "Swarm autonomy", "agency": "DOD",
                          "phase": "2", "award_year": 2026, "uei": "UEILIMA00001", "award_link": "https://www.sbir.gov/award/1003"})  # fmt: skip
    nsf = {"response": {"award": [{"id": "N-1", "title": "Robotic welding cells", "awardee": "November Robotics Inc", "fundProgramName": "SBIR Phase I"},
                                  {"id": "N-2", "title": "Basic research", "awardee": "University of Somewhere", "fundProgramName": "Research"}]}}  # fmt: skip
    nih = {"results": [{"organization": {"org_name": "OSCAR THERAPEUTICS INC", "org_uei": ["UEIOSCAR0001"]},
                        "project_title": "Robotic drug screening", "appl_id": 111}]}  # fmt: skip
    gtr = {"project": [{"id": "P-1", "title": "Autonomous ships", "grantCategory": "Feasibility Studies",
                        "links": {"link": [{"rel": "LEAD_ORG", "href": "https://gtr.invented.example/api/organisations/O-1"},
                                           {"rel": "PARTICIPANT_ORG", "href": "https://gtr.invented.example/api/organisations/O-2"}]}}]}  # fmt: skip
    cordis = ('<?xml version="1.0"?><rss version="2.0"><channel><title>CORDIS</title><item><title>Robot swarms for farms</title>'
              "<link>https://cordis.europa.eu/project/id/101077?WT.mc_id=RSS-Feed&amp;WT.rss_a=1</link></item></channel></rss>")  # fmt: skip
    cordis_xml = ("<project><organization><legalName>QUEBEC ROBOTICS SA</legalName><address><country>FR</country></address>"
                  "<activityType>Private for-profit entities (excluding Higher or Secondary Education Establishments)</activityType></organization>"
                  "<organization><legalName>UNIVERSITE INVENTEE</legalName><address><country>FR</country></address>"
                  "<activityType>Higher or Secondary Education Establishments</activityType></organization></project>")  # fmt: skip
    ckan = {
        "result": {
            "records": [{"recipient_legal_name": "Romeo Photonics Inc.", "description_en": "Photonic sensor R&D"}]
        }
    }
    out: dict[str, Any] = {
        FEED: {"body": rss(feed)},
        FEED2: {"body": rss(feed2)},
        PAGE: {"body": html(page)},
        FIRST: {"body": html(cohort)},
        DOWN: {"status": 404} if step == 0 else {"body": html(["Victor Space GmbH – spin-off founded 2026"])},
        RESET: {"error": "connection reset by peer"},
        f"{SBIR}?year=2026&rows=1": {"body": "[]"},
        f"{SBIR}?year=2026&rows=50&start=0": {"body": json.dumps(sbir_rows)},
        f"{SBIR}?year=2026&rows=50&start=50": {"body": "[]"},
        f"{NSF}?keyword=robotics&printFields=id,title,awardee,date,fundProgramName&offset=1": {"body": json.dumps(nsf)},
        f"{NSF}?keyword=robotics&printFields=id,title,awardee,date,fundProgramName&offset=26": {
            "body": json.dumps({"response": {"award": []}})
        },
        f"POST {NIH} {nih_body(0)}": {"body": json.dumps(nih)},
        f"POST {NIH} {nih_body(50)}": {"body": json.dumps({"results": []})},
        f"{GTR}?term=autonomous&page=1&size=20": {"body": json.dumps(gtr)},
        "https://gtr.invented.example/api/organisations/O-1": {
            "body": json.dumps({"name": "Papa Marine Ltd", "id": "O-1"})
        },
        "https://gtr.invented.example/api/organisations/O-2": {
            "body": json.dumps({"name": "University of Nowhere", "id": "O-2"})
        },
        CORDIS_RSS: {"body": cordis},
        "https://cordis.europa.eu/project/id/101077?format=xml": {"body": cordis_xml},
        f"{CKAN}?resource_id=res-invented-1&limit=25": {"body": json.dumps(ckan)},
    }
    for url, text in v2_pages.items():
        out[url] = {"body": text}
    return out


def world_input(v2_pages: Mapping[str, str]) -> dict[str, Any]:
    return {"max_workers": 1, "docs": world_docs(),
            "steps": [{"clock": c, "days": 7, "responses": responses(i, v2_pages)} for i, c in enumerate(CLOCKS)]}  # fmt: skip


# ------------------------------------------------------------------ the oracle
def files_of(docs: Mapping[str, Any]) -> dict[str, bytes]:
    return {k: json.dumps(v, ensure_ascii=False, indent=2).encode("utf-8") for k, v in docs.items()}


def oracle(inp: Mapping[str, Any]) -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-scan-oracle-") as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        for rel, raw in files_of(inp["docs"]).items():
            target = (data / rel).resolve()
            if data.resolve() not in target.parents:
                raise SystemExit(f"refusing a path outside the scratch folder: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        srcf, dst = Path(tmp) / "in.json", Path(tmp) / "out.json"
        srcf.write_bytes(json.dumps({k: inp[k] for k in ("max_workers", "steps")}, ensure_ascii=False).encode("utf-8"))
        env = {k: v for k, v in os.environ.items() if k != "SUPABASE_DB_URL" and not k.endswith(("_API_KEY", "_TOKEN"))}
        env.update({"PZ_DATA": str(data), "PZ_TESTING": "1", "PYTHONPATH": str(OLD_REPO / "backend" / "src")})
        res = subprocess.run([str(python), str(ORACLE), str(srcf), str(dst)], env=env, capture_output=True, text=True)
        if res.returncode != 0:
            raise SystemExit(f"oracle failed:\n{res.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_bytes().decode("utf-8"))
        return out


# ------------------------------------------------------------------ completion order (not a difference)
def ordered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The per-source rows by source (the old scan appended them in COMPLETION order, which is not deterministic
    even with one worker: the futures finished during one wait come back as a set), the system rows after them."""
    src = [r for r in rows if r.get("tier") != "system"]
    return sorted(src, key=lambda r: str(r.get("source_id") or r.get("source"))) + [
        r for r in rows if r.get("tier") == "system"
    ]


def ordered_pure(p: Mapping[str, Any]) -> dict[str, Any]:
    return {"merged": sorted(p["merged"], key=lambda c: str(c.get("id"))), "report": ordered(list(p["report"]))}


def ordered_state(st: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(st)
    out["report"] = ordered(list(st["report"]))
    out["history"] = [{**h, "sources": sorted(h.get("sources") or [], key=lambda r: str(r.get("source_id") or r.get("source")))}
                      for h in st["history"]]  # fmt: skip
    return out


# ------------------------------------------------------------------ the declared differences (ONE place)
_HTTP = re.compile(r"HTTPError: HTTP Error (\d{3}): [A-Za-z ]+")


def _errors(v: Any) -> Any:
    """(e): the old urllib error text -> ``core/net``'s."""
    if isinstance(v, dict):
        return {k: _errors(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_errors(x) for x in v]
    if isinstance(v, str):
        return _HTTP.sub(r"FetchError: HTTP Error \1", v)
    return v


def normalise(step: Mapping[str, Any], seed: Mapping[str, Any]) -> dict[str, Any]:
    """The old step -> the expected new one. ``seed``: the imported inbox records by id (declared a)."""
    s = _errors(copy.deepcopy(dict(step)))
    summary = {**s["summary"], "refused": 0, "triage": ingest.TRIAGE_NOTE}  # revision 2 / (d)
    candidates = {
        c["id"]: (copy.deepcopy(seed[c["id"]]) if c["id"] in seed else c) for c in s["inbox"]["candidates"]
    }  # (a)
    scans = [({**h, "refused": 0, "triage": ingest.TRIAGE_NOTE} if h.get("run_id") in s["new_runs"] else h)
             for h in s["history"]["scans"]]  # fmt: skip
    return {"summary": summary, "report": s["inbox"]["report"], "last_run": s["inbox"]["last_run"],
            "candidates": candidates, "sources": sources_state(s["sources"]["sources"]), "watch": s["watch"],
            "history": scans}  # fmt: skip


def sources_state(sources: list[dict[str, Any]]) -> dict[str, Any]:
    keys = (
        "enabled",
        "last_scan",
        "last_ok",
        "last_result_count",
        "failures_in_row",
        "total_results",
        "last_truncated",
        "hwm",
    )
    return {s["id"]: {**{k: s.get(k) for k in keys}, "candidates_found": (s.get("quality") or {}).get("candidates_found", 0)}
            for s in sources if isinstance(s, dict)}  # fmt: skip


# ------------------------------------------------------------------ check: the pure parts
def new_pure(sources_doc: Mapping[str, Any], watch: Mapping[str, Any], step: Mapping[str, Any]) -> dict[str, Any]:
    from projectzero.dealflow.scan import run

    sources = load_registry({"sources": copy.deepcopy(list(sources_doc["sources"]))})["sources"]
    baselines = {k.split("/", 1)[1]: {"lines": v, "seeded_from": k} for k, v in watch.items()}
    clock = datetime.fromisoformat(step["clock"])
    f = run.fetch(sources, baselines, days=int(step["days"]), today=clock.date(), now_stamp=clock.strftime("%Y-%m-%d %H:%M"),
                  transport=FixtureTransport(step["responses"]), resolver=fixture_resolver, max_workers=1)  # fmt: skip
    return {"merged": f.merged, "report": f.report}


def compare_pure(golden: Mapping[str, Any]) -> list[str]:
    from projectzero.dealflow.scan import parsers

    parsers._GTR_ORG_CACHE.clear()
    inp, exp = golden["input"], golden["expected"]
    problems: list[str] = []
    before_sources, before_watch = (
        inp["docs"]["sources.json"],
        {k: v for k, v in inp["docs"].items() if k.startswith(".watch/")},
    )
    for i, step in enumerate(inp["steps"]):
        old = _errors(exp["steps"][i]["pure"])
        problems += diff(
            js(ordered_pure(old)), js(ordered_pure(new_pure(before_sources, before_watch, step))), f"/step{i}/pure"
        )
        before_sources, before_watch = exp["steps"][i]["sources"], exp["steps"][i]["watch"]
    return problems


# ------------------------------------------------------------------ hosted: the whole new scan
def new_state(conn: Any, schema: str, summary: dict[str, Any], archived_watch: Mapping[str, Any]) -> dict[str, Any]:
    from psycopg.rows import dict_row

    from projectzero.dealflow.ranking.service import ranking_input
    from projectzero.dealflow.scan import history
    from projectzero.dealflow.sources.store import SourcesStore

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"select * from {schema}.candidates order by first_seen_at, id".encode())
        rows = cur.fetchall()
        cur.execute(f"select uid, lines from {schema}.scan_watch_snapshots".encode())
        snaps = {f".watch/{r['uid']}.json": r["lines"] for r in cur.fetchall()}
    old_id = {str(r["id"]): (r["attrs"].get("scan_record") or {}).get("id", r["id"]) for r in rows}
    candidates = {}
    for r in rows:
        c, _ = ranking_input(r)
        candidates[str(c.get("id") if "scan_record" in (r["attrs"] or {}) else r["id"])] = c

    def old_ids(entry: dict[str, Any]) -> dict[str, Any]:  # (a): a candidate id back to its record's old id
        e = copy.deepcopy(entry)
        for k in ("new_companies", "baseline_companies"):
            if isinstance(e.get(k), list):
                e[k] = [{**x, "id": old_id.get(x["id"], x["id"])} for x in e[k]]
        return e

    s = old_ids(summary)
    last = history.latest(conn, schema)
    return {"summary": s, "report": last["report"] if last else [], "last_run": last["run_id"] if last else None,
            "candidates": candidates, "sources": sources_state(SourcesStore(conn, schema).view()["sources"]),
            "watch": dict(sorted({**archived_watch, **snaps}.items())),
            "history": [old_ids(h) for h in history.scan_history(conn, schema)["scans"]]}  # fmt: skip


def hosted(golden: Mapping[str, Any] | None = None) -> int:  # pragma: no cover - needs the hosted database
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import transaction
    from projectzero.dealflow.scan import parsers, run
    from projectzero.ops.scratch_import import drop_schema, import_world

    load_dotenv()
    settings = Settings.from_env()
    golden = golden or json.loads(GOLDEN.read_text(encoding="utf-8"))
    inp, exp = golden["input"], golden["expected"]
    parsers._GTR_ORG_CACHE.clear()
    schema = import_world(settings.db_url, inp["docs"])
    problems: list[str] = []
    seed = {c["id"]: c for c in inp["docs"]["inbox.json"]["candidates"]}
    archived = {k: v for k, v in inp["docs"].items() if k.startswith(".watch/")}
    runs: list[str] = []
    try:
        for i, step in enumerate(inp["steps"]):
            clock = datetime.fromisoformat(step["clock"]).replace(tzinfo=BERLIN)
            frozen: Callable[[], datetime] = functools.partial(lambda c: c, clock)
            summary = run.scan(settings.db_url, schema, days=int(step["days"]), clock=frozen,
                               transport=FixtureTransport(step["responses"]), resolver=fixture_resolver,
                               max_workers=int(inp["max_workers"]))  # fmt: skip
            runs.append(summary["run_id"])
            with transaction(settings.db_url) as conn:
                new = new_state(conn, schema, summary, archived)
            old = normalise({**exp["steps"][i], "new_runs": runs}, seed)
            problems += diff(js(ordered_state(old)), js(ordered_state(new)), f"/step{i}")
            print(
                json.dumps(
                    {"step": i, "summary": {k: v for k, v in summary.items() if isinstance(v, int)}}, ensure_ascii=False
                )
            )
    finally:
        drop_schema(settings.db_url, schema)
    for p in problems[:80]:
        print("  DIFF", p)
    print("SCAN HOSTED PARITY PASSED" if not problems else f"SCAN HOSTED PARITY FAILED ({len(problems)})")
    return 1 if problems else 0


REAL_KEYS = ("report", "last_run", "last_summary", "pipeline_label")


def real(data_dir: str, old_url: str) -> int:  # pragma: no cover - for the main session: needs the hosted database
    """The read-back of the imported scan state (034a Verification, "Real snapshot"): ``data_dir`` (the OLD app's
    scratch copy, which the old app at ``old_url`` serves; never the live data folder) is imported by the PRODUCTION
    importer into a throw-away schema, then the new ``GET /api/deal-flow/inbox`` (its ``report``, ``last_run``,
    ``last_summary``, ``pipeline_label``), ``scan_history`` (n = 20 and the whole history) and ``find_status`` are
    compared with the old ``/api/inbox``, ``/api/scan_history`` and ``/api/find_status`` over the same bytes. Nothing is
    scanned and nothing touches the network beyond the local old app. Every table is checked unchanged by the reads.
    Aggregates only are printed (no name)."""
    import secrets as _secrets
    import urllib.request

    from fastapi.testclient import TestClient

    from projectzero.api.app import create_app
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import connect, transaction
    from projectzero.ops.db_check import _scratch_sql
    from projectzero.ops.legacy.apply import apply_plan
    from projectzero.ops.legacy.plan import build_plan
    from projectzero.ops.legacy.source import LegacySnapshot
    from projectzero.ops.parity_validation import _fingerprint
    from projectzero.ops.scratch_import import drop_schema

    if not re.match(r"^http://(127\.0\.0\.1|localhost):\d+$", old_url):
        raise SystemExit("the old app must be a local scratch instance")
    load_dotenv()  # the app's start runs no overdue job: importing ``ops`` turned the catch-up off
    settings = Settings.from_env()

    def old_get(path: str) -> Any:
        with urllib.request.urlopen(old_url + path, timeout=60) as r:  # a local scratch app only (checked above)
            return json.loads(r.read().decode("utf-8"))

    old_inbox = old_get("/api/inbox")
    old = {
        "inbox": {k: old_inbox.get(k) for k in REAL_KEYS},
        "history20": old_get("/api/scan_history?n=20"),
        "history_all": old_get("/api/scan_history?n=100000"),
        "find_status": old_get("/api/find_status"),
    }
    snapshot_ = LegacySnapshot.capture(Path(data_dir))
    schema = f"pz_rehearse_{_secrets.token_hex(4)}"
    admin = connect(settings.db_url, autocommit=True)
    problems: list[str] = []
    try:
        admin.execute(_scratch_sql(schema).encode())
        conn = connect(settings.db_url)
        try:
            applied = apply_plan(build_plan(snapshot_), schema=schema, conn=conn)
            assert applied.get("applied"), applied
        finally:
            conn.close()
        with transaction(settings.db_url) as c:
            before = _fingerprint(c, schema)
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            new_inbox = client.get("/api/deal-flow/inbox").json()
            new = {
                "inbox": {k: new_inbox.get(k) for k in REAL_KEYS},
                "history20": client.get("/api/deal-flow/scan_history?n=20").json(),
                "history_all": client.get("/api/deal-flow/scan_history?n=100000").json(),
                "find_status": client.get("/api/deal-flow/find_status").json(),
            }
        with transaction(settings.db_url) as c:
            after = _fingerprint(c, schema)
        problems += diff(js(old), js(new), "")
        changed = sorted(t for t in set(before) | set(after) if before.get(t) != after.get(t))
        if changed:
            problems.append(f"/tables: the reads changed {changed}")
        summary = old["inbox"]["last_summary"] or {}
        print(json.dumps({
            "report_rows": len(old["inbox"]["report"] or []),
            "summary_counts": {k: v for k, v in summary.items() if isinstance(v, int)},
            "history_total": old["history_all"].get("total"),
            "history_listed": [len(old["history20"].get("scans") or []), len(old["history_all"].get("scans") or [])],
        }, ensure_ascii=False))  # fmt: skip
    finally:
        admin.close()
        drop_schema(settings.db_url, schema)
    for p in problems[:80]:
        print("  DIFF", p)
    print("SCAN REAL PARITY PASSED" if not problems else f"SCAN REAL PARITY FAILED ({len(problems)})")
    return 1 if problems else 0


# ------------------------------------------------------------------ goldens / check
def write_goldens() -> int:
    pages = json.loads(V2_PAGES.read_text(encoding="utf-8"))
    inp = world_input(pages)
    out = oracle(inp)
    meta = out.pop("meta")
    golden = {"provenance": {**meta, "clocks": list(CLOCKS)}, "input": inp, "expected": out}
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    if out.get("blocked"):
        print("BLOCKED WRITES in the oracle:", out["blocked"])
        return 1
    problems = compare_pure(golden)
    for i, st in enumerate(out["steps"]):
        print(
            json.dumps(
                {"step": i, "summary": {k: v for k, v in st["summary"].items() if isinstance(v, int)}},
                ensure_ascii=False,
            )
        )
    for p in problems[:60]:
        print("  DIFF", p)
    print("SCAN GOLDENS MATCH" if not problems else f"SCAN GOLDENS DIFFER ({len(problems)})")
    return 1 if problems else 0


def check() -> int:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    problems = compare_pure(golden)
    if golden["expected"].get("blocked"):
        problems.append(f"/blocked: the oracle wrote outside its folder: {golden['expected']['blocked']}")
    for p in problems[:60]:
        print("  DIFF", p)
    print("SCAN CHECK PASSED" if not problems else f"SCAN CHECK FAILED ({len(problems)})")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    mode = argv[1:]
    if mode == ["goldens"]:
        return write_goldens()
    if mode == ["check"]:
        return check()
    if mode == ["hosted"]:
        return hosted()
    if len(mode) == 3 and mode[0] == "real":
        return real(mode[1], mode[2])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

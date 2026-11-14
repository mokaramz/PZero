# ruff: noqa
# mypy: ignore-errors
# (protected WATCH sensor rules, copied by script from the old modules; see the header. The cut code is the old untyped
# code verbatim, so it is exempt from lint and type checks, like a vendored module.)
"""The WATCH sensors (review 037b), cut MECHANICALLY from the old ``services/watch.py`` (and the news bridge from
``services/news.py``) at revision 6c739b9 by exact top-level line ranges (``scripts/gen_watch_sensors.py``); nothing
is retyped. See the script's header for the cut list and the declared replacements (the two lazy imports of the
sensors, the bridge's own lazy import and its events).

Pure over what the run hands in: every outside reach goes through the ``Context`` the run installs for ONE unit of
work (one page, one company's re-hits, one news run's bridge), and nothing here touches the database or the network.
The run (``watch/run.py``) decides what is written: the collected trigger lines, the saved snapshot, the check record.
"""

# fmt: off
import hashlib
import json
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from projectzero.dealflow.scan import parsers as _parsers
from projectzero.dealflow.ranking.names import norm_company as _norm_company
from projectzero.dealflow.triage.view import edge as _edge
from projectzero.events import when as _when

log = logging.getLogger("projectzero.watch.sensors")
TRIGGERS = "watch/triggers.jsonl"


# ── hand-written seams (NOT cut): what the old module reached outside itself ───────────────────────────────────────
@dataclass
class Context:
    """One unit of work's world. ``page``: the fetched page text, or the exception the fetch raised."""

    ts: str  # the old ``ledger.now_ts()``
    today: date  # the old ``date.today()`` of ``extract_date``
    watched: dict = field(default_factory=dict)  # what ``watched()`` answers
    fired: set = field(default_factory=set)  # what ``_fired_keys()`` answers (mutated by ``_fire``, as before)
    proposals: dict = field(default_factory=dict)  # ``triage_proposals.json``'s ``proposals``
    news_events: dict = field(default_factory=dict)  # the bridge's ``load()["events"]``
    page: Any = None
    baselines: dict = field(default_factory=dict)  # snapshot name -> the lines the run resolved
    saved: dict = field(default_factory=dict)  # snapshot name -> the page's new lines
    lines: list = field(default_factory=list)  # the trigger lines ``_fire`` appended, in order
    case_refresh: list = field(default_factory=list)  # decision (f): the deferred ``on_watch_trigger`` calls


_CTX: ContextVar = ContextVar("watch_sensor_context")


@contextmanager
def context(ctx):
    token = _CTX.set(ctx)
    try:
        yield ctx
    finally:
        _CTX.reset(token)


def _ctx():
    return _CTX.get()


class _Storage:
    @staticmethod
    def append_line(name, line):
        assert name == TRIGGERS, name
        _ctx().lines.append(line)

    @staticmethod
    def load_json(name, default=None, tolerant=False):
        assert name == "triage_proposals.json", name
        return {"proposals": _ctx().proposals}


class _Ledger:
    @staticmethod
    def now_ts():
        return _ctx().ts


class _Connectors:
    _lines = staticmethod(_parsers._lines)
    _uid = staticmethod(_parsers._uid)
    norm_company = staticmethod(_norm_company)

    @staticmethod
    def _snap_path(name):
        return name  # the old ``<data>/.watch/<name>``: here the baseline's key, resolved by the run

    @staticmethod
    def _get(url):
        page = _ctx().page
        if isinstance(page, BaseException):
            raise page
        return page

    @staticmethod
    def _load_snapshot(name):
        got = _ctx().baselines.get(name)
        return list(got) if isinstance(got, list) else []

    @staticmethod
    def _save_snapshot(name, lines):
        _ctx().saved[name] = list(lines)


class _TriageReview:
    edge = staticmethod(_edge)


class _CaseRefresh:
    """Decision (f): the high-value case refresh is case preparation's (item 4): recorded, never run."""

    @staticmethod
    def on_watch_trigger(name, label):
        _ctx().case_refresh.append([name, label])


class _Events:
    @staticmethod
    def extract_date(text):
        return _when.extract_date(text, today=_ctx().today)


def watched():
    return _ctx().watched


def _fired_keys():
    return _ctx().fired


def _news_events():
    return _ctx().news_events


class _This:
    """The bridge's ``watch`` module: this one."""

    def __getattr__(self, name):
        return globals()[name]


storage, ledger, connectors, triage_review = _Storage(), _Ledger(), _Connectors(), _TriageReview()
_CASE_PREP, _EVMOD, _WATCH = _CaseRefresh(), _Events(), _This()

# ── cut from services/watch.py ──
MATERIAL_MIN_LINES = 6  # a page change with no predicate hit counts only if this many lines AND

MATERIAL_SHARE = 0.3  # this share of the page are new

PREDICATES: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "regulatory_approval",
        "Regulatory approval",
        re.compile(
            r"\b(fda|ce[- ]mark(ed|ing)?|510\(k\)|clearance|mdr approval|ema approval|regulatory approval|zulassung)\b",
            re.I,
        ),
    ),
    (
        "certification",
        "Certification",
        re.compile(r"\b(iso ?\d{4,5}|soc ?2|certified|certification|tüv|zertifiziert)\b", re.I),
    ),
    (
        "procurement",
        "Procurement / tender",
        re.compile(r"\b(tender|procurement|ausschreibung|framework agreement|awarded (a|the)? ?contract)\b", re.I),
    ),
    (
        "accelerator",
        "Accelerator admission",
        re.compile(r"\b(accelerator|incubator|y ?combinator|techstars|cohort|batch|selected for|admitted to)\b", re.I),
    ),
    ("demo_day", "Demo day / pitch", re.compile(r"\b(demo ?day|pitch (day|competition|night))\b", re.I)),
    (
        "new_grant",
        "New grant",
        re.compile(
            r"\b(grant|eic accelerator|eic pathfinder|horizon europe|exist|innosuisse|sbir|sttr|förderung|gefördert|awarded .{0,40}(funding|prize))\b",
            re.I,
        ),
    ),
    (
        "funding",
        "Funding",
        re.compile(
            r"\b(raise[sd]|raising|funding round|pre-?seed|seed round|series [a-d]|led by|finanzierungsrunde|investment from|backed by)\b",
            re.I,
        ),
    ),
    ("pilot", "Pilot", re.compile(r"\b(pilot|proof[- ]of[- ]concept|poc|field trial|trial with)\b", re.I)),
    (
        "customer",
        "Customer",
        re.compile(
            r"\b(customer|client|signed (a|an)?|contract with|order from|deployed (at|with)|kunde|auftrag)\b", re.I
        ),
    ),
    (
        "partnership",
        "Partnership",
        re.compile(r"\b(partner(s|ship|ing)? with|collaborat(e|ion|ing) with|cooperation|kooperation)\b", re.I),
    ),
    (
        "launch",
        "Launch",
        re.compile(r"\b(launch(es|ed)?|now available|general availability|public beta|released?)\b", re.I),
    ),
    (
        "founder_change",
        "Founder change",
        re.compile(r"\b(co-?founder .{0,30}(left|leaves|departs|steps? down)|new ceo|appointed ceo)\b", re.I),
    ),
    (
        "key_hire",
        "Key hire",
        re.compile(
            r"\b(joins (us )?as|appointed|welcome[s]? .{0,40}\b(cto|cfo|coo|cpo|vp|head of)|new (cto|cfo|coo))\b", re.I
        ),
    ),
    (
        "team_growth",
        "Team growth",
        re.compile(r"\b(we('re| are) hiring|join our team|open (positions|roles)|stellenangebot)\b", re.I),
    ),
    (
        "paper",
        "New paper",
        re.compile(
            r"\b(arxiv|preprint|published in|neurips|icml|iclr|cvpr|nature (communications|\w+)?|science advances)\b",
            re.I,
        ),
    ),
    ("patent", "New patent", re.compile(r"\b(patent(s|ed)?|patent application)\b", re.I)),
    (
        "technical_milestone",
        "Technical milestone",
        re.compile(r"\b(milestone|breakthrough|world record|first (flight|prototype|demo)|prototype)\b", re.I),
    ),
    (
        "incorporation",
        "Incorporation",
        re.compile(r"\b(incorporated|gmbh (was )?founded|gründung|registered as)\b", re.I),
    ),
]

LABEL = {k: lab for k, lab, _ in PREDICATES} | {
    "first_institutional_round": "First institutional round",
    "material_page_change": "Material page change",
    "source_rehit": "New independent source mention",
}

CLAIM_PREDICATE = {
    "funding": "funding_round",
    "first_institutional_round": "funding_round",
    "new_grant": "grant_award",
    "pilot": "traction",
    "customer": "traction",
    "procurement": "traction",
    "key_hire": "founder_identity",
    "founder_change": "founder_identity",
    "incorporation": "incorporation",
}

HIGH_VALUE = {
    "funding",
    "first_institutional_round",
    "new_grant",
    "pilot",
    "customer",
    "procurement",
    "regulatory_approval",
    "founder_change",
    "accelerator",
}

def _sha(*parts: Any) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:20]

def _norm(text: str) -> str:
    return re.sub(
        r"\s+", " ", re.sub(r"\d{1,2}:\d{2}|\b\d+ (min|minutes|hours?|days?) ago\b", "", text.lower())
    ).strip()

def classify(line: str) -> str | None:
    for key, _lab, rx in PREDICATES:
        if rx.search(line):
            return key
    return None

def _fire(
    key: str,
    w: dict[str, Any],
    predicate: str,
    *,
    source: str,
    source_kind: str,
    url: str,
    evidence: str,
    source_date: str,
    dedupe: str,
    fired: set[str],
) -> dict[str, Any] | None:
    if dedupe in fired:
        return None
    cand = w.get("candidate") or {}
    # funding seen for a company whose machine-estimated stage is pre-funding = possibly its FIRST institutional round
    if predicate == "funding":
        props = (storage.load_json("triage_proposals.json", {"proposals": {}}, tolerant=True) or {}).get(
            "proposals", {}
        )
        if (
            triage_review.edge((props.get(w.get("candidate_id") or "") or {}).get("capital_stage"))
            == "PRE_FUNDING_EDGE"
        ):
            predicate = "first_institutional_round"
    row = {
        "id": "wt-" + dedupe[:12],
        "kind": "trigger",
        "entity_key": key,
        "name": w["name"],
        "candidate_id": w.get("candidate_id") or cand.get("id") or "",
        "predicate": predicate,
        "label": LABEL.get(predicate, predicate),
        "high_value": predicate in HIGH_VALUE,
        "source": source,
        "source_kind": source_kind,
        "url": url,
        "source_date": source_date,
        "first_observed": ledger.now_ts(),
        "evidence": evidence[:500],
        "dedupe_key": dedupe,
    }
    storage.append_line(TRIGGERS, json.dumps(row, ensure_ascii=False, sort_keys=True))
    fired.add(dedupe)
    if row["high_value"]:  # a material change on a company with a Conviction case: refresh that case
        try:
            case_prep = _CASE_PREP

            case_prep.on_watch_trigger(w["name"], row["label"])
        except Exception:  # never blocks the watch check
            log.warning("case refresh after WATCH trigger failed", exc_info=True)
    return row

def scan_rehits() -> list[dict[str, Any]]:
    """Sensor 1 (no network): new provenance merged into a watched candidate by a later Deal Flow scan."""
    fired, out = _fired_keys(), []
    for key, w in watched().items():
        c = w.get("candidate") or {}
        for a in c.get("also_seen") or []:
            if not a.get("source_id") or (a.get("first_seen") or "") <= (c.get("first_seen") or ""):
                continue  # only provenance that appeared AFTER the company was first seen
            tier = a.get("discovery_tier") or ""
            pred = {"announcement": "funding", "grant": "new_grant"}.get(tier, "source_rehit")
            r = _fire(
                key,
                w,
                pred,
                source=a.get("source") or a["source_id"],
                source_kind="scan_rehit",
                url=a.get("url") or "",
                evidence=f"{a.get('source') or a['source_id']} ({tier or 'source'})",
                source_date=str(a.get("source_date") or "")[:10],
                dedupe=_sha(key, "rehit", a["source_id"], a.get("url") or ""),
                fired=fired,
            )
            if r:
                out.append(r)
    return out

def check_page(key: str, w: dict[str, Any], url: str, fired: set[str]) -> dict[str, Any]:
    """Sensor 2: one official page. First check = baseline only. Later checks: new lines → deterministic predicates."""
    evmod = _EVMOD

    snap = connectors._snap_path("wt-" + connectors._uid(key, url) + ".json")
    lines = connectors._lines(connectors._get(url))
    old = connectors._load_snapshot(snap)
    connectors._save_snapshot(snap, lines)
    if not old:
        return {"url": url, "state": "baseline", "fired": []}
    seen = {_norm(x) for x in old}
    new = [ln for ln in lines if _norm(ln) not in seen]
    fired_now, hit_any = [], False
    for ln in new:
        pred = classify(ln)
        if not pred:
            continue
        hit_any = True
        r = _fire(
            key,
            w,
            pred,
            source=url,
            source_kind="page_check",
            url=url,
            evidence=ln,
            source_date=evmod.extract_date(ln) or "",
            dedupe=_sha(key, url, pred, _norm(ln)),
            fired=fired,
        )
        if r:
            fired_now.append(r)
    if not hit_any and len(new) >= MATERIAL_MIN_LINES and len(new) >= MATERIAL_SHARE * max(1, len(lines)):
        r = _fire(
            key,
            w,
            "material_page_change",
            source=url,
            source_kind="page_check",
            url=url,
            evidence=" | ".join(new[:4]),
            source_date="",
            dedupe=_sha(key, url, "material", *sorted(_norm(x) for x in new)),
            fired=fired,
        )
        if r:
            fired_now.append(r)
    return {"url": url, "state": "changed" if new else "unchanged", "new_lines": len(new), "fired": fired_now}


# ── cut from services/news.py ──
def _watch_bridge() -> int:
    """A watched company in the news fires ONE WATCH trigger per article (the watch ledger dedupes by key)."""
    watch = _WATCH

    watched = watch.watched()
    fired_keys = watch._fired_keys()
    n = 0
    for e in _news_events().values():
        w = watched.get(e["entity_key"]) if e["entity_key"] else None
        if not w or e["materiality"] == "NOISE":
            continue
        for s in e["sources"][:1]:
            pred = {
                "funding": "funding",
                "customer": "customer",
                "acquisition": "source_rehit",
                "accelerator": "accelerator",
                "grant": "new_grant",
                "regulatory": "regulatory_approval",
                "launch": "launch",
                "partnership": "partnership",
                "hire": "key_hire",
            }.get(e["event_type"], "source_rehit")
            r = watch._fire(
                e["entity_key"],
                w,
                pred,
                source=s["publisher"],
                source_kind="news",
                url=s["url"],
                evidence=e["headline"],
                source_date=e["event_date"],
                dedupe=watch._sha(e["entity_key"], "news", s["url"]),
                fired=fired_keys,
            )
            n += 1 if r else 0
    return n

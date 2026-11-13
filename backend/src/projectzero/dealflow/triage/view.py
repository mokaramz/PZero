"""``GET /api/deal-flow/triage``: the old ``GET /api/triage`` payload (``services/triage_review.py::view``) from pz.

Every Deal Flow candidate that has a current machine proposal (status ``proposed`` / ``needs_human``), joined with
deterministic, computed-on-read context: operating-queue routing (``routing``), entity-name repair (``entity_repair``),
the Project A portfolio / conflict check (``portfolio_check``), staleness against today's card (``card``), the
operator's latest verdict, and the compressor's routing overlay. Nothing here writes. The assembly (``build``) is pure
and verbatim; only ``load`` reads the database.

Where each input comes from (``load``):

* candidates: ``candidates`` rows with a CURRENT proposal, as the legacy-shaped record the rules read
  (``ranking.service.ranking_input``: the imported inbox record with today's status and notes). ``id`` is the
  surviving candidate id; imported Deal Flow ids are the old ids.
* proposals: ``triage_proposals`` where ``is_current`` (one per survivor), rebuilt as the old record: ``detail`` plus
  the promoted columns. ``proposed_at`` is the column in Europe/Berlin formatted as the old writer did
  (``%Y-%m-%dT%H:%M:%S``, ``ledger.now_ts``); a proposal the import found without a usable ``proposed_at`` carries the
  import time instead (the old view showed the raw value).
* routing overlay: ``candidate_routing`` (``detail`` plus ``state`` / ``priority`` / ``reason``), keyed by survivor.
* the operator's verdicts (review 035a): the archived ``triage_decisions.jsonl`` (``legacy_documents.raw``) FIRST,
  then the ``triage_decisions`` rows ``order by seq`` (``triage.log.log_text``), read line by line as the old
  ``decisions()`` did. Each line keeps its ``candidate_id`` as recorded (an archived line names the old id); the latest
  verdict per candidate is chosen per SURVIVOR (``latest_verdicts`` maps each line's id through the ``candidate``
  aliases first, decision e), so an archived line for an absorbed id and a new line for its survivor count once, in
  the panel's verdict and in ``calibration``.
* acceptance (``shadow_triage/acceptance.json``) and the automatic-triage runs (``shadow_triage/auto_runs.json``):
  ``documents`` (un-modelled state, one row per old file). ``pending`` keys are mapped to survivors through the
  ``candidate`` merge aliases, and their proposal status is read from the survivor.
* Conviction records: ``conviction_entries`` (live), as the old signal: ``legacy`` overlaid with today's ``attrs``,
  ``company`` from the legacy record (else the company name); file order of the archived ``real_data.json`` first,
  then creation order (a later record of the same normalised name wins, as before).
* Scout Intake items: Scout Intake no longer exists (merged into Deal Flow) and merged items are absorbed into their
  survivors, so the frozen archived ``scout_intake.json`` (``legacy_documents.raw``, parsed like the old tolerant load:
  raw bytes keep the item order, which decides which item of a name wins) is the record set.
* workspace override: ``documents['workspace_geos.json']``, as the inbox read model.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from projectzero.core.db import schema_ident
from projectzero.dealflow import workspaces
from projectzero.dealflow.ranking.service import ranking_input
from projectzero.dealflow.triage import card, entity_repair, log, portfolio_check, routing

PRE_FUNDING = {"PRE_COMPANY", "INCORPORATED_NO_INSTITUTIONAL", "GRANT_ONLY", "BOOTSTRAPPED", "ANGEL_ONLY"}
NOTE = "Machine proposals only. Nothing becomes a decision until Mohamed accepts or overrides it."
OPEN_STATUSES = ("proposed", "needs_human")
QUEUE_KEYS = ("state", "reason", "priority", "priority_why", "underlying", "resurfaced", "at")
DECISION_LOG = "triage_decisions.jsonl"
SCOUT_INTAKE = "scout_intake.json"
ACCEPTANCE_DOC = "shadow_triage/acceptance.json"
AUTO_RUNS_DOC = "shadow_triage/auto_runs.json"
BERLIN = ZoneInfo("Europe/Berlin")  # the old app wrote naive local times
OLD_TS_FORMAT = "%Y-%m-%dT%H:%M:%S"


@dataclass
class TriageInputs:
    """Everything the old ``view()`` read, already loaded. ``aliases`` maps old candidate ids to their survivor."""

    candidates: list[dict[str, Any]]
    proposals: dict[str, dict[str, Any]]
    routes: dict[str, dict[str, Any]] = field(default_factory=dict)
    decision_log: str = ""
    conviction_signals: Any = None
    scout_items: Any = None
    acceptance: Any = None
    auto_runs: Any = None
    aliases: Mapping[str, str] = field(default_factory=dict)
    override: workspaces.Override = field(default_factory=lambda: workspaces.NO_OVERRIDE)


# ------------------------------------------------------------------ the pure assembly (verbatim)
def edge(stage: Any) -> str:
    if stage in PRE_FUNDING:
        return "PRE_FUNDING_EDGE"
    return {
        "ROUND_FORMING": "ROUND_FORMING",
        "FIRST_INSTITUTIONAL": "FIRST_INSTITUTIONAL",
        "ALREADY_INSTITUTIONALLY_FUNDED": "ALREADY_FUNDED",
    }.get(str(stage), "UNKNOWN")


def decisions(text: str) -> list[dict[str, Any]]:
    out = []
    for line in text.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def latest_verdicts(log: list[dict[str, Any]], aliases: Mapping[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """The last line per candidate (the old ``_latest_verdicts``), keyed by SURVIVOR: each line's recorded
    ``candidate_id`` is mapped through ``aliases`` (old id -> survivor) for the selection only (decision e)."""
    aliases = aliases or {}
    latest: dict[str, dict[str, Any]] = {}
    for e in log:
        if e.get("candidate_id"):
            cid = e["candidate_id"]
            latest[aliases.get(cid, cid) if isinstance(cid, str) else cid] = e
    return latest


def obvious_reject(p: Mapping[str, Any]) -> bool:
    return p.get("proposal") == "REJECT" and (p.get("stage") == "stage0" or "both reject" in str(p.get("path") or ""))


def summary(
    c: Mapping[str, Any],
    p: Mapping[str, Any],
    checker: portfolio_check.Checker,
    verdict: Mapping[str, Any] | None,
    override: workspaces.Override = workspaces.NO_OVERRIDE,
) -> dict[str, Any]:
    veto = p.get("veto") or {}
    pf = checker.check(c)
    rep = entity_repair.repair(c)
    rt = routing.route(c, override)
    stale = card.is_stale(c, p)
    machine = p.get("proposal")
    flagged = pf["status"] in ("KNOWN_PORTFOLIO", "PROJECT_A_RELATIONSHIP") or pf["route_to_omar"]
    return {
        "candidate_id": c["id"],
        "proposal": machine,
        "display_proposal": (
            "KNOWN_PORTFOLIO"
            if pf["status"] == "KNOWN_PORTFOLIO" and machine != "REJECT"
            else "ASK_OMAR_CONFLICT"
            if flagged and machine != "REJECT"
            else machine
        ),
        "status": p.get("status"),
        "stage": p.get("stage"),
        "path": p.get("path"),
        "confidence": p.get("confidence"),
        "reject_basis": p.get("reject_basis"),
        "reject_evidence": p.get("reject_evidence"),
        "reasons": p.get("reasons") or [],
        "missing": p.get("missing") or [],
        "flags": p.get("flags") or [],
        "flash": {
            "model": p.get("model"),
            "proposal": p.get("model_proposal") or machine,
            "confidence": p.get("confidence"),
            "reject_basis": p.get("reject_basis"),
        },
        "veto": (
            {
                "model": veto.get("model"),
                "mode": veto.get("mode"),
                "ok": veto.get("ok"),
                "proposal": veto.get("model_proposal"),
                "reject_basis": veto.get("reject_basis"),
                "reasons": veto.get("reasons") or [],
            }
            if veto
            else None
        ),
        "capital_stage": p.get("capital_stage"),
        "edge": edge(p.get("capital_stage")),
        "themes": p.get("themes") or [],
        "sector": p.get("sector"),
        "entity_type": p.get("entity_type"),
        "routing": rt,
        "entity": {"display_name": rep["display_name"], "broken": rep["broken"], "entities": rep["entities"]},
        "portfolio": pf,
        "stale": stale,
        "obvious_reject": obvious_reject(p) and not flagged and not stale,
        "prompt_version": p.get("prompt_version"),
        "proposed_at": p.get("proposed_at"),
        "mohamed": (
            {
                "verdict": verdict.get("verdict"),
                "mode": verdict.get("mode"),
                "at": verdict.get("ts"),
                "agreed": verdict.get("agreed"),
            }
            if verdict
            else None
        ),
    }


def calibration(latest: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    matrix: dict[str, Counter[str]] = defaultdict(Counter)
    for e in latest.values():
        matrix[str(e.get("machine"))][str(e.get("verdict"))] += 1
    n = len(latest)
    agreed = sum(1 for e in latest.values() if e.get("agreed"))
    machine_rejects = [e for e in latest.values() if e.get("machine") == "REJECT"]
    overturned = sum(1 for e in machine_rejects if e.get("verdict") in ("KEEP", "RESEARCH"))
    return {
        "decisions": n,
        "agreement": round(agreed / n, 3) if n else None,
        "machine_rejects_reviewed": len(machine_rejects),
        "machine_rejects_overturned_to_keep_or_research": overturned,
        "matrix_machine_to_mohamed": {k: dict(v) for k, v in matrix.items()},
    }


def pending_map(auto_runs: Any, props: Mapping[str, Any], aliases: Mapping[str, str] | None = None) -> dict[str, str]:
    """{candidate id: reason} for undecided candidates the last automatic runs could not triage (old
    ``auto_triage.pending_map``; any malformed run document means "nothing pending", as before). Old ids are mapped
    to their survivor."""
    aliases = aliases or {}
    try:
        d = auto_runs if auto_runs is not None else {}
        d.setdefault("runs", [])
        out: dict[str, str] = {}
        for r in d["runs"][-5:]:
            for p in r.get("pending", []) + r.get("failed", []):
                cid = aliases.get(p["id"], p["id"])
                if (props.get(cid) or {}).get("status") != "proposed":
                    out[cid] = ("TRIAGE FAILED: " if p in r.get("failed", []) else "TRIAGE PENDING: ") + p["reason"]
        return out
    except Exception:
        return {}


def build(inp: TriageInputs) -> dict[str, Any]:
    """The old ``view()``."""
    props = inp.proposals
    latest = latest_verdicts(decisions(inp.decision_log), inp.aliases)
    checker = portfolio_check.Checker(inp.conviction_signals, inp.scout_items)
    out: dict[str, Any] = {}
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    c_new: dict[Any, bool] = {}
    for c in inp.candidates:
        if not isinstance(c, dict) or c.get("id") in (None, ""):
            continue
        c_new[c.get("id")] = c.get("decision") == "new"
        p = props.get(c["id"])
        if not isinstance(p, dict) or p.get("status") not in OPEN_STATUSES:
            continue
        s = summary(c, p, checker, latest.get(c["id"]), inp.override)
        out[c["id"]] = s
        if c.get("decision") == "new":
            counts[s["routing"]["queue"]][s["display_proposal"]] += 1
            if s["obvious_reject"] and s["routing"]["queue"] == "operating":
                counts["operating"]["OBVIOUS_REJECT"] += 1
    for cid, s in out.items():  # routing overlay — attention order only, never a decision
        r = inp.routes.get(cid)
        s["queue"] = {k: r.get(k) for k in QUEUE_KEYS} if r and c_new.get(cid) else None
    acc = inp.acceptance if isinstance(inp.acceptance, dict) else {}
    return {
        "architecture": {
            "prompt_version": card.PROMPT_VERSION,
            "locked": card.LOCKED_V3,
            "accepted": acc.get("status"),
            "holdout": acc.get("holdout"),
        },
        "proposals": out,
        "counts": {k: dict(v) for k, v in counts.items()},
        "calibration": calibration(latest),
        "pending": pending_map(inp.auto_runs, props, inp.aliases),
        "note": NOTE,
    }


# ------------------------------------------------------------------ reading pz
_PROPOSAL_COLUMNS = ("candidate_id", "run_id", "prompt_version", "input_sha", "proposal", "status", "model",
                     "veto_model")  # fmt: skip
_CONVICTION = """
    select ce.slug, ce.attrs, ce.legacy, co.name as company_name, pos.ord
    from {s}.conviction_entries ce
    join {s}.companies co on co.id = ce.company_id
    left join lateral (
        select min(e.ord) as ord
        from {s}.legacy_documents d, jsonb_array_elements(d.parsed->'signals') with ordinality as e(value, ord)
        where d.path = 'real_data.json' and jsonb_typeof(d.parsed->'signals') = 'array' and e.value = ce.legacy
    ) pos on true
    order by pos.ord nulls last, ce.created_at, ce.id
"""


def _old_ts(value: Any) -> Any:
    return value.astimezone(BERLIN).strftime(OLD_TS_FORMAT) if hasattr(value, "astimezone") else value


def proposal_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """A ``triage_proposals`` row as the old proposal record."""
    p = dict(row.get("detail") or {})
    for k in _PROPOSAL_COLUMNS:
        p[k] = row.get(k)
    usd = row.get("usd")
    p["usd"] = float(usd) if usd is not None else None
    p["proposed_at"] = _old_ts(row.get("proposed_at"))
    return p


def route_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """A ``candidate_routing`` row as the old ``queue_routing.json`` route."""
    return {**(row.get("detail") or {}), "state": row.get("state"), "priority": row.get("priority"),
            "reason": row.get("reason")}  # fmt: skip


def conviction_signal(row: Mapping[str, Any]) -> dict[str, Any]:
    """A ``conviction_entries`` row as the old ``real_data.json`` signal (only what the check reads matters)."""
    raw = row.get("legacy")
    legacy: dict[str, Any] = raw if isinstance(raw, dict) else {}
    return {**legacy, **(row.get("attrs") or {}), "company": legacy.get("company") or row.get("company_name")}


def _text(raw: Any) -> str:
    try:
        return bytes(raw).decode("utf-8") if raw is not None else ""
    except UnicodeDecodeError:
        return ""


def _tolerant_json(raw: Any) -> Any:
    try:
        return json.loads(_text(raw)) if raw is not None else {}
    except ValueError:
        return {}


def load(conn: psycopg.Connection[Any], schema: str, only: list[str] | None = None) -> TriageInputs:
    """``only``: the candidate ids to read (the triage writes judge a few candidates with the same build); every other
    input is read whole, as the view reads it."""
    s = schema_ident(schema)
    with conn.cursor(row_factory=dict_row) as cur:
        # a survivor's own current proposal, else the newest proposal of a record merged into it (review 009: an
        # absorbed lead's machine KEEP must not vanish; it is judged against the survivor's card, so it reads stale)
        cur.execute(sql.SQL(
            "select distinct on (candidate_id) * from {}.triage_proposals "
            + ("where candidate_id = any(%s) " if only is not None else "")
            + "order by candidate_id, is_current desc, proposed_at desc, id desc"
        ).format(s), (list(only),) if only is not None else ())  # fmt: skip
        proposals = {str(r["candidate_id"]): proposal_record(r) for r in cur.fetchall()}
        cur.execute(sql.SQL("select * from {}.candidates where id = any(%s) order by id").format(s), (list(proposals),))
        candidates = []
        for row in cur.fetchall():
            c, _ = ranking_input(row)
            c["id"] = row["id"]
            candidates.append(c)
        # every route unless ``only`` (Today reads the whole table from these inputs)
        cur.execute(sql.SQL("select * from {}.candidate_routing"
                            + (" where candidate_id = any(%s)" if only is not None else "")).format(s),
                    (list(proposals),) if only is not None else ())  # fmt: skip
        routes = {str(r["candidate_id"]): route_record(r) for r in cur.fetchall()}
        cur.execute(sql.SQL(_CONVICTION).format(s=s))
        signals = [conviction_signal(r) for r in cur.fetchall()]
        cur.execute(sql.SQL("select path, raw from {}.legacy_documents where path = any(%s)").format(s),
                    ([DECISION_LOG, SCOUT_INTAKE],))  # fmt: skip
        archived = {r["path"]: r["raw"] for r in cur.fetchall()}
        cur.execute(sql.SQL("select key, body from {}.documents where key = any(%s)").format(s),
                    ([ACCEPTANCE_DOC, AUTO_RUNS_DOC, "workspace_geos.json"],))  # fmt: skip
        docs = {r["key"]: r["body"] for r in cur.fetchall()}
        cur.execute(sql.SQL("select alias_id, candidate_id from {}.candidate_aliases where namespace = 'candidate'")
                    .format(s))  # fmt: skip
        aliases = {str(r["alias_id"]): str(r["candidate_id"]) for r in cur.fetchall()}
    intake = _tolerant_json(archived.get(SCOUT_INTAKE))
    return TriageInputs(
        candidates=candidates,
        proposals=proposals,
        routes=routes,
        decision_log=log.log_text(conn, schema, _text(archived.get(DECISION_LOG))),
        conviction_signals=signals,
        scout_items=(intake.get("items", {}) or {}) if isinstance(intake, dict) else {},
        acceptance=docs.get(ACCEPTANCE_DOC) or {},
        auto_runs=docs.get(AUTO_RUNS_DOC) or {},
        aliases=aliases,
        override=workspaces.parse_override(docs.get("workspace_geos.json") or {}),
    )


def triage_view(conn: psycopg.Connection[Any], schema: str) -> dict[str, Any]:
    return build(load(conn, schema))

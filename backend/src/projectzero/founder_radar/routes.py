# ruff: noqa: E501
"""The old ``api/routers/founder_radar.py`` (rev 6c739b9) as pure functions (review 026a): ``view`` for
``GET /api/founder_radar`` and one function per network-free write endpoint (``radar_action``, ``radar_import``,
``radar_company``, ``radar_promote``, ``boardy_brief``, ``radar_pair``, ``radar_review``) plus ``proposals``
(``radar_proposals``, a read sent as a POST). ``radar_scan`` / ``radar_research`` / ``radar_research_queue`` are
review 026b.

Inputs (``Inputs``): the LIVE people in their stored order (a merged person — a tombstone — is absent, revisions
2/3), the stored ``radar_companies.json`` / ``radar_research.json`` / ``radar_health.json`` /
``radar_regions.json`` / ``radar_metrics.json`` bodies as read (None: missing), the pipeline signals and the
reserved ids (every tombstone id, for the import's id allocation). The documents' dict key ORDER is significant (the
research ``proposals`` / ``pages`` / ``pairings`` and the ``companies`` maps): hand them in their stored order.

Each function answers what the old route answered (status + body). Expected refusals are the old HTTP 200
``{ok: false, error}``. Changes, each a decision of the plan:
* (a) ``view`` and ``proposals`` never write: the person migrations (``migrate_all``), the founder references, the
  default regions and the metrics ``latest`` are computed in memory.
* (b) import ids: ``ingestion.allocate_id`` (sha1 suffix, collision check against live AND reserved ids).
* (c) ``merge``: ``Outcome.merged = (survivor, tombstone)``; the new ``people`` list no longer holds the tombstone,
  which the store keeps with ``merged_into`` (its last record is the stored one, unchanged).
* (e) only real changes write: an outcome whose documents equal the input returns no document (and an action or
  import that changes nothing records no metrics either).
* (f) an unknown ``state`` is a 400 ``{ok: false, error: "state must be one of: ..."}`` (the old route raised: 500).
* review 036a: a ``confirm`` that is supplied but is not a JSON boolean is a 400 ``{ok: false, error}`` that writes
  nothing, on the actions that read it (``CONFIRMING_ACTIONS``) and on ``radar_company``'s nested ``fact.confirm``;
  ``radar_review``'s ``confirm`` is the list of proposal ids to confirm, unchanged.
* (g) one clock: ``now`` (Berlin wall clock) and ``today`` (its day) are parameters.
* ``radar_pair`` uses the founder references derived on read (the old route read only the stored ones, which the old
  GET always persisted first) and stores them with the pairing; a pairing or binding to a person who is not live is
  the old refusal for a record that is not a founder reference.
Kept for parity (decision d): ``radar_action`` ends by replacing ``identity_evidence`` with the recomputed resolution
and stores ``signal`` assessed without company context; the metrics count the stored signals; ``radar_company``
appends a repeated fact and creates a record for an unknown key. Never changed: the inputs (every function works on
copies). Not here: the 400 for a body that is not a JSON object (the API layer's ``json_body``).
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from projectzero.core.body import BadConfirm, confirmed
from projectzero.ecosystems.coverage import radar_health
from projectzero.founder_radar import companies as companies_mod
from projectzero.founder_radar import review as review_mod
from projectzero.founder_radar.boardy import boardy_brief as _boardy_brief
from projectzero.founder_radar.catalog import BUCKETS, DECISION_FIELDS, NETWORK_STATES, STATES
from projectzero.founder_radar.clock import Clock
from projectzero.founder_radar.csv_import import parse_import_csv
from projectzero.founder_radar.evidence import add_evidence, dedupe_evidence
from projectzero.founder_radar.extraction import group_proposals, recommended_ids, research_summary, with_evidence_kind
from projectzero.founder_radar.identity import can_merge, identity_resolution, promotion_guard, proposed_identity
from projectzero.founder_radar.ingestion import _merge_into, ingest
from projectzero.founder_radar.leads import founder_leads
from projectzero.founder_radar.metrics import append_history, metrics_snapshot
from projectzero.founder_radar.names import _canon_domain
from projectzero.founder_radar.records import migrate_all, migrate_person, promote_to_network, set_state
from projectzero.founder_radar.scoring import assess
from projectzero.founder_radar.sources import geo_options, load_regions, source_coverage
from projectzero.network.view import listing
from projectzero.network.view import records as _records

CONFIRMING_ACTIONS = ("linkedin", "confirm_identity", "verify_identity", "merge")  # the actions that read ``confirm``
UNKNOWN_PERSON = "unknown person"
UNKNOWN_ACTION = "unknown action"
STATE_REFUSAL = "state must be one of: "  # decision f (review 026a), the one new text


@dataclass(frozen=True)
class Inputs:
    """What the routes read. ``people``: the live people records in stored order (no tombstone). The documents: the
    stored bodies (None: missing). ``signals``: the pipeline signals (``real_data.json`` ``signals``).
    ``reserved_ids``: the ids no new person may take (the merge tombstones)."""

    people: list[dict[str, Any]] = field(default_factory=list)
    companies: Any = None
    research: Any = None
    health: Any = None
    regions: Any = None
    metrics: Any = None
    signals: Any = field(default_factory=list)
    reserved_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Outcome:
    """One request's answer and writes. A document field is None when that document is not written (unchanged,
    refused, or not touched by the endpoint); otherwise it is the whole new document, with the ``*_changed`` list
    naming the new or changed entries in the new document's order.

    * ``people``: the new list of LIVE people (a merge leaves the tombstone out); ``people_changed`` the ids of the
      new or changed records (the survivor of a merge included).
    * ``merged``: ``(survivor_id, tombstone_id)`` for a merge: the store sets ``merged_into`` on the tombstone and
      moves its identifiers, in the same transaction.
    * ``companies`` / ``companies_changed``: the ``radar_companies.json`` body and its changed keys.
    * ``research`` / ``research_changed``: the ``radar_research.json`` body and its changed domain keys.
    * ``metrics``: the new ``radar_metrics.json`` body (``radar_action`` and ``radar_import``, as before).
    """

    status: int
    body: dict[str, Any]
    people: list[dict[str, Any]] | None = None
    people_changed: list[Any] = field(default_factory=list)
    merged: tuple[str, str] | None = None
    companies: Any = None
    companies_changed: list[str] = field(default_factory=list)
    research: Any = None
    research_changed: list[str] = field(default_factory=list)
    metrics: Any = None

    @property
    def wrote(self) -> bool:
        return any(x is not None for x in (self.people, self.companies, self.research, self.metrics))


def _key(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


def _js(v: Any) -> Any:
    """A JSON round trip (what the old route's answer was on the wire)."""
    return json.loads(json.dumps(v, ensure_ascii=False, default=str))


def _index(people: list[dict[str, Any]], pid: Any) -> int | None:
    """The old ``people.get(d, pid)``: the first record whose id equals ``pid``."""
    return next((i for i, p in enumerate(people) if isinstance(p, dict) and p.get("id") not in (None, "") and p.get("id") == pid), None)  # fmt: skip


def _changed_keys(before: Any, after: Any, name: str) -> list[str]:
    b = before.get(name) if isinstance(before, dict) else None
    a = after.get(name) if isinstance(after, dict) else None
    if not isinstance(a, dict):
        return []
    b = b if isinstance(b, dict) else {}
    return [k for k, v in a.items() if k not in b or _key(b[k]) != _key(v)]


def _doc_write(before: Any, after: Any, name: str) -> tuple[Any, list[str]]:
    """``after`` when it differs from ``before`` (content or key order), else (None, [])."""
    if after is None or _key(before) == _key(after):
        return None, []
    return after, _changed_keys(before, after, name)


def _people_changed(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[Any]:
    was = {_key(p.get("id")): _key(p) for p in _records(before)}
    return [p.get("id") for p in _records(after) if was.get(_key(p.get("id"))) != _key(p)]


def _queue(inputs: Inputs, rows: list[dict[str, Any]], ck: Clock) -> tuple[list[dict[str, Any]], Any]:
    return companies_mod.companies_queue(
        rows, companies_doc=inputs.companies, research_doc=inputs.research, signals=inputs.signals,
        now=ck.now, today=ck.today,
    )  # fmt: skip


# ------------------------------------------------------------------ reads
def view(inputs: Inputs, *, today: date, now: datetime) -> dict[str, Any]:
    """``GET /api/founder_radar``: the whole Founder Radar view (decision a: computed, never written)."""
    ck = Clock.at(now, today)
    migrated = migrate_all(inputs.people, ck).people
    rows = listing(migrated, ck.today)
    h = radar_health(inputs.health)
    for r in rows:
        r["evidence"] = dedupe_evidence(r.get("evidence") or [])
    comps, _refs = _queue(inputs, rows, ck)
    for r in rows:
        r["_companies"] = comps
        r["signal"] = assess(r, today=ck.today)
        r["proposed_identity"] = proposed_identity(r)
        r["promotion_block"] = promotion_guard(r)
        r.pop("_companies", None)
    for c in comps:
        for f in c["founders"]:
            f["bucket"] = next((x["signal"]["bucket"] for x in rows if x["id"] == f["id"]), f.get("bucket", ""))
    claim_ids = {r["id"] for r in rows if r["signal"]["bucket"] == BUCKETS[2] and r.get("radar_state") != "dismissed"}
    ref_ids = {f["id"] for c in comps for f in c["founders"]}
    qc = {
        "company_leads": len(comps),
        "claimed_founder_refs": sum(len(c["founders"]) for c in comps),
        "claim_bucket_people": len(claim_ids),
        "claim_people_without_lead": len(claim_ids - ref_ids),
        "reconciled": claim_ids <= ref_ids,
    }
    leads = founder_leads(rows, comps, inputs.research, ck.today)
    answer: dict[str, Any] = _js(
        {
            "people": rows,
            "companies": comps,
            "leads": leads,
            "queue_counts": qc,
            "health": h,
            "coverage": source_coverage(h),
            "geo": geo_options(rows, h, inputs.regions),
            "metrics": metrics_snapshot(migrated, ck.today),
            "states": STATES,
            "network_states": NETWORK_STATES,
            "buckets": BUCKETS,
            "regions": [r["region"] for r in load_regions(inputs.regions)],
        }
    )
    return answer


def proposals(inputs: Inputs, body: dict[str, Any], *, today: date, now: datetime) -> Outcome:
    """``POST radar_proposals {key}``: a read (decision a: the founder references are derived, never written)."""
    ck = Clock.at(now, today)
    research = review_mod.loaded_research(inputs.research)
    dom = research["domains"].get(body.get("key", ""), {})
    props = with_evidence_kind(list((dom.get("proposals") or {}).values()))
    comps, _refs = _queue(inputs, listing(inputs.people, ck.today), ck)
    comp = next((c for c in comps if c["key"] == body.get("key")), {})
    groups = group_proposals(props)
    answer = {
        "ok": True,
        "proposals": props,
        "groups": groups,
        "recommended": recommended_ids(groups),
        "summary": research_summary(dom, groups, comp),
        "company": {
            k: comp.get(k) for k in ("name", "domain", "next_missing", "priority_label", "priority_why", "next_action")
        },
        "pages": dom.get("pages", {}),
        "done": dom.get("done", False),
        "history": dom.get("history", []),
        "refreshed_at": dom.get("refreshed_at", ""),
        "pairings": dom.get("pairings", {}),
    }
    return Outcome(200, _js(answer))


# ------------------------------------------------------------------ writes
def _with_metrics(inputs: Inputs, people: list[dict[str, Any]], ck: Clock) -> Any:
    """The new ``radar_metrics.json`` body, or None when it equals the stored one (decision e)."""
    doc = append_history(inputs.metrics, metrics_snapshot(people, ck.today))
    return None if _key(doc) == _key(inputs.metrics) else doc


def action(inputs: Inputs, body: dict[str, Any], *, today: date, now: datetime) -> Outcome:
    """``POST radar_action {id, action, ...}``. A merged id is absent (``inputs.people`` holds only live people), so it
    answers the old ``unknown person``."""
    ck = Clock.at(now, today)
    act = body.get("action")
    pid = body.get("id")
    people = inputs.people
    confirm = False
    if act in CONFIRMING_ACTIONS:  # review 036a: only JSON true confirms; a malformed value is a 400, nothing written,
        try:  # checked BEFORE the person lookup (H-371), so an unknown person never hides a malformed confirmation
            confirm = confirmed(body)
        except BadConfirm as exc:
            return Outcome(400, {"ok": False, "error": str(exc)})
    i = _index(people, pid)
    if i is None:
        return Outcome(200, {"ok": False, "error": UNKNOWN_PERSON})
    if act == "state" and body.get("state") not in STATES:  # decision f: the old set_state raised (a 500)
        return Outcome(400, {"ok": False, "error": STATE_REFUSAL + ", ".join(STATES)})
    d = {"people": list(people)}
    pr = copy.deepcopy(people[i])
    d["people"][i] = pr
    migrate_person(pr)
    merged: tuple[str, str] | None = None
    companies_write: Any = None
    if act == "watch":
        set_state(pr, "watchlisted", body.get("note", ""), ck=ck)
    elif act == "research":
        set_state(pr, "researching", body.get("note", ""), ck=ck)
    elif act == "dismiss":
        set_state(pr, "dismissed", body.get("note", ""), ck=ck)
        pr["dismissed_reason"] = body.get("note", "")
        pr["watch"] = False
    elif act == "intro_path":
        pr["intro_route"] = body.get("route", "")
        set_state(pr, "introduction path identified", body.get("route", ""), ck=ck)
    elif act == "link_company":
        c = body.get("company", "").strip()
        if c and c not in pr.setdefault("companies", []):
            pr["companies"].append(c)
    elif act == "link_event":
        ev = body.get("event", "").strip()
        if ev and ev not in pr.setdefault("events", []):
            pr["events"].append(ev)
    elif act in ("opportunity", "boardy") and promotion_guard(pr):
        return Outcome(200, {"ok": False, "error": promotion_guard(pr)})
    elif act == "opportunity":
        pr.setdefault("opportunities", []).append(
            {
                "kind": "pre_company",
                "name": body.get("name", "") or (pr.get("name", "") + " — new company"),
                "created": ck.now.strftime("%Y-%m-%d"),
                "status": "needs review",
                "note": "reviewable signal — not an investment recommendation",
            }
        )
        set_state(pr, "opportunity introduced", "pre-company opportunity created (needs review)", ck=ck)
    elif act == "boardy":
        st = body.get("status", "introduction requested")
        pr.setdefault("boardy", {"status": "", "history": []})
        pr["boardy"]["status"] = st
        pr["boardy"]["history"].append({"status": st, "on": ck.minute(), "by": "operator"})
        if st == "introduction requested":
            set_state(pr, "introduction requested", "via Boardy (operator)", ck=ck)
    elif act == "state":
        set_state(pr, body.get("state"), body.get("note", ""), ck=ck)
    elif act == "linkedin":
        url = (body.get("url") or "").strip()
        if url and not url.startswith("http"):
            url = "https://" + url
        pr["linkedin"] = url
        pr.setdefault("profile_urls", [])
        if url and url not in pr["profile_urls"]:
            pr["profile_urls"].append(url)
        pr.setdefault("sources", []).append(
            {
                "source": "LinkedIn (manual / authorized)",
                "source_id": "linkedin",
                "url": url,
                "retrieved": ck.minute(),
                "route": "manual",
                "by": "operator",
            }
        )
        if body.get("verified"):
            if not (body.get("fact") and confirm and url):
                return Outcome(
                    200,
                    {
                        "ok": False,
                        "error": "manual verification needs the profile URL, the verified fact and explicit confirmation",
                    },
                )
            pr["identity_verified_by"] = "operator"
            pr["identity_verified_on"] = ck.minute()
            pr.setdefault("identity_evidence", []).append(
                "operator verified manually on LinkedIn: " + (body.get("note") or "profile checked by Mohamed")
            )
            if body.get("founder"):
                pr["founder_status"] = "explicit founder — verified by operator (LinkedIn, manual)"
                pr.setdefault("evidence", []).append(
                    {
                        "category": "entrepreneurial",
                        "claim": "founder / co-founder status confirmed by operator on LinkedIn (manual check)",
                        "source": "LinkedIn (manual / authorized)",
                        "source_url": url,
                        "retrieved": ck.minute(),
                    }
                )
    elif act == "evidence":
        r = add_evidence(
            body.get("kind") or "operator",
            body.get("url"),
            body.get("label"),
            body.get("claim"),
            body.get("field", ""),
            body.get("activity_date"),
            now=ck.now,
            today=ck.today,
        )
        if not r["ok"]:
            return Outcome(200, _js(r))
        pr.setdefault("evidence", []).append(r["row"])
        pr["evidence"] = dedupe_evidence(pr["evidence"])
        pr["last_signal"] = ck.now.strftime("%Y-%m-%d")
    elif act == "confirm_identity":
        url_ = (body.get("url") or "").strip()
        handle_ = (body.get("handle") or "").strip()
        od = ""
        comps, refs = _queue(inputs, listing(people, ck.today), ck)  # the stored people, as the old route listed them
        for comp in comps:  # the person's company lead whose official domain hosts the page
            if (
                any(f["id"] == pid for f in comp.get("founders", []))
                and comp.get("domain") not in ("", "UNKNOWN", None)
                and _canon_domain(url_) == _canon_domain(comp["domain"])
            ):
                od = comp["domain"]
                break
        if not handle_ and od:
            handle_ = url_  # the exact official page URL is the stable public identifier on this route
        r = review_mod.confirm_identity(
            pr,
            body.get("name"),
            handle_,
            body.get("company"),
            url_,
            body.get("label"),
            body.get("fact"),
            confirm,
            official_domain=od,
            research=review_mod.loaded_research(inputs.research),
            ck=ck,
        )
        if not r["ok"]:
            return Outcome(200, _js(r))
        if refs.changed:
            companies_write = refs.doc  # the founder references the old route saved
    elif act == "investigate_founder":
        set_state(
            pr,
            "researching",
            "investigate founder status: " + (body.get("note") or "research-only profile"),
            "operator",
            ck=ck,
        )
    elif act == "verify_identity":
        ev2 = add_evidence("identity", body.get("url"), body.get("label"), body.get("fact"), now=ck.now, today=ck.today)
        if not ev2["ok"] or not confirm:
            return Outcome(
                200,
                {
                    "ok": False,
                    "error": ev2.get("error")
                    or "explicit confirmation required (source URL, source label, verified fact)",
                },
            )
        pr["identity_verified_by"] = "operator"
        pr["identity_verified_on"] = ck.minute()
        pr.setdefault("identity_evidence", []).append(
            f"operator verified with public evidence ({body.get('label')}): {body.get('fact')}"
        )
        pr.setdefault("evidence", []).append(ev2["row"])
    elif act == "merge":
        j = _index(people, body.get("other"))
        other = people[j] if j is not None else None
        ok, why = can_merge(pr, other or {})
        if not (other and ok and confirm):
            return Outcome(
                200,
                {
                    "ok": False,
                    "error": "merge refused: " + (why if other else "unknown person"),
                    "needs_confirmation": bool(other and ok),
                },
            )
        if other["id"] == pr["id"]:  # the old code deleted the person itself; a self-merge is refused (no change)
            return Outcome(200, {"ok": False, "error": "merge refused: " + why, "needs_confirmation": False})
        _merge_into(pr, copy.deepcopy(other), "operator confirmed: " + why, ck=ck)
        d["people"] = [x for x in d["people"] if x["id"] != other["id"]]
        merged = (str(pr["id"]), str(other["id"]))
    else:
        return Outcome(200, {"ok": False, "error": UNKNOWN_ACTION})
    pr["signal"] = assess(pr, today=ck.today)  # decision d: without company context, as before
    pr["identity_status"], pr["identity_evidence"] = identity_resolution(pr)  # decision d: REPLACES, as before
    answer = _js({"ok": True, "person": pr})
    changed = _people_changed(people, d["people"])
    if not changed and merged is None and companies_write is None:
        return Outcome(200, answer)  # decision e: nothing changed, nothing written
    new_people = d["people"] if (changed or merged) else None
    companies, companies_changed = _doc_write(inputs.companies, companies_write, "companies")
    return Outcome(
        200,
        answer,
        people=new_people,
        people_changed=changed,
        merged=merged,
        companies=companies,
        companies_changed=companies_changed,
        metrics=_with_metrics(inputs, d["people"], ck) if new_people is not None else None,
    )


def import_csv(inputs: Inputs, body: dict[str, Any], *, today: date, now: datetime) -> Outcome:
    """``POST radar_import {csv, include_email, label}`` (always ``ok``)."""
    ck = Clock.at(now, today)
    text = body.get("csv") or ""
    cands, skipped, fmt = parse_import_csv(
        text,
        include_email=bool(body.get("include_email")),
        label=body.get("label") or ("LinkedIn Connections export" if "First Name" in text else "CSV"),
        now=ck.now,
    )
    res = ingest(inputs.people, cands, ck=ck, reserved_ids=inputs.reserved_ids)
    provenance = "official LinkedIn Connections export" if fmt == "linkedin_connections" else "custom CSV"
    answer = {
        "ok": True,
        "format": fmt,
        "rows": len(cands) + len(skipped),
        "skipped": skipped[:10],
        **res.result,
        "note": f"imported as identity-unresolved records with import provenance ({provenance}) — nothing was scanned from LinkedIn, nothing was verified or promoted",
    }
    if not res.changed:
        return Outcome(200, _js(answer))
    return Outcome(
        200, _js(answer), people=res.people, people_changed=res.changed, metrics=_with_metrics(inputs, res.people, ck)
    )


def company(inputs: Inputs, body: dict[str, Any], *, today: date, now: datetime) -> Outcome:
    """``POST radar_company {key, fact, evidence, description, notes}``."""
    ck = Clock.at(now, today)
    f_in = body.get("fact")
    try:  # review 036a (H-371): the NESTED ``fact.confirm`` is checked FIRST, so no earlier refusal hides a malformed one
        fact_confirm = confirmed(f_in) if isinstance(f_in, dict) else False
    except BadConfirm as exc:
        return Outcome(400, {"ok": False, "error": str(exc)})
    key = body.get("key", "")
    if not key:
        return Outcome(200, {"ok": False, "error": "company key required"})
    # decision-bearing fields are accepted ONLY as sourced facts bound to that exact field; rejection never writes
    if any(body.get(k) not in (None, "") for k in DECISION_FIELDS):
        return Outcome(
            200,
            {
                "ok": False,
                "error": "decision-bearing company facts must be submitted as a sourced fact (field, value, exact claim, public URL, source label, confirmation)",
            },
        )
    new_fact = None
    new_ev = None
    if body.get("fact"):
        f = body["fact"]  # its ``confirm`` was checked above (a non-object fact: unchanged)
        r = companies_mod.sourced_fact(
            f.get("field"),
            f.get("value"),
            f.get("claim"),
            f.get("url"),
            f.get("label"),
            fact_confirm,
            f.get("activity_date"),
            now=ck.now,
            today=ck.today,
        )
        if not r["ok"]:
            return Outcome(200, _js(r))
        new_fact = r["fact"]
    if body.get("evidence"):
        e = body["evidence"]
        r = add_evidence(
            "company", e.get("url"), e.get("label"), e.get("claim"), e.get("field", ""), now=ck.now, today=ck.today
        )
        if not r["ok"]:
            return Outcome(200, _js(r))
        new_ev = r["row"]
    cd = companies_mod.loaded_companies(inputs.companies)
    c = cd["companies"].setdefault(key, {})
    if new_fact:
        c.setdefault("facts", []).append(new_fact)
        c.setdefault("evidence", []).append(
            {
                "category": "company",
                "claim": new_fact["claim"],
                "source": "Operator-supplied public evidence — " + new_fact["source_label"],
                "source_url": new_fact["source_url"],
                "field": new_fact["field"],
                "retrieved": new_fact["recorded"],
                "by": "operator",
            }
        )
    if new_ev:
        c.setdefault("evidence", []).append(new_ev)
    for k in ("description", "notes"):
        if body.get(k) is not None and body.get(k) != "":
            c[k] = copy.deepcopy(body[k])  # human judgment / description: never decision-bearing
    companies, changed = _doc_write(inputs.companies, cd, "companies")
    return Outcome(200, {"ok": True}, companies=companies, companies_changed=changed)


def promote(inputs: Inputs, body: dict[str, Any], *, today: date, now: datetime) -> Outcome:
    """``POST radar_promote {id, how, introduced_by, stage, ...}``: an unknown (or merged) id and an unresolved
    identity both answer ``{ok: false, person: null, error: "Resolve identity before promotion"}``."""
    ck = Clock.at(now, today)
    people, pr = promote_to_network(
        inputs.people,
        body.get("id"),
        body.get("how", ""),
        body.get("introduced_by", ""),
        body.get("stage", "contacted"),
        body.get("last_interaction", ""),
        body.get("next_action", ""),
        body.get("next_action_date", ""),
        body.get("channel", ""),
        body.get("notes", ""),
        ck=ck,
    )
    answer = _js({"ok": pr is not None, "person": pr, "error": None if pr is not None else "Resolve identity before promotion"})  # fmt: skip
    changed = _people_changed(inputs.people, people) if pr is not None else []
    return Outcome(200, answer, people=people if changed else None, people_changed=changed)


def boardy_brief(inputs: Inputs, body: dict[str, Any], *, today: date, now: datetime) -> Outcome:
    """``POST boardy_brief {id, desired, exclusions}`` (no API call ever happens)."""
    ck = Clock.at(now, today)
    i = _index(inputs.people, body.get("id"))
    if i is None:
        return Outcome(200, {"ok": False})
    pr = copy.deepcopy(inputs.people[i])
    migrate_person(pr)
    text = _boardy_brief(
        pr,
        body.get("desired") or "a 20-minute intro call",
        body.get("exclusions") or "no fundraising pitch, no data sharing beyond public evidence",
        now=ck.now,
        today=ck.today,
    )
    pr.setdefault("boardy", {"status": "", "history": []})
    pr["boardy"]["status"] = pr["boardy"].get("status") or "brief prepared"
    pr["boardy"]["history"].append({"status": "brief prepared", "on": ck.minute(), "by": "operator"})
    pr["boardy"]["brief"] = text
    people = list(inputs.people)
    people[i] = pr
    answer = {"ok": True, "brief": text, "sent": False, "note": "No Boardy API — paste this into Boardy yourself."}
    return Outcome(200, answer, people=people, people_changed=_people_changed(inputs.people, people))


def pair(inputs: Inputs, body: dict[str, Any], *, today: date, now: datetime) -> Outcome:
    """``POST radar_pair {key, proposal, person}``."""
    ck = Clock.at(now, today)
    _comps, refs = _queue(inputs, listing(inputs.people, ck.today), ck)
    live = {p.get("id") for p in _records(inputs.people)}
    r = review_mod.confirm_pairing(
        inputs.research, refs.doc, body.get("key", ""), body.get("proposal", ""), body.get("person", ""), live, ck=ck
    )
    if not r.body.get("ok"):
        return Outcome(200, _js(r.body))
    research, research_changed = _doc_write(inputs.research, r.research, "domains")
    companies, companies_changed = _doc_write(inputs.companies, refs.doc if refs.changed else None, "companies")
    return Outcome(
        200,
        _js(r.body),
        research=research,
        research_changed=research_changed,
        companies=companies,
        companies_changed=companies_changed,
    )


def review(inputs: Inputs, body: dict[str, Any], *, today: date, now: datetime) -> Outcome:
    """``POST radar_review {key, confirm[], reject[], bindings{proposal_id: person_id}}``. An all-conflict review
    whose documents do not change writes nothing (decision e; the old route saved anyway)."""
    ck = Clock.at(now, today)
    comps, refs = _queue(inputs, listing(inputs.people, ck.today), ck)
    comp = next((c for c in comps if c["key"] == body.get("key")), {})
    bindings = {str(k): str(v) for k, v in (body.get("bindings") or {}).items() if v}
    r = review_mod.review_proposals(
        inputs.research,
        refs.doc,
        body.get("key", ""),
        body.get("confirm") or [],
        body.get("reject") or [],
        bindings=bindings,
        people=inputs.people,
        allowed_person_ids={f["id"] for f in comp.get("founders", [])},
        official_domain=comp.get("domain", "") if comp.get("domain") not in ("", "UNKNOWN") else "",
        ck=ck,
    )
    if not r.body.get("ok"):
        return Outcome(200, _js(r.body))
    research, research_changed = _doc_write(inputs.research, r.research, "domains")
    companies, companies_changed = _doc_write(inputs.companies, r.companies, "companies")
    people = r.people if (r.people is not None and r.people_changed) else None
    return Outcome(
        200,
        _js(r.body),
        people=people,
        people_changed=r.people_changed if people is not None else [],
        companies=companies,
        companies_changed=companies_changed,
        research=research,
        research_changed=research_changed,
    )

# ruff: noqa: E501
"""The old ``domain/founder_radar/review.py`` (rev 6c739b9), ported line for line (review 026a): identity confirmation,
the explicit founder pairing and the one auditable proposal review.

Changes:
* The documents are parameters and the results are new documents (the old functions loaded and saved
  ``radar_research.json`` / ``radar_companies.json``): ``confirm_pairing`` and ``review_proposals`` return a
  ``Review``; the inputs are never changed (they work on deep copies).
* ``confirm_identity`` still changes the record it is given (callers hand it a copy); its hardened-page check reads
  the research document it is GIVEN.
* Revisions 2/3 (a merged id is absent): ``confirm_pairing`` takes the ids of the LIVE people; a founder reference
  whose person is not live (a merge tombstone keeps its stored reference) answers the old refusal for a record that
  is not a founder reference. ``review_proposals`` already refuses a binding outside the live company lead.
* The clock (``ck``, decision g).
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any

from projectzero.founder_radar.catalog import DECISION_FIELDS
from projectzero.founder_radar.clock import Clock
from projectzero.founder_radar.companies import founder_ref_matches, loaded_companies, sourced_fact
from projectzero.founder_radar.evidence import add_evidence, dedupe_evidence
from projectzero.founder_radar.extraction import _norm_val
from projectzero.founder_radar.identity import (
    founded_by_connection,
    identity_resolution,
    official_page_hardened,
    role_bound_to_name,
)
from projectzero.founder_radar.names import _canon_domain, _fold, clean_person_name, is_person_name
from projectzero.founder_radar.scoring import assess
from projectzero.network.view import records as _records


def confirm_identity(
    p: dict[str, Any],
    human_name: Any,
    handle: Any,
    company: Any,
    url: Any,
    label: Any,
    fact: Any,
    confirm: Any,
    official_domain: Any = "",
    *,
    research: Any,
    ck: Clock,
) -> dict[str, Any]:
    """Identity resolves ONLY with evidence that explicitly connects human name + stable handle/id + relevant company,
    and explicit operator confirmation. A name edit alone is never verification. Aliases are kept; an operator-entered
    name is never overwritten."""
    if not confirm:
        return {"ok": False, "error": "explicit confirmation required"}
    ev = add_evidence("identity", url, label, fact, now=ck.now, today=ck.today)
    if not ev["ok"]:
        return ev
    human_name = str(human_name or "").strip()
    handle = str(handle or "").strip()
    company = str(company or "").strip()
    if not (is_person_name(human_name) and handle and company):
        return {"ok": False, "error": "human name, stable handle/id and company are all required"}
    fact_l = (fact or "").lower()
    team_page = (
        handle.startswith("http")
        and not any(k in handle.lower() for k in ("linkedin.com", "google.com/search", "github.com"))
        and re.search(r"/[^/]*(team|about|company|founders|people|leadership|news|press|blog|insights)", handle.lower())
    )
    if team_page:
        on_official = bool(official_domain) and _canon_domain(handle) == _canon_domain(
            official_domain
        )  # the page itself is the company's official domain
        role_route = role_bound_to_name(fact, human_name) and (_fold(company) in _fold(fact) or on_official)
        founded_route = (
            on_official
            and official_page_hardened(handle, official_domain, research)
            and founded_by_connection(fact, human_name, company)
        )
        if not (role_route or founded_route):
            return {
                "ok": False,
                "error": "an official team page confirmation must explicitly connect the name, a founder role and the company (or sit on the company's confirmed official domain)",
            }
    elif not (handle.lower() in fact_l and _fold(human_name) in _fold(fact) and _fold(company) in _fold(fact)):
        return {"ok": False, "error": "the verified fact must explicitly connect the name, the handle and the company"}
    old = p.get("name", "")
    if not p.get("name_by_operator") and p.get("provenance") != "user_provided":
        if old and old not in p.setdefault("aliases", []):
            p["aliases"].append(old)
        p["name"] = human_name
    if handle not in p.setdefault("aliases", []):
        p["aliases"].append(handle)
    p["name_attributed"] = True
    p["identity_verified_by"] = "operator"
    p["identity_verified_on"] = ck.minute()
    if company and company not in p.setdefault("companies", []):
        p["companies"].append(company)
    if not p.get("company"):
        p["company"] = company
    p.setdefault("identity_evidence", []).append(
        f"identity confirmed by operator with public evidence ({label}): {fact}"
    )
    p["identity_evidence"] = [x for x in p["identity_evidence"] if "login / handle only" not in x]
    p.setdefault("sources", []).append(
        {
            "source": ev["row"]["source"],
            "source_id": "operator-evidence",
            "url": url,
            "retrieved": ev["row"]["retrieved"],
            "route": "manual",
            "by": "operator",
            "claim": False,
        }
    )
    p.setdefault("evidence", []).append(ev["row"])
    p["evidence"] = dedupe_evidence(p["evidence"])
    p["identity_status"], p["identity_evidence"] = (
        identity_resolution(p)[0],
        list(dict.fromkeys(p["identity_evidence"] + identity_resolution(p)[1])),
    )
    if p.get("radar_state") == "needs identity resolution":
        p["radar_state"] = "detected"
    p["signal"] = assess(p, today=ck.today)
    p["signal_categories"] = p["signal"]["bands"]
    return {"ok": True}


@dataclass(frozen=True)
class Review:
    """The old answer and the documents as the old code left them. ``research`` / ``companies`` are None when that
    document was not saved (a refusal); ``people`` is the new people list when a person changed (else None) with
    ``people_changed`` their ids in document order."""

    body: dict[str, Any]
    research: Any = None
    companies: Any = None
    people: list[Any] | None = None
    people_changed: list[Any] = field(default_factory=list)


def loaded_research(doc: Any) -> dict[str, Any]:
    """The old ``load_research()`` over a stored body (missing -> ``{"domains": {}}``), as a deep copy."""
    return copy.deepcopy(doc) if doc is not None else {"domains": {}}


def confirm_pairing(
    research_doc: Any,
    companies_doc: Any,
    key: Any,
    proposal_id: Any,
    person_id: Any,
    live_ids: Collection[Any] | None = None,
    operator: str = "operator",
    *,
    ck: Clock,
) -> Review:
    """Explicit pair-confirmation for a handle-only founder reference: records that THIS proposal's human name is THIS
    record, with operator provenance. Required before identity confirmation can bind a login-only record."""
    res = loaded_research(research_doc)
    dom = res["domains"].get(key)
    if not dom or proposal_id not in dom.get("proposals", {}):
        return Review({"ok": False, "error": "unknown proposal"})
    p = dom["proposals"][proposal_id]
    if p.get("field") != "founder" or p.get("status") != "pending":
        return Review({"ok": False, "error": "only pending founder proposals can be paired"})
    if clean_person_name(p["person"]["name"]) != p["person"]["name"]:
        return Review({"ok": False, "error": "malformed founder candidate — not a clean human name"})
    refs = loaded_companies(companies_doc).get("companies", {}).get(key, {}).get("founder_refs", {})
    ref = next((r for r in refs.values() if r["person_id"] == person_id), None)
    if ref is not None and live_ids is not None and person_id not in live_ids:
        ref = None  # revision 2: a merged (tombstone) id is absent
    if not ref:
        return Review({"ok": False, "error": "selected record is not a founder reference of this company"})
    if not ref.get("handle_only") and not founder_ref_matches(
        ref, p["person"]["name"]
    ):  # a NAMED founder reference pairs only with its own name (aliases count); nothing is written
        return Review(
            {
                "ok": False,
                "error": "proposal name '{}' does not match the founder reference '{}' — pairing refused".format(
                    p["person"]["name"], ref.get("claimed_name") or person_id
                ),
            }
        )
    dom.setdefault("pairings", {})[proposal_id] = {
        "person_id": person_id,
        "founder_ref_id": ref["founder_ref_id"],
        "proposed_name": p["person"]["name"],
        "by": operator,
        "on": ck.second(),
    }
    dom.setdefault("history", []).append(
        {
            "proposal": proposal_id,
            "from": "pending",
            "to": f"pending (paired with {person_id})",
            "by": operator,
            "on": ck.second(),
            "person": person_id,
        }
    )
    return Review({"ok": True, "pairing": dom["pairings"][proposal_id]}, research=res)


def review_proposals(
    research_doc: Any,
    companies_doc: Any,
    key: Any,
    confirm_ids: Any = (),
    reject_ids: Any = (),
    bindings: dict[str, str] | None = None,
    people: list[Any] | None = None,
    allowed_person_ids: Collection[Any] | None = None,
    official_domain: Any = "",
    operator: str = "operator",
    *,
    ck: Clock,
) -> Review:
    """ONE auditable operator action. Transitions only from `pending` (replays / stale ids are explicit conflicts,
    never re-applied). Company facts dedupe by proposal id, then field + normalized value + URL + passage; access
    routes by value + URL. Founder proposals bind per proposal ({proposal_id: person_id}); a person may receive one
    identity per action; missing or failed binding stays pending and actionable. Append-only decision history."""
    res = loaded_research(research_doc)
    dom = res["domains"].get(key)
    if not dom:
        return Review({"ok": False, "error": "nothing researched for this company yet"})
    dom.setdefault("history", [])
    bindings = bindings or {}
    cd = loaded_companies(companies_doc)
    comp = cd["companies"].setdefault(key, {})
    people_data = {"people": copy.deepcopy(people)} if people is not None else None
    made: list[Any] = []
    refused: list[Any] = []
    conflicts: list[Any] = []
    bound: list[Any] = []
    pending: list[Any] = []
    now = ck.second()
    used_persons: set[Any] = set()

    def hist(pid: Any, prior: Any, new: Any, person: Any = None) -> None:
        dom["history"].append({"proposal": pid, "from": prior, "to": new, "by": operator, "on": now, "person": person})

    for pid in list(confirm_ids):
        p = dom["proposals"].get(pid)
        if not p:
            conflicts.append({"proposal": pid, "reason": "unknown proposal for this company"})
            continue
        if p["status"] != "pending":
            conflicts.append({"proposal": pid, "reason": "not pending ({})".format(p["status"])})
            continue
        if p["field"] in DECISION_FIELDS:
            r = sourced_fact(
                p["field"],
                p["value"],
                p["passage"],
                p["url"],
                p["source_label"],
                True,
                p.get("activity_date") or None,
                now=ck.now,
                today=ck.today,
            )
            if not r["ok"]:
                p["status"] = "refused: " + r["error"]
                refused.append(p["field"])
                hist(pid, "pending", p["status"])
                continue
            facts = comp.setdefault("facts", [])
            dup = any(f.get("from_proposal") == pid for f in facts) or any(
                f["field"] == p["field"]
                and _norm_val(f["value"]) == _norm_val(p["value"])
                and f["source_url"] == p["url"]
                and _norm_val(f.get("claim")) == _norm_val(p["passage"])
                for f in facts
            )
            if not dup:
                r["fact"]["from_proposal"] = pid
                facts.append(r["fact"])
            p["status"] = "confirmed"
            made.append(p["field"])
            hist(pid, "pending", "confirmed")
        elif p["field"] == "access_route":
            routes = comp.setdefault("access_routes", [])
            if not any(_norm_val(x["value"]) == _norm_val(p["value"]) and x.get("url") == p["url"] for x in routes):
                routes.append(
                    {
                        "value": p["value"],
                        "url": p["url"],
                        "recorded": now,
                        "by": operator,
                        "from_proposal": pid,
                        "kind": "cold company access route",
                    }
                )
            p["status"] = "confirmed"
            made.append("access_route")
            hist(pid, "pending", "confirmed")
        elif p["field"] == "founder":
            person_id = bindings.get(pid)
            if not person_id:
                pending.append({"proposal": pid, "reason": "no person selected — still pending"})
                p["last_error"] = "no person selected"
                continue
            if allowed_person_ids is not None and person_id not in allowed_person_ids:
                pending.append(
                    {"proposal": pid, "reason": "selected person is not a founder reference of this company"}
                )
                p["last_error"] = "person not in this company lead"
                continue
            refs = comp.get("founder_refs", {})
            ref = next((r for r in refs.values() if r["person_id"] == person_id), None)
            pairing = (dom.get("pairings") or {}).get(pid)
            paired = bool(
                pairing
                and pairing.get("person_id") == person_id
                and _fold(pairing.get("proposed_name")) == _fold(p["person"]["name"])
            )
            if ref is None or not (founder_ref_matches(ref, p["person"]["name"]) or paired):
                why = (
                    (
                        "handle-only record — confirm the pairing ({} ↔ {}) explicitly first".format(
                            p["person"]["name"], person_id
                        )
                    )
                    if (ref and ref.get("handle_only"))
                    else (
                        "proposal name '{}' does not match founder reference '{}'".format(
                            p["person"]["name"], (ref or {}).get("claimed_name") or person_id
                        )
                    )
                )
                pending.append({"proposal": pid, "reason": why})
                p["last_error"] = why
                continue
            if person_id in used_persons:
                pending.append(
                    {"proposal": pid, "reason": "one identity per person per action — second proposal left pending"}
                )
                p["last_error"] = "person already bound in this action"
                continue
            pr = (
                next((x for x in _records(people_data["people"]) if x.get("id") == person_id), None)
                if people_data is not None
                else None
            )
            if pr is None:
                pending.append({"proposal": pid, "reason": "person record not found"})
                p["last_error"] = "person not found"
                continue
            rr = confirm_identity(
                pr,
                p["person"]["name"],
                p["url"],
                p["person"]["company"],
                p["url"],
                p["source_label"],
                p["passage"],
                True,
                official_domain=official_domain,
                research=research_doc if research_doc is not None else {"domains": {}},
                ck=ck,
            )
            if not rr["ok"]:
                pending.append({"proposal": pid, "reason": rr["error"]})
                p["last_error"] = rr["error"]
                continue
            pr["identity_evidence"] = list(dict.fromkeys(pr.get("identity_evidence") or []))
            pr["sources"] = [
                json.loads(s) for s in dict.fromkeys(json.dumps(s, sort_keys=True) for s in (pr.get("sources") or []))
            ]
            used_persons.add(person_id)
            p["status"] = "confirmed"
            p["bound_person"] = person_id
            p.pop("last_error", None)
            bound.append({"proposal": pid, "person": person_id, "name": p["person"]["name"]})
            hist(pid, "pending", "confirmed", person_id)
    for pid in list(reject_ids):
        p = dom["proposals"].get(pid)
        if not p:
            conflicts.append({"proposal": pid, "reason": "unknown proposal for this company"})
            continue
        if p["status"] != "pending":
            conflicts.append({"proposal": pid, "reason": "not pending ({})".format(p["status"])})
            continue
        p["status"] = "rejected"
        hist(pid, "pending", "rejected")
    body = {
        "ok": True,
        "facts": made,
        "refused": refused,
        "conflicts": conflicts,
        "identity_bound": bound,
        "still_pending": pending,
        "history_len": len(dom["history"]),
    }
    new_people = people_data["people"] if (bound and people_data is not None) else None
    changed = [pid for pid in dict.fromkeys(b["person"] for b in bound)]
    if new_people is not None:
        order = [x.get("id") for x in _records(new_people)]
        changed = [i for i in order if i in changed]
    return Review(body, research=res, companies=cd, people=new_people, people_changed=changed)

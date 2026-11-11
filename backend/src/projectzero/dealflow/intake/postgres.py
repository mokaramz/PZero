"""Postgres side of intake: record the submission and resolve its entities, on ONE connection inside ONE transaction.

Usage (CLI, API, scheduler)::

    with transaction(settings.db_url) as conn:
        store = PostgresIntake(conn, schema)
        result = IntakeService(store, resolver=store).submit_external(payload, submitted_by="grok")

Resolution takes a transaction-scoped advisory lock first, so concurrent deliveries resolve one after another and can
never create two companies for the same new name, or two candidates for the same company.

**The production write boundary is guarded**: ``insert_if_absent`` refuses to write into ``pz`` until the legacy
import marker exists, for every caller (CLI, API, trusted in-process writers) - review 004 #2.

**A delivery is decided as a whole** (review 004 #1), so the order of entities in the file never changes the result:
``identity_rules.plan_delivery`` groups the company entities by strong identity against what is stored (an entity
bridging two companies stays unresolved), and a name shared by two groups of the same delivery is ambiguous, so
neither group may join a stored company by name. Each group then gets ONE company decision.

Per accepted entity:
* company / opportunity -> its group's company decision; person / event -> no company.
* The company's open candidate gets the new evidence (``re_reported``); if it only has closed candidates, the newest
  one gets it (``re_reported_closed``) and keeps its status; otherwise a new ``new`` candidate is created.
  Intake never changes an existing candidate's status.
* A person or event re-delivered with the same ``external_id`` from the same origin attaches to its candidate.
* Every entity leaves an observation (evidence + the entity as delivered) and an ``intake`` event.

**Ingest tagging** (review 007, decision 0002): a company / opportunity candidate CREATED by a live origin (Grok,
manual) stores ``attrs.tagging`` = the old scan's tags for it, with the inputs they came from and a version. On a
re-report the tags are replayed from the stored columns (so unchanged inputs give identical tags), and a different
live origin is added once as a cross-source sighting. Imported and untagged candidates are never retagged here.
Interstitial entities never reach this module: the contract refuses them before identity grouping.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from projectzero.core.db import schema_ident
from projectzero.dealflow.identity import company_domain, is_placeholder_name, normalize_name
from projectzero.dealflow.identity_rules import (
    Decision,
    EntityFacts,
    GroupPlan,
    StoredCompany,
    StrongKey,
    decide,
    origin_family,
    plan_delivery,
)
from projectzero.dealflow.intake.contract import COMPANY_KINDS
from projectzero.dealflow.intake.service import SubmissionRecord
from projectzero.dealflow.ranking import tagging
from projectzero.dealflow.sources.registry import registry_value

_ENTITY_ATTRS = (
    "external_id", "related_external_ids", "flags", "intent", "source_scouts", "scout_assessment", "claims", "stage",
    "signal_types", "signal_date", "confidence", "recommended_action", "thesis_fit", "founders", "aliases",
    "registry_ids", "website", "event",
)  # fmt: skip


IMPORT_MARKER = "ops/legacy_import"


class IntakeClosedError(RuntimeError):
    """Live intake into ``pz`` opens only after the one-time legacy import (else the import would collide)."""


def ensure_intake_open(conn: psycopg.Connection[Any], schema: str) -> None:
    """Refuse live deliveries into the production schema until the legacy import has written its marker."""
    if schema != "pz":
        return  # scratch / test schemas are always open
    row = conn.execute(
        sql.SQL("select 1 from {}.documents where key = %s").format(schema_ident(schema)), (IMPORT_MARKER,)
    ).fetchone()
    if row is None:
        raise IntakeClosedError(
            "intake opens after the legacy import: run `python -m projectzero.ops.legacy apply --confirm` first "
            "(validate deliveries meanwhile with `pz intake check`)"
        )


class PostgresIntake:
    """Implements both ``SubmissionStore`` and ``EntityResolver`` for one open transaction."""

    def __init__(self, conn: psycopg.Connection[Any], schema: str = "pz") -> None:
        self.conn = conn
        self.s = schema_ident(schema)
        self._schema = schema
        self.submission_id: str | None = None

    def _q(self, query: str) -> sql.Composed:
        return sql.SQL(query).format(s=self.s)

    def _one(self, query: str, params: Sequence[Any] = ()) -> tuple[Any, ...] | None:
        return self.conn.execute(self._q(query), params).fetchone()

    def _all(self, query: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        return self.conn.execute(self._q(query), params).fetchall()

    # ── SubmissionStore ─────────────────────────────────────────────────────────────────────────────────────────
    def insert_if_absent(self, submission: SubmissionRecord) -> bool:
        ensure_intake_open(self.conn, self._schema)  # the shared write boundary: no caller can bypass it
        row = self._one(
            "select submission_id, inserted from {s}.record_submission(%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                submission.origin.value, submission.submitted_by, submission.external_ref, submission.sha256,
                submission.contract_version, Jsonb(dict(submission.payload)), submission.outcome,
                Jsonb(dict(submission.outcome_detail)),
            ),
        )  # fmt: skip
        assert row is not None
        self.submission_id = str(row[0])
        return bool(row[1])

    # ── EntityResolver ──────────────────────────────────────────────────────────────────────────────────────────
    def resolve_submission(
        self, submission: SubmissionRecord, entities: Sequence[tuple[int, Mapping[str, Any]]]
    ) -> list[dict[str, Any]]:
        self.conn.execute(sql.SQL("select pg_advisory_xact_lock(hashtext(%s))"), (f"{self._schema}.intake",))
        origin = submission.origin.value
        family = origin_family(origin)
        by_index = dict(entities)
        companies = {i: e for i, e in entities if str(e["kind"]) in COMPANY_KINDS}
        facts = [
            EntityFacts(i, tuple(self._strong_keys(e, origin)), self._name_key(e)) for i, e in sorted(companies.items())
        ]
        owner_of = {key: owner for f in facts for key in f.keys if (owner := self._owner(key))}
        plan = plan_delivery(facts, owner_of)

        decided: dict[int, tuple[Decision, str | None, GroupPlan | None]] = {}
        for index in companies:
            if index in plan.conflicts:
                conflict = Decision("conflict", basis="identity_conflict", detail=plan.conflicts[index])
                decided[index] = (conflict, None, None)
        for group in plan.groups:
            decision, company_id = self._decide_group(group, [by_index[m] for m in group.members], family, origin)
            for member in group.members:
                decided[member] = (decision, company_id, group)

        results: list[dict[str, Any]] = []
        group_candidate: dict[tuple[int, ...], str] = {}
        for index, entity in sorted(by_index.items()):
            not_company = Decision("none", basis="not_a_company", detail=f"kind {entity['kind']}")
            decision, company_id, member_of = decided.get(index, (not_company, None, None))
            result = self._resolve_one(index, entity, origin, decision, company_id)
            results.append(result)
            if member_of is not None:
                group_candidate.setdefault(member_of.members, result["candidate_id"])
        for group in plan.groups:  # one suggestion per group, raised on its candidate
            decision, company_id, _ = decided[group.members[0]]
            for other in decision.suggest_with:
                names = " / ".join(sorted(group.names))
                self._suggest(group_candidate[group.members], company_id, other, names, decision.detail)
        self.conn.execute(
            self._q("update {s}.intake_submissions set outcome_detail = outcome_detail || %s where id = %s"),
            (Jsonb({"resolution": results}), self.submission_id),
        )
        return results

    def _decide_group(
        self, group: GroupPlan, members: list[Mapping[str, Any]], family: str, origin: str
    ) -> tuple[Decision, str | None]:
        names = [str(m["name"]).strip() for m in members]
        usable = sorted({n for n in names if not is_placeholder_name(n)}, key=str.casefold)
        if group.stored_company:
            decision = Decision("join", group.stored_company, basis="strong_identifier")
        else:
            same_name = sorted({cid for name in group.names for cid in self._companies_named(name)})
            decision = decide(
                family=family,
                strong_keys=list(group.keys),
                owners=[],
                same_name=[self._stored_company(cid) for cid in same_name],
                has_usable_name=bool(usable),
                delivery_ambiguous=group.name_ambiguous,
            )
        display = members[names.index(usable[0])] if usable else members[0]
        company_id = self._apply_company(decision, display, usable[0] if usable else "", list(group.keys), origin)
        return decision, company_id

    def _resolve_one(
        self, index: int, entity: Mapping[str, Any], origin: str, decision: Decision, company_id: str | None
    ) -> dict[str, Any]:
        kind = str(entity["kind"])
        name = str(entity["name"]).strip()
        if kind in COMPANY_KINDS and company_id:
            candidate_id, action = self._company_candidate(company_id, entity, name, origin)
        elif kind in COMPANY_KINDS:
            candidate_id, action = (
                self._create_candidate(None, entity, name, origin, identity=decision.basis),
                "created",
            )
        elif existing := self._by_external_id(kind, origin, entity.get("external_id")):
            candidate_id, action = existing, "re_reported"
        else:
            candidate_id, action = (
                self._create_candidate(None, entity, name, origin, identity=decision.basis),
                "created",
            )
        if action != "created":
            self._touch(candidate_id, entity, origin)
        self._observe(candidate_id, entity, origin)
        detail = {
            "submission_id": self.submission_id,
            "index": index,
            "company": company_id,
            "decision": decision.basis,
            "decision_detail": decision.detail,
        }
        self._event(candidate_id, "intake", detail | {"result": action})
        if decision.action == "conflict":
            self._event(candidate_id, "identity_conflict", detail)
        return {
            "index": index,
            "name": name,
            "kind": kind,
            "candidate_id": candidate_id,
            "result": action,
            "company_id": company_id,
            "company_decision": decision.basis,
        }

    # ── identity ────────────────────────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _strong_keys(entity: Mapping[str, Any], origin: str) -> list[StrongKey]:
        keys: list[StrongKey] = []
        for namespace, raw in sorted((entity.get("registry_ids") or {}).items()):
            if (value := registry_value(raw)) is not None:
                keys.append(("registry", str(namespace), value))
        if domain := company_domain(entity.get("website")):
            keys.append(("domain", "", domain))
        if external_id := entity.get("external_id"):
            keys.append(("submitter_key", origin, str(external_id)))
        return keys

    @staticmethod
    def _name_key(entity: Mapping[str, Any]) -> str | None:
        name = str(entity.get("name") or "")
        return None if is_placeholder_name(name) else normalize_name(name)

    def _owner(self, key: StrongKey) -> str | None:
        row = self._one(
            "select company_id from {s}.company_identifiers "
            "where kind = %s and namespace = %s and value = %s and strength = 'strong'",
            key,
        )
        return str(row[0]) if row else None

    def _companies_named(self, normalized: str) -> list[str]:
        rows = self._all(
            "select company_id from {s}.company_identifiers where kind = 'normalized_name' and value = %s",
            (normalized,),
        )
        return [str(r[0]) for r in rows]

    def _stored_company(self, company_id: str) -> StoredCompany:
        families = {
            origin_family(str(o))
            for (o,) in self._all(
                "select distinct unnest(origins) from {s}.candidates where company_id = %s", (company_id,)
            )
        }
        if self._one("select 1 from {s}.conviction_entries where company_id = %s", (company_id,)):
            families.add("conviction")
        keys = frozenset(
            (str(k), str(ns), str(v))
            for k, ns, v in self._all(
                "select kind, namespace, value from {s}.company_identifiers "
                "where company_id = %s and strength = 'strong'",
                (company_id,),
            )
        )
        return StoredCompany(company_id, frozenset(families), keys)

    def _apply_company(
        self, decision: Decision, entity: Mapping[str, Any], name: str, keys: list[StrongKey], origin: str
    ) -> str | None:
        if decision.action in ("conflict", "none"):
            return None
        location = entity.get("location") or {}
        if decision.action == "create":
            row = self._one(
                "insert into {s}.companies (name, normalized_name, website, country, location, sectors, attrs) "
                "values (%s, %s, %s, %s, %s, %s, %s) returning id",
                (name, normalize_name(name), entity.get("website"), location.get("country"), location.get("city"),
                 list(entity.get("sectors") or []), Jsonb({"created_by": origin})),
            )  # fmt: skip
            assert row is not None
            company_id = str(row[0])
            if normalized := normalize_name(name):
                self._identifier(company_id, ("normalized_name", "", normalized), origin)
        else:
            company_id = str(decision.company_id)
            # LOCK ORDER (all writers): company row first, then its candidate rows. This update takes the company lock
            # before _company_candidate/_touch touch a candidate; DealFlowStore.decide locks in the same order.
            self.conn.execute(
                self._q(
                    "update {s}.companies set website = coalesce(website, %s), country = coalesce(country, %s), "
                    "location = coalesce(location, %s) where id = %s"
                ),
                (entity.get("website"), location.get("country"), location.get("city"), company_id),
            )
        for key in keys:
            self._identifier(company_id, key, origin)
        return company_id

    def _identifier(self, company_id: str, key: StrongKey, origin: str) -> None:
        # owners were checked under the intake lock, so a conflict here can only be this company's own key
        self.conn.execute(
            self._q(
                "insert into {s}.company_identifiers (company_id, kind, namespace, value, source) "
                "values (%s, %s, %s, %s, %s) on conflict (company_id, kind, namespace, value) do nothing"
            ),
            (company_id, *key, origin),
        )

    # ── candidates ──────────────────────────────────────────────────────────────────────────────────────────────
    def _company_candidate(self, company_id: str, entity: Mapping[str, Any], name: str, origin: str) -> tuple[str, str]:
        open_row = self._one(
            "select id from {s}.candidates where company_id = %s and status not in ('rejected', 'archived')",
            (company_id,),
        )
        if open_row:
            return str(open_row[0]), "re_reported"
        closed = self._one(
            "select id from {s}.candidates where company_id = %s order by last_observed_at desc, id limit 1",
            (company_id,),
        )
        if closed:
            return str(closed[0]), "re_reported_closed"
        return self._create_candidate(company_id, entity, name, origin, identity=None), "created"

    def _by_external_id(self, kind: str, origin: str, external_id: Any) -> str | None:
        if not external_id:
            return None
        row = self._one(
            "select id from {s}.candidates where subject_kind = %s and attrs->>'external_key' = %s "
            "order by first_seen_at limit 1",
            (kind, f"{origin}:{external_id}"),
        )
        return str(row[0]) if row else None

    def _create_candidate(
        self, company_id: str | None, entity: Mapping[str, Any], name: str, origin: str, *, identity: str | None
    ) -> str:
        location = entity.get("location") or {}
        assessment = entity.get("scout_assessment") or {}
        attrs: dict[str, Any] = {k: entity[k] for k in _ENTITY_ATTRS if k in entity}
        if entity.get("external_id"):
            attrs["external_key"] = f"{origin}:{entity['external_id']}"
        if company_id is None and identity in ("identity_conflict", "no_company"):
            attrs["identity"] = "identity_conflict" if identity == "identity_conflict" else "unresolved_name"
        if entity["kind"] in COMPANY_KINDS and origin in tagging.LIVE_SOURCES:
            inputs = tagging.live_inputs(origin, name, entity.get("key_fact"), entity.get("stage"), entity.get("flags"))
            attrs["tagging"] = tagging.tag(inputs)
        row = self._one(
            "insert into {s}.candidates (company_id, subject_kind, name, status, origins, country, location, "
            "description, key_fact, key_unknown, recommended_object_type, sectors, attrs) "
            "values (%s, %s, %s, 'new', %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
            (company_id, entity["kind"], name, [origin], location.get("country"), location.get("city"),
             entity.get("thesis_fit"), entity.get("key_fact"), entity.get("key_unknown"),
             assessment.get("recommended_object_type"), list(entity.get("sectors") or []), Jsonb(attrs)),
        )  # fmt: skip
        assert row is not None
        candidate_id = str(row[0])
        self.conn.execute(
            self._q(
                "insert into {s}.candidate_aliases (namespace, alias_id, candidate_id, reason) "
                "values ('candidate', %s, %s, 'own_id')"
            ),
            (candidate_id, candidate_id),
        )
        return candidate_id

    def _touch(self, candidate_id: str, entity: Mapping[str, Any], origin: str) -> None:
        """New evidence on an existing candidate: never its status; fill gaps, extend origins, bump last_observed."""
        self.conn.execute(
            self._q(
                "update {s}.candidates set last_observed_at = now(), "
                "origins = (select array_agg(distinct o order by o) from unnest(origins || %s::text) o), "
                "key_fact = coalesce(key_fact, %s), key_unknown = coalesce(key_unknown, %s) where id = %s"
            ),
            (origin, entity.get("key_fact"), entity.get("key_unknown"), candidate_id),
        )
        self._retag(candidate_id, entity, origin)

    def _retag(self, candidate_id: str, entity: Mapping[str, Any], origin: str) -> None:
        """Replay a live-tagged candidate's tags from its stored columns, plus a sighting by a new live origin."""
        row = self._one("select name, key_fact, attrs from {s}.candidates where id = %s", (candidate_id,))
        assert row is not None
        name, key_fact, attrs = row[0], row[1], row[2] or {}
        stored = attrs.get("tagging")
        if not tagging.is_current(stored):
            return  # imported (legacy record) or pre-007 untagged: never retagged by intake
        first = stored["inputs"]["origin"]
        inputs = tagging.live_inputs(first, name, key_fact, attrs.get("stage"), attrs.get("flags"))
        sightings = list(stored.get("sightings") or [])
        seen = {inputs["source"]} | {s.get("source") for s in sightings}
        if origin in tagging.LIVE_SOURCES and tagging.LIVE_SOURCES[origin]["name"] not in seen:
            sightings.append(
                tagging.sighting_for(origin, entity.get("stage"), entity.get("flags"), str(self.submission_id))
            )
        fresh = tagging.tag(inputs, sightings)
        if fresh != stored:
            self.conn.execute(
                self._q(
                    "update {s}.candidates set attrs = attrs || jsonb_build_object('tagging', %s::jsonb) where id = %s"
                ),
                (Jsonb(fresh), candidate_id),
            )

    def _observe(self, candidate_id: str, entity: Mapping[str, Any], origin: str) -> None:
        evidence = list(entity.get("evidence") or [])
        self.conn.execute(
            self._q(
                "insert into {s}.observations (candidate_id, submission_id, origin, url, title, evidence, payload) "
                "values (%s, %s, %s, %s, %s, %s, %s)"
            ),
            (candidate_id, self.submission_id, origin, evidence[0]["url"] if evidence else None,
             entity.get("name"), Jsonb(evidence), Jsonb(dict(entity))),
        )  # fmt: skip

    def _event(self, candidate_id: str, action: str, detail: Mapping[str, Any]) -> None:
        self.conn.execute(
            self._q("insert into {s}.candidate_events (candidate_id, actor, action, detail) values (%s, %s, %s, %s)"),
            (candidate_id, "intake", action, Jsonb(dict(detail))),
        )

    def _suggest(
        self, candidate_id: str, company_id: str | None, other: str, normalized: str | None, reason: str
    ) -> None:
        others = [str(r[0]) for r in self._all("select id from {s}.candidates where company_id = %s", (other,))]
        detail = {"normalized_name": normalized, "reason": reason, "company": company_id, "other_company": other,
                  "other_candidates": others}  # fmt: skip
        self._event(candidate_id, "merge_suggested", detail)
        for other_candidate in others:
            self._event(other_candidate, "merge_suggested", detail | {"other_candidates": [candidate_id]})

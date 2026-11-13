"""The single intake service every origin goes through.

* ``submit_external`` — Grok / operator paste. All or nothing: one invalid entity refuses the whole submission and
  nothing is written, so the submitter fixes and resubmits one file.
* ``submit_trusted`` — registry connectors, research jobs, legacy import. The origin is set by the calling code, never
  by data. Entities are validated one by one; invalid ones are refused and reported, valid ones are accepted
  (``partial``), so one malformed registry record cannot block a whole scan.

Both paths deduplicate on the canonical sha256 of what was received: the same delivery twice is a no-op.

**The Deal Flow scan's creation hints** (review 034a, decision c): a ``REGISTRY_SCAN`` batch may carry ``scan``, per
entity index ``{"status": "new" | "baseline" | "rejected", "record": <the old scan record>, "run_id": ...}``. They act
ONLY when the resolution creates the candidate (its status, and ``attrs.scan_record``), or when it re-reports a
candidate the scan itself created (the old ``absorb``: provenance on ``attrs.scan_record``). An existing candidate's
status is never changed. The hints are not part of the delivery's canonical hash (the entities and ``external_ref``
are); any other origin carrying them is a programming error.
When a ``resolver`` is given, the accepted entities are resolved into companies and candidates right after the
submission is recorded. Postgres runs both in ONE transaction (``dealflow.intake.postgres``): a failure while
resolving also rolls back the submission row, so the same delivery can simply be resubmitted.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from projectzero.dealflow.intake.contract import (
    CONTRACT_VERSION,
    EXTERNAL_ORIGINS,
    Issue,
    Origin,
    canonical_sha256,
    cross_entity_issues,
    validate_entity,
    validate_external,
)

Outcome = Literal["accepted", "partial", "rejected", "duplicate"]


@dataclass(frozen=True)
class TrustedBatch:
    """What an in-process caller hands to intake. Constructing one with an external origin is a programming error."""

    origin: Origin
    submitted_by: str
    entities: Sequence[Mapping[str, Any]]
    external_ref: str | None = None
    summary: str | None = None
    scan: Mapping[int, Mapping[str, Any]] | None = None  # the Deal Flow scan's creation hints (REGISTRY_SCAN only)

    def __post_init__(self) -> None:
        if self.origin in EXTERNAL_ORIGINS:
            raise ValueError(f"origin '{self.origin}' must come through the external envelope (submit_external)")
        if not self.submitted_by.strip():
            raise ValueError("submitted_by is required")
        if self.scan is not None:
            if self.origin is not Origin.REGISTRY_SCAN:
                raise ValueError("scan creation hints are for the registry scan only")
            for index, hint in self.scan.items():
                if (
                    not 0 <= index < len(self.entities)
                    or hint.get("status") not in SCAN_CREATION_STATUSES
                    or ("source_id" in hint and not isinstance(hint["source_id"], str))
                ):
                    raise ValueError(f"invalid scan creation hint for entity {index}")


SCAN_CREATION_STATUSES = frozenset({"new", "baseline", "rejected"})  # decision c (review 034a): at creation only


@dataclass(frozen=True)
class SubmissionRecord:
    """A row of ``pz.intake_submissions``."""

    origin: Origin
    submitted_by: str
    external_ref: str | None
    sha256: str
    contract_version: str
    payload: Mapping[str, Any]
    outcome: Outcome
    outcome_detail: Mapping[str, Any]


class SubmissionStore(Protocol):
    def insert_if_absent(self, submission: SubmissionRecord) -> bool:
        """Atomically store the submission unless one with the same sha256 exists. True = this call inserted it.

        Postgres implementation: ``select * from pz.record_submission(...)`` (INSERT ... ON CONFLICT DO NOTHING).
        """
        ...


class EntityResolver(Protocol):
    def resolve_submission(
        self,
        submission: SubmissionRecord,
        entities: Sequence[tuple[int, Mapping[str, Any]]],
        hints: Mapping[int, Mapping[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Resolve the accepted (index, entity) pairs of the submission just recorded; one result each. ``hints``:
        the scan's creation hints (only ever passed for a ``REGISTRY_SCAN`` batch that carries them)."""
        ...


@dataclass(frozen=True)
class IntakeResult:
    outcome: Outcome
    sha256: str | None
    accepted: int = 0
    issues: tuple[Issue, ...] = ()
    refused: tuple[tuple[int, tuple[Issue, ...]], ...] = field(default=())  # (entity index, its issues)
    resolution: tuple[dict[str, Any], ...] = ()  # per accepted entity: candidate, company decision


class IntakeService:
    """No "look up, then insert": the store's atomic insert decides who wins a concurrent replay."""

    def __init__(self, store: SubmissionStore, resolver: EntityResolver | None = None) -> None:
        self._store = store
        self._resolver = resolver

    def _resolve(
        self,
        record: SubmissionRecord,
        accepted: Sequence[tuple[int, Mapping[str, Any]]],
        hints: Mapping[int, Mapping[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        if self._resolver is None:
            return ()
        if hints is not None:  # only the scan's batches: every other caller's resolver is called as before
            return tuple(self._resolver.resolve_submission(record, accepted, hints=hints))
        return tuple(self._resolver.resolve_submission(record, accepted))

    def submit_external(self, payload: Any, *, submitted_by: str) -> IntakeResult:
        issues = validate_external(payload)
        if issues:
            return IntakeResult("rejected", None, issues=tuple(issues))  # writes nothing
        sha = canonical_sha256(payload)
        entities = payload["entities"]
        record = SubmissionRecord(
            origin=Origin(payload["origin"]),
            submitted_by=submitted_by,
            external_ref=payload.get("external_ref"),
            sha256=sha,
            contract_version=CONTRACT_VERSION,
            payload=payload,
            outcome="accepted",
            outcome_detail={"entities": len(entities), "accepted": len(entities), "refused": []},
        )
        if not self._store.insert_if_absent(record):
            return IntakeResult("duplicate", sha)
        resolution = self._resolve(record, list(enumerate(entities)))
        return IntakeResult("accepted", sha, accepted=len(entities), resolution=resolution)

    def submit_trusted(self, batch: TrustedBatch) -> IntakeResult:
        payload: dict[str, Any] = {
            "contract_version": CONTRACT_VERSION,
            "origin": batch.origin.value,
            "external_ref": batch.external_ref,
            "summary": batch.summary,
            "entities": [dict(e) for e in batch.entities],
        }
        sha = canonical_sha256(payload)
        per_entity: dict[int, list[Issue]] = {}
        for index, entity in enumerate(batch.entities):
            if issues := validate_entity(entity, prefix=f"$/entities/{index}"):
                per_entity[index] = issues
        for index, issues in cross_entity_issues(batch.entities, per_entity.keys()).items():
            per_entity.setdefault(index, []).extend(issues)
        refused = tuple((index, tuple(sorted(set(per_entity[index])))) for index in sorted(per_entity))
        accepted = len(batch.entities) - len(refused)
        outcome: Outcome = "accepted" if not refused else ("partial" if accepted else "rejected")
        record = SubmissionRecord(
            origin=batch.origin,
            submitted_by=batch.submitted_by,
            external_ref=batch.external_ref,
            sha256=sha,
            contract_version=CONTRACT_VERSION,
            payload=payload,
            outcome=outcome,
            outcome_detail={
                "entities": len(batch.entities),
                "accepted": accepted,
                "refused": [{"index": i, "issues": [str(x) for x in iss]} for i, iss in refused],
            },
        )
        if not self._store.insert_if_absent(record):
            return IntakeResult("duplicate", sha)
        refused_at = {index for index, _ in refused}
        good = [(i, e) for i, e in enumerate(batch.entities) if i not in refused_at]
        hints = None if batch.scan is None else {i: batch.scan[i] for i, _ in good if i in batch.scan}
        resolution = self._resolve(record, good, hints)
        return IntakeResult(outcome, sha, accepted=accepted, refused=refused, resolution=resolution)

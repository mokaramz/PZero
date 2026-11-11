"""Shared state of the import builder: constants, the plan container and row helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from projectzero.ops.legacy.companies import CompanyBook
from projectzero.ops.legacy.source import LegacyFile, LegacySnapshot

TABLE_ORDER = (
    "sources",
    "companies",
    "company_identifiers",
    "people",
    "person_identifiers",
    "intake_submissions",
    "candidates",
    "candidate_aliases",
    "observations",
    "candidate_events",
    "triage_proposals",
    "candidate_routing",
    "committee_reviews",
    "conviction_entries",
    "events",
    "event_leads",
    "research_jobs",
    "model_ledger",
    "job_state",
    "job_runs",
    "documents",
)

# Files whose records are fully modelled. Partially modelled files keep their remainder as a `<path>#rest` document.
MODELLED_FILES = frozenset(
    {
        "inbox.json",
        "scout_intake.json",
        "native_scout.json",
        "real_data.json",
        "people.json",
        "events.json",
        "sources.json",
        "triage_proposals.json",
        "queue_routing.json",
        "committee.json",
        "inference_ledger.jsonl",
        "schedule/jobs.json",
        "schedule/runs.jsonl",
        "bridge_jobs.json",
    }
)
# Files a real legacy folder always has, and the collection each must hold. A missing file or collection is a
# blocker; a present but empty collection is allowed and reported (review 003 #4).
REQUIRED_FILES: dict[str, str | None] = {
    "inbox.json": "candidates",
    "real_data.json": "signals",
    "people.json": "people",
    "events.json": "events",
    "sources.json": "sources",
    "scout_intake.json": "items",
    "native_scout.json": "signals",
    "triage_proposals.json": "proposals",
    "queue_routing.json": "routes",
    "committee.json": "second_pass",
    "bridge_jobs.json": "jobs",
    "schedule/jobs.json": None,
    "inference_ledger.jsonl": None,
    "schedule/runs.jsonl": None,
}
# Rebuildable caches and fetched page text: archived byte for byte, never live state.
ARCHIVE_ONLY_PREFIXES = ("inference_cache/", "native_cache/", "research_pages/", ".watch/")

# Old scheduler intervals (services/scheduler.py JOBS), hours.
JOB_INTERVALS_H = {
    "watch_checks": 24,
    "deal_flow_scan": 168,
    "event_scan": 72,
    "validation_snapshot": 24,
    "news_refresh": 24,
    "triage_retry": 1,
    "news_weekly_review": 168,
    "source_network": 24,
    "triage_compression": 6,
    "native_scout": 12,
    "native_planner": 12,
    "native_bridge": 24,
    "case_refresh": 24,
    "scout00_inbox": 1,
    "news_source_review": 720,
}
BRIDGE_STATUS = {
    "queued": "queued",
    "sent": "running",
    "running": "running",
    "response_received": "staged",
    "needs_operator": "staged",
    "closed": "staged",
    "failed": "failed",
    "cancelled": "cancelled",
}
SECRET_KEY_PATTERN = re.compile(r"(api[_-]?key|secret|token|password|passwd|bearer)", re.IGNORECASE)


@dataclass
class ImportPlan:
    tables: dict[str, list[dict[str, Any]]]
    archive: list[LegacyFile]
    report: dict[str, Any]
    secrets_found: list[str] = field(default_factory=list)
    inventory_errors: list[str] = field(default_factory=list)
    identity_blockers: list[str] = field(default_factory=list)

    @property
    def blockers(self) -> list[str]:
        """Reasons apply must refuse. Empty means the plan may be applied."""
        return (
            [f"missing or malformed required file: {e}" for e in self.inventory_errors]
            + [f"secret-looking value in the source: {s}" for s in self.secrets_found]
            + self.identity_blockers
        )

    def counts(self) -> dict[str, int]:
        return {name: len(rows) for name, rows in self.tables.items()} | {"legacy_documents": len(self.archive)}


@dataclass
class _Candidate:
    row: dict[str, Any]
    namespace: str  # alias namespace of its legacy id
    legacy_id: str
    observations: list[dict[str, Any]]


class BuilderState:
    def __init__(self, source: LegacySnapshot, now: datetime) -> None:
        self.src = source
        self.now = now
        self.book = CompanyBook()
        self.t: dict[str, list[dict[str, Any]]] = {name: [] for name in TABLE_ORDER}
        self.cands: list[_Candidate] = []
        self.report: dict[str, Any] = {"generated_at": now.isoformat(), "reconciliation": {}, "notes": []}
        self.source_ids: set[str] = set()
        self.stub_sources: dict[str, dict[str, Any]] = {}
        self.cycle_submission: dict[str, str] = {}
        self.conviction_by_company: dict[str, dict[str, Any]] = {}
        self.identity_blockers: list[str] = []  # conflicts that make a record impossible to import (Conviction)

    def _identity_attrs(self, seed: str) -> dict[str, Any]:
        """Marks a candidate whose company could not be resolved, and why."""
        if seed in self.book.conflicted_seeds:
            return {"identity": "identity_conflict"}
        return {"identity": "unresolved_name"}

    # ── row helpers ─────────────────────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _candidate_row(**values: Any) -> dict[str, Any]:
        row: dict[str, Any] = {
            "subject_kind": "company",
            "key_fact": None,
            "key_unknown": None,
            "recommended_object_type": None,
            "decided_at": None,
        }
        row.update(values)
        for text in ("key_fact", "key_unknown", "recommended_object_type", "description", "why", "location"):
            if row.get(text) is not None and not isinstance(row[text], str):
                row[text] = str(row[text])
        return row

    @staticmethod
    def _observation(
        origin: str,
        source_id: str | None,
        observed_at: datetime,
        url: Any,
        title: Any,
        payload: dict[str, Any],
        *,
        evidence: list[dict[str, Any]] | None = None,
        submission_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "submission_id": submission_id,
            "origin": origin,
            "source_id": source_id,
            "observed_at": observed_at,
            "url": url if isinstance(url, str) else None,
            "title": title if isinstance(title, str) else None,
            "evidence": evidence if evidence is not None else ([{"url": url}] if isinstance(url, str) and url else []),
            "payload": payload,
        }

    def _event(self, candidate_id: str, action: str, *, to_status: str | None = None, detail: dict[str, Any]) -> None:
        self.t["candidate_events"].append(
            {
                "candidate_id": candidate_id,
                "actor": "import",
                "action": action,
                "from_status": None,
                "to_status": to_status,
                "reason": None,
                "detail": detail,
                "at": self.now,
            }
        )

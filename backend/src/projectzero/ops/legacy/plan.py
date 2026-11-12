"""Build the import plan: every legacy record mapped to rows, plus a reconciliation report. Pure: reads, never writes.

Everything is built from ONE captured snapshot (``LegacySnapshot``): mapping, archive and fingerprint read the same
bytes, so a table row can never disagree with its archived source.

Order matters for identity: Conviction first (registers ``legacy_key real_data:<slug>``), then Deal Flow, Scout
Intake and Native Scout planner leads. Open candidates that resolve to the same company are merged (survivor = most
advanced status, then earliest first_seen); every absorbed id stays resolvable through ``candidate_aliases``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from projectzero.ops.legacy.map_pipeline import PipelineMapper
from projectzero.ops.legacy.map_records import RecordsMapper
from projectzero.ops.legacy.map_scouts import ScoutMapper
from projectzero.ops.legacy.source import LegacySnapshot, LegacySource, parse_json_bytes, parse_jsonl_bytes
from projectzero.ops.legacy.state import REQUIRED_FILES, TABLE_ORDER, ImportPlan

__all__ = ["TABLE_ORDER", "ImportPlan", "build_plan", "check_inventory"]


def build_plan(source: LegacySnapshot | LegacySource, *, now: datetime | None = None) -> ImportPlan:
    """Plan from one captured snapshot; a live ``LegacySource`` is captured first, with change detection."""
    snapshot = source if isinstance(source, LegacySnapshot) else LegacySnapshot.capture(source.root)
    return _Builder(snapshot, now or datetime.now(UTC)).build()


def check_inventory(snapshot: LegacySnapshot) -> tuple[list[str], dict[str, Any]]:
    """Required files present, parseable and holding their collection. Returns (errors, per-file inventory)."""
    errors: list[str] = []
    inventory: dict[str, Any] = {}
    for path, key in REQUIRED_FILES.items():
        if not snapshot.exists(path):
            errors.append(f"{path}: missing")
            inventory[path] = {"present": False}
            continue
        raw = snapshot.file(path).raw
        try:
            body = parse_jsonl_bytes(raw) if path.endswith(".jsonl") else parse_json_bytes(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            errors.append(f"{path}: not parseable ({exc})")
            inventory[path] = {"present": True, "parseable": False}
            continue
        collection = body if key is None else (body.get(key) if isinstance(body, dict) else None)
        if not isinstance(collection, list | dict):
            errors.append(f"{path}: expected collection {key or '(top level)'!r} is missing or not a list/object")
            inventory[path] = {"present": True, "parseable": True, "collection": key, "records": None}
            continue
        inventory[path] = {"present": True, "parseable": True, "collection": key, "records": len(collection)}
    return errors, inventory


class _Builder(PipelineMapper, ScoutMapper, RecordsMapper):
    def build(self) -> ImportPlan:
        inventory_errors, inventory = check_inventory(self.src)
        self.report["inventory"] = inventory
        self.report["snapshot"] = {"files": len(self.src.paths()), "capture_attempts": self.src.attempts}
        self.sources()
        self.conviction()
        self.dealflow()
        self.intake()
        self.native()
        self.finalize_identity()
        alias_map = self.merge_candidates()
        self.suggestion_events()
        self.triage(alias_map)
        self.routing(alias_map)
        self.committee(alias_map)
        self.people()
        self.events()
        self.content_log()
        self.founder_calls()
        self.evaluations()
        self.source_network()
        self.founder_radar()
        self.research_jobs()
        self.ledger()
        self.schedule()
        self.companies_rows()
        self.t["sources"].extend(self.stub_sources.values())
        archive = list(self.src.files())
        secrets = self.documents(archive)
        self.report["counts"] = {name: len(rows) for name, rows in self.t.items()} | {"legacy_documents": len(archive)}
        self.report["archive_bytes"] = sum(len(f.raw) for f in archive)
        plan = ImportPlan(self.t, archive, self.report, secrets, inventory_errors, self.identity_blockers)
        self.report["blockers"] = plan.blockers
        return plan

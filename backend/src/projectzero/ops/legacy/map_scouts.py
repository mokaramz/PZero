"""Mappers for scout leads: Scout Intake (cycles + items) and Native Scout planner leads."""

from __future__ import annotations

from projectzero.dealflow.identity import company_domain
from projectzero.dealflow.intake.contract import canonical_sha256
from projectzero.ops.legacy.companies import StrongKey
from projectzero.ops.legacy.convert import (
    INTAKE_STATUS,
    NATIVE_STATUS,
    day,
    records,
    stable_short_id,
    stable_uuid,
    str_list,
    text_or_none,
    timestamp,
)
from projectzero.ops.legacy.state import (
    BuilderState,
    _Candidate,
)


class ScoutMapper(BuilderState):
    # ── Scout Intake ────────────────────────────────────────────────────────────────────────────────────────────
    def intake(self) -> None:
        data = self.src.json("scout_intake.json", {}) or {}
        for cycle in records(data.get("cycles")):
            cycle_id = str(cycle.get("cycle_id"))
            submission_id = stable_uuid(f"cycle:{cycle_id}")
            received = timestamp(cycle.get("imported")) or day(cycle.get("cycle_date")) or self.now
            self.t["intake_submissions"].append(
                {
                    "id": submission_id,
                    "origin": "legacy_scout00",
                    "submitted_by": "legacy-import",
                    "external_ref": cycle_id,
                    "sha256": canonical_sha256(cycle),
                    "contract_version": "legacy",
                    "payload": cycle,
                    "outcome": "accepted",
                    "outcome_detail": {"reported_counts": cycle.get("reported_counts")},
                    "received_at": received,
                    "processed_at": received,
                }
            )
            self.cycle_submission[cycle_id] = submission_id
        promoted = {
            "id",
            "entity_name",
            "status",
            "key_fact",
            "key_unknown",
            "recommended_object_type",
            "website",
            "location",
            "raw",
            "history",
        }
        for item in records(data.get("items")):
            keys: list[StrongKey] = []
            if domain := company_domain(text_or_none(item.get("website"))):
                keys.append(("domain", "", domain))
            for created in (item.get("linked") or {}).get("created") or []:
                if isinstance(created, dict) and created.get("kind") == "company" and created.get("id"):
                    keys.append(("legacy_key", "real_data", str(created["id"])))
            company_id = self.book.resolve(
                seed=f"scout_intake:{item['id']}",
                name=item.get("entity_name"),
                strong_keys=keys,
                source="legacy_scout00",
                website=text_or_none(item.get("website")),
                location=item.get("location"),
            )
            first_seen = timestamp(item.get("imported")) or day(item.get("date_discovered")) or self.now
            row = self._candidate_row(
                id=stable_short_id(f"scout_intake:{item['id']}"),
                company_id=company_id,
                name=item.get("entity_name") or "UNKNOWN",
                status=INTAKE_STATUS.get(str(item.get("status")), "new"),
                legacy_status=item.get("status"),
                origins=["legacy_scout00"],
                primary_source_id=None,
                priority=None,
                country=None,
                location=item.get("location") if isinstance(item.get("location"), str) else None,
                description=None,
                why=None,
                sectors=[],
                first_seen_at=first_seen,
                last_observed_at=first_seen,
                key_fact=item.get("key_fact"),
                key_unknown=item.get("key_unknown"),
                recommended_object_type=item.get("recommended_object_type"),
                attrs={k: v for k, v in item.items() if k not in promoted},
                legacy=item,
            )
            urls = str_list(item.get("evidence_urls"))
            observation = self._observation(
                "legacy_scout00",
                None,
                first_seen,
                urls[0] if urls else None,
                item.get("entity_name"),
                {
                    k: item.get(k)
                    for k in (
                        "cycle_id",
                        "source_scouts",
                        "signal_types",
                        "key_fact",
                        "key_unknown",
                        "attention_state",
                        "recommended_action",
                        "stage",
                        "founders",
                    )
                },
                evidence=[{"url": u} for u in urls],
                submission_id=self.cycle_submission.get(str(item.get("cycle_id"))),
            )
            self.cands.append(_Candidate(row, "scout_intake", item["id"], [observation]))
        self.report["reconciliation"]["scout_intake.json"] = {
            "cycles": len(records(data.get("cycles"))),
            "items": len(records(data.get("items"))),
            "events": len(records(data.get("events"))),
            "events_home": "documents (scout_intake.json#rest; event_id without the '|merged:' suffix)",
        }

    # ── Native Scout ────────────────────────────────────────────────────────────────────────────────────────────
    def native(self) -> None:
        signals = records((self.src.json("native_scout.json", {}) or {}).get("signals"))
        leads = [s for s in signals if s.get("origin") == "planner"]
        promoted = {"id", "name", "status", "why", "first_seen", "last_seen", "evidence", "history"}
        for s in leads:
            first_seen = timestamp(s.get("first_seen")) or self.now
            company_id = self.book.resolve(
                seed=f"native_scout:{s['id']}",
                name=s.get("name"),
                strong_keys=[],
                source="legacy_native",
                country=s.get("country") if isinstance(s.get("country"), str) and len(s["country"]) == 2 else None,
                description=s.get("why"),
            )
            evidence = [
                {"url": e["url"]} | ({"title": e["source"]} if e.get("source") else {})
                for e in s.get("evidence") or []
                if isinstance(e, dict) and e.get("url")
            ]
            row = self._candidate_row(
                id=stable_short_id(f"native_scout:{s['id']}"),
                company_id=company_id,
                name=s.get("name") or "UNKNOWN",
                status=NATIVE_STATUS.get(str(s.get("status")), "new"),
                legacy_status=s.get("status"),
                origins=["legacy_native"],
                primary_source_id=None,
                priority=None,
                country=None,
                location=None,
                description=s.get("why"),
                why=s.get("why"),
                sectors=[],
                first_seen_at=first_seen,
                last_observed_at=timestamp(s.get("last_seen")) or first_seen,
                attrs={k: v for k, v in s.items() if k not in promoted},
                legacy=s,
            )
            observation = self._observation(
                "legacy_native",
                None,
                first_seen,
                evidence[0]["url"] if evidence else None,
                s.get("name"),
                {k: s.get(k) for k in ("key", "lanes", "lane_why", "organizations", "geography", "confidence")},
                evidence=evidence,
            )
            self.cands.append(_Candidate(row, "native_scout", s["id"], [observation]))
        self.report["reconciliation"]["native_scout.json signals"] = {
            "in": len(signals),
            "planner_leads_as_candidates": len(leads),
            "theme_hypotheses_kept_as_documents": len(signals) - len(leads),
        }

    # ── candidates: merge open duplicates, emit rows, aliases, events ─────────────────────────────────────────────

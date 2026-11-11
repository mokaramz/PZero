"""Mappers for everything around candidates: machine proposals, people, events, spend, scheduler, documents."""

from __future__ import annotations

from typing import Any

from projectzero.network.people import WEAK_KINDS, columns_of, identifiers_of
from projectzero.ops.legacy.convert import (
    day,
    records,
    stable_uuid,
    timestamp,
)
from projectzero.ops.legacy.source import LegacyFile
from projectzero.ops.legacy.state import (
    ARCHIVE_ONLY_PREFIXES,
    BRIDGE_STATUS,
    JOB_INTERVALS_H,
    MODELLED_FILES,
    SECRET_KEY_PATTERN,
    BuilderState,
)


class RecordsMapper(BuilderState):
    # ── machine proposals ───────────────────────────────────────────────────────────────────────────────────────
    def triage(self, alias_map: dict[str, str]) -> None:
        proposals = (self.src.json("triage_proposals.json", {}) or {}).get("proposals", {})
        items = proposals.items() if isinstance(proposals, dict) else ((p.get("candidate_id"), p) for p in proposals)
        orphans = 0
        promoted = {
            "candidate_id",
            "run_id",
            "prompt_version",
            "input_sha",
            "proposal",
            "status",
            "model",
            "veto_model",
            "usd",
            "proposed_at",
        }
        for candidate_id, p in items:
            target = alias_map.get(str(candidate_id))
            if target is None:
                orphans += 1
                continue
            usd = p.get("usd")
            self.t["triage_proposals"].append(
                {
                    "candidate_id": target,
                    "run_id": p.get("run_id"),
                    "prompt_version": p.get("prompt_version"),
                    "input_sha": p.get("input_sha"),
                    "proposal": str(p.get("proposal") or "UNKNOWN"),
                    "status": p.get("status"),
                    "model": p.get("model"),
                    "veto_model": p.get("veto_model"),
                    "usd": usd if isinstance(usd, int | float) and not isinstance(usd, bool) else None,
                    "detail": {k: v for k, v in p.items() if k not in promoted},
                    "proposed_at": timestamp(p.get("proposed_at")) or self.now,
                    "is_current": target == candidate_id,
                }
            )
        self.report["reconciliation"]["triage_proposals.json"] = {
            "in": len(proposals),
            "rows": len(self.t["triage_proposals"]),
            "orphans_dropped_to_rest": orphans,
        }

    def routing(self, alias_map: dict[str, str]) -> None:
        routes = (self.src.json("queue_routing.json", {}) or {}).get("routes", {})
        seen: set[str] = set()
        folded = 0
        for candidate_id, r in routes.items():
            target = alias_map.get(candidate_id)
            if target is None or target in seen:
                folded += 1
                continue
            seen.add(target)
            priority = r.get("priority")
            self.t["candidate_routing"].append(
                {
                    "candidate_id": target,
                    "state": str(r.get("state") or "UNKNOWN"),
                    "priority": priority if isinstance(priority, int) else None,
                    "reason": r.get("reason"),
                    "detail": {k: v for k, v in r.items() if k not in {"state", "priority", "reason"}},
                    "updated_at": timestamp(r.get("at")) or self.now,
                }
            )
        self.report["reconciliation"]["queue_routing.json routes"] = {
            "in": len(routes),
            "rows": len(self.t["candidate_routing"]),
            "not_rows_kept_in_legacy_archive": folded,
        }

    def committee(self, alias_map: dict[str, str]) -> None:
        data = self.src.json("committee.json", {}) or {}
        total = 0
        for seat in ("chair", "outside", "second_pass"):
            for key, rec in (data.get(seat) or {}).items():
                total += 1
                target = alias_map.get(str(rec.get("candidate_id") or key))
                if target is None:
                    continue
                self.t["committee_reviews"].append(
                    {
                        "candidate_id": target,
                        "seat": seat,
                        "model": rec.get("model"),
                        "verdict": rec.get("route") or rec.get("verdict"),
                        "detail": rec,
                        "reviewed_at": timestamp(rec.get("at")) or self.now,
                    }
                )
        self.report["reconciliation"]["committee.json"] = {"in": total, "rows": len(self.t["committee_reviews"])}

    # ── network, events ─────────────────────────────────────────────────────────────────────────────────────────
    def people(self) -> None:
        """``people.json`` -> people + person_identifiers (review 012).

        A record without an ``id`` is skipped and reported (the old ``compat.records(..., ("id",))``: the old app never
        showed it); two records with one id are a blocker (the old ``people.get`` saw only the first). ``created_at``
        is the old ``created`` day; ``normalized_name`` the old person key ``fold``. Strong identifiers are globally
        unique (a cross-person repeat is reported, not stored); weak ones (``url``, ``alias``) are unique per person.
        """
        collection = (self.src.json("people.json", {}) or {}).get("people")
        items = list(collection.values()) if isinstance(collection, dict) else collection
        items = items if isinstance(items, list) else []
        owned: dict[tuple[str, str], str] = {}
        seen_ids: dict[str, Any] = {}
        duplicates: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        repeated = 0
        created_from_import_time = 0
        for position, p in enumerate(items):
            if not isinstance(p, dict) or p.get("id") in (None, ""):
                name = p.get("name") if isinstance(p, dict) else None
                why = "no id" if isinstance(p, dict) else "not a record"
                skipped.append({"position": position, "name": name if isinstance(name, str) else None, "why": why})
                continue
            pid = str(p["id"])
            if pid in seen_ids:
                self.identity_blockers.append(
                    f"people.json records {seen_ids[pid]!r} and {p.get('name')!r} share the id {pid!r}: "
                    "the old app showed only the first; rename or merge one first"
                )
                continue
            seen_ids[pid] = p.get("name")
            created = day(p.get("created"))
            if created is None:
                created_from_import_time += 1
            self.t["people"].append(
                {
                    "id": pid,
                    # the ONE mapping shared with the Network writes (review 013): name / fold key / text columns,
                    # a non-text promoted value stays in attrs, and "record" (reserved for application writes,
                    # review 012, H-078) stays in legacy only
                    **columns_of(pid, p),
                    "legacy": p,
                    "created_at": created or self.now,
                }
            )
            mine: set[tuple[str, str]] = set()
            for kind, value in identifiers_of(p):
                if (kind, value) in mine:
                    repeated += 1  # the same identifier twice on one person: one row, nothing to report
                    continue
                mine.add((kind, value))
                if kind not in WEAK_KINDS:
                    owner = owned.setdefault((kind, value), pid)
                    if owner != pid:
                        duplicates.append({"kind": kind, "value": value, "people": [owner, pid]})
                        continue
                self.t["person_identifiers"].append({"person_id": pid, "kind": kind, "value": value})
        by_kind: dict[str, int] = {}
        for i in self.t["person_identifiers"]:
            by_kind[i["kind"]] = by_kind.get(i["kind"], 0) + 1
        self.report["reconciliation"]["people.json"] = {
            "in": len(items),
            "rows": len(self.t["people"]),
            "skipped_without_id": skipped,
            "duplicate_ids_blocked": len(items) - len(skipped) - len(self.t["people"]),
            "created_at_from_import_time": created_from_import_time,
            "identifiers": dict(sorted(by_kind.items())),
            "duplicate_identifiers_not_stored": duplicates,
            "repeated_within_one_person": repeated,
            "company_links": "kept in people.attrs (legacy links are by name; company_people waits for confirmation)",
        }

    def events(self) -> None:
        data = self.src.json("events.json", {}) or {}
        promoted = {"id", "name", "start", "end", "city", "country", "url", "status", "lat", "lng"}
        for e in records(data.get("events")):
            self.t["events"].append(
                {
                    "id": e["id"],
                    "name": e.get("name") or e["id"],
                    "starts_at": day(e.get("start")),
                    "ends_at": day(e.get("end")),
                    "city": e.get("city"),
                    "country": e.get("country") if isinstance(e.get("country"), str) else None,
                    "url": e.get("url"),
                    "status": e.get("status"),
                    "lat": e.get("lat") if isinstance(e.get("lat"), int | float) else None,
                    "lng": e.get("lng") if isinstance(e.get("lng"), int | float) else None,
                    "attrs": {k: v for k, v in e.items() if k not in promoted},
                    "legacy": e,
                }
            )
        self.report["reconciliation"]["events.json"] = {
            "events": len(records(data.get("events"))),
            "leads_home": "documents (events.json#rest)",
        }

    # ── research jobs, spend, scheduler ─────────────────────────────────────────────────────────────────────────
    def research_jobs(self) -> None:
        jobs = (self.src.json("bridge_jobs.json", {}) or {}).get("jobs", {})
        for job in jobs.values() if isinstance(jobs, dict) else jobs:
            subject = job.get("subject")
            context = job.get("context") if isinstance(job.get("context"), dict) else {}
            cap = context.get("cost_cap_usd")
            self.t["research_jobs"].append(
                {
                    "id": stable_uuid(f"bridge:{job.get('job_id')}"),
                    "job_type": str(job.get("job_type") or "UNKNOWN"),
                    "target_kind": str(
                        subject.get("kind") if isinstance(subject, dict) and subject.get("kind") else "legacy"
                    ),
                    "target_id": str(
                        subject.get("id")
                        if isinstance(subject, dict) and subject.get("id")
                        else (subject if isinstance(subject, str) else job.get("job_id"))
                    ),
                    "status": BRIDGE_STATUS.get(str(job.get("status")), "staged"),
                    "cost_cap_usd": cap if isinstance(cap, int | float) and not isinstance(cap, bool) else 0,
                    "request": {k: v for k, v in job.items() if k not in {"response", "result"}},
                    "result": {"response": job.get("response"), "result": job.get("result")},
                    "error": job.get("error") if isinstance(job.get("error"), str) and job.get("error") else None,
                    "created_at": timestamp(job.get("created_at")) or self.now,
                }
            )
        self.report["reconciliation"]["bridge_jobs.json"] = {"jobs": len(jobs), "rows": len(self.t["research_jobs"])}

    def ledger(self) -> None:
        lines = self.src.jsonl("inference_ledger.jsonl")
        promoted = {
            "ts",
            "purpose",
            "provider",
            "model",
            "entity_id",
            "usd",
            "input_tokens",
            "output_tokens",
            "cached",
            "outcome",
        }
        for line in lines:
            usd = line.get("usd")
            self.t["model_ledger"].append(
                {
                    "at": timestamp(line.get("ts")) or self.now,
                    "purpose": str(line.get("purpose") or "unknown"),
                    "provider": line.get("provider"),
                    "model": line.get("model"),
                    "entity_ref": line.get("entity_id"),
                    "usd": usd if isinstance(usd, int | float) and not isinstance(usd, bool) else 0,
                    "tokens_in": line.get("input_tokens") if isinstance(line.get("input_tokens"), int) else None,
                    "tokens_out": line.get("output_tokens") if isinstance(line.get("output_tokens"), int) else None,
                    "cached": bool(line.get("cached")),
                    "outcome": line.get("outcome"),
                    "detail": {k: v for k, v in line.items() if k not in promoted},
                }
            )
        self.report["reconciliation"]["inference_ledger.jsonl"] = {
            "lines": len(lines),
            "rows": len(self.t["model_ledger"]),
        }

    def schedule(self) -> None:
        jobs = self.src.json("schedule/jobs.json", {}) or {}
        for name, state in jobs.items():
            self.t["job_state"].append(
                {
                    "job": name,
                    "interval_hours": JOB_INTERVALS_H.get(name, 24),
                    "enabled": True,
                    "last_started_at": timestamp(state.get("started")),
                    "last_finished_at": timestamp(state.get("finished")),
                    "last_outcome": state.get("outcome") or state.get("state"),
                    "detail": state,
                }
            )
        runs = self.src.jsonl("schedule/runs.jsonl")
        for run in runs:
            self.t["job_runs"].append(
                {
                    "job": str(run.get("job") or "unknown"),
                    "started_at": timestamp(run.get("at")) or self.now,
                    "finished_at": None,
                    "outcome": "ok" if run.get("ok") else "failed",
                    "detail": run,
                }
            )
        self.report["reconciliation"]["schedule"] = {"jobs": len(jobs), "runs": len(runs)}
        self.report["notes"].append("job_runs.started_at holds the legacy 'at' (recording time); finished_at unknown")

    def documents(self, archive: list[LegacyFile]) -> list[str]:
        """Un-modelled state as documents; secret-looking values are redacted and reported."""
        secrets: list[str] = []
        rest_keys = {
            "inbox.json": {"candidates"},
            "scout_intake.json": {"cycles", "items"},
            "native_scout.json": set(),
            "events.json": {"events"},
            "triage_proposals.json": {"proposals"},
            "queue_routing.json": set(),
            "committee.json": set(),
            "people.json": {"people"},
            "sources.json": {"sources"},
            "real_data.json": {"signals"},
            "bridge_jobs.json": {"jobs"},
        }
        for f in archive:
            if f.path.startswith(ARCHIVE_ONLY_PREFIXES) or not f.path.endswith(".json"):
                continue
            body = f.parsed
            if body is None:
                continue
            if f.path in MODELLED_FILES:
                if f.path not in rest_keys or not isinstance(body, dict):
                    continue
                body = {k: v for k, v in body.items() if k not in rest_keys[f.path]}
                if f.path == "native_scout.json":
                    body["signals"] = [s for s in records(body.get("signals")) if s.get("origin") != "planner"]
                if not body:
                    continue
                key = f"{f.path}#rest"
            else:
                key = f.path
            self.t["documents"].append({"key": key, "body": _redact(body, f.path, secrets)})
        for f in archive:  # the raw archive can't be redacted: report anything that looks like a secret
            if f.parsed is not None:
                _redact(f.parsed, f"archive:{f.path}", secrets)
        return sorted(set(secrets))


def _redact(value: Any, where: str, found: list[str], path: str = "") -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if SECRET_KEY_PATTERN.search(str(k)) and isinstance(v, str) and v.strip():
                found.append(f"{where}:{path}/{k}")
                out[k] = "[redacted]"
            else:
                out[k] = _redact(v, where, found, f"{path}/{k}")
        return out
    if isinstance(value, list):
        return [_redact(v, where, found, f"{path}/{i}") for i, v in enumerate(value)]
    return value

"""Mappers for everything around candidates: machine proposals, people, events, spend, scheduler, documents."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from projectzero.events.columns import LEAD_DECISIONS, SPAN_PROBLEMS, event_columns, lead_columns
from projectzero.map.network import check_candidates
from projectzero.network.people import WEAK_KINDS, columns_of, identifiers_of
from projectzero.ops.legacy.convert import (
    BERLIN,
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

SIDES = ("start", "end")


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

    def _keyed(
        self, label: str, collection: Any, title: str
    ) -> tuple[list[tuple[str, dict[str, Any]]], list[Any], list[dict[str, Any]]]:
        """(id, record) pairs of a legacy collection, the people rule (review 012): a record without an ``id`` (or not
        a record) is skipped and listed; a repeated id is a blocker naming both records, and only the first is kept."""
        items = list(collection.values()) if isinstance(collection, dict) else collection
        items = items if isinstance(items, list) else []
        seen: dict[str, Any] = {}
        kept: list[tuple[str, dict[str, Any]]] = []
        skipped: list[dict[str, Any]] = []
        for position, r in enumerate(items):
            if not isinstance(r, dict) or r.get("id") in (None, ""):
                name = r.get(title) if isinstance(r, dict) else None
                why = "no id" if isinstance(r, dict) else "not a record"
                skipped.append({"position": position, title: name if isinstance(name, str) else None, "why": why})
                continue
            rid = str(r["id"])
            if rid in seen:
                self.identity_blockers.append(
                    f"{label} records {seen[rid]!r} and {r.get(title)!r} share the id {rid!r}: "
                    "the old app reached only the first; rename or merge one first"
                )
                continue
            seen[rid] = r.get(title)
            kept.append((rid, r))
        return kept, items, skipped

    def founder_calls(self) -> None:
        """``founder_calls.json`` (review 023): its records are mapped, in their ORIGINAL order, by
        ``pz.backfill_founder_calls()`` from the byte-exact archive (the apply calls it). Checked here first, by the
        backfill's own rules (``keyed_collections``), so a malformed file blocks the import before anything is
        written instead of failing the apply."""
        self._keyed_archive("founder_calls.json", ("companies", "founders", "calls"))

    def evaluations(self) -> None:
        """``evaluations.json`` (review 024): its sessions are mapped, in their ORIGINAL order, by
        ``pz.backfill_evaluations()`` from the byte-exact archive (the apply calls it). Checked here first, by the
        backfill's own rules (``keyed_collections``)."""
        self._keyed_archive("evaluations.json", ("sessions",))

    def source_network(self) -> None:
        """``sources/network.json`` (review 025, decision f): archived as is and read by the Map until the source
        network is ported. Checked here by the Map's own rules (``map.network.check_candidates``: the fields the city
        detail reads), so a new import never stores a candidate that would break it; each problem is a blocker."""
        path = "sources/network.json"
        if path not in self.src.paths():
            return
        usable, problems = check_candidates(self.src.json(path))
        self.identity_blockers.extend(f"{path}: {p}: fix it first" for p in problems)
        self.report["reconciliation"][path] = {"candidates_usable": len(usable)}

    def founder_radar(self) -> None:
        """``radar_companies.json`` / ``radar_research.json`` (review 026a): mapped, in their ORIGINAL order and with
        each record's own key order, by ``pz.backfill_founder_radar()`` from the byte-exact archives (the apply calls
        it). Checked here first by the backfill's rules; the records are keyed by name / domain and carry no id."""
        self._keyed_archive("radar_companies.json", ("companies",), own_id=False)
        self._keyed_archive("radar_research.json", ("domains",), own_id=False)

    def _keyed_archive(self, path: str, colls: tuple[str, ...], *, own_id: bool = True) -> None:
        if path not in self.src.paths():
            return
        problems, counts = keyed_collections(path, self.src.file(path).raw, colls, own_id=own_id)
        self.identity_blockers.extend(problems)
        if counts is not None:
            self.report["reconciliation"][path] = counts

    def content_log(self) -> None:
        """``content.json`` (review 020): its items are mapped by ``pz.backfill_content_items()`` from the archived
        document (the apply calls it), the ONE mapping the 0011 upgrade shares. Checked here first so a malformed log
        blocks the import before anything is written: the top level must be an object with an ``items`` list, and
        every item a record with a non-empty string ``id``, no id repeated. A JSON number is never coerced to text."""
        if "content.json" not in self.src.paths():
            return
        data = self.src.json("content.json")
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            self.identity_blockers.append('content.json: the top level must be an object with an "items" list')
            return
        seen: dict[str, int] = {}
        for position, item in enumerate(data["items"]):
            iid = item.get("id") if isinstance(item, dict) else None
            if not isinstance(iid, str) or iid == "":
                self.identity_blockers.append(
                    f"content.json item at position {position} is not a record with a non-empty string id "
                    f"(found {type(iid).__name__ if isinstance(item, dict) else type(item).__name__}): fix it first"
                )
            elif iid in seen:
                self.identity_blockers.append(
                    f"content.json items at positions {seen[iid]} and {position} share the id {iid!r}: "
                    "the old app edited only the first; rename one first"
                )
            else:
                seen[iid] = position
        self.report["reconciliation"]["content.json"] = {"items": len(data["items"])}

    def events(self) -> None:
        """``events.json`` -> events + event_leads (review 014).

        Ids follow the people rule (``_keyed``). Dates are the old ``parse_when`` / ``event_span``
        (``events.when``) at the Berlin date of the import clock; the columns are ``events.columns`` (the ONE mapping
        the Events writes will share). ``created_at`` is the old ``created`` (a day or a timestamp), else a valid
        ``retrieved_at`` (naive = Berlin), else the import time, each source counted. A span that overflows or does
        not run forward in UTC (``columns.checked_span``) blocks the import, naming the event; that row is not written.
        """
        data = self.src.json("events.json", {}) or {}
        data = data if isinstance(data, dict) else {}
        today = self.now.astimezone(BERLIN).date()
        kept, items, skipped = self._keyed("events.json events", data.get("events"), "name")
        dates = {side: dict.fromkeys(("date_only", "timed", "unparseable", "absent", "free_text"), 0) for side in SIDES}
        why_unparseable: dict[str, int] = {}
        coords = {axis: dict.fromkeys(("kept", "kept_from_text", "dropped", "absent"), 0) for axis in ("lat", "lng")}
        created_from = dict.fromkeys(("created", "retrieved_at", "import_time"), 0)
        name_from_id = end_before_start = 0
        statuses: dict[str, int] = {}
        span_blocked: list[str] = []
        for eid, e in kept:
            mapped = event_columns(eid, e, today=today)
            notes = mapped.notes
            if notes["span_problem"]:
                span_blocked.append(eid)
                self.identity_blockers.append(
                    f"events.json event {eid!r} ({mapped.columns['name']!r}) states start {e.get('start')!r} and "
                    f"end {e.get('end')!r}: {SPAN_PROBLEMS[notes['span_problem']]}; fix its dates in the old app first"
                )
                continue
            for side in SIDES:
                s = notes[side]
                dates[side][s.kind] += 1
                dates[side]["free_text"] += int(s.free_text)
                if s.why:
                    why_unparseable[f"{side}: {s.why}"] = why_unparseable.get(f"{side}: {s.why}", 0) + 1
            for axis in ("lat", "lng"):
                coords[axis][notes[axis]] += 1
            name_from_id += int(notes["name_from_id"])
            end_before_start += int(notes["end_before_start"])
            status = mapped.columns["status"] if mapped.columns["status"] is not None else "(none)"
            statuses[status] = statuses.get(status, 0) + 1
            created, source = day(e.get("created")), "created"
            if created is None:
                created, source = timestamp(e.get("retrieved_at")), "retrieved_at"
            if created is None:
                created, source = self.now, "import_time"
            created_from[source] += 1
            self.t["events"].append({"id": eid, **mapped.columns, "legacy": e, "created_at": created})
        self.report["reconciliation"]["events.json"] = {
            "in": len(items),
            "rows": len(self.t["events"]),
            "skipped_without_id": skipped,
            "duplicate_ids_blocked": len(items) - len(skipped) - len(span_blocked) - len(self.t["events"]),
            "span_blocked": span_blocked,
            "dates": dates,
            "unparseable": dict(sorted(why_unparseable.items())),
            "end_before_start": end_before_start,
            "dates_clock": today.isoformat(),
            "created_at_from": created_from,
            "name_from_id": name_from_id,
            "coordinates": coords,
            "status": dict(sorted(statuses.items())),
        }
        self._leads(data.get("leads"), today)

    def _leads(self, collection: Any, today: date) -> None:
        kept, items, skipped = self._keyed("events.json leads", collection, "title")
        dates = dict.fromkeys(("date_only", "timed", "unparseable", "absent", "free_text"), 0)
        created_from_import_time = 0
        decisions: dict[str, int] = {}
        for lid, lead in kept:
            mapped = lead_columns(lead, today=today)
            decision = mapped.columns["decision"]
            if decision not in LEAD_DECISIONS:
                self.identity_blockers.append(
                    f"events.json lead {lid!r} has the decision {decision!r}, not one of {', '.join(LEAD_DECISIONS)}: "
                    "set it in the old app first"
                )
                continue
            decisions[decision] = decisions.get(decision, 0) + 1
            when = mapped.notes["date"]
            dates[when.kind] += 1
            dates["free_text"] += int(when.free_text)
            created = mapped.columns["detected_on"]
            created_from_import_time += int(created is None)
            self.t["event_leads"].append(
                {
                    "id": lid,
                    **mapped.columns,
                    "legacy": lead,
                    "created_at": datetime.combine(created, datetime.min.time(), BERLIN) if created else self.now,
                }
            )
        self.report["reconciliation"]["events.json leads"] = {
            "in": len(items),
            "rows": len(self.t["event_leads"]),
            "open": decisions.get("new", 0),
            "decisions": dict(sorted(decisions.items())),
            "skipped_without_id": skipped,
            "duplicate_ids_or_unknown_decisions_blocked": len(items) - len(skipped) - len(self.t["event_leads"]),
            "dates": dates,
            "created_at_from_import_time": created_from_import_time,
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
            "events.json": {"events", "leads"},
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
                if f.path == "scout_intake.json":
                    body = self._scout_event_ids(body)
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

    def _scout_event_ids(self, body: dict[str, Any]) -> dict[str, Any]:
        """Scout 00 event reports stay in ``scout_intake.json#rest``, but their ``event_id`` is the plain event id
        (review 014): the old ``events.upsert`` returned ``"<id>|merged:<name>"`` when it folded the report into an
        existing event, and every old reader split the suffix off (``event_scout.by_event``). ``legacy_documents``
        keeps the original bytes."""
        stripped = 0

        def plain(report: Any) -> Any:
            nonlocal stripped
            eid = report.get("event_id") if isinstance(report, dict) else None
            if isinstance(eid, str) and "|" in eid:
                stripped += 1
                return report | {"event_id": eid.split("|")[0]}
            return report

        reports = body.get("events")
        if isinstance(reports, dict):
            body = body | {"events": {k: plain(v) for k, v in reports.items()}}
        elif isinstance(reports, list):
            body = body | {"events": [plain(v) for v in reports]}
        self.report["reconciliation"].setdefault("scout_intake.json", {})["event_id_merge_suffixes_stripped"] = stripped
        return body


class _Pairs(list[tuple[str, Any]]):
    """A JSON object as its key/value pairs in file order, repeated keys included (``json`` keeps them all)."""


def keyed_collections(
    path: str, raw: bytes, colls: tuple[str, ...], *, own_id: bool = True
) -> tuple[list[str], dict[str, int] | None]:
    """The rules of the archive backfills that map id-keyed objects in their raw order (0014 founder calls, 0015
    evaluator sessions), applied to the SAME bytes, so the preview blocks exactly what the apply would reject:

    * the top level must be an object;
    * each collection, when the key is present, must be an object (an explicit ``null`` is NOT absent: the backfill
      rejects it), with no key repeated;
    * each record must be an object under a non-empty key, whose ``id``, when present, is that key as text
      (``own_id=False``: records keyed by a name or domain that carry no id of their own, 0016).

    Returns (the blockers, the record count per present collection; None when the top level is unusable)."""
    try:
        top = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_Pairs)
    except (UnicodeDecodeError, ValueError):
        return [f"{path}: not readable JSON"], None
    if not isinstance(top, _Pairs):
        return [f"{path}: the top level must be an object"], None
    fields = dict(top)  # a repeated top-level key: the last one counts, as in the backfill's json operators
    problems: list[str] = []
    counts: dict[str, int] = {}
    for coll in colls:
        if coll not in fields:
            continue
        recs = fields[coll]
        if not isinstance(recs, _Pairs):
            problems.append(f'{path}: "{coll}" must be an object keyed by id (it is {_json_kind(recs)})')
            continue
        seen: set[str] = set()
        for key, rec in recs:
            if key in seen:
                problems.append(f"{path} {coll} id {key!r} is repeated: fix it first")
            seen.add(key)
            rid = (dict(rec).get("id", key) if own_id else key) if isinstance(rec, _Pairs) else None
            if key == "" or not isinstance(rec, _Pairs) or rid != key:
                problems.append(f"{path} {coll} record {key!r} is not a record keyed by its own id: fix it first")
        counts[coll] = len(seen)
    return problems, counts


def _json_kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, list):
        return "an array"
    return {str: "a string", bool: "a boolean"}.get(type(value), "a number")


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

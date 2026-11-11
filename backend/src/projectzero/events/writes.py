"""Events writes on ``pz`` (review 016), each in the caller's ONE transaction. The rules are ``events.edits``.

* nothing is written into ``pz`` before the legacy import's marker exists (``ensure_intake_open``);
* ONE lock order everywhere: the events advisory lock (``<schema>.events``) -> the affected event / lead rows -> the
  people lock and person rows (debrief, through ``network.store``) -> the intake lock (debrief leads, through
  ``dealflow.intake``) -> the ``scout_intake.json#rest`` document row (Scout 00 actions; Monitor / Ignore take only
  this one);
* the current record is written whole into ``attrs.record`` (``legacy`` is never changed); the typed columns and the
  flattened ``attrs`` mirror it through ``events.columns``. A start / end the write did not change keeps its STORED
  date and time (a free-text date is never re-resolved by an unrelated edit, Codex H-107); a changed side is resolved
  with the request's Berlin date, and a span that would not run forward (or overflows) is refused (400) before
  anything is written;
* every write that changes a record appends an ``event_history`` row (event or lead target); a Scout 00 Monitor /
  Ignore is audited in the locked report's own ``history`` instead (the documented exception of migration 0008);
* a lead conversion (the save + the lead's decision) is ONE transaction; a retry after a lost response finds the
  recorded conversion and answers it again instead of creating a second event.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from projectzero.core.db import schema_ident
from projectzero.dealflow.intake.contract import Origin, cross_entity_issues, validate_entity
from projectzero.dealflow.intake.postgres import PostgresIntake, ensure_intake_open
from projectzero.dealflow.intake.service import IntakeService, TrustedBatch
from projectzero.events import edits
from projectzero.events.columns import SPAN_PROBLEMS, event_columns, lead_columns, stored_stated
from projectzero.events.edits import EventsError
from projectzero.events.store import record_of
from projectzero.events.when import BERLIN, Stated
from projectzero.network.edits import NetworkError
from projectzero.network.store import PeopleStore, changes
from projectzero.network.view import berlin_today

SCOUT_DOC = "scout_intake.json#rest"
NO_EVIDENCE = (
    "startup lead {which} has no public evidence URL: give the lead a URL or add the event's URL first — nothing was "
    "saved"
)
LEAD_REFUSED = "startup lead {which} was refused by Deal Flow intake ({issues}) — nothing was saved"

_EVENT_ROWS = """
    with arch as (
        select (e.value->>'id') as id, min(e.ord) as pos
        from {s}.legacy_documents d, jsonb_array_elements(d.parsed->'events') with ordinality as e(value, ord)
        where d.path = 'events.json' and jsonb_typeof(d.parsed->'events') = 'array'
        group by 1
    )
    select t.* from {s}.events t left join arch a on a.id = t.id
    order by a.pos nulls last, t.created_at, t.id
"""


def _stamp(now: datetime) -> str:
    return now.astimezone(BERLIN).strftime("%Y-%m-%d %H:%M")


class EventsWriter:
    def __init__(self, conn: psycopg.Connection[Any], schema: str, now: datetime) -> None:
        self.conn = conn
        self._schema = schema
        self.now = now if now.tzinfo else now.replace(tzinfo=BERLIN)
        self.today: date = berlin_today(self.now)

    # ── plumbing ────────────────────────────────────────────────────────────────────────────────────────────────
    def _q(self, query: str) -> sql.Composed:
        return sql.SQL(query).format(s=schema_ident(self._schema))

    def _rows(self, query: str, params: Any = ()) -> list[dict[str, Any]]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(self._q(query), params)
            return cur.fetchall() if cur.description else []

    def _lock(self) -> None:
        ensure_intake_open(self.conn, self._schema)
        self._rows("select pg_advisory_xact_lock(hashtext(%s))", (f"{self._schema}.events",))

    def _events(self) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
        """Every event (records and rows by id, and the stored order), read under the events lock."""
        rows = self._rows(_EVENT_ROWS)
        by_row = {str(r["id"]): r for r in rows}
        return {eid: record_of(r) for eid, r in by_row.items()}, by_row, list(by_row)

    def _lock_event(self, eid: str) -> dict[str, Any] | None:
        rows = self._rows("select * from {s}.events where id = %s for update", (eid,))
        return rows[0] if rows else None

    def _lock_lead(self, lid: str) -> dict[str, Any] | None:
        rows = self._rows("select * from {s}.event_leads where id = %s for update", (lid,))
        return rows[0] if rows else None

    def _history(self, *, event_id: str | None = None, lead_id: str | None = None, action: str, before: Any,
                 after: Any, detail: Mapping[str, Any]) -> None:  # fmt: skip
        self._rows(
            "insert into {s}.event_history (event_id, lead_id, actor, action, before, after, detail) "
            "values (%s, %s, 'operator', %s, %s, %s, %s)",
            (event_id, lead_id, action, None if before is None else Jsonb(before), Jsonb(after), Jsonb(dict(detail))),
        )

    # ── the mirrored event write ────────────────────────────────────────────────────────────────────────────────
    def _kept(
        self, before: Mapping[str, Any] | None, record: Mapping[str, Any], row: Mapping[str, Any] | None
    ) -> dict[str, Stated]:
        """The sides the write did not change, as stored (their date / time columns govern)."""
        if before is None or row is None:
            return {}
        return {
            side: stored_stated(record.get(side), row.get(f"{side}_date"), row.get(f"{side}_time"))
            for side in ("start", "end")
            if record.get(side) == before.get(side)
        }

    def _write_event(
        self,
        eid: str,
        before: dict[str, Any] | None,
        row: dict[str, Any] | None,
        record: dict[str, Any],
        action: str,
        detail: Mapping[str, Any],
        *,
        record_unchanged: bool = False,
    ) -> bool:
        """Write ``record`` as the event's current record (insert when ``before`` is None), mirror it, and append the
        history row. Returns False (nothing written) when an existing record did not change, unless
        ``record_unchanged``: then the history row alone is written (a debrief note for a person already linked has no
        other home, Codex H-109)."""
        if before is not None:
            old_b, new_a = changes(before, record)
            if not new_a:
                if record_unchanged:  # nothing of the event changed, but the write carries what only history keeps
                    self._history(event_id=eid, action=action, before={}, after={}, detail=detail)
                    return True
                return False
        mapped = event_columns(eid, record, today=self.today, kept=self._kept(before, record, row))
        if problem := mapped.notes["span_problem"]:
            raise EventsError(
                400, f"the event's dates do not make a span: {SPAN_PROBLEMS[problem]} — nothing was saved"
            )
        c = mapped.columns
        attrs = {**c["attrs"], "record": record}
        cols = ("name", "starts_at", "ends_at", "start_date", "start_time", "end_date", "end_time", "city", "country",
                "url", "status", "lat", "lng")  # fmt: skip
        values = (*(c[k] for k in cols), Jsonb(attrs))
        if before is None:
            self._rows(
                "insert into {s}.events (id, name, starts_at, ends_at, start_date, start_time, end_date, end_time, "
                "city, country, url, status, lat, lng, attrs, created_at) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, clock_timestamp())",
                (eid, *values),
            )
            self._history(event_id=eid, action="create" if action in ("save", "create") else action, before=None,
                          after=record, detail=detail)  # fmt: skip
        else:
            self._rows(
                "update {s}.events set name = %s, starts_at = %s, ends_at = %s, start_date = %s, start_time = %s, "
                "end_date = %s, end_time = %s, city = %s, country = %s, url = %s, status = %s, lat = %s, lng = %s, "
                "attrs = %s, updated_at = now() where id = %s",
                (*values, eid),
            )
            self._history(event_id=eid, action=action, before=old_b, after=new_a, detail=detail)
        return True

    def _save_locked(
        self, body: Mapping[str, Any], action: str | None = None, extra: Mapping[str, Any] | None = None
    ) -> tuple[str, str]:
        """The old ``upsert`` under the events lock: ``(event id, merged-into name)``."""
        detail = dict(extra or {})
        by_id, _rows, order = self._events()
        kind, eid, merged_into = edits.plan_save(body, by_id, order)
        fields = sorted(k for k in body if k in edits.EVENT_FIELDS)
        if kind == "create":
            record = edits.new_event(eid, self.today)
            edits.apply_fields(record, body, self.today)
            self._write_event(eid, None, None, record, action or "create", {**detail, "fields": fields})
            return eid, ""
        row = self._lock_event(eid)
        assert row is not None  # under the events lock: it was just read
        before = record_of(row)
        record = copy.deepcopy(before)
        if kind == "merge":
            edits.merge_into(record, body, self.today)
            edits.fill_coordinates(record)
            self._write_event(
                eid, before, row, record, action or "merge", {**detail, "fields": fields, "merged_into": merged_into}
            )
            return eid, merged_into
        edits.apply_fields(record, body, self.today)
        self._write_event(eid, before, row, record, action or "save", {**detail, "fields": fields})
        return eid, ""

    # ── writes ──────────────────────────────────────────────────────────────────────────────────────────────────
    def save(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """The old ``event_save``; with ``convert_lead`` the lead's conversion in the SAME transaction (H-107)."""
        edits.validate_save(body)
        lead_id = body.get("convert_lead")
        save_body = {k: v for k, v in body.items() if k != "convert_lead"}
        self._lock()
        lead_row = None
        if lead_id:
            lead_row = self._lock_lead(str(lead_id))
            if lead_row is None:
                raise EventsError(404, edits.UNKNOWN_LEAD, id=lead_id)
            done = self._rows(
                "select detail->>'answer' as answer from {s}.event_history where lead_id = %s and action = 'convert' "
                "order by id desc limit 1",
                (lead_id,),
            )
            if done and record_of(lead_row).get("decision") == "converted":
                return {"ok": True, "id": done[0]["answer"], "replayed": True}  # a retry: the conversion is recorded
        eid, merged_into = self._save_locked(save_body)
        answer = edits.answer_id(eid, merged_into)
        if lead_row is not None:
            self._decide_lead(lead_row, "converted", "convert", {"event_id": eid, "answer": answer})
        return {"ok": True, "id": answer}

    def verify(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """The old ``event_verify``: an unknown id answers ``{ok: false}`` (f)."""
        self._lock()
        eid = body.get("id")
        row = self._lock_event(eid) if isinstance(eid, str) else None
        if row is None:
            return {"ok": False}
        before = record_of(row)
        record = copy.deepcopy(before)
        edits.apply_verify(record, body, _stamp(self.now))
        self._write_event(str(eid), before, row, record, "verify", {"verified": record["human_verified"]})
        return {"ok": True}

    def _decide_lead(self, row: dict[str, Any], decision: str, action: str, detail: Mapping[str, Any]) -> None:
        before = record_of(row)
        record = copy.deepcopy(before)
        record["decision"] = decision
        old_b, new_a = changes(before, record)
        mapped = lead_columns(record, today=self.today)
        attrs = {**mapped.columns["attrs"], "record": record}
        # only the decision and the record change: the stored date columns are kept as they are
        self._rows(
            "update {s}.event_leads set decision = %s, attrs = %s, updated_at = now() where id = %s",
            (decision, Jsonb(attrs), row["id"]),
        )
        after = new_a or {"decision": decision}
        self._history(lead_id=str(row["id"]), action=action, before=old_b or None, after=after, detail=detail)

    def lead(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """The old ``event_lead``: a decision outside the vocabulary is a 400, an unknown lead a 404 (e)."""
        decision = edits.lead_decision(body)
        self._lock()
        lid = body.get("id")
        row = self._lock_lead(lid) if isinstance(lid, str) else None
        if row is None:
            raise EventsError(404, edits.UNKNOWN_LEAD, id=lid)
        self._decide_lead(row, decision, "lead_decision", {})
        return {"ok": True}

    def debrief(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """The old ``event_debrief`` in ONE transaction: people met (created, or linked without overwriting, (c)), the
        startup leads through Deal Flow intake ((d), refused as a whole before any write), the event's record."""
        people_met, leads = edits.validate_debrief(body)
        eid = body.get("id")
        if not isinstance(eid, str):
            raise EventsError(404, edits.UNKNOWN_EVENT, id=eid)
        self._lock()
        row = self._lock_event(eid)
        if row is None:
            raise EventsError(404, edits.UNKNOWN_EVENT, id=eid)
        before = record_of(row)
        named = [ld for ld in leads if (ld.get("name") or "").strip()]
        entities = edits.lead_entities(before, leads, self.today)
        self._refuse_bad_leads(named, entities)
        people = PeopleStore(self.conn, self._schema)
        met: list[tuple[str, Mapping[str, Any], str]] = []  # (person id, the entry, created | linked)
        for pm in people_met:
            pbody = edits.person_body(before, pm, self.today)
            if not pbody["name"]:
                continue
            try:
                met.append((str(people.save(pbody, self.now)["id"]), pm, "created"))
            except NetworkError as exc:
                if exc.status != 409 or not exc.extra.get("duplicate"):
                    raise
                pid = str(exc.extra["id"])  # (c) already in the network: link, never overwrite the introduction
                people.save({"id": pid, "last_interaction": self.today.isoformat()}, self.now)
                met.append((pid, pm, "linked"))
        person_ids = [pid for pid, _, _ in met]
        intake: dict[str, Any] = {}
        if entities:
            store = PostgresIntake(self.conn, self._schema)
            result = IntakeService(store, resolver=store).submit_trusted(
                TrustedBatch(Origin.EVENT_DEBRIEF, "operator", entities, external_ref=f"event-debrief:{eid}")
            )
            intake = {"outcome": result.outcome, "sha256": result.sha256, "accepted": result.accepted}
        record = copy.deepcopy(before)
        edits.apply_debrief(record, person_ids, body.get("notes", ""))
        detail = {
            "people": [{"id": pid, "outcome": how} for pid, _, how in met],
            # the note of a person already in the network is kept here, never written over their own notes (c)
            "linked_notes": {pid: pm.get("note") for pid, pm, how in met if how == "linked" and pm.get("note")},
            "leads": len(entities),
            "intake": intake,
        }
        self._write_event(eid, before, row, record, "debrief", detail, record_unchanged=bool(detail["linked_notes"]))
        new_leads = 0 if intake.get("outcome") in (None, "duplicate") else int(intake.get("accepted", 0))
        return {"ok": True, "people": person_ids, "leads": new_leads}

    def _refuse_bad_leads(self, named: list[dict[str, Any]], entities: list[dict[str, Any]]) -> None:
        """Validate the WHOLE batch through the intake contract before anything is written (Codex H-107)."""
        for i, (ld, entity) in enumerate(zip(named, entities, strict=True)):
            which = f"{i + 1} ({(ld.get('name') or '').strip()})"
            if not entity["evidence"]:
                raise EventsError(400, NO_EVIDENCE.format(which=which), lead=i)
            if issues := validate_entity(entity, prefix=f"$/leads/{i}"):
                raise EventsError(400, LEAD_REFUSED.format(which=which, issues="; ".join(map(str, issues))), lead=i)
        for i, issues in cross_entity_issues(entities).items():
            which = f"{i + 1} ({(named[i].get('name') or '').strip()})"
            raise EventsError(400, LEAD_REFUSED.format(which=which, issues="; ".join(map(str, issues))), lead=i)

    def scout(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """The old ``scout_event``: one Scout 00 report. Add saves through the save (its merge) under the events
        lock; Monitor / Ignore change only the report (its own history is the audit)."""
        rid, act = body.get("id"), body.get("action")
        if act == "add":
            self._lock()
        else:
            ensure_intake_open(self.conn, self._schema)
        docs = self._rows("select body from {s}.documents where key = %s for update", (SCOUT_DOC,))
        doc = docs[0]["body"] if docs else None
        reports = doc.get("events") if isinstance(doc, dict) else None
        items = list(reports.values()) if isinstance(reports, dict) else reports if isinstance(reports, list) else []
        report = next((x for x in items if isinstance(x, dict) and x.get("id") == rid), None)
        if report is None:
            return {"ok": False, "error": edits.UNKNOWN_SCOUT}
        if act not in edits.SCOUT_STATUS:
            return {"ok": False, "error": edits.UNKNOWN_SCOUT_ACTION}
        prev = report.get("status")
        answer = ""
        if act == "add":
            eid, merged_into = self._save_locked(edits.scout_add_body(report), "scout_add", {"scout_report_ids": [rid]})
            report["event_id"] = eid  # the plain id (review 014 G10: never the old "|merged:" suffix)
            answer = edits.answer_id(eid, merged_into)
        report["status"] = edits.SCOUT_STATUS[str(act)]
        report.setdefault("history", []).append(
            {"on": _stamp(self.now), "from": prev, "to": report["status"], "note": "operator"}
        )
        self._rows("update {s}.documents set body = %s, updated_at = now() where key = %s", (Jsonb(doc), SCOUT_DOC))
        return {
            "ok": True,
            "status": report["status"],
            "event_id": answer if act == "add" else report.get("event_id", ""),
        }

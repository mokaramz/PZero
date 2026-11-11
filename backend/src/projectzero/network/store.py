"""Network people reads and writes on ``pz`` (review 013).

**Read** — ``load_people`` is the ONE reader of the people table (Conviction's IMQ inputs use it too): every row's
current record (``network.people.record_of``: ``attrs.record`` once written here, else ``legacy``) in the old
``people.json`` order: the archived file order, then people created here by ``created_at``, then ``id``. The views
(``network.view``) are computed from it with the request's clock. Reads never write.

**Writes** — ``save`` (the old ``person_save``), ``talented`` (``add_talented``) and ``watch_log``, each in the
caller's ONE transaction:

* nothing is written into ``pz`` before the legacy import's marker exists (``ensure_intake_open``, the boundary intake
  and Conviction use);
* every write takes the people advisory lock (``<schema>.people``) first, so people writers run one after another and
  a concurrent add of one id, or two introducers recommending one new person, are decided under the lock; then it
  locks every affected person row, sorted by id (``select ... order by id for update``): one lock order everywhere;
* the current record is written whole into ``attrs.record`` (``legacy`` is never changed); the typed columns, the
  flattened ``attrs`` and ``person_identifiers`` mirror it by the importer's rules (``columns_of`` /
  ``identifiers_of``); a strong identifier another person holds refuses the WHOLE write (409) — one this person's
  previous record already asserted (the import reported it and stored it for the first person only) stays unstored;
  the strong-unique index is the last line of defence (the router maps it to the same 409, after the rollback);
* every write that changes a record appends a ``person_events`` row (operator, action, the changed fields
  before -> after; the whole record on create);
* a person created here gets ``created_at = clock_timestamp()``, so people created by one request keep the order the
  old file appended them in.

The write rules and the deliberate changes from the old code are in ``network.edits``. Errors: ``NetworkError``.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from projectzero.core.db import schema_ident
from projectzero.dealflow.intake.postgres import ensure_intake_open
from projectzero.network import edits, view
from projectzero.network.edits import NetworkError
from projectzero.network.people import WEAK_KINDS, columns_of, distinct_identifiers, record_of, slug

_PEOPLE = """
    with arch as (
        select (e.value->>'id') as id, min(e.ord) as pos
        from {s}.legacy_documents d, jsonb_array_elements(d.parsed->'people') with ordinality as e(value, ord)
        where d.path = 'people.json' and jsonb_typeof(d.parsed->'people') = 'array'
        group by 1
    )
    select p.id, p.name, p.country, p.identity_status, p.founder_status, p.radar_state, p.attrs, p.legacy
    from {s}.people p left join arch a on a.id = p.id
    order by a.pos nulls last, p.created_at, p.id
"""


def load_people(conn: psycopg.Connection[Any], schema: str) -> list[dict[str, Any]]:
    """Every person's current record, in the old ``people.json`` order (see the module docstring)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL(_PEOPLE).format(s=schema_ident(schema)))
        return [record_of(r) for r in cur.fetchall()]


def changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The top-level fields a write changed: (before, after); a field that did not exist reads as None before."""
    keys = [k for k in after if k not in before or before[k] != after[k]]
    keys += [k for k in before if k not in after]
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}


class PeopleStore:
    def __init__(self, conn: psycopg.Connection[Any], schema: str = "pz") -> None:
        self.conn = conn
        self._schema = schema
        self.s = schema_ident(schema)

    def _rows(self, query: str, params: Any = ()) -> list[dict[str, Any]]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql.SQL(query).format(s=self.s), params)
            return list(cur.fetchall()) if cur.description else []

    # ── read ────────────────────────────────────────────────────────────────────────────────────────────────────
    def records(self) -> list[dict[str, Any]]:
        return load_people(self.conn, self._schema)

    def people_view(self, now: datetime) -> dict[str, Any]:
        return view.people_view(self.records(), view.berlin_today(now))

    def watchlist_view(self, now: datetime) -> dict[str, Any]:
        return view.watchlist_view(self.records(), view.berlin_today(now))

    def graph_view(self) -> dict[str, Any]:
        return view.graph_view(self.records())

    # ── locks ───────────────────────────────────────────────────────────────────────────────────────────────────
    def _lock(self) -> None:
        ensure_intake_open(self.conn, self._schema)  # the production write boundary: nothing before the import
        self._rows("select pg_advisory_xact_lock(hashtext(%s))", (f"{self._schema}.people",))

    def _lock_rows(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """Lock the existing rows among ``ids`` in id order (the one lock order) and return them by id."""
        rows = self._rows("select * from {s}.people where id = any(%s) order by id for update", (sorted(set(ids)),))
        return {str(r["id"]): r for r in rows}

    # ── the mirrored write ──────────────────────────────────────────────────────────────────────────────────────
    def _refuse_strong_conflicts(
        self, pid: str, before: Mapping[str, Any] | None, record: Mapping[str, Any]
    ) -> set[tuple[str, str]]:
        """409 when the record asserts a strong identifier another person holds and the person's previous record did
        not (a NEW conflict). Returns the pre-existing conflicts, which stay unstored (the import's rule)."""
        strong = [(k, v) for k, v in distinct_identifiers(dict(record)) if k not in WEAK_KINDS]
        if not strong:
            return set()
        held = self._rows(
            "select kind, value, person_id from {s}.person_identifiers where strength = 'strong' and person_id <> %s "
            "and (kind, value) in (select * from unnest(%s::text[], %s::text[]))",
            (pid, [k for k, _ in strong], [v for _, v in strong]),
        )
        previous = set(distinct_identifiers(dict(before))) if before is not None else set()
        kept: set[tuple[str, str]] = set()
        for h in held:
            key = (str(h["kind"]), str(h["value"]))
            if key in previous:
                kept.add(key)
                continue
            raise NetworkError(
                409,
                edits.IDENTIFIER_TAKEN.format(kind=key[0], value=key[1], owner=h["person_id"]),
                identifier={"kind": key[0], "value": key[1]},
                owner=str(h["person_id"]),
            )
        return kept

    def _sync_identifiers(self, pid: str, record: Mapping[str, Any], unstored: set[tuple[str, str]]) -> None:
        """``person_identifiers`` = the record's identifiers (one row per kind and value), minus ``unstored``. Rows
        that stay are not touched (their ids survive a partial edit)."""
        want = [i for i in distinct_identifiers(dict(record)) if i not in unstored]
        have = self._rows("select id, kind, value from {s}.person_identifiers where person_id = %s", (pid,))
        have_keys = {(str(r["kind"]), str(r["value"])): r["id"] for r in have}
        gone = [rid for key, rid in have_keys.items() if key not in set(want)]
        if gone:
            self._rows("delete from {s}.person_identifiers where id = any(%s)", (gone,))
        for kind, value in want:
            if (kind, value) not in have_keys:
                self._rows(
                    "insert into {s}.person_identifiers (person_id, kind, value) values (%s, %s, %s)",
                    (pid, kind, value),
                )

    def _event(self, pid: str, action: str, before: Any, after: Any, detail: Mapping[str, Any]) -> None:
        self._rows(
            "insert into {s}.person_events (person_id, actor, action, before, after, detail) "
            "values (%s, 'operator', %s, %s, %s, %s)",
            (pid, action, None if before is None else Jsonb(before), Jsonb(after), Jsonb(dict(detail))),
        )

    def _write(
        self,
        pid: str,
        before: dict[str, Any] | None,
        record: dict[str, Any],
        action: str,
        detail: Mapping[str, Any],
    ) -> bool:
        """Write ``record`` as the person's current record (insert when ``before`` is None), mirror it, and append
        the event. Returns False (nothing written) when an existing record did not change."""
        if before is not None:
            old_b, new_a = changes(before, record)
            if not new_a:
                return False
        unstored = self._refuse_strong_conflicts(pid, before, record)
        cols = columns_of(pid, record)
        attrs = {**cols["attrs"], "record": record}
        values = (cols["name"], cols["normalized_name"], cols["country"], cols["identity_status"],
                  cols["founder_status"], cols["radar_state"], Jsonb(attrs))  # fmt: skip
        if before is None:
            self._rows(
                "insert into {s}.people (id, name, normalized_name, country, identity_status, founder_status, "
                "radar_state, attrs, created_at) values (%s, %s, %s, %s, %s, %s, %s, %s, clock_timestamp())",
                (pid, *values),
            )
        else:
            self._rows(
                "update {s}.people set name = %s, normalized_name = %s, country = %s, identity_status = %s, "
                "founder_status = %s, radar_state = %s, attrs = %s where id = %s",
                (*values, pid),
            )
        self._sync_identifiers(pid, record, unstored)
        if before is None:
            self._event(pid, "create", None, record, detail)
        else:
            self._event(pid, action, old_b, new_a, detail)
        return True

    # ── writes ──────────────────────────────────────────────────────────────────────────────────────────────────
    def save(self, body: Mapping[str, Any], now: datetime) -> dict[str, Any]:
        """Add (no ``id``) or edit (``id``): the old ``person_save`` -> ``operator_save`` -> ``upsert``, with (a)."""
        edits.validate_save(body)
        today = view.berlin_today(now)
        self._lock()
        fields = sorted(k for k in body if k in edits.FIELDS)
        if body.get("id"):
            pid = str(body["id"])
            row = self._lock_rows([pid]).get(pid)
            if row is None:  # (a) an edit never creates a person
                raise NetworkError(404, edits.UNKNOWN, id=pid)
            before = record_of(row)
            if edits.is_radar_rename(before, body, row.get("legacy")):  # the durable imported origin (H-091)
                raise NetworkError(409, edits.RADAR_NAME, id=pid, radar_name=True)
            record = copy.deepcopy(before)
            edits.apply_save(record, body)
            self._write(pid, before, record, "save", {"fields": fields})
            return {"ok": True, "id": pid}
        pid = slug(str(body.get("name") or ""))
        if self._lock_rows([pid]):  # (a) the generated id is taken: never overwrite that person
            raise NetworkError(409, edits.DUPLICATE, id=pid, duplicate=True)
        record = edits.new_record(pid, today)
        edits.apply_save(record, body)
        self._write(pid, None, record, "create", {"fields": fields, "via": "person_save"})
        return {"ok": True, "id": pid}

    def talented(self, body: Mapping[str, Any], now: datetime) -> dict[str, Any]:
        """The '3 most talented people you know?' ritual (old ``add_talented``, decision (b))."""
        persons = edits.validate_talented(body)
        host_id = body.get("id")
        if not host_id:
            return {"ok": True, "created": []}  # the old code: no such introducer, nothing happens
        host_id = str(host_id)
        today = view.berlin_today(now)
        self._lock()
        rows = self._lock_rows(edits.ritual_ids(host_id, persons))
        if host_id not in rows:
            return {"ok": True, "created": []}
        before = {pid: record_of(r) for pid, r in rows.items()}
        work = {pid: copy.deepcopy(rec) for pid, rec in before.items()}
        created, records, notes = edits.apply_talented(host_id, persons, work.get, today)
        for pid in dict.fromkeys([host_id, *created]):  # new people in the order the old file appended them
            detail: dict[str, Any] = {"ritual": "3 most talented", "introducer": host_id, **notes.get(pid, {})}
            if pid == host_id:  # the introducer's event keeps every recommendation, incl. a note no record took
                detail["role"] = "introducer"
                detail["named"] = created
                kept = {k: v["introduction_kept"] for k, v in notes.items() if "introduction_kept" in v}
                if kept:
                    detail["introductions_kept"] = kept
                    detail["notes"] = {k: v["note"] for k, v in notes.items() if "note" in v}
            self._write(pid, before.get(pid), records[pid], "talented", detail)
        return {"ok": True, "created": created}

    def watch_log(self, body: Mapping[str, Any], now: datetime) -> dict[str, Any]:
        """The Watchlist's signal log (old ``/api/watch_log``): an unknown id changes nothing, as before."""
        edits.validate_watch_log(body)
        pid = body.get("id")
        if not pid:
            return {"ok": True}
        pid = str(pid)
        self._lock()
        row = self._lock_rows([pid]).get(pid)
        if row is None:
            return {"ok": True}
        before = record_of(row)
        record = copy.deepcopy(before)
        edits.apply_watch_log(record, body.get("note"), view.berlin_today(now))
        self._write(pid, before, record, "watch_log", {"note": body.get("note") or ""})
        return {"ok": True}

"""Conviction reads and writes on ``pz`` (review 011).

**Where today's record lives.** ``conviction_entries.attrs.record`` holds the WHOLE current record (the old
``real_data.json`` signal shape) once the new app has written the entry; until then ``legacy`` (the imported record,
never changed) is the record. The columns ``slug`` / ``status`` / ``verified`` / ``scores`` mirror it on every write.

**Read** — ``pipeline_view``: the old ``GET /api/pipeline`` (``conviction.pipeline.build``), order = the archived
``real_data.json`` signal order, then entries created here by ``created_at``. Reads never write (decision a).

**Writes** — ``save`` (old ``save_entry``) and ``set_status`` (old ``set_status``), each in the caller's ONE transaction:

* every write first takes the intake advisory lock (``<schema>.intake``), so Conviction writers run one after another
  and a concurrent create / Keep of the same slug is decided under the lock (the loser gets 409 + the slug). Then, for a
  Keep, the candidate's company row and the candidate row (``DealFlowStore.lock_for_keep``: the one lock order);
* the server score is authoritative: nothing the client computed is stored; ``sc`` / ``imq_eval`` are derived on read;
* the IMQ snapshot is persisted on the written entry (``imq.persist`` at the write's clock), so a transition caused by
  time alone is stamped once, by the next write;
* every write that changes something appends a ``conviction_events`` row (operator, action, changed fields before ->
  after); a Keep also writes the candidate's ``kept`` status event with the feedback snapshot (``DealFlowStore.keep``).

Old side effects NOT ported: ``case_prep.request`` (no-op, decision b), the source-yield vote
``connectors.registry_yield`` and the funnel milestones ``discovery.milestone(cx, "kept")`` (``q_milestones`` on the
inbox record) — the source-yield / quality context reads candidate events later. Errors: ``ConvictionError``.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from projectzero.conviction import entries, imq, operator, pipeline, radar, weekly
from projectzero.conviction.inputs import load_inputs
from projectzero.core.db import schema_ident
from projectzero.dealflow.candidates import DealFlowStore
from projectzero.dealflow.identity import normalize_name
from projectzero.dealflow.inbox_view import candidate_rows
from projectzero.dealflow.intake.postgres import ensure_intake_open
from projectzero.dealflow.ranking.names import norm_company
from projectzero.dealflow.ranking.names import slug as radar_slug
from projectzero.dealflow.ranking.service import ranking_input
from projectzero.events import store as events_store
from projectzero.network.store import load_people
from projectzero.network.view import berlin_today

DUPLICATE = "a company with this name already exists — open it in Conviction to edit it"
KEEP_REASON = "Keep — scored in Conviction"
CONFLICTING_LINK = "this Conviction entry belongs to another Deal Flow lead or company — nothing was changed"

_ENTRIES = """
    with arch as (
        select (e.value->>'company') as company, e.ord
        from {s}.legacy_documents d, jsonb_array_elements(d.parsed->'signals') with ordinality as e(value, ord)
        where d.path = 'real_data.json' and jsonb_typeof(d.parsed->'signals') = 'array'
          and jsonb_typeof(e.value) = 'object'
    )
    select ce.id, ce.slug, ce.company_id, ce.candidate_id, ce.status, ce.attrs, ce.legacy, ce.created_at,
           (select array_agg(a.company order by a.ord) from arch a) as archived
    from {s}.conviction_entries ce
"""


class ConvictionError(ValueError):
    def __init__(self, status: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.extra = extra


def record_of(row: dict[str, Any]) -> dict[str, Any]:
    """Today's record of an entry row (see the module docstring)."""
    attrs = row.get("attrs") or {}
    rec = attrs.get("record") if isinstance(attrs, dict) else None
    if isinstance(rec, dict):
        return rec
    legacy = row.get("legacy")
    return legacy if isinstance(legacy, dict) else {}


def ordered(rows: list[dict[str, Any]], archived: list[Any]) -> list[dict[str, Any]]:
    """The archived ``real_data.json`` order (by the imported record's slug), then new entries by creation."""
    pos: dict[str, int] = {}
    for i, company in enumerate(archived):
        if company not in (None, ""):
            pos.setdefault(radar_slug(str(company)), i)

    def key(r: dict[str, Any]) -> tuple[int, int, Any, str]:
        legacy = r.get("legacy")
        p = pos.get(radar_slug(str(legacy.get("company") or ""))) if isinstance(legacy, dict) else None
        return (0 if p is not None else 1, p or 0, r["created_at"], str(r["id"]))

    return sorted(rows, key=key)


class ConvictionStore:
    def __init__(self, conn: psycopg.Connection[Any], schema: str = "pz") -> None:
        self.conn = conn
        self._schema = schema
        self.s = schema_ident(schema)

    def _rows(self, query: str, params: Any = ()) -> list[dict[str, Any]]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql.SQL(query).format(s=self.s), params)
            return list(cur.fetchall()) if cur.description else []

    def _first(self, query: str, params: Any = ()) -> dict[str, Any] | None:
        rows = self._rows(query, params)
        return rows[0] if rows else None

    # ── read ────────────────────────────────────────────────────────────────────────────────────────────────────
    def entry_rows(self) -> list[dict[str, Any]]:
        rows = self._rows(_ENTRIES)
        archived = (rows[0]["archived"] or []) if rows else []
        return ordered(rows, archived)

    def rest(self) -> dict[str, Any]:
        """``real_data.json`` without its signals (``week``, ``_note``, ...), as imported."""
        doc = self._first("select body from {s}.documents where key = 'real_data.json#rest'")
        body = (doc or {}).get("body")
        return dict(body) if isinstance(body, dict) else {"week": ""}  # the old default document when there is none

    def pipeline_view(self, now: datetime) -> dict[str, Any]:
        stored = [record_of(r) for r in self.entry_rows()]
        return pipeline.build(self.rest(), stored, load_inputs(self.conn, self._schema), now)

    def case_view(self, slug: str, now: datetime) -> dict[str, Any]:
        """The old ``GET /api/case``: the imported prepared case, read-only (decision b: nothing is prepared)."""
        inputs = load_inputs(self.conn, self._schema)
        stored = [record_of(r) for r in self.entry_rows()]
        view = pipeline.build(self.rest(), stored, inputs, now)["signals"]
        entry = next((e for e in view if e.get("slug") == slug), None)
        return operator.case_view(slug, entry, inputs.operator, now)

    # ── writes ──────────────────────────────────────────────────────────────────────────────────────────────────
    def _lock(self) -> None:
        ensure_intake_open(self.conn, self._schema)  # the production write boundary: nothing before the import
        self._rows("select pg_advisory_xact_lock(hashtext(%s))", (f"{self._schema}.intake",))

    def _entry_by_slug(self, slug: str) -> dict[str, Any] | None:
        return self._first("select * from {s}.conviction_entries where slug = %s", (slug,))

    def _persist_imq(self, record: dict[str, Any], now: datetime) -> dict[str, Any] | None:
        """``imq.persist`` on the record being written; returns the transition it stamped (or None)."""
        if not record.get("company"):
            return None
        before = copy.deepcopy(record.get("imq"))
        view = copy.deepcopy(record)
        try:
            ev = pipeline.enrich(view, load_inputs(self.conn, self._schema).imq, now)
        except Exception:  # an uninterpretable record is shown as UNKNOWN on read; there is no transition to stamp
            return None
        if not imq.persist(record, ev, now=now):
            return None
        return {"from": (before or {}).get("state"), "to": ev["state"]}

    def _event(
        self, entry_id: Any, slug: str, action: str, before: Any, after: Any, detail: dict[str, Any],
        actor: str = "operator",
    ) -> None:  # fmt: skip
        self._rows(
            "insert into {s}.conviction_events (entry_id, slug, actor, action, before, after, detail) "
            "values (%s, %s, %s, %s, %s, %s, %s)",
            (entry_id, slug, actor, action, None if before is None else Jsonb(before), Jsonb(after), Jsonb(detail)),
        )

    def _write_row(self, row: dict[str, Any], record: dict[str, Any], slug: str) -> None:
        scores = record.get("scores")
        verified = record.get("verified")
        self._rows(
            "update {s}.conviction_entries set slug = %s, status = %s, verified = %s, scores = %s, "
            "attrs = attrs || jsonb_build_object('record', %s::jsonb), candidate_id = %s where id = %s",
            (
                slug,
                str(record.get("status") or "new"),
                Jsonb({k: v for k, v in verified.items() if isinstance(v, bool)} if isinstance(verified, dict) else {}),
                Jsonb(scores if isinstance(scores, dict) else {"value": scores}),
                Jsonb(record),
                row.get("candidate_id"),
                row["id"],
            ),
        )

    def _name_match(self, company: str) -> tuple[dict[str, Any], str] | None:
        """Old save: a new entry without ``inbox_id`` still records the provenance of the FIRST Deal Flow candidate
        whose name matches (``norm_company``), in the old inbox order. Provenance only: the candidate is not decided,
        not linked, and its company is not reused."""
        nm = norm_company(company)
        for row in candidate_rows(self.conn, self._schema):
            c, _ = ranking_input(row)
            if norm_company(c.get("name", "")) == nm:
                return c, str(row["id"])
        return None

    def _new_company(self, record: dict[str, Any]) -> str:
        name = str(record["company"])
        row = self._first(
            "insert into {s}.companies (name, normalized_name, website, country, location, attrs) "
            "values (%s, %s, %s, %s, %s, %s) returning id",
            (
                name,
                normalize_name(name),
                record.get("website") if isinstance(record.get("website"), str) else None,
                record.get("country") if isinstance(record.get("country"), str) else None,
                record.get("location") if isinstance(record.get("location"), str) else None,
                Jsonb({"created_by": "conviction"}),
            ),
        )
        assert row is not None
        company_id = str(row["id"])
        if normalized := normalize_name(name):  # a weak name assertion, like intake: identity review can see it
            self._rows(
                "insert into {s}.company_identifiers (company_id, kind, namespace, value, source) "
                "values (%s, 'normalized_name', '', %s, 'conviction')",
                (company_id, normalized),
            )
        return company_id

    @staticmethod
    def _refuse_conflicting_link(row: dict[str, Any], candidate_id: str, locked: dict[str, Any] | None) -> None:
        """An existing entry edited with an ``inbox_id`` may only Keep ITS lead (review 011, Codex H-074).

        * linked entry: the resolved survivor must be the stored link (a repeat of its own Keep is fine);
        * unlinked entry: the candidate must belong to the entry's company.
        Anything else would decide another company's lead and credit its feedback to the wrong entry, so it is
        refused before the candidate, the ledger or the entry change.
        """
        linked = row.get("candidate_id")
        if linked:
            if str(linked) != candidate_id:
                raise ConvictionError(409, CONFLICTING_LINK, slug=row["slug"], linked_candidate=str(linked))
            return
        if (locked or {}).get("company_id") != row.get("company_id"):
            raise ConvictionError(409, CONFLICTING_LINK, slug=row["slug"])

    def save(self, body: dict[str, Any], now: datetime) -> dict[str, Any]:
        """Create or update an entry (Keep form / edit / checklist). Returns the old ``{ok, slug}`` (+ ``keep``)."""
        problems = entries.validate_entry(body, now.date())
        if problems:
            raise ConvictionError(400, entries.refusal(problems))
        self._lock()
        dealflow = DealFlowStore(self.conn, self._schema)
        candidate_id: str | None = None
        locked: dict[str, Any] | None = None
        if body.get("inbox_id"):  # a Keep names a real Deal Flow candidate — never linked by a name guess instead
            candidate_id = dealflow.resolve_id("candidate", str(body["inbox_id"]))
            if candidate_id is None:
                raise ConvictionError(404, "unknown Deal Flow candidate — nothing was saved")
            locked = dealflow.lock_for_keep(candidate_id)  # company row, then candidate row
        row = self._entry_by_slug(str(body["slug"])) if body.get("slug") else None
        if row is not None and candidate_id is not None:
            self._refuse_conflicting_link(row, candidate_id, locked)  # before any status change or event (H-074)
        new_entry = row is None
        if row is None and body.get("company"):  # an existing company is never duplicated by a slug-less save
            dup_slug = radar_slug(str(body["company"]))
            if self._entry_by_slug(dup_slug):
                raise ConvictionError(409, DUPLICATE, slug=dup_slug, duplicate=True)
        before = record_of(row) if row else {}
        record: dict[str, Any] = copy.deepcopy(before) if row else {"status": "new"}
        if new_entry and body.get("company"):
            try:
                if candidate_id is not None:
                    cand = self._first("select * from {s}.candidates where id = %s", (candidate_id,))
                    assert cand is not None
                    cx: tuple[dict[str, Any], str] | None = (ranking_input(cand)[0], candidate_id)
                else:
                    cx = self._name_match(str(body["company"]))
                if cx is not None:
                    entries.provenance(record, *cx)
            except psycopg.Error:
                raise
            except Exception:  # v1: provenance is best-effort and never blocks the save
                pass
        entries.apply_save(record, body)
        if not record.get("company"):
            raise ConvictionError(400, "company required")
        slug = radar_slug(str(record["company"]))
        if not new_entry and row is not None and slug != row["slug"] and self._entry_by_slug(slug):
            # a rename onto another entry's name: the old file would have held two records with one slug
            raise ConvictionError(409, DUPLICATE, slug=slug, duplicate=True)
        company_id: str | None = None
        if new_entry:
            company_id = (locked or {}).get("company_id")
            if company_id:
                taken = self._first("select slug from {s}.conviction_entries where company_id = %s", (company_id,))
                if taken:  # one entry per company (schema): the Keep opens the existing entry instead
                    raise ConvictionError(409, DUPLICATE, slug=taken["slug"], duplicate=True)
        transition = self._persist_imq(record, now)
        detail: dict[str, Any] = {"fields": sorted(k for k in body if k in (*entries.SAVE_FIELDS, "slug", "inbox_id"))}
        if transition:
            detail["imq"] = transition
        keep: dict[str, Any] | None = None
        if candidate_id is not None:
            keep = dealflow.keep(candidate_id, reason=KEEP_REASON, detail={"conviction_slug": slug})
            detail["keep"] = {"candidate_id": candidate_id, "changed": keep["changed"],
                              "previous_status": keep["previous_status"]}  # fmt: skip
        if new_entry:
            created = self._first(
                "insert into {s}.conviction_entries (company_id, candidate_id, slug, status, verified, scores, attrs) "
                "values (%s, %s, %s, 'new', '{{}}', '{{}}', '{{}}') returning id, candidate_id",
                (company_id or self._new_company(record), candidate_id, slug),
            )
            assert created is not None
            row = {"id": created["id"], "candidate_id": created["candidate_id"], "slug": slug}
            self._write_row(row, record, slug)
            self._event(row["id"], slug, "create", None, record, detail)
        else:
            assert row is not None
            link = candidate_id is not None and not row.get("candidate_id")
            if link:
                row["candidate_id"] = candidate_id
            old_b, new_a = entries.changes(before, record)
            if new_a or link or (keep is not None and keep["changed"]):
                self._write_row(row, record, slug)
                self._event(row["id"], slug, "save", old_b, new_a, detail)
        out: dict[str, Any] = {"ok": True, "slug": slug}
        if keep is not None:
            out["keep"] = keep
        return out

    def set_status(self, body: dict[str, Any], now: datetime) -> dict[str, Any]:
        if body.get("status") not in entries.STATUSES:
            raise ConvictionError(400, "status must be one of: " + ", ".join(entries.STATUSES))
        self._lock()
        row = self._entry_by_slug(str(body.get("slug") or ""))
        if row is None:
            raise ConvictionError(404, "unknown company — nothing was changed")
        before = record_of(row)
        record = copy.deepcopy(before)
        entries.apply_status(record, str(body["status"]), now)
        transition = self._persist_imq(record, now)
        old_b, new_a = entries.changes(before, record)
        if new_a:
            self._write_row(row, record, str(row["slug"]))
            detail: dict[str, Any] = {"status": body["status"]}
            if transition:
                detail["imq"] = transition
            self._event(row["id"], str(row["slug"]), "status", old_b, new_a, detail)
        return {"ok": True}

    def existing_slug(self, body: dict[str, Any]) -> str | None:
        """After a lost race (unique violation, the last line of defence): the slug of the entry that won."""
        if body.get("company") and (slug := radar_slug(str(body["company"]))) and self._entry_by_slug(slug):
            return slug
        if body.get("inbox_id"):
            cid = DealFlowStore(self.conn, self._schema).resolve_id("candidate", str(body["inbox_id"]))
            hit = self._first(
                "select e.slug from {s}.conviction_entries e join {s}.candidates c on c.company_id = e.company_id "
                "where c.id = %s",
                (cid,),
            )
            return str(hit["slug"]) if hit else None
        return None

    # ── the Radar, memos, emails and the weekly update (review 019) ────────────────────────────────────────────
    def signals(self, now: datetime) -> list[dict[str, Any]]:
        """The pipeline's signals (the old ``pipeline()["signals"]``), which the Radar, memos and emails read."""
        return list(self.pipeline_view(now)["signals"])

    @staticmethod
    def radar_of(signals: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], set[str]]:
        """The old ``radar_view`` body (``_`` keys stripped) and the slugs it places in the Top 10."""
        composed = radar.compose_radar(copy.deepcopy(signals))
        view = {k: [{kk: vv for kk, vv in e.items() if not kk.startswith("_")} for e in v] for k, v in composed.items()}
        placed = {radar_slug(str(e.get("company") or "")) for k in radar.RADAR_SLOTS for e in composed.get(k, [])}
        placed.discard("")
        return view, placed

    def _radar_due(self, placed: set[str]) -> list[dict[str, Any]]:
        """Entry rows the composition places that have no Radar milestone yet (the old loop's filter)."""
        due = []
        for row in self.entry_rows():
            record = record_of(row)
            company = record.get("company")
            if company in (None, "") or radar_slug(str(company)) not in placed:
                continue
            if "radar" not in (record.get("q_milestones") or []):
                due.append(row)
        return due

    def radar_due(self, placed: set[str]) -> bool:
        return bool(placed) and bool(self._radar_due(placed))

    def _legacy_radar_credits(self) -> set[Any]:
        """Old inbox candidate ids carrying the PRE-FIX (Keep-time) Radar credit: the imported ``inbox.json`` as the
        old ``credit_radar_milestones`` read it (by id; a later duplicate id wins, as in its dict)."""
        rows = self._rows(
            "select e.value->>'id' as id, e.value->'q_milestones' as qm "
            "from {s}.legacy_documents d, jsonb_array_elements(d.parsed->'candidates') with ordinality as e(value, ord) "
            "where d.path = 'inbox.json' and jsonb_typeof(d.parsed->'candidates') = 'array' "
            "and jsonb_typeof(e.value) = 'object' order by e.ord"
        )
        latest: dict[Any, Any] = {}
        for r in rows:
            latest[r["id"]] = r["qm"]
        return {i for i, qm in latest.items() if isinstance(qm, list) and "radar" in qm}

    def credit_radar(self, placed: set[str]) -> int:
        """The old ``credit_radar_milestones`` (review 019, decision a, Codex H-137): under the Conviction lock, every
        newly placed entry gains ``radar`` in ``q_milestones`` and ONE ``radar_milestone`` event with
        ``counted = bool(source_id) and not legacy_credit``. Re-checked under the lock, so a concurrent view adds
        nothing. Returns the counted credits (the old return value)."""
        if not placed:
            return 0
        self._lock()
        due = self._radar_due(placed)
        legacy = self._legacy_radar_credits() if due else set()
        counted_total = 0
        for row in due:
            before = record_of(row)
            record = copy.deepcopy(before)
            qm = record.setdefault("q_milestones", [])
            qm.append("radar")
            source_id = record.get("source_id")
            legacy_credit = record.get("inbox_id") in legacy
            counted = bool(source_id) and not legacy_credit
            self._write_row(row, record, str(row["slug"]))
            old_b, new_a = entries.changes(before, record)
            detail = {"source_id": source_id or None, "legacy_credit": legacy_credit, "counted": counted}
            self._event(row["id"], str(row["slug"]), "radar_milestone", old_b, new_a, detail, actor="system")
            counted_total += counted
        return counted_total

    def lock(self) -> None:
        """The one write lock (and the write boundary), for a caller that writes records through ``write_records``."""
        self._lock()

    def write_records(
        self, rows: list[dict[str, Any]], changes: Iterable[Any], action: str, detail: dict[str, Any], now: datetime
    ) -> int:
        """Store records another feature changed (review 024: ending an evaluator session, the why-now trigger).
        ``rows`` is ``entry_rows()`` as read under the lock; each change names its row by ``index`` and carries the
        whole new ``record``. The IMQ snapshot is persisted on each record as on every Conviction write; a record
        that ends up unchanged writes nothing. One ``conviction_events`` row per written record; returns their count."""
        written = 0
        for ch in changes:
            row = rows[ch.index]
            before = record_of(row)
            record = copy.deepcopy(ch.record)
            transition = self._persist_imq(record, now)
            old_b, new_a = entries.changes(before, record)
            if not new_a:
                continue
            self._write_row(row, record, str(row["slug"]))
            d = dict(detail)
            if transition:
                d["imq"] = transition
            self._event(row["id"], str(row["slug"]), action, old_b, new_a, d)
            written += 1
        return written

    def signal(self, slug: str, now: datetime) -> dict[str, Any] | None:
        """The old ``find_signal``: the pipeline signal with this slug."""
        return next((e for e in self.signals(now) if e["slug"] == slug), None)

    def weekly_text(self, body: dict[str, Any], now: datetime) -> str:
        """The old ``POST /api/weekly``: the stored records (not the enriched view), people and events; no write."""
        today = berlin_today(now)
        stored = [record_of(r) for r in self.entry_rows()]
        events = events_store.load(self.conn, self._schema, today, people=False).events
        return weekly.weekly_update(
            stored, load_people(self.conn, self._schema), events, today,
            str(body.get("insight", "") or ""), str(body.get("question", "") or ""),
        )  # fmt: skip

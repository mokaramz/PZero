"""Deal Flow read model and operator decisions — one candidate list for every origin (registry, Grok, Scout Intake,
Native Scout, manual).

* ``list_candidates`` — filters (status, origin, text), counts per status and origin, keyset paging. Default order is
  last observed first. The old attention ranking (Taste Map rules) is ported separately and will replace this order.
* Every list item and the detail carry ``ranking`` (attention_v2, themes, lens, feedback, inputs), computed on read
  by the protected rules (``dealflow.ranking``) with ONE context per request, so list and detail agree (review 006).
  The order is still the client's job, as in the old app.
* ``get_candidate`` — one candidate with its company, identifiers, observations, events, machine proposals, routing,
  committee reviews and every id it is known by. Any old id resolves (``candidate`` / ``scout_intake`` /
  ``native_scout`` namespaces), so legacy deep links keep working.
* ``decide`` — the operator changes a status. ``kept`` is refused: Keep is the scored Conviction workflow, never a
  bare flag (old rule E2); that workflow calls ``lock_for_keep`` / ``keep`` inside its own save transaction.
  Deciding the current status again changes nothing and says so. An optional ``expected_status`` guards against two
  tabs overwriting each other. Every change is one ``candidate_events`` row; source yield, feedback learning and case
  preparation will read those events instead of being side effects here.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from projectzero.core.db import schema_ident
from projectzero.dealflow.ranking import feedback, ledger
from projectzero.dealflow.ranking.service import STATUS_TO_DECISION, RankingContext, rank, ranking_input

STATUSES = ("new", "reviewing", "watch", "baseline", "rejected", "archived", "kept")
OPERATOR_STATUSES = frozenset({"new", "reviewing", "watch", "baseline", "rejected", "archived"})
CLOSED_STATUSES = frozenset({"rejected", "archived"})
ALIAS_NAMESPACES = ("candidate", "scout_intake", "native_scout")
MAX_PAGE = 200


class DecisionError(ValueError):
    def __init__(self, status: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.extra = extra


@dataclass(frozen=True)
class ListQuery:
    status: tuple[str, ...] = ()
    origin: tuple[str, ...] = ()
    text: str | None = None
    limit: int = 50
    cursor: str | None = None

    def __post_init__(self) -> None:
        unknown = [s for s in self.status if s not in STATUSES]
        if unknown:
            raise DecisionError(400, f"unknown status {unknown[0]!r}", allowed=list(STATUSES))
        if not 1 <= self.limit <= MAX_PAGE:
            raise DecisionError(400, f"limit must be between 1 and {MAX_PAGE}")


def like_literal(text: str) -> str:
    """Escape ``text`` for a LIKE pattern so it only matches itself. The backslash (LIKE's escape character) goes first,
    or a name containing one could lose characters and a trailing backslash would swallow the appended wildcard."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def validate_operator_status(status: str) -> None:
    """The statuses an operator may set. Raises before any database work, so bad requests never open a connection."""
    if status == "kept":
        raise DecisionError(
            409, "Keep goes through the scored Conviction workflow, not a status change", keep_via="conviction"
        )
    if status not in OPERATOR_STATUSES:
        raise DecisionError(400, f"unknown status {status!r}", allowed=sorted(OPERATOR_STATUSES))


def _encode_cursor(last_observed_at: datetime, candidate_id: str) -> str:
    raw = json.dumps([last_observed_at.isoformat(), candidate_id]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        at, candidate_id = json.loads(base64.urlsafe_b64decode(padded.encode()))
        datetime.fromisoformat(at)
        return str(at), str(candidate_id)
    except (ValueError, TypeError) as exc:
        raise DecisionError(400, "invalid cursor") from exc


def decision_sources(c: Mapping[str, Any]) -> dict[str, Any]:
    """The sources a decision credits, captured when it is made (review 021, Codex H-161): the yield vote goes to the
    candidate's ``source_id``, the funnel milestones to its ``quality_source_id`` (else ``source_id``), as the old
    ``decide`` / ``milestone`` read them from the inbox record at that moment. A later re-report that changes the
    candidate's provenance never moves a past vote or credit."""
    sid = c.get("source_id") if isinstance(c.get("source_id"), str) and c.get("source_id") else None
    qsid = (
        c.get("quality_source_id")
        if isinstance(c.get("quality_source_id"), str) and c.get("quality_source_id")
        else None
    )
    return {"source_id": sid, "quality_source_id": qsid or sid}


def decision_detail(row: Mapping[str, Any], status: str, alias_ids: Iterable[str]) -> dict[str, Any]:
    """The decision snapshot a status event carries (review 008 / 021, one source of truth since review 035d): the old
    ``record_decision`` (the ranking input as the row is now, the ledger keys = the candidate's own id, then the old
    ids merged into it) and the sources credited AT decision time (H-161). Pure: ``row`` is the candidate row,
    ``alias_ids`` its ``candidate`` aliases (its own id may be among them)."""
    c, _ = ranking_input(row)
    keys = ledger.ordered_keys(str(row["id"]), [str(a) for a in alias_ids])
    return {"feedback": ledger.decision_record(c, STATUS_TO_DECISION[status], keys), "sources": decision_sources(c)}


# review 035d: the batch confirm's audit rows, ONE statement each, in the eligible list's (request) order
_BATCH_EVENTS = (
    "insert into {s}.candidate_events (candidate_id, actor, action, from_status, to_status, reason, detail) "
    "select e.value->>'id', 'operator', 'status', %s, %s, %s, e.value->'detail' "
    "from jsonb_array_elements(%s::jsonb) with ordinality as e(value, ord) order by e.ord"
)


class DealFlowStore:
    def __init__(self, conn: psycopg.Connection[Any], schema: str = "pz") -> None:
        self.conn = conn
        self.s = schema_ident(schema)
        self._schema = schema

    @staticmethod
    def _ranking_row(item: dict[str, Any]) -> dict[str, Any]:
        """A list item carries the adapter's inputs under private keys; the detail row has them as real columns."""
        return item | {
            "legacy": item["_legacy"],
            "attrs": item["_attrs"],
            "primary_source_id": item["_primary_source_id"],
        }

    def _rows(self, query: str, params: Any = ()) -> list[dict[str, Any]]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql.SQL(query).format(s=self.s), params)
            return list(cur.fetchall())

    def _first(self, query: str, params: Any = ()) -> dict[str, Any] | None:
        rows = self._rows(query, params)
        return rows[0] if rows else None

    # ── list ────────────────────────────────────────────────────────────────────────────────────────────────────
    def list_candidates(self, q: ListQuery) -> dict[str, Any]:
        where = ["true"]
        params: list[Any] = []
        if q.status:
            where.append("c.status = any(%s)")
            params.append(list(q.status))
        if q.origin:
            where.append("c.origins && %s")
            params.append(list(q.origin))
        if q.text:
            where.append("(c.name ilike %s or co.name ilike %s or c.key_fact ilike %s or c.description ilike %s)")
            like = f"%{like_literal(q.text)}%"
            params += [like] * 4
        filters = " and ".join(where)
        page_where = filters
        page_params = list(params)
        if q.cursor:
            at, candidate_id = _decode_cursor(q.cursor)
            page_where += " and (c.last_observed_at, c.id) < (%s::timestamptz, %s)"
            page_params += [at, candidate_id]
        items = self._rows(
            f"""
            select c.id, c.name, c.subject_kind, c.status, c.legacy_status, c.origins, c.country, c.location,
                   c.description, c.why, c.key_fact, c.key_unknown, c.recommended_object_type, c.sectors,
                   c.first_seen_at, c.last_observed_at, c.decided_at, c.attrs->>'identity' as identity,
                   c.legacy as _legacy, c.attrs as _attrs, c.primary_source_id as _primary_source_id,
                   case when co.id is null then null else jsonb_build_object(
                     'id', co.id, 'name', co.name, 'website', co.website, 'country', co.country) end as company,
                   (select count(*) from {{s}}.observations o where o.candidate_id = c.id) as observations,
                   exists(select 1 from {{s}}.candidate_events e
                          where e.candidate_id = c.id and e.action = 'merge_suggested') as merge_suggested,
                   (select jsonb_build_object('proposal', t.proposal, 'model', t.model, 'proposed_at', t.proposed_at)
                      from {{s}}.triage_proposals t where t.candidate_id = c.id and t.is_current) as triage,
                   (select jsonb_build_object('state', r.state, 'priority', r.priority, 'reason', r.reason)
                      from {{s}}.candidate_routing r where r.candidate_id = c.id) as routing
            from {{s}}.candidates c left join {{s}}.companies co on co.id = c.company_id
            where {page_where}
            order by c.last_observed_at desc, c.id desc
            limit %s
            """,
            [*page_params, q.limit + 1],
        )
        more = len(items) > q.limit
        items = items[: q.limit]
        ctx = RankingContext.load(self.conn, self._schema)
        for item in items:
            item["ranking"] = rank(self._ranking_row(item), ctx)
            for private in ("_legacy", "_attrs", "_primary_source_id"):
                item.pop(private)
        counts = self._rows(
            f"""
            select 'status' as kind, c.status as key, count(*) as n
              from {{s}}.candidates c left join {{s}}.companies co on co.id = c.company_id where {filters} group by 2
            union all
            select 'origin', o, count(*)
              from {{s}}.candidates c left join {{s}}.companies co on co.id = c.company_id, unnest(c.origins) o
             where {filters} group by 2
            """,
            params + params,
        )
        return {
            "items": items,
            "next_cursor": _encode_cursor(items[-1]["last_observed_at"], items[-1]["id"]) if more else None,
            "counts": {
                "status": {r["key"]: r["n"] for r in counts if r["kind"] == "status"},
                "origin": {r["key"]: r["n"] for r in counts if r["kind"] == "origin"},
            },
        }

    # ── detail ──────────────────────────────────────────────────────────────────────────────────────────────────
    def resolve_id(self, namespace: str, alias_id: str) -> str | None:
        if namespace not in ALIAS_NAMESPACES:
            raise DecisionError(400, f"unknown id namespace {namespace!r}", allowed=list(ALIAS_NAMESPACES))
        rows = self._rows("select {s}.resolve_candidate(%s, %s) as id", (namespace, alias_id))
        resolved = rows[0]["id"] if rows else None
        if resolved:
            return str(resolved)
        if namespace == "candidate" and self._first("select id from {s}.candidates where id = %s", (alias_id,)):
            return alias_id  # a current id always resolves, even if its own alias row was never written
        return None

    def resolve_many(self, alias_ids: list[str]) -> dict[str, str | None]:
        """``resolve_id("candidate", ...)`` for many ids in two reads: each id's survivor, or ``None``."""
        rows = self._rows(
            "select alias_id, candidate_id from {s}.candidate_aliases where namespace = 'candidate' "
            "and alias_id = any(%s)",
            (list(alias_ids),),
        )
        found: dict[str, str | None] = {str(r["alias_id"]): str(r["candidate_id"]) for r in rows}
        rest = [i for i in alias_ids if i not in found]
        current = {str(r["id"]) for r in self._rows("select id from {s}.candidates where id = any(%s)", (rest,))}
        return {i: found.get(i) or (i if i in current else None) for i in alias_ids}

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        found = self._rows("select * from {s}.candidates where id = %s", (candidate_id,))
        if not found:
            return None
        candidate = found[0]
        company_id = candidate["company_id"]
        detail: dict[str, Any] = {"candidate": candidate}
        detail["ranking"] = rank(candidate, RankingContext.load(self.conn, self._schema))
        detail["company"] = (
            self._first("select * from {s}.companies where id = %s", (company_id,)) if company_id else None
        )
        detail["identifiers"] = (
            self._rows(
                "select kind, namespace, value, strength, source from {s}.company_identifiers "
                "where company_id = %s order by strength, kind, value",
                (company_id,),
            )
            if company_id
            else []
        )
        detail["known_ids"] = self._rows(
            "select namespace, alias_id, reason from {s}.candidate_aliases where candidate_id = %s order by 1, 2",
            (candidate_id,),
        )
        detail["observations"] = self._rows(
            "select id, origin, source_id, observed_at, url, title, evidence, payload, submission_id "
            "from {s}.observations where candidate_id = %s order by observed_at desc, id desc",
            (candidate_id,),
        )
        detail["events"] = self._rows(
            "select id, actor, action, from_status, to_status, reason, detail, at "
            "from {s}.candidate_events where candidate_id = %s order by at desc, id desc",
            (candidate_id,),
        )
        detail["triage"] = self._rows(
            "select proposal, status, model, veto_model, usd, is_current, proposed_at, detail "
            "from {s}.triage_proposals where candidate_id = %s order by is_current desc, proposed_at desc",
            (candidate_id,),
        )
        detail["routing"] = self._first("select * from {s}.candidate_routing where candidate_id = %s", (candidate_id,))
        detail["committee"] = self._rows(
            "select seat, model, verdict, detail, reviewed_at from {s}.committee_reviews "
            "where candidate_id = %s order by reviewed_at desc",
            (candidate_id,),
        )
        detail["conviction"] = (
            self._first(
                "select id, slug, status, verified from {s}.conviction_entries where company_id = %s", (company_id,)
            )
            if company_id
            else None
        )
        return detail

    def _guard_reopen(self, candidate_id: str, company_id: str) -> None:
        """A company has at most one open candidate (``candidates_one_open_per_company``). Reopening a closed one while
        a sibling is open is refused with the sibling's id. The caller already holds the company lock, so two reopen
        attempts on two closed siblings run one after the other: the second sees the first one open and is refused."""
        sibling = self._first(
            "select id, status from {s}.candidates where company_id = %s and id <> %s "
            "and status not in ('rejected', 'archived')",
            (company_id, candidate_id),
        )
        if sibling:
            raise DecisionError(
                409,
                "this company already has an open candidate; decide on that one, or close it first",
                open_candidate=sibling["id"],
                open_status=sibling["status"],
            )

    def _lock_candidate(self, candidate_id: str) -> dict[str, Any]:
        """Lock in the ONE order every writer uses: company row first, then candidate row (review 005 rev 2).

        Live intake re-reports lock the company, then the candidate; deciding must not take them the other way round,
        or the two could deadlock. The candidate's company is read without a lock, that company is locked, then the
        candidate is locked and re-read. If the company changed in between (a merge), the decision is refused with 409
        at once: retrying inside this transaction would request a new company lock while holding the candidate lock
        (review 005 rev 3). The caller's transaction rolls back, so nothing is written; the client simply retries.
        """
        peek = self._first("select company_id from {s}.candidates where id = %s", (candidate_id,))
        if peek is None:
            raise DecisionError(404, "candidate not found")
        if peek["company_id"]:
            self._rows("select id from {s}.companies where id = %s for update", (peek["company_id"],))
        row = self._first("select status, company_id from {s}.candidates where id = %s for update", (candidate_id,))
        if row is None:
            raise DecisionError(404, "candidate not found")
        if row["company_id"] != peek["company_id"]:
            raise DecisionError(409, "the candidate moved to another company meanwhile; reload and decide again")
        return row

    # ── decisions ───────────────────────────────────────────────────────────────────────────────────────────────
    def decide(
        self,
        candidate_id: str,
        status: str,
        *,
        reason: str | None = None,
        notes: str | None = None,
        expected_status: str | None = None,
        feedback_answer: bool = True,
    ) -> dict[str, Any]:
        """``feedback_answer=False`` leaves the answer's ``feedback`` out (``None``): a batch decides many candidates
        and answers none of them, so it skips that read; the event and its snapshot are the same."""
        validate_operator_status(status)
        locked = self._lock_candidate(candidate_id)
        current, company_id = locked["status"], locked["company_id"]  # re-read under both locks
        if expected_status is not None and expected_status != current:
            raise DecisionError(409, "the candidate changed meanwhile; reload and decide again", current=current)
        if company_id and current in CLOSED_STATUSES and status not in CLOSED_STATUSES:
            self._guard_reopen(candidate_id, company_id)
        changed: Literal[True, False] = current != status
        if changed:
            self._rows(
                "update {s}.candidates set status = %s, decided_at = now() where id = %s returning id",
                (status, candidate_id),
            )
        if notes is not None:
            self._rows(
                "update {s}.candidates set attrs = attrs || jsonb_build_object('notes', %s::text) where id = %s "
                "returning id",
                (notes, candidate_id),
            )
        # the old record_decision, captured at decision time (review 008): the ranking input as it is now
        row = self._rows("select * from {s}.candidates where id = %s", (candidate_id,))[0]
        c, _ = ranking_input(row)
        detail: dict[str, Any] = {"notes": notes} if notes is not None else {}
        if changed:
            aliases = self._rows(
                "select alias_id from {s}.candidate_aliases where namespace = 'candidate' and candidate_id = %s",
                (candidate_id,),
            )
            detail.update(decision_detail(row, status, [str(r["alias_id"]) for r in aliases]))
        if changed or notes is not None:
            self._rows(
                "insert into {s}.candidate_events "
                "(candidate_id, actor, action, from_status, to_status, reason, detail) "
                "values (%s, 'operator', %s, %s, %s, %s, %s) returning id",
                (
                    candidate_id,
                    "status" if changed else "note",
                    current,
                    status if changed else None,
                    reason,
                    Jsonb(detail),
                ),
            )
        fb = (
            feedback.for_candidate(c, RankingContext.load(self.conn, self._schema).table) if feedback_answer else None
        )  # the old decide response
        return {"id": candidate_id, "status": status, "previous_status": current, "changed": changed, "feedback": fb}

    # ── machine triage (review 035a) ────────────────────────────────────────────────────────────────────────────
    def lock_for_triage(self, candidate_id: str, expected_status: str | None = None) -> dict[str, Any]:
        """The one locked check of a triage decision, every verdict included (KEEP writes only its log line): the
        company row, then the candidate row (``_lock_candidate``: a 409 when the company moved meanwhile), then
        ``expected_status`` against the status read under both locks (the decision route's 409). Returns
        ``{status, company_id}``; a later ``decide`` in the same transaction re-takes the locks it holds (no-op)."""
        locked = self._lock_candidate(candidate_id)
        if expected_status is not None and expected_status != locked["status"]:
            raise DecisionError(
                409, "the candidate changed meanwhile; reload and decide again", current=locked["status"]
            )
        return locked

    def lock_for_triage_batch(self, candidate_ids: list[str]) -> dict[str, dict[str, Any]]:
        """A batch's locks in the ONE order across the whole batch (Codex H-347): every candidate's company is read
        without a lock, the DISTINCT companies are locked in company-id order, then the candidates in candidate-id
        order. A candidate whose company changed between the read and the lock refuses the whole batch with the
        decision writer's retryable 409 (nothing is written; the caller's transaction rolls back). A candidate with
        no company is locked at the candidate step only. Returns ``{id: {status, company_id}}`` read under the locks."""
        ids = sorted(set(candidate_ids))
        if not ids:
            return {}
        peek = {str(r["id"]): r["company_id"] for r in self._rows(
            "select id, company_id from {s}.candidates where id = any(%s)", (ids,))}  # fmt: skip
        companies = sorted({str(c) for c in peek.values() if c})
        if companies:
            self._rows("select id from {s}.companies where id = any(%s::uuid[]) order by id for update", (companies,))
        locked = {
            str(r["id"]): r
            for r in self._rows(
                "select id, status, company_id from {s}.candidates where id = any(%s) order by id for update", (ids,)
            )
        }
        for cid, row in locked.items():
            if row["company_id"] != peek.get(cid):
                raise DecisionError(409, "the candidate moved to another company meanwhile; reload and decide again")
        return {cid: {"status": r["status"], "company_id": r["company_id"]} for cid, r in locked.items()}

    def reject_new_batch(self, candidate_ids: list[str], *, reason: str) -> None:
        """Review 035d: ``new -> rejected`` for the batch confirm's eligible ids, with a FIXED number of statements
        whatever their number. The caller holds every lock (``lock_for_triage_batch``) and read eligibility under them,
        so every id is ``new``: no reopen guard applies (the decision only closes). One update, which must return
        exactly ``candidate_ids`` as a set with the same cardinality (anything else raises: the caller's transaction
        rolls back); one read of the updated rows and one of their aliases (the snapshot is built in memory by
        ``decision_detail``, as ``decide`` builds it); one insert of the status events in ``candidate_ids`` order (the
        request order: never sorted), each the event ``decide(id, "rejected", reason=reason)`` writes."""
        ids = list(candidate_ids)
        if not ids:
            return
        if len(set(ids)) != len(ids):
            raise RuntimeError("the batch holds the same candidate twice")
        updated = self._rows(
            "update {s}.candidates set status = 'rejected', decided_at = now() "
            "where id = any(%s) and status = 'new' returning id",
            (ids,),
        )
        got = [str(r["id"]) for r in updated]
        if len(got) != len(ids) or set(got) != set(ids):
            raise RuntimeError(f"the batch update changed {len(got)} of {len(ids)} locked candidates")
        rows = {str(r["id"]): r for r in self._rows("select * from {s}.candidates where id = any(%s)", (ids,))}
        aliases: dict[str, list[str]] = {}
        for r in self._rows(
            "select candidate_id, alias_id from {s}.candidate_aliases where namespace = 'candidate' "
            "and candidate_id = any(%s)",
            (ids,),
        ):
            aliases.setdefault(str(r["candidate_id"]), []).append(str(r["alias_id"]))
        events = [{"id": cid, "detail": decision_detail(rows[cid], "rejected", aliases.get(cid, []))} for cid in ids]
        self.conn.execute(sql.SQL(_BATCH_EVENTS).format(s=self.s), ("new", "rejected", reason, Jsonb(events)))

    # ── Keep (review 011) ───────────────────────────────────────────────────────────────────────────────────────
    def lock_for_keep(self, candidate_id: str) -> dict[str, Any]:
        """The first half of a scored Keep: company row, then candidate row (the one lock order), and the reopen
        guard, BEFORE the Conviction entry is written. Returns ``{status, company_id}`` read under both locks."""
        locked = self._lock_candidate(candidate_id)
        if locked["company_id"] and locked["status"] in CLOSED_STATUSES:
            self._guard_reopen(candidate_id, locked["company_id"])
        return locked

    def keep(self, candidate_id: str, *, reason: str, detail: dict[str, Any]) -> dict[str, Any]:
        """The status half of a scored Keep: the Conviction save (``conviction.store``) calls it in the SAME
        transaction as the entry write, after ``lock_for_keep``. The candidate becomes ``kept`` and the operator status
        event carries the decision snapshot (the old ``record_decision(c, "kept")``), so the effective feedback ledger
        counts it like every other decision. A candidate already ``kept`` records nothing: repeating a Keep is no new
        decision."""
        locked = self.lock_for_keep(candidate_id)  # already held by this transaction: no new lock, same order
        current = locked["status"]
        changed = current != "kept"
        if changed:
            self._rows(
                "update {s}.candidates set status = 'kept', decided_at = now() where id = %s returning id",
                (candidate_id,),
            )
        row = self._rows("select * from {s}.candidates where id = %s", (candidate_id,))[0]
        c, _ = ranking_input(row)
        if changed:
            aliases = self._rows(
                "select alias_id from {s}.candidate_aliases where namespace = 'candidate' and candidate_id = %s",
                (candidate_id,),
            )
            event = {**detail, **decision_detail(row, "kept", [str(r["alias_id"]) for r in aliases])}
            self._rows(
                "insert into {s}.candidate_events "
                "(candidate_id, actor, action, from_status, to_status, reason, detail) "
                "values (%s, 'operator', 'status', %s, 'kept', %s, %s) returning id",
                (candidate_id, current, reason, Jsonb(event)),
            )
        fb = feedback.for_candidate(c, RankingContext.load(self.conn, self._schema).table)
        return {"id": candidate_id, "status": "kept", "previous_status": current, "changed": changed, "feedback": fb}

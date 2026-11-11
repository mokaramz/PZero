"""From stored candidates to the old rules' inputs, and back to the four ranking blocks the Deal Flow view shows.

* ``ranking_input(row)`` builds the legacy-shaped dict the protected rules read.
  - **full**: the candidate was imported from the old Deal Flow (``legacy`` is an inbox record). The rules read that
    record exactly as the old app did, with today's operator notes (the old decide wrote ``notes`` into the record,
    so notes always fed the ranking text).
  - **full** too: a live Grok / manual lead tagged at intake (``attrs.tagging``, review 007). The rules read the
    stored old-scan-shaped record, with today's status and operator notes, exactly like an imported record.
  - **partial**: anything else — a Scout Intake / Native record, a pre-007 untagged lead, or an origin without a
    tagging mapping yet (registry scans until the scanner port). The stored columns are mapped onto the same
    fields, but the ingest tags (``archetype_hits``, ``noise``, ``priority``, ``discovery_tier``) are missing.
* ``RankingContext`` holds the two inputs that are not per candidate, loaded once per request, so the list and the
  detail paths read the SAME values: the old inbox's exact ``last_run`` (compared directly with ``run_id``) and the
  effective feedback ledger: the imported one plus every operator decision since (``ranking.ledger``, review 008).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypeGuard

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from projectzero.core.db import schema_ident
from projectzero.dealflow.ranking import attention, feedback, ledger, tagging, themes

STATUS_TO_DECISION = {"new": "new", "reviewing": "research", "watch": "watch", "baseline": "baseline",
                      "rejected": "rejected", "archived": "rejected", "kept": "kept"}  # fmt: skip
INBOX_MARKERS = ("decision", "discovery_tier", "source_id")  # keys every legacy Deal Flow record carries


@dataclass(frozen=True)
class RankingContext:
    last_run: Any
    ledger: Any  # the raw ledger document; None = no ledger (reads as empty, like a missing feedback.json)
    table: Mapping[str, Any]

    @classmethod
    def load(cls, conn: psycopg.Connection[Any], schema: str) -> RankingContext:
        s = schema_ident(schema)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                sql.SQL("select key, body from {}.documents where key in ('inbox.json#rest', 'feedback.json')").format(
                    s
                )
            )
            docs = {row["key"]: row["body"] for row in cur.fetchall()}
            cur.execute(sql.SQL("select raw from {}.legacy_documents where path = %s").format(s), (ledger.LEDGER_FILE,))
            archived = cur.fetchone()
            cur.execute(
                sql.SQL(
                    "select candidate_id, to_status, detail, at from {}.candidate_events "
                    "where actor = 'operator' and action = 'status' order by id"
                ).format(s)
            )
            events = cur.fetchall()
            missing = sorted({str(e["candidate_id"]) for e in events if not ledger.has_snapshot(e)})
            rows: dict[str, Mapping[str, Any]] = {}
            aliases: dict[str, list[str]] = {}
            if missing:  # pre-008 status events: rebuilt from the candidate's current inputs (review 008, H-058)
                cur.execute(sql.SQL("select * from {}.candidates where id = any(%s)").format(s), (missing,))
                rows = {str(r["id"]): r for r in cur.fetchall()}
                cur.execute(
                    sql.SQL(
                        "select candidate_id, alias_id from {}.candidate_aliases "
                        "where namespace = 'candidate' and candidate_id = any(%s)"
                    ).format(s),
                    (missing,),
                )
                for a in cur.fetchall():
                    aliases.setdefault(str(a["candidate_id"]), []).append(str(a["alias_id"]))
            events = backfill_snapshots(events, rows, aliases)
        inbox_rest = docs.get("inbox.json#rest") or {}
        base = ledger.parse_base(archived["raw"] if archived else None, docs.get("feedback.json"))
        effective = ledger.effective(base, events)
        return cls(last_run=inbox_rest.get("last_run"), ledger=effective, table=feedback.table(effective))


def backfill_snapshots(
    events: list[dict[str, Any]], rows: Mapping[str, Mapping[str, Any]], aliases: Mapping[str, list[str]]
) -> list[dict[str, Any]]:
    """Status events written before 008 carry no decision snapshot. Supply one from the recorded target status and the
    candidate's CURRENT ranking input and aliases (the compatibility fallback agreed in review 008). Events that carry
    a snapshot, including an explicitly empty source list, are left exactly as recorded."""
    out = []
    for ev in events:
        cid = str(ev["candidate_id"])
        if ledger.has_snapshot(ev) or cid not in rows or ev.get("to_status") not in STATUS_TO_DECISION:
            out.append(ev)
            continue
        c, _ = ranking_input(rows[cid])
        rec = ledger.decision_record(
            c, STATUS_TO_DECISION[str(ev["to_status"])], ledger.ordered_keys(cid, aliases.get(cid, []))
        )
        out.append({**ev, "detail": {**(ev.get("detail") or {}), "feedback": rec}})
    return out


def is_legacy_inbox_record(legacy: Any) -> TypeGuard[dict[str, Any]]:
    return isinstance(legacy, dict) and all(k in legacy for k in INBOX_MARKERS)


def ranking_input(row: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    attrs = row.get("attrs") or {}
    legacy = row.get("legacy")
    if is_legacy_inbox_record(legacy):
        c = dict(legacy)
        c["decision"] = STATUS_TO_DECISION.get(str(row.get("status")), c.get("decision"))
        if "notes" in attrs:
            c["notes"] = attrs["notes"]
        return c, "full"
    tags = attrs.get("tagging")
    if tagging.is_current(tags):
        c = dict(tags["record"])
        c["decision"] = STATUS_TO_DECISION.get(str(row.get("status")), "new")
        c["notes"] = attrs.get("notes", "")  # operator notes only: the generated auto-reject note is never stored
        return c, "full"
    c = {
        "id": row.get("id"),
        "name": row.get("name") or "",
        "description": row.get("description") or row.get("key_fact") or "",
        "notes": attrs.get("notes", ""),
        "why": [row["why"]] if row.get("why") else [],
        "sectors": list(row.get("sectors") or []),
        "source": ", ".join(row.get("origins") or []),
        "source_id": row.get("primary_source_id") or "",
        "decision": STATUS_TO_DECISION.get(str(row.get("status")), "new"),
    }
    return c, "partial"


def rank(row: Mapping[str, Any], ctx: RankingContext) -> dict[str, Any]:
    """The four blocks of the old ``/api/inbox`` candidate, computed on read, plus how complete the inputs were."""
    c, inputs = ranking_input(row)
    score, signals = themes.lens_signals(c)
    return {
        "attention_v2": attention.annotate_v31(c, ctx.last_run),
        "themes": themes.themes_for(c),
        "lens": {"score": score, "signals": signals},
        "feedback": feedback.for_candidate(c, ctx.table),
        "inputs": inputs,
    }

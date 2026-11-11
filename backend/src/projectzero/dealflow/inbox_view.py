"""The Deal Flow view's read model (review 009): the old ``GET /api/inbox`` payload, built from ``pz``.

The Deal Flow page keeps its protected client logic (``logic.ts``: workspaces, the top-15 Attention queue, filters,
counts), which reads the whole inbox at once and sorts it with STABLE sorts. So the payload is the old shape, and the
candidate ORDER is the old file order: ties then break exactly as before.

    {**inbox_rest, candidates: [{...ranking input, themes, lens, attention_v2, feedback}], themes, feedback_label,
     feedback_min_reviewed, feedback_cap, pipeline_label, ws_geos}

* ``inbox_rest`` is the imported ``inbox.json`` without its candidates (``documents['inbox.json#rest']``):
  ``last_run``, ``report``, ``last_summary``, ...
* every candidate of the merged Deal Flow (legacy Deal Flow, Scout Intake / Native survivors, live leads) is the
  ranking input the rules read (``ranking.service.ranking_input``) with today's status and notes, plus the four
  computed blocks. Its ``id`` is the candidate id (imported Deal Flow candidates kept their old ids).
* order: the position in the archived ``inbox.json`` (through merge aliases) first, then everything else by first
  sighting, then id.
* ``ws_geos``: the old base geo list plus every source's geo tags, in the archived ``sources.json`` order.

Not carried (the page never reads them): ``manual_sources``, ``pages``, ``feeds``. Added: ``pz_status`` per candidate
(the stored status; ``archived`` and ``rejected`` both read as the old ``rejected``), sent back as ``expected_status``.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from projectzero.core.db import schema_ident
from projectzero.dealflow import workspaces
from projectzero.dealflow.ranking import attention, feedback, themes
from projectzero.dealflow.ranking.service import RankingContext, ranking_input

PIPELINE_EXISTING_LABEL = "Existing pipeline — not discovered in this scan"
BASE_GEOS = ["DACH", "CH", "NORD", "BNL", "FR", "UK", "SEU", "EU", "US", "CA"]  # old connectors.GEOS

# A survivor takes the EARLIEST archived position among the inbox records that resolve to it (its own id, or an old
# inbox id merged into it through a 'candidate' alias), so merged records keep the old input order (review 009 #2).
_CANDIDATES = """
    with inbox as (
        select (e.value->>'id') as id, min(e.ord) as pos
        from {s}.legacy_documents d, jsonb_array_elements(d.parsed->'candidates') with ordinality as e(value, ord)
        where d.path = 'inbox.json' and jsonb_typeof(d.parsed->'candidates') = 'array'
        group by 1
    ), positions as (
        select coalesce(al.candidate_id, i.id) as candidate_id, min(i.pos) as pos
        from inbox i left join {s}.candidate_aliases al on al.namespace = 'candidate' and al.alias_id = i.id
        group by 1
    )
    select c.*, p.pos
    from {s}.candidates c left join positions p on p.candidate_id = c.id
    order by p.pos nulls last, c.first_seen_at, c.id
"""
_SOURCES = """
    select s.legacy, s.attrs, s.id, a.pos
    from {s}.sources s
    left join (
        select (e.value->>'id') as id, min(e.ord) as pos
        from {s}.legacy_documents d, jsonb_array_elements(d.parsed->'sources') with ordinality as e(value, ord)
        where d.path = 'sources.json' and jsonb_typeof(d.parsed->'sources') = 'array'
        group by 1
    ) a on a.id = s.id
    where s.kind <> 'legacy_stub'
    order by a.pos nulls last, s.id
"""


def _source_geo(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("legacy")
    legacy: dict[str, Any] = raw if isinstance(raw, dict) else {}
    return {"geo": legacy.get("geo") or (row.get("attrs") or {}).get("geo") or []}


def inbox_view(conn: psycopg.Connection[Any], schema: str) -> dict[str, Any]:
    s = schema_ident(schema)
    ctx = RankingContext.load(conn, schema)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL("select key, body from {}.documents where key = any(%s)").format(s),
                    (["inbox.json#rest", "workspace_geos.json"],))  # fmt: skip
        docs = {r["key"]: r["body"] for r in cur.fetchall()}
        cur.execute(sql.SQL(_CANDIDATES).format(s=s))
        rows = cur.fetchall()
        cur.execute(sql.SQL(_SOURCES).format(s=s))
        sources = [_source_geo(r) for r in cur.fetchall()]

    rest = docs.get("inbox.json#rest") or {}
    out: dict[str, Any] = {"report": [], **{k: v for k, v in rest.items() if k != "candidates"}}
    out["last_run"] = ctx.last_run
    candidates = []
    for row in rows:
        c, _ = ranking_input(row)
        c["id"] = row["id"]
        c["pz_status"] = row["status"]  # the stored status, for the decision's stale check (old names can't tell)
        score, signals = themes.lens_signals(c)
        candidates.append({
            **c,
            "themes": themes.themes_for(c),
            "lens": {"score": score, "signals": signals},
            "attention_v2": attention.annotate_v31(c, ctx.last_run),
            "feedback": feedback.for_candidate(c, ctx.table),
        })  # fmt: skip
    out["candidates"] = candidates
    out["themes"] = themes.THEMES
    out["feedback_label"] = feedback.LABEL
    out["feedback_min_reviewed"] = feedback.MIN_REVIEWED
    out["feedback_cap"] = feedback.CAP
    out["pipeline_label"] = PIPELINE_EXISTING_LABEL
    override = workspaces.parse_override(docs.get("workspace_geos.json") or {})
    out["ws_geos"] = workspaces.ws_geos(sources, BASE_GEOS, override)
    return out

"""ONE loader for everything the Conviction read side reads besides the entries (review 011).

Where each input comes from (what the legacy import stored):

| Old source | Read from | Why |
|---|---|---|
| ``people.json`` (founder identities, IMQ gate C) | ``people`` table through ``network.store.load_people``: the current record (``attrs.record`` once written, else ``legacy``; ``network.people.record_of``), in the archived ``people.json`` order, then newer rows by ``created_at``, then ``id`` | modelled table; IMQ takes the FIRST matching person, so file order matters |
| ``radar_companies.json`` (Founder Radar facts, IMQ gate E) | ``legacy_documents`` byte-exact, else ``documents`` | not modelled yet; the first name match wins, and jsonb loses key order |
| ``evaluations.json`` (contradictions, gate C; founder-call filter) | ``legacy_documents`` byte-exact, else ``documents`` | not modelled; session order = blocker order |
| ``founder_calls.json`` (calls, contact state) | ``legacy_documents`` byte-exact, else ``documents`` | not modelled; call ties keep file order |
| ``case_prep/cases.json`` (prepared case, next action) | ``legacy_documents`` byte-exact, else ``documents`` | case preparation is not ported (decision b) |
| ``config.json`` (outreach policy) | ``legacy_documents`` byte-exact, else ``documents`` | not modelled |
| ``watch/triggers.jsonl`` (re-open evidence) | ``legacy_documents`` | ``documents`` holds only ``.json`` files |
| ``case_prep/actions.jsonl`` (case audit, ``GET /case``) | ``legacy_documents`` | the same |

None of these files has a writer in the new system yet. When its context is ported, this loader switches to its tables.
Failure semantics are the old ones: radar companies / evaluations unreadable -> both read as empty (the old pipeline's
``try``); founder calls, cases and config are tolerant (unreadable -> empty); a missing file is its old default.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from projectzero.conviction.operator import OperatorInputs
from projectzero.conviction.pipeline import ImqInputs, Inputs
from projectzero.core.db import schema_ident
from projectzero.network.store import load_people  # the ONE people reader (review 013)

DOCS = ("radar_companies.json", "evaluations.json", "founder_calls.json", "case_prep/cases.json", "config.json")
TRIGGERS = "watch/triggers.jsonl"
ACTIONS = "case_prep/actions.jsonl"
JSONL = (TRIGGERS, ACTIONS)
_MISSING = object()


class _Unreadable:
    """A file that exists but does not parse (the old ``load_json`` raised, or fell back when tolerant)."""


UNREADABLE = _Unreadable()


def _parse(raw: bytes | memoryview) -> Any:
    try:
        return json.loads(bytes(raw).decode("utf-8"))  # the old json.load(encoding="utf-8"): a BOM is unreadable
    except (UnicodeDecodeError, ValueError):
        return UNREADABLE


def load_documents(conn: psycopg.Connection[Any], schema: str) -> dict[str, Any]:
    """path -> parsed value, UNREADABLE, or absent. The byte-exact archive wins (old key order)."""
    s = schema_ident(schema)
    out: dict[str, Any] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL("select key, body from {}.documents where key = any(%s)").format(s), (list(DOCS),))  # fmt: skip
        for r in cur.fetchall():
            out[r["key"]] = r["body"]
        cur.execute(
            sql.SQL("select path, raw from {}.legacy_documents where path = any(%s)").format(s), ([*DOCS, *JSONL],)
        )
        for r in cur.fetchall():
            out[r["path"]] = r["raw"] if r["path"] in JSONL else _parse(r["raw"])
    # review 023: founder calls are modelled; the current records (written by the Founder Calls page) are read through
    # the ONE shared reader, which keeps the archived order. A broken archive with no rows stays UNREADABLE.
    from projectzero.founder_calls.store import FounderCallsStore

    current = FounderCallsStore(conn, schema).load()
    if current is not None:
        out["founder_calls.json"] = current
    # review 024: evaluator sessions too, through their ONE shared reader (archived order, the old load() defaulting)
    from projectzero.evaluator.store import EvaluationsStore

    sessions = EvaluationsStore(conn, schema).load()
    if sessions is not None:
        out["evaluations.json"] = sessions
    # review 026a: Founder Radar companies too (IMQ gate E, the evaluator's research facts), through their ONE reader
    from projectzero.founder_radar.store import FounderRadarStore

    companies = FounderRadarStore(conn, schema).load_companies()
    if companies is not None:
        out["radar_companies.json"] = companies
    return out


def _tolerant(doc: Any, default: Any) -> Any:
    return default if doc is _MISSING or doc is UNREADABLE else doc


def _jsonl(raw: Any) -> list[dict[str, Any]]:
    if raw is _MISSING:
        return []
    try:
        text = bytes(raw).decode("utf-8")
    except UnicodeDecodeError:
        return []  # the old storage.read_text: unreadable -> ""
    out = []
    for line in text.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def inputs_from(docs: dict[str, Any], people: list[dict[str, Any]]) -> Inputs:
    """The pure part (also used by the oracle comparison and the offline tests)."""
    radar = docs.get("radar_companies.json", _MISSING)
    evals = docs.get("evaluations.json", _MISSING)
    try:  # the old pipeline: founder-radar / evaluator state is optional; either failing resets both
        if radar is UNREADABLE or evals is UNREADABLE:
            raise ValueError("unreadable")
        comps = ({"companies": {}} if radar is _MISSING else radar).get("companies", {})
        evd = {} if evals is _MISSING else evals
        evd.setdefault("sessions", {})
    except Exception:
        comps, evd = {}, {"sessions": {}}
    cases_doc = _tolerant(docs.get("case_prep/cases.json", _MISSING), {}) or {}
    cases = cases_doc.get("cases") if isinstance(cases_doc, dict) else None
    operator = OperatorInputs(
        cases=cases if isinstance(cases, dict) else {},
        founder_calls=_tolerant(docs.get("founder_calls.json", _MISSING), {}) or {},
        evaluations=_tolerant(evals, {}) or {},
        watch_events=_jsonl(docs.get(TRIGGERS, _MISSING)),
        config=_tolerant(docs.get("config.json", _MISSING), {}) or {},
        case_actions=_jsonl(docs.get(ACTIONS, _MISSING)),
    )
    return Inputs(imq=ImqInputs(people=people, radar_companies=comps, evaluations=evd), operator=operator)


def load_inputs(conn: psycopg.Connection[Any], schema: str) -> Inputs:
    return inputs_from(load_documents(conn, schema), load_people(conn, schema))

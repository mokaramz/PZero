"""The database side of the Map (review 025): ``load(conn, schema, now, for_pins=False) -> MapInputs``, in ONE read
transaction.

The Map writes nothing (decision a). Every store is read once, in the old ORDER:

* through ``EcosystemsStore.snapshot`` (the reads the coverage needs, shared): the Deal Flow candidates as the old
  inbox records in the inbox order, the stored source registry, the Conviction records (file order), the people, the
  Events listing (with its pins) and the coverage inputs with the recorded adoptions;
* the CURRENT triage proposals, re-keyed by the inbox records' ids (the old ``triage_proposals.json`` was keyed by the
  inbox id);
* the frozen, byte-exact archives in their KEY order (decision b): ``scout_intake.json`` (merged into Deal Flow),
  ``news/events.json`` and ``sources/network.json`` (until their own ports), ``watch/triggers.jsonl``;
* ``config.json`` as Conviction reads it (the byte-exact archive first: the ``home_base`` key order) and
  ``ecosystems.json`` from ``documents``.

The archives go through the same tolerant old-format reading as the goldens (``inputs_from_docs``); the source network
through ``check_candidates`` (decision f: an already-imported malformed archive keeps its usable candidates, and the
answer's note names the rest). Scout cards link to their archived item (decision d: Deal Flow resolves the old Scout
Intake id). ``for_pins``: only what the pins read (no coverage, proposals or archives).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from projectzero.core.db import schema_ident
from projectzero.dealflow.ranking.service import ranking_input
from projectzero.dealflow.triage.view import proposal_record
from projectzero.ecosystems.store import EcosystemsStore
from projectzero.map.inputs_model import MapInputs, coverage_of, inputs_from_docs
from projectzero.network import view as people_view
from projectzero.network.view import berlin_today

ARCHIVES = ("scout_intake.json", "news/events.json", "sources/network.json")
WATCH = "watch/triggers.jsonl"
DOCUMENTS = ("config.json", "ecosystems.json")
CONFIG = "config.json"
_PROPOSALS = (
    "select distinct on (candidate_id) * from {}.triage_proposals "
    "order by candidate_id, is_current desc, proposed_at desc, id desc"
)


RETIRED_ORIGINS = frozenset({"legacy_scout00", "legacy_native"})  # imported from the retired Scout views only


def _old_inbox(row: dict[str, Any]) -> bool:
    """Decision (i): the Deal Flow layer is what the old ``inbox.json`` held plus what intake added since. Candidates
    imported ONLY from the retired Scout views (Scout Intake, native scout) are left out: the old Map never read native
    scout items, and Scout 00 items are already its archived Scout layer (counting them twice would change states)."""
    origins = row.get("origins") or []
    return not origins or not set(origins) <= RETIRED_ORIGINS


def _parse(raw: Any) -> Any:
    """An archived JSON file, decoded as the importer reads it (``utf-8-sig``: an optional leading BOM, Codex H-201),
    with its key order kept; genuinely unreadable -> ``None`` (each consumer then applies its old default)."""
    try:
        return json.loads(_text(raw, strict=True))
    except (UnicodeDecodeError, ValueError):
        return None


def _text(raw: Any, *, strict: bool = False) -> str:
    """An archived text file, decoded as the importer reads it (``utf-8-sig``), so a BOM never hides the first JSONL
    record; undecodable -> ``""`` (``strict``: raise instead)."""
    try:
        return bytes(raw).decode("utf-8-sig")
    except UnicodeDecodeError:
        if strict:
            raise
        return ""


def load(conn: psycopg.Connection[Any], schema: str, now: datetime, *, for_pins: bool = False) -> MapInputs:
    today = berlin_today(now)
    s = schema_ident(schema)
    snap = EcosystemsStore(conn, schema).snapshot(now)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL("select key, body from {}.documents where key = any(%s)").format(s), (list(DOCUMENTS),))
        documents = {r["key"]: r["body"] for r in cur.fetchall()}
        paths = [CONFIG] if for_pins else [CONFIG, *ARCHIVES, WATCH]
        cur.execute(sql.SQL("select path, raw from {}.legacy_documents where path = any(%s)").format(s), (paths,))
        archived: dict[str, Any] = {r["path"]: r["raw"] for r in cur.fetchall()}
        proposal_rows: dict[str, dict[str, Any]] = {}
        if not for_pins:
            cur.execute(sql.SQL(_PROPOSALS).format(s))
            proposal_rows = {str(r["candidate_id"]): proposal_record(r) for r in cur.fetchall()}

    inbox: list[dict[str, Any]] = []
    proposals: dict[str, Any] = {}
    for row in snap.candidate_rows:
        if not _old_inbox(row):
            continue
        c, _ = ranking_input(row)
        c.setdefault("id", row["id"])
        inbox.append(c)
        p = proposal_rows.get(str(row["id"]))
        if p is not None:
            proposals[str(c["id"])] = p

    # the byte-exact archive first (the old key order of ``home_base``), else the stored document (Conviction's rule)
    config = _parse(archived[CONFIG]) if CONFIG in archived else documents.get(CONFIG)
    home_base = config.get("home_base") if isinstance(config, dict) else None
    if for_pins:
        return MapInputs(inbox=inbox, signals=snap.inputs.signals, events=list(snap.listing),
                         people=_listing(snap.inputs.people, today), home_base=home_base)  # fmt: skip

    docs: dict[str, Any] = {
        "inbox.json": {"candidates": inbox},
        "triage_proposals.json": {"proposals": proposals},
        "sources.json": {"sources": snap.stored_sources},
        "real_data.json": {"signals": snap.inputs.signals},
        "people.json": {"people": snap.inputs.people},
        WATCH: _text(archived[WATCH]) if WATCH in archived else "",
    }
    for path in ARCHIVES:
        if path in archived:
            docs[path] = _parse(archived[path])
    if "ecosystems.json" in documents:
        docs["ecosystems.json"] = documents["ecosystems.json"]
    if config is not None:
        docs[CONFIG] = config
    base = inputs_from_docs(docs, today, cover=coverage_of(snap.inputs, today))
    # the Events listing as the ported view computes it (with the event pins), and the Scout item links (decision d)
    return dataclasses.replace(base, events=list(snap.listing), scout_links=True)


def _listing(people: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    try:
        return people_view.listing(people, today)
    except Exception:  # the old ``_rows``: an unreadable store empties only its layer
        return []

"""ORACLE: runs the OLD Project Zero triage review read side. Never imported by the new code (review 009).

Run with the OLD repository's interpreter and package (``python -m projectzero.ops.parity_triage`` does this):

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/triage_oracle.py IN.json OUT.json

PZ_DATA must point at a SCRATCH data folder the caller filled (a temp copy of a captured snapshot, or synthetic
files); the old modules read settings on import and read the data folder on every call. It is never the real folder.

IN.json  = {"units": [candidate, ...]}   (optional: candidates to run the pure rules on, one by one)
OUT.json = {"meta": {...}, "view": triage_review.view(), "tables": {...},
            "units": {"<index>:<id>": {route, non_startup_reason, european_connection, broken_name_reason, repair,
                                       extract_entities, names_for, check, card, card_sha}}}

``check`` / ``names_for`` use a ``portfolio_check.Checker`` built from the same scratch folder (its real_data.json and
scout_intake.json).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def _pattern(rx: re.Pattern[str]) -> list[Any]:
    return [rx.pattern, int(rx.flags)]


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and "project-zero-data" not in data_dir, "PZ_DATA must be a scratch folder"
    os.environ.setdefault("PZ_TESTING", "1")

    # the OLD package (sys.path set by the caller)
    from projectzero.domain import connectors, ecosys, entity_repair, portfolio_check, routing, taste
    from projectzero.services import shadow_triage, triage_review

    old_root = Path(routing.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()

    inp = json.loads(src.read_text(encoding="utf-8"))
    view = triage_review.view()
    checker = portfolio_check.Checker()
    units = {}
    for index, c in enumerate(inp.get("units") or []):
        units[f"{index}:{c.get('id')}"] = {
            "route": routing.route(c),
            "non_startup_reason": routing.non_startup_reason(c),
            "european_connection": routing.european_connection(c),
            "broken_name_reason": entity_repair.broken_name_reason(c),
            "repair": entity_repair.repair(c),
            "extract_entities": entity_repair.extract_entities(c),
            "extract_company": connectors.extract_company(c.get("name")),
            "names_for": checker.names_for(c),
            "check": checker.check(c),
            "card": shadow_triage.candidate_card(c),
            "card_sha": shadow_triage._sha(shadow_triage.PROMPT_VERSION + "\n" + shadow_triage.candidate_card(c)),
        }
    tables = {
        "eu_places": list(routing._eu_places()),
        "cities": list(ecosys.CITIES),
        "incumbents": list(routing._INCUMBENTS),
        "routing_patterns": {k: _pattern(getattr(routing, k)) for k in
                             ("_UNIVERSITY", "_GOVERNMENT", "_CATAPULT", "_PUBLIC_RESEARCH", "_PLC")},
        "repair_patterns": {k: _pattern(getattr(entity_repair, k)) for k in
                            ("_DATEISH", "_EVENTISH", "_AFTER_DESCRIPTOR", "_BEFORE_VERB", "_NOT_A_COMPANY",
                             "_LEGAL_SUFFIX")},
        "repair_sets": {k: sorted(getattr(entity_repair, k)) for k in ("_DEMONYMS", "_LEADING_NOISE", "_GENERIC")},
        "headline_patterns": {k: _pattern(getattr(connectors, k)) for k in
                              ("_HEADLINE_LABELS", "_CITY_BASED", "_COUNTRY_POSS")},
        "headline_strings": {k: getattr(connectors, k) for k in ("_FUNDING_VERBS", "_NAME_TOKEN", "_NAME_RUN")},
        "name_stop": sorted(connectors._NAME_STOP),
        "portfolio": [[n, w, list(k)] for n, w, k in taste.PORTFOLIO],
        "portfolio_patterns": {k: _pattern(getattr(portfolio_check, k)) for k in ("_PROJECT_A", "_RELATIONSHIP_WORDS")},
        "discovery_tiers": dict(taste.DISCOVERY_TIERS),
        "locked_v3": dict(shadow_triage.LOCKED_V3),
        "prompt_version": shadow_triage.PROMPT_VERSION,
        "pre_funding": sorted(triage_review.PRE_FUNDING),
    }  # fmt: skip
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "units": len(units)}
    out = {"meta": meta, "view": view, "tables": tables, "units": units}
    dst.write_text(json.dumps(out, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

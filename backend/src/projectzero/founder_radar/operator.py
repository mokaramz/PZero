"""The radar part of the operator's person edit (review 026a: what Network, review 013, deferred). The old
``founder_radar.ingestion.operator_save`` ran ``people.upsert`` (the plain save, ported in ``network/edits``) and then,
for an existing radar-generated record, this post-processing. Pure: it works on the saved COPY.

* a changed human name (``is_person_name``) becomes the canonical name with operator provenance: ``name_by_operator``
  and ``name_attributed``, the former name kept in ``aliases``, the "login / handle only" evidence dropped, an
  identity-evidence line and an "Operator edit" source added (entering a name never sets ``identity_verified_by``);
* then, for every radar-generated record, the identity and the signal are recomputed.

"Radar-generated" is the DURABLE imported origin (``legacy.provenance``, Codex H-091), as Network's guard already
decides it, never the current record. Everything else, including the clock, is the old code.
"""

from __future__ import annotations

import copy
from typing import Any

from projectzero.founder_radar.clock import Clock
from projectzero.founder_radar.identity import identity_resolution
from projectzero.founder_radar.names import _fold, is_person_name
from projectzero.founder_radar.records import migrate_person
from projectzero.founder_radar.scoring import assess

OPERATOR = "Mohamed"  # the old text names the operator


def radar_generated(legacy: Any) -> bool:
    return isinstance(legacy, dict) and legacy.get("provenance") != "user_provided"


def after_operator_save(
    before: dict[str, Any], saved: dict[str, Any], body: dict[str, Any], ck: Clock
) -> dict[str, Any]:
    """The record ``people.upsert`` produced (``saved``) with the old radar post-processing applied (a copy)."""
    p = copy.deepcopy(saved)
    old_name = before.get("name", "")
    new_name = str(body.get("name") or "").strip()
    if new_name and _fold(new_name) != _fold(old_name) and is_person_name(new_name):
        migrate_person(p)
        if old_name and old_name not in p.setdefault("aliases", []):
            p["aliases"].append(old_name)
        p["name"] = new_name
        p["name_by_operator"] = True
        p["name_attributed"] = True
        p.setdefault("identity_evidence", [])
        p["identity_evidence"] = [x for x in p["identity_evidence"] if "login / handle only" not in x]
        p["identity_evidence"].append(
            f"human name entered by {OPERATOR} (operator edit {ck.minute()}): {old_name or '—'} -> {new_name}"
        )
        p.setdefault("sources", []).append(
            {
                "source": "Operator edit",
                "source_id": "operator",
                "url": "",
                "retrieved": ck.minute(),
                "route": "manual",
                "by": "operator",
                "note": f"human name entered by {OPERATOR}",
            }
        )
    status, evidence = identity_resolution(p)
    p["identity_status"], p["identity_evidence"] = (
        status,
        list(dict.fromkeys((p.get("identity_evidence") or []) + evidence)),
    )
    p["signal"] = assess(p, today=ck.today)
    p["signal_categories"] = p["signal"]["bands"]
    p["evidence_confidence"] = p["signal"]["evidence_confidence"]
    return p

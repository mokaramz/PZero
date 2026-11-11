"""Reading a ``people`` row (the write model is described in ``projectzero.network``)."""

from __future__ import annotations

from typing import Any

PROMOTED = ("id", "name", "country", "identity_status", "founder_status", "radar_state")


def record_of(row: dict[str, Any]) -> dict[str, Any]:
    """Today's record of a person row: ``attrs.record`` once the new app wrote it, else the imported ``legacy``.

    A row with neither (never written by the importer or the app) is rebuilt from its columns and attributes."""
    attrs = row.get("attrs")
    rec = attrs.get("record") if isinstance(attrs, dict) else None
    if isinstance(rec, dict):
        return rec
    legacy = row.get("legacy")
    if isinstance(legacy, dict):
        return legacy
    return {**(attrs if isinstance(attrs, dict) else {}), **{k: row[k] for k in PROMOTED if row.get(k) is not None}}

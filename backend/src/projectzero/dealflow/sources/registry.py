"""Map a registry-scan record (NIH RePORTER, UKRI GtR, …) to a contract entity for the trusted intake path."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO2 = re.compile(r"^[A-Z]{2}$")
_COUNTRY_ALIASES = {"USA": "US", "UK": "GB", "UNITED STATES": "US", "UNITED KINGDOM": "GB", "GERMANY": "DE"}
_REGISTRY_NAMESPACE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


def country_code(record: Mapping[str, Any]) -> str | None:
    for raw in [*(record.get("geo") or []), record.get("country")]:
        if isinstance(raw, str):
            code = _COUNTRY_ALIASES.get(raw.strip().upper(), raw.strip().upper())
            if _ISO2.match(code):
                return code
    return None


# Values that mean "no id". A registry id is a strong identifier: a placeholder shared by unrelated records would
# merge them into one company, so these are dropped, never stored (review 001 rev 2, #1).
_PLACEHOLDERS = frozenset({"none", "null", "nil", "nan", "n/a", "na", "-", "--", "0", "unknown", "tbd", "?"})


def registry_value(raw: Any) -> str | None:
    """A usable registry id, or None for missing / placeholder / structurally invalid values."""
    if isinstance(raw, bool) or not isinstance(raw, str | int):
        return None  # null, floats (lossy), lists, dicts, booleans
    value = str(raw).strip()
    if not value or value.lower() in _PLACEHOLDERS or len(value) > 80:
        return None
    return value


REGISTRY_KINDS = ("uei", "duns", "org_id")  # the registry ids an old scan record carries (``entity_ids``)


def registry_namespace(kind: str, source_id: Any) -> str:
    """The storage namespace of a registry id an old scan record carried (``entity_ids``), shared by the importer and
    the scan's identity resolution (review 034a, H-343): a DUNS is global; a UK GtR organisation id is ``gtr_org``;
    every other id (a UEI, another ``org_id``) is qualified by its source, so equal values from distinct sources never
    join companies on their own."""
    if kind == "org_id" and source_id == "uk-gtr":
        return "gtr_org"
    return kind if kind == "duns" else f"{kind}:{source_id}"


def entity_from_registry_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Build a contract entity. Fields the record cannot support are omitted, never invented."""
    entity: dict[str, Any] = {
        "kind": "company",
        "name": str(record.get("name") or "").strip(),
        "key_fact": str(record.get("description") or "").strip()[:600],
        "evidence": [],
    }
    if url := record.get("source_url"):
        item: dict[str, Any] = {"url": url}
        if title := (record.get("raw_title") or record.get("source")):
            item["title"] = str(title)[:300]
        entity["evidence"].append(item)
    if country := country_code(record):
        entity["location"] = {"country": country}
    registry_ids = {
        k: value
        for k, v in (record.get("entity_ids") or {}).items()
        if isinstance(k, str) and _REGISTRY_NAMESPACE.match(k) and (value := registry_value(v)) is not None
    }
    if registry_ids:
        entity["registry_ids"] = registry_ids
    if sectors := [s for s in (record.get("sectors") or []) if isinstance(s, str) and s][:8]:
        entity["sectors"] = sectors
    # `date` is only a signal date when it is not merely the day the scan detected the record
    candidates = [record.get("source_date")]
    if record.get("date_kind") != "detected":
        candidates.append(record.get("date"))
    for value in candidates:
        if isinstance(value, str) and _ISO_DATE.match(value):
            entity["signal_date"] = value
            break
    return entity

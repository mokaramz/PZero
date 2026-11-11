"""A person row: reading it (``record_of``) and the ONE mapping of a current record onto the columns and identifiers.

The write model is described in ``projectzero.network``. The importer (``ops.legacy.map_records.people``) and the
Network writes (``network.store``) both use ``columns_of`` and ``identifiers_of``, so an imported person and a person
the app wrote mirror their record by the same rules (review 012 / 013).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from projectzero.dealflow.identity import is_placeholder_name
from projectzero.network.identity import (
    canonical_github_id,
    canonical_openalex,
    canonical_orcid,
    classify_profile_url,
    fold,
    own_accounts,
)

PROMOTED = ("id", "name", "country", "identity_status", "founder_status", "radar_state")
TEXT_COLUMNS = ("name", "country", "identity_status", "founder_status", "radar_state")  # text columns of pz.people
WEAK_KINDS = frozenset({"url", "alias"})  # unique per person only (migration 0005)
RESERVED_ATTRS = ("id", "record")  # "record" is the application's current record (review 012, H-078)


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


def slug(name: str) -> str:
    """The old ``people._slug``, verbatim: the id the old app gave a new person (``p-<slug, at most 40>``)."""
    s = name.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return "p-" + (re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40] or "person")


def columns_of(pid: str, record: dict[str, Any]) -> dict[str, Any]:
    """The typed columns and the flattened ``attrs`` of a person row for ``record`` (without ``attrs.record``).

    * ``name``: the record's name when it is non-blank text, else the id (the column is ``not null``);
    * ``normalized_name``: the old person key ``fold`` (``NULL`` when it has no letters);
    * a promoted text field whose value is not text is ``NULL`` in its column and stays in ``attrs``.
    """
    name = record.get("name") if isinstance(record.get("name"), str) and record["name"].strip() else pid
    return {
        "name": name,
        "normalized_name": fold(name) or None,
        **{k: record.get(k) if isinstance(record.get(k), str) else None for k in TEXT_COLUMNS if k != "name"},
        "attrs": {
            k: v
            for k, v in record.items()
            if k not in RESERVED_ATTRS and (k not in TEXT_COLUMNS or (v is not None and not isinstance(v, str)))
        },
    }


def _str_list(value: Any) -> list[str]:
    """The legacy importer's ``str_list``: strings and ints of a list (or one string), blanks dropped."""
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, str | int) and str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def identifiers_of(p: dict[str, Any]) -> list[tuple[str, str]]:
    """(kind, canonical value) of every identifier a person record asserts, strongest first (review 012)."""

    def text(value: Any, canonical: Callable[[str], str]) -> str | None:
        return canonical(value) if isinstance(value, str) and value.strip() and not is_placeholder_name(value) else None

    out: list[tuple[str, str]] = []
    strong = (
        ("orcid", text(p.get("orcid"), canonical_orcid)),
        ("openalex", text(p.get("openalex_id"), canonical_openalex)),
        ("github", canonical_github_id(p.get("github_id"))),  # the same validator as the ownership evidence (H-082)
        ("patent_inventor", text(p.get("patent_inventor_id"), str.strip)),
    )
    out.extend((kind, value) for kind, value in strong if value is not None)
    own = own_accounts(p)
    for url in _str_list(p.get("profile_urls")):
        if not is_placeholder_name(url) and (classified := classify_profile_url(url, own)) is not None:
            out.append(classified)
    seen: set[str] = set()
    for alias in _str_list(p.get("aliases")):
        value = alias.strip()
        if value and not is_placeholder_name(value) and value.casefold() not in seen:
            seen.add(value.casefold())  # one alias per spelling, case aside (the first spelling is kept)
            out.append(("alias", value))
    return out


def distinct_identifiers(p: dict[str, Any]) -> list[tuple[str, str]]:
    """``identifiers_of`` with a repeat within the one person dropped (one row per (kind, value))."""
    return list(dict.fromkeys(identifiers_of(p)))

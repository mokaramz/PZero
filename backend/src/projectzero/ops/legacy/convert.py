"""Small, pure conversions from legacy values to schema values."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")  # the old app wrote naive local times
_NAMESPACE = uuid.UUID("6f1d3c52-6a0e-4c0b-9a52-3f7f1b0f2a10")  # fixed: deterministic ids make re-planning stable

# legacy status -> unified candidate status (DATA_MODEL.md "Status mapping")
DEALFLOW_STATUS = {
    "new": "new", "baseline": "baseline", "rejected": "rejected", "watch": "watch", "kept": "kept",
    "research": "reviewing",
}  # fmt: skip
INTAKE_STATUS = {
    "NEW INTAKE": "new", "REVIEWING": "reviewing", "MONITOR": "watch", "APPROVED — CREATE": "kept",
    "APPROVED — UPDATE": "kept", "REJECTED": "rejected", "ARCHIVED": "archived",
}  # fmt: skip
NATIVE_STATUS = {
    "NEW_SIGNAL": "new", "INVESTIGATE": "reviewing", "MONITORING": "watch", "DISMISSED": "rejected",
    "STALE": "archived", "PROMOTED_TO_CANDIDATE": "kept",
}  # fmt: skip
OPEN_STATUSES = frozenset({"new", "reviewing", "watch", "baseline", "kept"})
STATUS_RANK = {"kept": 5, "reviewing": 4, "watch": 3, "new": 2, "baseline": 1}  # survivor choice when merging


def stable_uuid(key: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, key))


def stable_short_id(key: str) -> str:
    """12 hex chars, like legacy Deal Flow ids, derived from a namespaced legacy key."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")


def timestamp(value: Any) -> datetime | None:
    """Legacy timestamps: ISO with or without 'T', seconds or offset; naive values are Europe/Berlin."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=BERLIN)


def day(value: Any) -> datetime | None:
    """A date-only value as midnight Europe/Berlin; full timestamps pass through ``timestamp``."""
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        return datetime.combine(date.fromisoformat(value.strip()), datetime.min.time(), BERLIN)
    return timestamp(value)


def epoch() -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC)


def text_or_none(value: Any, *, placeholder: frozenset[str] = frozenset({"unknown", "n/a", "none", ""})) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return None if stripped.casefold() in placeholder else stripped


def str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, str | int) and str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def records(value: Any) -> list[dict[str, Any]]:
    """Legacy collections are lists or id-keyed dicts; return the records either way (non-dicts dropped)."""
    items = value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
    return [item for item in items if isinstance(item, dict)]

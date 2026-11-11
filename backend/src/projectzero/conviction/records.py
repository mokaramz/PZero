"""Small readers shared by the Conviction port (the old ``compat`` helpers and the pipeline's tolerant readers)."""

from __future__ import annotations

from typing import Any

from projectzero.conviction import taste

PIPELINE_EXISTING_LABEL = "Existing pipeline — not discovered in this scan"
COMPUTED_FIELDS = ("sc", "slug", "days_old", "discovery_status", "archetype_name", "imq_eval", "data_warning", "op")


def records(seq: Any, required: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """The old ``compat.records``: the dict records of ``seq`` (a list, or a dict's values) that carry every
    ``required`` key with a value."""
    if isinstance(seq, dict):
        seq = list(seq.values())
    if not isinstance(seq, list):
        return []
    return [r for r in seq if isinstance(r, dict) and all(r.get(k) not in (None, "") for k in required)]


def list_(v: Any) -> list[Any]:
    return v if isinstance(v, list) else []


def discovery_status(e: dict[str, Any]) -> str:
    """Truthful origin label: only entries created from a scanned inbox candidate carry ``discovered_run``."""
    if e.get("discovered_run"):
        return "Discovered by scan %s (first seen %s)" % (e["discovered_run"], e.get("discovered_first_seen") or "—")  # noqa: UP031
    return PIPELINE_EXISTING_LABEL


def readable(e: dict[str, Any]) -> dict[str, Any]:
    """A COPY of ``e`` the frozen scoring can read: unreadable legacy values become neutral (old ``_readable``)."""
    fixed = dict(e)
    sc = e.get("scores")
    fixed["scores"] = (
        {k: (int(v) if str(v).strip().lstrip("-").isdigit() else 0) for k, v in sc.items()}
        if isinstance(sc, dict)
        else {}
    )
    fixed["verified"] = {k: v is True for k, v in e["verified"].items()} if isinstance(e.get("verified"), dict) else {}
    pen = e.get("penalties")
    fixed["penalties"] = [x for x in pen if isinstance(x, str)] if isinstance(pen, list) else []
    if not isinstance(e.get("earliness"), str):
        fixed["earliness"] = "unknown"
    if not isinstance(e.get("conflict"), (str, type(None))):
        fixed["conflict"] = "unclear"
    return fixed


DATA_WARNING_SCORE = "a stored value could not be read — shown as neutral here; the stored record is unchanged"
DATA_WARNING_RECORD = "part of this record could not be read — shown with neutral values; nothing was changed"


def safe_score(e: dict[str, Any]) -> dict[str, Any]:
    """The frozen ``taste.score``; a value it cannot read is read as neutral on a COPY and the company is flagged."""
    try:
        return taste.score(e)
    except Exception:
        e["data_warning"] = DATA_WARNING_SCORE
        return taste.score(readable(e))


def clean_founders(fl: Any) -> list[Any]:
    """RC1.1: tolerate strings / null / empty founder rows (old ``pipeline._clean_founders``)."""
    fl = fl or []
    return [({"name": str(f).strip()} if not isinstance(f, dict) else f) for f in (fl if isinstance(fl, list) else [fl])
            if f and (str(f).strip() if not isinstance(f, dict) else str(f.get("name") or "").strip())]  # fmt: skip

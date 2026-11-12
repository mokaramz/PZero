"""The old ``domain/founder_radar/evidence.py`` (rev 6c739b9), the part review 024 did not port: ``dedupe_evidence``,
``_ev`` and ``person_recent_activity``, line for line (review 026a). ``valid_activity_date``, ``is_recent`` and
``add_evidence`` are the Active Evaluator's (``evaluator/evidence.py``), reused. The clock is a parameter: ``today``
(the Berlin day) replaces ``date.today()``; ``now`` (the Berlin wall clock) replaces ``datetime.now()``."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from projectzero.evaluator.evidence import add_evidence, is_recent, valid_activity_date

__all__ = ["_ev", "add_evidence", "dedupe_evidence", "is_recent", "person_recent_activity", "valid_activity_date"]


def dedupe_evidence(ev: Any) -> list[Any]:
    """One row per (category, normalized claim, source URL) — applied before persistence and before rendering."""
    seen, out = set(), []
    for x in ev or []:
        key = (
            x.get("category"),
            re.sub(r"\s+", " ", str(x.get("claim") or "").strip().lower()),
            str(x.get("source_url") or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(x)
    return out


def _ev(
    cat: Any, claim: Any, url: Any, src: Any, when: Any = None, activity_date: Any = None, *, now: datetime
) -> dict[str, Any]:
    row = {
        "category": cat,
        "claim": claim,
        "source": src,
        "source_url": url,
        "retrieved": when or now.strftime("%Y-%m-%d %H:%M"),
    }
    if activity_date:
        row["activity_date"] = activity_date  # explicit date of the underlying activity (never the retrieval time)
    return row


def person_recent_activity(p: dict[str, Any], today: date) -> dict[str, Any]:
    """The latest DATED, attributable trajectory/activity evidence — scan/merge/save timestamps never count."""
    best: tuple[date, Any] | None = None
    for x in p.get("evidence") or []:
        if x.get("category") == "trajectory" and valid_activity_date(x.get("activity_date"), today):
            d0 = valid_activity_date(x["activity_date"], today)
            assert d0 is not None
            if best is None or d0 > best[0]:
                best = (d0, x)
    if not best:
        return {"recent": False, "date": "", "source": "", "reason": "no dated trajectory/activity evidence"}
    return {
        "recent": is_recent(best[0].isoformat(), today),
        "date": best[0].isoformat(),
        "source": best[1].get("source", ""),
        "claim": best[1].get("claim", "")[:110],
        "reason": "" if is_recent(best[0].isoformat(), today) else "latest dated activity older than 90 days",
    }

"""The old ``domain/founder_radar/evidence.py`` (rev 6c739b9): ``valid_activity_date``, ``is_recent`` and
``add_evidence``, ported line for line (review 024; the Active Evaluator owns these, PORT_ORDER step 6).

Only change: the clock is a parameter. ``today`` (the Berlin day) replaces ``date.today()``; ``now`` (the Berlin wall
clock) replaces ``datetime.now()``. ``add_evidence`` only VALIDATES and returns its row, as before: nothing here (or
in its callers) writes ``radar_companies.json`` (decision e).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


def valid_activity_date(v: Any, today: date) -> date | None:
    """ISO YYYY-MM-DD, real calendar date, not in the future -> date; otherwise None."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", str(v or "").strip())
    if not m:
        return None
    try:
        d0 = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return d0 if d0 <= today else None


def is_recent(activity_date: Any, today: date, window: int = 90) -> bool:
    d0 = valid_activity_date(activity_date, today)
    return d0 is not None and 0 <= (today - d0).days <= window


def add_evidence(
    kind: Any,
    url: Any,
    label: Any,
    claim: Any,
    field: Any = "",
    activity_date: Any = None,
    *,
    now: datetime,
    today: date,
) -> dict[str, Any]:
    """Operator-supplied PUBLIC evidence (GitHub profile, official company/team page,
    accelerator/university/grant/portfolio page, existing Project Zero URL). LinkedIn is a contact route, never
    evidence. Search results are never evidence until saved here."""
    url = str(url or "").strip()
    label = str(label or "").strip()
    claim = str(claim or "").strip()
    if not url.startswith("http") or not label or not claim:
        return {"ok": False, "error": "source URL, source label and the supported claim are all required"}
    if "linkedin.com" in url.lower():
        return {
            "ok": False,
            "error": "LinkedIn pages are a contact route, not evidence — paste an official/public source instead",
        }
    if any(k in url.lower() for k in ("google.com/search", "bing.com/search", "duckduckgo.com")):
        return {
            "ok": False,
            "error": "search results are not evidence — open the actual source page and paste that URL",
        }
    row = {
        "category": kind or "operator",
        "claim": claim,
        "source": "Operator-supplied public evidence — " + label,
        "source_url": url,
        "field": field,
        "retrieved": now.strftime("%Y-%m-%d %H:%M"),
        "by": "operator",
    }
    if kind == "trajectory":
        if not valid_activity_date(activity_date, today):
            return {
                "ok": False,
                "error": "trajectory/activity evidence needs an explicit activity date YYYY-MM-DD (not in the future)",
            }
        row["activity_date"] = str(activity_date).strip()
    return {"ok": True, "row": row}

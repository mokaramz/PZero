"""The prepared-case rows Today reads (review 030a): the old ``services/case_prep.py`` ``summary`` (:1581-1604) at
revision 6c739b9, ported line for line as a pure function over the ported ``conviction.operator.state_of``.

The old one read ``case_prep/cases.json`` and the Conviction pipeline itself (its second pipeline read per Today
view); both are parameters here (``TodayInputs.operator.cases`` / ``signals``), and the clock is the request's
(decision b: the 14-day freshness rule reads the same Berlin ``now`` as every other date of the view). No case is
ever PREPARING: case preparation is not ported (Conviction 011, decision b).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from projectzero.conviction.operator import OperatorInputs, state_of
from projectzero.conviction.records import list_


def _dict(v: Any) -> dict[str, Any]:
    """The old ``compat.dict_``."""
    return v if isinstance(v, dict) else {}


def summary(signals: list[dict[str, Any]], inp: OperatorInputs, now: datetime) -> list[dict[str, Any]]:
    """One row per prepared / preparing case (Today, Conviction list)."""
    cases = inp.cases
    entries = {e["slug"]: e for e in signals if e.get("status") != "dropped"}
    out = []
    for slug, e in entries.items():
        c = cases.get(slug)
        st = state_of(slug, c, e, inp, now)
        card = _dict((c or {}).get("card") if isinstance(c, dict) else None)
        out.append(
            {
                "slug": slug,
                "company": e.get("company"),
                **st,
                "decisions": [str(d.get("text") or "") for d in list_(card.get("decisions")) if isinstance(d, dict)],
                "next_action": card.get("next_action") if isinstance(card.get("next_action"), dict) else None,
                "prepared_at": (c or {}).get("prepared_at") if isinstance(c, dict) else None,
                "discovered": e.get("discovery_date") or "",
                "serious": (c or {}).get("serious") if isinstance(c, dict) else None,
            }
        )
    return out


def newest_prepared_at(inp: OperatorInputs) -> str | None:
    """The newest ``prepared_at`` of the imported prepared cases (the snapshot note, decision f), or ``None``."""
    stamps = [str(c.get("prepared_at")) for c in inp.cases.values() if isinstance(c, dict) and c.get("prepared_at")]
    return max(stamps) if stamps else None

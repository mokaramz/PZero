"""The Events dedup rule: the old ``domain/events.py`` ``_norm_name`` / ``paren_base`` / ``_similar`` /
``_close_dates`` (rev 6c739b9, :1293-1322), ported VERBATIM.

Scout 00 report matching uses it now (review 015); the ``event_save`` merge and lead dedup will use it in review 016.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any


def norm_name(n: Any) -> str:
    n = re.sub(r"20\d\d", "", (n or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


def paren_base(n: Any) -> str:
    """'Slush 2026 (robotics demo area, Day 0)' -> 'Slush 2026' (a trailing annotation in brackets removed)."""
    return re.sub(r"\s*\([^()]*\)\s*$", "", str(n or "")).strip()


def similar(a: Any, b: Any) -> bool:
    ta, tb = set(norm_name(a).split()), set(norm_name(b).split())
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    if (inter / min(len(ta), len(tb)) >= 0.7 and inter >= 2) or norm_name(a) == norm_name(b):
        return True
    # one name is the other plus a bracketed annotation; two different annotations never match
    na, nb = norm_name(a), norm_name(b)
    return bool(na and nb) and (na == norm_name(paren_base(b)) or nb == norm_name(paren_base(a)))


def close_dates(d1: Any, d2: Any) -> bool:
    if not d1 or not d2:
        return True  # unknown date does not block a name match
    try:
        return abs((date.fromisoformat(d1[:10]) - date.fromisoformat(d2[:10])).days) <= 1
    except Exception:  # the old code: any failure (a non-string, a bad date) does not block a name match
        return True

"""How the old rules turn a candidate into text. Kept on purpose — every quirk below moves scores if "fixed".

* ``joined(c, keys)`` is ``" ".join(str(c.get(k, "")) for k in keys)`` exactly:
  - an ABSENT key contributes ``""``, but a key present with value ``None`` contributes ``"None"`` (and ``"none"``
    after the callers lower-case it);
  - a list value contributes Python's ``repr`` of the list (``"['robotics', 'ai']"``), including its quote switching
    (``"[\"it's\"]"``) and escaped newlines (``"['a\\nb']"``);
  - numbers and dicts contribute their ``str``.
* ``entity_type`` instead joins ``why`` element-wise with spaces (``spaced_list``) — a different rule on purpose.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def joined(c: Mapping[str, Any], keys: Iterable[str]) -> str:
    return " ".join(str(c.get(k, "")) for k in keys)


def spaced_list(value: Any) -> str:
    """``" ".join(str(x) for x in (value or []))`` — how the old ``entity_type`` reads ``why``."""
    return " ".join(str(x) for x in (value or []))

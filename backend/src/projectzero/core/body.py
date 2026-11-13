"""Strict reads of request-body fields (review 036a).

``confirmed`` is the one test of an explicit confirmation: only the JSON boolean ``true`` confirms a write. The old
routes read ``bool(body.get("confirm"))``, so a malformed value such as the string ``"false"`` confirmed (H-351).
Each route maps ``BadConfirm`` to its own error answer with HTTP 400, checked with its other input checks before any
write.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CONFIRM_REFUSAL = "confirm must be true or false"


class BadConfirm(ValueError):
    """A supplied confirmation that is not a JSON boolean (``null``, ``0``, ``1``, ``""``, ``"false"``, a list...)."""

    def __init__(self) -> None:
        super().__init__(CONFIRM_REFUSAL)


def confirmed(body: Mapping[str, Any], key: str = "confirm") -> bool:
    """``True`` only for JSON ``true``; an absent key or JSON ``false`` is ``False``; any other supplied value
    (an explicit ``null`` included: the key is present) raises ``BadConfirm``. ``bool`` is tested by type, never by
    truthiness or equality, since ``1 == True`` and ``0 == False`` in Python."""
    if key not in body:
        return False
    value = body[key]
    if isinstance(value, bool):
        return value
    raise BadConfirm

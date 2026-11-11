"""The inbox comparison itself (review 009): it must fail on order, membership, merge and field problems."""

from __future__ import annotations

import copy
from typing import Any

from projectzero.ops.parity_inbox import compare


def payload(*ids: str, **extra: Any) -> dict[str, Any]:
    return {"last_run": "r1", "report": [], "candidates": [{"id": i, "name": i.upper()} for i in ids], **extra}


def test_identical_payloads_with_a_verified_merge_pass() -> None:
    old = payload("a", "b", "c")
    new = payload("a", "c", "x")  # b merged into c; x is an additional candidate
    result = compare(old, new, {"b": ("c", "merge")})
    assert result["problems"] == [] and result["field_differences"] == [] and result["top_level_differences"] == []
    assert (result["legacy_survivors"], result["absorbed"], result["additional"]) == (2, 1, 1)


def test_order_membership_merge_and_fields_are_checked() -> None:
    old = payload("a", "b", "c")
    assert compare(old, payload("b", "a", "c"), {})["problems"]  # order
    assert compare(old, payload("a", "c"), {})["problems"]  # missing survivor
    assert compare(old, payload("a", "c"), {"b": ("c", "legacy_import")})["problems"]  # not a merge
    assert compare(old, payload("a", "x", "b", "c"), {})["problems"]  # an additional one before legacy survivors
    changed = copy.deepcopy(old)
    changed["candidates"][1]["name"] = "other"
    assert compare(old, changed, {})["field_differences"] == ["/b/name: 'B' != 'other'"]
    assert compare(old, payload("a", "b", "c", last_run="r2"), {})["top_level_differences"]
    assert compare(payload("a", feeds=[1]), payload("a"), {})["top_level_differences"] == []  # never read: not carried

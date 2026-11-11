"""Deal Flow read model: request validation and paging cursors (no database)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from projectzero.dealflow.candidates import (
    DecisionError,
    ListQuery,
    _decode_cursor,
    _encode_cursor,
    validate_operator_status,
)


def test_cursor_round_trip() -> None:
    at = datetime(2026, 11, 11, 9, 30, tzinfo=UTC)
    assert _decode_cursor(_encode_cursor(at, "4225c719f2f2")) == (at.isoformat(), "4225c719f2f2")


@pytest.mark.parametrize("cursor", ["", "not-base64!", "W10", "WyJub3QtYS1kYXRlIiwgIngiXQ"])
def test_bad_cursor_is_a_400(cursor: str) -> None:
    with pytest.raises(DecisionError) as err:
        _decode_cursor(cursor)
    assert err.value.status == 400


def test_unknown_status_filter_is_a_400() -> None:
    with pytest.raises(DecisionError) as err:
        ListQuery(status=("NEW INTAKE",))
    assert err.value.status == 400 and "kept" in err.value.extra["allowed"]


@pytest.mark.parametrize("limit", [0, 201, -5])
def test_limit_bounds(limit: int) -> None:
    with pytest.raises(DecisionError):
        ListQuery(limit=limit)


def test_keep_is_never_a_bare_status_change() -> None:
    with pytest.raises(DecisionError) as err:
        validate_operator_status("kept")
    assert err.value.status == 409 and err.value.extra == {"keep_via": "conviction"}


@pytest.mark.parametrize("status", ["research", "NEW INTAKE", "", "Rejected"])
def test_unknown_operator_status_is_a_400(status: str) -> None:
    with pytest.raises(DecisionError) as err:
        validate_operator_status(status)
    assert err.value.status == 400


@pytest.mark.parametrize("status", ["new", "reviewing", "watch", "baseline", "rejected", "archived"])
def test_operator_statuses(status: str) -> None:
    validate_operator_status(status)

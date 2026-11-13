"""Review 036a: ``confirmed`` over the value matrix. Only the JSON boolean ``true`` confirms; an absent key or JSON
``false`` does not; every other supplied value (an explicit ``null`` included) raises ``BadConfirm``."""

from __future__ import annotations

import json
from typing import Any

import pytest

from projectzero.core.body import CONFIRM_REFUSAL, BadConfirm, confirmed


def test_absent_and_false_are_not_confirmed() -> None:
    assert confirmed({}) is False
    assert confirmed({"other": True}) is False
    assert confirmed({"confirm": False}) is False
    assert confirmed(json.loads('{"confirm": false}')) is False


def test_only_a_literal_true_confirms() -> None:
    assert confirmed({"confirm": True}) is True
    assert confirmed(json.loads('{"confirm": true}')) is True


@pytest.mark.parametrize(
    "value", [None, 0, 1, 0.0, 1.0, -1, "", "false", "true", "False", "True", "0", "1", [], [True], {}, {"x": 1}]
)
def test_any_other_supplied_value_is_refused(value: Any) -> None:
    with pytest.raises(BadConfirm) as exc:
        confirmed({"confirm": value})
    assert str(exc.value) == CONFIRM_REFUSAL == "confirm must be true or false"


def test_an_explicit_null_is_not_an_absent_key() -> None:
    with pytest.raises(BadConfirm):
        confirmed(json.loads('{"confirm": null}'))


def test_another_key() -> None:
    assert confirmed({"ok": True}, key="ok") is True
    assert confirmed({"confirm": True}, key="ok") is False
    with pytest.raises(BadConfirm):
        confirmed({"ok": 1}, key="ok")

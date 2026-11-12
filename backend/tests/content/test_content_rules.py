"""Public work (review 020), offline: the id contract, the goldens' provenance and script, and the import check."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from projectzero.content.store import ID_NOT_STRING, ContentError, delete_id, request_id
from projectzero.ops.legacy.map_records import RecordsMapper
from projectzero.ops.parity_content import CLOCK, NUMERIC, SCRIPT, SEED

GOLDEN: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "golden_v1" / "oracle_content.json").read_text(encoding="utf-8")
)


def test_provenance_and_script_are_current() -> None:
    assert GOLDEN["provenance"]["old_revision"] == "6c739b9cb6ca2517b845e381d39a36c50eccc59e"
    assert GOLDEN["provenance"]["old_dirty"] is False and GOLDEN["provenance"]["clock"] == CLOCK
    assert GOLDEN["seed"] == SEED and GOLDEN["script"] == SCRIPT and GOLDEN["numeric"]["script"] == NUMERIC
    assert not any("raises" in s for s in GOLDEN["expected"])


@pytest.mark.parametrize("raw", [None, "", 0, False, [], {}])
def test_a_falsy_id_generates_one(raw: Any) -> None:
    assert request_id({"id": raw}) is None and request_id({}) is None


@pytest.mark.parametrize("raw", [7, 7.5, True, ["x"], {"a": 1}])
def test_any_other_non_string_id_is_refused(raw: Any) -> None:
    with pytest.raises(ContentError) as err:
        request_id({"id": raw})
    assert (err.value.status, str(err.value)) == (400, ID_NOT_STRING)


def test_a_string_id_is_used_as_sent() -> None:
    assert request_id({"id": "7"}) == "7" and request_id({"id": " x "}) == " x "


class FakeSource:
    def __init__(self, body: Any) -> None:
        self.body = body

    def paths(self) -> list[str]:
        return ["content.json"]

    def json(self, path: str, default: Any = None) -> Any:
        return self.body


def blockers(body: Any) -> list[str]:
    mapper = RecordsMapper.__new__(RecordsMapper)
    mapper.src = FakeSource(body)  # type: ignore[assignment]
    mapper.identity_blockers = []
    mapper.report = {"reconciliation": {}}
    mapper.content_log()
    return mapper.identity_blockers


def test_a_well_formed_log_imports() -> None:
    assert blockers(SEED) == [] and blockers({"items": []}) == []


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"items": [{"id": 7}, {"id": "7"}]}, "position 0 is not a record with a non-empty string id (found int)"),
        ({"items": [{"id": "a"}, {"id": "a"}]}, "positions 0 and 1 share the id 'a'"),
        ({"items": [{"title": "no id"}]}, "found NoneType"),
        ({"items": [{"id": ""}]}, "position 0 is not a record"),
        ({"items": ["x"]}, "found str"),
        ({"items": {}}, 'must be an object with an "items" list'),
        ({"note": "no items"}, 'must be an object with an "items" list'),
        (["x"], 'must be an object with an "items" list'),
    ],
)
def test_a_malformed_log_blocks_the_import(body: Any, fragment: str) -> None:
    found = blockers(body)
    assert found and any(fragment in b for b in found), found


def test_delete_ids_no_key_is_the_old_success_a_string_is_used_any_other_value_is_refused() -> None:
    assert delete_id({}) is None and delete_id({"id": ""}) == "" and delete_id({"id": "nope"}) == "nope"
    for raw in (0, False, None, 7, [], {}):
        with pytest.raises(ContentError) as err:
            delete_id({"id": raw})
        assert (err.value.status, str(err.value)) == (400, ID_NOT_STRING)

"""Review 028b, offline: the pure News writes (``news/writes.py``) match the OLD writes' goldens
(``oracle_news_writes.json``, ``python -m projectzero.ops.parity_news writes-goldens``): per step the seeding, the
answer, the appended action and Validation bytes, the saved event record (key order) and the next News and
Validation views, with no declared difference. Also: the decision matrix (once the LATEST decision is a confirm, any
valid decision answers it again and appends nothing), the old refusal texts in the old check order, the three
action-line encodings byte for byte, the 027b id seam, the stored-seeding helper and purity."""

from __future__ import annotations

import ast
import copy
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from projectzero.news import core, writes
from projectzero.news.inputs_model import CASES_KEY
from projectzero.news.writes import NewsError, NewsWritten, SeedChange
from projectzero.ops import parity_news
from projectzero.ops.parity_news import (
    CLOCK,
    WRITE_SEQUENCES,
    WRITES_GOLDEN,
    case_b,
    case_text,
    compare_writes,
    read_golden,
    write_sequences,
    writes_docs,
)
from projectzero.ops.parity_ranking import OLD_REPO
from projectzero.validation import ValidationError, ValidationInputs
from projectzero.validation import inputs_from_docs as validation_inputs

GOLDEN: dict[str, Any] = read_golden(WRITES_GOLDEN)
OLD_NEWS = OLD_REPO / "backend" / "src" / "projectzero" / "services" / "news.py"
TODAY = date(2026, 11, 12)
NOW = datetime(2026, 11, 12, 10, 0)


def hexes(*values: str) -> Any:
    seq = list(values)
    return lambda: seq.pop(0)


def no_hex() -> str:
    raise AssertionError("no id is made by this write")


def world() -> tuple[Any, ValidationInputs]:
    """The writes world after the store's ``ensure_seeded``, as a write transaction sees it."""
    v = validation_inputs(writes_docs(), TODAY)
    doc, _changes = writes.ensure_seeded(v.news_inputs.events, v.news_inputs.cases, NOW)
    return writes.with_events(v.news_inputs, v, doc)


def run(op: Any, body: dict[str, Any], n: Any, v: Any, new_hex: Any = no_hex) -> NewsWritten:
    out: NewsWritten = op(n, body, today=TODAY, now=NOW, new_hex=new_hex, validation=v)
    return out


# ------------------------------------------------------------------------------------------------ the goldens
def test_the_pure_writes_match_the_old_code_step_by_step() -> None:
    assert compare_writes(GOLDEN) == []


def test_provenance_and_inputs_are_current() -> None:
    assert GOLDEN["provenance"]["old_revision"] == "6c739b9cb6ca2517b845e381d39a36c50eccc59e"
    assert GOLDEN["provenance"]["old_dirty"] is False
    assert GOLDEN["provenance"]["mode"] == "news-writes"
    assert GOLDEN["clock"] == CLOCK
    assert GOLDEN["expected"]["changed"] == []  # the old writes never reached the data folder
    # serialized without sort_keys: the documents' insertion order is part of the input
    assert json.dumps(GOLDEN["docs"]) == json.dumps(json.loads(json.dumps(writes_docs())))
    assert GOLDEN["sequences"] == json.loads(json.dumps(write_sequences()))
    assert list(GOLDEN["expected"]["sequences"]) == list(WRITE_SEQUENCES)


def test_the_golden_is_lf_json_read_as_bytes() -> None:
    raw = WRITES_GOLDEN.read_bytes()
    assert raw.endswith(b"}\n") and b"\r\n" not in raw
    attrs = (Path(__file__).resolve().parents[3] / ".gitattributes").read_text(encoding="utf-8")
    assert "backend/tests/fixtures/** -text" in attrs  # never converted on checkout


def test_the_goldens_cover_the_planned_cases() -> None:
    e = GOLDEN["expected"]["sequences"]

    def answers(name: str) -> list[Any]:
        return [s["answer"].get("code", s["answer"].get("raises")) for s in e[name]]

    def logs(name: str) -> list[list[str]]:
        return [[a[0] for a in s["appended"]] for s in e[name]]

    assert logs("confirm") == [["outcomes", "actions"]]
    for name in ("confirm-confirm", "confirm-reject", "confirm-not_enough"):  # the prior confirmation, nothing appended
        first, second = e[name]
        assert logs(name) == [["outcomes", "actions"], []]
        assert second["answer"]["body"] == {"ok": True, "already": True, **json.loads(first["appended"][1][1])}
    assert logs("reject-confirm") == [["actions"], ["outcomes", "actions"]]
    assert logs("not_enough-twice") == [["actions"], ["actions"]]
    assert answers("archived-confirm") == [200, 200, 400] and logs("archived-confirm") == [[], [], []]
    assert e["archived-confirm"][0]["answer"]["body"]["outcome_id"] == "oc-acq"
    assert "IndexError" in answers("outcome-refusals") and answers("outcome-refusals").count(400) == 9
    assert answers("audit-explicit") == [200, 400, 200, 200, 400, 400, 400, "IndexError", 200]
    assert all(s["saved"] for s in e["backcast"]) and answers("backcast-refusals")[-2:] == [
        "TypeError",
        "AttributeError",
    ]
    for name in ("seed-then-backcast", "seed-then-confirm", "seed-then-refusal"):  # the not-yet-seeded case
        assert [c[0] for c in e[name][0]["seed"]["changes"]] == ["nw-case-a", "nw-case-b"]
        assert e[name][0]["seed"]["rest"] == {"seeded": ["nw-case-a", "nw-case-b"]}
    assert e["seed-then-backcast"][0]["saved"]["changes"][0][0] == "nw-case-b"
    assert answers("seed-then-refusal") == [400] and logs("seed-then-refusal") == [[]]
    views = {(s["news_view"].get("code"), s["validation_view"].get("code")) for steps in e.values() for s in steps}
    assert views == {(200, 200)}


def test_a_changed_write_is_detected() -> None:
    golden = copy.deepcopy(GOLDEN)
    step = golden["expected"]["sequences"]["confirm"][0]
    step["appended"][1][1] = step["appended"][1][1].replace(", ", ",", 1)
    golden["expected"]["sequences"]["backcast"][5]["saved"]["changes"][0][1] = dict(
        reversed(list(golden["expected"]["sequences"]["backcast"][5]["saved"]["changes"][0][1].items()))
    )
    golden["expected"]["sequences"]["backcast"][0]["news_view"]["sha"] = "0" * 64
    problems = compare_writes(golden)
    assert any(p.startswith("/confirm[0](outcome)/appended") for p in problems)
    assert any(p == "/backcast[5](backcast)/saved: the serialized value differs (key order)" for p in problems)
    assert any(p.startswith("/backcast[0](backcast)/news_view/v/sha") for p in problems)


# ---------------------------------------------------------------------------------------------- the old code
def _literals(path: Path) -> set[str]:
    return {n.value for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}  # fmt: skip


@pytest.mark.skipif(not OLD_NEWS.exists(), reason="the old repository is not checked out")
def test_the_writes_carry_the_old_literals_unchanged() -> None:
    old = _literals(OLD_NEWS)
    tree = ast.parse(Path(writes.__file__).read_text(encoding="utf-8"))
    docs = {id(n.body[0].value) for n in ast.walk(tree)  # docstrings are commentary, not the old data
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body and isinstance(n.body[0], ast.Expr)}  # fmt: skip
    ours = {
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs
    }
    seams = {  # the one new guard, the 027b answer key, the old append's line end
        "audit_miss needs the current Validation inputs (the frozen miss context)",
        "entry",
        "events",
        "\n",
        " ",
    }
    assert sorted(v for v in ours if v not in old and v not in seams) == []


# ------------------------------------------------------------------------------------------- the decisions
def test_once_the_latest_decision_is_confirm_every_valid_decision_answers_it() -> None:
    n, v = world()
    w = run(writes.decide_outcome, {"event_id": "nw-early", "decision": "confirm"}, n, v, hexes("a1"))
    assert w.answer["outcome_id"] == w.validation_appends[0][1].split('"id": "')[1].split('"')[0]
    assert list(w.answer) == ["ok", "kind", "event_id", "decision", "at", "outcome_id"]  # insertion order
    n2, v2 = writes.applied(n, v, w)
    prev = json.loads(w.action_line or "")
    for decision in ("confirm", "reject", "not_enough"):
        again = run(writes.decide_outcome, {"event_id": "nw-early", "decision": decision}, n2, v2)
        assert again == NewsWritten({"ok": True, "already": True, **prev})  # nothing appended
    with pytest.raises(NewsError, match=r"^decision must be confirm, reject or not_enough$"):
        run(writes.decide_outcome, {"event_id": "nw-early", "decision": "maybe"}, n2, v2)  # the decision first


def test_reject_and_not_enough_append_every_time_and_the_last_line_wins() -> None:
    n, v = world()
    for decision in ("reject", "not_enough", "reject"):
        w = run(writes.decide_outcome, {"event_id": "nw-tie-z", "decision": decision}, n, v)
        assert w.validation_appends == [] and w.event is None
        n, v = writes.applied(n, v, w)
    assert core._decisions(n.actions_log)["nw-tie-z"]["decision"] == "reject"
    w = run(writes.decide_outcome, {"event_id": "nw-tie-z", "decision": "confirm"}, n, v, hexes("b2"))
    assert [log for log, _ in w.validation_appends] == ["outcomes"]


def test_the_refusals_keep_the_old_texts_and_order() -> None:
    n, v = world()
    cases: list[tuple[Any, dict[str, Any], str]] = [
        (writes.decide_outcome, {"event_id": "nw-nope", "decision": "x"}, "decision must be confirm, reject or not_enough"),
        (writes.decide_outcome, {"event_id": "nw-nope", "decision": "reject"}, "no such news event"),
        (writes.decide_outcome, {"event_id": "nw-launch", "decision": "confirm"}, "this news event cannot become an outcome"),
        (writes.audit_miss, {"event_id": "nw-unk2"}, "no such news event with a named company"),
        (writes.add_backcast_signal, {"event_id": "nw-nope", "date": "bad", "url": ""}, "date as YYYY, YYYY-MM or YYYY-MM-DD"),
        (writes.add_backcast_signal, {"event_id": "nw-nope", "date": "2025", "url": "x"},
         "a source URL is required — a backcast signal is evidence, not a guess"),
        (writes.add_backcast_signal, {"event_id": "nw-nope", "date": "2025", "url": "https://x.invented.example"}, "no such news event"),
    ]  # fmt: skip
    for op, body, text in cases:
        with pytest.raises(NewsError) as exc:
            run(op, body, n, v, hexes("c3"))
        assert str(exc.value) == text
        assert isinstance(exc.value, ValueError)  # the route's 400
    with pytest.raises(ValidationError, match=r"^event_date is in the future"):
        run(writes.decide_outcome, {"event_id": "nw-w-future", "decision": "confirm"}, n, v, hexes("d4"))
    with pytest.raises(ValidationError, match=r"^why_missed must be one of "):  # after the frozen context (one id)
        run(writes.audit_miss, {"event_id": "nw-miss", "why_missed": "forgot"}, n, v, hexes("e5"))
    with pytest.raises(TypeError):
        writes.audit_miss(n, {"event_id": "nw-miss"}, today=TODAY, now=NOW, new_hex=no_hex)


# ------------------------------------------------------------------------------------------- the encodings
def test_the_three_action_line_encodings_are_the_old_ones() -> None:
    n, v = world()
    o = run(writes.decide_outcome, {"event_id": "nw-w-café", "decision": "confirm"}, n, v, hexes("f6"))
    assert o.action_line == json.dumps(json.loads(o.action_line or ""), ensure_ascii=False, sort_keys=True)
    assert "café" in (o.action_line or "")
    a = run(writes.audit_miss, {"event_id": "nw-w-café"}, n, v, hexes("f7"))
    assert a.action_line is not None and a.action_line.startswith(
        '{"kind": "miss_audit", "event_id": "nw-w-caf\\u00e9", '
    )
    b = run(
        writes.add_backcast_signal,
        {"event_id": "nw-w-café", "date": "2026-09", "url": "https://x.invented.example/é"},
        n,
        v,
    )
    assert b.action_line is not None and b.action_line.startswith(
        '{"kind": "backcast_signal", "event_id": "nw-w-café", "signal": {"date"'
    )
    assert "/é" in b.action_line and b.validation_appends == []


def test_the_ids_come_from_the_027b_seam_once_per_write() -> None:
    n, v = world()
    calls: list[str] = []

    def seam() -> str:
        calls.append("x")
        return "00ff"

    w1 = run(writes.decide_outcome, {"event_id": "nw-early", "decision": "confirm"}, n, v, seam)
    w2 = run(writes.decide_outcome, {"event_id": "nw-early", "decision": "confirm"}, n, v, seam)
    assert len(calls) == 2 and w1 == w2  # reproducible: the same seam, clock and inputs give the same id
    assert w1.answer["outcome_id"].startswith("oc-") and len(w1.answer["outcome_id"]) == 13
    a = run(writes.audit_miss, {"event_id": "nw-miss"}, n, v, seam)
    assert a.answer["audit"]["id"].startswith("au-") and len(calls) == 3


# ------------------------------------------------------------------------------------------- the backcast
def test_a_backcast_returns_the_whole_record_in_stored_key_order() -> None:
    n, v = world()
    stored = core.load(n.events)["events"]["nw-w-nobc"]
    w = run(
        writes.add_backcast_signal,
        {"event_id": "nw-w-nobc", "date": "2026-09", "url": " https://x.invented.example "},
        n,
        v,
    )
    assert w.event is not None
    eid, record = w.event
    assert eid == "nw-w-nobc" and list(record) == [*stored, "backcast"]  # setdefault: the new key last
    assert record["backcast"] == [w.answer["signal"]] and w.answer["signal"]["url"] == "https://x.invented.example"
    assert w.answer["signal"]["precision"] == "month"
    n2, v2 = writes.applied(n, v, w)
    assert core.load(n2.events)["events"]["nw-w-nobc"] == record and v2.news is n2.events
    assert list(core.load(n2.events)["events"]) == list(core.load(n.events)["events"])  # the archive order kept
    assert n2.actions_log == n.actions_log + (w.action_line or "") + "\n"
    curated = run(
        writes.add_backcast_signal,
        {"event_id": "nw-unk", "date": "2026-10-01", "url": "http://x.invented.example"},
        n,
        v,
    )
    assert (
        core.check(curated.event[1] if curated.event else {}, v.news_inputs.entities or {}, "2026-09-27")["state"]
        == "MISSED"
    )


def test_the_writes_never_modify_their_inputs() -> None:
    n, v = world()
    before = (copy.deepcopy(n), copy.deepcopy(v))
    bodies = [
        (writes.decide_outcome, {"event_id": "nw-early", "decision": "confirm"}),
        (writes.audit_miss, {"event_id": "nw-miss"}),
        (writes.add_backcast_signal, {"event_id": "nw-miss", "date": "2026", "url": "https://x.invented.example"}),
        (writes.add_backcast_signal, {"event_id": "nw-w-nobc", "date": "2026", "url": "https://x.invented.example"}),
    ]
    for op, body in bodies:
        run(op, body, n, v, hexes("01"))
    assert (n, v) == before


# ------------------------------------------------------------------------------------------- the seeding
def test_ensure_seeded_is_the_guarded_old_seeding_with_its_changes() -> None:
    docs = writes_docs()
    events = docs["news/events.json"]
    before = copy.deepcopy(events)
    cases = tuple(sorted(docs[CASES_KEY].items()))
    doc, changes = writes.ensure_seeded(events, cases, NOW)
    assert events == before  # pure
    assert [c.event_id for c in changes] == ["nw-case-a", "nw-case-b"]
    assert isinstance(changes[0], SeedChange) and changes[0].before == before["events"]["nw-case-a"]
    assert changes[1].before is None and changes[1].after == doc["events"]["nw-case-b"]
    assert list(doc["events"])[-1] == "nw-case-b" and doc["seeded"] == ["nw-case-a", "nw-case-b"]
    assert (doc, len(changes)) == core.seed_cases(events, cases, NOW)  # reused, not duplicated
    again, none = writes.ensure_seeded(doc, cases, NOW)  # idempotent: the guard is now false
    assert again is doc and none == []
    assert writes.ensure_seeded(events, None, NOW) == (events, [])  # no case folder
    stored = {**case_b(), "ingested_at": "2026-10-01T09:00:00", "card": None, "entity_key": "x", "materiality": "HIGH",
              "materiality_why": []}  # fmt: skip
    noop = {"events": {"nw-case-b": stored}, "seeded": []}
    assert writes.ensure_seeded(noop, (("case-b.json", case_text(case_b())),), NOW) == (noop, [])  # nothing added
    with pytest.raises(json.JSONDecodeError):  # a ValueError: the old seeding raised too
        writes.ensure_seeded({"events": {}, "seeded": []}, (("x.json", "{not json"),), NOW)


def test_a_write_on_a_case_seeded_in_the_same_transaction() -> None:
    v = validation_inputs(writes_docs(), TODAY)
    n = v.news_inputs
    with pytest.raises(NewsError, match=r"^no such news event$"):  # before the seeding the case does not exist
        run(
            writes.add_backcast_signal,
            {"event_id": "nw-case-b", "date": "2020", "url": "https://x.invented.example"},
            n,
            v,
        )
    n, v = world()
    w = run(
        writes.add_backcast_signal, {"event_id": "nw-case-b", "date": "2020", "url": "https://x.invented.example"}, n, v
    )
    assert w.event is not None and w.event[1]["curated"] is True and len(w.event[1]["backcast"]) == 3


def test_the_parity_module_documents_the_writes_modes() -> None:
    assert "writes-goldens" in (parity_news.__doc__ or "") and "writes-check" in (parity_news.__doc__ or "")
    readme = (WRITES_GOLDEN.parent / "README.md").read_bytes()
    assert b"`oracle_news_writes.json` (review 028b)" in readme
    assert readme.count(b"\n") == readme.count(b"\r\n")  # the README keeps its CRLF line ends

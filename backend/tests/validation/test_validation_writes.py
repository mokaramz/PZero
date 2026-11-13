"""Review 027b, offline: the pure Validation writes (``validation/writes.py``) match the OLD writes' goldens
(``oracle_validation_writes.json``, ``python -m projectzero.ops.parity_validation writes-goldens``): the answers, the
appended lines byte for byte and the next view, with only the declared (e), (f) and (g). Also: the id / clock seam, the
Berlin clock, the old refusal texts, retraction routing over the CURRENT logs, the miss context built before
``why_missed`` is validated, the two former-500 CSVs, the verified packet mark and purity."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from projectzero.ops.parity_ranking import OLD_REPO
from projectzero.ops.parity_validation import (
    CLOCK,
    SETS,
    WRITE_STEPS,
    WRITE_WORLDS,
    compare_writes,
    jl,
    main_docs,
)
from projectzero.validation import ValidationError, inputs_from_docs, scout_packet, view, writes
from projectzero.validation.catalog import KINDS, MISS_REASONS, REAL_WORLD_STRONG

GOLDEN: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "golden_v1" / "oracle_validation_writes.json").read_text(
        encoding="utf-8"
    )
)
OLD_VALIDATION = OLD_REPO / "backend" / "src" / "projectzero" / "services" / "validation.py"
TODAY = date(2026, 11, 12)
NOW = datetime(2026, 11, 12, 10, 0)


def hexes(*values: str) -> Any:
    seq = list(values)
    return lambda: seq.pop(0)


def main_inputs() -> Any:
    return inputs_from_docs(main_docs(), TODAY)


def empty_inputs() -> Any:
    return inputs_from_docs({}, TODAY)


# ------------------------------------------------------------------ the goldens
def test_provenance_and_inputs_are_current() -> None:
    assert GOLDEN["provenance"]["old_revision"] == "6c739b9cb6ca2517b845e381d39a36c50eccc59e"
    assert GOLDEN["provenance"]["old_dirty"] is False
    assert GOLDEN["clock"] == CLOCK
    assert tuple(GOLDEN["sets"]) == WRITE_WORLDS
    for name in WRITE_WORLDS:
        assert json.dumps(GOLDEN["sets"][name]["docs"]) == json.dumps(json.loads(json.dumps(SETS[name]()))), name
        assert GOLDEN["sets"][name]["steps"] == json.loads(json.dumps(WRITE_STEPS[name]())), name
        assert GOLDEN["sets"][name]["expected"]["changed"] == []  # the old writes went to memory only


def test_the_pure_writes_match_the_old_code_with_only_the_declared_differences() -> None:
    problems, declared = compare_writes(GOLDEN)
    assert problems == []
    assert declared == {"e": 4, "f": 5, "g": 2}


def test_the_goldens_cover_the_planned_cases() -> None:
    main = GOLDEN["sets"]["main"]
    pairs = list(zip(main["steps"], main["expected"]["steps"], strict=True))
    ok = [(s, x) for s, x in pairs if x["answer"].get("code") == 200]
    errors = {x["answer"]["error"] for _, x in pairs if x["answer"].get("code") == 400}
    kinds = {(s["body"]["kind"], bool(s["body"].get("evidence_url"))) for s, _ in ok if s["op"] == "outcome"}
    assert {k for k, _ in kinds} == set(KINDS)
    assert {k for k, url in kinds if not url} == set(KINDS) - set(REAL_WORLD_STRONG)
    misses = [x["answer"]["body"]["entry"] for s, x in ok if s["op"] == "audit" and s["body"]["type"] == "miss"]
    assert {m["why_missed"] for m in misses} == set(MISS_REASONS)
    assert {m["miss_type"] for m in misses} >= {"never_found", "found_too_late", "watch_not_followed",
                                                "found_early_but_rejected", "found_early_not_progressed"}  # fmt: skip
    assert {
        "event_date is in the future — record outcomes only once they have happened",
        "company required",
        "no such entry",
        "a retraction needs a reason (at least 8 characters)",
        "no rows in the CSV",
        "system name (e.g. Dealroom) and the CSV text are required",
        "a real-world outcome needs an evidence URL (never recorded from memory)",
        "type (miss | false_positive) and company required",
    } <= errors
    assert any(e.startswith("why_missed must be one of") for e in errors)
    assert any(e.startswith("at least one cause from") for e in errors)
    assert any(e.startswith("could not find the name / date columns") for e in errors)
    retracted = [x["appended"][0][0] for s, x in ok if s["op"] == "retract"]
    assert "outcomes" in retracted and "audits" in retracted
    bench = [x["answer"]["body"] for s, x in ok if s["op"] == "benchmark"]
    assert any(b["skipped"] and b["matched_to_pz"] and b["usable"] > b["matched_to_pz"] for b in bench)
    assert {b["imported"] for b in bench} == {True, False}
    assert sorted(x["answer"]["raises"] for _, x in pairs if "raises" in x["answer"]) == [
        "AttributeError", "AttributeError", "Error"]  # fmt: skip  # the former 500s
    assert [s["op"] for s, _ in pairs].count("mark") == 4


# ------------------------------------------------------------------ the id and clock seam
def test_ids_are_the_old_format_with_the_seam_in_place_of_the_timestamp() -> None:
    w = writes.outcome(empty_inputs(), {"kind": "accelerator", "company": " Invented Seam Co ", "event_date": "2026-11-01"},
                       today=TODAY, now=NOW, new_hex=hexes("abc123"))  # fmt: skip
    raw = "Invented Seam Co|accelerator|2026-11-12T10:00:00|abc123"
    assert w.answer["entry"]["id"] == "oc-" + hashlib.sha1(raw.encode()).hexdigest()[:10]
    again = writes.outcome(empty_inputs(), {"kind": "accelerator", "company": "Invented Seam Co", "event_date": "2026-11-01"},
                           today=TODAY, now=NOW, new_hex=hexes("abc124"))  # fmt: skip
    assert again.answer["entry"]["id"] != w.answer["entry"]["id"]  # a double POST is two rows, two ids
    calls: list[str] = []

    def counted() -> str:
        calls.append("x")
        return f"{len(calls):04x}"

    csv = "name,date\nInvented One Co,2026-10-01\nInvented One Co,2026-10-01\n"
    b = writes.benchmark_import(empty_inputs(), {"system": "Invented DB", "csv": csv, "confirm": True},
                                today=TODAY, now=NOW, new_hex=counted)  # fmt: skip
    assert len(calls) == 2 and len({json.loads(line)["id"] for _, line in b.appends}) == 2
    assert all(json.loads(line)["id"].startswith("bm-") for _, line in b.appends)


def test_recorded_at_is_berlin_wall_time_and_the_future_check_uses_the_berlin_day() -> None:
    instant = datetime(2026, 11, 12, 23, 30, tzinfo=UTC)  # 00:30 on 13 November in Berlin
    day = date(2026, 11, 13)
    w = writes.outcome(empty_inputs(), {"kind": "accelerator", "company": "Invented Clock Co", "event_date": "2026-11-13"},
                       today=day, now=instant, new_hex=hexes("1"))  # fmt: skip
    assert w.answer["entry"]["recorded_at"] == "2026-11-13T00:30:00"
    with pytest.raises(ValidationError, match="event_date is in the future"):
        writes.outcome(empty_inputs(), {"kind": "accelerator", "company": "Invented Clock Co", "event_date": "2026-11-14"},
                       today=day, now=instant, new_hex=hexes("1"))  # fmt: skip


def test_the_answer_keeps_insertion_order_and_the_line_is_sorted() -> None:
    w = writes.audit(empty_inputs(), {"type": "false_positive", "company": "Invented Ordré Co", "causes": ["other"]},
                     today=TODAY, now=NOW, new_hex=hexes("1"))  # fmt: skip
    entry = w.answer["entry"]
    assert list(w.answer) == ["ok", "entry"] and w.answer["ok"] is True
    assert list(entry) == [
        "id",
        "type",
        "recorded_at",
        "company",
        "entity_key",
        "note",
        "supersedes",
        "causes",
        "lesson",
    ]
    assert w.appends == [("audits", json.dumps(entry, ensure_ascii=False, sort_keys=True))]
    assert "Ordré" in w.appends[0][1]  # ensure_ascii=False, as the old line


# ------------------------------------------------------------------ the writes
def test_retract_searches_the_current_outcomes_then_audits_and_appends_where_it_found() -> None:
    inputs = dataclasses.replace(
        empty_inputs(),
        outcomes_log=jl([{"id": "x-both", "kind": "accelerator"}]),
        audits_log=jl([{"id": "x-both"}, {"id": "au-only"}]),
    )
    w = writes.retract(
        inputs, {"id": "x-both", "reason": "a long enough reason"}, today=TODAY, now=NOW, new_hex=hexes("1")
    )
    assert [log for log, _ in w.appends] == ["outcomes"]
    w = writes.retract(
        inputs, {"id": "au-only", "reason": "a long enough reason"}, today=TODAY, now=NOW, new_hex=hexes("1")
    )
    assert [log for log, _ in w.appends] == ["audits"]
    assert list(w.answer["entry"]) == ["id", "retracts", "recorded_at", "reason"]
    with pytest.raises(ValidationError, match=r"^no such entry$"):
        writes.retract(
            inputs, {"id": "oc-later", "reason": "a long enough reason"}, today=TODAY, now=NOW, new_hex=hexes("1")
        )
    later = writes.outcome(inputs, {"kind": "accelerator", "company": "Invented Later Co", "event_date": "2026-11-01"},
                           today=TODAY, now=NOW, new_hex=hexes("1"))  # fmt: skip
    current = writes.appended(inputs, later.appends)
    rid = later.answer["entry"]["id"]
    w = writes.retract(current, {"id": rid, "reason": "a long enough reason"}, today=TODAY, now=NOW, new_hex=hexes("1"))
    assert w.appends[0][0] == "outcomes" and json.loads(w.appends[0][1])["retracts"] == rid
    with pytest.raises(ValidationError, match="at least 8 characters"):  # the reason is checked first
        writes.retract(current, {"id": "nothing", "reason": " 1234567 "}, today=TODAY, now=NOW, new_hex=hexes("1"))


def test_a_miss_builds_its_context_before_why_missed_is_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    real = writes.entities

    def spy(inputs: Any, today: date) -> Any:
        seen.append(today.isoformat())
        return real(inputs, today)

    monkeypatch.setattr(writes, "entities", spy)
    with pytest.raises(ValidationError, match=r"^why_missed must be one of source_not_covered, "):
        writes.audit(main_inputs(), {"type": "miss", "company": "Invented Watch Optics", "why_missed": "forgot"},
                     today=TODAY, now=NOW, new_hex=hexes("1"))  # fmt: skip
    assert seen == ["2026-11-12"]
    w = writes.audit(main_inputs(), {"type": "miss", "company": "Invented Watch Optics", "why_missed": "other",
                                     "preventable": "maybe"}, today=TODAY, now=NOW, new_hex=hexes("1"))  # fmt: skip
    e = w.answer["entry"]
    assert e["miss_type"] == "watch_not_followed" and e["preventable"] == "unclear"
    assert e["pz_state_at_audit"]["inbox_decision"] == "watch"


def test_the_two_former_500_csvs_are_refused_and_append_nothing() -> None:
    for csv in ("name,date\nInvented Extra Co,2026-10-01,surplus\n", "name,date\nInvented\rBroken Co,2026-10-01\n"):
        with pytest.raises(ValidationError, match=r"^the CSV could not be read: "):
            writes.benchmark_import(empty_inputs(), {"system": "Invented DB", "csv": csv, "confirm": True},
                                    today=TODAY, now=NOW, new_hex=hexes(*"abc"))  # fmt: skip
    # a LATER row with extra fields was never a 500: the old code read it
    csv = "name,date\nInvented Good Co,2026-10-01\nInvented Extra Co,2026-10-02,surplus\n"
    w = writes.benchmark_import(empty_inputs(), {"system": "Invented DB", "csv": csv, "confirm": True},
                                today=TODAY, now=NOW, new_hex=hexes(*"ab"))  # fmt: skip
    assert w.answer["usable"] == 2 and len(w.appends) == 2 and "ok" not in w.answer


def test_a_preview_appends_nothing_and_a_confirm_appends_every_usable_row_in_order() -> None:
    csv = (
        "Company,Date\nInvented Alpha Robotics,2026-10-01\nInvented Nobody Co,2026-10-02\nInvented Late Co,2027-01-01\n"
    )
    body = {"system": "Invented DB", "csv": csv}
    preview = writes.benchmark_import(main_inputs(), body, today=TODAY, now=NOW, new_hex=hexes())
    assert preview.appends == [] and preview.answer["imported"] is False
    assert (preview.answer["usable"], preview.answer["skipped"], preview.answer["matched_to_pz"]) == (2, 1, 1)
    done = writes.benchmark_import(main_inputs(), {**body, "confirm": True}, today=TODAY, now=NOW, new_hex=hexes(*"ab"))
    assert [json.loads(line)["company"] for _, line in done.appends] == [
        "Invented Alpha Robotics",
        "Invented Nobody Co",
    ]
    assert {log for log, _ in done.appends} == {"outcomes"}
    assert list(done.answer) == ["system", "rows", "usable", "skipped", "matched_to_pz", "name_column", "date_column",
                                 "imported", "file_sha"]  # fmt: skip


def test_the_packet_mark_logs_the_shown_sha_and_refuses_a_stale_packet() -> None:
    inputs = main_inputs()
    shown = scout_packet(inputs, "c-9", TODAY, NOW)
    generated = writes.generated_at(shown["text"])
    assert generated == "2026-11-12T10:00:00"
    later = datetime(2026, 11, 12, 10, 5)  # the user copies a few minutes later
    w = writes.packet_mark(
        inputs, {"cycle": "c-9", "generated": generated, "sha": shown["sha"]}, today=TODAY, now=later
    )
    assert w.answer == shown
    row = json.loads(w.appends[0][1])
    assert w.appends[0][0] == "scout_feedback"
    assert row == {"at": "2026-11-12T10:05:00", "cycle": "c-9", "companies": shown["companies"], "sha": shown["sha"],
                   "handed_over": True}  # fmt: skip
    assert w.appends[0][1] == json.dumps(row, sort_keys=True)
    # the data changed since the packet was prepared: a new miss is in every packet
    miss = writes.audit(inputs, {"type": "miss", "company": "Invented New Miss Co", "why_missed": "other"},
                        today=TODAY, now=later, new_hex=hexes("1"))  # fmt: skip
    changed = writes.appended(inputs, miss.appends)
    with pytest.raises(writes.StalePacket) as stale:
        writes.packet_mark(
            changed, {"cycle": "c-9", "generated": generated, "sha": shown["sha"]}, today=TODAY, now=later
        )
    assert str(stale.value) == "the packet changed since it was prepared — prepare it again"
    assert not isinstance(stale.value, ValidationError)  # the route's 409, not a 400
    with pytest.raises(writes.StalePacket):
        writes.packet_mark(inputs, {"cycle": "", "generated": generated, "sha": shown["sha"]}, today=TODAY, now=later)
    for bad in ("", "2026-11-12 10:00", None):
        with pytest.raises(ValidationError, match=r"^generated "):
            writes.packet_mark(inputs, {"cycle": "c-9", "generated": bad, "sha": shown["sha"]}, today=TODAY, now=later)


def test_the_mark_renders_on_the_day_the_packet_was_generated_and_escapes_like_the_old_line() -> None:
    inputs = empty_inputs()
    at = datetime(2026, 11, 11, 23, 59, 59)
    shown = scout_packet(inputs, "cÿcle-ü", at.date(), at)
    body = {"cycle": "cÿcle-ü", "generated": writes.generated_at(shown["text"]), "sha": shown["sha"]}
    w = writes.packet_mark(inputs, body, today=TODAY, now=datetime(2026, 11, 12, 0, 0, 5))  # after midnight
    assert '"cycle": "c\\u00ffcle-\\u00fc"' in w.appends[0][1]  # the old mark dump kept ensure_ascii
    assert writes.generated_at("no packet") == ""


def test_writes_are_pure_and_appended_grows_the_logs_like_the_old_file() -> None:
    inputs = main_inputs()
    before = copy.deepcopy(inputs)
    w = writes.outcome(inputs, {"kind": "accelerator", "company": "Invented Pure Co", "event_date": "2026-11-01"},
                       today=TODAY, now=NOW, new_hex=hexes("1"))  # fmt: skip
    assert inputs == before
    with pytest.raises(dataclasses.FrozenInstanceError):
        w.answer = {}  # type: ignore[misc]
    after = writes.appended(inputs, w.appends)
    assert after.outcomes_log == inputs.outcomes_log + w.appends[0][1] + "\n"
    assert after.audits_log == inputs.audits_log and after.scout_log == inputs.scout_log
    assert view(after, TODAY, NOW)["outcomes"][-1] == w.answer["entry"]
    torn = dataclasses.replace(empty_inputs(), outcomes_log='{"id": "oc-torn"}')  # no final newline: glued, as before
    assert writes.appended(torn, w.appends).outcomes_log.startswith('{"id": "oc-torn"}{')


@pytest.mark.skipif(not OLD_VALIDATION.exists(), reason="the old repository is not checked out")
def test_every_refusal_text_is_the_old_one() -> None:
    old = OLD_VALIDATION.read_text(encoding="utf-8")
    for text in (
        "unknown outcome kind {kind!r}",
        "company required",
        "event_date (YYYY-MM-DD) required — when it happened in the world, not when you noticed",
        "event_date is in the future — record outcomes only once they have happened",
        "a real-world outcome needs an evidence URL (never recorded from memory)",
        "type (miss | false_positive) and company required",
        "why_missed must be one of {', '.join(MISS_REASONS)}",
        "at least one cause from {', '.join(FP_CAUSES)}",
        "a retraction needs a reason (at least 8 characters)",
        "no such entry",
        "system name (e.g. Dealroom) and the CSV text are required",
        "no rows in the CSV",
        "could not find the name / date columns — columns are: {', '.join(rows[0])}",
    ):
        assert text in old, text
        assert text in Path(writes.__file__ or "").read_text(encoding="utf-8"), text

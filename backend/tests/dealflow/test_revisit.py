"""Revisit flags (decision 0004, review 018, Codex H-127): the rule in every branch, the Berlin calendar day, and the
contract field."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from projectzero.dealflow import revisit
from projectzero.dealflow.intake.contract import (
    MATERIAL_CHANGE_KIND,
    MATERIAL_CHANGE_SUPPORT,
    MATERIAL_CHANGE_URL,
    validate_entity,
)

URL = "https://news.example.com/series-a"
REJECTED = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)  # 11:00 in Berlin, 1 Oct


def entity(
    kind: str = "funding_round", since: str | None = "2026-10-15", note: str | None = None, **kw: Any
) -> dict[str, Any]:
    change = (
        {"kind": kind, "evidence_url": URL} | ({"since": since} if since else {}) | ({"note": note} if note else {})
    )
    return {"kind": "company", "name": "Example Robotics GmbH", "key_fact": "Raised a seed round.",
            "evidence": [{"url": URL}], "material_change": change, **kw}  # fmt: skip


def run(e: dict[str, Any], *, status: str = "rejected", decided_at: datetime | None = REJECTED,
        changes: list[dict[str, Any]] | None = None, flags: list[dict[str, Any]] | None = None) -> revisit.Outcome:  # fmt: skip
    return revisit.evaluate(e, status=status, decided_at=decided_at, earlier_changes=changes or [],
                            earlier_flags=flags or [], submission_id="sub-1")  # fmt: skip


def test_a_dated_change_after_the_rejection_is_flagged_with_its_evidence_and_date() -> None:
    out = run(entity(note="A new lead investor."))
    assert out.reason == "flagged"
    assert out.flag == {"kind": "funding_round", "since": "2026-10-15", "date_source": "since",
                        "rejected_on": "2026-10-01", "evidence_url": URL, "evidence": [{"url": URL}],
                        "note": "A new lead investor.", "submission_id": "sub-1"}  # fmt: skip


def test_without_since_the_signal_date_is_the_change_date() -> None:
    out = run(entity(since=None, signal_date="2026-10-20"))
    assert out.flag is not None and (out.flag["since"], out.flag["date_source"]) == ("2026-10-20", "signal_date")


@pytest.mark.parametrize(
    ("e", "kw", "reason"),
    [
        (entity(), {"status": "new"}, "not_rejected"),
        (entity(), {"status": "archived"}, "not_rejected"),  # rejected only (c)
        (entity(), {"decided_at": None}, "unknown_rejection_date"),  # never surface a historical change as new
        (entity(since=None), {}, "undated"),
        (entity(since="not a date"), {}, "undated"),
        (entity(since="2026-10-01"), {}, "before_rejection"),  # the SAME Berlin day is not later
        (entity(since="2026-09-30"), {}, "before_rejection"),
        ({k: v for k, v in entity().items() if k != "material_change"}, {}, "no_change"),
    ],
)
def test_what_is_not_flagged_and_why(e: dict[str, Any], kw: dict[str, Any], reason: str) -> None:
    out = run(e, **kw)
    assert (out.flag, out.reason) == (None, reason)


def test_the_rejection_day_is_the_berlin_calendar_day() -> None:
    late = datetime(2026, 10, 1, 22, 30, tzinfo=UTC)  # 00:30 on 2 Oct in Berlin, while UTC still says 1 Oct
    assert run(entity(since="2026-10-02"), decided_at=late).reason == "before_rejection"
    assert run(entity(since="2026-10-03"), decided_at=late).reason == "flagged"
    early = datetime(2026, 10, 1, 21, 59, tzinfo=UTC)  # 23:59 on 1 Oct in Berlin
    assert run(entity(since="2026-10-02"), decided_at=early).reason == "flagged"


FIRST = "https://registry.example.org/notice/7"  # an earlier report of the change, from another source


def corroborating(*cited: str) -> dict[str, Any]:
    """A corroboration whose own source is ``URL`` and which cites ``cited`` too."""
    return entity(kind="independent_corroboration", evidence=[{"url": URL}, *({"url": u} for u in cited)])


def test_independent_corroboration_needs_an_earlier_report_of_the_same_change_from_another_source() -> None:
    earlier = [{"evidence_url": FIRST, "submission_id": "sub-0"}]
    assert run(corroborating()).reason == "single_source"  # one URL alone
    assert run(corroborating(FIRST)).reason == "single_source"  # cites a URL no earlier change reported
    # Codex H-129: an unrelated earlier report on another host (it is not cited here) never qualifies
    assert run(corroborating(), changes=earlier).reason == "single_source"
    assert run(corroborating("https://blog.example.net/p"), changes=earlier).reason == "single_source"
    # the cited earlier change from the SAME source is not independent (www. folded)
    same = [{"evidence_url": "https://www.news.example.com/first", "submission_id": "sub-0"}]
    assert run(corroborating("https://www.news.example.com/first"), changes=same).reason == "single_source"
    out = run(corroborating(FIRST), changes=earlier)
    assert out.reason == "flagged" and out.flag is not None
    assert out.flag["corroboration"] == [{"evidence_url": FIRST, "submission_id": "sub-0"},
                                         {"evidence_url": URL, "submission_id": "sub-1"}]  # fmt: skip


def supported(*support: str, general: tuple[str, ...] = ()) -> dict[str, Any]:
    """A FIRST corroboration report naming ``support`` as reporting this change; ``general`` is other evidence."""
    e = corroborating(*support, *general)
    e["material_change"] = {**e["material_change"], "supporting_urls": list(support)}
    return e


def test_a_first_report_with_two_independent_sources_for_the_change_is_flagged() -> None:
    """Codex H-131: two sources named for THIS change in one delivery qualify, with no earlier report."""
    out = run(supported(FIRST))
    assert out.reason == "flagged" and out.flag is not None
    assert out.flag["corroboration"] == [{"evidence_url": FIRST, "submission_id": "sub-1"},
                                         {"evidence_url": URL, "submission_id": "sub-1"}]  # fmt: skip


def test_general_company_evidence_and_the_same_source_never_count() -> None:
    # the second URL is only general company evidence (not named as supporting the change)
    assert run(corroborating("https://blog.example.net/p")).reason == "single_source"
    assert run(supported(general=(FIRST,))).reason == "single_source"
    # a supporting URL on the change's own source (www. folded) is not independent
    assert run(supported("https://www.news.example.com/other")).reason == "single_source"


def test_the_earlier_report_and_a_supporting_url_are_both_kept() -> None:
    earlier = [{"evidence_url": FIRST, "submission_id": "sub-0"}]
    third = "https://blog.example.net/ceo"
    e = supported(third, general=(FIRST,))
    out = run(e, changes=earlier)
    assert out.flag is not None and out.flag["corroboration"] == [
        {"evidence_url": FIRST, "submission_id": "sub-0"},
        {"evidence_url": third, "submission_id": "sub-1"},
        {"evidence_url": URL, "submission_id": "sub-1"},
    ]


def test_other_kinds_carry_no_corroboration() -> None:
    out = run(entity())
    assert out.flag is not None and "corroboration" not in out.flag


def test_one_flag_per_change_within_the_current_rejection() -> None:
    first = run(entity())
    assert first.flag is not None
    assert run(entity(), flags=[first.flag]).reason == "already_flagged"
    other = entity(kind="founder_or_key_hire")
    assert run(other, flags=[first.flag]).reason == "flagged"  # a different change is flagged


# ── the contract field ──────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "kind", ["funding_round", "registry_event", "founder_or_key_hire", "independent_corroboration"]
)
def test_the_field_is_accepted_with_each_kind(kind: str) -> None:
    assert validate_entity(entity(kind=kind, note="Short note.")) == []
    assert validate_entity({**entity(kind=kind), "kind": "opportunity"}) == []


@pytest.mark.parametrize(
    ("change", "where"),
    [
        ({"kind": "rumour", "evidence_url": URL}, "$/material_change/kind"),
        ({"kind": "funding_round"}, "$/material_change"),
        ({"kind": "funding_round", "evidence_url": URL, "since": "15.10.2026"}, "$/material_change/since"),
        ({"kind": "funding_round", "evidence_url": URL, "extra": 1}, "$/material_change"),
    ],
)
def test_a_malformed_field_is_refused(change: dict[str, Any], where: str) -> None:
    issues = validate_entity({**entity(), "material_change": change})
    assert issues and any(str(i).startswith(where) for i in issues)


def test_the_evidence_url_must_be_one_the_entity_cites() -> None:
    e = {**entity(), "material_change": {"kind": "funding_round", "evidence_url": "https://elsewhere.example.com/x"}}
    assert [str(i) for i in validate_entity(e)] == [f"$/material_change/evidence_url: {MATERIAL_CHANGE_URL}"]


@pytest.mark.parametrize("kind", ["person", "event"])
def test_the_field_is_refused_on_people_and_events(kind: str) -> None:
    e = {**entity(), "kind": kind}
    if kind == "event":
        e["event"] = {"starts_on": "2026-12-04"}
    assert f"$/material_change: {MATERIAL_CHANGE_KIND}" in [str(i) for i in validate_entity(e)]


def test_supporting_urls_must_be_cited_by_the_entity() -> None:
    ok = supported(FIRST)
    assert validate_entity(ok) == []
    bad = {**ok, "evidence": [{"url": URL}]}  # FIRST is named as supporting but not cited
    assert [str(i) for i in validate_entity(bad)] == [f"$/material_change/supporting_urls: {MATERIAL_CHANGE_SUPPORT}"]
    empty = {**ok, "material_change": {**ok["material_change"], "supporting_urls": []}}
    assert any(str(i).startswith("$/material_change/supporting_urls") for i in validate_entity(empty))

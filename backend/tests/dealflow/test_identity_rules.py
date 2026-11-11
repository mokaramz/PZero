"""Live intake identity decisions (decision 0001, one record at a time)."""

from __future__ import annotations

import pytest

from projectzero.dealflow.identity_rules import StoredCompany, decide, origin_family, strong_conflict


def company(cid: str, *families: str, keys: frozenset[tuple[str, str, str]] = frozenset()) -> StoredCompany:
    return StoredCompany(cid, frozenset(families), keys)


def test_grok_continues_scout00_and_registry_scans_continue_dealflow() -> None:
    assert origin_family("grok") == origin_family("legacy_scout00") == "scout"
    assert origin_family("registry_scan") == origin_family("legacy_dealflow") == "dealflow"


def test_one_strong_owner_joins() -> None:
    d = decide(family="scout", strong_keys=[("domain", "", "a.com")], owners=["c1"], same_name=[], has_usable_name=True)
    assert (d.action, d.company_id, d.basis) == ("join", "c1", "strong_identifier")


def test_two_strong_owners_is_a_conflict_and_never_a_join() -> None:
    d = decide(
        family="scout", strong_keys=[], owners=["c1", "c2"], same_name=[company("c3", "dealflow")], has_usable_name=True
    )
    assert d.action == "conflict" and d.company_id is None


def test_unique_same_name_from_another_origin_joins() -> None:
    d = decide(family="scout", strong_keys=[], owners=[], same_name=[company("c1", "dealflow")], has_usable_name=True)
    assert (d.action, d.company_id, d.basis) == ("join", "c1", "same_name_cross_origin")


def test_conviction_company_counts_as_another_origin() -> None:
    d = decide(family="scout", strong_keys=[], owners=[], same_name=[company("c1", "conviction")], has_usable_name=True)
    assert d.action == "join"


def test_same_name_same_origin_creates_and_suggests() -> None:
    d = decide(
        family="scout", strong_keys=[], owners=[], same_name=[company("c1", "scout", "dealflow")], has_usable_name=True
    )
    assert d.action == "create" and d.suggest_with == ("c1",) and "ambiguous" in d.detail


def test_same_name_with_a_conflicting_domain_creates_and_suggests() -> None:
    other = company("c1", "dealflow", keys=frozenset({("domain", "", "kontext-ai.com")}))
    d = decide(
        family="scout",
        strong_keys=[("domain", "", "kontext.legal")],
        owners=[],
        same_name=[other],
        has_usable_name=True,
    )
    assert d.action == "create" and d.suggest_with == ("c1",) and "domain" in d.detail


def test_same_name_held_by_two_companies_is_ambiguous() -> None:
    d = decide(
        family="manual",
        strong_keys=[],
        owners=[],
        same_name=[company("c1", "dealflow"), company("c2", "scout")],
        has_usable_name=True,
    )
    assert d.action == "create" and d.suggest_with == ("c1", "c2")


def test_placeholder_name_without_strong_ids_gets_no_company() -> None:
    d = decide(family="scout", strong_keys=[], owners=[], same_name=[], has_usable_name=False)
    assert d.action == "none" and d.company_id is None


def test_strong_conflict_compares_same_kind_and_namespace_only() -> None:
    held = [("registry", "duns", "1"), ("domain", "", "a.com")]
    assert strong_conflict(held, [("registry", "duns", "2")]) == ("registry", "duns", "2")
    assert strong_conflict(held, [("registry", "handelsregister", "2")]) is None
    assert strong_conflict(held, [("domain", "", "a.com")]) is None


# ── plan_delivery: a delivery is decided as a whole ─────────────────────────────────────────────────────────────

from projectzero.dealflow.identity_rules import EntityFacts, plan_delivery  # noqa: E402


@pytest.mark.parametrize("reverse", [False, True])
def test_name_only_record_is_ambiguous_next_to_a_strongly_matched_namesake(reverse: bool) -> None:
    """Codex rev 2: Twin Labs (known domain -> stored company) + Twin Labs (name only) in one delivery."""
    strong = EntityFacts(0 if not reverse else 1, (("domain", "", "twin-labs.com"),), "twin labs")
    name_only = EntityFacts(1 if not reverse else 0, (), "twin labs")
    facts = [strong, name_only] if not reverse else [name_only, strong]
    plan = plan_delivery(facts, {("domain", "", "twin-labs.com"): "stored-manual"})
    by_member = {g.members: g for g in plan.groups}
    strong_group = by_member[(strong.index,)]
    name_group = by_member[(name_only.index,)]
    assert strong_group.stored_company == "stored-manual"  # the strong match is kept
    assert name_group.stored_company is None and name_group.name_ambiguous  # the other may not join by name


def test_unrelated_names_in_one_delivery_stay_unambiguous() -> None:
    plan = plan_delivery([EntityFacts(0, (), "kontext"), EntityFacts(1, (), "twin labs")], {})
    assert [g.name_ambiguous for g in plan.groups] == [False, False]

"""Review 018 acceptance tests (decision 0004, Codex H-127) against the hosted project, in throw-away scratch schemas:

* a dated material change after the rejection flags the rejected candidate (an event, never a status change), and the
  Deal Flow inbox shows it and counts it;
* a reopen clears the flag, and a NEW rejection never revives the old one;
* an imported rejection without a date keeps the report but is not flagged (``unknown_rejection_date``);
* two deliveries of the same change leave one flag;
* a re-report racing a manual reopen: the observation survives, and the list and count agree with the final decision.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC
from typing import Any

import pytest
from tests.hosted.test_intake_hosted import company, delivery, query, schema, settings, submit

from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.dealflow.candidates import DealFlowStore
from projectzero.dealflow.inbox_view import inbox_view
from projectzero.dealflow.revisit import BERLIN

pytestmark = pytest.mark.hosted
_ = (schema, settings)
NAME = "Revisit Robotics"
URL = "https://news.example.com/revisit-robotics"


def change(since: str = "2026-10-15", kind: str = "funding_round") -> dict[str, Any]:
    return company(NAME, external_id="x:revisit", material_change={"kind": kind, "evidence_url": URL, "since": since})


def rejected_candidate(settings: Settings, schema: str, decided_at: str | None = "2026-10-01 09:00+00") -> str:
    cid = submit(settings, schema, delivery(company(NAME, external_id="x:revisit"))).resolution[0]["candidate_id"]
    with connect(settings.db_url, autocommit=True) as conn:
        conn.execute(f"update {schema}.candidates set status = 'rejected', decided_at = %s where id = %s".encode(),
                     (decided_at, cid))  # fmt: skip
    return str(cid)


def inbox(settings: Settings, schema: str) -> tuple[dict[str, Any], int]:
    with transaction(settings.db_url) as conn:
        view = inbox_view(conn, schema)
    return {c["id"]: c["revisit"] for c in view["candidates"]}, view["revisit_count"]


def intake_reasons(settings: Settings, schema: str, cid: str) -> list[Any]:
    rows = query(settings, f"select detail->>'material_change' from {schema}.candidate_events "
                           "where candidate_id = %s and action = 'intake' order by id", cid)  # fmt: skip
    return [r[0] for r in rows]


def flags(settings: Settings, schema: str, cid: str) -> int:
    rows = query(settings, f"select count(*) from {schema}.candidate_events where candidate_id = %s "
                           "and action = 'revisit_flagged'", cid)  # fmt: skip
    return int(rows[0][0])


def test_a_dated_change_after_the_rejection_is_flagged_and_listed(settings: Settings, schema: str) -> None:
    cid = rejected_candidate(settings, schema)
    out = submit(settings, schema, delivery(change()))
    assert out.resolution[0]["result"] == "re_reported_closed"
    assert query(settings, f"select status from {schema}.candidates where id = %s", cid) == [("rejected",)]
    revisits, count = inbox(settings, schema)
    assert count == 1 and revisits[cid]["kind"] == "funding_round" and revisits[cid]["since"] == "2026-10-15"
    assert revisits[cid]["evidence_url"] == URL and revisits[cid]["date_source"] == "since"
    assert intake_reasons(settings, schema, cid)[-1] == "flagged"
    at = query(settings, f"select at from {schema}.candidate_events where candidate_id = %s "
                         "and action = 'revisit_flagged'", cid)[0][0]  # fmt: skip
    assert revisits[cid]["flagged_at"] == at.astimezone(UTC).isoformat()  # UTC: sortable as text
    assert revisits[cid]["flagged_on"] == at.astimezone(BERLIN).date().isoformat()  # the Berlin day, for display


def test_a_reopen_clears_the_flag_and_a_new_rejection_never_revives_it(settings: Settings, schema: str) -> None:
    cid = rejected_candidate(settings, schema)
    submit(settings, schema, delivery(change()))
    with transaction(settings.db_url) as conn:
        DealFlowStore(conn, schema).decide(cid, "new", reason="reopened by Mohamed")
    assert inbox(settings, schema)[1] == 0
    with transaction(settings.db_url) as conn:
        DealFlowStore(conn, schema).decide(cid, "rejected", reason="rejected again")
    revisits, count = inbox(settings, schema)
    assert count == 0 and revisits[cid] is None  # the old flag is older than the new rejection
    submit(settings, schema, delivery(change(), ref="again"))  # the same change again: dated before today's rejection
    assert inbox(settings, schema)[1] == 0 and intake_reasons(settings, schema, cid)[-1] == "before_rejection"


def test_an_undated_imported_rejection_keeps_the_report_but_is_not_flagged(settings: Settings, schema: str) -> None:
    cid = rejected_candidate(settings, schema, decided_at=None)
    submit(settings, schema, delivery(change()))
    assert flags(settings, schema, cid) == 0 and inbox(settings, schema)[1] == 0
    assert intake_reasons(settings, schema, cid)[-1] == "unknown_rejection_date"
    observed = query(settings, f"select payload->'material_change'->>'kind' from {schema}.observations "
                               "where candidate_id = %s order by id desc limit 1", cid)  # fmt: skip
    assert observed == [("funding_round",)]  # the report itself is kept


def test_two_deliveries_of_the_same_change_leave_one_flag(settings: Settings, schema: str) -> None:
    cid = rejected_candidate(settings, schema)
    results: list[Any] = []
    threads = [threading.Thread(target=lambda r=r: results.append(submit(settings, schema, delivery(change(), ref=r))))
               for r in ("a", "b")]  # fmt: skip
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert len(results) == 2 and flags(settings, schema, cid) == 1
    assert sorted(intake_reasons(settings, schema, cid)[-2:]) == ["already_flagged", "flagged"]


@pytest.mark.parametrize("reopen_first", [True, False])
def test_a_re_report_racing_a_manual_reopen_keeps_the_observation_and_agrees_with_the_decision(
    settings: Settings, schema: str, reopen_first: bool
) -> None:
    cid = rejected_candidate(settings, schema)
    before = query(settings, f"select count(*) from {schema}.observations where candidate_id = %s", cid)[0][0]
    if reopen_first:  # the reopen holds the locks while the re-report waits for them
        conn = connect(settings.db_url)
        with conn.transaction():
            DealFlowStore(conn, schema).decide(cid, "new", reason="reopened by Mohamed")
            t = threading.Thread(target=lambda: submit(settings, schema, delivery(change())))
            t.start()
            time.sleep(1.5)
        conn.close()
        t.join(60)
    else:  # the re-report flags first, the reopen follows
        submit(settings, schema, delivery(change()))
        with transaction(settings.db_url) as conn:
            DealFlowStore(conn, schema).decide(cid, "new", reason="reopened by Mohamed")
    after = query(settings, f"select count(*) from {schema}.observations where candidate_id = %s", cid)[0][0]
    assert after == before + 1  # the re-report's observation survives either way
    revisits, count = inbox(settings, schema)
    assert query(settings, f"select status from {schema}.candidates where id = %s", cid) == [("new",)]
    assert revisits[cid] is None and count == 0  # the list and count agree with the final decision (reopened)


def test_a_flag_decided_after_a_rejection_that_committed_while_it_waited_is_current(
    settings: Settings, schema: str
) -> None:
    """The re-report's transaction STARTS before a manual rejection commits and waits for the lock: its flag is decided
    after that rejection, so it must count as newer (``clock_timestamp()``, not the transaction's start time)."""
    cid = submit(settings, schema, delivery(company(NAME, external_id="x:revisit"))).resolution[0]["candidate_id"]
    conn = connect(settings.db_url)
    with conn.transaction():
        DealFlowStore(conn, schema).decide(str(cid), "rejected", reason="rejected by Mohamed")
        t = threading.Thread(target=lambda: submit(settings, schema, delivery(change(since="2026-12-31"))))
        t.start()
        time.sleep(1.5)  # the re-report has begun and waits for the intake lock
    conn.close()
    t.join(60)
    revisits, count = inbox(settings, schema)
    assert count == 1 and revisits[str(cid)]["since"] == "2026-12-31"


REGISTRY = "https://registry.example.org/revisit-robotics/notice-7"
TRADE = "https://trade.example.net/revisit-robotics-ceo"


def corroboration(own: str, *cited: str) -> dict[str, Any]:
    """A report claiming independent corroboration from ``own``, citing ``cited`` too."""
    return company(NAME, external_id="x:revisit", evidence=[{"url": own}, *({"url": u} for u in cited)],
                   material_change={"kind": "independent_corroboration", "evidence_url": own, "since": "2026-10-15"})  # fmt: skip


def test_unrelated_evidence_from_another_source_never_corroborates(settings: Settings, schema: str) -> None:
    """Codex H-129: a registry observation of something else (an address change), then a trade report of a new CEO
    claiming corroboration: one source reported the appointment, so it is kept but not flagged."""
    cid = rejected_candidate(settings, schema)
    submit(settings, schema, delivery(company(NAME, external_id="x:revisit", evidence=[{"url": REGISTRY}],
                                              key_fact="Registered a new address.")))  # fmt: skip
    submit(settings, schema, delivery(corroboration(TRADE)))
    assert flags(settings, schema, cid) == 0 and intake_reasons(settings, schema, cid)[-1] == "single_source"


def test_corroboration_of_an_earlier_reported_change_keeps_both_references(settings: Settings, schema: str) -> None:
    cid = rejected_candidate(settings, schema)
    submit(settings, schema, delivery(corroboration(REGISTRY)))  # one source so far
    assert intake_reasons(settings, schema, cid)[-1] == "single_source"
    submit(settings, schema, delivery(corroboration(TRADE, REGISTRY)))  # cites the earlier report's source
    assert intake_reasons(settings, schema, cid)[-1] == "flagged"
    revisits, count = inbox(settings, schema)
    first, second = (str(r[0]) for r in query(settings, f"select submission_id from {schema}.observations "
                                                         "where candidate_id = %s order by id desc limit 2", cid)[::-1])  # fmt: skip
    assert count == 1 and revisits[cid]["corroboration"] == [
        {"evidence_url": REGISTRY, "submission_id": first},
        {"evidence_url": TRADE, "submission_id": second},
    ]


def test_a_first_report_naming_two_independent_sources_is_flagged_with_both(settings: Settings, schema: str) -> None:
    """Codex H-131: one delivery, two sources named for THIS change: flagged, both kept under one submission."""
    cid = rejected_candidate(settings, schema)
    e = corroboration(TRADE, REGISTRY)
    e["material_change"] = {**e["material_change"], "supporting_urls": [REGISTRY]}
    submit(settings, schema, delivery(e))
    assert intake_reasons(settings, schema, cid)[-1] == "flagged"
    (sid,) = query(settings, f"select submission_id from {schema}.observations where candidate_id = %s "
                             "order by id desc limit 1", cid)[0]  # fmt: skip
    revisits, count = inbox(settings, schema)
    assert count == 1 and revisits[cid]["corroboration"] == [
        {"evidence_url": REGISTRY, "submission_id": str(sid)},
        {"evidence_url": TRADE, "submission_id": str(sid)},
    ]


def test_a_first_report_whose_second_url_is_general_evidence_is_not_flagged(settings: Settings, schema: str) -> None:
    cid = rejected_candidate(settings, schema)
    submit(settings, schema, delivery(corroboration(TRADE, REGISTRY)))  # REGISTRY is cited, not named as support
    assert flags(settings, schema, cid) == 0 and intake_reasons(settings, schema, cid)[-1] == "single_source"

"""Review 005 rev 2: an intake re-report and an operator reopen of the same closed candidate, overlapping on two
connections, must both commit (one lock order everywhere: company row, then candidate row)."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest

from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.dealflow.candidates import DealFlowStore, DecisionError
from projectzero.dealflow.intake.postgres import PostgresIntake
from projectzero.dealflow.intake.service import IntakeService
from projectzero.ops.db_check import _scratch_sql

pytestmark = pytest.mark.hosted


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture
def schema(settings: Settings) -> Iterator[str]:
    name = f"pz_itest_{secrets.token_hex(4)}"
    admin = connect(settings.db_url, autocommit=True)
    try:
        admin.execute(_scratch_sql(name).encode())
        yield name
    finally:
        admin.execute(f"drop schema if exists {name} cascade".encode())
        admin.close()


def deliver(settings: Settings, schema: str, origin: str) -> list[dict[str, Any]]:
    payload = {
        "contract_version": "1.0",
        "origin": origin,
        "external_ref": secrets.token_hex(3),
        "submitted_at": "2026-11-11T09:00:00+01:00",
        "entities": [
            {
                "kind": "company",
                "name": "Overlap Robotics",
                "website": "https://overlap-robotics.com",
                "key_fact": "Overlap Robotics raised a pre-seed round",
                "evidence": [{"url": f"https://news.example.com/overlap-{origin}"}],
            }
        ],
    }
    with transaction(settings.db_url) as conn:
        store = PostgresIntake(conn, schema)
        return list(IntakeService(store, resolver=store).submit_external(payload, submitted_by=origin).resolution)


def test_re_report_and_reopen_of_the_same_closed_candidate_both_commit(
    settings: Settings, schema: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = deliver(settings, schema, "grok")[0]["candidate_id"]
    with transaction(settings.db_url) as conn:
        DealFlowStore(conn, schema).decide(candidate, "rejected")

    company_locked, release = threading.Event(), threading.Event()
    original_touch = PostgresIntake._touch

    def touch_after_overlap(self: PostgresIntake, *args: Any, **kwargs: Any) -> None:
        company_locked.set()  # intake already updated (locked) the company row in _apply_company
        assert release.wait(30), "test never released the intake"
        original_touch(self, *args, **kwargs)  # ...and now wants the candidate row

    monkeypatch.setattr(PostgresIntake, "_touch", touch_after_overlap)
    errors: list[BaseException] = []
    results: dict[str, Any] = {}

    def run(label: str, fn: Any) -> None:
        try:
            results[label] = fn()
        except BaseException as exc:  # record deadlocks or anything else
            errors.append(exc)

    def reopen() -> dict[str, Any]:
        with transaction(settings.db_url) as conn:
            return DealFlowStore(conn, schema).decide(candidate, "reviewing", reason="re-reported by a second scout")

    intake = threading.Thread(target=run, args=("intake", lambda: deliver(settings, schema, "manual")))
    intake.start()
    assert company_locked.wait(30), "intake never reached the candidate step"
    operator = threading.Thread(target=run, args=("decide", reopen))
    operator.start()
    time.sleep(2)  # let the reopen reach its first lock while intake holds the company
    release.set()
    intake.join(60)
    operator.join(60)

    assert errors == []  # no deadlock, no unique violation: both transactions committed
    assert results["intake"][0]["result"] == "re_reported_closed"
    assert results["decide"]["changed"] is True
    with connect(settings.db_url, autocommit=True) as conn:
        status, origins = conn.execute(
            f"select status, origins from {schema}.candidates where id = %s".encode(), (candidate,)
        ).fetchone()  # type: ignore[misc]
        observations = conn.execute(
            f"select count(*) from {schema}.observations where candidate_id = %s".encode(), (candidate,)
        ).fetchone()
        open_count = conn.execute(
            f"select count(*) from {schema}.candidates where status not in ('rejected', 'archived')".encode()
        ).fetchone()
    assert status == "reviewing" and origins == ["grok", "manual"]  # operator decision AND the re-report kept
    assert observations == (2,) and open_count == (1,)  # the observation preserved; one open candidate


def test_a_company_reassignment_while_locking_is_a_409_that_writes_nothing(
    settings: Settings, schema: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review 005 rev 3: the candidate moves to another company between the unlocked read and the candidate lock."""
    candidate = deliver(settings, schema, "grok")[0]["candidate_id"]
    with connect(settings.db_url, autocommit=True) as conn:
        other = conn.execute(
            f"insert into {schema}.companies (name) values ('Merge Target') returning id".encode()
        ).fetchone()
    assert other is not None
    original_rows = DealFlowStore._rows

    def rows_with_reassignment(self: DealFlowStore, query: str, params: Any = ()) -> list[dict[str, Any]]:
        result = original_rows(self, query, params)
        if "from {s}.companies where id = %s for update" in query:  # company locked, candidate not yet
            with connect(settings.db_url, autocommit=True) as side:  # a merge re-points the candidate meanwhile
                side.execute(
                    f"update {schema}.candidates set company_id = %s where id = %s".encode(), (other[0], candidate)
                )
        return result

    monkeypatch.setattr(DealFlowStore, "_rows", rows_with_reassignment)
    with pytest.raises(DecisionError) as refused, transaction(settings.db_url) as conn:
        DealFlowStore(conn, schema).decide(candidate, "watch", notes="must not be saved", reason="x")
    assert refused.value.status == 409 and "moved to another company" in str(refused.value)
    monkeypatch.undo()
    with connect(settings.db_url, autocommit=True) as conn:
        state = conn.execute(
            f"select status, attrs ? 'notes' from {schema}.candidates where id = %s".encode(), (candidate,)
        ).fetchone()
        operator_events = conn.execute(
            f"select count(*) from {schema}.candidate_events where candidate_id = %s and actor = 'operator'".encode(),
            (candidate,),
        ).fetchone()
    assert state == ("new", False) and operator_events == (0,)  # rolled back: no status, no note, no event

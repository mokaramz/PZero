"""The gateway's deadline (review 028d, plan revisions 2 and 3) over the fake provider, the in-memory store and a fake
clock: no admission with no time left, each attempt's timeout bounded by the time left, no retry wait past the
deadline, the deadline checked again after admission, the budget-lock waits bounded (``BudgetBusy``), a dispatched
attempt whose settlement misses the lock left to the reconciler (one debit), and 029a unchanged without a deadline.
No network anywhere."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from typing import Any

import pytest

from projectzero.core import net
from projectzero.core.inference import budget, gateway
from projectzero.core.inference.budget import BERLIN
from projectzero.core.inference.providers import FakeProvider, OpenAICompatibleProvider, ProviderError
from projectzero.core.inference.store import (
    Admission,
    AttemptRequest,
    BudgetBusy,
    InMemoryBudgetStore,
    LedgerRow,
    Settlement,
)

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=BERLIN)
ON = {"PZ_AI_PAID": "on"}
MSG = [{"role": "system", "content": "Answer in JSON."}, {"role": "user", "content": "Invented Lantern Robotics?"}]
FLASH = {"input": 0.09, "output": 0.18, "cached_input": 0.018}
EST = budget.estimate_usd(FLASH, len(json.dumps(MSG, ensure_ascii=False)), 700)


class Clock:
    """A fake monotonic clock: ``sleep`` advances it."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


class Run:
    def __init__(self, store: InMemoryBudgetStore | None = None, clock: Clock | None = None) -> None:
        self.clock = clock or Clock()
        self.store = store or InMemoryBudgetStore(monotonic=self.clock, sleep=self.clock.sleep)
        self.waits: list[float] = []
        self.n = 0

    def ids(self) -> str:
        self.n += 1
        return f"ic-{self.n:012d}"

    def sleep(self, s: float) -> None:
        self.waits.append(s)
        self.clock.sleep(s)

    def __call__(self, prov: Any, *, within: float | None, wall: datetime = NOW, **kw: Any) -> gateway.Result:
        return gateway.complete(
            "CHEAP",
            kw.pop("messages", MSG),
            purpose="t",
            store=self.store,
            clock=lambda: wall,
            env=kw.pop("env", ON),
            providers={"deepinfra": prov},
            sleep=self.sleep,
            new_id=self.ids,
            deadline=None if within is None else self.clock.t + within,
            monotonic=self.clock,
            **kw,
        )


def test_no_time_left_admits_nothing_and_sends_nothing() -> None:
    run = Run()
    p = FakeProvider(paid=True)
    r = run(p, within=0.0)
    assert not r.ok and r.error_kind == "deadline" and not r.must_stop and "deadline" not in gateway.STOP_KINDS
    assert p.calls == [] and run.store.rows == [] and run.store.reservations == {} and r.attempts == 0
    assert r.settled and r.usd == 0.0


def test_each_attempt_timeout_is_bounded_by_the_time_left() -> None:
    run = Run()
    p = FakeProvider(paid=True)
    assert run(p, within=7.5, use_cache=False).ok and p.calls[-1]["timeout_s"] == 7.5
    assert run(p, within=500.0, use_cache=False).ok and p.calls[-1]["timeout_s"] == 60.0  # the role's timeout
    assert run(p, within=None, use_cache=False).ok and p.calls[-1]["timeout_s"] == 60.0
    assert len(p.calls) == 3


def test_a_retry_wait_past_the_deadline_is_not_taken() -> None:
    run = Run()
    p = FakeProvider.scripted([ProviderError("server", "HTTP 503")], paid=True)
    r = run(p, within=1.5)  # the first retry waits 2 s
    assert not r.ok and r.error_kind == "deadline" and "retry wait" in r.error
    assert p.dispatches == 1 and run.waits == []
    (row,) = run.store.rows  # the dispatched attempt is settled: charged its estimate (029a)
    assert (row.outcome, row.error_kind, row.usd, row.usd_source, row.detail["attempt"]) == (
        "error",
        "server",
        EST,
        "estimated",
        1,
    )
    assert r.usd == EST and r.settled and run.store.reservations == {}


def test_a_retry_wait_that_fits_is_taken_with_the_rest_of_the_time() -> None:
    run = Run()
    p = FakeProvider.scripted([ProviderError("server", "HTTP 503")], paid=True)
    r = run(p, within=10.0)
    assert r.ok and run.waits == [2.0] and p.dispatches == 2
    assert [c["timeout_s"] for c in p.calls] == [10.0, 8.0]
    assert [x.detail["attempt"] for x in run.store.rows] == [1, 2]


def test_retry_after_past_the_deadline_is_not_taken() -> None:
    run = Run()
    p = FakeProvider.scripted([ProviderError("rate_limited", "HTTP 429", 429, retry_after=20)], paid=True)
    r = run(p, within=15.0)
    assert r.error_kind == "deadline" and p.dispatches == 1 and run.waits == []


def test_a_busy_budget_lock_at_admission_ends_the_call_within_the_deadline() -> None:
    run = Run()
    run.store.busy_until = run.clock.t + 50.0  # another connection holds the budget lock
    start = run.clock.t
    p = FakeProvider(paid=True)
    r = run(p, within=5.0)
    assert not r.ok and r.error_kind == "deadline" and "busy" in r.error
    assert run.clock.t - start == 5.0 and run.store.waited == [5.0]  # waited only the time left
    assert p.calls == [] and run.store.rows == [] and run.store.reservations == {}
    assert run.store.busy == [("admit", "ic-000000000001", 1)]


def test_a_budget_lock_freed_in_time_is_taken_and_the_rest_bounds_the_attempt() -> None:
    run = Run()
    run.store.busy_until = run.clock.t + 2.0
    p = FakeProvider(paid=True)
    r = run(p, within=10.0)
    assert r.ok and run.store.waited == [2.0] and p.calls[0]["timeout_s"] == 8.0


def test_the_deadline_is_checked_again_after_admission() -> None:
    """The admission waited the whole time left: the attempt is not sent, its fresh reservation settled at $0."""
    run = Run()
    run.store.busy_until = run.clock.t + 5.0
    p = FakeProvider(paid=True)
    r = run(p, within=5.0)
    assert not r.ok and r.error_kind == "deadline" and "not sent" in r.error and p.calls == []
    (row,) = run.store.rows
    assert (row.outcome, row.error_kind, row.usd, row.usd_source, row.detail["attempt"]) == (
        "error",
        "deadline",
        0.0,
        "none",
        1,
    )
    assert run.store.reservations == {} and r.settled and r.attempts == 0


class SettleBusy(InMemoryBudgetStore):
    """Settlements never get the lock (held by another connection past the deadline)."""

    def settle(self, settlement: Settlement, *, wait_s: float | None = None) -> bool:
        if wait_s is not None:
            self.busy.append(("settle", settlement.call_id, settlement.attempt))
            raise BudgetBusy("held")
        return super().settle(settlement, wait_s=wait_s)


def test_an_unsent_attempt_whose_release_misses_the_lock_is_reconciled_at_its_estimate() -> None:
    """Codex H-278: an abandoned estimate can conservatively consume budget even for an unsent attempt; it stays
    visible as ``estimated``."""
    clock = Clock()
    store = SettleBusy(monotonic=clock, sleep=clock.sleep)
    store.busy_until = clock.t + 5.0
    run = Run(store, clock)
    p = FakeProvider(paid=True)
    r = run(p, within=5.0)
    assert r.error_kind == "deadline" and p.calls == [] and r.unsettled == (1,) and not r.settled
    assert list(store.reservations) == [("ic-000000000001", 1)] and store.rows == []
    later = NOW + timedelta(hours=1)  # past expires_at: the next admission reconciles it
    assert run(FakeProvider(paid=True), within=None, wall=later).ok
    abandoned = [x for x in store.rows if x.outcome == "abandoned"]
    assert len(abandoned) == 1 and abandoned[0].usd == EST and abandoned[0].usd_source == "estimated"


def test_a_dispatched_attempt_whose_settlement_misses_the_lock_keeps_its_reservation_then_one_debit() -> None:
    run = Run()

    def responder(messages: Any, model: str) -> str:
        run.store.busy_until = run.clock.t + 100.0  # the lock is taken while the provider answers
        raise ProviderError("server", "HTTP 503")

    p = FakeProvider(responder, paid=True)
    r = run(p, within=5.0)
    assert not r.ok and r.error_kind == "deadline" and r.unsettled == (1,) and not r.settled
    assert p.dispatches == 1 and run.waits == []  # the call ends: no retry, no settlement retried past the deadline
    assert run.store.rows == [] and list(run.store.reservations) == [("ic-000000000001", 1)]
    assert run.store.spend(now=NOW, role="CHEAP", entity_id=None, run_id=None).pending == EST  # still counted
    # the lock is released; after expires_at the next admission reconciles the attempt at its estimate
    run.store.busy_until = None
    later = NOW + timedelta(hours=1)
    assert run(FakeProvider(paid=True), within=None, wall=later).ok
    mine = [x for x in run.store.rows if x.call_id == "ic-000000000001"]
    assert [(x.outcome, x.usd, x.usd_source) for x in mine] == [("abandoned", EST, "estimated")]
    # a late settlement of the same attempt records nothing: exactly one debit
    late = LedgerRow(NOW, "t", "deepinfra", "m", None, EST, None, None, False, "error",
                     {"call_id": "ic-000000000001", "attempt": 1})  # fmt: skip
    assert run.store.settle(Settlement(late)) is False
    assert len([x for x in run.store.rows if x.call_id == "ic-000000000001"]) == 1


def test_a_valid_reply_whose_settlement_misses_the_lock_stays_ok_and_is_not_cached() -> None:
    run = Run()

    def responder(messages: Any, model: str) -> str:
        run.store.busy_until = run.clock.t + 100.0
        return '{"answer": 1}'

    r = run(FakeProvider(responder, paid=True), within=5.0)
    assert r.ok and r.data == {"answer": 1} and r.unsettled == (1,)
    assert run.store.rows == [] and len(run.store.reservations) == 1 and run.store.cache == {}


def test_without_a_deadline_the_store_gets_no_wait_bound_and_the_result_is_029a_shaped() -> None:
    class Legacy:
        """A 029a-shaped store: no ``wait_s`` keyword."""

        def __init__(self) -> None:
            self.inner = InMemoryBudgetStore()

        def admit(self, attempt: AttemptRequest) -> Admission:
            return self.inner.admit(attempt)

        def settle(self, settlement: Settlement) -> bool:
            return self.inner.settle(settlement)

        def __getattr__(self, name: str) -> Any:
            return getattr(self.inner, name)

    legacy = Legacy()
    r = gateway.complete("CHEAP", MSG, purpose="t", store=legacy, clock=lambda: NOW, env=ON,  # type: ignore[arg-type]
                         providers={"deepinfra": FakeProvider(paid=True)})  # fmt: skip
    assert r.ok and len(legacy.inner.rows) == 1
    assert set(r.__dict__) == {f for f in gateway.Result.__dataclass_fields__}  # no new field


def test_the_store_wait_bound() -> None:
    clock = Clock()
    store = InMemoryBudgetStore(monotonic=clock, sleep=clock.sleep)
    req = AttemptRequest(
        call_id="ic-x",
        attempt=1,
        role="CHEAP",
        purpose="t",
        provider="deepinfra",
        model="m",
        entity_id=None,
        run_id=None,
        est_usd=0.001,
        limits=budget.limits({}),
        run_cap_usd=None,
        override_reason=None,
        now=NOW,
        expires_at=NOW + timedelta(minutes=2),
    )
    store.busy_until = clock.t + 3.0
    with pytest.raises(BudgetBusy):
        store.admit(req, wait_s=0.0)  # only a free lock: no wait at all
    assert store.waited == [] and store.reservations == {}
    with pytest.raises(BudgetBusy):
        store.admit(req, wait_s=1.0)
    assert store.waited == [1.0] and store.reservations == {}
    assert store.admit(req).admitted  # None: waits until the lock frees
    assert store.waited == [1.0, 2.0] and list(store.reservations) == [("ic-x", 1)]
    # the real lock too: held by another thread, a bounded wait gives up
    held, release = threading.Event(), threading.Event()

    def holder() -> None:
        with store._lock:
            held.set()
            release.wait(5)

    t = threading.Thread(target=holder)
    t.start()
    held.wait(5)
    try:
        with pytest.raises(BudgetBusy):
            store.settle(Settlement(LedgerRow(NOW, "t", None, None, None, 0.0, None, None, False, "ok",
                                              {"call_id": "ic-x", "attempt": 1})), wait_s=0.01)  # fmt: skip
    finally:
        release.set()
        t.join()
    assert list(store.reservations) == [("ic-x", 1)] and store.rows == []


def test_deadline_is_an_error_kind_with_a_plain_message() -> None:
    assert "deadline" in gateway.ERROR_KINDS


def test_a_refusal_before_admission_with_a_deadline_writes_its_row_without_waiting() -> None:
    run = Run()
    run.store.busy_until = run.clock.t + 50.0
    r = run(FakeProvider(paid=True), within=5.0, env={"PZ_AI_PAID": "off"})
    assert r.error_kind == "disabled" and r.must_stop and r.unsettled == (0,)  # the $0 row could not be written
    assert run.store.rows == [] and run.store.reservations == {} and run.store.waited == [5.0]


def test_the_real_client_s_transport_gets_the_time_left() -> None:
    """The OpenAI-compatible client over a fake transport: the exchange's timeout and deadline end by the call's."""
    seen: list[tuple[float, float | None]] = []
    body = {
        "choices": [{"message": {"content": '{"answer": 1}'}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
    }

    class Transport:
        def send(self, target: Any, method: str, headers: Any, data: Any, timeout: float, max_bytes: int,
                 deadline: float | None = None) -> net.Response:  # fmt: skip
            seen.append((timeout, deadline))
            return net.Response("https://api.deepinfra.com/", 200, {}, json.dumps(body).encode())

    prov = OpenAICompatibleProvider("deepinfra", "https://api.deepinfra.com/v1/openai", "DEEPINFRA_API_KEY",
                                    transport=Transport(), resolver=lambda h: ["93.184.215.14"])  # fmt: skip
    deadline = time.monotonic() + 4.0
    r = gateway.complete("CHEAP", MSG, purpose="t", store=InMemoryBudgetStore(), clock=lambda: NOW,
                         env={"PZ_AI_PAID": "on", "DEEPINFRA_API_KEY": "sk-INVENTED-test-only"},
                         providers={"deepinfra": prov}, deadline=deadline)  # fmt: skip
    assert r.ok and len(seen) == 1
    timeout, sent_deadline = seen[0]
    assert timeout <= 4.0 and sent_deadline is not None and sent_deadline <= deadline + 0.01

"""The pure budget rules and the in-memory store (review 029a, plan revisions 2 and 3): the old rule order per attempt,
the Berlin windows, the cost rules, admission with reconciliation, idempotent settlement, abandoned attempts."""

from __future__ import annotations

import math
import threading
from datetime import datetime, timedelta

import pytest

from projectzero.core.inference import budget
from projectzero.core.inference import config as icfg
from projectzero.core.inference.budget import BERLIN, Spend
from projectzero.core.inference.store import (
    AttemptRequest,
    InMemoryBudgetStore,
    LedgerRow,
    Reservation,
    Settlement,
    abandoned_row,
)

LIM = budget.limits(icfg.load())
NOW = datetime(2026, 11, 12, 10, 0, tzinfo=BERLIN)  # a Thursday


EMPTY = Spend()


def chk(spend: Spend = EMPTY, est: float = 0.01, **kw: object) -> str:
    args: dict[str, object] = {
        "est_usd": est,
        "role": "CHEAP",
        "entity_id": None,
        "run_id": None,
        "run_cap_usd": None,
        "override_reason": None,
        "purpose": "t",
    }
    args.update(kw)
    return budget.check(LIM, spend, **args)  # type: ignore[arg-type]


def row(at: datetime, usd: float, **detail: object) -> LedgerRow:
    entity = detail.pop("entity", None)
    return LedgerRow(at, "t", "deepinfra", "m", entity if isinstance(entity, str) else None, usd, None, None, False,
                     "ok", dict(detail))  # fmt: skip


def req(
    call_id: str = "ic-a", attempt: int = 1, est: float = 0.01, now: datetime = NOW, **kw: object
) -> AttemptRequest:
    args: dict[str, object] = {
        "call_id": call_id,
        "attempt": attempt,
        "role": "CHEAP",
        "purpose": "t",
        "provider": "deepinfra",
        "model": "m",
        "entity_id": None,
        "run_id": None,
        "est_usd": est,
        "limits": LIM,
        "run_cap_usd": None,
        "override_reason": None,
        "now": now,
        "expires_at": now + timedelta(seconds=120),
        "detail": {"prompt_sha": "p", "request_sha": "r"},
    }
    args.update(kw)
    return AttemptRequest(**args)  # type: ignore[arg-type]


def settled(call_id: str, attempt: int, usd: float, at: datetime = NOW) -> Settlement:
    return Settlement(row(at, usd, call_id=call_id, attempt=attempt, role="CHEAP", usd_source="priced"))


# ---------------------------------------------------------------- the rule order
def test_rule_order_and_texts() -> None:
    assert chk() == ""
    # 1. the run cap, even with a valid override
    over = chk(Spend(run=0.04, pending_run=0.005), run_id="r1", run_cap_usd=0.05, override_reason="a long reason")
    assert over == "run cap reached for r1 ($0.0450 spent + $0.0100 next > $0.05)"
    assert chk(Spend(run=0.04), run_cap_usd=0.05) == ""  # no run id: no run cap
    # 2. an override: too short blocks, long enough skips everything after
    assert chk(override_reason="  short  ") == "override reason must be at least 8 characters"
    assert chk(Spend(day=5.0), est=9.0, override_reason="Mohamed approved") == ""
    # 3. the per-call cap, by purpose
    assert chk(est=0.051) == "single call estimate $0.0510 exceeds the per-call cap $0.05"
    assert chk(est=0.19, purpose="ic_chair") == ""
    assert chk(est=0.011, purpose="native_planner").startswith("single call estimate $0.0110")
    # 4. the windows, pending included
    day = chk(Spend(day=0.98, pending=0.015))
    assert day == "day budget reached ($0.9950 spent + $0.0100 next > $1.00) — Mohamed may override with a reason"
    assert chk(Spend(week=4.995)).startswith("week budget reached")
    assert chk(Spend(month=24.995)).startswith("month budget reached")
    # 5. the role's monthly cap (CHEAP only)
    assert chk(Spend(role_month=2.99, pending_role=0.005)) == "CHEAP monthly cap reached ($2.9950 + $0.0100 > $3.00)"
    assert chk(Spend(role_month=2.99, pending_role=0.005), role="STANDARD") == ""
    # 6. the entity's all-time cap
    assert chk(Spend(entity=0.995), entity_id="inbox:x") == "spend on inbox:x would exceed the per-entity cap $1.00"
    assert chk(Spend(entity=0.995)) == ""


def test_limits_default_to_infinity() -> None:
    lim = budget.limits({"budget": {"daily_usd": "x", "role_monthly_usd": {"CHEAP": "y", "STANDARD": 2}}})
    assert (
        lim.daily_usd == math.inf and lim.max_call_usd == math.inf and dict(lim.role_monthly_usd) == {"STANDARD": 2.0}
    )


def test_berlin_windows() -> None:
    assert budget.windows(NOW) == (
        datetime(2026, 11, 12, tzinfo=BERLIN),
        datetime(2026, 11, 9, tzinfo=BERLIN),
        datetime(2026, 11, 1, tzinfo=BERLIN),
    )
    # a UTC clock is read on the Berlin wall: 23:30 UTC on Nov 30 is already Dec 1 in Berlin
    utc = datetime.fromisoformat("2026-11-30T23:30:00+00:00")
    assert budget.windows(utc)[0] == datetime(2026, 12, 1, tzinfo=BERLIN)
    assert budget.windows(utc)[2] == datetime(2026, 12, 1, tzinfo=BERLIN)
    store = InMemoryBudgetStore(
        [
            row(datetime(2026, 11, 12, 0, 0, tzinfo=BERLIN), 0.1),  # today
            row(datetime(2026, 11, 11, 23, 59, 59, tzinfo=BERLIN), 0.2),  # yesterday, this week
            row(datetime(2026, 11, 8, 23, 59, 59, tzinfo=BERLIN), 0.4),  # last week, this month
            row(datetime(2026, 10, 31, 23, 59, 59, tzinfo=BERLIN), 0.8, entity="e"),  # last month
        ]
    )
    s = store.spend(now=NOW, role="CHEAP", entity_id="e", run_id=None)
    assert (s.day, s.week, s.month, s.entity) == (0.1, 0.3, 0.7, 0.8)


def test_estimate_and_actual_cost() -> None:
    price = icfg.price(icfg.load(), "deepseek-ai/DeepSeek-V4-Flash")
    assert price == {"input": 0.09, "output": 0.18, "cached_input": 0.018}
    assert budget.estimate_usd(price, 350, 700) == round((100 * 0.09 + 700 * 0.18) / 1e6, 6)
    usage = {"prompt_tokens": 1000, "completion_tokens": 200, "prompt_tokens_details": {"cached_tokens": 400}}
    assert budget.actual_usd(price, usage) == round((600 * 0.09 + 400 * 0.018 + 200 * 0.18) / 1e6, 8)
    assert budget.actual_usd(price, {}) is None
    assert icfg.price({"prices": {"x": {"input": 1}}}, "x") is None


def test_cost_classification() -> None:
    price = {"input": 1.0, "output": 2.0, "cached_input": 1.0}
    assert budget.attempt_cost(paid=True, est_usd=0.003, dispatched=False) == (0.0, "none")
    assert budget.attempt_cost(paid=True, est_usd=0.003, dispatched=True) == (0.003, "estimated")
    assert budget.attempt_cost(paid=False, est_usd=0.0, dispatched=True) == (0.0, "none")
    usage = {"prompt_tokens": 10, "completion_tokens": 5}
    assert budget.reply_cost(paid=True, price=price, est_usd=0.003, reported_usd=0.0001234567891, usage=usage) == (
        0.00012346,
        "reported",
    )
    assert budget.reply_cost(paid=True, price=price, est_usd=0.003, reported_usd=None, usage=usage) == (2e-05, "priced")
    assert budget.reply_cost(paid=True, price=price, est_usd=0.003, reported_usd=None, usage={}) == (0.003, "estimated")
    assert budget.reply_cost(paid=False, price=price, est_usd=0.0, reported_usd=None, usage=usage) == (0.0, "none")


def test_paid_switch_is_exactly_on() -> None:
    assert icfg.paid_enabled({"PZ_AI_PAID": "on"})
    for value in ("", "ON", " on", "true", "1", "yes", "off"):
        assert not icfg.paid_enabled({"PZ_AI_PAID": value})
    assert not icfg.paid_enabled({})
    assert icfg.key_present("deepinfra", {"DEEPINFRA_API_KEY": "x"})
    assert not icfg.key_present("deepinfra", {"DEEPINFRA_API_KEY": "  "})
    assert icfg.key_present("fake", {}) and not icfg.key_present("nowhere", {})
    assert "RESEARCH" not in icfg.ROLES and "xai" not in icfg.DEFAULTS["providers"]


# ---------------------------------------------------------------- the store
def test_admit_reserves_and_counts_pending() -> None:
    store = InMemoryBudgetStore([row(NOW, 0.97)])
    assert store.admit(req("ic-a", est=0.02)).admitted
    blocked = store.admit(req("ic-b", est=0.02))
    assert not blocked.admitted and blocked.reason.startswith("day budget reached ($0.9900 spent")
    assert list(store.reservations) == [("ic-a", 1)]  # a refusal reserves nothing


def test_settle_is_idempotent_and_releases() -> None:
    store = InMemoryBudgetStore()
    assert store.admit(req("ic-a")).admitted
    assert store.settle(settled("ic-a", 1, 0.005)) is True
    assert store.reservations == {}
    assert store.settle(settled("ic-a", 1, 0.005)) is False  # repeated: one debit
    assert [r.usd for r in store.rows] == [0.005] and store.late == [("ic-a", 1)]
    with pytest.raises(ValueError):
        Settlement(row(NOW, 0.0))  # no call id / attempt


def test_settlement_racing_admission_at_the_cap() -> None:
    """A holds the last headroom; B is blocked by the reservation, then by the committed charge; C fits exactly."""
    store = InMemoryBudgetStore([row(NOW, 0.95)])
    assert store.admit(req("ic-a", est=0.04)).admitted  # the day is at 0.99 with A pending
    assert not store.admit(req("ic-b", est=0.02)).admitted  # sees A's reservation
    assert store.settle(settled("ic-a", 1, 0.04))  # debit in, reservation out, atomically
    assert not store.admit(req("ic-b", est=0.02)).admitted  # sees A's committed charge
    assert store.admit(req("ic-c", est=0.01)).admitted  # 0.99 + 0.01 == the cap: admitted exactly up to it


def test_concurrent_admissions_never_overshoot() -> None:
    store = InMemoryBudgetStore([row(NOW, 0.90)])
    admitted: list[bool] = []
    lock = threading.Lock()

    def one(i: int) -> None:
        a = store.admit(req(f"ic-{i}", est=0.03))
        with lock:
            admitted.append(a.admitted)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert admitted.count(True) == 3  # 0.90 + 3 * 0.03 = 0.99; a fourth would be 1.02


def test_restart_between_dispatch_and_settlement() -> None:
    """Reserved and dispatched, then the process 'crashes': after expiry the next admission reconciles it into an
    abandoned row charged the estimate; the late settlement records nothing; the day total includes it throughout."""
    store = InMemoryBudgetStore()
    assert store.admit(req("ic-a", est=0.03, expires_at=NOW + timedelta(seconds=120))).admitted
    s = store.spend(now=NOW, role="CHEAP", entity_id=None, run_id=None)
    assert s.day + s.pending == 0.03
    later = NOW + timedelta(seconds=121)
    adm = store.admit(req("ic-b", est=0.01, now=later))
    assert adm.admitted and adm.reconciled == 1
    (abandoned,) = [r for r in store.rows if r.outcome == "abandoned"]
    assert abandoned == abandoned_row(
        Reservation(
            "ic-a",
            1,
            0.03,
            "CHEAP",
            "t",
            "deepinfra",
            "m",
            None,
            None,
            NOW,
            NOW + timedelta(seconds=120),
            {"prompt_sha": "p", "request_sha": "r"},
        )
    )
    assert abandoned.usd == 0.03 and abandoned.usd_source == "estimated" and abandoned.at == NOW
    s = store.spend(now=later, role="CHEAP", entity_id=None, run_id=None)
    assert s.day == 0.03 and s.pending == 0.01
    assert store.settle(settled("ic-a", 1, 0.0002, at=later)) is False  # late: the abandoned row stands
    assert [r.usd for r in store.rows if r.call_id == "ic-a"] == [0.03]
    assert store.late == [("ic-a", 1)]


def test_not_expired_is_not_reconciled() -> None:
    store = InMemoryBudgetStore()
    store.admit(req("ic-a", expires_at=NOW + timedelta(seconds=5)))
    assert store.admit(req("ic-b", now=NOW + timedelta(seconds=4))).reconciled == 0
    assert store.admit(req("ic-c", now=NOW + timedelta(seconds=5))).reconciled == 1  # expires_at <= now


def test_free_attempt_reserves_without_rules_and_totals() -> None:
    store = InMemoryBudgetStore([row(NOW, 5.0, role="CHEAP"), row(NOW - timedelta(days=40), 1.0)])
    assert store.admit(req("ic-a", est=0.0, check=False)).admitted
    t = store.totals(NOW)
    assert (t.day, t.week, t.month, t.all_time) == (5.0, 5.0, 5.0, 6.0)
    assert dict(t.by_role) == {"CHEAP": 5.0, "None": 1.0} and dict(t.outcomes) == {"ok": 2} and t.reservations == 1

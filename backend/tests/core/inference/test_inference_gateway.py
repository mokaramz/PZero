"""The gateway over the fake provider and the in-memory store (review 029a): the old order with the paid switch
before the cache, per-attempt admission and settlement, the cost of each attempt, retries, JSON and validation,
the cache, and ``status`` without key values. No network anywhere."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

import pytest

from projectzero.core.inference import budget, errors, gateway
from projectzero.core.inference.budget import BERLIN
from projectzero.core.inference.providers import FakeProvider, ProviderError, Reply
from projectzero.core.inference.store import InMemoryBudgetStore, LedgerRow

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=BERLIN)
ON = {"PZ_AI_PAID": "on"}
MSG = [{"role": "system", "content": "Answer in JSON."}, {"role": "user", "content": "Invented Lantern Robotics?"}]
FLASH = {"input": 0.09, "output": 0.18, "cached_input": 0.018}
EST = budget.estimate_usd(FLASH, len(json.dumps(MSG, ensure_ascii=False)), 700)
PRICED = round((1000 * 0.09 + 200 * 0.18) / 1e6, 8)


class Run:
    def __init__(self, store: InMemoryBudgetStore | None = None) -> None:
        self.store = store or InMemoryBudgetStore()
        self.waits: list[float] = []
        self.n = 0

    def ids(self) -> str:
        self.n += 1
        return f"ic-{self.n:012d}"

    def __call__(self, prov: Any, *, env: Mapping[str, str] = ON, role: str = "CHEAP", **kw: Any) -> gateway.Result:
        return gateway.complete(
            role,
            kw.pop("messages", MSG),
            purpose=kw.pop("purpose", "t"),
            store=self.store,
            clock=lambda: NOW,
            env=env,
            providers={"deepinfra": prov},
            sleep=self.waits.append,
            new_id=self.ids,
            **kw,
        )

    def rows(self, call_id: str | None = None) -> list[LedgerRow]:
        return [r for r in self.store.rows if call_id is None or r.call_id == call_id]


def test_success_prices_usage_and_ledgers() -> None:
    run = Run()
    p = FakeProvider(lambda m, model: 'Sure:\n```json\n{"answer": 42}\n```', paid=True)
    r = run(p, entity_id="inbox:x", run_id="r1")
    assert r.ok and r.data == {"answer": 42} and r.usd == PRICED and r.usd_source == "priced" and r.attempts == 1
    assert p.calls[0]["json_mode"] is True and p.calls[0]["max_output_tokens"] == 700
    (row,) = run.rows()
    assert (row.outcome, row.usd, row.entity_ref, row.tokens_in, row.tokens_out) == ("ok", PRICED, "inbox:x", 1000, 200)
    assert row.detail["attempt"] == 1 and row.run_id == "r1" and row.role == "CHEAP" and row.usd_source == "priced"
    assert "Lantern" not in json.dumps(dict(row.detail))  # prompts are never stored, only shas
    assert run.store.reservations == {}


def test_valid_answer_without_usage_is_ok_and_charged_the_estimate() -> None:
    """Codex H-267: one dispatch, a successful Result with its data, one estimated debit."""
    run = Run()
    p = FakeProvider(lambda m, model: Reply(text='{"answer": 1}'), paid=True)
    r = run(p)
    assert r.ok and r.data == {"answer": 1} and r.usd == EST and r.usd_source == "estimated"
    assert p.dispatches == 1 and r.attempts == 1 and run.waits == []
    (row,) = run.rows()
    assert row.outcome == "ok" and row.usd == EST and row.usd_source == "estimated" and row.error_kind is None


def test_reported_cost_wins() -> None:
    run = Run()
    r = run(FakeProvider(paid=True, usage={"prompt_tokens": 10, "completion_tokens": 5, "estimated_cost": 0.000123}))
    assert r.usd == 0.000123 and r.usd_source == "reported"


def test_failure_before_dispatch_costs_nothing() -> None:
    run = Run()
    p = FakeProvider.scripted([ProviderError("bad_request", "refused URL", dispatched=False)], paid=True)
    r = run(p)
    assert not r.ok and r.error_kind == "bad_request" and r.usd == 0.0 and r.usd_source == "none"
    (row,) = run.rows()
    assert (row.outcome, row.usd, row.usd_source, row.error_kind) == ("error", 0.0, "none", "bad_request")
    assert p.dispatches == 0


def test_failure_after_dispatch_is_charged_the_estimate() -> None:
    run = Run()
    p = FakeProvider.scripted([ProviderError("auth", "HTTP 401 invalid: no")], paid=True)
    r = run(p)
    assert r.error_kind == "auth" and r.must_stop and r.usd == EST and r.usd_source == "estimated"
    (row,) = run.rows()
    assert (row.outcome, row.usd, row.usd_source) == ("error", EST, "estimated")


def test_retries_are_admitted_again_and_settled_each() -> None:
    run = Run()
    p = FakeProvider.scripted(
        [
            ProviderError("timeout", "timed out after 60s"),  # after dispatch: the estimate
            ProviderError("network", "ConnectionRefusedError", dispatched=False),  # before: $0
            '{"answer": 3}',
        ],
        paid=True,
    )
    r = run(p)
    assert r.ok and r.attempts == 3 and run.waits == [2.0, 6.0]
    assert r.usd == round(EST + PRICED, 8) and r.usd_source == "priced"
    rows = run.rows()
    assert [(x.detail["attempt"], x.outcome, x.usd, x.usd_source) for x in rows] == [
        (1, "error", EST, "estimated"),
        (2, "error", 0.0, "none"),
        (3, "ok", PRICED, "priced"),
    ]
    assert run.store.reservations == {}


def test_a_retry_that_no_longer_fits_is_blocked_unsent() -> None:
    seed = LedgerRow(NOW, "t", "deepinfra", "m", None, round(1.0 - EST * 1.5, 6), None, None, False, "ok", {})
    run = Run(InMemoryBudgetStore([seed]))
    p = FakeProvider.scripted([ProviderError("server", "HTTP 500 : boom")], paid=True)
    r = run(p)
    assert r.error_kind == "budget_blocked" and r.error.startswith("day budget reached") and r.must_stop
    assert p.dispatches == 1 and r.attempts == 1 and r.usd == EST and r.usd_source == "estimated"
    assert [(x.detail["attempt"], x.outcome, x.usd) for x in run.rows()[1:]] == [(1, "error", EST), (2, "blocked", 0.0)]


@pytest.mark.parametrize(
    ("error", "waits"),
    [
        (ProviderError("rate_limited", "HTTP 429 : slow down", 429, retry_after=12), [12.0, 12.0]),
        (ProviderError("rate_limited", "HTTP 429 : slow down", 429, retry_after=90), [30.0, 30.0]),
        (ProviderError("rate_limited", "HTTP 429 : slow down", 429, retry_after=1), [2.0, 6.0]),
        (ProviderError("server", "HTTP 503 engine_overloaded: Model busy, retry later", 503), [4.0, 12.0]),
        (ProviderError("network", "OSError: reset"), [2.0, 6.0]),
    ],
)
def test_bounded_retries_and_waits(error: ProviderError, waits: list[float]) -> None:
    run = Run()
    p = FakeProvider.scripted([error, error, error, '{"x": 1}'], paid=True)
    r = run(p)
    assert not r.ok and r.attempts == 3 and run.waits == waits and len(p.calls) == 3
    assert r.error_kind == error.kind and [x.detail["attempt"] for x in run.rows()] == [1, 2, 3]


@pytest.mark.parametrize("kind", ["auth", "billing", "bad_request", "malformed"])
def test_non_retryable_kinds(kind: str) -> None:
    run = Run()
    p = FakeProvider.scripted([ProviderError(kind, "no")], paid=True)
    assert run(p).attempts == 1 and run.waits == [] and len(p.calls) == 1


def test_json_extraction_and_validation() -> None:
    assert gateway.extract_json('x ```json\n{"a": 1}\n``` y') == {"a": 1}
    assert gateway.extract_json('noise {"a": [1, 2]} tail') == {"a": [1, 2]}
    assert gateway.extract_json("no json") is None and gateway.extract_json("{broken") is None
    run = Run()
    r = run(FakeProvider(lambda m, model: "plain words", paid=True))
    assert r.error_kind == "malformed" and r.usd == PRICED  # the answer was billed

    def need(d: Any) -> Any:
        if "answer" not in d:
            raise ValueError("missing answer")
        return d["answer"]

    r = run(FakeProvider(lambda m, model: '{"other": 1}', paid=True), validate=need)
    assert r.error_kind == "invalid" and r.error == "missing answer" and run.rows(r.call_id)[0].outcome == "error"
    assert run.store.cache == {}  # malformed and invalid replies are never cached
    r = run(FakeProvider(lambda m, model: "plain words", paid=True), json_mode=False)
    assert r.ok and r.data == "plain words" and len(run.store.cache) == 1


def test_cache_hit_is_free_and_revalidated() -> None:
    run = Run()
    p = FakeProvider(lambda m, model: '{"answer": 7}', paid=True)
    first = run(p)
    hit = run(p)
    assert first.ok and hit.ok and hit.cached and hit.usd == 0.0 and hit.attempts == 0 and len(p.calls) == 1
    assert run.rows(hit.call_id)[0].outcome == "cache_hit" and run.rows(hit.call_id)[0].detail["attempt"] == 0

    def reject(d: Any) -> Any:
        raise ValueError("now refused")

    again = run(p, validate=reject)
    assert again.cached and again.error_kind == "invalid" and len(p.calls) == 1
    assert run(p, use_cache=False).cached is False and len(p.calls) == 2


def test_paid_switch_off_or_unset_refuses_before_the_cache() -> None:
    """Decisions (c) and (d): unset is off; a cached paid answer is not served while paid calls are off."""
    run = Run()
    p = FakeProvider(lambda m, model: '{"answer": 7}', paid=True)
    assert run(p).ok
    for env in ({}, {"PZ_AI_PAID": "off"}, {"PZ_AI_PAID": "true"}):
        r = run(p, env=env)
        assert r.error_kind == "disabled" and not r.cached and r.must_stop
        assert r.error == "paid inference is switched off (PZ_AI_PAID is not 'on')"
    assert len(p.calls) == 1 and run.store.reservations == {}
    free = FakeProvider(lambda m, model: '{"answer": 8}')  # a free provider ignores the switch
    assert run(free, env={}).ok


def test_refusals_never_call_the_provider() -> None:
    run = Run()
    p = FakeProvider(paid=True)
    assert run(p, role="ESCALATION").error_kind == "disabled"
    assert run(p, role="RESEARCH").error == "unknown role 'RESEARCH'"  # decision h: dropped
    assert run(p, model="Invented/unpriced").error_kind == "not_configured"
    from projectzero.core.inference.providers import OpenAICompatibleProvider

    real = OpenAICompatibleProvider("deepinfra", "https://api.deepinfra.com/v1/openai", "DEEPINFRA_API_KEY")
    r = run(real)
    assert r.error == "deepinfra: API key not set (environment variable DEEPINFRA_API_KEY)"
    assert p.calls == [] and {x.detail["attempt"] for x in run.rows()} == {0}


def test_budget_blocked_first_attempt() -> None:
    run = Run()
    p = FakeProvider(paid=True)
    r = run(p, max_output_tokens=300_000)
    assert r.error_kind == "budget_blocked" and r.error.startswith("single call estimate") and p.calls == []
    (row,) = run.rows()
    assert row.outcome == "blocked" and row.detail["attempt"] == 1 and row.detail["attempts"] == 0
    r = run(p, max_output_tokens=300_000, override_reason="Invented approval for a long answer")
    assert r.ok and run.rows(r.call_id)[0].detail["override_reason"] == "Invented approval for a long answer"


def test_abandoned_then_late_settlement_in_the_gateway() -> None:
    """A dispatched attempt whose process stalls past expiry: a concurrent admission reconciles it; the gateway's
    own settlement afterwards records nothing more (one debit)."""
    store = InMemoryBudgetStore()
    late_clock = [NOW]

    def stall(m: Any, model: str) -> str:
        late_clock[0] = NOW + timedelta(seconds=500)  # past timeout + margin
        other = gateway.complete(
            "CHEAP", MSG, purpose="t", store=store, clock=lambda: late_clock[0], env=ON,
            providers={"deepinfra": FakeProvider(paid=True)}, use_cache=False, new_id=lambda: "ic-other",
        )  # fmt: skip
        assert other.ok
        return '{"answer": 1}'

    r = gateway.complete(
        "CHEAP", MSG, purpose="t", store=store, clock=lambda: late_clock[0], env=ON,
        providers={"deepinfra": FakeProvider(stall, paid=True)}, use_cache=False, new_id=lambda: "ic-stall",
    )  # fmt: skip
    assert r.ok
    mine = [x for x in store.rows if x.call_id == "ic-stall"]
    assert [(x.outcome, x.usd, x.usd_source) for x in mine] == [("abandoned", EST, "estimated")]
    assert store.late == [("ic-stall", 1)] and store.reservations == {}


def test_status_reports_readiness_without_values() -> None:
    secret = "sk-INVENTED-status-0000"
    s = gateway.status(InMemoryBudgetStore(), {"DEEPINFRA_API_KEY": secret}, clock=lambda: NOW)
    assert secret not in json.dumps(s)
    assert s["paid_enabled"] is False and s["roles"]["CHEAP"]["key_present"] is True
    assert s["roles"]["CHEAP"]["ready"] is False and "PZ_AI_PAID" in s["roles"]["CHEAP"]["problem"]
    s = gateway.status(InMemoryBudgetStore(), {**ON}, clock=lambda: NOW)
    assert s["roles"]["CHEAP"]["problem"] == "API key not set (environment variable DEEPINFRA_API_KEY)"
    assert s["roles"]["ESCALATION"]["ready"] is False and s["budget"]["remaining"]["day"] == 1.0


def test_plain_language_layer() -> None:
    raw = 'HTTP 429: {"error": {"message": "Model busy, retry later", "code": "engine_overloaded"}}'
    assert errors.compact(raw) == "HTTP 429 engine_overloaded: Model busy, retry later"
    assert errors.category("bad_request", raw) == "RETRYABLE" and errors.category("auth") == "CONFIGURATION"
    assert errors.explain("rate_limited", raw) == "DeepInfra was temporarily overloaded"
    assert errors.explain("budget_blocked") == "the configured AI budget limit was reached"

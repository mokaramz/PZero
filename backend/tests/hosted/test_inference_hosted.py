"""Review 029a acceptance tests (plan revisions 2 / 3, Codex H-265 / H-267 / H-269) against the hosted project, in
throw-away scratch schemas. The fake provider only: no model is ever called, and no key is ever read.

* settlement racing admission at the cap, on two connections: while A's settlement holds the budget lock, B waits;
  B then sees A's committed charge (never neither the reservation nor the charge) and is blocked; a smaller caller is
  admitted exactly up to the cap;
* a restart between dispatch and settlement: the expired reservation becomes an ``abandoned`` row charged its
  estimate at the next admission, and the late settlement records nothing (one debit);
* a repeated settlement records one debit;
* the gateway over the Postgres store: an answer is one ledger row with its reported cost; a valid answer without usage
  is ``ok`` with one estimated debit and one dispatch; ``status`` reports readiness without key values.
"""

from __future__ import annotations

import re
import secrets
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta
from itertools import count
from typing import Any

import pytest

from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.core.inference import gateway
from projectzero.core.inference.budget import BERLIN, Limits
from projectzero.core.inference.pg_store import PostgresBudgetStore
from projectzero.core.inference.providers import FakeProvider, Reply
from projectzero.core.inference.store import AttemptRequest, LedgerRow, Settlement
from projectzero.ops.db_check import _scratch_sql

pytestmark = pytest.mark.hosted
NOW = datetime(2026, 11, 12, 10, 0, tzinfo=BERLIN)
CAP = Limits(daily_usd=0.01)
ON = {"PZ_AI_PAID": "on"}
MSG = [{"role": "system", "content": "Answer in JSON."}, {"role": "user", "content": "Invented Lantern Robotics?"}]


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture
def schema(settings: Settings) -> Iterator[str]:
    name = f"pz_itest_{secrets.token_hex(4)}"
    with connect(settings.db_url, autocommit=True) as admin:
        admin.execute(re.sub(r"\bpz\b", name, _scratch_sql("pz")).encode())
    yield name
    with connect(settings.db_url, autocommit=True) as admin:
        admin.execute(f"drop schema if exists {name} cascade".encode())


def _attempt(call_id: str, est: float, *, now: datetime = NOW, attempt: int = 1) -> AttemptRequest:
    return AttemptRequest(call_id=call_id, attempt=attempt, role="CHEAP", purpose="news_card", provider="deepinfra",
                          model="fake-model", entity_id=None, run_id=None, est_usd=est, limits=CAP, run_cap_usd=None,
                          override_reason=None, now=now, expires_at=now + timedelta(minutes=2),
                          detail={"prompt_sha": "p" * 8})  # fmt: skip


def _row(call_id: str, usd: float, *, attempt: int = 1, outcome: str = "ok") -> LedgerRow:
    return LedgerRow(at=NOW, purpose="news_card", provider="deepinfra", model="fake-model", entity_ref=None, usd=usd,
                     tokens_in=10, tokens_out=5, cached=False, outcome=outcome,
                     detail={"call_id": call_id, "attempt": attempt, "role": "CHEAP", "usd_source": "reported"})  # fmt: skip


def _ledger(settings: Settings, schema: str) -> list[tuple[Any, ...]]:
    with transaction(settings.db_url) as conn:
        return conn.execute(f"select call_id, attempt, outcome, usd::float from {schema}.model_ledger order by id".encode()).fetchall()  # fmt: skip


def test_settlement_racing_admission_at_the_cap(settings: Settings, schema: str) -> None:
    a, b = PostgresBudgetStore(settings.db_url, schema), PostgresBudgetStore(settings.db_url, schema)
    assert a.admit(_attempt("ic-a", 0.008)).admitted  # the day is now at 0.008 of 0.010, pending
    assert not b.admit(_attempt("ic-b", 0.004)).admitted  # B sees A's reservation
    holder = connect(settings.db_url)  # A's settlement, holding the budget lock while B tries to admit
    holder.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"{schema}.model_budget",))
    holder.execute(f"insert into {schema}.model_ledger (at, purpose, usd, outcome, detail) values (%s, 'news_card', 0.008, 'ok', "
                   "'{\"call_id\": \"ic-a\", \"attempt\": 1, \"role\": \"CHEAP\"}') on conflict (call_id, attempt) "
                   "where call_id is not null do nothing".encode(), (NOW,))  # fmt: skip
    holder.execute(f"delete from {schema}.model_reservations where call_id = 'ic-a' and attempt = 1".encode())
    result: list[Any] = []
    waiting = threading.Thread(target=lambda: result.append(b.admit(_attempt("ic-b", 0.004))))
    waiting.start()
    waiting.join(timeout=2.0)
    assert waiting.is_alive()  # B waits on the lock while the settlement is open
    holder.commit()
    holder.close()
    waiting.join(timeout=30.0)
    assert result and not result[0].admitted  # B now sees the committed charge
    assert a.admit(_attempt("ic-c", 0.002)).admitted  # exactly up to the cap: 0.008 + 0.002
    assert not a.admit(_attempt("ic-d", 0.000001)).admitted
    assert [r[:3] for r in _ledger(settings, schema)] == [("ic-a", 1, "ok")]


def test_a_restart_between_dispatch_and_settlement_is_charged_once(settings: Settings, schema: str) -> None:
    store = PostgresBudgetStore(settings.db_url, schema)
    assert store.admit(_attempt("ic-lost", 0.003)).admitted  # dispatched, then the process "crashes"
    later = NOW + timedelta(minutes=5)  # past expires_at
    adm = store.admit(_attempt("ic-next", 0.001, now=later))
    assert adm.admitted and adm.reconciled == 1
    assert _ledger(settings, schema) == [("ic-lost", 1, "abandoned", 0.003)]  # charged its estimate, never freed
    assert store.settle(Settlement(_row("ic-lost", 0.0001))) is False  # the late settlement records nothing
    assert store.totals(later).day == 0.003  # one debit; ic-next is still a reservation
    assert store.totals(later).reservations == 1


def test_a_repeated_settlement_records_one_debit(settings: Settings, schema: str) -> None:
    store = PostgresBudgetStore(settings.db_url, schema)
    assert store.admit(_attempt("ic-r", 0.002)).admitted
    assert store.settle(Settlement(_row("ic-r", 0.00012345))) is True
    assert store.settle(Settlement(_row("ic-r", 0.00012345))) is False
    assert _ledger(settings, schema) == [("ic-r", 1, "ok", 0.00012345)]  # eight decimals kept
    assert store.totals(NOW).reservations == 0


def test_the_gateway_over_the_postgres_store(settings: Settings, schema: str) -> None:
    store = PostgresBudgetStore(settings.db_url, schema)
    ids = count(1)

    def call(provider: FakeProvider, **kw: Any) -> gateway.Result:
        return gateway.complete("CHEAP", MSG, purpose="news_card", store=store, clock=lambda: NOW, env=ON,
                                providers={"deepinfra": provider}, sleep=lambda s: None, use_cache=False,
                                new_id=lambda: f"ic-{next(ids):012d}", **kw)  # fmt: skip

    usage = {"prompt_tokens": 10, "completion_tokens": 5, "estimated_cost": 0.000123}
    reported = call(FakeProvider(lambda m, model: '{"answer": 42}', paid=True, usage=usage))
    assert reported.ok and reported.data == {"answer": 42} and reported.usd == 0.000123
    bare = FakeProvider(lambda m, model: Reply(text='{"answer": 1}'), paid=True)  # a valid answer, no usage block
    r = call(bare)
    assert r.ok and r.data == {"answer": 1} and r.usd_source == "estimated" and len(bare.calls) == 1
    rows = _ledger(settings, schema)
    assert [(row[2], row[1]) for row in rows] == [("ok", 1), ("ok", 1)]
    assert rows[1][3] == r.usd  # one estimated debit
    secret = "sk-invented-" + secrets.token_hex(8)
    s = gateway.status(store, {"DEEPINFRA_API_KEY": secret}, clock=lambda: NOW)
    assert secret not in repr(s) and s["paid_enabled"] is False  # readiness without the value; paid stays off

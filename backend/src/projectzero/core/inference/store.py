"""Where the gateway's money and cache live (review 029a, plan revisions 2 and 3): the ``BudgetStore`` Protocol, its
records, and ``InMemoryBudgetStore`` (the exact reference implementation, for tests and the oracle). The Postgres
store (``pg_store.py``) implements the same Protocol over ``model_ledger``, ``model_reservations`` and
``model_cache``.

The contract, per method (each runs as ONE atomic step: in Postgres one transaction under
``pg_advisory_xact_lock(hashtext('<schema>.model_budget'))``; here one ``threading.Lock``):

``admit(attempt, *, wait_s=None)``
    1. **reconcile**: every reservation with ``expires_at <= attempt.now`` becomes the ledger row
       ``abandoned_row(reservation)`` (outcome ``abandoned``, ``usd`` = its estimate, ``usd_source`` ``estimated``),
       inserted ``on conflict (call_id, attempt) where call_id is not null do nothing``, and the reservation is
       deleted. An abandoned attempt keeps counting as spent;
    2. **check** (only when ``attempt.check``): ``budget.check(attempt.limits, <Spend>, ...)`` over the committed
       ledger and EVERY remaining live reservation (``Spend`` documents each sum). A refusal returns
       ``Admission(False, reason)`` and reserves nothing;
    3. **reserve**: one reservation keyed by (``call_id``, ``attempt``) with the estimate and ``expires_at``.
``settle(settlement, *, wait_s=None)``
    inserts ``settlement.row`` ``on conflict (call_id, attempt) where call_id is not null do nothing`` AND deletes the
    reservation (``call_id``, ``attempt``) if there is one. Returns True when the row was inserted, False when that
    attempt was already recorded (a repeated or late settlement: nothing is inserted, the existing row stands, so
    exactly one debit exists). The next admitter therefore sees either the reservation or the committed charge.
``wait_s`` (review 028d, plan revision 3): ``None`` waits for the budget lock as long as it takes (029a); a number
    waits at most that many seconds, and ``<= 0`` takes the lock only if it is free right now (Postgres:
    ``lock_timeout`` / ``statement_timeout`` set to it before ``pg_advisory_xact_lock``, or
    ``pg_try_advisory_xact_lock`` for no wait). A store that cannot get the lock in time raises ``BudgetBusy`` and
    has done NOTHING: no reconciliation, no reservation, no row, no reservation retired. The gateway passes ``wait_s``
    only when its caller gave a ``deadline``, so a store without the keyword keeps working for calls without one.
``cache_get(key)`` / ``cache_put(entry)``
    the response cache (no TTL, as before); a put replaces the entry under the same key.
``totals(now)``
    the budget summary sums for ``status()``.

Every row the gateway writes carries ``call_id`` and ``attempt`` in ``detail`` (the generated columns of migration
0021); attempt 0 is a call's row that made no attempt (a refusal before admission, a cache hit).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from projectzero.core.inference import budget
from projectzero.core.inference.budget import Limits, Spend

OUTCOMES = ("ok", "cache_hit", "error", "blocked", "disabled", "abandoned")

# the keys the writer puts in ``detail`` (migration 0021 promotes role, run_id, call_id, attempt, error_kind)
DETAIL_KEYS = (
    "call_id",  # "ic-" + 12 hex, one per complete() call
    "attempt",  # 0: no attempt (refused before admission, cache hit); 1..n: the attempt this row settles
    "attempts",  # attempts dispatched by the call when this row was written (the old field)
    "role",  # CHEAP / STANDARD / ESCALATION (or the unknown role asked for)
    "run_id",  # the caller's run (the run cap), or None
    "error_kind",  # the error kind, or None (ok, cache_hit, abandoned)
    "usd_source",  # reported | priced | estimated | none
    "prompt_sha",  # sha256[:16] of the system messages (the prompt VERSION; prompts are never stored)
    "request_sha",  # the cache key (absent when the call was refused before it was computed)
    "latency_ms",  # this attempt's latency (None for an abandoned row)
    "cached_input_tokens",  # usage.prompt_tokens_details.cached_tokens, or None
    "override_reason",  # only when an override was given (stripped, at most 300 characters)
)


class BudgetBusy(Exception):
    """The budget lock could not be taken within the caller's ``wait_s`` (review 028d): the store did nothing."""


@dataclass(frozen=True)
class LedgerRow:
    """One ``model_ledger`` row, every column but the identity ``id`` (the store assigns it; insertion order).

    ``at`` is timezone-aware (written in Europe/Berlin); ``usd`` goes to ``numeric(14,8)``; ``tokens_in`` /
    ``tokens_out`` are the usage's prompt / completion tokens when integers, else None; ``outcome`` is one of
    ``OUTCOMES``; ``detail`` holds ``DETAIL_KEYS`` (imported rows hold the old keys, without ``attempt``)."""

    at: datetime
    purpose: str
    provider: str | None
    model: str | None
    entity_ref: str | None
    usd: float
    tokens_in: int | None
    tokens_out: int | None
    cached: bool
    outcome: str | None
    detail: Mapping[str, Any] = field(default_factory=dict)

    @property
    def call_id(self) -> str | None:
        v = self.detail.get("call_id")
        return v if isinstance(v, str) else None

    @property
    def attempt(self) -> int | None:
        v = self.detail.get("attempt")
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    @property
    def role(self) -> str | None:
        v = self.detail.get("role")
        return v if isinstance(v, str) else None

    @property
    def run_id(self) -> str | None:
        v = self.detail.get("run_id")
        return v if isinstance(v, str) else None

    @property
    def error_kind(self) -> str | None:
        v = self.detail.get("error_kind")
        return v if isinstance(v, str) else None

    @property
    def usd_source(self) -> str | None:
        v = self.detail.get("usd_source")
        return v if isinstance(v, str) else None

    @property
    def key(self) -> tuple[str, int] | None:
        """The idempotency key (``call_id``, ``attempt``); None for an imported row without them."""
        c, a = self.call_id, self.attempt
        return (c, a) if c is not None and a is not None else None


@dataclass(frozen=True)
class AttemptRequest:
    """One attempt asking to be admitted. ``now`` is the gateway's clock (aware): the store uses it for the windows,
    for expiry and as the reservation time. ``est_usd`` is the attempt's worst-case estimate (the same for every
    attempt of a call). ``check`` False (a free provider) reserves without running the rules. ``detail`` carries
    what the abandoned row would need beyond the reservation's fields (``prompt_sha``, ``request_sha``,
    ``override_reason``)."""

    call_id: str
    attempt: int
    role: str
    purpose: str
    provider: str
    model: str
    entity_id: str | None
    run_id: str | None
    est_usd: float
    limits: Limits
    run_cap_usd: float | None
    override_reason: str | None
    now: datetime
    expires_at: datetime
    check: bool = True
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Reservation:
    """One live ``model_reservations`` row, keyed by (``call_id``, ``attempt``)."""

    call_id: str
    attempt: int
    usd: float
    role: str
    purpose: str
    provider: str
    model: str
    entity_id: str | None
    run_id: str | None
    reserved_at: datetime
    expires_at: datetime
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Admission:
    """``admitted`` with ``reason`` '' (reserved), or refused with the block reason (nothing reserved).
    ``reconciled``: how many expired reservations this admission turned into ``abandoned`` rows."""

    admitted: bool
    reason: str = ""
    reconciled: int = 0


@dataclass(frozen=True)
class Settlement:
    """The ledger row of one attempt (or of a call that made none: ``attempt`` 0). ``row.detail`` must carry
    ``call_id`` and ``attempt``: they are the idempotency key and the reservation to retire."""

    row: LedgerRow

    def __post_init__(self) -> None:
        if self.row.key is None:
            raise ValueError("a settlement row needs detail.call_id and detail.attempt")

    @property
    def call_id(self) -> str:
        key = self.row.key
        assert key is not None
        return key[0]

    @property
    def attempt(self) -> int:
        key = self.row.key
        assert key is not None
        return key[1]


@dataclass(frozen=True)
class CacheEntry:
    """One ``model_cache`` row: the reply text of an accepted call, keyed by the request sha (no TTL)."""

    key: str
    provider: str
    model: str
    text: str
    stored_at: datetime


@dataclass(frozen=True)
class Totals:
    """The budget summary sums: committed spend today / this week / this month (Berlin windows) / all time (each
    rounded to 6), committed spend by role (``str(role)``, so imported rows without one count under ``"None"``),
    row counts by outcome, and the live reservations (count and USD)."""

    day: float
    week: float
    month: float
    all_time: float
    by_role: Mapping[str, float]
    outcomes: Mapping[str, int]
    reservations: int
    pending: float


class BudgetStore(Protocol):
    """The gateway's persistence. Each method is atomic (see the module docstring for the exact contract)."""

    def admit(self, attempt: AttemptRequest, *, wait_s: float | None = None) -> Admission: ...

    def settle(self, settlement: Settlement, *, wait_s: float | None = None) -> bool: ...

    def cache_get(self, key: str, *, wait_s: float | None = None) -> CacheEntry | None: ...

    def cache_put(self, entry: CacheEntry, *, wait_s: float | None = None) -> None: ...

    def totals(self, now: datetime) -> Totals: ...


def reservation_of(req: AttemptRequest) -> Reservation:
    return Reservation(
        call_id=req.call_id,
        attempt=req.attempt,
        usd=req.est_usd,
        role=req.role,
        purpose=req.purpose,
        provider=req.provider,
        model=req.model,
        entity_id=req.entity_id,
        run_id=req.run_id,
        reserved_at=req.now,
        expires_at=req.expires_at,
        detail=dict(req.detail),
    )


def abandoned_row(res: Reservation) -> LedgerRow:
    """The row an expired reservation becomes: charged its estimate, dated when it was reserved (the attempt was
    dispatched then), outcome ``abandoned``."""
    detail: dict[str, Any] = {
        "call_id": res.call_id,
        "attempt": res.attempt,
        "attempts": res.attempt,
        "role": res.role,
        "run_id": res.run_id,
        "error_kind": None,
        "usd_source": "estimated",
        "latency_ms": None,
        "cached_input_tokens": None,
    }
    for k in ("prompt_sha", "request_sha", "override_reason"):
        if k in res.detail:
            detail[k] = res.detail[k]
    return LedgerRow(
        at=res.reserved_at,
        purpose=res.purpose,
        provider=res.provider,
        model=res.model,
        entity_ref=res.entity_id,
        usd=res.usd,
        tokens_in=None,
        tokens_out=None,
        cached=False,
        outcome="abandoned",
        detail=detail,
    )


def spend_of(
    rows: Iterable[LedgerRow],
    pending: Iterable[Reservation],
    *,
    now: datetime,
    role: str,
    entity_id: str | None,
    run_id: str | None,
) -> Spend:
    """``Spend`` from rows and live reservations, summed in insertion order exactly as the old ``ledger.spend`` /
    ``total`` / ``role_month`` and the old pending sums did (the Postgres store sums the same sets in SQL)."""
    day0, week0, month0 = budget.windows(now)
    rows = list(rows)
    day = week = month = role_month = 0.0
    for r in rows:
        v = float(r.usd or 0.0)
        if not v:
            continue
        day += v if r.at >= day0 else 0.0
        week += v if r.at >= week0 else 0.0
        month += v if r.at >= month0 else 0.0
    role_month = sum(float(r.usd or 0.0) for r in rows if r.role == role and r.at >= month0)
    entity = sum(float(r.usd or 0.0) for r in rows if r.entity_ref == entity_id) if entity_id else 0.0
    run = sum(float(r.usd or 0.0) for r in rows if r.run_id == run_id) if run_id else 0.0
    pend = list(pending)
    return Spend(
        day=round(day, 6),
        week=round(week, 6),
        month=round(month, 6),
        role_month=round(role_month, 6),
        entity=round(entity, 6),
        run=round(run, 6),
        pending=sum(p.usd for p in pend),
        pending_role=sum(p.usd for p in pend if p.role == role),
        pending_entity=sum(p.usd for p in pend if p.entity_id == entity_id) if entity_id else 0.0,
        pending_run=sum(p.usd for p in pend if p.run_id == run_id) if run_id else 0.0,
    )


class InMemoryBudgetStore:
    """The reference ``BudgetStore``: rows in insertion order, reservations keyed by (``call_id``, ``attempt``), the
    cache in a dict, every method under one lock. ``rows`` seeds the ledger (imported rows may lack the key).

    The busy-lock seam (review 028d): while ``monotonic() < busy_until`` the budget lock is held by "another
    connection". ``admit`` / ``settle`` then wait for it through ``sleep`` (a fake clock's advance in tests) at most
    ``wait_s``: the lock is taken if it frees within the bound, else ``BudgetBusy`` is raised after waiting the bound
    (``wait_s`` None waits until it frees, as an unbounded advisory lock would). ``waited`` records every wait.
    ``busy_until`` None (the default) is a free lock; the real ``threading.Lock`` is also taken within ``wait_s``."""

    def __init__(
        self,
        rows: Iterable[LedgerRow] = (),
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._lock = threading.Lock()
        self.rows: list[LedgerRow] = list(rows)
        self.reservations: dict[tuple[str, int], Reservation] = {}
        self.cache: dict[str, CacheEntry] = {}
        self.late: list[tuple[str, int]] = []  # settlements that found their attempt already recorded
        self.monotonic = monotonic
        self.sleep = sleep
        self.busy_until: float | None = None
        self.waited: list[float] = []
        self.busy: list[tuple[str, str, int]] = []  # (method, call_id, attempt) refused with BudgetBusy

    @contextmanager
    def _budget_lock(self, wait_s: float | None, what: tuple[str, str, int]) -> Iterator[None]:
        """The budget lock within ``wait_s`` (see the class docstring), else ``BudgetBusy`` with nothing done."""
        left = wait_s
        if self.busy_until is not None:
            hold = self.busy_until - self.monotonic()
            if hold > 0:
                if left is not None and hold > left:
                    pause = max(0.0, left)
                    if pause:
                        self.waited.append(pause)
                        self.sleep(pause)
                    self.busy.append(what)
                    raise BudgetBusy(f"the budget lock was busy for more than {max(0.0, left):.3f}s")
                self.waited.append(hold)
                self.sleep(hold)
                left = None if left is None else max(0.0, left - hold)
        if left is None:
            got = self._lock.acquire()
        elif left > 0:
            got = self._lock.acquire(timeout=left)
        else:
            got = self._lock.acquire(blocking=False)
        if not got:
            self.busy.append(what)
            raise BudgetBusy(f"the budget lock was busy for more than {max(0.0, left or 0.0):.3f}s")
        try:
            yield
        finally:
            self._lock.release()

    # ---- the Protocol
    def admit(self, attempt: AttemptRequest, *, wait_s: float | None = None) -> Admission:
        with self._budget_lock(wait_s, ("admit", attempt.call_id, attempt.attempt)):
            reconciled = self._reconcile(attempt.now)
            if attempt.check:
                spend = spend_of(
                    self.rows,
                    self.reservations.values(),
                    now=attempt.now,
                    role=attempt.role,
                    entity_id=attempt.entity_id,
                    run_id=attempt.run_id,
                )
                reason = budget.check(
                    attempt.limits,
                    spend,
                    est_usd=attempt.est_usd,
                    role=attempt.role,
                    entity_id=attempt.entity_id,
                    run_id=attempt.run_id,
                    run_cap_usd=attempt.run_cap_usd,
                    override_reason=attempt.override_reason,
                    purpose=attempt.purpose,
                )
                if reason:
                    return Admission(False, reason, reconciled)
            self.reservations[(attempt.call_id, attempt.attempt)] = reservation_of(attempt)
            return Admission(True, "", reconciled)

    def settle(self, settlement: Settlement, *, wait_s: float | None = None) -> bool:
        with self._budget_lock(wait_s, ("settle", settlement.call_id, settlement.attempt)):
            key = (settlement.call_id, settlement.attempt)
            inserted = self._insert(settlement.row)
            self.reservations.pop(key, None)
            if not inserted:
                self.late.append(key)
            return inserted

    def cache_get(self, key: str, *, wait_s: float | None = None) -> CacheEntry | None:
        with self._lock:
            return self.cache.get(key)

    def cache_put(self, entry: CacheEntry, *, wait_s: float | None = None) -> None:
        with self._lock:
            self.cache[entry.key] = entry

    def totals(self, now: datetime) -> Totals:
        with self._lock:
            day0, week0, month0 = budget.windows(now)
            out = {"day": 0.0, "week": 0.0, "month": 0.0, "all_time": 0.0}
            by_role: dict[str, float] = {}
            outcomes: dict[str, int] = {}
            for r in self.rows:
                v = float(r.usd or 0.0)
                by_role[str(r.role)] = round(by_role.get(str(r.role), 0.0) + v, 6)
                outcomes[str(r.outcome)] = outcomes.get(str(r.outcome), 0) + 1
                if not v:
                    continue
                out["all_time"] += v
                out["day"] += v if r.at >= day0 else 0.0
                out["week"] += v if r.at >= week0 else 0.0
                out["month"] += v if r.at >= month0 else 0.0
            return Totals(
                day=round(out["day"], 6),
                week=round(out["week"], 6),
                month=round(out["month"], 6),
                all_time=round(out["all_time"], 6),
                by_role=by_role,
                outcomes=outcomes,
                reservations=len(self.reservations),
                pending=sum(p.usd for p in self.reservations.values()),
            )

    # ---- helpers (tests and the oracle)
    def spend(self, *, now: datetime, role: str, entity_id: str | None, run_id: str | None) -> Spend:
        """The snapshot an admission would check (without reconciling)."""
        with self._lock:
            return spend_of(
                self.rows, self.reservations.values(), now=now, role=role, entity_id=entity_id, run_id=run_id
            )

    def hold(self, reservation: Reservation) -> None:
        """Insert a live reservation without the rules (another caller's in-flight attempt)."""
        with self._lock:
            self.reservations[(reservation.call_id, reservation.attempt)] = reservation

    def drop(self, call_id: str, attempt: int) -> None:
        with self._lock:
            self.reservations.pop((call_id, attempt), None)

    def _insert(self, row: LedgerRow) -> bool:
        key = row.key
        if key is not None and any(r.key == key for r in self.rows):
            return False
        self.rows.append(row)
        return True

    def _reconcile(self, now: datetime) -> int:
        expired = [k for k, r in self.reservations.items() if r.expires_at <= now]
        for k in expired:
            self._insert(abandoned_row(self.reservations.pop(k)))
        return len(expired)

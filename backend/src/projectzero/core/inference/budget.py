"""The budget rules (review 029a), PURE: the old ``inference/budget.py`` (rev 6c739b9) rule order, estimate and
actual-cost rules over an abstract ``Spend`` snapshot, so the in-memory store and the Postgres store run the SAME rules.

``check`` (one attempt; plan revision 2: every ATTEMPT is admitted, the first and each retry), in the old order:

1. the run cap (when ``run_cap_usd`` and ``run_id``): the run's committed spend + its pending reservations + the
   estimate > the cap -> block. Enforced EVEN WITH an override (it is the caller's own ceiling);
2. an override: a reason shorter than 8 characters (after strip) -> block; else admit, skipping 3-6;
3. the per-call cap: the estimate > ``purpose_max_call_usd[purpose]`` (else ``max_call_usd``);
4. the day, ISO week (Monday) and calendar month on the Europe/Berlin clock: the window's committed spend + EVERY
   pending reservation + the estimate > the window's cap;
5. the role's monthly cap (when the role has one): the role's committed spend this month + the role's pending;
6. the entity's all-time cap (when ``entity_id``): the entity's committed spend + the entity's pending.

The messages are the old ones, verbatim. Committed spend comes ONLY from ledger rows' ``usd`` (blocked, disabled,
cache-hit and before-dispatch rows are 0; ``abandoned`` rows carry their estimate and keep counting).

The cost of one attempt (plan revisions 2 and 3, ``attempt_cost`` / ``reply_cost``):

* a failure BEFORE dispatch (nothing reached the provider): $0, ``none``;
* an answer: the provider-reported cost (``reported``), else priced from its usage (``priced``), else - a VALID reply
  without usage included - the attempt's estimate (``estimated``), with the reply's own outcome (``ok`` when valid);
* a failure AFTER dispatch (a timeout or reset after sending, an HTTP error status, a malformed body): the provider
  may have billed it, so the attempt is charged its estimate (``estimated``), outcome ``error``.

A free provider (the fake with ``paid=False``) is never charged an estimate: only a reported cost, else $0 ``none``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, TypeGuard
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
MIN_OVERRIDE_REASON = 8  # the same bar as the Omar-handoff override

USD_SOURCES = ("reported", "priced", "estimated", "none")


@dataclass(frozen=True)
class Limits:
    """The caps in USD (``inf`` when missing or invalid, as before)."""

    max_call_usd: float = math.inf
    entity_cap_usd: float = math.inf
    daily_usd: float = math.inf
    weekly_usd: float = math.inf
    monthly_usd: float = math.inf
    role_monthly_usd: Mapping[str, float] = field(default_factory=dict)
    purpose_max_call_usd: Mapping[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_call_usd": self.max_call_usd,
            "entity_cap_usd": self.entity_cap_usd,
            "daily_usd": self.daily_usd,
            "weekly_usd": self.weekly_usd,
            "monthly_usd": self.monthly_usd,
            "role_monthly_usd": dict(self.role_monthly_usd),
            "purpose_max_call_usd": dict(self.purpose_max_call_usd),
        }


def limits(cfg: Mapping[str, Any]) -> Limits:
    """The old ``limits(cfg)``."""
    b = cfg.get("budget") if isinstance(cfg.get("budget"), Mapping) else {}
    assert isinstance(b, Mapping)
    vals: dict[str, float] = {}
    for k in ("max_call_usd", "entity_cap_usd", "daily_usd", "weekly_usd", "monthly_usd"):
        try:
            vals[k] = float(b[k])
        except (KeyError, TypeError, ValueError):
            vals[k] = math.inf
    roles = b.get("role_monthly_usd") if isinstance(b.get("role_monthly_usd"), Mapping) else {}
    purp = b.get("purpose_max_call_usd") if isinstance(b.get("purpose_max_call_usd"), Mapping) else {}
    assert isinstance(roles, Mapping) and isinstance(purp, Mapping)
    return Limits(
        **vals,
        role_monthly_usd={str(r): float(v) for r, v in roles.items() if isinstance(v, int | float)},
        purpose_max_call_usd={str(p): float(v) for p, v in purp.items() if isinstance(v, int | float)},
    )


def estimate_usd(price: Mapping[str, float], input_chars: int, max_output_tokens: int) -> float:
    """Worst case: ~3.5 characters per input token, the full output allowance, no cache discount."""
    in_tokens = input_chars / 3.5
    return round((in_tokens * price["input"] + max_output_tokens * price["output"]) / 1_000_000, 6)


def _count(v: Any) -> TypeGuard[float]:
    """A usable token count: a finite, non-negative number that is not a bool."""
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) and v >= 0


def usable_usd(v: Any) -> TypeGuard[float]:
    """A usable reported cost: a finite, non-negative number that is not a bool."""
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) and v >= 0


def actual_usd(price: Mapping[str, float], usage: Any) -> float | None:
    """Cost from reported token usage (OpenAI-style fields); None when the provider reported no usable usage."""
    if not isinstance(usage, Mapping):
        return None
    pin, pout = (
        usage.get("prompt_tokens", usage.get("input_tokens")),
        usage.get("completion_tokens", usage.get("output_tokens")),
    )
    if not _count(pin) or not _count(pout):  # Codex H-271: negative / non-finite / bool counts are unusable
        return None
    det = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), Mapping) else {}
    assert isinstance(det, Mapping)
    raw = det.get("cached_tokens")
    tin, tout = float(pin), float(pout)
    cached: float = min(float(raw) if _count(raw) else 0.0, tin)
    return round(
        ((tin - cached) * price["input"] + cached * price["cached_input"] + tout * price["output"]) / 1_000_000, 8
    )


def reply_cost(
    *, paid: bool, price: Mapping[str, float] | None, est_usd: float, reported_usd: float | None, usage: Any
) -> tuple[float, str]:
    """An answered attempt: reported -> priced -> estimated (the old order; a free provider: reported or $0)."""
    if usable_usd(reported_usd):  # Codex H-271: a negative or non-finite reported cost is unusable metadata
        assert reported_usd is not None
        return round(reported_usd, 8), "reported"
    if price is not None and paid:
        priced = actual_usd(price, usage)
        return (priced, "priced") if priced is not None else (est_usd, "estimated")
    return 0.0, "none"


def attempt_cost(*, paid: bool, est_usd: float, dispatched: bool) -> tuple[float, str]:
    """A failed attempt: before dispatch $0 ``none``; after dispatch the estimate ``estimated`` (paid only)."""
    if dispatched and paid:
        return est_usd, "estimated"
    return 0.0, "none"


def windows(now: datetime) -> tuple[datetime, datetime, datetime]:
    """The start of today, this ISO week (Monday) and this calendar month on the Europe/Berlin wall clock (the old
    windows on the machine's naive local clock, which was Berlin)."""
    local = now.astimezone(BERLIN) if now.tzinfo is not None else now.replace(tzinfo=BERLIN)
    day0 = datetime(local.year, local.month, local.day, tzinfo=BERLIN)
    week0 = day0 - timedelta(days=day0.weekday())
    week0 = datetime(week0.year, week0.month, week0.day, tzinfo=BERLIN)
    month0 = datetime(local.year, local.month, 1, tzinfo=BERLIN)
    return day0, week0, month0


@dataclass(frozen=True)
class Spend:
    """What a store must sum for ONE admission (under its lock).

    Committed (ledger rows' ``usd``, each sum rounded to 6 decimals as before): ``day`` / ``week`` / ``month``: rows
    with ``at`` >= the window start (``windows(now)``; a future row counts); ``role_month``: rows of this role with
    ``at`` >= the month start; ``entity``: every row of this ``entity_ref`` (all time; 0 without an entity);
    ``run``: every row of this ``run_id`` (0 without a run id).

    Pending (live reservations, after expired ones were reconciled; not windowed, as before): ``pending``: all of
    them; ``pending_role`` / ``pending_entity`` / ``pending_run``: those of this role / entity / run."""

    day: float = 0.0
    week: float = 0.0
    month: float = 0.0
    role_month: float = 0.0
    entity: float = 0.0
    run: float = 0.0
    pending: float = 0.0
    pending_role: float = 0.0
    pending_entity: float = 0.0
    pending_run: float = 0.0


def check(
    lim: Limits,
    spend: Spend,
    *,
    est_usd: float,
    role: str,
    entity_id: str | None,
    run_id: str | None,
    run_cap_usd: float | None,
    override_reason: str | None,
    purpose: str = "",
) -> str:
    """'' when the attempt may proceed, else the operator-readable block reason (the old ``check``, same order and
    texts)."""
    if run_cap_usd is not None and run_id:
        used = spend.run + spend.pending_run
        if used + est_usd > run_cap_usd:
            return f"run cap reached for {run_id} (${used:.4f} spent + ${est_usd:.4f} next > ${run_cap_usd:.2f})"
    if override_reason is not None:
        if len(override_reason.strip()) < MIN_OVERRIDE_REASON:
            return f"override reason must be at least {MIN_OVERRIDE_REASON} characters"
        return ""
    call_cap = lim.purpose_max_call_usd.get(purpose, lim.max_call_usd)
    if est_usd > call_cap:
        return f"single call estimate ${est_usd:.4f} exceeds the per-call cap ${call_cap:.2f}"
    extra = spend.pending
    for window, value, cap in (
        ("day", spend.day, lim.daily_usd),
        ("week", spend.week, lim.weekly_usd),
        ("month", spend.month, lim.monthly_usd),
    ):
        if value + extra + est_usd > cap:
            return (
                f"{window} budget reached (${value + extra:.4f} spent + ${est_usd:.4f} next > "
                f"${cap:.2f}) — Mohamed may override with a reason"
            )
    role_cap = lim.role_monthly_usd.get(role)
    if role_cap is not None:
        used = spend.role_month + spend.pending_role
        if used + est_usd > role_cap:
            return f"{role} monthly cap reached (${used:.4f} + ${est_usd:.4f} > ${role_cap:.2f})"
    if entity_id:
        used = spend.entity + spend.pending_entity
        if used + est_usd > lim.entity_cap_usd:
            return f"spend on {entity_id} would exceed the per-entity cap ${lim.entity_cap_usd:.2f}"
    return ""

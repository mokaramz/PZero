"""The inference gateway (review 029a): ``complete(role, messages, ...) -> Result``, the old
``inference/gateway.py`` (rev 6c739b9) over a ``BudgetStore``.

Order of operations for one call (the old order, except where marked):
  1. the role (unknown -> ``not_configured``; disabled -> ``disabled``), its provider and model, the provider resolved;
  2. a paid provider: its key present and the model's price known (else ``not_configured``);
  3. a paid provider: the paid switch, ``PZ_AI_PAID`` exactly ``on`` (else ``disabled``). CHANGED (decision c): the
     old switch was on unless set off. CHANGED (decision d): the switch comes BEFORE the cache, so a cached paid
     answer is not served while paid calls are off;
  4. the response cache (an identical request -> the stored reply, re-validated, $0, still ledgered);
  5. per ATTEMPT (CHANGED, plan revision 2; the old code reserved once per call): ``store.admit`` runs the budget rules
     with the attempt's estimate and reserves it; a refused first attempt is ``budget_blocked``, a retry that no
     longer fits ends the call ``budget_blocked`` unsent, with the attempts so far settled;
  6. the provider call, at most 3 attempts: only timeout / rate_limited / server / network are retried, after 2 s
     then 6 s (``Retry-After`` honoured up to 30 s; an "overloaded" or "busy" message doubles the wait, up to 30 s);
  7. JSON extraction and the caller's validation (malformed or invalid replies are failures, never defaults);
  8. every attempt settled as its own ledger row (``store.settle``, idempotent by (call_id, attempt)); a call that
     made no attempt writes one row with attempt 0. The cost rules are ``budget.reply_cost`` / ``attempt_cost``.

Expected failures never raise: callers branch on ``Result.ok`` / ``Result.error_kind``. ``STOP_KINDS`` are the
failures after which a batch must stop instead of moving on to the next item. Prompts and keys are never stored.

The deadline (review 028d, plan revisions 2 and 3; additive: without ``deadline`` the call is exactly 029a's). With
``deadline`` (a ``monotonic()`` time) the WHOLE call is bounded:
  * before each attempt's admission: no time left -> the call ends ``deadline`` (not a ``STOP_KINDS`` kind), nothing
    admitted, nothing sent, no row for that attempt (writing one would need the budget lock);
  * ``store.admit`` / ``store.settle`` get ``wait_s`` = the time left (``<= 0``: only a free lock); ``BudgetBusy`` at
    admission ends the call ``deadline`` with nothing reserved and nothing sent;
  * after admission (which may have waited) the deadline is checked again: no time left -> the attempt is NOT sent
    and its fresh reservation is settled at $0 ``none`` (outcome ``error``, kind ``deadline``) without waiting;
  * each attempt's timeout is ``min(role timeout, time left)`` (the provider's own deadline over the exchange is
    ``timeout_s`` from its start, so the transport ends by the call's deadline);
  * a retry wait that would end at or past the deadline is not taken: the call ends ``deadline``, no further
    dispatch;
  * a DISPATCHED attempt whose settlement raises ``BudgetBusy`` keeps its reservation (it already counts as pending;
    after ``expires_at`` the next admission reconciles it into an ``abandoned`` row charged its estimate, and a late
    settlement records nothing, so there is never a duplicate debit). The settlement is NOT retried past the
    deadline: ``Result.unsettled`` lists the attempt, ``Result.settled`` is False, and the call ends (a failed
    attempt ends it ``deadline``; a valid reply stays ``ok``: it is paid for).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from projectzero.core.inference import budget
from projectzero.core.inference import config as icfg
from projectzero.core.inference.providers import Provider, ProviderError, Reply
from projectzero.core.inference.providers import resolve as resolve_provider
from projectzero.core.inference.store import (
    Admission,
    AttemptRequest,
    BudgetBusy,
    BudgetStore,
    CacheEntry,
    LedgerRow,
    Settlement,
)

log = logging.getLogger("projectzero.inference")

STOP_KINDS = frozenset({"disabled", "not_configured", "budget_blocked", "auth", "billing"})
ERROR_KINDS = frozenset(
    {
        "not_configured",  # unknown role, no provider / model, no key, no price
        "disabled",  # the role is off, or the paid switch is
        "budget_blocked",  # a cap
        "auth",  # 401 / 403
        "billing",  # 402
        "rate_limited",  # 429
        "timeout",  # 408, a timeout
        "server",  # >= 500
        "network",  # the connection failed or broke
        "bad_request",  # another 4xx, a refused URL
        "malformed",  # an unusable response, or no JSON in the reply
        "invalid",  # the caller's validation refused the reply
        "deadline",  # the caller's deadline: no time left to admit, send, wait for a retry or get the budget lock
    }
)
RESERVATION_MARGIN_S = 60.0  # expires_at = the reservation time + the attempt's timeout + this margin
MAX_WAIT_S = 30.0


def berlin_now() -> datetime:
    return datetime.now(budget.BERLIN)


def new_call_id() -> str:
    return "ic-" + uuid.uuid4().hex[:12]


@dataclass
class Result:
    ok: bool
    role: str
    provider: str = ""
    model: str = ""
    text: str = ""
    data: Any = None
    error_kind: str = ""
    error: str = ""
    usd: float = 0.0  # every attempt's charge, summed
    usd_source: str = "none"  # the last dispatched attempt's: reported | priced | estimated | none
    usage: dict[str, Any] = field(default_factory=dict)
    cached: bool = False
    tool_calls: list[dict[str, Any]] = field(default_factory=list)  # function calls for the caller to run (never here)
    attempts: int = 0  # attempts dispatched (or refused by the provider before dispatch)
    latency_ms: int = 0
    call_id: str = ""

    @property
    def must_stop(self) -> bool:
        return not self.ok and self.error_kind in STOP_KINDS

    @property
    def unsettled(self) -> tuple[int, ...]:
        """The attempts whose settlement could not get the budget lock before the deadline (review 028d): each keeps
        its reservation until the reconciler charges it. Kept outside the dataclass fields, so a 029a ``Result``
        (its fields, ``__dict__``) is unchanged."""
        return tuple(self.__dict__.get("_unsettled", ()))

    @property
    def settled(self) -> bool:
        return not self.unsettled


def extract_json(text: str) -> Any:
    """The JSON value in a model reply: whole text, a ```json fence, or the outermost {...}. None when absent."""
    t = (text or "").strip()
    for candidate in (t, *re.findall(r"```(?:json)?\s*(.*?)```", t, re.S)):
        try:
            return json.loads(candidate)
        except ValueError:
            pass
    i, j = t.find("{"), t.rfind("}")
    if 0 <= i < j:
        try:
            return json.loads(t[i : j + 1])
        except ValueError:
            return None
    return None


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


# options of an OpenAI-compatible body that change what one call can bill; the estimate prices ``max_out`` and one
# completion, so they are refused before admission (Codex H-271), and the provider never lets an extra override them
BILLING_OPTIONS = frozenset({"max_tokens", "max_completion_tokens", "n", "best_of"})


def _tokens(v: Any) -> int | None:
    """A usable token count: a non-negative int (not a bool), else None (Codex H-271: invalid metadata is unusable)."""
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def complete(
    role: str,
    messages: list[dict[str, str]],
    *,
    purpose: str,
    entity_id: str | None = None,
    run_id: str | None = None,
    run_cap_usd: float | None = None,
    json_mode: bool = True,
    validate: Callable[[Any], Any] | None = None,
    model: str | None = None,
    max_output_tokens: int | None = None,
    override_reason: str | None = None,
    use_cache: bool = True,
    extra_body: Mapping[str, Any] | None = None,
    timeout_s: float | None = None,
    store: BudgetStore,
    clock: Callable[[], datetime] | None = None,
    env: Mapping[str, str] | None = None,
    providers: Mapping[str, Provider] | None = None,
    config: Mapping[str, Any] | None = None,
    sleep: Callable[[float], None] | None = None,
    new_id: Callable[[], str] | None = None,
    deadline: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> Result:
    """Run one model call under the budget. ``validate(data)`` may return a cleaned value or raise ``ValueError``.
    ``extra_body`` (merged over the role's ``extra_body``) carries provider-specific options; it is part of the cache
    key. ``store`` holds the ledger, the reservations and the cache; ``clock`` (aware; Europe/Berlin by default),
    ``env`` (``os.environ`` by default: the paid switch and the key, read at call time), ``providers`` (by name, over
    the configured ones), ``config`` (``config.load()`` by default), ``sleep`` and ``new_id`` are injectable.
    ``deadline`` (a ``monotonic()`` time, review 028d) bounds the whole call: see the module docstring."""
    cfg = config if config is not None else icfg.load()
    environ: Mapping[str, str] = os.environ if env is None else env
    now = clock or berlin_now
    pause = sleep or time.sleep
    call_id = (new_id or new_call_id)()
    res = Result(ok=False, role=role, call_id=call_id)
    rcfg = (cfg.get("roles") or {}).get(role)
    base: dict[str, Any] = {
        "call_id": call_id,
        "role": role,
        "run_id": run_id,
        # the prompt VERSION (system instructions only): a change in outputs is attributable to a prompt change
        "prompt_sha": _sha([m.get("content") for m in messages if isinstance(m, dict) and m.get("role") == "system"])[
            :16
        ],
    }
    if override_reason is not None:
        base["override_reason"] = override_reason.strip()[:300]
    charged = 0.0

    def left() -> float:
        return float("inf") if deadline is None else deadline - monotonic()

    def bound() -> dict[str, float]:
        """The store's wait bound: only with a deadline (a store without ``wait_s`` keeps working without one)."""
        return {} if deadline is None else {"wait_s": max(0.0, left())}

    def unsettled(attempt: int) -> None:
        res.__dict__.setdefault("_unsettled", []).append(attempt)

    def row(
        outcome: str,
        attempt: int,
        *,
        usd: float,
        usd_source: str,
        usage: Mapping[str, Any],
        error_kind: str | None,
        latency_ms: int,
    ) -> bool:
        det = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), Mapping) else {}
        assert isinstance(det, Mapping)
        detail = {
            **base,
            "attempt": attempt,
            "attempts": res.attempts,
            "error_kind": error_kind or None,
            "usd_source": usd_source,
            "latency_ms": latency_ms,
            "cached_input_tokens": det.get("cached_tokens"),
        }
        entry = LedgerRow(
            at=now(),
            purpose=purpose,
            provider=res.provider,
            model=res.model,
            entity_ref=entity_id,
            usd=usd,
            tokens_in=_tokens(usage.get("prompt_tokens", usage.get("input_tokens"))),
            tokens_out=_tokens(usage.get("completion_tokens", usage.get("output_tokens"))),
            cached=res.cached,
            outcome=outcome,
            detail=detail,
        )
        try:
            inserted = store.settle(Settlement(entry), **bound())
        except BudgetBusy:  # review 028d: never retried past the deadline; a reservation, if any, is left to expire
            log.warning("settlement of %s attempt %d: the budget lock was busy until the deadline", call_id, attempt)
            unsettled(attempt)
            return False
        if not inserted:  # a late settlement (already reconciled): exactly one debit stands
            log.warning("late settlement for %s attempt %d: already recorded", call_id, attempt)
        return inserted

    def finish(outcome: str, attempt: int = 0) -> Result:
        """A row from the Result itself (a call that made no attempt, or a cache hit)."""
        row(
            outcome,
            attempt,
            usd=res.usd,
            usd_source=res.usd_source,
            usage=res.usage,
            error_kind=res.error_kind,
            latency_ms=res.latency_ms,
        )
        return res

    def fail(kind: str, msg: str, outcome: str = "error") -> Result:
        res.error_kind, res.error = kind, msg
        return finish(outcome)

    if role not in icfg.ROLES or not isinstance(rcfg, Mapping):
        return fail("not_configured", f"unknown role {role!r}")
    if not rcfg.get("enabled", True):
        return fail("disabled", f"role {role} is disabled (config.json inference.roles.{role}.enabled)", "disabled")
    res.provider = str(rcfg.get("provider") or "")
    res.model = str(model or rcfg.get("model") or "")
    if not res.provider or not res.model:
        return fail("not_configured", f"role {role} has no provider/model configured")
    try:
        prov = resolve_provider(res.provider, cfg, providers)
    except ProviderError as e:
        return fail(e.kind, str(e))
    paid = bool(getattr(prov, "paid", True))
    price = icfg.price(cfg, res.model)
    if paid:
        missing = prov.ready(environ)
        if missing:
            return fail("not_configured", f"{res.provider}: {missing}")
        if price is None:
            return fail(
                "not_configured",
                f"no price for model {res.model!r} (add it to inference.prices) — paid calls must be accountable",
            )
    max_out = int(max_output_tokens or rcfg.get("max_output_tokens") or 1000)
    temperature = float(rcfg.get("temperature", 0.0))
    timeout = float(timeout_s or rcfg.get("timeout_s", 60))  # a long-reasoning call may ask for more time
    request: dict[str, Any] = {
        "provider": res.provider,
        "model": res.model,
        "messages": messages,
        "json_mode": json_mode,
        "max_out": max_out,
        "temperature": temperature,
    }
    role_extra = rcfg.get("extra_body") if isinstance(rcfg.get("extra_body"), Mapping) else {}
    assert isinstance(role_extra, Mapping)
    extra_req = {**role_extra, **(extra_body or {})}
    billing = sorted(k for k in extra_req if k in BILLING_OPTIONS)
    if billing:  # Codex H-271: admission prices exactly what is sent (``max_out``, one completion)
        return fail(
            "bad_request",
            f"extra_body option(s) {', '.join(billing)} change what the call can bill; use max_output_tokens "
            "(one completion per call)",
        )
    if extra_req:
        request["extra_body"] = extra_req
    key = _sha(request)
    base["request_sha"] = key
    caching = bool(use_cache and cfg.get("cache", True))

    def accept(text: str) -> bool:
        res.text = text
        if not json_mode:
            res.data = text
        else:
            data = extract_json(text)
            if data is None:
                res.error_kind, res.error = "malformed", "reply contained no parseable JSON"
                return False
            res.data = data
        if validate is not None:
            try:
                res.data = validate(res.data)
            except ValueError as e:
                res.error_kind, res.error = "invalid", str(e)[:500]
                return False
        res.ok = True
        return True

    if paid and not icfg.paid_enabled(environ):  # decision (c), and decision (d): before the cache
        return fail("disabled", f"paid inference is switched off ({icfg.PAID_ENV} is not 'on')", "disabled")

    if caching:
        try:
            hit = store.cache_get(key, **bound())  # Codex H-282: bounded by the same deadline
        except BudgetBusy:  # no time left to read the cache: nothing is sent
            return fail("deadline", "the response cache was busy until the deadline; nothing was sent")
        if hit is not None and isinstance(hit.text, str):
            res.cached = True
            if accept(hit.text):
                return finish("cache_hit")
            return finish("error")

    est = (
        budget.estimate_usd(price, len(json.dumps(messages, ensure_ascii=False)), max_out) if (paid and price) else 0.0
    )
    lim = budget.limits(cfg)
    max_retries, backoff = icfg.retries(cfg)
    reply: Reply | None = None
    t0 = time.monotonic()
    attempt = 0
    last_source = "none"

    def out_of_time(msg: str) -> Result:
        res.error_kind, res.error = "deadline", msg
        res.latency_ms = int((time.monotonic() - t0) * 1000) if attempt > 1 else 0
        res.usd, res.usd_source = round(charged, 8), last_source
        return res

    while True:
        attempt += 1
        if left() <= 0:
            return out_of_time(f"the deadline passed before attempt {attempt} could be admitted; nothing was sent")
        if paid:
            at = now()
            try:
                admission: Admission = store.admit(
                    AttemptRequest(
                        call_id=call_id,
                        attempt=attempt,
                        role=role,
                        purpose=purpose,
                        provider=res.provider,
                        model=res.model,
                        entity_id=entity_id,
                        run_id=run_id,
                        est_usd=est,
                        limits=lim,
                        run_cap_usd=run_cap_usd,
                        override_reason=override_reason,
                        now=at,
                        expires_at=at + timedelta(seconds=timeout + RESERVATION_MARGIN_S),
                        detail={k: base[k] for k in ("prompt_sha", "request_sha", "override_reason") if k in base},
                    ),
                    **bound(),
                )
            except BudgetBusy:
                return out_of_time(f"the budget was busy until the deadline; attempt {attempt} was not sent")
            if not admission.admitted:
                res.error_kind, res.error = "budget_blocked", admission.reason
                res.latency_ms = int((time.monotonic() - t0) * 1000) if attempt > 1 else 0
                res.usd, res.usd_source = round(charged, 8), last_source
                row(
                    "blocked",
                    attempt,
                    usd=0.0,
                    usd_source="none",
                    usage={},
                    error_kind="budget_blocked",
                    latency_ms=res.latency_ms,
                )
                return res
            if left() <= 0:  # plan revision 3: the admission may have waited; the deadline is checked again
                row("error", attempt, usd=0.0, usd_source="none", usage={}, error_kind="deadline", latency_ms=0)
                return out_of_time(f"the deadline passed while attempt {attempt} was admitted; it was not sent")
        res.attempts = attempt
        a0 = time.monotonic()
        try:
            reply = prov.complete(
                model=res.model,
                messages=messages,
                max_output_tokens=max_out,
                temperature=temperature,
                json_mode=json_mode,
                timeout_s=min(timeout, left()),
                extra_body=extra_req or None,
                env=environ,
            )
        except ProviderError as e:
            usd, source = budget.attempt_cost(paid=paid, est_usd=est, dispatched=e.dispatched)
            charged += usd
            last_source = source
            res.error_kind, res.error = e.kind, str(e)[:300]
            row(
                "error",
                attempt,
                usd=usd,
                usd_source=source,
                usage={},
                error_kind=e.kind,
                latency_ms=int((time.monotonic() - a0) * 1000),
            )
            if attempt in res.unsettled:  # review 028d: the deadline came while settling it
                return out_of_time(
                    f"attempt {attempt} failed ({e.kind}) and the budget was busy until the deadline; its reservation "
                    "stands until it is reconciled"
                )
            if not e.retryable or attempt > max_retries:
                break
            wait = backoff[min(attempt - 1, len(backoff) - 1)]
            if e.retry_after:  # the provider said how long: honour it (bounded)
                wait = min(max(wait, float(e.retry_after)), MAX_WAIT_S)
            elif "overloaded" in str(e).lower() or "busy" in str(e).lower():
                wait = min(wait * 2, MAX_WAIT_S)  # an overloaded engine needs a little longer than a blip
            if wait >= left():  # review 028d: the retry wait would end at or past the deadline
                return out_of_time(
                    f"attempt {attempt} failed ({e.kind}); the {wait:.0f}s retry wait would end past the deadline"
                )
            pause(wait)
            continue
        except Exception:  # a bug, not an expected failure: settle the attempt as possibly billed, then raise
            usd, source = budget.attempt_cost(paid=paid, est_usd=est, dispatched=True)
            row("error", attempt, usd=usd, usd_source=source, usage={}, error_kind="network", latency_ms=0)
            raise
        break
    res.latency_ms = int((time.monotonic() - t0) * 1000)
    if reply is None:
        res.usd, res.usd_source = round(charged, 8), last_source
        return res
    res.error_kind = res.error = ""
    res.usage = dict(reply.usage or {})
    usd, source = budget.reply_cost(
        paid=paid, price=price, est_usd=est, reported_usd=reply.reported_usd, usage=res.usage
    )
    res.usd = round(charged + usd, 8) if charged else usd
    res.usd_source = source
    res.tool_calls = list(reply.tool_calls or [])
    ok = accept(reply.text)
    row(
        "ok" if ok else "error",
        attempt,
        usd=usd,
        usd_source=source,
        usage=res.usage,
        error_kind=res.error_kind,
        latency_ms=int((time.monotonic() - a0) * 1000),
    )
    if ok and caching and not res.tool_calls and left() > 0:
        try:
            store.cache_put(
                CacheEntry(key=key, provider=res.provider, model=res.model, text=reply.text, stored_at=now()), **bound()
            )
        except BudgetBusy:  # Codex H-282: the answer and its debit stand; the reply is just not cached
            log.warning("cache write for %s skipped: the cache was busy until the deadline", call_id)
    return res


def status(
    store: BudgetStore,
    env: Mapping[str, str] | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
    config: Mapping[str, Any] | None = None,
    providers: Mapping[str, Provider] | None = None,
) -> dict[str, Any]:
    """Readiness per role (never a key value: only whether it is set) and the budget summary."""
    cfg = config if config is not None else icfg.load()
    environ: Mapping[str, str] = os.environ if env is None else env
    paid_on = icfg.paid_enabled(environ)
    roles: dict[str, Any] = {}
    for role in icfg.ROLES:
        r = (cfg.get("roles") or {}).get(role) or {}
        problem = ""
        if r.get("enabled", True) and r.get("provider"):
            try:
                p = resolve_provider(str(r["provider"]), cfg, providers)
                paid = bool(getattr(p, "paid", True))
                problem = p.ready(environ) if paid else ""
                if not problem and paid and icfg.price(cfg, str(r.get("model"))) is None:
                    problem = "no price table for the model"
                if not problem and paid and not paid_on:
                    problem = f"paid inference is switched off ({icfg.PAID_ENV} is not 'on')"
            except ProviderError as e:
                problem = str(e)
        roles[role] = {
            "enabled": bool(r.get("enabled", True)),
            "provider": r.get("provider"),
            "model": r.get("model"),
            "key_present": icfg.key_present(str(r.get("provider") or ""), environ, cfg),
            "ready": not problem and bool(r.get("enabled", True)),
            "problem": problem or None,
        }
    lim = budget.limits(cfg)
    t = store.totals((clock or berlin_now)())
    return {
        "roles": roles,
        "paid_enabled": paid_on,
        "budget": {
            "spend": {"day": t.day, "week": t.week, "month": t.month, "all_time": t.all_time},
            "limits": lim.as_dict(),
            "remaining": {
                "day": round(max(0.0, lim.daily_usd - t.day), 4),
                "week": round(max(0.0, lim.weekly_usd - t.week), 4),
                "month": round(max(0.0, lim.monthly_usd - t.month), 4),
            },
            "by_role": dict(t.by_role),
            "calls": dict(t.outcomes),
            "reservations": {"count": t.reservations, "usd": t.pending},
            "paid_switch": icfg.PAID_ENV,
        },
    }

"""Inference configuration (review 029a): providers, logical roles, the price table, the caps and the retries, cut
from the old ``inference/config.py`` (rev 6c739b9).

Kept as before: CHEAP and STANDARD on DeepInfra, ESCALATION disabled (decision h), the prices in USD per 1M tokens,
every cap (decision g) and the retry settings. Dropped: the RESEARCH role and the xAI provider (decision h; its price
row too), the ``config.json["inference"]`` override (there is no ``config.json`` in the rewrite; ``load(overrides)``
deep-merges an override for tests and tooling the same way), and the ``PZ_SCOUT00_PAID`` alias.

The paid switch is inverted (decision c): paid calls run only when ``PZ_AI_PAID`` is exactly ``on``; the old switch
was on unless set to off. ``key_present`` checks that a key is set, never what it is. Nothing here reads a key value.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

ROLES = ("CHEAP", "STANDARD", "ESCALATION")
PAID_ENV = "PZ_AI_PAID"
PAID_ON = "on"
# every provider key name the old app or this one ever read: the test guard (decision b) blanks all of them
KEY_ENVS = ("DEEPINFRA_API_KEY", "XAI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")

DEFAULTS: dict[str, Any] = {
    "providers": {
        "deepinfra": {
            "type": "openai_compatible",
            "base_url": "https://api.deepinfra.com/v1/openai",
            "key_env": "DEEPINFRA_API_KEY",
        },
        "fake": {"type": "fake"},  # the deterministic offline provider (never paid, never on the network)
    },
    "roles": {
        "CHEAP": {
            "enabled": True,
            "provider": "deepinfra",
            "model": "deepseek-ai/DeepSeek-V4-Flash",
            "max_output_tokens": 700,
            "temperature": 0.0,
            "timeout_s": 60,
        },
        "STANDARD": {
            "enabled": True,
            "provider": "deepinfra",
            "model": "deepseek-ai/DeepSeek-V4-Pro",
            "max_output_tokens": 3000,
            "temperature": 0.0,
            "timeout_s": 120,
        },
        # configurable, off (decision h: kept disabled, as before)
        "ESCALATION": {"enabled": False, "provider": "", "model": "", "max_output_tokens": 6000, "timeout_s": 180},
    },
    "prices": {
        "deepseek-ai/DeepSeek-V4-Flash": {"input": 0.09, "cached_input": 0.018, "output": 0.18},
        "deepseek-ai/DeepSeek-V4-Pro": {"input": 1.30, "cached_input": 0.10, "output": 2.60},
        "Qwen/Qwen3.5-397B-A17B": {"input": 0.45, "cached_input": 0.22, "output": 3.00},
        "Qwen/Qwen3.5-9B": {"input": 0.10, "output": 0.15},
        "openai/gpt-oss-120b": {"input": 0.05, "output": 0.25},
        "zai-org/GLM-4.7": {"input": 0.40, "cached_input": 0.08, "output": 1.75},
        "zai-org/GLM-5.3": {"input": 0.90, "cached_input": 0.20, "output": 4.00},
        "moonshotai/Kimi-K3": {"input": 2.85, "cached_input": 0.285, "output": 14.25},
        "deepseek-ai/DeepSeek-V4.1-Flash-1017": {"input": 0.20, "cached_input": 0.006, "output": 0.60},
    },
    "budget": {
        "max_call_usd": 0.05,  # worst-case estimate of a single call
        "entity_cap_usd": 1.00,  # cumulative per company / candidate, all time
        "daily_usd": 1.00,
        "weekly_usd": 5.00,
        "monthly_usd": 25.00,
        "role_monthly_usd": {"CHEAP": 3.00},
        # ONLY these purposes may cost more (or must cost less) than the general per-call cap
        "purpose_max_call_usd": {
            "ic_chair": 0.20,
            "ic_outside": 0.40,
            "triage_second_pass": 0.02,
            "native_scout": 0.06,
            "native_planner": 0.01,
            "associate": 0.05,  # review 033a: the PZ Associate, at the default per-call cap
        },
    },
    "retries": {"max_retries": 2, "backoff_s": [2.0, 6.0]},
    "cache": True,
}


def _merge(base: dict[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, Mapping) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load(overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The effective configuration: ``DEFAULTS``, deep-merged with ``overrides`` when given (the old
    ``config.json["inference"]`` merge rule: a nested dict merges key by key, anything else replaces)."""
    return _merge(DEFAULTS, overrides) if isinstance(overrides, Mapping) else copy.deepcopy(DEFAULTS)


def paid_enabled(env: Mapping[str, str]) -> bool:
    """Decision (c): True ONLY when ``PZ_AI_PAID`` is exactly ``on``. Unset, empty, ``true``, ``1`` or ``ON``: off."""
    return env.get(PAID_ENV) == PAID_ON


def key_env(provider: str, cfg: Mapping[str, Any] | None = None) -> str:
    """The NAME of the environment variable that holds ``provider``'s key ('' when it needs none)."""
    p = ((cfg if cfg is not None else DEFAULTS).get("providers") or {}).get(provider)
    return str(p.get("key_env") or "") if isinstance(p, Mapping) else ""


def key_present(provider: str, env: Mapping[str, str], cfg: Mapping[str, Any] | None = None) -> bool:
    """Whether ``provider``'s key is set (non-blank) in ``env``. Presence only: the value is never returned, compared
    or logged. A provider without a key variable (the fake) needs none."""
    p = ((cfg if cfg is not None else DEFAULTS).get("providers") or {}).get(provider)
    if not isinstance(p, Mapping):
        return False
    name = str(p.get("key_env") or "")
    if not name:
        return p.get("type") == "fake"
    return bool(str(env.get(name) or "").strip())


def price(cfg: Mapping[str, Any], model: str) -> dict[str, float] | None:
    """The old ``price``: input / output / cached_input (defaulting to input) per 1M tokens, None when unknown."""
    p = (cfg.get("prices") or {}).get(model)
    if not isinstance(p, Mapping):
        return None
    try:
        return {
            "input": float(p["input"]),
            "output": float(p["output"]),
            "cached_input": float(p.get("cached_input", p["input"])),
        }
    except (KeyError, TypeError, ValueError):
        return None


def retries(cfg: Mapping[str, Any]) -> tuple[int, list[float]]:
    """The old retry settings: ``max_retries`` clamped to 0..5 (so at most 6 attempts; 2 by default, 3 attempts) and
    the backoff list (``[2.0]`` when empty)."""
    r = cfg.get("retries") if isinstance(cfg.get("retries"), Mapping) else {}
    assert isinstance(r, Mapping)
    max_retries = max(0, min(int(r.get("max_retries", 2)), 5))
    backoff = [float(x) for x in (r.get("backoff_s") or [2.0, 6.0])] or [2.0]
    return max_retries, backoff

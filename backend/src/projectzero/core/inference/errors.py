"""Provider failures in plain language (the old ``inference/errors.py``, rev 6c739b9, line for line): the one place
that turns gateway error kinds and raw provider bodies into what Mohamed reads. Technical detail stays in the ledger
(sanitised, never the API key).

Categories:
  RETRYABLE      overloaded / rate limited / timeout / server error / network: work is preserved and retried
  CONFIGURATION  key missing, provider not configured, auth / billing refused: needs a setting, not a retry
  BUDGET         a configured AI cap or the paid switch stopped paid calls: preserved, resumes when allowed
  NON_RETRYABLE  the request itself was refused / the reply unusable: the item needs a look
"""

from __future__ import annotations

import json
import re
from typing import Any

RETRYABLE = frozenset({"rate_limited", "timeout", "server", "network"})
CONFIGURATION = frozenset({"not_configured", "auth", "billing"})
BUDGET = frozenset({"budget_blocked", "disabled"})
_OVERLOAD = re.compile(r"engine_overloaded|model busy|overloaded|capacity", re.I)


def compact(raw: Any) -> str:
    """'HTTP 429: {"error":{"message":"Model busy, retry later",...,"code":"engine_overloaded"}}'
    -> 'HTTP 429 engine_overloaded: Model busy, retry later' (short, no JSON, no headers, no key)."""
    s = str(raw or "").strip()
    m = re.match(r"^(HTTP \d{3}):?\s*(\{.*)$", s, re.S)
    if not m:
        return s[:200]
    head, body = m.group(1), m.group(2)
    try:
        err = json.loads(body).get("error")
        if isinstance(err, dict):
            code = err.get("code") or err.get("type") or ""
            return f"{head} {code}: {err.get('message') or ''}".strip()[:200]
        if isinstance(err, str):
            return f"{head}: {err}"[:200]
    except (ValueError, AttributeError):
        pass
    msg = re.search(r'"message"\s*:\s*"([^"]{1,160})', body)
    code = re.search(r'"code"\s*:\s*"([^"]{1,60})', body)
    return f"{head} {code.group(1) if code else ''}: {msg.group(1) if msg else 'provider error'}".replace("  ", " ")[
        :200
    ]


def category(kind: str | None, raw: Any = "") -> str:
    k = (kind or "").strip()
    if k in RETRYABLE or _OVERLOAD.search(str(raw or "")):
        return "RETRYABLE"
    if k in CONFIGURATION:
        return "CONFIGURATION"
    if k in BUDGET:
        return "BUDGET"
    return "NON_RETRYABLE"


def explain(kind: str | None, raw: Any = "", provider: str = "DeepInfra") -> str:
    """One plain sentence about WHAT happened (the caller adds what happens next)."""
    k = (kind or "").strip()
    text = str(raw or "")
    if _OVERLOAD.search(text):
        return f"{provider} was temporarily overloaded"
    return {
        "rate_limited": f"{provider} temporarily rate-limited Project Zero",
        "timeout": f"{provider} did not respond in time",
        "server": f"{provider} had a temporary server error",
        "network": f"{provider} could not be reached (network)",
        "not_configured": f"{provider} is not configured (API key or price missing)",
        "auth": f"{provider} refused the API key",
        "billing": f"{provider} refused the request for billing reasons",
        "budget_blocked": "the configured AI budget limit was reached",
        "disabled": "paid AI is switched off (kill switch)",
        "malformed": f"{provider} sent a reply that could not be read",
        "invalid": f"{provider}'s reply did not pass Project Zero's checks",
        "bad_request": f"{provider} refused the request",
    }.get(k, f"{provider} call failed")

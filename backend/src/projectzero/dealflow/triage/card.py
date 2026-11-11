"""The candidate card the triage models saw, and the locked v3 architecture (protected; old
``services/shadow_triage.py``: ``candidate_card``, ``_sha``, ``PROMPT_VERSION``, ``LOCKED_V3``; and the
``taste.DISCOVERY_TIERS`` labels the card prints), verbatim.

A proposal is stale when the card it was made from no longer matches today's card (``input_sha``), or when it was made
under another prompt version.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

PROMPT_VERSION = "triage-v3"
VETO_MODEL = "Qwen/Qwen3.5-397B-A17B"
CHEAP_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
# Locked candidate architecture for holdout validation (Mohamed, 2026-10-09).
LOCKED_V3: dict[str, Any] = {
    "prompt_version": "triage-v3",
    "cheap_model": CHEAP_MODEL,
    "veto_model": VETO_MODEL,
    "veto_thinking": False,
}
# old ``taste.DISCOVERY_TIERS``
DISCOVERY_TIERS = {
    "pre_company": "Pre-company channel (DIANA/EUDIS, TUM/UnternehmerTUM, transfer office, grant winner, "
    "stealth/talent exit) — THE EDGE",
    "announcement": "Announcement feed — discovery only, usually recently funded",
    "register": "Company register",
    "manual": "Manual / relationship",
}


def candidate_card(c: Mapping[str, Any]) -> str:
    """The candidate as the model sees it: only fields Project Zero already holds, truncated, no internal scores."""
    also = [str(x.get("source") or "") for x in (c.get("also_seen") or []) if isinstance(x, dict)]
    tier = DISCOVERY_TIERS.get(str(c.get("discovery_tier")), c.get("discovery_tier") or "")
    lines = [
        f"name: {c.get('name') or ''}",
        f"description: {str(c.get('description') or '')[:1200]}",
        f"found via: {c.get('source') or ''} ({tier})",
        f"source url: {c.get('source_url') or ''}",
        f"date: {c.get('source_date') or c.get('date') or ''} ({c.get('date_kind') or 'detected'})",
        f"location: {c.get('location') or ''} {c.get('country') or ''} geo={','.join(c.get('geo') or [])}".strip(),
        f"sectors: {', '.join(c.get('sectors') or c.get('source_sectors') or [])}",
    ]
    if also:
        lines.append(f"also seen at: {'; '.join(also[:5])}")
    return "\n".join(lines)


def sha(text: str) -> str:
    """Old ``shadow_triage._sha``."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def card_sha(c: Mapping[str, Any]) -> str:
    """The ``input_sha`` a proposal made today, from this card, would carry."""
    return sha(PROMPT_VERSION + "\n" + candidate_card(c))


def is_stale(c: Mapping[str, Any], p: Mapping[str, Any]) -> bool:
    """The candidate text changed after the proposal was made (the machine judged different evidence)."""
    if p.get("prompt_version") != PROMPT_VERSION:
        return True
    return p.get("input_sha") != card_sha(c)

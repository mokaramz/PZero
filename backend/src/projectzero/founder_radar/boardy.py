"""The old ``domain/founder_radar/boardy.py`` (rev 6c739b9), ported line for line (review 026a): the operator-controlled
Boardy introduction brief (no API call ever happens). Only change: the clock (``now`` for the "prepared" stamp,
``today`` for the assessment when no signal is stored)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from projectzero.founder_radar.scoring import assess


def boardy_brief(
    p: dict[str, Any],
    desired: Any = "a 20-minute intro call",
    exclusions: Any = "no fundraising pitch, no data sharing beyond public evidence",
    *,
    now: datetime,
    today: date,
) -> str:
    """Operator-controlled brief. No API call happens; the operator pastes it into Boardy."""
    a = p.get("signal") or assess(p, today=today)
    lines = [
        "BOARDY INTRODUCTION REQUEST (draft — not sent automatically)",
        "Who I want to meet: {}{}{}".format(
            p.get("name"), " · " + p["role"] if p.get("role") else "", " · " + p["company"] if p.get("company") else ""
        ),
        "Why this person matters: " + (p.get("why_surfaced") or p.get("why_interesting") or "see evidence"),
        "Verified evidence: "
        + (
            "; ".join(x["claim"] for x in (p.get("evidence") or [])[:3])
            or "none yet — identity " + p.get("identity_status", "")
        ),
        "Geography / thesis: {}{} · Project A (pre-seed/seed, Europe-first) — themes: {}".format(
            p.get("location") or "UNKNOWN",
            " " + p["country"] if p.get("country") else "",
            ", ".join(a["factors"].get("project_a") or ["not evidenced"]),
        ),
        "Desired outcome: " + desired,
        "Why useful for both sides: Mohamed brings Project A's network, portfolio insight and honest early feedback; asks only for a conversation.",  # noqa: E501
        "Explicit exclusions: " + exclusions,
        "Status: prepared {} · not sent (no Boardy API)".format(now.strftime("%Y-%m-%d %H:%M")),
    ]
    return "\n".join(lines)

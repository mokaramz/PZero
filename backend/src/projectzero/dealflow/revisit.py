"""Revisit flags (decision 0004, review 018): when a re-report onto a REJECTED company carries a material change
since the rejection, intake flags the candidate for revisit. The flag is one ``candidate_events`` row
(``revisit_flagged``): never a status change, never an interrupt, and only Mohamed reopens a candidate.

``evaluate`` is the whole rule, pure (approved by Codex H-127):

* only a ``rejected`` candidate is eligible (``archived`` keeps today's quiet absorption);
* the rejection must have a recorded date (``decided_at``): an imported rejection without one is not flagged
  (``unknown_rejection_date``), so a historical change is never surfaced as new;
* the change date is ``since``, else the entity's ``signal_date`` (``undated`` without either); it must fall on a
  STRICTLY later Europe/Berlin calendar day than the rejection (``before_rejection`` otherwise);
* ``independent_corroboration`` needs two independent sources FOR THE SAME CHANGE (Codex H-129 / H-131): besides this
  report's ``evidence_url``, a source on a different host that reports the change, either
  - one of this report's own ``supporting_urls`` (the producer names it as reporting THIS change), or
  - an earlier report of a material change since the rejection, from another delivery, whose ``evidence_url`` THIS
    report cites among its evidence.
  General company evidence and unrelated reports never count: without such a source the report is kept but not
  flagged (``single_source``). The flag keeps every supporting reference (``corroboration``);
* the same change (kind + evidence URL) is flagged once per rejection (``already_flagged``); a reopen and a new
  rejection start over, because only flags newer than the latest decision count.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
ACTION = "revisit_flagged"


def host(url: Any) -> str:
    """The source a URL is attributable to: its host, lower-case, without ``www.``."""
    try:
        h = (urlsplit(str(url or "")).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


def change_date(entity: Mapping[str, Any]) -> tuple[date | None, str]:
    """(the day the change happened, where that came from: since | signal_date | "")."""
    change = entity.get("material_change") or {}
    for value, source in ((change.get("since"), "since"), (entity.get("signal_date"), "signal_date")):
        if isinstance(value, str):
            try:
                return date.fromisoformat(value), source
            except ValueError:
                continue
    return None, ""


@dataclass(frozen=True)
class Outcome:
    flag: dict[str, Any] | None  # the event detail when flagged
    reason: str  # "flagged" or why not


def evaluate(
    entity: Mapping[str, Any],
    *,
    status: str,
    decided_at: datetime | None,
    earlier_changes: Iterable[Mapping[str, Any]],
    earlier_flags: Iterable[Mapping[str, Any]],
    submission_id: Any,
) -> Outcome:
    """Whether this re-report flags the candidate. ``earlier_changes``: the material changes reported onto the
    candidate by OTHER deliveries since ``decided_at`` (the current rejection), each ``{evidence_url, submission_id}``;
    ``earlier_flags``: its revisit flags since then."""
    change = entity.get("material_change")
    if not isinstance(change, Mapping):
        return Outcome(None, "no_change")
    if status != "rejected":
        return Outcome(None, "not_rejected")
    if decided_at is None:
        return Outcome(None, "unknown_rejection_date")
    day, source = change_date(entity)
    if day is None:
        return Outcome(None, "undated")
    rejected_on = decided_at.astimezone(BERLIN).date()
    if day <= rejected_on:
        return Outcome(None, "before_rejection")
    evidence = [dict(e) for e in entity.get("evidence") or [] if isinstance(e, Mapping)]
    corroboration: list[dict[str, Any]] = []
    if change.get("kind") == "independent_corroboration":
        corroboration = _corroboration(change, evidence, earlier_changes, submission_id)
        if not corroboration:
            return Outcome(None, "single_source")
    if any(f.get("kind") == change.get("kind") and f.get("evidence_url") == change.get("evidence_url")
           for f in earlier_flags):  # fmt: skip
        return Outcome(None, "already_flagged")
    return Outcome(
        {
            "kind": change.get("kind"),
            "since": day.isoformat(),
            "date_source": source,
            "rejected_on": rejected_on.isoformat(),
            "evidence_url": change.get("evidence_url"),
            "evidence": evidence,
            "note": change.get("note"),
            "submission_id": submission_id,
        }
        | ({"corroboration": corroboration} if corroboration else {}),
        "flagged",
    )


def _corroboration(
    change: Mapping[str, Any],
    evidence: list[dict[str, Any]],
    earlier_changes: Iterable[Mapping[str, Any]],
    submission_id: Any,
) -> list[dict[str, Any]]:
    """Every reference supporting THIS change from a source other than its own ``evidence_url``: earlier reports of the
    change this report cites (earliest first), then its own ``supporting_urls``, then the ``evidence_url`` last; []
    when there is none."""
    own = host(change.get("evidence_url"))
    cited = {e.get("url") for e in evidence}
    support: dict[str, dict[str, Any]] = {}
    for earlier in earlier_changes:
        url = earlier.get("evidence_url")
        if isinstance(url, str) and url in cited and host(url) not in ("", own) and url not in support:
            support[url] = {"evidence_url": url, "submission_id": earlier.get("submission_id")}
    for url in change.get("supporting_urls") or []:
        if isinstance(url, str) and url in cited and host(url) not in ("", own) and url not in support:
            support[url] = {"evidence_url": url, "submission_id": submission_id}
    if not own or not support:
        return []
    return [*support.values(), {"evidence_url": change.get("evidence_url"), "submission_id": submission_id}]

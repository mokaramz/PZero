"""The pure half of the Conviction writes — the old ``services/pipeline.py`` save / status rules (review 011).

* ``validate_entry`` (old :218): refused BEFORE anything is written — scores 0..25/20/15/15/10, yes/no flags, no future
  signal date, the status and conflict enums, archetype 0..15, founders a list.
* ``apply_save`` (old ``save_entry`` :262, minus storage): SAVE_FIELDS copied from the body, founders cleaned, the
  originating Deal Flow candidate's provenance on a NEW entry.
* ``apply_status`` (old ``set_status`` :334): the status, plus the old outreach event on the FIRST contacted / replied.

The clock is a parameter. Nothing here touches the database (``conviction.store`` does).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from projectzero.conviction.records import clean_founders
from projectzero.dealflow.ranking import feedback

STATUSES = ["new", "contacted", "replied", "forwarded", "dropped"]
SAVE_FIELDS = ("company", "one_liner", "location", "country", "website", "discovery_source", "discovery_tier",
               "discovery_date", "archetype", "emerging", "founders", "scores", "earliness", "funding_status",
               "fundraising_timing", "penalties", "twin", "conflict", "verified", "why_found", "why_project_a",
               "why_now_text", "founder_signal", "venture_scale_text", "bull", "bear", "verify_list", "next_action",
               "sources", "status", "sent_to_omar", "omar_feedback")  # fmt: skip
SCORE_CAPS = {"founder": 25, "venture_scale": 20, "why_now": 15, "taste": 15, "insight": 10}  # the frozen maxima
CONFLICTS = ("none", "similar", "complementary", "clone", "potential_conflict", "unclear")
OUTREACH_BY = "Mohamed (recorded by hand — Project Zero never sends anything)"


def validate_entry(body: Mapping[str, Any], today: date) -> list[str]:
    """Reasons a Conviction write must be refused (checked BEFORE anything is written — never a partial record)."""
    bad: list[str] = []
    if "company" in body and not str(body.get("company") or "").strip():
        bad.append("company name is empty")
    sc = body.get("scores")
    if sc is not None:
        if not isinstance(sc, dict):
            bad.append("scores must be a set of numbers")
        else:
            for k, v in sc.items():
                try:
                    n = int(v)
                except (TypeError, ValueError):
                    bad.append(f"score '{k}' is not a number")
                    continue
                if n < 0 or (k in SCORE_CAPS and n > SCORE_CAPS[k]):
                    bad.append(f"score '{k}' = {n} is outside 0–{SCORE_CAPS.get(k, '…')}")
    ver = body.get("verified")
    if ver is not None and (not isinstance(ver, dict) or any(not isinstance(v, bool) for v in ver.values())):
        bad.append("verified flags must be yes / no")
    dd = str(body.get("discovery_date") or "").strip()
    if dd:
        try:
            if datetime.strptime(dd[:10], "%Y-%m-%d").date() > today:
                bad.append(f"signal date {dd[:10]} is in the future")
        except ValueError:
            bad.append(f"signal date '{dd[:20]}' is not a date (YYYY-MM-DD)")
    if "status" in body and body["status"] not in STATUSES:
        bad.append(f"status '{body['status']}' is not one of {', '.join(STATUSES)}")
    if body.get("conflict") not in (None, "") and body["conflict"] not in CONFLICTS:
        bad.append(f"conflict '{body['conflict']}' is not a known value")
    arch = body.get("archetype")
    if arch not in (None, ""):
        try:
            if not 0 <= int(arch) <= 15:
                bad.append(f"archetype {arch} does not exist")
        except (TypeError, ValueError):
            bad.append("archetype must be a number")
    if "founders" in body and body["founders"] is not None and not isinstance(body["founders"], (list, str, dict)):
        bad.append("founders must be a list of names")
    return bad


def refusal(problems: list[str]) -> str:
    return "Not saved — " + "; ".join(problems) + ". Nothing was changed."


def provenance(entry: dict[str, Any], cx: Mapping[str, Any], candidate_id: str) -> None:
    """A NEW entry records the Deal Flow candidate it came from (old save_entry, "provenance is best-effort").
    ``cx`` is the candidate's ranking input (the old inbox record); ``candidate_id`` its current id."""
    entry["source_id"] = cx.get("quality_source_id") or cx.get("source_id", "")
    entry["inbox_id"] = candidate_id  # originating candidate
    entry["source_ids"] = feedback.source_ids_of(cx)  # every credited source (merged provenance)
    if cx.get("run_id"):  # provenance of a scanned discovery (never on bundled seeds)
        entry["discovered_run"] = cx.get("first_seen_run") or cx.get("run_id")
        entry["discovered_first_seen"] = cx.get("first_seen") or cx.get("detected_on") or ""
        entry["discovered_source_url"] = cx.get("source_url", "")


def apply_save(entry: dict[str, Any], body: Mapping[str, Any]) -> None:
    """The body's SAVE_FIELDS onto the record (founders cleaned first), exactly as the old save did."""
    values = dict(body)
    if "founders" in values:
        values["founders"] = clean_founders(values.get("founders"))
    for k in SAVE_FIELDS:
        if k in values:
            entry[k] = values[k]


def outreach_event(kind: str, when: str, channel: str, note: str, now: datetime) -> dict[str, Any]:
    return {
        "kind": kind,
        "date": when,
        "channel": channel,
        "note": note[:300],
        "by": OUTREACH_BY,
        "recorded": now.isoformat(timespec="seconds"),
    }


def apply_status(entry: dict[str, Any], status: str, now: datetime) -> None:
    """Mohamed's own status change; the first contacted / replied dates the contact (nothing was sent by PZ)."""
    prev, entry["status"] = entry.get("status"), status
    kind = {"contacted": "outreach_sent", "replied": "reply_received"}.get(status)
    log: list[Any] = entry["outreach"] if isinstance(entry.get("outreach"), list) else []
    if kind and prev != status and not any(isinstance(x, dict) and x.get("kind") == kind for x in log):
        entry["outreach"] = [*log, outreach_event(kind, now.strftime("%Y-%m-%d"), "other",
                                                  f"status set to {status} in Conviction", now)]  # fmt: skip


def changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The top-level fields a write changed: (before, after); a field that did not exist reads as None before."""
    keys = [k for k in after if k not in before or before[k] != after[k]]
    keys += [k for k in before if k not in after]
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}

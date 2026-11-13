# ruff: noqa
# mypy: ignore-errors
# (protected auto-triage rules, copied by script from the old module; see the header. The cut code is the old untyped
# code verbatim, so it is exempt from lint and type checks, like a vendored module.)
"""The automatic machine triage's pure rules (review 035b), cut MECHANICALLY from the old ``services/auto_triage.py``
(rev 6c739b9) by exact top-level line ranges (``scripts/gen_triage_cascade.py``); nothing is retyped: the retry
backoff and its bound, the run cap, the kept-runs count, the stop-kind fallback, one retry item (``_retry_item``), the
earliest next try, the summary sentence and ``plain`` (a run record as the UI shows it).

The one declared replacement (decision c): ``perrors.explain(`` -> ``_explain(``, the hand-written seam below that
names the NEW paid switch (``PZ_AI_PAID``) where the old text named the old kill switch.
"""

# fmt: off
from datetime import datetime, timedelta
from typing import Any

from projectzero.core.inference import errors as perrors

PAID_OFF_OLD = "(kill switch)"
PAID_OFF_NEW = "(PZ_AI_PAID is not 'on')"


# ── hand-written seam (NOT cut): the plain sentence, with the new paid switch's name (decision c) ─────────────────
def _explain(kind, raw="", provider="DeepInfra"):
    return perrors.explain(kind, raw, provider).replace(PAID_OFF_OLD, PAID_OFF_NEW)


# ── cut from services/auto_triage.py ──
RETRY_BACKOFF_MIN = (15, 60, 240, 720, 1440)  # a provider outage is retried politely, never hammered

MAX_AUTO_RETRIES = len(RETRY_BACKOFF_MIN)  # then the candidate waits for Mohamed's "Retry now" (never dropped)

AUTO_RUN_CAP_USD = 0.50  # per automatic run (one scan); the gateway's day/week/month caps still apply on top

KEEP_RUNS = 30

def _stop_kind(stopped: str | None) -> str:
    s = (stopped or "").lower()
    for k in (
        "budget_blocked",
        "not_configured",
        "disabled",
        "auth",
        "billing",
        "rate_limited",
        "timeout",
        "server",
        "network",
    ):
        if k in s:
            return k
    if "budget" in s or "cap" in s:
        return "budget_blocked"
    return "server"

def _retry_item(
    rs: dict[str, Any], cid: str, name: str | None, kind: str | None, raw: Any, now: datetime, count: bool = True
) -> dict[str, Any]:
    """Record one unfinished candidate in the retry state and describe it in plain words (never the raw payload)."""
    cat = perrors.category(kind, raw)
    r = rs.setdefault(cid, {"attempts": 0, "first_failed": now.isoformat(timespec="seconds")})
    if count:
        r["attempts"] = int(r.get("attempts", 0)) + 1
    r.update(kind=kind, category=cat, reason=_explain(kind, raw), last_failed=now.isoformat(timespec="seconds"))
    if cat == "NON_RETRYABLE" or r["attempts"] > MAX_AUTO_RETRIES:
        r["next_eligible"] = None
        retry = "manual"
        tail = (
            "automatic retries used up" if cat != "NON_RETRYABLE" else "this needs a look"
        ) + " — use “Retry now” in Deal Flow; the candidate is kept"
    elif cat in ("CONFIGURATION", "BUDGET"):
        r["next_eligible"] = (now + timedelta(minutes=RETRY_BACKOFF_MIN[0])).isoformat(timespec="seconds")
        retry = "after the setting / budget allows"
        tail = "kept — it runs again once that is resolved (no action needed for the budget; a missing key needs a setting)"
    else:
        wait = RETRY_BACKOFF_MIN[min(max(r["attempts"], 1) - 1, len(RETRY_BACKOFF_MIN) - 1)]
        r["next_eligible"] = (now + timedelta(minutes=wait)).isoformat(timespec="seconds")
        retry = "automatic"
        tail = f"kept for an automatic retry after {r['next_eligible'][11:16]}"
    return {
        "id": cid,
        "name": name,
        "reason": f"{r['reason']} — {tail}",
        "category": cat,
        "retry": retry,
        "next_try": r.get("next_eligible"),
        "attempts": r["attempts"],
    }

def rs_next(items: list[dict[str, Any]]) -> str | None:
    return min((i["next_try"] for i in items if i.get("next_try")), default=None)

def summary(rec: dict[str, Any]) -> str:
    """The one sentence every screen shows for an automatic triage run (no codes, no payloads)."""
    if rec.get("state") == "running":
        return f"Machine triage running — {rec.get('selected', 0)} candidate(s)"
    if not rec.get("selected"):
        return "Machine triage complete — no new or changed candidates, nothing to do."
    counts = rec.get("counts") or {}
    done = sum(counts.values())
    parts = [f"{done} processed" + (f" ({' · '.join(f'{v} {k}' for k, v in counts.items())})" if counts else "")]
    if rec.get("unchanged_skipped"):
        parts.append(f"{rec['unchanged_skipped']} unchanged (current proposal kept)")
    pend, fail = rec.get("pending") or [], rec.get("failed") or []
    if pend:
        why = pend[0]["reason"].split(" — ")[0]
        nxt = rs_next(pend)
        parts.append(
            f"{len(pend)} preserved for automatic retry because {why}"
            + (f" (next try after {nxt[11:16]})" if nxt else "")
        )
    if fail:
        parts.append(f"{len(fail)} need a manual retry (“Retry now”) — {fail[0]['reason'].split(' — ')[0]}")
    head = {
        "done": "Machine triage complete",
        "partial": "Machine triage partially complete",
        "failed": "Machine triage could not run",
    }.get(rec.get("state") or "", "Machine triage")
    money = f" · ${float(rec.get('usd') or 0):.4f}" if rec.get("usd") else ""
    tail = " No data was lost; these are proposals only." if pend or fail else ""
    return f"{head} — " + "; ".join(parts) + money + "." + tail

def plain(rec: dict[str, Any] | None) -> dict[str, Any] | None:
    """A run record as the UI may show it: plain reasons and a summary even for runs recorded before this release
    (derived at read time — the stored record is not rewritten)."""
    if not rec:
        return rec
    out = dict(rec)
    for key in ("pending", "failed"):
        items = []
        for it in rec.get(key) or []:
            reason = str(it.get("reason") or "")
            if "HTTP" in reason or "{" in reason or ":" in reason.split(" — ")[0][:40]:
                kind = reason.split(":", 1)[0].strip() if ":" in reason else ""
                reason = (
                    f"{_explain(kind, reason)} — kept for an automatic retry"
                    if perrors.category(kind, reason) == "RETRYABLE"
                    else f"{_explain(kind, reason)} — kept; use “Retry now” in Deal Flow"
                )
            items.append({**it, "reason": reason})
        out[key] = items
    if rec.get("state") != "running":
        legacy_failed = [i for i in out["failed"] if "automatic retry" in i["reason"]]
        if legacy_failed and not rec.get("summary"):  # old records: retryable failures are really "pending"
            out["pending"] = (out.get("pending") or []) + legacy_failed
            out["failed"] = [i for i in out["failed"] if i not in legacy_failed]
        out["summary"] = rec.get("summary") or summary(out)
    return out

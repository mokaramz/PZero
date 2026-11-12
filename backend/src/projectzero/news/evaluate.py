"""The source evaluation (review 028c): the old ``news_sources.evaluate`` (``services/news_sources.py`` 1012-1153 at
revision 6c739b9) as a PURE function over ONE ``NewsInputs``, returning every write instead of making it.

Only mechanical changes: every store read is a field of the inputs; the clock is ``today`` (the Berlin day) and
``now`` (``ts(now)``: the old naive ``ledger.now_ts()`` Berlin wall time); ``_deal_flow_alpha`` reads the inputs'
``source_alpha`` (computed by the caller from the Validation entities over the CURRENT events, 028a decision b).

Decision (d): the nominations into the source network (old ``source_network.nominate``, not ported) are DEFERRED: for
each ready missing publication, where the old code nominated, one ``source_log`` line ``{at, event:
"nomination_deferred", source, domain, url, family, events, why, reason: NOMINATION_REASON}`` (sorted keys) is
written instead; nothing is nominated, so ``nominated`` is ``[]``, the old ``nominated`` line is never written and the
``evaluated`` line counts 0.

What it reads (the caller re-reads them FRESH under the News write lock): ``events`` (the stored document, its key
order), ``runs_log`` (the technical rows), ``outcomes_log`` (the live outcomes), ``source_alpha`` / ``sources`` (the
Deal Flow row), ``feeds_extra`` (the monitored universe), ``disagreements_log`` (first observations),
``source_state`` and ``source_history_log``. ``source_metrics`` and ``source_log`` are only written.

The writes, in the old order (``EvalOutcome.appends``): the new ``disagreements`` lines, the ``source_log`` lines of
the lifecycle changes, the deferred nominations, the ``source_history`` line when due, the ``evaluated`` line; the
documents ``news/source_state.json`` (always saved by the old code, changed or not) and
``news/source_metrics.json``. Every line is the old ``json.dumps(..., ensure_ascii=False, sort_keys=True)`` without
its line end.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from projectzero.news.catalog import DEFAULT_WINDOW, SNAPSHOT, STATE, WINDOWS
from projectzero.news.core import load
from projectzero.news.inputs_model import NewsInputs
from projectzero.news.sources import _d, _deal_flow_alpha, _rows, compute, disagreements, missing_publications
from projectzero.validation.core import ts

NOMINATION_REASON = "the source network arrives with its port"  # decision (d)


@dataclass(frozen=True)
class EvalOutcome:
    """Everything one evaluation writes (nothing is written here)."""

    result: dict[
        str, Any
    ]  # the old return value ``{at, benchmark_events, new_disagreements, lifecycle_changes, nominated}``
    source_state: dict[str, Any]  # the new ``news/source_state.json``
    source_metrics: dict[str, Any]  # the new ``news/source_metrics.json`` ``{at, today, windows}``
    appends: tuple[
        tuple[str, str], ...
    ]  # ``(log, line)`` in the old order; log: disagreements | source_log | source_history
    deferred_nominations: tuple[dict[str, Any], ...] = field(default_factory=tuple)  # the would-be nominations

    def lines(self, log: str) -> list[str]:
        return [line for name, line in self.appends if name == log]

    @property
    def documents(self) -> dict[str, Any]:
        """The two documents, in the old save order."""
        return {STATE: self.source_state, SNAPSHOT: self.source_metrics}


def _dump(row: Any) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True)


def degradation(cur: dict[str, Any], prev: dict[str, Any] | None) -> list[str]:
    """Reasons a monitored source should be DEGRADED now (empty = healthy). Sample-aware; never deletes anything."""
    why = []
    t = cur["technical"]
    if (t.get("streak") or 0) >= 3:
        why.append(f"feed failed {t['streak']} runs in a row ({t.get('last_error') or 'no detail'})")
    elif t.get("state") == "BLOCKED":
        why.append(f"access blocked (login / paywall): {t.get('last_error')}")
    a = cur["articles"]
    if a["n"] >= 30 and (a["noise"]["rate"] or 0) >= 0.8:
        why.append(f"severe noise: {a['noise']['k']}/{a['n']} articles off-scope or noise")
    o = cur["originality"]
    if o["n"] >= 20 and (o["syndicated"]["rate"] or 0) >= 0.8:
        why.append(f"syndicated copies dominate ({o['syndicated']['k']}/{o['n']})")
    if prev:
        pa, ca = prev["articles"]["precision"], a["precision"]
        if pa["n"] >= 20 and ca["n"] >= 20 and (pa["rate"] or 0) >= 0.2 and (ca["rate"] or 0) < 0.5 * pa["rate"]:
            why.append(f"editorial drift: relevance fell from {pa['rate']:.0%} to {ca['rate']:.0%} of articles")
        pu, cu = prev["unique"]["of_covered"], cur["unique"]["of_covered"]
        if pu["n"] >= 10 and cu["n"] >= 10 and (pu["rate"] or 0) >= 0.2 and (cu["rate"] or 0) < 0.4 * pu["rate"]:
            why.append(f"unique value fell from {pu['rate']:.0%} to {cu['rate']:.0%} of its covered events")
    return why


def evaluate(inputs: NewsInputs, *, today: date, now: datetime, record_history: bool = False) -> EvalOutcome:
    """The old ``evaluate(today, record_history)``: the metric cache, the new disagreements, degraded / recovered
    sources, the monthly history line; the nominations deferred (decision d). Pure: ``inputs`` is never modified."""
    at = ts(now)
    events = list(copy.deepcopy(load(inputs.events)["events"]).values())
    appends: list[tuple[str, str]] = []

    def log(row: dict[str, Any]) -> None:  # the old ``_log``
        appends.append(("source_log", _dump({"at": at, **row})))

    out: dict[str, Any] = {"at": at}
    alpha = _deal_flow_alpha(inputs)
    cur = compute(DEFAULT_WINDOW, today, events, inputs, alpha)
    prev_window_end = today - timedelta(days=90)
    prev = compute(
        DEFAULT_WINDOW,
        prev_window_end,
        [e for e in events if e["event_date"] <= prev_window_end.isoformat()],
        inputs,
        alpha,
    )
    # disagreements: append-only first observation
    known = {
        (r["event_id"], r["field"], json.dumps(r["values"], sort_keys=True)) for r in _rows(inputs.disagreements_log)
    }
    new_dis = 0
    for r in disagreements(events):
        if r["status"] == "AGREE":
            continue
        key = (r["event_id"], r["field"], json.dumps(r["values"], sort_keys=True))
        if key not in known:
            appends.append(("disagreements", _dump({"at": at, **r})))
            new_dis += 1
    # lifecycle of monitored news sources
    changed = []
    st = copy.deepcopy(inputs.source_state or {})
    for name, row in cur["sources"].items():
        if row["kind"] == "external":
            continue
        s = st.setdefault(name, {"state": "ACTIVE", "since": at, "reasons": [], "history": []})
        why = degradation(row, prev["sources"].get(name))
        if why and s["state"] != "DEGRADED":
            s["history"].append({"at": at, "from": s["state"], "to": "DEGRADED", "why": why})
            s.update(state="DEGRADED", since=at, reasons=why)
            log({"source": name, "event": "degraded", "why": why})
            changed.append(name)
        elif not why and s["state"] == "DEGRADED":
            s["history"].append({"at": at, "from": "DEGRADED", "to": "ACTIVE", "why": ["signals recovered"]})
            s.update(state="ACTIVE", since=at, reasons=[])
            log({"source": name, "event": "recovered"})
            changed.append(name)
        elif why:
            s["reasons"] = why
    # missing publications -> the source network: DEFERRED (decision d), one logged line per would-be nomination
    nominated: list[str] = []
    deferred: list[dict[str, Any]] = []
    for m in missing_publications(events, inputs):
        if not m["ready"]:
            continue
        row = {
            "event": "nomination_deferred",
            "source": m["name"],
            "domain": m["domain"],
            "url": f"https://{m['domain']}/",
            "family": "news_publication",
            "events": m["n"],
            "why": f"Reported or was cited on {m['n']} material European events Project Zero's feeds covered: "
            + "; ".join(f"{x['company'] or '?'} ({x['date']})" for x in m["events"][:3]),
            "reason": NOMINATION_REASON,
        }
        deferred.append(row)
        log(row)
    snap: dict[str, Any] = {"at": at, "today": today.isoformat(), "windows": {}}
    for w in WINDOWS:
        snap["windows"][w] = cur if w == DEFAULT_WINDOW else compute(w, today, events, inputs, alpha)
    hist = _rows(inputs.source_history_log)
    if record_history or not hist or (_d(hist[-1].get("date")) and (today - _d(hist[-1]["date"])).days >= 28):  # type: ignore[operator]
        appends.append(
            (
                "source_history",
                _dump(
                    {
                        "date": today.isoformat(),
                        "sources": {
                            n: {
                                "articles": r["articles"]["n"],
                                "precision": r["articles"]["precision"]["rate"],
                                "recall_eu": (r["recall"].get("EUROPE") or {}).get("rate"),
                                "unique": r["unique"]["events"],
                                "early": r["earliness"]["companies"],
                                "fetch": r["technical"].get("ok_share"),
                            }
                            for n, r in cur["sources"].items()
                        },
                    }
                ),
            )
        )
    out.update(
        benchmark_events=cur["benchmark_events"],
        new_disagreements=new_dis,
        lifecycle_changes=changed,
        nominated=nominated,
    )
    log({"event": "evaluated", **{k: (len(v) if isinstance(v, list) else v) for k, v in out.items() if k != "at"}})
    # the documents as the old ``save_json`` wrote them and the next ``load_json`` read them back
    state = json.loads(json.dumps(st, ensure_ascii=False))
    metrics = json.loads(json.dumps(snap, ensure_ascii=False))
    return EvalOutcome(json.loads(json.dumps(out, ensure_ascii=False)), state, metrics, tuple(appends), tuple(deferred))

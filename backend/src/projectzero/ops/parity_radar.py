"""Radar, memo, email and weekly parity: the port against the OLD code as oracle, with a FIXED clock (review 019).

    python -m projectzero.ops.parity_radar goldens   # (re)generate tests/fixtures/golden_v1/oracle_radar.json
    python -m projectzero.ops.parity_radar real      # the real snapshot through the new endpoints

The oracle is ``scripts/oracle/conviction_oracle.py radar`` in the OLD interpreter, over a scratch data folder (a
synthetic one for the goldens, a byte-exact copy of the snapshot for ``real``; the old data folder is only read).

``goldens`` compares the PURE port: ``compose_radar`` over the old pipeline's signals, ``memo`` / ``email`` per
signal, ``weekly_update`` over the same records, people and events, and the Radar document's bytes. The milestone
credit needs the database: ``real`` and the hosted tests cover it.

``real`` imports the snapshot into a throw-away schema with the production importer, then at the first clock:
the Radar view, the counted credits (old return value vs ``counted: true`` events), a second view (no new event),
the pipeline payload after the credit, every memo and email, the weekly texts and the download (filename and bytes);
and at the second clock everything except the credit (the schema is already credited). It prints AGGREGATES and
difference PATHS only; real records never leave the machine. Exit 1 on any difference.
"""

from __future__ import annotations

import copy
import json
import sys
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

from projectzero.conviction import radar, weekly
from projectzero.ops.parity_conviction import REAL_CLOCKS, compare_view, run_oracle
from projectzero.ops.parity_ranking import GOLDEN_DIR, diff, js

GOLDEN = GOLDEN_DIR / "oracle_radar.json"
CLOCK = "2026-11-11T12:00:00"
WEEKLY = [{}, {"insight": "  Industrial buyers ask for audit trails.  ", "question": "Worth a deeper look?"},
          {"insight": "   ", "question": ""}]  # fmt: skip
ALL_V = {"founders": True, "traction": True, "funding": True}


# ------------------------------------------------------------------ the synthetic corpus (invented companies only)
def _day(days_ago: int) -> str:
    return (datetime.fromisoformat(CLOCK).date() - timedelta(days=days_ago)).isoformat()


def _scores(total: int) -> dict[str, int]:
    """Scores whose sum (earliness unknown, no conflict, no penalty) is ``total`` (0..84)."""
    founder, vs, wn = min(25, total), min(19, max(0, total - 25)), min(15, max(0, total - 44))
    taste = min(15, max(0, total - 59))
    return {"founder": founder, "venture_scale": vs, "why_now": wn, "taste": taste,
            "insight": max(0, total - founder - vs - wn - taste)}  # fmt: skip


def sig(name: str, total: int, **kw: Any) -> dict[str, Any]:
    return {"company": name, "one_liner": f"{name} automates paperwork for mid-sized manufacturers.",
            "location": "Karlsruhe, DE", "archetype": 1, "scores": _scores(total), "verified": dict(ALL_V),
            "status": "new", "conflict": "none", "discovery_source": "Example registry", "discovery_tier": "manual",
            "discovery_date": _day(40), **kw}  # fmt: skip


def corpus() -> dict[str, Any]:
    """The Radar's slot rules, the memo / email variants and the weekly window."""
    signals: list[dict[str, Any]] = []
    for i, total in enumerate((84, 80, 78, 75, 72, 70, 68, 66, 65)):  # nine above the bar: the eighth cut
        signals.append(sig(f"Highmark {i} GmbH", total, archetype=1 + i, source_id=f"src-{i % 3}",
                           inbox_id=f"aa{i:010x}"))  # fmt: skip
    signals += [
        sig("Belowbar Systems", 64, archetype=2),  # 64: not high-confidence -> watch
        sig("Fourteen Robotics", 70, archetype=14),  # the last high archetype
        sig("Emergent Labs", 60, emerging=True, archetype=3),
        sig("Emergent Two", 58, emerging=True, archetype=4),
        sig("Emergent Low", 54, emerging=True),  # under 55
        sig("Highmark Dropped", 84, status="dropped"),
        sig("Gated Industrial AG", 82, conflict="potential_conflict"),
        sig("Unverified Rising", 70, verified={"founders": True}),  # provisional 70 -> research queue
        sig("Unverified Edge", 65, verified={}),
        sig("Unverified Low", 64, verified={"traction": True}),
        sig("Watch Fifty", 50, archetype=5),
        sig("Under Fifty", 49, archetype=5),
        sig("No Source Co", 77, archetype=6),  # placed, no source_id: marked, not counted
    ]
    outlier = {"founder": 22, "venture_scale": 17, "why_now": 12, "taste": 0, "insight": 8}
    signals += [
        sig("Wild Outlier", 0, archetype=15, scores=dict(outlier), earliness="pre_seed"),
        sig("Wild Better", 0, archetype=15, scores=outlier | {"founder": 25}, earliness="pre_company"),
        sig("Wild Short", 0, archetype=15, scores=outlier | {"insight": 7}, earliness="pre_seed"),
    ]
    # memo / email variants
    timings = ["raising_now", "0_6m", "6_12m", "recently_funded", "unknown", "bogus"]
    founders: list[Any] = [
        [{"name": "Dr. Lena Beispiel", "background": "ex-plant manager", "email": "lena@example.com"}],
        [{"name": "TBD"}],
        [{"name": "Founder (unknown)"}],
        [],
        [{"name": "Jonas Muster"}, {"name": "Mia Probe", "background": "PhD robotics"}],
        [{"name": "Dr Ada"}],
    ]
    for i, (t, f) in enumerate(zip(timings, founders, strict=True)):
        signals.append(sig(f"Mail Case {i} UG", 60, fundraising_timing=t, founders=f,
                           one_liner=("AI copilots for customs brokers" if i % 2 else "Customs paperwork in minutes"),
                           verify_list=([] if i % 2 else ["Founders", "Traction"]),
                           sources=(["https://example.com/a"] if i == 1 else []),
                           conflict=("potential_conflict" if i == 2 else "similar" if i == 3 else "none"),
                           twin=("Example Twin" if i == 3 else ""), why_found="Seen in a registry filing.",
                           bull="Clear buyer.", bear="Small market.", next_action="Call the founder."))  # fmt: skip
    # the weekly window
    signals += [
        sig("Fresh Find", 40, discovery_date=_day(3)),
        sig("Old Find", 40, discovery_date=_day(30), detected_on=_day(2)),
        sig("Sent Over", 40, sent_to_omar=_day(1)),
        sig("Contacted Co", 40, status="contacted"),
        sig("Replied Co", 40, status="replied"),
        sig("Forwarded Co", 40, status="forwarded"),
        sig("Dropped Fresh", 40, status="dropped", discovery_date=_day(1)),
        sig("Edge Seven", 40, discovery_date=_day(7)),
        sig("Edge Eight", 40, discovery_date=_day(8)),
    ]
    people = [
        {"id": "p-intro", "name": "Clara Intro", "company": "Example Ventures", "created": _day(60)},
        {"id": "p-new1", "name": "Ben Neu", "company": "Neu GmbH", "created": _day(2)},
        {"id": "p-new2", "name": "Ida Rolle", "role": "Plant lead", "created": _day(5)},
        {"id": "p-new3", "name": "Otto Via", "introduced_by": "p-intro", "created": _day(6)},
        {"id": "p-new4", "name": "Eva Lost", "introduced_by": "p-missing", "created": _day(1)},
        {"id": "p-new5", "name": "Tim Fünf", "created": _day(0)},
        {"id": "p-new6", "name": "Uli Sechs", "created": _day(3)},
        {"id": "p-new7", "name": "Vera Sieben", "created": _day(4)},
        {"id": "p-omar-hedeya", "name": "Excluded Person", "created": _day(1)},
        {"id": "p-old", "name": "Old Contact", "created": _day(20)},
    ]
    events = [
        {"id": "ev-1", "name": "Example Demo Day", "city": "Berlin", "status": "attended", "start": _day(2)},
        {"id": "ev-2", "name": "Old Meetup", "city": "Munich", "status": "attended", "start": _day(30)},
        {"id": "ev-3", "name": "Planned Summit", "city": "Paris", "status": "planned", "start": _day(1)},
    ]
    inbox = {"candidates": [{"id": "aa0000000001", "name": "Highmark 1 GmbH", "q_milestones": ["kept", "radar"]},
                            {"id": "aa0000000002", "name": "Highmark 2 GmbH", "q_milestones": ["kept"]}]}  # fmt: skip
    return {"real_data.json": {"week": "", "signals": signals}, "people.json": {"people": people},
            "events.json": {"events": events}, "inbox.json": inbox}  # fmt: skip


def compose_cases() -> list[list[dict[str, Any]]]:
    """Each bar and boundary on its own (the full corpus cannot pin an edge inside a full Top 8)."""
    return [
        [sig(f"Edge High {t}", t, archetype=1 + i) for i, t in enumerate((84, 80, 78, 75, 72, 70, 68, 65, 64))],
        [sig("Edge Emerging 55", 55, emerging=True)],
        [sig("Edge Emerging 54", 54, emerging=True)],  # alone: the one slot would hide it behind a 55
        [sig("Edge Research 65", 65, verified={}), sig("Edge Research 64", 64, verified={"funding": True})],
        [
            sig("Edge Watch V50", 50),
            sig("Edge Watch P50", 50, verified={}),
            sig("Edge Watch 49", 49),
            sig("Edge Watch Gated", 50, conflict="potential_conflict"),
            sig("Edge Watch Dropped", 70, status="dropped"),
        ],
        [
            sig("Edge Arch 0", 70, archetype=0),
            sig("Edge Arch None", 70, archetype=None),
            sig("Edge Arch 14", 70, archetype=14),
            sig("Edge Arch 15", 70, archetype=15),
        ],
        [sig("Edge Clean Conflict", 70, conflict="unclear"), sig("Edge Similar", 70, conflict="similar")],
        [],
    ]


def _files(docs: Mapping[str, Any]) -> dict[str, bytes]:
    return {k: json.dumps(v, ensure_ascii=False, indent=2).encode("utf-8") for k, v in docs.items()}


# ------------------------------------------------------------------ the pure port against the goldens
def _try(fn: Any) -> Any:
    try:
        return {"ok": fn()}
    except Exception as exc:
        return {"raises": type(exc).__name__}


def new_pure(docs: Mapping[str, Any], expected: Mapping[str, Any], today: date) -> dict[str, Any]:
    """The new pure functions over the OLD pipeline's signals (``expected["signals"]``) and the same raw inputs."""
    from projectzero.api.routers.conviction import radar_file_bytes
    from projectzero.conviction.store import ConvictionStore

    signals = expected["signals"]
    view, _ = ConvictionStore.radar_of(signals)
    raw = docs["real_data.json"]["signals"]
    out: dict[str, Any] = js({
        "radar": view,
        "compose": [ConvictionStore.radar_of(case)[0] for case in compose_cases()],
        "memo": {e["slug"]: _try(lambda e=e: radar.memo(copy.deepcopy(e), today)) for e in signals},
        "email": {e["slug"]: _try(lambda e=e: radar.email(copy.deepcopy(e))) for e in signals},
        "weekly": [_try(lambda w=w: weekly.weekly_update(raw, docs["people.json"]["people"],
                                                         docs["events.json"]["events"], today,
                                                         w.get("insight", ""), w.get("question", "")))
                   for w in WEEKLY],
        "html": radar_file_bytes(radar.render_radar(signals, today)).decode("utf-8"),
    })  # fmt: skip
    return out


def compare_goldens(golden: Mapping[str, Any]) -> list[str]:
    exp = golden["expected"]
    today = datetime.fromisoformat(golden["input"]["clock"]).date()
    new = new_pure(golden["docs"], exp, today)
    return diff(js({k: exp[k] for k in ("radar", "compose", "memo", "email", "weekly", "html")}), new)


def write_goldens() -> int:
    docs = corpus()
    inp = {"clock": CLOCK, "weekly": WEEKLY, "compose": compose_cases()}
    oracle = run_oracle("radar", inp, _files(docs))
    meta = oracle.pop("meta")
    golden = {"provenance": meta, "input": inp, "docs": docs, "expected": oracle}
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    problems = compare_goldens(json.loads(GOLDEN.read_text(encoding="utf-8")))
    slots = {k: len(v) for k, v in oracle["radar"].items()}
    raises = sum(1 for d in (oracle["memo"], oracle["email"]) for r in d.values() if "raises" in r)
    print(f"radar goldens written: {len(oracle['signals'])} signals, slots {slots}, credited "
          f"{oracle['credited']} then {oracle['credited_again']}; {raises} memo/email raise; provenance "
          f"{meta['old_revision'][:7]} dirty={meta['old_dirty']}; new code differences: {len(problems)}")  # fmt: skip
    for p in problems[:40]:
        print("  DIFF", p)
    return 1 if problems else 0


# ------------------------------------------------------------------ the real snapshot
def real() -> int:  # pragma: no cover - needs the hosted database and the old repository
    import os
    import secrets as _secrets
    from pathlib import Path

    from fastapi.testclient import TestClient
    from psycopg import sql as _sql

    from projectzero.api.app import create_app
    from projectzero.conviction.store import ConvictionStore, record_of
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import connect, transaction
    from projectzero.ops.db_check import _scratch_sql
    from projectzero.ops.legacy.apply import apply_plan
    from projectzero.ops.legacy.plan import build_plan
    from projectzero.ops.legacy.source import LegacySnapshot

    load_dotenv()
    settings = Settings.from_env()
    snapshot = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    files = {f.path: f.raw for f in snapshot.files()}
    old = {c: run_oracle("radar", {"clock": c, "weekly": WEEKLY}, files) for c in REAL_CLOCKS}

    schema = f"pz_rehearse_{_secrets.token_hex(4)}"
    report: dict[str, Any] = {"oracle": old[REAL_CLOCKS[0]]["meta"]}
    problems: list[str] = []
    admin = connect(settings.db_url, autocommit=True)

    def events() -> list[dict[str, Any]]:
        with transaction(settings.db_url) as conn:
            q = _sql.SQL("select detail from {}.conviction_events where action = 'radar_milestone'")
            return [r[0] for r in conn.execute(q.format(_sql.Identifier(schema))).fetchall()]

    try:
        admin.execute(_scratch_sql(schema).encode())
        conn = connect(settings.db_url)
        try:
            applied = apply_plan(build_plan(snapshot), schema=schema, conn=conn)
            assert applied.get("applied"), applied
        finally:
            conn.close()
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            for n, clock in enumerate(REAL_CLOCKS):
                o = old[clock]
                app.state.clock = lambda clock=clock: datetime.fromisoformat(clock)
                got = client.get("/api/conviction/radar").json()
                d = [f"/radar{p.split(':')[0]}" for p in diff(js(o["radar"]), got)]
                local: dict[str, Any] = {"slots": {k: len(v) for k, v in got.items()}, "radar_differences": len(d)}
                if n == 0:  # the credit, once, on a fresh schema
                    ev = events()
                    counted = sum(1 for e in ev if e.get("counted"))
                    local |= {"credited_old": o["credited"], "counted_new": counted, "events": len(ev),
                              "credited_again_old": o["credited_again"]}  # fmt: skip
                    if counted != o["credited"]:
                        d.append(f"/credited {o['credited']} != {counted}")
                    client.get("/api/conviction/radar")
                    if len(events()) != len(ev):
                        d.append("/second view wrote events")
                    with transaction(settings.db_url) as c2:
                        stored = [record_of(r) for r in ConvictionStore(c2, schema).entry_rows()]
                    d += [f"/stored{p.split(':')[0]}" for p in diff(js(o["stored_after"]), js(stored))]
                    after = client.get("/api/conviction/pipeline").json()
                    d += [f"/pipeline_after{p}" for p in compare_view(o["pipeline_after"], after)]
                for kind in ("memo", "email"):
                    for slug_, exp in o[kind].items():
                        r = client.get(f"/api/conviction/{kind}", params={"c": slug_})
                        new = {"ok": r.json()["text"]} if r.status_code == 200 else {"status": r.status_code}
                        if "raises" in exp:  # the old route would have failed: the new one must not return text
                            if r.status_code == 200:
                                d.append(f"/{kind}/{slug_}: old raised {exp['raises']}, new returned text")
                        elif new != exp:
                            d.append(f"/{kind}/{slug_}")
                    if client.get(f"/api/conviction/{kind}", params={"c": "no-such-company"}).status_code != 404:
                        d.append(f"/{kind}/unknown: not 404")
                for i, w in enumerate(WEEKLY):
                    text = client.post("/api/conviction/weekly", json=w).json().get("text")
                    if {"ok": text} != o["weekly"][i]:
                        d.append(f"/weekly/{i}")
                r = client.get("/api/conviction/radar.html")
                if r.content != o["html"].encode("utf-8"):
                    d.append("/radar.html: bytes differ")
                if 'filename="weekly_memo.html"' not in r.headers.get("content-disposition", ""):
                    d.append("/radar.html: filename")
                local["memos"] = len(o["memo"])
                local["differences"] = len(d)
                report[f"@{clock}"] = local
                problems += [f"@{clock}{p}" for p in d]
    finally:
        admin.execute(_sql.SQL("drop schema if exists {} cascade").format(_sql.Identifier(schema)))
        admin.close()
    report["differences"] = len(problems)
    print(json.dumps(report, indent=2))
    for p in problems[:60]:
        print("  DIFF", p)
    print("RADAR PARITY PASSED" if not problems else "RADAR PARITY FAILED")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["goldens"]:
        return write_goldens()
    if argv[1:] == ["real"]:
        return real()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

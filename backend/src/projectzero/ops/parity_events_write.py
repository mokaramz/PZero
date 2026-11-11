"""Events write parity: one write script replayed on the OLD routes and on the new endpoints (review 016).

    python -m projectzero.ops.parity_events_write real

The oracle (``scripts/oracle/events_read_oracle.py writes``) runs the OLD ``event_save`` / ``event_verify`` /
``event_lead`` / ``event_debrief`` / ``scout_event`` in the OLD interpreter on a byte-exact copy of the captured
snapshot, with the clock frozen. The new side imports the SAME snapshot into a throw-away scratch schema with the
production importer and posts the same bodies to ``/api/events/*`` with the same instant.

1. **Parity segment** (adds, the fuzzy merge, edits incl. a structured price, verify incl. an unknown id, lead
   decisions, a lead conversion, a debrief meeting a new person, Scout 00 add / monitor / unknown report / unknown
   action): after EVERY step the codes, the bodies, every stored event and lead (in order), the Scout 00 reports and
   the people must match exactly. One normalisation, by decision (review 014 G10): a Scout report's ``event_id`` is
   compared without the old ``|merged:`` suffix. The old frontend converted a lead with two requests (save, then
   ``event_lead converted``); the new one sends ONE save with ``convert_lead`` (H-107): the replay compares the state
   after both old requests with the state after the one new request.
2. **Decision segment** (review 016 a-e): each step's difference is asserted explicitly, and every record the step
   did not touch must stay identical old vs new.
It prints AGGREGATES and difference PATHS only; real records never leave the machine. Exit 1 on any difference.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from projectzero.events.edits import slug_id
from projectzero.network.people import slug
from projectzero.ops.parity_events_read import run_oracle, utc_instant
from projectzero.ops.parity_ranking import diff, js

CLOCK = "2026-11-11T12:00:00"
OPEN = ("NEW", "MONITOR")


def _plain(reports: list[Any]) -> list[Any]:
    out = []
    for r in reports:
        if isinstance(r, dict) and isinstance(r.get("event_id"), str) and "|" in r["event_id"]:
            r = {**r, "event_id": r["event_id"].split("|")[0]}
        out.append(r)
    return out


def pick(snapshot_events: list[dict[str, Any]], leads: list[dict[str, Any]], reports: list[dict[str, Any]],
         people: list[dict[str, Any]]) -> dict[str, Any]:  # fmt: skip
    today = datetime.fromisoformat(CLOCK).date().isoformat()
    upcoming = [e for e in snapshot_events if str(e.get("start") or "")[:10] >= today and e.get("name")]
    new_leads = [x for x in leads if x.get("decision") == "new"]
    open_reports = [r for r in reports if r.get("status") in OPEN and r.get("event_name")]
    # an existing person in the old code's sense: the id the debrief's people.upsert generates (the slug of the name)
    named = [p for p in people if isinstance(p, dict) and p.get("name") and p.get("id") == slug(str(p["name"]))]
    assert len(upcoming) >= 3 and len(new_leads) >= 4 and named, "the snapshot is too small for the replay"
    with_url = next(e for e in upcoming if str(e.get("url") or "").startswith("http"))
    return {
        "e1": upcoming[0]["id"],
        "e2": upcoming[1]["id"],
        "e_url": with_url["id"],
        "leads": [x["id"] for x in new_leads[:4]],
        "reports": [r["id"] for r in open_reports[:2]],
        "person_name": named[0]["name"],
        "person_id": named[0]["id"],
    }


def parity_steps(p: Mapping[str, Any]) -> list[dict[str, Any]]:
    day = "2026-12-04"
    steps: list[dict[str, Any]] = [
        {"op": "save", "body": {"name": "Replay Founder Pitch Night", "type": "founder_meetup", "start": f"{day}T18:30",
                                "city": "Karlsruhe", "url": "https://replay.example.com/pitch", "source": "manual",
                                "notes": "first notes"}},
        # the fuzzy merge: similar name, same day, no id -> folded into the event above, gaps filled, source kept
        {"op": "save", "body": {"name": "Replay Founder Pitch Night 2026", "start": f"{day}T19:00",
                                "organizer": "Replay Org", "url": "https://other.example.com/pitch",
                                "source": "Luma — Replay"}},
        {"op": "save", "body": {"id": p["e1"], "status": "planned"}},
        {"op": "save", "body": {"id": p["e1"], "price": {"amount": 0, "currency": "EUR", "availability": "InStock"},
                                "notes": "edited notes"}},
        {"op": "save", "body": {"id": p["e2"], "status": "skipped"}},
        {"op": "verify", "body": {"id": p["e2"], "verified": True}},
        {"op": "verify", "body": {"id": p["e1"], "verified": False}},
        {"op": "verify", "body": {"id": "ev-replay-unknown", "verified": True}},
        {"op": "lead", "body": {"id": p["leads"][0], "decision": "dismissed"}},
        {"op": "lead", "body": {"id": p["leads"][1]}},  # the default decision: dismissed
        {"op": "lead", "body": {"id": p["leads"][0], "decision": "new"}},  # back to new
        {"op": "debrief", "body": {"id": p["e1"], "people_met": [{"name": "Replay Met Person", "note": "builds drones",
                                                                  "founder_potential": "high"}, {"name": " "}],
                                   "leads": [], "notes": "great room"}},
        {"op": "debrief", "body": {"id": p["e1"], "people_met": [], "leads": [], "notes": ""}},  # a repeat: no change
    ]  # fmt: skip
    for rid in p["reports"][:1]:
        steps.append({"op": "scout", "body": {"id": rid, "action": "add"}})
    for rid in p["reports"][1:2]:
        steps.append({"op": "scout", "body": {"id": rid, "action": "monitor"}})
    steps.append({"op": "scout", "body": {"id": "se-replay-unknown", "action": "add"}})
    if p["reports"]:
        steps.append({"op": "scout", "body": {"id": p["reports"][0], "action": "archive"}})
    return steps


def convert_steps(p: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The lead conversion: two old requests, one new one (``convert_lead``), and the same final state."""
    body = {"name": "Replay Converted Meetup", "type": "community", "start": "2026-12-09", "city": "Stuttgart",
            "url": "https://replay.example.com/conv", "source": "lead"}  # fmt: skip
    old = [{"op": "save", "body": body}, {"op": "lead", "body": {"id": p["leads"][2], "decision": "converted"}}]
    new = [{"op": "save", "body": {**body, "convert_lead": p["leads"][2]}}]
    return old, new


def decision_steps(p: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {"decision": "a-slug-merge", "op": "save", "body": {"name": "Replay Founder Pitch Night",
                                                             "start": "2026-12-04T18:30", "city": "Karlsruhe",
                                                             "notes": "collider notes", "venue": "Replay Hall"}},
        {"decision": "a-slug-conflict", "op": "save", "body": {"name": "Replay Founder Pitch Night",
                                                                "start": "2026-12-04T18:30", "city": "Berlin"}},
        {"decision": "b-unknown", "op": "save", "body": {"id": "ev-replay-not-there", "name": "Ghost", "status": "planned"}},
        {"decision": "e-bad-decision", "op": "lead", "body": {"id": p["leads"][3], "decision": "maybe"}},
        {"decision": "e-unknown-lead", "op": "lead", "body": {"id": "evlead-replay-unknown", "decision": "dismissed"}},
        {"decision": "c-existing-person", "op": "debrief", "body": {"id": p["e2"], "people_met": [
            {"name": p["person_name"], "note": "met again"}], "leads": [], "notes": ""}},
        {"decision": "d-leads", "op": "debrief", "body": {"id": p["e_url"], "people_met": [], "leads": [
            {"name": "Replay Drone Startup", "desc": "pre-seed drone inspection team"}], "notes": ""}},
        {"decision": "d-unknown-event", "op": "debrief", "body": {"id": "ev-replay-not-there", "people_met": [],
                                                                   "leads": [], "notes": ""}},
    ]  # fmt: skip


def _by_id(rows: list[Any]) -> dict[str, Any]:
    return {str(r["id"]): r for r in rows if isinstance(r, dict) and r.get("id")}


def check_decision(step: Mapping[str, Any], old: Mapping[str, Any], new_code: int, new_body: Mapping[str, Any],
                   before: Mapping[str, dict[str, Any]], old_after: Mapping[str, dict[str, Any]],
                   new_after: Mapping[str, dict[str, Any]], extra: Mapping[str, Any]) -> tuple[list[str], set[str]]:  # fmt: skip
    """``before`` / ``old_after`` / ``new_after``: {"events": by id, "leads": by id, "people": by id}."""
    kind, out = step["decision"], []

    def expect(cond: bool, what: str) -> None:
        if not cond:
            out.append(f"{kind}: {what}")

    ev_o, ev_n, ev_b = old_after["events"], new_after["events"], before["events"]
    touched: set[str] = set()
    slugged = slug_id("Replay Founder Pitch Night", "2026-12-04T18:30")
    if kind == "a-slug-merge":
        eid = slugged
        expect(old["code"] == 200 and ev_o[eid]["notes"] == "collider notes", "old overwrote the stored notes")
        expect(new_code == 200 and str(new_body.get("id", "")).startswith(eid + "|merged:"), "new: merged answer")
        expect(ev_n[eid]["notes"] == ev_b[eid]["notes"], "new: the stored notes are kept")
        expect(ev_n[eid].get("venue") == "Replay Hall", "new: the gap (venue) is filled")
        touched = {f"events/{eid}"}
    elif kind == "a-slug-conflict":
        eid = slugged
        expect(old["code"] == 200 and ev_o[eid]["city"] == "Berlin", "old overwrote the city")
        expect(new_code == 409 and new_body.get("collision") is True and new_body.get("id") == eid, "new: 409 + id")
        expect(ev_n[eid] == ev_b[eid], "new: the event is unchanged")
        touched = {f"events/{eid}"}
    elif kind == "b-unknown":
        expect(old["code"] == 200 and "ev-replay-not-there" in ev_o, "old created the unknown id")
        expect(new_code == 404 and "ev-replay-not-there" not in ev_n, "new: 404 and nothing created")
        touched = {"events/ev-replay-not-there"}
    elif kind == "e-bad-decision":
        lid = step["body"]["id"]
        expect(old_after["leads"][lid]["decision"] == "maybe", "old stored the unknown decision")
        expect(new_code == 400 and new_after["leads"][lid] == before["leads"][lid], "new: 400 and unchanged")
        touched = {f"leads/{lid}"}
    elif kind == "e-unknown-lead":
        expect(old["code"] == 200 and old["body"].get("ok") is True, "old answered ok")
        expect(new_code == 404, "new: 404")
    elif kind == "c-existing-person":
        pid, eid = extra["person_id"], step["body"]["id"]
        expect(old_after["people"][pid].get("why_interesting") == "met again", "old overwrote why_interesting")
        np, bp = new_after["people"][pid], before["people"][pid]
        expect(new_code == 200 and new_body.get("people") == [pid], "new: 200 + the person linked")
        expect(np.get("last_interaction") == datetime.fromisoformat(CLOCK).date().isoformat(), "new: last contact")
        expect({k: v for k, v in np.items() if k != "last_interaction"} ==
               {k: v for k, v in bp.items() if k != "last_interaction"}, "new: nothing else of the person changed")  # fmt: skip
        expect(pid in ev_n[eid].get("people_met", []) and ev_n[eid].get("status") == "attended", "new: event linked")
        touched = {f"people/{pid}", f"events/{eid}"}
    elif kind == "d-leads":
        eid = step["body"]["id"]
        expect(old["code"] == 200 and old["body"].get("leads") == 1, "old inserted one inbox lead")
        expect(new_code == 200 and new_body.get("leads") == 1, "new: one lead accepted by intake")
        expect(extra.get("debrief_candidates") == 1, "new: one Deal Flow candidate with origin event_debrief")
        expect(ev_n[eid].get("status") == "attended", "new: the event is attended")
        touched = {f"events/{eid}"}
    else:  # d-unknown-event
        expect(old["code"] == 200 and old["body"].get("people") == [], "old answered an empty debrief")
        expect(new_code == 404, "new: 404")
    return out, touched


def _state(steps_out: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "events": steps_out["events"],
        "leads": steps_out["leads"],
        "scout_events": _plain(steps_out["scout_events"]),
        "people": steps_out["people"],
    }


def real() -> int:  # pragma: no cover - needs the hosted database and the old repository
    import secrets as _secrets

    from fastapi.testclient import TestClient
    from psycopg import sql as _sql

    from projectzero.api.app import create_app
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import connect, transaction
    from projectzero.events import store
    from projectzero.network.store import load_people
    from projectzero.ops.db_check import _scratch_sql
    from projectzero.ops.legacy.apply import apply_plan
    from projectzero.ops.legacy.plan import build_plan
    from projectzero.ops.legacy.source import LegacySnapshot

    load_dotenv()
    settings = Settings.from_env()
    snapshot = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    files = {f.path: f.raw for f in snapshot.files()}
    ev_doc = snapshot.json("events.json", {}) or {}
    scout_doc = snapshot.json("scout_intake.json", {}) or {}
    people_doc = snapshot.json("people.json", {}) or {}
    picked = pick(ev_doc.get("events") or [], ev_doc.get("leads") or [], scout_doc.get("events") or [],
                  people_doc.get("people") or [])  # fmt: skip
    p_steps = parity_steps(picked)
    conv_old, conv_new = convert_steps(picked)
    d_steps = decision_steps(picked)
    old_run = run_oracle(
        {"clock": CLOCK, "steps": [*p_steps, *conv_old, *[{"op": s["op"], "body": s["body"]} for s in d_steps]]},
        files,
        mode="writes",
    )
    old_steps = old_run["steps"]

    schema = "pz_verify_" + _secrets.token_hex(4)
    admin = connect(settings.db_url, autocommit=True)
    problems: list[str] = []
    report: dict[str, Any] = {"schema_prefix": "pz_verify_", "clock": CLOCK, "steps": {}}
    try:
        admin.execute(_scratch_sql(schema).encode())
        with transaction(settings.db_url) as conn:
            applied = apply_plan(build_plan(snapshot), schema=schema, conn=conn)
        if not applied.get("applied"):
            raise SystemExit(f"import into the scratch schema failed: {applied}")
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        app.state.clock = lambda: utc_instant(CLOCK)
        today = date.fromisoformat(CLOCK[:10])

        def new_state() -> dict[str, Any]:
            with transaction(settings.db_url) as conn:
                data = store.load(conn, schema, today)
                doc = conn.execute(
                    _sql.SQL("select body from {}.documents where key = 'scout_intake.json#rest'").format(
                        _sql.Identifier(schema)
                    )
                ).fetchone()
                people = load_people(conn, schema)
            reports = ((doc[0] if doc else {}) or {}).get("events") or []
            return {"events": data.events, "leads": data.leads, "scout_events": _plain(reports), "people": people}

        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            # 1. the parity segment, step by step
            for i, step in enumerate(p_steps):
                r = client.post(f"/api/events/{step['op']}", json=step["body"])
                got = {"code": r.status_code, "body": r.json(), **new_state()}
                want = {"code": old_steps[i]["code"], "body": old_steps[i]["body"], **_state(old_steps[i])}
                d = diff(js(want), js(got), f"/parity/{i}:{step['op']}")
                problems += d
                report["steps"][f"{i}:{step['op']}"] = len(d)
            # the conversion: two old requests vs one new
            k = len(p_steps)
            r = client.post("/api/events/save", json=conv_new[0]["body"])
            got = {"code": r.status_code, "body": r.json(), **new_state()}
            want = {"code": old_steps[k]["code"], "body": old_steps[k]["body"], **_state(old_steps[k + 1])}
            d = diff(js(want), js(got), "/convert")
            problems += d
            retry = client.post("/api/events/save", json=conv_new[0]["body"])
            after_retry = new_state()
            if retry.json().get("replayed") is not True or js(after_retry) != js({k2: got[k2] for k2 in after_retry}):
                problems.append("/convert: a retried conversion must be answered again without a second event")
            report["steps"]["convert"] = len(d)
            # 2. the decision segment: each difference asserted, nothing else may differ
            diverged: set[str] = set()
            base = k + len(conv_old)
            for j, step in enumerate(d_steps):
                before = new_state()
                r = client.post(f"/api/events/{step['op']}", json=step["body"])
                new_after, old_after = new_state(), _state(old_steps[base + j])
                old_entry = old_steps[base + j]
                extra: dict[str, Any] = {"person_id": picked["person_id"]}
                if step["decision"] == "d-leads":
                    with transaction(settings.db_url) as conn:
                        extra["debrief_candidates"] = conn.execute(
                            _sql.SQL("select count(*) from {}.candidates where 'event_debrief' = any(origins)").format(
                                _sql.Identifier(schema)
                            )
                        ).fetchone()[0]  # type: ignore[index]
                index = {name: {"events": _by_id(s["events"]), "leads": _by_id(s["leads"]), "people": _by_id(s["people"])}
                         for name, s in (("before", before), ("old", old_after), ("new", new_after))}  # fmt: skip
                d, touched = check_decision(step, old_entry, r.status_code, r.json(), index["before"], index["old"],
                                            index["new"], extra)  # fmt: skip
                diverged |= touched
                for kind in ("events", "leads", "people"):
                    for rid in set(index["old"][kind]) | set(index["new"][kind]):
                        if f"{kind}/{rid}" in diverged:
                            continue
                        if js(index["old"][kind].get(rid)) != js(index["new"][kind].get(rid)):
                            d.append(f"{step['decision']}: {kind}/{rid} differs although the step did not touch it")
                problems += d
                report["steps"][step["decision"]] = len(d)
            with transaction(settings.db_url) as conn:
                report["event_history"] = dict(conn.execute(
                    _sql.SQL("select action, count(*) from {}.event_history group by 1 order by 1").format(_sql.Identifier(schema))
                ).fetchall())  # fmt: skip
    finally:
        admin.execute(_sql.SQL("drop schema if exists {} cascade").format(_sql.Identifier(schema)))
        admin.close()
    report["differences"] = len(problems)
    print(json.dumps(report, indent=2, default=str))
    for p in problems[:60]:
        print("  DIFF", p)
    print("EVENTS WRITE PARITY PASSED" if not problems else "EVENTS WRITE PARITY FAILED")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["real"]:
        return real()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

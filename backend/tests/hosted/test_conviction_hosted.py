"""Review 011 acceptance tests (Codex) against the hosted project, in throw-away scratch schemas:

* IMQ expiry: a fixed clock crosses the 90-day line; two reads change the display, the stored history is untouched;
  the next write appends the transition once.
* Atomic Keep: entry + candidate ``kept`` + the decision event with the feedback snapshot, in one transaction; a
  duplicate Keep (by slug, or by the company's existing entry) changes nothing, and a lead on ``watch`` stays on watch.
* Concurrent create / Keep of the same slug on two sessions: one wins, the loser waits on the lock, then gets 409 + the
  slug, and its candidate, events and ledger are unchanged.
* Repeating a successful Keep records no second Keep. Keep and a Deal Flow decision on the same candidate overlap
  without deadlock (company row, then candidate row).
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from projectzero.api.app import create_app
from projectzero.conviction.store import ConvictionError, ConvictionStore
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.dealflow.candidates import DealFlowStore
from projectzero.dealflow.intake.postgres import PostgresIntake
from projectzero.dealflow.intake.service import IntakeService
from projectzero.dealflow.ranking.service import RankingContext
from projectzero.ops.db_check import _scratch_sql

pytestmark = pytest.mark.hosted
T0 = datetime(2026, 11, 11, 12, 0, 0)


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture
def schema(settings: Settings) -> Iterator[str]:
    name = f"pz_itest_{secrets.token_hex(4)}"
    admin = connect(settings.db_url, autocommit=True)
    try:
        admin.execute(_scratch_sql(name).encode())
        yield name
    finally:
        admin.execute(f"drop schema if exists {name} cascade".encode())
        admin.close()


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def api(settings: Settings, schema: str) -> Iterator[tuple[TestClient, Clock]]:
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    clock = Clock(T0)
    app.state.clock = clock
    with TestClient(app, base_url="http://127.0.0.1:8177") as client:
        yield client, clock


def deliver(settings: Settings, schema: str, name: str) -> str:
    payload = {"contract_version": "1.0", "origin": "grok", "external_ref": secrets.token_hex(3),
               "submitted_at": "2026-11-11T09:00:00+01:00",
               "entities": [{"kind": "company", "name": name, "key_fact": f"{name} raised a pre-seed round",
                             "evidence": [{"url": f"https://news.example.com/{name.lower().replace(' ', '-')}"}]}]}  # fmt: skip
    with transaction(settings.db_url) as conn:
        store = PostgresIntake(conn, schema)
        result = IntakeService(store, resolver=store).submit_external(payload, submitted_by="grok")
    return str(result.resolution[0]["candidate_id"])


def q(settings: Settings, schema: str, query: str, params: Any = ()) -> list[tuple[Any, ...]]:
    with transaction(settings.db_url) as conn:
        return conn.execute(query.replace("{s}", schema).encode(), params).fetchall()


def keep_events(settings: Settings, schema: str, cid: str) -> list[tuple[Any, ...]]:
    return q(settings, schema, "select from_status, detail from {s}.candidate_events where candidate_id = %s "
             "and action = 'status' and to_status = 'kept' order by id", (cid,))  # fmt: skip


def scored(**extra: Any) -> dict[str, Any]:
    return {"scores": {"founder": 20, "venture_scale": 14, "why_now": 11, "taste": 10, "insight": 5},
            "verified": {"founders": True, "traction": False, "funding": False}, "archetype": 7,
            "founders": [{"name": "Jane Roe", "background": "ex-Siemens"}], **extra}  # fmt: skip


# ── IMQ expiry ──────────────────────────────────────────────────────────────────────────────────────────────────
def seed_qualifying_entry(settings: Settings, schema: str) -> None:
    """An imported-style entry that qualifies at T0 (trigger 80 days old) and expires 11 days later."""
    record = {"company": "Qual Labs", "status": "new", "archetype": 3, "earliness": "pre_company", "conflict": "none",
              "scores": {"founder": 25, "venture_scale": 19, "why_now": 15, "taste": 15, "insight": 10},
              "verified": {"founders": True, "traction": True, "funding": True}, "founders": [{"name": "Ada Lovelace"}],
              "imq_trigger": {"kind": "fundraising", "date": (T0 - timedelta(days=80)).date().isoformat(),
                              "url": "https://news.example.com/q", "fact": "raising a seed", "by": "operator"}}  # fmt: skip
    with transaction(settings.db_url) as conn:
        co = conn.execute(
            f"insert into {schema}.companies (name) values ('Qual Labs') returning id".encode()
        ).fetchone()
        assert co is not None
        conn.execute(
            f"insert into {schema}.conviction_entries (company_id, slug, status, verified, scores, legacy) "
            "values (%s, 'qual-labs', 'new', %s, %s, %s)".encode(),
            (co[0], Jsonb(record["verified"]), Jsonb(record["scores"]), Jsonb(record)),
        )
        conn.execute(
            f"insert into {schema}.people (id, name, identity_status, legacy) values ('p-ada', 'Ada Lovelace', "
            "'resolved', %s)".encode(),
            (Jsonb({"id": "p-ada", "name": "Ada Lovelace", "identity_status": "resolved"}),),
        )


def stored_imq(settings: Settings, schema: str) -> Any:
    rows = q(settings, schema, "select attrs->'record'->'imq', legacy->'imq' from {s}.conviction_entries "
             "where slug = 'qual-labs'")  # fmt: skip
    return rows[0]


def test_imq_expiry_reads_display_writes_stamp_once(
    settings: Settings, schema: str, api: tuple[TestClient, Clock]
) -> None:
    client, clock = api
    seed_qualifying_entry(settings, schema)

    def signal() -> dict[str, Any]:
        sig: dict[str, Any] = client.get("/api/conviction/pipeline").json()["signals"][0]
        return sig

    assert signal()["imq_eval"]["state"] == "IMQ — QUALIFIED NOW"
    assert stored_imq(settings, schema) == (None, None)  # the read stamped nothing
    assert client.post("/api/conviction/status", json={"slug": "qual-labs", "status": "contacted"}).status_code == 200
    stamped, _ = stored_imq(settings, schema)
    assert stamped["state"] == "IMQ — QUALIFIED NOW" and stamped["qualified_at"] == "2026-11-11 12:00"
    assert stamped["history"] == [{"on": "2026-11-11 12:00", "to": "IMQ — QUALIFIED NOW"}]

    clock.now = T0 + timedelta(days=11, hours=2)  # the trigger is now 91 days old
    for _ in range(2):
        e = signal()
        assert e["imq_eval"]["state"] == "IMQ — STALE" and e["imq_eval"]["persisted"] == stamped
        assert stored_imq(settings, schema)[0] == stamped  # two reads: stored history untouched
    events_before = q(settings, schema, "select count(*) from {s}.conviction_events")[0][0]

    assert client.post("/api/conviction/status", json={"slug": "qual-labs", "status": "replied"}).status_code == 200
    stale, _ = stored_imq(settings, schema)
    assert stale["state"] == "IMQ — STALE" and stale["stale_since"] == "2026-11-22 14:00"
    assert [h["to"] for h in stale["history"]] == ["IMQ — QUALIFIED NOW", "IMQ — STALE"]
    detail = q(settings, schema, "select detail from {s}.conviction_events order by id desc limit 1")[0][0]
    assert detail["imq"] == {"from": "IMQ — QUALIFIED NOW", "to": "IMQ — STALE"}

    clock.now += timedelta(hours=3)
    save = client.post("/api/conviction/save", json={"slug": "qual-labs", "company": "Qual Labs", "bull": "still"})
    assert save.status_code == 200
    again, _ = stored_imq(settings, schema)
    assert again == stale  # the next write does not append the transition a second time
    assert q(settings, schema, "select count(*) from {s}.conviction_events")[0][0] == events_before + 2


# ── Keep ────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_keep_is_atomic_and_duplicates_change_nothing(
    settings: Settings, schema: str, api: tuple[TestClient, Clock]
) -> None:
    client, _ = api
    alpha = deliver(settings, schema, "Alpha Robotics")
    watched = deliver(settings, schema, "Watch Labs")
    with transaction(settings.db_url) as conn:
        DealFlowStore(conn, schema).decide(watched, "watch")

    r = client.post("/api/conviction/save", json={"company": "Alpha Robotics GmbH", "inbox_id": alpha, **scored()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["slug"] == "alpha-robotics"
    assert body["keep"]["status"] == "kept" and body["keep"]["changed"] is True
    assert q(settings, schema, "select status from {s}.candidates where id = %s", (alpha,))[0][0] == "kept"
    entry = q(settings, schema, "select candidate_id, company_id, attrs->'record' from {s}.conviction_entries")[0]
    company = q(settings, schema, "select company_id from {s}.candidates where id = %s", (alpha,))[0][0]
    assert entry[0] == alpha and entry[1] == company and entry[2]["inbox_id"] == alpha
    (from_status, detail), = keep_events(settings, schema, alpha)  # fmt: skip
    assert from_status == "new" and detail["feedback"]["decision"] == "kept" and detail["feedback"]["keys"][0] == alpha
    with transaction(settings.db_url) as conn:  # the effective ledger counts it like any decision (review 008)
        ledger = RankingContext.load(conn, schema).ledger
    assert detail["feedback"]["source_ids"]  # a tagged Grok lead carries its source
    assert ledger["decisions"][alpha]["decision"] == "kept"
    created = q(settings, schema, "select action, before, after from {s}.conviction_events")
    assert (
        [c[0] for c in created] == ["create"]
        and created[0][1] is None
        and created[0][2]["company"] == "Alpha Robotics GmbH"
    )

    def unchanged() -> tuple[Any, ...]:
        return (q(settings, schema, "select status from {s}.candidates where id = %s", (watched,))[0][0],
                q(settings, schema, "select count(*) from {s}.candidate_events where candidate_id = %s", (watched,))[0][0],
                q(settings, schema, "select count(*) from {s}.conviction_events")[0][0],
                q(settings, schema, "select count(*) from {s}.conviction_entries")[0][0])  # fmt: skip

    before = unchanged()
    dup = client.post("/api/conviction/save", json={"company": "Alpha Robotics", "inbox_id": watched, **scored()})
    assert dup.status_code == 409
    assert dup.json() == {"ok": False, "error": "a company with this name already exists — open it in Conviction to "
                          "edit it", "slug": "alpha-robotics", "duplicate": True}  # fmt: skip
    assert unchanged() == before and before[0] == "watch"

    # the same company under another name: one entry per company, so the Keep opens the existing entry
    other = client.post("/api/conviction/save", json={"company": "Alpha Two", "inbox_id": alpha, **scored()})
    assert other.status_code == 409 and other.json()["slug"] == "alpha-robotics"

    # repeating the successful Keep: a duplicate (no slug), or an update through the entry (slug): no second Keep
    again = client.post("/api/conviction/save", json={"company": "Alpha Robotics GmbH", "inbox_id": alpha, **scored()})
    assert again.status_code == 409 and again.json()["slug"] == "alpha-robotics"
    through = client.post("/api/conviction/save", json={"company": "Alpha Robotics GmbH", "inbox_id": alpha,
                                                         "slug": "alpha-robotics", **scored()})  # fmt: skip
    assert through.status_code == 200 and through.json()["keep"]["changed"] is False
    assert len(keep_events(settings, schema, alpha)) == 1
    assert client.post("/api/conviction/save", json={"inbox_id": "nope", "company": "X"}).status_code == 404


def test_keep_of_an_unknown_lead_and_a_bad_save_write_nothing(
    settings: Settings, schema: str, api: tuple[TestClient, Clock]
) -> None:
    client, _ = api
    lead = deliver(settings, schema, "Gamma Grid")
    r = client.post("/api/conviction/save", json={"inbox_id": lead})  # no company: refused after the lookups
    assert r.status_code == 400 and r.json()["error"] == "company required"
    assert q(settings, schema, "select status from {s}.candidates where id = %s", (lead,))[0][0] == "new"
    assert q(settings, schema, "select count(*) from {s}.conviction_entries")[0][0] == 0


def test_concurrent_create_and_keep_of_one_slug(settings: Settings, schema: str, api: tuple[TestClient, Clock]) -> None:
    client, _ = api
    first = deliver(settings, schema, "Delta Labs")
    second = deliver(settings, schema, "Delta Labs Research")  # another company and candidate
    slug_body = {"company": "Delta Labs", **scored()}

    holder = connect(settings.db_url)
    result: dict[str, Any] = {}
    try:
        with holder.transaction():
            ConvictionStore(holder, schema).save({**slug_body, "inbox_id": first}, T0)  # uncommitted winner

            def loser() -> None:
                r = client.post("/api/conviction/save", json={**slug_body, "company": "Delta Labs GmbH",
                                                               "inbox_id": second})  # fmt: skip
                result["code"], result["body"] = r.status_code, r.json()

            thread = threading.Thread(target=loser)
            thread.start()
            deadline = time.monotonic() + 20
            waiting = 0
            while time.monotonic() < deadline and not waiting:
                time.sleep(0.2)
                waiting = q(settings, schema, "select count(*) from pg_locks where locktype = 'advisory' "
                            "and not granted")[0][0]  # fmt: skip
            assert waiting, "the second save did not wait on the Conviction write lock"
            assert thread.is_alive()
    finally:
        holder.close()
    thread.join(30)
    assert result["code"] == 409 and result["body"]["slug"] == "delta-labs" and result["body"]["duplicate"] is True
    assert q(settings, schema, "select status from {s}.candidates where id = %s", (first,))[0][0] == "kept"
    assert q(settings, schema, "select status from {s}.candidates where id = %s", (second,))[0][0] == "new"
    assert keep_events(settings, schema, second) == []
    assert q(settings, schema, "select count(*) from {s}.conviction_entries")[0][0] == 1
    with transaction(settings.db_url) as conn:
        ledger = RankingContext.load(conn, schema).ledger or {}
    assert second not in (ledger.get("decisions") or {})


def test_keep_and_a_deal_flow_decision_on_one_candidate_overlap_without_deadlock(
    settings: Settings, schema: str, api: tuple[TestClient, Clock]
) -> None:
    client, _ = api
    lead = deliver(settings, schema, "Epsilon Bio")
    holder = connect(settings.db_url)
    result: dict[str, Any] = {}
    try:
        with holder.transaction():
            DealFlowStore(holder, schema).decide(lead, "watch")  # holds the company, then the candidate row

            def keep() -> None:
                r = client.post("/api/conviction/save", json={"company": "Epsilon Bio", "inbox_id": lead, **scored()})
                result["code"] = r.status_code

            thread = threading.Thread(target=keep)
            thread.start()
            time.sleep(1.5)
            assert thread.is_alive(), "the Keep did not wait for the decision's row locks"
    finally:
        holder.close()
    thread.join(30)
    assert result["code"] == 200
    assert [e[0] for e in keep_events(settings, schema, lead)] == ["watch"]


def test_keep_onto_a_company_that_has_an_entry_changes_nothing(
    settings: Settings, schema: str, api: tuple[TestClient, Clock]
) -> None:
    """One entry per company: a Keep under ANOTHER name of a company that already has an entry is a duplicate. The
    lead keeps its status (watch), no event or ledger vote is written: the whole save is one transaction."""
    client, _ = api
    watched = deliver(settings, schema, "Zeta Watch")
    with transaction(settings.db_url) as conn:
        DealFlowStore(conn, schema).decide(watched, "watch")
    company = q(settings, schema, "select company_id from {s}.candidates where id = %s", (watched,))[0][0]
    with transaction(settings.db_url) as conn:
        conn.execute(f"insert into {schema}.conviction_entries (company_id, slug, status, legacy) values "
                     "(%s, 'zeta-legacy', 'new', %s)".encode(), (company, Jsonb({"company": "Zeta Legacy"})))  # fmt: skip
    events = q(settings, schema, "select count(*) from {s}.candidate_events where candidate_id = %s", (watched,))[0][0]
    r = client.post("/api/conviction/save", json={"company": "Zeta Watch New", "inbox_id": watched, **scored()})
    assert r.status_code == 409 and r.json()["slug"] == "zeta-legacy" and r.json()["duplicate"] is True
    assert q(settings, schema, "select status from {s}.candidates where id = %s", (watched,))[0][0] == "watch"
    assert (
        q(settings, schema, "select count(*) from {s}.candidate_events where candidate_id = %s", (watched,))[0][0]
        == events
    )
    assert q(settings, schema, "select count(*) from {s}.conviction_entries")[0][0] == 1
    # decided by the explicit check under the lock, not by the schema's last line of defence
    with transaction(settings.db_url) as conn, pytest.raises(ConvictionError) as refused:
        ConvictionStore(conn, schema).save({"company": "Zeta Watch New", "inbox_id": watched}, T0)
    assert refused.value.status == 409 and refused.value.extra["slug"] == "zeta-legacy"


# ── H-074: an existing entry may only Keep its own lead ─────────────────────────────────────────────────────────
def _snapshot(settings: Settings, schema: str, lead: str) -> tuple[Any, ...]:
    return (
        q(settings, schema, "select status from {s}.candidates where id = %s", (lead,))[0][0],
        q(settings, schema, "select count(*) from {s}.candidate_events where candidate_id = %s", (lead,))[0][0],
        q(settings, schema, "select count(*) from {s}.conviction_events")[0][0],
        q(settings, schema, "select slug, candidate_id, company_id, attrs from {s}.conviction_entries order by slug"),
    )


def test_a_linked_entry_refuses_to_keep_another_lead(
    settings: Settings, schema: str, api: tuple[TestClient, Clock]
) -> None:
    client, _ = api
    own = deliver(settings, schema, "Linked Robotics")
    other = deliver(settings, schema, "Other Watch Co")
    with transaction(settings.db_url) as conn:
        DealFlowStore(conn, schema).decide(other, "watch")
    assert (
        client.post(
            "/api/conviction/save", json={"company": "Linked Robotics", "inbox_id": own, **scored()}
        ).status_code
        == 200
    )
    before = _snapshot(settings, schema, other)
    r = client.post("/api/conviction/save", json={"company": "Linked Robotics", "slug": "linked-robotics",
                                                  "inbox_id": other, "next_action": "should not land", **scored()})  # fmt: skip
    assert r.status_code == 409
    assert r.json()["slug"] == "linked-robotics" and r.json()["linked_candidate"] == own
    after = _snapshot(settings, schema, other)
    assert after == before and before[0] == "watch"  # lead on watch, no event, entry and its link untouched
    assert keep_events(settings, schema, other) == []
    with transaction(settings.db_url) as conn:
        vote = (RankingContext.load(conn, schema).ledger or {}).get("decisions", {}).get(other)
    assert vote is not None and vote["decision"] == "watch"  # its own Watch vote, never a Keep for another entry
    # its own lead through the same edit is still a harmless repeat
    ok = client.post("/api/conviction/save", json={"company": "Linked Robotics", "slug": "linked-robotics",
                                                   "inbox_id": own, **scored()})  # fmt: skip
    assert ok.status_code == 200 and ok.json()["keep"]["changed"] is False


def test_an_unlinked_entry_refuses_a_lead_of_another_company(
    settings: Settings, schema: str, api: tuple[TestClient, Clock]
) -> None:
    client, _ = api
    other = deliver(settings, schema, "Foreign Watch Co")
    with transaction(settings.db_url) as conn:
        DealFlowStore(conn, schema).decide(other, "watch")
    assert client.post("/api/conviction/save", json={"company": "Manual Entry Co", **scored()}).status_code == 200
    before = _snapshot(settings, schema, other)
    r = client.post("/api/conviction/save", json={"company": "Manual Entry Co", "slug": "manual-entry-co",
                                                  "inbox_id": other, **scored()})  # fmt: skip
    assert r.status_code == 409 and r.json()["slug"] == "manual-entry-co"
    after = _snapshot(settings, schema, other)
    assert after == before and before[0] == "watch"
    assert keep_events(settings, schema, other) == []

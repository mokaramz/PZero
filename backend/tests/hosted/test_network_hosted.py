"""Review 013 acceptance tests (Codex) against the hosted project, in throw-away scratch schemas:

* an add whose generated id exists gets 409 with that id; an edit of an unknown id creates nothing;
* a partial edit on an imported person keeps every other field and the identifier rows; a strong identifier another
  person holds rolls back the WHOLE edit (the pre-check, and the unique index behind it);
* two introducers concurrently recommending one person: both recommendations survive, only one fills an initially
  empty parent, an existing parent survives either write; a retry leaves one recommendation per introducer;
* concurrent saves of one person run one after another, and neither loses the other's field;
* an ``attrs.record`` edit through the endpoint reaches Conviction's IMQ inputs;
* the read order (archive, then ``created_at``, then id; one request's new people in the order it named them), and
  reads never write.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from projectzero.api.app import create_app
from projectzero.conviction.inputs import load_inputs
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.network.people import WEAK_KINDS, columns_of, distinct_identifiers
from projectzero.network.store import PeopleStore, load_people
from projectzero.ops.db_check import _scratch_sql

pytestmark = pytest.mark.hosted
T0 = datetime(2026, 11, 11, 12, 0, 0)
IMPORTED_AT = datetime(2026, 9, 12, tzinfo=UTC)


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


def q(settings: Settings, schema: str, query: str, params: Any = ()) -> list[tuple[Any, ...]]:
    with transaction(settings.db_url) as conn:
        return conn.execute(query.replace("{s}", schema).encode(), params).fetchall()


def seed(settings: Settings, schema: str, people: list[dict[str, Any]]) -> None:
    """People as the importer writes them: the archived people.json, a row per person (``columns_of``, ``legacy``,
    no ``attrs.record``) and its identifiers (a strong one held by an earlier person is reported, not stored)."""
    raw = json.dumps({"people": people}).encode()
    owned: set[tuple[str, str]] = set()
    with transaction(settings.db_url) as conn:
        conn.execute(
            f"insert into {schema}.legacy_documents (path, sha256, bytes, raw, parsed) values (%s, %s, %s, %s, %s)".encode(),
            ("people.json", hashlib.sha256(raw).hexdigest(), len(raw), raw, Jsonb(json.loads(raw))),
        )
        for i, p in enumerate(people):
            cols = columns_of(p["id"], p)
            conn.execute(
                f"insert into {schema}.people (id, name, normalized_name, country, identity_status, founder_status, "
                "radar_state, attrs, legacy, created_at) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)".encode(),
                (
                    p["id"],
                    cols["name"],
                    cols["normalized_name"],
                    cols["country"],
                    cols["identity_status"],
                    cols["founder_status"],
                    cols["radar_state"],
                    Jsonb(cols["attrs"]),
                    Jsonb(p),
                    IMPORTED_AT + timedelta(minutes=len(people) - i),
                ),
            )  # created_at deliberately REVERSED: the archive order must win
            for kind, value in distinct_identifiers(p):
                if kind not in WEAK_KINDS:
                    if (kind, value) in owned:
                        continue
                    owned.add((kind, value))
                conn.execute(
                    f"insert into {schema}.person_identifiers (person_id, kind, value) values (%s, %s, %s)".encode(),
                    (p["id"], kind, value),
                )


def row(settings: Settings, schema: str, pid: str) -> dict[str, Any] | None:
    with transaction(settings.db_url) as conn, conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(f"select * from {schema}.people where id = %s".encode(), (pid,))
        return cur.fetchone()


def record(settings: Settings, schema: str, pid: str) -> dict[str, Any]:
    r = row(settings, schema, pid)
    assert r is not None
    rec = (r["attrs"] or {}).get("record")
    return rec if isinstance(rec, dict) else r["legacy"]


def identifiers(settings: Settings, schema: str, pid: str) -> list[tuple[Any, ...]]:
    return q(settings, schema, "select id, kind, value from {s}.person_identifiers where person_id = %s order by id",
             (pid,))  # fmt: skip


def events(settings: Settings, schema: str, pid: str | None = None) -> list[tuple[Any, ...]]:
    if pid is None:
        return q(settings, schema, "select person_id, action, before, after, detail from {s}.person_events order by id")
    return q(settings, schema, "select action, before, after, detail from {s}.person_events where person_id = %s "
             "order by id", (pid,))  # fmt: skip


ADA = {"id": "p-ada-quill", "name": "Ada Quill", "provenance": "radar_detected", "company": "Quill Labs",
       "orcid": "0000-0002-1825-0097", "openalex_id": "A5000000001", "aliases": ["adaq"],
       "profile_urls": ["https://openalex.org/A5000000001", "https://quill.example.com"],
       "identity_status": "needs identity resolution", "recommended": [], "startups": [], "created": "2026-09-12"}  # fmt: skip
# the same person imported as a Network person (user_provided): edits take the plain save, without the Founder Radar
# identity / signal recompute that review 026a ported for radar-generated people
ADA_NET = {**ADA, "provenance": "user_provided"}
BEN = {"id": "p-ben-ortiz", "name": "Ben Ortiz", "provenance": "user_provided", "recommended": [], "startups": [],
       "created": "2026-09-13"}  # fmt: skip


def waiting_on_lock(settings: Settings, schema: str, seconds: float = 20) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(0.2)
        if q(settings, schema, "select count(*) from pg_locks where not granted and locktype = 'advisory'")[0][0]:
            return True
    return False


# ── decision (a) ────────────────────────────────────────────────────────────────────────────────────────────────
def test_an_add_onto_an_existing_generated_id_returns_that_id(
    settings: Settings, schema: str, api: tuple[TestClient, Clock]
) -> None:
    client, _ = api
    seed(settings, schema, [ADA])
    before = row(settings, schema, "p-ada-quill")
    r = client.post("/api/network/person_save", json={"name": "Ada  Quill!", "company": "Overwritten Co"})
    assert r.status_code == 409
    assert r.json() == {"ok": False, "error": "a person with this name already exists — open the existing person to "
                        "edit them; nothing was saved", "id": "p-ada-quill", "duplicate": True}  # fmt: skip
    assert row(settings, schema, "p-ada-quill") == before and events(settings, schema) == []

    r = client.post("/api/network/person_save", json={"name": "Cleo Vance", "startups": "A, B", "watch": True})
    assert r.status_code == 200 and r.json() == {"ok": True, "id": "p-cleo-vance"}
    created = record(settings, schema, "p-cleo-vance")
    assert created == {"id": "p-cleo-vance", "name": "Cleo Vance", "recommended": [], "startups": ["A", "B"],
                       "created": "2026-11-11", "provenance": "user_provided", "watch": True}  # fmt: skip
    assert events(settings, schema, "p-cleo-vance")[0][:3] == ("create", None, created)
    again = client.post("/api/network/person_save", json={"name": "Cleo Vance"})
    assert again.status_code == 409 and again.json()["id"] == "p-cleo-vance"
    assert len(events(settings, schema)) == 1


def test_an_edit_of_an_unknown_id_creates_nothing(
    settings: Settings, schema: str, api: tuple[TestClient, Clock]
) -> None:
    client, _ = api
    seed(settings, schema, [ADA])
    r = client.post("/api/network/person_save", json={"id": "p-nobody", "name": "No Body", "next_action": "x"})
    assert r.status_code == 404 and r.json() == {"ok": False, "error": "unknown person — nothing was saved",
                                                 "id": "p-nobody"}  # fmt: skip
    assert q(settings, schema, "select count(*) from {s}.people")[0][0] == 1
    assert events(settings, schema) == [] and identifiers(settings, schema, "p-nobody") == []


# ── the mirrored write ──────────────────────────────────────────────────────────────────────────────────────────
def test_a_partial_edit_on_an_imported_person_keeps_everything_else(
    settings: Settings, schema: str, api: tuple[TestClient, Clock]
) -> None:
    client, _ = api
    seed(settings, schema, [ADA_NET, BEN])
    ids_before = identifiers(settings, schema, "p-ada-quill")
    cols_before = row(settings, schema, "p-ada-quill")
    assert cols_before is not None
    r = client.post("/api/network/person_save", json={"id": "p-ada-quill", "next_action": "Follow up after the "
                                                      "paper", "next_action_date": "2026-11-20"})  # fmt: skip
    assert r.status_code == 200 and r.json() == {"ok": True, "id": "p-ada-quill"}
    after = row(settings, schema, "p-ada-quill")
    assert after is not None
    assert after["legacy"] == ADA_NET  # the import is never changed
    assert after["attrs"]["record"] == {**ADA_NET, "next_action": "Follow up after the paper",
                                        "next_action_date": "2026-11-20"}  # fmt: skip
    for col in ("name", "normalized_name", "country", "identity_status", "founder_status", "radar_state"):
        assert after[col] == cols_before[col]
    assert after["attrs"]["company"] == "Quill Labs" and after["attrs"]["next_action"] == "Follow up after the paper"
    assert identifiers(settings, schema, "p-ada-quill") == ids_before  # the same rows, untouched
    ((action, b, a, detail),) = events(settings, schema, "p-ada-quill")
    assert action == "save" and b == {"next_action": None, "next_action_date": None}
    assert a == {"next_action": "Follow up after the paper", "next_action_date": "2026-11-20"}
    assert detail == {"fields": ["next_action", "next_action_date"]}

    # an identifier edit: only the changed identifier's row is replaced
    r = client.post("/api/network/person_save", json={"id": "p-ada-quill", "orcid": "0000-0001-5109-3700"})
    assert r.status_code == 200
    now = identifiers(settings, schema, "p-ada-quill")
    assert [i for i in now if i[1] != "orcid"] == [i for i in ids_before if i[1] != "orcid"]
    assert [i[1:] for i in now if i[1] == "orcid"] == [("orcid", "https://orcid.org/0000-0001-5109-3700")]
    # a save that changes nothing writes nothing
    r = client.post("/api/network/person_save", json={"id": "p-ada-quill", "orcid": "0000-0001-5109-3700"})
    assert r.status_code == 200 and len(events(settings, schema, "p-ada-quill")) == 2


def test_a_strong_identifier_conflict_rolls_back_the_whole_edit(
    settings: Settings, schema: str, api: tuple[TestClient, Clock], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = api
    seed(settings, schema, [ADA, BEN])
    ben_before, ids_before = row(settings, schema, "p-ben-ortiz"), identifiers(settings, schema, "p-ben-ortiz")
    body = {
        "id": "p-ben-ortiz",
        "next_action": "call",
        "aliases": ["benny"],
        "orcid": "https://orcid.org/0000-0002-1825-0097",
    }
    r = client.post("/api/network/person_save", json=body)
    assert r.status_code == 409
    assert r.json() == {"ok": False, "error": "orcid https://orcid.org/0000-0002-1825-0097 already belongs to another "
                        "person (p-ada-quill) — nothing was saved", "identifier": {"kind": "orcid", "value":
                        "https://orcid.org/0000-0002-1825-0097"}, "owner": "p-ada-quill"}  # fmt: skip
    assert (
        row(settings, schema, "p-ben-ortiz") == ben_before
        and identifiers(settings, schema, "p-ben-ortiz") == ids_before
    )
    assert events(settings, schema) == []

    # the unique index behind the pre-check: the row update and the new alias are rolled back with it
    monkeypatch.setattr(PeopleStore, "_refuse_strong_conflicts", lambda *_: set())
    r = client.post("/api/network/person_save", json=body)
    assert r.status_code == 409 and r.json() == {"ok": False, "error": "a strong identifier of this person already "
                                                 "belongs to another person — nothing was saved"}  # fmt: skip
    assert (
        row(settings, schema, "p-ben-ortiz") == ben_before
        and identifiers(settings, schema, "p-ben-ortiz") == ids_before
    )
    assert events(settings, schema) == []


def test_a_conflict_the_import_already_reported_does_not_block_other_edits(
    settings: Settings, schema: str, api: tuple[TestClient, Clock]
) -> None:
    """The importer stored a repeated strong identifier for the first person only. Editing the second person's other
    fields still works, and the identifier stays unstored for them (the import's rule)."""
    client, _ = api
    twin = {**BEN, "orcid": ADA["orcid"]}
    seed(settings, schema, [ADA, twin])
    r = client.post("/api/network/person_save", json={"id": "p-ben-ortiz", "notes": "met at the meetup"})
    assert r.status_code == 200
    assert [i[1] for i in identifiers(settings, schema, "p-ben-ortiz")] == []
    assert record(settings, schema, "p-ben-ortiz")["notes"] == "met at the meetup"


def test_renaming_a_founder_radar_person_takes_the_old_radar_name_path(
    settings: Settings, schema: str, api: tuple[TestClient, Clock]
) -> None:
    """Review 026a delivers what review 013 deferred: the old ``operator_save`` radar path."""
    client, _ = api
    seed(settings, schema, [ADA])
    r = client.post("/api/network/person_save", json={"id": "p-ada-quill", "name": "Ada Lovequill", "notes": "x"})
    assert r.status_code == 200, r.text
    rec = record(settings, schema, "p-ada-quill")
    assert rec["name"] == "Ada Lovequill" and "Ada Quill" in rec["aliases"]  # the former name kept as an alias
    assert rec["name_by_operator"] is True and rec["name_attributed"] is True
    assert "identity_verified_by" not in rec  # entering a name never verifies the identity
    assert any("human name entered by Mohamed" in x and "Ada Quill -> Ada Lovequill" in x
               for x in rec["identity_evidence"])  # fmt: skip
    assert rec["sources"][-1]["source"] == "Operator edit" and rec["sources"][-1]["by"] == "operator"
    assert isinstance(rec["signal"], dict) and rec["signal_categories"] == rec["signal"]["bands"]  # recomputed
    assert [e[0] for e in events(settings, schema, "p-ada-quill")] == ["save"]
    r = client.post("/api/network/person_save", json={"id": "p-ada-quill", "name": "Ada Lovequill", "notes": "x"})
    assert r.status_code == 200 and [e[0] for e in events(settings, schema, "p-ada-quill")] == ["save"]  # unchanged


def test_a_recommended_radar_person_is_still_a_radar_person(
    settings: Settings, schema: str, api: tuple[TestClient, Clock]
) -> None:
    """H-091: the ritual marks an existing person user_provided; the radar path reads the durable imported origin."""
    client, _ = api
    seed(settings, schema, [ADA, BEN])
    assert (
        client.post("/api/network/talented", json={"id": "p-ben-ortiz", "persons": [{"name": "Ada Quill"}]}).status_code
        == 200
    )
    assert record(settings, schema, "p-ada-quill")["provenance"] == "user_provided"  # the current record changed
    r = client.post("/api/network/person_save", json={"id": "p-ada-quill", "name": "Ada Lovequill"})
    assert r.status_code == 200
    rec = record(settings, schema, "p-ada-quill")
    assert rec["name_by_operator"] is True and "Ada Quill" in rec["aliases"]  # still the radar path
    # a person created in this app (the ritual's new person) is renamed plainly
    assert (
        client.post("/api/network/talented", json={"id": "p-ben-ortiz", "persons": [{"name": "Dev Rao"}]}).status_code
        == 200
    )
    renamed = client.post("/api/network/person_save", json={"id": "p-dev-rao", "name": "Devika Rao"})
    assert renamed.status_code == 200
    dev = record(settings, schema, "p-dev-rao")
    assert dev["name"] == "Devika Rao" and "name_by_operator" not in dev and "signal" not in dev


# ── decision (b): the ritual under concurrency ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("initial", ["absent", "empty_parent", "existing_parent"])
def test_two_introducers_recommend_one_person_concurrently(
    settings: Settings, schema: str, api: tuple[TestClient, Clock], initial: str
) -> None:
    client, _ = api
    zoe = {"id": "p-zoe-park", "name": "Zoe Park", "recommended": [], "startups": [], "created": "2026-09-14",
           "provenance": "user_provided"}  # fmt: skip
    cleo = {"id": "p-cleo-vance", "name": "Cleo Vance", "provenance": "radar_detected", "why_interesting": "imported"}
    if initial == "empty_parent":
        cleo["introduced_by"] = ""
    elif initial == "existing_parent":
        cleo["introduced_by"] = "p-zoe-park"
    seed(settings, schema, [ADA, BEN, zoe, *([cleo] if initial != "absent" else [])])

    holder = connect(settings.db_url)
    result: dict[str, Any] = {}
    try:
        with holder.transaction():
            out = PeopleStore(holder, schema).talented(
                {"id": "p-ada-quill", "persons": [{"name": "Cleo Vance", "note": "Ada's note"}]}, T0
            )
            assert out == {"ok": True, "created": ["p-cleo-vance"]}

            def second() -> None:
                r = client.post("/api/network/talented", json={"id": "p-ben-ortiz", "persons": [
                    {"name": "Cleo Vance", "note": "Ben's note"}]})  # fmt: skip
                result["code"], result["body"] = r.status_code, r.json()

            thread = threading.Thread(target=second)
            thread.start()
            assert waiting_on_lock(settings, schema), "the second ritual did not wait for the first"
            assert thread.is_alive()
    finally:
        holder.close()
    thread.join(30)
    assert result == {"code": 200, "body": {"ok": True, "created": ["p-cleo-vance"]}}
    person = record(settings, schema, "p-cleo-vance")
    assert record(settings, schema, "p-ada-quill")["recommended"] == ["p-cleo-vance"]  # both recommendations
    assert record(settings, schema, "p-ben-ortiz")["recommended"] == ["p-cleo-vance"]
    assert q(settings, schema, "select count(*) from {s}.people where id = 'p-cleo-vance'")[0][0] == 1
    if initial == "existing_parent":  # an existing parent survives either write
        assert person["introduced_by"] == "p-zoe-park" and person["why_interesting"] == "imported"
        assert "discovery" not in person
    else:  # only the first fills the empty parent
        assert person["introduced_by"] == "p-ada-quill"
        assert person["discovery"] == "Recommended by Ada Quill ('3 most talented' ask)"
        assert person["why_interesting"] == "Ada's note"
    ben = events(settings, schema, "p-ben-ortiz")[-1][3]  # the second introducer's event keeps its note
    assert ben["named"] == ["p-cleo-vance"] and ben["notes"] == {"p-cleo-vance": "Ben's note"}
    assert ben["introductions_kept"] == {
        "p-cleo-vance": "p-zoe-park" if initial == "existing_parent" else "p-ada-quill"
    }


def test_a_retried_ritual_leaves_one_recommendation_per_introducer(
    settings: Settings, schema: str, api: tuple[TestClient, Clock]
) -> None:
    client, _ = api
    seed(settings, schema, [ADA, BEN])
    ada_ritual = {"id": "p-ada-quill", "persons": [{"name": "Cleo Vance", "note": "robotics"}, {"name": "Dev Rao"}]}
    ben_ritual = {"id": "p-ben-ortiz", "persons": [{"name": "Cleo Vance"}]}
    for body in (ada_ritual, ben_ritual, ada_ritual, ben_ritual):
        assert client.post("/api/network/talented", json=body).status_code == 200
    assert record(settings, schema, "p-ada-quill")["recommended"] == ["p-cleo-vance", "p-dev-rao"]
    assert record(settings, schema, "p-ben-ortiz")["recommended"] == ["p-cleo-vance"]
    assert record(settings, schema, "p-cleo-vance")["introduced_by"] == "p-ada-quill"
    assert q(settings, schema, "select count(*) from {s}.people")[0][0] == 4
    # the retries changed nothing on the named people (the introducer's last_interaction is already today)
    assert [e[0] for e in events(settings, schema, "p-cleo-vance")] == ["create"]
    assert [e[0] for e in events(settings, schema, "p-dev-rao")] == ["create"]


def test_one_ritual_keeps_the_order_it_named_new_people_in(
    settings: Settings, schema: str, api: tuple[TestClient, Clock]
) -> None:
    """Archive order first (created_at is seeded REVERSED), then new people by created_at: one request's new people
    keep the order the old file appended them in, not their id order. Equal created_at falls back to the id."""
    client, _ = api
    seed(settings, schema, [ADA, BEN])
    r = client.post("/api/network/talented", json={"id": "p-ben-ortiz", "persons": [{"name": "Zed Mor"},
                    {"name": "Amy Lund"}, {"name": "Max Ott"}]})  # fmt: skip
    assert r.json()["created"] == ["p-zed-mor", "p-amy-lund", "p-max-ott"]
    with transaction(settings.db_url) as conn:
        conn.execute(
            f"insert into {schema}.people (id, name, attrs, created_at) values ('p-tie-b', 'Tie B', %s, %s), "
            "('p-tie-a', 'Tie A', %s, %s)".encode(),
            (
                Jsonb({"record": {"id": "p-tie-b", "name": "Tie B"}}),
                T0 + timedelta(days=400),
                Jsonb({"record": {"id": "p-tie-a", "name": "Tie A"}}),
                T0 + timedelta(days=400),
            ),
        )
    with transaction(settings.db_url) as conn:
        order = [p["id"] for p in load_people(conn, schema)]
    assert order == ["p-ada-quill", "p-ben-ortiz", "p-zed-mor", "p-amy-lund", "p-max-ott", "p-tie-a", "p-tie-b"]
    listed = [p["id"] for p in client.get("/api/network/people").json()["people"]]
    # due first (the three SUGGESTED next actions have no date: due), then the stalest; ties keep that order
    assert listed == ["p-zed-mor", "p-amy-lund", "p-max-ott", "p-ada-quill", "p-tie-a", "p-tie-b", "p-ben-ortiz"]


# ── concurrent saves of one person ──────────────────────────────────────────────────────────────────────────────
def test_concurrent_saves_of_one_person_run_one_after_another(
    settings: Settings, schema: str, api: tuple[TestClient, Clock]
) -> None:
    client, _ = api
    seed(settings, schema, [ADA_NET])
    holder = connect(settings.db_url)
    result: dict[str, Any] = {}
    try:
        with holder.transaction():
            PeopleStore(holder, schema).save({"id": "p-ada-quill", "next_action": "first"}, T0)

            def second() -> None:
                r = client.post("/api/network/person_save", json={"id": "p-ada-quill", "notes": "second"})
                result["code"] = r.status_code

            thread = threading.Thread(target=second)
            thread.start()
            assert waiting_on_lock(settings, schema), "the second save did not wait"
            assert thread.is_alive()
    finally:
        holder.close()
    thread.join(30)
    assert result["code"] == 200
    rec = record(settings, schema, "p-ada-quill")
    assert rec["next_action"] == "first" and rec["notes"] == "second"  # no lost update
    assert [(e[0], e[2]) for e in events(settings, schema, "p-ada-quill")] == [
        ("save", {"next_action": "first"}), ("save", {"notes": "second"})]  # fmt: skip


# ── Conviction sees the edit ────────────────────────────────────────────────────────────────────────────────────
def test_an_attrs_record_edit_reaches_the_conviction_imq_inputs(
    settings: Settings, schema: str, api: tuple[TestClient, Clock]
) -> None:
    client, _ = api
    seed(settings, schema, [ADA_NET])
    entry = {"company": "Quill Labs", "status": "new", "archetype": 3, "earliness": "pre_company", "conflict": "none",
             "scores": {"founder": 25, "venture_scale": 19, "why_now": 15, "taste": 15, "insight": 10},
             "verified": {"founders": True, "traction": True, "funding": True}, "founders": [{"name": "Ada Quill"}],
             "imq_trigger": {"kind": "fundraising", "date": (T0 - timedelta(days=10)).date().isoformat(),
                             "url": "https://news.example.com/q", "fact": "raising a seed", "by": "operator"}}  # fmt: skip
    with transaction(settings.db_url) as conn:
        co = conn.execute(
            f"insert into {schema}.companies (name) values ('Quill Labs') returning id".encode()
        ).fetchone()
        assert co is not None
        conn.execute(
            f"insert into {schema}.conviction_entries (company_id, slug, status, verified, scores, legacy) "
            "values (%s, 'quill-labs', 'new', %s, %s, %s)".encode(),
            (co[0], Jsonb(entry["verified"]), Jsonb(entry["scores"]), Jsonb(entry)),
        )

    def state() -> str:
        signals = client.get("/api/conviction/pipeline").json()["signals"]
        return str(signals[0]["imq_eval"]["state"])

    assert state() == "NOT YET IMQ"  # gate C: the founder's identity is not resolved
    r = client.post("/api/network/person_save", json={"id": "p-ada-quill", "identity_status": "resolved"})
    assert r.status_code == 200
    with transaction(settings.db_url) as conn:
        people = load_inputs(conn, schema).imq.people
    assert people == [{**ADA_NET, "identity_status": "resolved"}]
    assert row(settings, schema, "p-ada-quill")["identity_status"] == "resolved"  # type: ignore[index]
    assert state() == "IMQ — QUALIFIED NOW"
    assert row(settings, schema, "p-ada-quill")["legacy"] == ADA_NET  # type: ignore[index]


# ── reads and the Watchlist ─────────────────────────────────────────────────────────────────────────────────────
def test_reads_never_write_and_the_watchlist_logs_with_the_berlin_date(
    settings: Settings, schema: str, api: tuple[TestClient, Clock]
) -> None:
    client, clock = api
    seed(settings, schema, [ADA, {**BEN, "watch": True, "notes": "met once"}])
    stamp = q(settings, schema, "select id, updated_at, attrs from {s}.people order by id")
    for path in ("people", "graph", "watchlist"):
        assert client.get(f"/api/network/{path}").status_code == 200
    assert q(settings, schema, "select id, updated_at, attrs from {s}.people order by id") == stamp
    assert [p["id"] for p in client.get("/api/network/watchlist").json()["people"]] == ["p-ben-ortiz"]
    clock.now = datetime(2026, 11, 11, 23, 30, tzinfo=UTC)  # 00:30 in Berlin: already the 12th
    assert client.post("/api/network/watch_log", json={"id": "p-ben-ortiz", "note": "new paper"}).json() == {"ok": True}
    rec = record(settings, schema, "p-ben-ortiz")
    assert rec["notes"] == "met once\n[2026-11-12 signal] new paper" and rec["last_checked"] == "2026-11-12"
    assert client.post("/api/network/watch_log", json={"id": "p-nobody", "note": "x"}).json() == {"ok": True}
    assert [e[1] for e in events(settings, schema)] == ["watch_log"]

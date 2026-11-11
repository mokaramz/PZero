"""Review 015 acceptance tests (Codex H-101) against the hosted project, in throw-away scratch schemas:

* every read route runs in a READ-ONLY transaction: a read that tried to write is refused by the server, and after
  every route has run over a fixture with more than 250 leads, nothing changed (no cleanup on read);
* the read order is the archived ``events.json`` order (not ``created_at``), then app-created rows by ``created_at``;
  ``attrs.record`` wins over ``legacy``;
* a year-less date keeps the year it was imported with (the persisted ``start_date``), while its wording stays;
* the request instant's Berlin date decides ``today``, also when UTC still has the previous date.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from projectzero.api.app import create_app
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.events import store
from projectzero.events.columns import event_columns, lead_columns
from projectzero.ops.db_check import _scratch_sql

pytestmark = pytest.mark.hosted
IMPORTED_AT = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)  # the import clock: August
GOOD = {"city": "Karlsruhe", "url": "https://hall.example.com/e", "organizer": "Example Founders Lab", "route": "api",
        "venue": "Hall A", "format": "in_person", "price": {"amount": 0},
        "description": "A hackathon for founders and engineers building robotics startups."}  # fmt: skip
TABLES = ("events", "event_leads", "documents", "legacy_documents", "people")


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


def client_at(settings: Settings, schema: str, instant: datetime) -> TestClient:
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    app.state.clock = lambda: instant
    return TestClient(app, base_url="http://127.0.0.1:8177")


def seed(
    settings: Settings,
    schema: str,
    events: list[dict[str, Any]],
    leads: list[dict[str, Any]],
    app_rows: Sequence[tuple[dict[str, Any], datetime]] = (),
) -> None:
    """As the importer writes them: the archived events.json, one row per record (``event_columns`` /
    ``lead_columns`` at the AUGUST import clock), ``legacy`` = the record; ``created_at`` deliberately REVERSED so the
    archive order must win. ``app_rows``: rows the app created (no archive entry, ``attrs.record``, no legacy)."""
    raw = json.dumps({"events": events, "leads": leads}).encode()
    today = IMPORTED_AT.date()
    with transaction(settings.db_url) as conn:
        conn.execute(
            f"insert into {schema}.legacy_documents (path, sha256, bytes, raw, parsed) values (%s, %s, %s, %s, %s)".encode(),
            ("events.json", hashlib.sha256(raw).hexdigest(), len(raw), raw, Jsonb(json.loads(raw))),
        )
        rows: list[tuple[dict[str, Any], dict[str, Any] | None, datetime]] = [
            (e, None, IMPORTED_AT + timedelta(minutes=len(events) - i)) for i, e in enumerate(events)
        ]
        rows += [(rec, rec, at) for rec, at in app_rows]
        for rec, current, created in rows:
            c = event_columns(rec["id"], rec, today=today).columns
            attrs = c["attrs"] | ({"record": current} if current else {})
            conn.execute(
                f"insert into {schema}.events (id, name, starts_at, ends_at, start_date, start_time, end_date, end_time,"
                " city, country, url, status, lat, lng, attrs, legacy, created_at) values"
                " (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)".encode(),
                (rec["id"], c["name"], c["starts_at"], c["ends_at"], c["start_date"], c["start_time"], c["end_date"],
                 c["end_time"], c["city"], c["country"], c["url"], c["status"], c["lat"], c["lng"], Jsonb(attrs),
                 None if current else Jsonb(rec), created),
            )  # fmt: skip
        for i, lead in enumerate(leads):
            c = lead_columns(lead, today=today).columns
            conn.execute(
                f"insert into {schema}.event_leads (id, title, source, url, city, type, lead_date, date_raw, confidence,"
                " detected_on, decision, note, attrs, legacy, created_at) values"
                " (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)".encode(),
                (lead["id"], c["title"], c["source"], c["url"], c["city"], c["type"], c["lead_date"], c["date_raw"],
                 c["confidence"], c["detected_on"], c["decision"], c["note"], Jsonb(c["attrs"]), Jsonb(lead),
                 IMPORTED_AT - timedelta(minutes=i)),
            )  # fmt: skip
        conn.execute(
            f"insert into {schema}.documents (key, body) values ('event_health.json', %s)".encode(),
            (Jsonb({"scan_time": "2026-08-19 08:00", "totals": {}, "sources": [{"name": "A", "kind": "luma"}]}),),
        )


def fingerprint(settings: Settings, schema: str) -> dict[str, Any]:
    out = {}
    with transaction(settings.db_url) as conn:
        for t in TABLES:
            out[t] = conn.execute(
                f"select count(*), md5(coalesce(string_agg(to_jsonb(x)::text, '|' order by to_jsonb(x)::text), ''))"
                f" from {schema}.{t} x".encode()
            ).fetchone()
    return out


ROUTES = ("/api/events", "/api/events/health", "/api/events/suggest?name=Robotics%20hackathon&type=hackathon",
          "/api/events/wsig?days=30", "/api/events/weekend?start=2026-11-14&end=2026-11-15")  # fmt: skip


def test_every_read_route_leaves_the_data_unchanged_even_with_more_than_250_leads(
    settings: Settings, schema: str
) -> None:
    leads = [{"id": f"evlead-{i:03d}", "title": f"Lead {i}", "decision": ("new", "dismissed", "converted")[i % 3],
              "date": "2026-12-01", "detected_on": "2026-08-01"} for i in range(300)]  # fmt: skip
    seed(settings, schema, [{"id": "ev-a", "name": "Robotics Hackathon", "start": "2026-11-14", **GOOD}], leads)
    before = fingerprint(settings, schema)
    with client_at(settings, schema, datetime(2026, 11, 11, 11, 0, tzinfo=UTC)) as client:
        for route in ROUTES:
            assert client.get(route).status_code == 200, route
        body = client.get("/api/events").json()
    assert [x["id"] for x in body["leads"]] == [f"evlead-{i:03d}" for i in range(0, 300, 3)]  # 100 new, stored order
    assert fingerprint(settings, schema) == before  # nothing written, nothing cleaned up (the old cap is write-side)


def test_a_read_that_tries_to_write_is_refused_by_the_server(
    settings: Settings, schema: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(settings, schema, [{"id": "ev-a", "name": "Robotics Hackathon", "start": "2026-11-14", **GOOD}], [])
    before = fingerprint(settings, schema)
    real_load = store.load

    def writing_load(
        conn: psycopg.Connection[Any], schema_: str, today: date, *, people: bool = True, records: bool = True
    ) -> Any:
        conn.execute(f"delete from {schema_}.event_leads".encode())  # an accidental cleanup on read
        return real_load(conn, schema_, today, people=people, records=records)

    monkeypatch.setattr(store, "load", writing_load)
    with client_at(settings, schema, datetime(2026, 11, 11, 11, 0, tzinfo=UTC)) as client:
        for route in ROUTES:
            if "suggest" in route:
                continue  # suggest reads nothing
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                client.get(route)
    assert fingerprint(settings, schema) == before


def test_archive_order_then_app_rows_and_the_current_record_wins(settings: Settings, schema: str) -> None:
    imported = [
        {"id": "ev-z", "name": "Zeta Demo Day", "start": "2026-11-20", **GOOD},
        {"id": "ev-a", "name": "Alpha Demo Day", "start": "2026-11-20", **GOOD},  # the same sort key: stored order
        {"id": "ev-m", "name": "Mu Demo Day", "start": "2026-11-20", **GOOD},
    ]
    created = [
        ({"id": "ev-new-2", "name": "Second New Demo Day", "start": "2026-11-20", **GOOD}, datetime(2026, 11, 2, tzinfo=UTC)),
        ({"id": "ev-new-1", "name": "First New Demo Day", "start": "2026-11-20", **GOOD}, datetime(2026, 11, 1, tzinfo=UTC)),
    ]  # fmt: skip
    seed(settings, schema, imported, [], created)
    with transaction(settings.db_url) as conn:  # an application write: attrs.record replaces the imported record
        conn.execute(
            f"update {schema}.events set attrs = attrs || %s where id = 'ev-m'".encode(),
            (Jsonb({"record": {**imported[2], "name": "Mu Demo Day (renamed)"}}),),
        )
    with client_at(settings, schema, datetime(2026, 11, 11, 11, 0, tzinfo=UTC)) as client:
        evs = client.get("/api/events").json()["events"]
    assert [e["id"] for e in evs] == ["ev-z", "ev-a", "ev-m", "ev-new-1", "ev-new-2"]
    assert evs[2]["name"] == "Mu Demo Day (renamed)"


def test_a_yearless_date_keeps_its_imported_year(settings: Settings, schema: str) -> None:
    """Imported in August: "Sept 20" -> 2026-09-20. Read in October, the old page would have said 2027-09-20."""
    seed(settings, schema, [{"id": "ev-free", "name": "Founder Mixer", "start": "Sept 20", **GOOD}], [])
    with client_at(settings, schema, datetime(2026, 10, 10, 10, 0, tzinfo=UTC)) as client:
        (e,) = client.get("/api/events").json()["events"]
        ranked = client.get("/api/events/wsig?days=400").json()["ranked"]
    assert (e["start"], e["when"]["start_date"], e["when"]["group"], e["past"]) == (
        "Sept 20",
        "2026-09-20",
        "past",
        True,
    )
    assert ranked == []  # a past event is not recommended (it would have been, a year later, by the old page)


def test_a_feb_29_stored_as_no_date_stays_undated_in_a_leap_year(settings: Settings, schema: str) -> None:
    """Imported in August 2026, "Feb 29" means 2027-02-29: no date, stored as NULL. Read in January 2028 (a leap year)
    the old page would have dated it 2028-02-29; the stored result decides (Codex H-103)."""
    seed(settings, schema, [{"id": "ev-leap", "name": "Leap Founder Night", "start": "Feb 29", **GOOD,
                             "status": "planned"}], [])  # fmt: skip
    with client_at(settings, schema, datetime(2028, 1, 10, 10, 0, tzinfo=UTC)) as client:
        (e,) = client.get("/api/events").json()["events"]
        ranked = client.get("/api/events/wsig?days=60").json()["ranked"]
        missions = client.get("/api/events/weekend?start=2028-02-28&end=2028-02-29").json()["missions"]
    assert (e["start"], e["when"]["group"], e["eligibility"]["label"]) == ("Feb 29", "undated", "NO DATE")
    assert ranked == [] and missions == []


@pytest.mark.parametrize(
    ("instant", "today"),
    [(datetime(2026, 11, 13, 22, 59, 59, tzinfo=UTC), "2026-11-13"), (datetime(2026, 11, 13, 23, 0, tzinfo=UTC), "2026-11-14")],
)  # fmt: skip
def test_the_berlin_date_of_the_instant_is_today(
    settings: Settings, schema: str, instant: datetime, today: str
) -> None:
    seed(settings, schema, [{"id": "ev-a", "name": "Robotics Hackathon", "start": "2026-11-14", **GOOD}], [])
    with client_at(settings, schema, instant) as client:
        body = client.get("/api/events").json()
    assert body["today"] == today and body["events"][0]["when"]["days_until"] == (1 if today == "2026-11-13" else 0)

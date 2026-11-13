"""Review 032a acceptance tests against the hosted project, in throw-away scratch schemas, with invented names only.

* every golden world, imported by the PRODUCTION importer and served by ``GET /api/system_health`` and
  ``GET /api/system_health_overview``, answers what the OLD reads answered, after the declared normalisation (the
  ONE ``parity_health.normalise``); both GETs leave every table unchanged (whole rows compared);
* the imported job state and run history read back exactly from ``detail`` (the old records whole);
* a new inference-gateway ledger row shows in today's spend and in the overview's models;
* both reads run at REPEATABLE READ, READ ONLY.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.types.json import Jsonb

from projectzero.api.app import create_app
from projectzero.core.config import Settings
from projectzero.core.db import connect, snapshot_transaction, transaction
from projectzero.core.inference import config as icfg
from projectzero.health import inputs as health_inputs
from projectzero.ops.parity_founder_calls import utc_instant
from projectzero.ops.parity_health import KEY_ENV, normalise, read_golden
from projectzero.ops.parity_ranking import diff, js
from projectzero.ops.parity_validation import _fingerprint
from projectzero.ops.scratch_import import import_world

pytestmark = pytest.mark.hosted
ROUTES = (("system", "/api/system_health"), ("overview", "/api/system_health_overview"))


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture(scope="module")
def golden() -> dict[str, Any]:
    return read_golden()


@pytest.fixture
def world(settings: Settings, golden: dict[str, Any]) -> Iterator[Callable[[str], str]]:
    made: list[str] = []

    def make(name: str) -> str:
        made.append(import_world(settings.db_url, golden["worlds"][name]["docs"]))
        return made[-1]

    yield make
    with connect(settings.db_url, autocommit=True) as admin:
        for schema in made:
            admin.execute(sql.SQL("drop schema if exists {} cascade").format(sql.Identifier(schema)))


def _env(monkeypatch: pytest.MonkeyPatch, paid: bool, key: bool) -> None:
    """The world's paid switch and key presence, as the new side reads them (never a real key: a fixed marker)."""
    for name in icfg.KEY_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(icfg.PAID_ENV, "on" if paid else "off")
    if key:
        monkeypatch.setenv(KEY_ENV, "invented-test-marker")


def _get(settings: Settings, schema: str, clock: str) -> dict[str, Any]:
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    app.state.clock = lambda: utc_instant(clock)
    got: dict[str, Any] = {}
    with TestClient(app, base_url="http://127.0.0.1:8177") as client:
        for route, path in ROUTES:
            r = client.get(path)
            assert r.status_code == 200, r.text
            got[route] = {"ok": js(r.json())}
    return got


@pytest.mark.parametrize("name", sorted(read_golden()["worlds"]))
def test_an_imported_world_answers_what_the_old_reads_answered_and_writes_nothing(
    settings: Settings, golden: dict[str, Any], world: Callable[[str], str], name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = golden["worlds"][name]
    _env(monkeypatch, w["paid"], w["key"])
    schema = world(name)
    with transaction(settings.db_url) as conn:
        before = _fingerprint(conn, schema)
    got = _get(settings, schema, w["clock"])
    with transaction(settings.db_url) as conn:
        after = _fingerprint(conn, schema)
        q = sql.SQL("select event_id from {}.news_events").format(sql.Identifier(schema))
        stored = [r[0] for r in conn.execute(q).fetchall()]
    want = js(normalise(w["expected"], real=True))  # 032c: the route serves the real runner (per-job switch, its lock)
    # the News import seeds the old app's shipped curated case(s) (review 028), which the old app wrote at its first
    # News read: a fresh world without them counts them on the new side only. The real snapshot already holds them.
    world_events = ((w["docs"].get("news/events.json") or {}).get("events")) or {}
    seeded = [e for e in stored if e not in world_events]
    assert all(e.startswith("nw-case-") for e in seeded), seeded
    if isinstance(want["system"].get("ok", {}).get("news"), dict) and "events" in want["system"]["ok"]["news"]:
        want["system"]["ok"]["news"]["events"] += len(seeded)
    # declared (l), Codex H-309: the overview's inbox counts are the Deal Flow inbox's (its own route, same data): a
    # world whose import absorbs records counts each survivor once, where the old inbox.json counted every record
    want["overview"]["ok"]["pipeline"]["inbox"] = _deal_flow_counts(settings, schema, w["clock"])
    for route, _path in ROUTES:
        assert diff(want[route], got[route]) == [], route
        assert json.dumps(want[route], ensure_ascii=False) == json.dumps(got[route], ensure_ascii=False), route
    assert sorted(t for t in before if before[t] != after.get(t)) == []


def _deal_flow_counts(settings: Settings, schema: str, clock: str) -> dict[str, int]:
    from collections import Counter

    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    app.state.clock = lambda: utc_instant(clock)
    with TestClient(app, base_url="http://127.0.0.1:8177") as client:
        inbox = client.get("/api/deal-flow/inbox").json()
    return dict(Counter(str(c.get("decision") or "") for c in inbox["candidates"]))


def test_the_imported_jobs_and_runs_read_back_exactly(
    settings: Settings, golden: dict[str, Any], world: Callable[[str], str]
) -> None:
    w = golden["worlds"]["main"]
    schema = world("main")
    with snapshot_transaction(settings.db_url) as conn:
        inputs = health_inputs.load(conn, schema, datetime.fromisoformat(w["clock"]))
    jobs = w["docs"]["schedule/jobs.json"]
    assert inputs.job_state == jobs  # every old record whole
    lines = [json.loads(x) for x in w["docs"]["schedule/runs.jsonl"].splitlines() if x.strip()]
    assert inputs.runs == [x for x in lines if isinstance(x, dict)]  # in line order


def test_a_new_gateway_ledger_row_shows_in_todays_spend_and_the_models(
    settings: Settings, golden: dict[str, Any], world: Callable[[str], str], monkeypatch: pytest.MonkeyPatch
) -> None:
    w = golden["worlds"]["healthy"]
    _env(monkeypatch, w["paid"], w["key"])
    schema = world("healthy")
    before = _get(settings, schema, w["clock"])
    at = utc_instant(w["clock"]).replace(minute=5)  # 09:05 Berlin on the world's day
    with transaction(settings.db_url) as conn:
        conn.execute(
            sql.SQL("insert into {}.model_ledger (at, purpose, provider, model, usd, tokens_in, tokens_out, outcome, "
                    "detail) values (%s, 'news_card', 'deepinfra', 'invented-model', 0.125, 100, 50, 'ok', %s)")
            .format(sql.Identifier(schema)),
            (at, Jsonb({"role": "CHEAP", "call_id": "ic-invented-1", "attempt": 1})),
        )  # fmt: skip
    after = _get(settings, schema, w["clock"])
    spend_before, spend_after = before["system"]["ok"]["spend"], after["system"]["ok"]["spend"]
    for window in ("day", "week", "month"):
        assert round(spend_after[window] - spend_before[window], 6) == 0.125, window
    rows = after["overview"]["ok"]["models"]["rows"]
    assert any("invented-model" in json.dumps(r) for r in rows)
    assert len(rows) >= len(before["overview"]["ok"]["models"]["rows"])


def test_both_reads_run_at_repeatable_read_read_only(settings: Settings, world: Callable[[str], str]) -> None:
    schema = world("empty")
    with snapshot_transaction(settings.db_url) as conn:
        level = conn.execute(b"show transaction_isolation").fetchone()
        ro = conn.execute(b"show transaction_read_only").fetchone()
        health_inputs.load(conn, schema, datetime(2026, 11, 13, 9))
    assert level == ("repeatable read",) and ro == ("on",)


def test_the_overview_inbox_counts_what_the_deal_flow_inbox_lists(
    settings: Settings, golden: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex H-309: the "You: review" node links to the Deal Flow inbox, so its counts by decision are that inbox's:
    an absorbed record counts once (through its survivor) and a Scout-only candidate the merge brought in counts too,
    where the old ``inbox.json`` count (the legacy reconstruction) would say otherwise."""
    from collections import Counter

    w = golden["worlds"]["healthy"]
    _env(monkeypatch, w["paid"], w["key"])
    docs = copy.deepcopy(w["docs"])
    pair = {"description": "Invented twin record.", "discovery_tier": "grant", "source_id": "s-founder-wire",
            "source": "Invented Founder Wire", "entity_ids": {"duns": "123456789"}}  # fmt: skip
    docs["inbox.json"]["candidates"] += [
        {**pair, "id": "c-twin-a", "name": "Invented Twinpeak Labs", "decision": "watch", "first_seen": "2026-10-01"},
        {**pair, "id": "c-twin-b", "name": "Invented Twinpeak Labs", "decision": "watch", "first_seen": "2026-10-02"},
    ]
    schema = import_world(settings.db_url, docs)
    try:
        with transaction(settings.db_url) as conn:
            q = sql.SQL("select count(*) from {}.candidate_aliases where reason = 'merge'").format(
                sql.Identifier(schema)
            )
            merged = conn.execute(q).fetchone()
            assert merged is not None and merged[0] >= 1  # the importer absorbed one twin into the other
            conn.execute(
                sql.SQL("insert into {}.candidates (id, name, status, origins, first_seen_at) values "
                        "('c-scout-0001', 'Invented Tern Robotics', 'new', '{{legacy_scout00}}', %s)")
                .format(sql.Identifier(schema)), (datetime(2026, 11, 12, 8),)
            )  # fmt: skip
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        app.state.clock = lambda: utc_instant(w["clock"])
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            overview = client.get("/api/system_health_overview").json()
            inbox = client.get("/api/deal-flow/inbox").json()
        listed = dict(Counter(str(c.get("decision") or "") for c in inbox["candidates"]))
        assert overview["pipeline"]["inbox"] == listed
        legacy = Counter(str(c.get("decision") or "") for c in docs["inbox.json"]["candidates"])
        assert listed["watch"] == legacy["watch"] - 1 and listed.get("new", 0) == legacy.get("new", 0) + 1
    finally:
        with connect(settings.db_url, autocommit=True) as admin:
            admin.execute(sql.SQL("drop schema if exists {} cascade").format(sql.Identifier(schema)))

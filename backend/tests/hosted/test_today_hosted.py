"""Review 030a acceptance tests (plan revision 2, Codex H-287 / H-289) against the hosted project, in throw-away scratch
schemas, with invented names only.

* the golden worlds the importer accepts (``main``, ``expired``, ``quiet``), imported by the PRODUCTION importer and
  served by ``GET /api/today``, answer exactly what the OLD code answered (the oracle's golden), served and ``uncut``,
  with only the declared normalisation; the GET leaves every table unchanged (whole rows compared);
* the inbox order decides the portfolio card's names (``main``: "Invented Rookwood" is first in the inbox, after
  "Invented Quillon" by id);
* ONE snapshot (revision 2): an edit committed between two of the view's reads (a Conviction company dropped AND a
  candidate rejected) leaves the in-flight answer on the earlier state throughout, and a fresh GET sees both; the same
  edit under plain READ COMMITTED mixes the two states (the regression bites);
* a candidate the new intake created has no route (decision f): it is live, but no triage count or card moves.
"""

from __future__ import annotations

import copy
import json
import secrets
import tempfile
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from projectzero.api.app import create_app
from projectzero.api.routers import today as today_route
from projectzero.conviction.store import ConvictionStore
from projectzero.core.config import Settings
from projectzero.core.db import connect, read_only_transaction, snapshot_transaction, transaction
from projectzero.ops.db_check import _scratch_sql
from projectzero.ops.legacy.apply import apply_plan
from projectzero.ops.legacy.plan import build_plan
from projectzero.ops.legacy.source import LegacySnapshot
from projectzero.ops.parity_founder_calls import utc_instant
from projectzero.ops.parity_ranking import diff, js
from projectzero.ops.parity_today import UNCUT, files_of, normalise_new, normalise_old, read_golden
from projectzero.ops.parity_validation import _fingerprint
from projectzero.today import core as today_core
from projectzero.today import inputs as today_inputs

pytestmark = pytest.mark.hosted
IMPORTABLE = ("main", "expired", "quiet")  # the other worlds hold no people / events file, or a broken pipeline
# the files the importer requires that Today never reads (empty collections, as a fresh install had them)
FILLER: dict[str, Any] = {
    "sources.json": {"sources": []}, "scout_intake.json": {"items": {}}, "native_scout.json": {"signals": {}},
    "committee.json": {"second_pass": {}}, "bridge_jobs.json": {"jobs": {}}, "schedule/jobs.json": {},
    "inference_ledger.jsonl": "", "schedule/runs.jsonl": "",
}  # fmt: skip
DROPPED = "Invented Bramble Robotics"  # the first CONTACT_FOUNDER card of ``main``
REJECTED = "c-205"  # "Invented Rookwood": first in the inbox, first on the triage portfolio card of ``main``


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture(scope="module")
def golden() -> dict[str, Any]:
    return read_golden()


def _import(settings: Settings, docs: dict[str, Any]) -> str:
    """The world's documents as a legacy data folder, through the production importer, into a new scratch schema."""
    name = f"pz_itest_{secrets.token_hex(4)}"
    with tempfile.TemporaryDirectory(prefix="pz-today-world-") as tmp:
        for rel, raw in files_of({**{k: v for k, v in FILLER.items() if k not in docs}, **docs}).items():
            target = Path(tmp) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        snapshot = LegacySnapshot.capture(Path(tmp))
    with connect(settings.db_url, autocommit=True) as admin:
        admin.execute(_scratch_sql(name).encode())
    conn = connect(settings.db_url)
    try:
        applied = apply_plan(build_plan(snapshot), schema=name, conn=conn)
    finally:
        conn.close()
    assert applied.get("applied"), applied
    return name


@pytest.fixture
def world(settings: Settings, golden: dict[str, Any]) -> Iterator[Callable[[str], str]]:
    made: list[str] = []

    def make(name: str) -> str:
        made.append(_import(settings, golden["worlds"][name]["docs"]))
        return made[-1]

    yield make
    with connect(settings.db_url, autocommit=True) as admin:
        for schema in made:
            admin.execute(sql.SQL("drop schema if exists {} cascade").format(sql.Identifier(schema)))


def _client(settings: Settings, schema: str, clock: str) -> TestClient:
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    app.state.clock = lambda: utc_instant(clock)
    return TestClient(app, base_url="http://127.0.0.1:8177")


def _get(settings: Settings, schema: str, clock: str, hook: Callable[[], None] | None = None) -> dict[str, Any]:
    with _client(settings, schema, clock) as client:
        if hook is not None:
            client.app.state.today_after_first_read = hook  # type: ignore[attr-defined]
        r = client.get("/api/today")
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def _compare(expected: dict[str, Any], got: dict[str, Any], docs: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    old = normalise_old({"ok": expected}, problems)
    new = normalise_new({"ok": got}, docs, problems)
    problems += diff(js(old), js(new))
    if json.dumps(old, ensure_ascii=False) != json.dumps(new, ensure_ascii=False):
        problems.append("the serialized answer differs (key order)")
    return problems


@pytest.mark.parametrize("name", IMPORTABLE)
def test_an_imported_world_answers_what_the_old_code_answered_and_writes_nothing(
    settings: Settings, golden: dict[str, Any], world: Callable[[str], str], name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = golden["worlds"][name]
    schema = world(name)
    with transaction(settings.db_url) as conn:
        before = _fingerprint(conn, schema)
    served = _get(settings, schema, w["clock"])
    monkeypatch.setattr(today_core, "MAX_ACTIONS", UNCUT)  # every ranked action, as the oracle's ``uncut``
    uncut = _get(settings, schema, w["clock"])
    with transaction(settings.db_url) as conn:
        after = _fingerprint(conn, schema)
    assert _compare(w["expected"]["ok"], served, w["docs"]) == []
    assert _compare(w["expected"]["uncut"]["ok"], uncut, w["docs"]) == []
    assert sorted(t for t in before if before[t] != after.get(t)) == []


def test_the_inbox_order_decides_the_portfolio_card(
    settings: Settings, golden: dict[str, Any], world: Callable[[str], str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(today_core, "MAX_ACTIONS", UNCUT)
    body = _get(settings, world("main"), golden["worlds"]["main"]["clock"])
    card = next(a for a in body["actions"] if a["title"].endswith("touch the Project A portfolio"))
    assert card["subject"] == "Invented Rookwood, Invented Quillon"  # inbox order; by id Quillon (c-101) is first


def _shape(body: dict[str, Any]) -> tuple[bool, list[str]]:
    """(the dropped company's CONTACT_FOUNDER card is there, the triage portfolio card's names)."""
    contact = any(a["type"] == "CONTACT_FOUNDER" and a["subject"] == DROPPED for a in body["actions"])
    card = next((a for a in body["actions"] if a["title"].endswith("touch the Project A portfolio")), None)
    return contact, [] if card is None else card["subject"].split(", ")


def _edit(settings: Settings, schema: str, clock: str) -> Callable[[], None]:
    """Another connection commits both edits: one the pipeline read already saw (the Conviction status), and one only
    the later reads see (the candidate status behind the triage card and the live ids)."""
    done: list[bool] = []

    def hook() -> None:
        if done:
            return
        done.append(True)
        with transaction(settings.db_url) as conn:
            store = ConvictionStore(conn, schema)
            slug = conn.execute(
                sql.SQL("select e.slug from {}.conviction_entries e join {}.companies c on c.id = e.company_id "
                        "where c.name = %s").format(sql.Identifier(schema), sql.Identifier(schema)), (DROPPED,)
            ).fetchone()  # fmt: skip
            assert slug is not None
            store.set_status({"slug": slug[0], "status": "dropped"}, datetime.fromisoformat(clock))
            conn.execute(
                sql.SQL("update {}.candidates set status = 'rejected' where id = %s").format(sql.Identifier(schema)),
                (REJECTED,),
            )

    return hook


def test_an_edit_committed_between_two_reads_is_not_mixed_into_the_view(
    settings: Settings, golden: dict[str, Any], world: Callable[[str], str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(today_core, "MAX_ACTIONS", UNCUT)
    clock = golden["worlds"]["main"]["clock"]
    schema = world("main")
    before = _get(settings, schema, clock)
    assert _shape(before) == (True, ["Invented Rookwood", "Invented Quillon"])
    in_flight = _get(settings, schema, clock, hook=_edit(settings, schema, clock))
    assert in_flight == before  # the earlier snapshot throughout: the card, the triage and the statuses agree
    fresh = _get(settings, schema, clock)
    assert _shape(fresh) == (False, ["Invented Quillon"])  # a fresh GET sees both edits


def test_without_the_snapshot_the_same_edit_would_mix_two_states(
    settings: Settings, golden: dict[str, Any], world: Callable[[str], str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control: the route on plain READ COMMITTED (READ ONLY) answers the old Conviction state with the new triage
    state, which is what revision 2 rules out."""
    monkeypatch.setattr(today_core, "MAX_ACTIONS", UNCUT)
    monkeypatch.setattr(today_route, "snapshot_transaction", read_only_transaction)
    clock = golden["worlds"]["main"]["clock"]
    schema = world("main")
    mixed = _get(settings, schema, clock, hook=_edit(settings, schema, clock))
    assert _shape(mixed) == (True, ["Invented Quillon"])


def test_the_route_reads_at_repeatable_read_read_only(settings: Settings, world: Callable[[str], str]) -> None:
    schema = world("quiet")
    with snapshot_transaction(settings.db_url) as conn:
        level = conn.execute(b"show transaction_isolation").fetchone()
        ro = conn.execute(b"show transaction_read_only").fetchone()
        today_inputs.load(conn, schema, datetime(2026, 11, 13, 9))
    assert level == ("repeatable read",) and ro == ("on",)


def test_a_new_intake_candidate_has_no_route(
    settings: Settings, golden: dict[str, Any], world: Callable[[str], str]
) -> None:
    clock = golden["worlds"]["main"]["clock"]
    schema = world("main")
    before = _get(settings, schema, clock)
    with transaction(settings.db_url) as conn:
        conn.execute(
            sql.SQL("insert into {}.candidates (id, name, status, origins, first_seen_at) "
                    "values ('c-intake-0001', 'Invented Plover Systems', 'new', '{{manual}}', %s)")
            .format(sql.Identifier(schema)), (datetime(2026, 11, 12, 8, tzinfo=UTC),)
        )  # fmt: skip
    with snapshot_transaction(settings.db_url) as conn:
        inputs = today_inputs.load(conn, schema, datetime.fromisoformat(clock))
    assert "c-intake-0001" in inputs.live_ids and "c-intake-0001" not in inputs.queue_routing["routes"]
    after = _get(settings, schema, clock)
    assert after["triage"] == before["triage"]
    assert copy.deepcopy(after["actions"]) == before["actions"]
    assert all("Invented Plover Systems" not in str(a) for a in after["actions"])


def test_one_get_reads_the_routing_table_once(
    settings: Settings, golden: dict[str, Any], world: Callable[[str], str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex H-292: the triage read's decoded routes feed the compressor too; the answer is unchanged (the parity test
    above compares it with the oracle, triage proposals and compressor summary included)."""
    import psycopg

    w = golden["worlds"]["main"]
    schema = world("main")
    seen: list[str] = []
    execute = psycopg.Cursor.execute

    def counting(self: Any, query: Any, *a: Any, **kw: Any) -> Any:
        text = query.as_string(self) if isinstance(query, sql.Composable) else str(query)
        if "candidate_routing" in text:
            seen.append(text)
        return execute(self, query, *a, **kw)

    monkeypatch.setattr(psycopg.Cursor, "execute", counting)
    body = _get(settings, schema, w["clock"])
    monkeypatch.setattr(psycopg.Cursor, "execute", execute)
    assert len(seen) == 1, seen
    assert _compare(w["expected"]["ok"], body, w["docs"]) == []
    assert body["triage"]["total"] == w["expected"]["ok"]["triage"]["total"]  # the compressor summary

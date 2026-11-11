"""Live intake against the hosted Supabase project, in a throw-away scratch schema (``scripts/db.ps1 itest``).

Each test gets a fresh schema with every migration applied; it is dropped afterwards. Production tables are never
touched. Skipped unless SUPABASE_DB_URL is configured.
"""

from __future__ import annotations

import copy
import itertools
import json
import secrets
import threading
from collections.abc import Iterator
from typing import Any

import pytest

from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.core.paths import REPO_ROOT
from projectzero.dealflow.intake.contract import Origin
from projectzero.dealflow.intake.postgres import PostgresIntake
from projectzero.dealflow.intake.service import IntakeResult, IntakeService, TrustedBatch
from projectzero.ops.db_check import _scratch_sql

pytestmark = pytest.mark.hosted


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


def submit(settings: Settings, schema: str, payload: dict[str, Any], by: str = "grok") -> IntakeResult:
    with transaction(settings.db_url) as conn:
        store = PostgresIntake(conn, schema)
        return IntakeService(store, resolver=store).submit_external(payload, submitted_by=by)


def query(settings: Settings, sql: str, *params: Any) -> list[tuple[Any, ...]]:
    with connect(settings.db_url, autocommit=True) as conn:
        return conn.execute(sql.encode() if not params else sql, params or None).fetchall()  # type: ignore[arg-type]


def company(name: str, **extra: Any) -> dict[str, Any]:
    return {"kind": "company", "name": name, "key_fact": f"{name} raised a pre-seed round",
            "evidence": [{"url": f"https://news.example.com/{name.lower().replace(' ', '-')}"}]} | extra  # fmt: skip


def delivery(*entities: dict[str, Any], origin: str = "grok", ref: str | None = None) -> dict[str, Any]:
    return {"contract_version": "1.0", "origin": origin, "external_ref": ref or secrets.token_hex(3),
            "submitted_at": "2026-11-11T09:00:00+01:00", "entities": list(entities)}  # fmt: skip


def test_grok_cycle_008_creates_candidates_once(settings: Settings, schema: str) -> None:
    sample = json.loads((REPO_ROOT / "docs/team/samples/grok_cycle_sample.json").read_text(encoding="utf-8"))
    first = submit(settings, schema, sample)
    assert first.outcome == "accepted" and len(first.resolution) == 13
    assert {r["result"] for r in first.resolution} == {"created"}
    assert query(settings, f"select count(*) from {schema}.candidates")[0][0] == 13
    assert query(settings, f"select count(*) from {schema}.observations")[0][0] == 13
    detail = query(settings, f"select outcome_detail from {schema}.intake_submissions")[0][0]
    assert len(detail["resolution"]) == 13

    again = submit(settings, schema, copy.deepcopy(sample))
    assert again.outcome == "duplicate" and again.resolution == ()
    assert query(settings, f"select count(*) from {schema}.candidates")[0][0] == 13


def test_re_report_with_the_same_external_id_attaches(settings: Settings, schema: str) -> None:
    submit(settings, schema, delivery(company("Freda", external_id="scout:freda")))
    second = submit(
        settings, schema, delivery(company("Freda AB", external_id="scout:freda", key_unknown="Who led the round?"))
    )
    (r,) = second.resolution
    assert r["result"] == "re_reported" and r["company_decision"] == "strong_identifier"
    rows = query(settings, f"select count(*), max(key_unknown) from {schema}.candidates")
    assert rows[0] == (1, "Who led the round?")  # filled a gap, no second candidate
    assert query(settings, f"select count(*) from {schema}.observations")[0][0] == 2


def test_same_name_from_another_origin_joins_and_same_origin_suggests(settings: Settings, schema: str) -> None:
    submit(settings, schema, delivery(company("Kontext")))  # grok (scout family)
    manual = submit(settings, schema, delivery(company("Kontext GmbH"), origin="manual"), by="operator")
    assert manual.resolution[0]["company_decision"] == "same_name_cross_origin"
    assert manual.resolution[0]["result"] == "re_reported"
    origins = query(settings, f"select origins from {schema}.candidates")
    assert origins == [(["grok", "manual"],)]

    same_origin = submit(settings, schema, delivery(company("Twin Labs")))
    other = submit(settings, schema, delivery(company("Twin Labs")))  # grok again: ambiguous, never joined
    assert same_origin.resolution[0]["candidate_id"] != other.resolution[0]["candidate_id"]
    suggestions = query(settings, f"select count(*) from {schema}.candidate_events where action = 'merge_suggested'")
    assert suggestions[0][0] == 2  # one on each side


def test_conflicting_strong_ids_leave_the_record_unresolved(settings: Settings, schema: str) -> None:
    submit(settings, schema, delivery(company("Alpha", website="https://alpha-robotics.com")))
    submit(settings, schema, delivery(company("Beta", registry_ids={"duns": "123456789"})))
    mixed = submit(
        settings,
        schema,
        delivery(company("Gamma", website="https://alpha-robotics.com", registry_ids={"duns": "123456789"})),
    )
    (r,) = mixed.resolution
    assert r["company_id"] is None and r["company_decision"] == "identity_conflict"
    attrs = query(settings, f"select attrs->>'identity' from {schema}.candidates where id = %s", r["candidate_id"])
    assert attrs == [("identity_conflict",)]
    assert query(settings, f"select count(*) from {schema}.companies")[0][0] == 2  # neither owner changed hands


def test_intake_never_changes_an_existing_status(settings: Settings, schema: str) -> None:
    first = submit(settings, schema, delivery(company("Closed Co", external_id="x:closed")))
    candidate = first.resolution[0]["candidate_id"]
    with connect(settings.db_url, autocommit=True) as conn:
        conn.execute(f"update {schema}.candidates set status = 'rejected' where id = %s".encode(), (candidate,))
    again = submit(settings, schema, delivery(company("Closed Co", external_id="x:closed")))
    assert again.resolution[0]["result"] == "re_reported_closed"
    assert query(settings, f"select status from {schema}.candidates") == [("rejected",)]


def test_trusted_registry_batch_resolves_only_accepted_entities(settings: Settings, schema: str) -> None:
    with transaction(settings.db_url) as conn:
        store = PostgresIntake(conn, schema)
        result = IntakeService(store, resolver=store).submit_trusted(
            TrustedBatch(
                origin=Origin.REGISTRY_SCAN,
                submitted_by="scheduler:deal_flow_scan",
                entities=[company("Via Therapeutics", registry_ids={"duns": "079642993"}), {"kind": "company"}],
            )
        )
    assert result.outcome == "partial" and [r["index"] for r in result.resolution] == [0]
    assert query(settings, f"select origins from {schema}.candidates") == [(["registry_scan"],)]


def test_failure_while_resolving_rolls_back_the_submission(
    settings: Settings, schema: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("resolver failed")

    monkeypatch.setattr(PostgresIntake, "_observe", boom)
    payload = delivery(company("Rollback Co"))
    with pytest.raises(RuntimeError):
        submit(settings, schema, payload)
    assert query(settings, f"select count(*) from {schema}.intake_submissions")[0][0] == 0
    assert query(settings, f"select count(*) from {schema}.candidates")[0][0] == 0
    monkeypatch.undo()
    assert submit(settings, schema, payload).outcome == "accepted"  # the same delivery can simply be resubmitted


def test_concurrent_deliveries_of_one_new_company_make_one_candidate(settings: Settings, schema: str) -> None:
    payloads = [delivery(company("Racer Robotics", external_id="scout:racer"), ref=f"r{i}") for i in range(3)]
    barrier = threading.Barrier(len(payloads))
    results: list[IntakeResult] = []

    def run(p: dict[str, Any]) -> None:
        barrier.wait()
        results.append(submit(settings, schema, p))

    threads = [threading.Thread(target=run, args=(p,)) for p in payloads]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert sorted(r.resolution[0]["result"] for r in results) == ["created", "re_reported", "re_reported"]
    assert query(settings, f"select count(*) from {schema}.candidates")[0][0] == 1
    assert query(settings, f"select count(*) from {schema}.companies")[0][0] == 1


def test_live_intake_into_pz_is_closed_until_the_legacy_import(settings: Settings) -> None:
    from projectzero.dealflow.intake.postgres import IntakeClosedError, ensure_intake_open

    with connect(settings.db_url, autocommit=True) as conn:
        marker = conn.execute(b"select 1 from pz.documents where key = 'ops/legacy_import'").fetchone()
        if marker is not None:
            pytest.skip("legacy import already applied: intake is open")
        with pytest.raises(IntakeClosedError, match="after the legacy import"):
            ensure_intake_open(conn, "pz")
        ensure_intake_open(conn, "pz_itest_any")  # scratch schemas are always open


# ── review 004 rev 1: a delivery is decided as a whole; the production guard sits at the shared write boundary ──


def twin(domain: str) -> dict[str, Any]:
    return company("Twin Labs", website=f"https://{domain}")


@pytest.mark.parametrize("order", [("twin-a.com", "twinlabs-b.org"), ("twinlabs-b.org", "twin-a.com")])
def test_two_same_name_entities_in_one_delivery_never_take_a_stored_company(
    settings: Settings, schema: str, order: tuple[str, str]
) -> None:
    submit(settings, schema, delivery(company("Twin Labs"), origin="manual"), by="operator")
    submit(settings, schema, delivery(company("Kontext"), origin="manual"), by="operator")
    grok = submit(settings, schema, delivery(twin(order[0]), twin(order[1]), company("Kontext")))

    by_name: dict[str, list[dict[str, Any]]] = {}
    for r in grok.resolution:
        by_name.setdefault(r["name"], []).append(r)
    assert sorted(r["company_decision"] for r in by_name["Twin Labs"]) == ["created", "created"]  # nobody joined
    assert by_name["Kontext"][0]["company_decision"] == "same_name_cross_origin"  # unrelated, unambiguous: still joins
    domains = query(
        settings,
        f"select ci.value, c.name from {schema}.company_identifiers ci join {schema}.companies c on c.id = ci.company_id "
        "where ci.kind = 'domain' order by ci.value",
    )
    assert domains == [("twin-a.com", "Twin Labs"), ("twinlabs-b.org", "Twin Labs")]
    manual_twin = query(
        settings,
        f"select count(*) from {schema}.company_identifiers where kind = 'domain' and company_id = "
        f"(select company_id from {schema}.candidates where 'manual' = any(origins) and name = 'Twin Labs')",
    )
    assert manual_twin == [(0,)]  # the stored manual company received neither domain
    suggestions = query(settings, f"select count(*) from {schema}.candidate_events where action = 'merge_suggested'")
    assert suggestions[0][0] >= 4


@pytest.mark.parametrize("order", list(itertools.permutations(["a", "b", "c"])))
def test_a_bridging_entity_in_one_delivery_joins_nobody_in_any_order(
    settings: Settings, schema: str, order: tuple[str, ...]
) -> None:
    entities = {
        "a": company("Alpha One", website="https://alpha-one.com"),
        "b": company("Beta Two", registry_ids={"duns": "222333444"}),
        "c": company("Gamma Three", website="https://alpha-one.com", registry_ids={"duns": "222333444"}),
    }
    result = submit(settings, schema, delivery(*(entities[k] for k in order)))
    by_name = {r["name"]: r for r in result.resolution}
    assert (
        by_name["Gamma Three"]["company_decision"] == "identity_conflict"
        and by_name["Gamma Three"]["company_id"] is None
    )
    assert by_name["Alpha One"]["company_id"] and by_name["Beta Two"]["company_id"]
    assert by_name["Alpha One"]["company_id"] != by_name["Beta Two"]["company_id"]
    assert query(settings, f"select count(*) from {schema}.companies")[0][0] == 2


def test_trusted_writer_into_pz_is_refused_before_cut_over(settings: Settings) -> None:
    from projectzero.dealflow.intake.postgres import IntakeClosedError

    with connect(settings.db_url, autocommit=True) as conn:
        if conn.execute(b"select 1 from pz.documents where key = 'ops/legacy_import'").fetchone():
            pytest.skip("legacy import already applied: intake is open")
    with pytest.raises(IntakeClosedError), transaction(settings.db_url) as conn:
        store = PostgresIntake(conn, "pz")
        IntakeService(store, resolver=store).submit_trusted(
            TrustedBatch(origin=Origin.REGISTRY_SCAN, submitted_by="scheduler:deal_flow_scan",
                         entities=[company("Via Therapeutics", registry_ids={"duns": "079642993"})])
        )  # fmt: skip
    counts = query(
        settings,
        "select (select count(*) from pz.intake_submissions), (select count(*) from pz.candidates), "
        "(select count(*) from pz.observations)",
    )
    assert counts == [(0, 0, 0)]


@pytest.mark.parametrize("reverse", [False, True])
def test_name_only_namesake_of_a_strong_match_in_one_delivery_does_not_join(
    settings: Settings, schema: str, reverse: bool
) -> None:
    """Codex rev 2: stored manual Twin Labs with a known domain; Grok sends Twin Labs (that domain) + Twin Labs (name only)."""
    stored = submit(
        settings,
        schema,
        delivery(company("Twin Labs", website="https://twin-labs.com"), origin="manual"),
        by="operator",
    )
    stored_company = stored.resolution[0]["company_id"]
    pair = [company("Twin Labs", website="https://twin-labs.com"), company("Twin Labs")]
    grok = submit(settings, schema, delivery(*(reversed(pair) if reverse else pair)))

    strong = next(r for r in grok.resolution if r["company_decision"] == "strong_identifier")
    other = next(r for r in grok.resolution if r is not strong)
    assert strong["company_id"] == stored_company and strong["result"] == "re_reported"  # strong match kept
    assert other["company_id"] != stored_company and other["company_decision"] == "created"  # not joined by name
    events = query(
        settings,
        f"select count(*) from {schema}.candidate_events where action = 'merge_suggested' and candidate_id = %s",
        other["candidate_id"],
    )
    assert events[0][0] >= 1  # left to the operator as a suggestion

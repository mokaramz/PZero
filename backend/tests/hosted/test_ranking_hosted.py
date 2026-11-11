"""Review 006: the ranking through the PRODUCTION path — stored rows -> adapter -> list/detail HTTP endpoints — must
equal the oracle outputs (v1 goldens and the old-code quirk/feedback goldens). Scratch schemas only."""

from __future__ import annotations

import json
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from projectzero.api.app import create_app
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.dealflow.candidates import DealFlowStore
from projectzero.ops.db_check import _scratch_sql
from projectzero.ops.legacy.convert import DEALFLOW_STATUS
from projectzero.ops.parity_ranking import diff, run_new

pytestmark = pytest.mark.hosted
GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "golden_v1"


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


def store_as_imported(
    settings: Settings, schema: str, records: list[dict[str, Any]], last_run: Any, ledger: Any
) -> None:
    """Rows exactly as the legacy import writes them: legacy record kept verbatim, status mapped, context documents."""
    with connect(settings.db_url, autocommit=True) as conn:
        for rec in records:
            conn.execute(
                f"insert into {schema}.candidates (id, name, status, legacy_status, origins, legacy, attrs) "
                "values (%s, %s, %s, %s, %s, %s, %s)".encode(),
                (rec["id"], rec.get("name") or "UNKNOWN", DEALFLOW_STATUS.get(str(rec.get("decision")), "new"),
                 rec.get("decision"), ["legacy_dealflow"], Jsonb(rec), Jsonb({})),
            )  # fmt: skip
            conn.execute(
                f"insert into {schema}.candidate_aliases (namespace, alias_id, candidate_id) values ('candidate', %s, %s)".encode(),
                (rec["id"], rec["id"]),
            )
        conn.execute(
            f"insert into {schema}.documents (key, body) values ('inbox.json#rest', %s)".encode(),
            (Jsonb({"last_run": last_run}),),
        )
        if ledger is not None:
            conn.execute(
                f"insert into {schema}.documents (key, body) values ('feedback.json', %s)".encode(), (Jsonb(ledger),)
            )


def all_items(client: TestClient) -> dict[str, dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    cursor = None
    while True:
        params: dict[str, Any] = {"limit": 50} | ({"cursor": cursor} if cursor else {})
        page = client.get("/api/deal-flow/candidates", params=params).json()
        for item in page["items"]:
            assert item["id"] not in items, "duplicate id across pages"
            items[item["id"]] = item
        if not (cursor := page["next_cursor"]):
            return items


def client_for(settings: Settings, schema: str) -> TestClient:
    return TestClient(create_app(Settings(db_url=settings.db_url, schema=schema)), base_url="http://127.0.0.1:8177")


def test_imported_rows_through_the_api_match_the_v1_goldens(settings: Settings, schema: str) -> None:
    sample = json.loads((GOLDEN / "inbox_sample.json").read_text(encoding="utf-8"))
    expected = json.loads((GOLDEN / "attention_themes.json").read_text(encoding="utf-8"))["per_candidate"]
    store_as_imported(settings, schema, sample["candidates"], sample["last_run"], None)
    with client_for(settings, schema) as client:
        items = all_items(client)
        assert set(items) == set(expected)  # no missing, extra or duplicate ids through the paged list
        mismatches = []
        for cid, item in items.items():
            want = {"attention_v2": expected[cid]["annotate_v31"], "themes": expected[cid]["themes_for"],
                    "lens": {"score": expected[cid]["lens_signals"][0], "signals": expected[cid]["lens_signals"][1]}}  # fmt: skip
            got = {k: item["ranking"][k] for k in want}
            mismatches += [f"{cid}{d}" for d in diff(want, got)]
            assert item["ranking"]["inputs"] == "full"
        assert mismatches == []
        for cid in sorted(items)[:5]:  # list and detail read the same context
            detail = client.get(f"/api/deal-flow/candidates/{cid}").json()
            assert detail["ranking"] == items[cid]["ranking"]


def test_quirks_and_ledgers_through_the_api_match_the_old_code(settings: Settings, schema: str) -> None:
    golden = json.loads((GOLDEN / "oracle_quirks_feedback.json").read_text(encoding="utf-8"))
    records = [
        c | {"decision": "new"} for c in golden["candidates"]
    ]  # inbox-shaped; 'decision' is not read by the rules
    store_as_imported(settings, schema, records, golden["last_run"], golden["ledgers"]["mixed"])
    with client_for(settings, schema) as client:
        items = all_items(client)
    by_id = {c["id"]: c for c in golden["candidates"]}
    mismatches = []
    for key, want in golden["expected"].items():
        cid = key.split(":", 1)[1]
        got = items[cid]["ranking"]
        mismatches += [f"{cid}{d}" for d in diff({**want, "feedback": want["feedback"]["mixed"]},
                                                 {k: got[k] for k in ("attention_v2", "themes", "lens", "feedback")})]  # fmt: skip
    assert mismatches == []
    adjustments = {s["source_id"]: s["adjustment"] for s in items["multi-source"]["ranking"]["feedback"]["sources"]}
    assert adjustments["src-pos"] > 0 and adjustments["src-neg"] < 0  # positive and negative through production
    assert by_id  # corpus present


def test_merged_and_partial_inputs_are_flagged(settings: Settings, schema: str) -> None:
    with connect(settings.db_url, autocommit=True) as conn:
        conn.execute(
            f"insert into {schema}.candidates (id, name, status, origins, key_fact, legacy, attrs) values "
            "('mergedintake', 'Kontext', 'watch', '{legacy_dealflow,legacy_scout00}', 'Founded in Berlin 2026', %s, '{}'),"
            "('liveGrok0001', 'Grok Robotics', 'new', '{grok}', 'Raised a pre-seed round', null, '{}')".encode(),
            (Jsonb({"id": "si-008-kontext", "entity_name": "Kontext", "status": "MONITOR"}),),
        )
    with client_for(settings, schema) as client:
        items = all_items(client)
    assert items["mergedintake"]["ranking"]["inputs"] == "partial"  # survivor is a Scout Intake record
    assert items["liveGrok0001"]["ranking"]["inputs"] == "partial"
    assert items["liveGrok0001"]["ranking"]["attention_v2"]["applied"]  # still ranked, from the mapped columns


def test_operator_notes_feed_the_ranking_text_like_the_old_app(settings: Settings, schema: str) -> None:
    record = {"id": "notes0000001", "name": "Quiet Labs", "decision": "new", "discovery_tier": "announcement",
              "source_id": "us-nih", "source": "NIH", "description": "Builds tools."}  # fmt: skip
    store_as_imported(settings, schema, [record], "2026-11-08 19:09:09", None)
    note = "Founders are PhD researchers from TU Munich; spin-off project."
    with transaction(settings.db_url) as conn:
        DealFlowStore(conn, schema).decide("notes0000001", "reviewing", notes=note)
    with client_for(settings, schema) as client:
        got = client.get("/api/deal-flow/candidates/notes0000001").json()["ranking"]
    expected = run_new([record | {"notes": note, "decision": "research"}], {"none": None}, "2026-11-08 19:09:09")
    want = next(iter(expected.values()))
    assert got["attention_v2"] == want["attention_v2"] and got["lens"] == want["lens"]
    assert "Research spinout" in [label for label, _ in got["attention_v2"]["applied"]]  # the note changed the score

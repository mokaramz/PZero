"""Review 022 acceptance tests (Codex H-165 / H-167) against the hosted project, in throw-away scratch schemas.

The synthetic corpus of ``ops/parity_ecosystems`` (invented names) is seeded as the import writes it: the Deal Flow
registry rows, and the archived documents (a standalone source override, an archived adoption whose recorded source
id differs from its derived ``cov-`` id and whose catalog URL is now empty, custom ecosystems, the candidates).

* the historical retry answers the RECORDED source id with ``already`` and writes nothing; without ``confirm`` it is
  the confirmation refusal; a candidate whose ``cov-`` source already exists answers ``already`` with no row;
* a new adoption writes ONE source, one ``adopt`` event and one adoption row; a fresh read keeps the standalone
  override, the historical adoption and the custom ecosystem unchanged;
* the adoption is all-or-nothing (a failure after the source write leaves nothing); two concurrent adopts of one
  candidate make one source and one row; writes are closed before the import in production.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from projectzero.api.app import create_app
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.dealflow.sources.normalize import load_registry
from projectzero.dealflow.sources.store import SourcesStore
from projectzero.ecosystems import adopt, coverage
from projectzero.ecosystems.inputs import merged_adoptions, merged_overrides
from projectzero.ecosystems.store import DOCS, EcosystemsStore
from projectzero.ops.db_check import _scratch_sql
from projectzero.ops.parity_ecosystems import CLOCK, corpus, utc_instant

pytestmark = pytest.mark.hosted
NOW = utc_instant(CLOCK)
HISTORIC = "cand-invented-historic-watcher"


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


@pytest.fixture
def client(settings: Settings, schema: str) -> Iterator[TestClient]:
    docs = corpus()
    with transaction(settings.db_url) as conn:
        for s in docs["sources.json"]["sources"]:
            conn.execute(f"insert into {schema}.sources (id, name, url, kind, enabled, legacy) values (%s, %s, %s, %s, %s, %s)"
                         .encode(), (s["id"], s["name"], s.get("url"), s["kind"], bool(s.get("enabled")), Jsonb(s)))  # fmt: skip
        raw = json.dumps(docs["sources.json"]).encode("utf-8")
        conn.execute(f"insert into {schema}.legacy_documents (path, sha256, bytes, raw, parsed) values "
                     "('sources.json', %s, %s, %s, %s)".encode(),
                     (hashlib.sha256(raw).hexdigest(), len(raw), raw, Jsonb(docs["sources.json"])))  # fmt: skip
        for key in DOCS.values():
            if key in docs:
                conn.execute(
                    f"insert into {schema}.documents (key, body) values (%s, %s)".encode(), (key, Jsonb(docs[key]))
                )
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    app.state.clock = lambda: NOW
    with TestClient(app, base_url="http://127.0.0.1:8177") as c:
        yield c


def counts(settings: Settings, schema: str) -> tuple[int, int, int]:
    with transaction(settings.db_url) as conn:
        out = []
        for table in ("sources", "source_events", "coverage_adoptions"):
            row = conn.execute(f"select count(*) from {schema}.{table}".encode()).fetchone()
            assert row is not None
            out.append(int(row[0]))
    return out[0], out[1], out[2]


def inputs(settings: Settings, schema: str) -> Any:
    with transaction(settings.db_url) as conn:
        return EcosystemsStore(conn, schema).inputs(NOW)


def fresh_candidate(settings: Settings, schema: str, skip: tuple[str, ...] = ()) -> str:
    """A candidate whose adoption would write (eligible, not adopted, no existing cov- source)."""
    inp = inputs(settings, schema)
    for c in coverage.candidate_sources(inp):
        if c["id"] not in skip and adopt.adopt_plan(inp, c["id"], True).writes:
            return str(c["id"])
    raise AssertionError("the corpus has no adoptable candidate")


def post(client: TestClient, cid: str, confirm: Any = True) -> dict[str, Any]:
    r = client.post("/api/ecosystems/coverage/adopt", json={"id": cid, "confirm": confirm})
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def test_the_imported_state_survives_and_a_new_adoption_overlays_it(
    settings: Settings, schema: str, client: TestClient
) -> None:
    assert "cov-" + HISTORIC[5:] == "cov-invented-historic-watcher"  # the legacy id mapping (pinned)
    before = counts(settings, schema)
    assert post(client, HISTORIC) == {"ok": True, "already": True, "source_id": "cov-legacy-historic"}
    assert post(client, HISTORIC, confirm=False) == {"ok": False, "error": "explicit confirmation required"}
    assert counts(settings, schema) == before  # the historical retry wrote nothing
    inp = inputs(settings, schema)
    existing = next(c["id"] for c in coverage.candidate_sources(inp)
                    if not c.get("adopted") and any(s.get("id") == "cov-" + c["id"][5:] for s in inp.sources))  # fmt: skip
    assert post(client, existing) == {"ok": True, "already": True, "source_id": "cov-" + existing[5:]}
    assert counts(settings, schema) == before  # an existing cov- source: no adoption row either
    overrides0, adoptions0 = merged_overrides(inp), merged_adoptions(inp)
    cid = fresh_candidate(settings, schema)
    answer = post(client, cid)
    assert answer["ok"] is True and answer["source_id"] == "cov-" + cid[5:] and "already" not in answer
    s1, e1, a1 = counts(settings, schema)
    assert (e1 - before[1], a1 - before[2]) == (1, 1) and s1 > before[0]  # (the registry is persisted whole)
    after = inputs(settings, schema)
    o1, d1 = merged_overrides(after), merged_adoptions(after)
    assert o1["x-standalone"] == overrides0["x-standalone"]  # the standalone override, unchanged
    assert d1[HISTORIC] == adoptions0[HISTORIC]  # the historical adoption: its id, date and operator
    assert d1[cid]["source_id"] == "cov-" + cid[5:] and d1[cid]["by"] == "operator"
    cov = client.get("/api/ecosystems/coverage").json()
    assert any(e["city"] == "Quellbrunn" for e in cov["ecosystems"])  # the custom ecosystem
    assert post(client, cid) == {"ok": True, "already": True, "source_id": "cov-" + cid[5:]}
    assert counts(settings, schema) == (s1, e1, a1)


def test_an_adoption_is_all_or_nothing(
    settings: Settings, schema: str, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = counts(settings, schema)
    cid = fresh_candidate(settings, schema)

    def boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("injected after the source write")

    monkeypatch.setattr(SourcesStore, "event", boom)
    with pytest.raises(RuntimeError, match="injected"):  # the test client re-raises the server's exception
        client.post("/api/ecosystems/coverage/adopt", json={"id": cid, "confirm": True})
    assert counts(settings, schema) == before  # the source write was rolled back with the rest
    monkeypatch.undo()
    assert post(client, cid)["ok"] is True


def test_two_concurrent_adopts_make_one_source_and_one_row(settings: Settings, schema: str, client: TestClient) -> None:
    before = counts(settings, schema)
    cid = fresh_candidate(settings, schema)
    answers: list[dict[str, Any]] = []
    threads = [threading.Thread(target=lambda: answers.append(post(client, cid))) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert sorted(bool(a.get("already")) for a in answers) == [False, True]
    with transaction(settings.db_url) as conn:
        rows = conn.execute(f"select count(*) from {schema}.coverage_adoptions where candidate_id = %s".encode(),
                            (cid,)).fetchone()  # fmt: skip
        src = conn.execute(
            f"select count(*) from {schema}.sources where id = %s".encode(), ("cov-" + cid[5:],)
        ).fetchone()
    assert rows == (1,) and src == (1,)
    assert counts(settings, schema)[1] - before[1] == 1  # one adopt event


def test_with_an_empty_registry_the_watcher_follows_every_repair_added_source(settings: Settings) -> None:
    """Codex H-171: the old adopt appended to the NORMALIZED registry, so the repair-added sources come first."""
    name = f"pz_itest_{secrets.token_hex(4)}"
    admin = connect(settings.db_url, autocommit=True)
    try:
        admin.execute(_scratch_sql(name).encode())
        docs = corpus()
        with transaction(settings.db_url) as conn:
            for key in DOCS.values():
                if key in docs:
                    conn.execute(
                        f"insert into {name}.documents (key, body) values (%s, %s)".encode(), (key, Jsonb(docs[key]))
                    )
        app = create_app(Settings(db_url=settings.db_url, schema=name))
        app.state.clock = lambda: NOW
        with TestClient(app, base_url="http://127.0.0.1:8177") as c:
            cid = fresh_candidate(settings, name)
            assert post(c, cid)["ok"] is True
        with transaction(settings.db_url) as conn:
            stored_ids = [s["id"] for s in SourcesStore(conn, name).stored()]
        normalized = [s["id"] for s in load_registry({"sources": []})["sources"]]
        assert len(normalized) == 7 and stored_ids == [*normalized, "cov-" + cid[5:]]  # a fresh read: the old order
    finally:
        admin.execute(f"drop schema if exists {name} cascade".encode())
        admin.close()


def test_writes_are_closed_before_the_import_in_production(settings: Settings) -> None:
    app = create_app(Settings(db_url=settings.db_url, schema="pz"))
    with TestClient(app, base_url="http://127.0.0.1:8177") as c:
        r = c.post("/api/ecosystems/coverage/adopt", json={"id": "cand-anything", "confirm": True})
    if r.status_code == 409:
        assert "after the legacy import" in r.json()["error"]
    else:  # the live import has happened: the boundary is open (an unknown candidate is the old refusal)
        assert r.json()["ok"] is False

"""Review 033a acceptance tests (plan revision 2, Codex H-313 / H-315) against the hosted project, in throw-away
scratch schemas, with invented names only and a scripted ``FakeProvider`` (never a real model).

* retention: the 81st message prunes exactly the oldest; a further append to a pruned conversation keeps the order
  (``seq`` after the highest retained); a delete cascades; the 61st conversation evicts the oldest with its messages;
  an UPDATE is refused, and so is a DELETE outside the lifecycle operations, on a fresh connection;
* concurrency: two overlapping asks on one conversation, released together at phase 3, both append whole turns in
  commit order, nothing lost or duplicated; a conversation deleted during phase 2 answers ``saved: false`` and is not
  recreated;
* writes: asks that together call EVERY tool (each within the 4-step limit) leave every business table unchanged;
  a failed phase 3 leaves no partial turn while each dispatched attempt keeps its accounting.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from projectzero.api.app import create_app
from projectzero.associate import caps
from projectzero.associate.store import AssociateStore
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.core.inference.providers import FakeProvider
from projectzero.ops.parity_associate import importable, read_golden
from projectzero.ops.parity_validation import _fingerprint
from projectzero.ops.scratch_import import drop_schema, import_world

pytestmark = pytest.mark.hosted
NOW = datetime(2026, 11, 13, 8, 0, tzinfo=UTC)  # 09:00 in Berlin
ACCOUNTING = {"model_ledger", "model_reservations", "model_cache"}
TOOLS = ("search_docs", "today_missions", "conviction_companies", "company_detail", "manager_decisions", "radar",
         "deal_flow_candidates", "candidate_detail", "find_records", "upcoming_events")  # fmt: skip
ARGS: dict[str, dict[str, Any]] = {
    "search_docs": {"query": "how does the Radar work"}, "company_detail": {"slug": "invented-arclight-systems"},
    "candidate_detail": {"id": "c-302"}, "find_records": {"query": "Invented Arclight Systems"},
    "deal_flow_candidates": {}, "conviction_companies": {}, "upcoming_events": {},
}  # fmt: skip


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture(scope="module")
def schema(settings: Settings) -> Iterator[str]:
    name = import_world(settings.db_url, importable(read_golden()["worlds"]["main"]["docs"]))
    yield name
    drop_schema(settings.db_url, name)


def _client(settings: Settings, schema: str, **state: Any) -> TestClient:
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    app.state.clock = lambda: NOW
    for k, v in state.items():
        setattr(app.state, k, v)
    return TestClient(app, base_url="http://127.0.0.1:8177", raise_server_exceptions=False)


def _seqs(settings: Settings, schema: str, cid: str) -> list[int]:
    with transaction(settings.db_url) as conn:
        q = sql.SQL("select seq from {}.associate_messages where conversation_id = %s order by seq")
        return [r[0] for r in conn.execute(q.format(sql.Identifier(schema)), (cid,)).fetchall()]


def _texts(settings: Settings, schema: str, cid: str) -> list[str]:
    with transaction(settings.db_url) as conn:
        q = sql.SQL("select body::text from {}.associate_messages where conversation_id = %s order by seq")
        return [json.loads(r[0])["text"] for r in conn.execute(q.format(sql.Identifier(schema)), (cid,)).fetchall()]


def _turn(i: int) -> tuple[dict[str, Any], dict[str, Any]]:
    return ({"role": "user", "text": f"q{i}", "at": "", "context": None},
            {"role": "assistant", "text": f"a{i}", "at": "", "tools": [], "usd": 0, "model": ""})  # fmt: skip


def test_the_81st_message_prunes_the_oldest_and_a_later_append_keeps_the_order(settings: Settings, schema: str) -> None:
    with transaction(settings.db_url) as conn:
        cid = AssociateStore(conn, schema).save_turn(None, "Invented retention", _turn(1), NOW).conversation_id
    assert cid is not None
    for i in range(2, 42):  # 41 turns: 82 messages -> the two oldest pruned
        with transaction(settings.db_url) as conn:
            assert AssociateStore(conn, schema).save_turn(cid, "", _turn(i), NOW + timedelta(seconds=i)).saved
    assert _seqs(settings, schema, cid) == list(range(3, 83)) and _texts(settings, schema, cid)[:2] == ["q2", "a2"]
    with transaction(settings.db_url) as conn:  # an append after pruning: after the HIGHEST retained seq
        AssociateStore(conn, schema).save_turn(cid, "", _turn(42), NOW + timedelta(seconds=60))
    seqs, texts = _seqs(settings, schema, cid), _texts(settings, schema, cid)
    assert seqs == list(range(5, 85)) and texts[-2:] == ["q42", "a42"] and texts[:2] == ["q3", "a3"]
    with transaction(settings.db_url) as conn:
        conv = AssociateStore(conn, schema).load_conversation(cid)
    assert conv is not None and len(conv["messages"]) == caps.MAX_TURNS
    assert list(conv) == ["id", "title", "created", "updated", "messages"]  # the old conversation file's keys


def test_messages_are_immutable_and_deleted_only_by_the_lifecycle_operations(settings: Settings, schema: str) -> None:
    with transaction(settings.db_url) as conn:
        cid = AssociateStore(conn, schema).save_turn(None, "Invented guard", _turn(1), NOW).conversation_id
    s = sql.Identifier(schema)
    for stmt in (sql.SQL("update {}.associate_messages set body = '{{}}' where conversation_id = %s").format(s),
                 sql.SQL("delete from {}.associate_messages where conversation_id = %s").format(s),
                 sql.SQL("delete from {}.associate_conversations where id = %s").format(s)):  # fmt: skip
        with connect(settings.db_url, autocommit=True) as fresh, pytest.raises(Exception, match=r"immutable|pruning"):
            fresh.execute(stmt, (cid,))  # a FRESH connection: the lifecycle flag is unset, so off
    assert _seqs(settings, schema, str(cid)) == [1, 2]
    with transaction(settings.db_url) as conn:
        assert AssociateStore(conn, schema).delete_conversation(str(cid)) is True
    assert _seqs(settings, schema, str(cid)) == []  # the cascade
    with transaction(settings.db_url) as conn:
        assert AssociateStore(conn, schema).delete_conversation(str(cid)) is False


def test_the_61st_conversation_evicts_the_oldest_with_its_messages(settings: Settings, schema: str) -> None:
    with transaction(settings.db_url) as conn:
        q = sql.SQL("select count(*) from {}.associate_conversations").format(sql.Identifier(schema))
        row = conn.execute(q).fetchone()
        assert row is not None
        start = int(row[0])
    made = []
    for i in range(caps.MAX_CONVERSATIONS - start + 1):
        with transaction(settings.db_url) as conn:
            made.append(AssociateStore(conn, schema).save_turn(
                None, f"Invented {i}", _turn(i), NOW + timedelta(minutes=10 + i)
            ).conversation_id)  # fmt: skip
    with transaction(settings.db_url) as conn:
        listed = AssociateStore(conn, schema).list_conversations()
        q = sql.SQL(
            "select count(*) from {s}.associate_messages m where not exists (select 1 from "
            "{s}.associate_conversations c where c.id = m.conversation_id)"
        ).format(s=sql.Identifier(schema))
        orphans = conn.execute(q).fetchone()
    assert len(listed) == caps.MAX_CONVERSATIONS and orphans == (0,)
    assert made[-1] in {c["id"] for c in listed}


def _scripted(*replies: dict[str, Any]) -> FakeProvider:
    return FakeProvider.scripted([json.dumps(r) for r in replies], paid=True)


def _kw(provider: FakeProvider) -> dict[str, Any]:
    return {"providers": {"deepinfra": provider}, "env": {"PZ_AI_PAID": "on", "DEEPINFRA_API_KEY": "invented"},
            "sleep": lambda s: None}  # fmt: skip


def _business(settings: Settings, schema: str) -> dict[str, Any]:
    with transaction(settings.db_url) as conn:
        fp = _fingerprint(conn, schema)
    return {t: v for t, v in fp.items() if not t.startswith("associate_") and t not in ACCOUNTING}


def test_asks_calling_every_tool_leave_every_business_table_unchanged(settings: Settings, schema: str) -> None:
    before = _business(settings, schema)
    called: list[str] = []
    for chunk in (TOOLS[0:3], TOOLS[3:6], TOOLS[6:9], TOOLS[9:]):  # each ask: at most 3 tools, then the answer
        script = [{"tool": t, "args": ARGS.get(t, {})} for t in chunk] + [{"answer": "Invented summary."}]
        with _client(settings, schema, associate_gateway_kw=_kw(_scripted(*script))) as client:
            r = client.post("/api/associate/ask", json={"message": f"Check {', '.join(chunk)}"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["message"]["tools"]) == len(chunk) <= 3
        called += [t["tool"] for t in body["message"]["tools"] if t["ok"]]
    assert sorted(called) == sorted(TOOLS)  # the whole registry, within the 4-step limit per ask
    assert _business(settings, schema) == before


def _accounting(settings: Settings, schema: str) -> tuple[int, int]:
    with transaction(settings.db_url) as conn:
        s = sql.Identifier(schema)
        led = conn.execute(sql.SQL("select count(*) from {}.model_ledger where purpose = 'associate' "
                                   "and call_id is not null").format(s)).fetchone()  # fmt: skip
        res = conn.execute(sql.SQL("select count(*) from {}.model_reservations").format(s)).fetchone()
    assert led is not None and res is not None
    return int(led[0]), int(res[0])


def test_a_failed_phase_3_leaves_no_partial_turn_and_keeps_the_accounting(settings: Settings, schema: str) -> None:
    def boom() -> None:
        raise RuntimeError("invented failure after the appends")

    with transaction(settings.db_url) as conn:
        fp = _fingerprint(conn, schema)
    assoc_before = {t: v for t, v in fp.items() if t.startswith("associate_")}
    led_before, res_before = _accounting(settings, schema)
    provider = _scripted({"answer": "Invented answer."})
    with _client(settings, schema, associate_gateway_kw=_kw(provider), associate_fail_after_append=boom) as client:
        r = client.post("/api/associate/ask", json={"message": "Invented question"})
    assert r.status_code == 500
    with transaction(settings.db_url) as conn:
        fp = _fingerprint(conn, schema)
    assert {t: v for t, v in fp.items() if t.startswith("associate_")} == assoc_before  # no partial turn
    led, res = _accounting(settings, schema)
    assert provider.dispatches == 1 and (led - led_before) + (res - res_before) == 1  # the attempt's accounting


def test_overlapping_asks_append_whole_turns_in_commit_order(settings: Settings, schema: str) -> None:
    with transaction(settings.db_url) as conn:
        cid = AssociateStore(conn, schema).save_turn(None, "Invented overlap", _turn(0), NOW).conversation_id
    barrier = threading.Barrier(2, timeout=60)
    answers: list[Any] = []

    def ask(text: str) -> None:
        provider = _scripted({"answer": f"answer to {text}"})
        with _client(settings, schema, associate_gateway_kw=_kw(provider),
                     associate_before_save=lambda: barrier.wait()) as client:  # fmt: skip
            answers.append(client.post("/api/associate/ask", json={"message": text, "conversation_id": cid}))

    threads = [threading.Thread(target=ask, args=(t,)) for t in ("Invented A", "Invented B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert [r.status_code for r in answers] == [200, 200]
    texts = _texts(settings, schema, str(cid))
    assert _seqs(settings, schema, str(cid)) == [1, 2, 3, 4, 5, 6]
    pairs = [texts[2:4], texts[4:6]]  # each turn whole: its question, then its answer
    assert sorted(pairs) == [["Invented A", "answer to Invented A"], ["Invented B", "answer to Invented B"]]


def test_a_conversation_deleted_during_phase_2_answers_unsaved_and_is_not_recreated(
    settings: Settings, schema: str
) -> None:
    with transaction(settings.db_url) as conn:
        cid = AssociateStore(conn, schema).save_turn(None, "Invented vanishing", _turn(0), NOW).conversation_id

    def delete() -> None:
        with transaction(settings.db_url) as conn:
            assert AssociateStore(conn, schema).delete_conversation(str(cid))

    provider = _scripted({"answer": "Invented late answer."})
    with _client(settings, schema, associate_gateway_kw=_kw(provider), associate_before_save=delete) as client:
        r = client.post("/api/associate/ask", json={"message": "Invented question", "conversation_id": cid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["saved"] is False and body["notice"].startswith("This conversation was deleted")
    assert body["message"]["text"]
    with transaction(settings.db_url) as conn:
        assert AssociateStore(conn, schema).load_conversation(str(cid)) is None


def test_with_paid_calls_off_an_ask_is_answered_offline_and_saved(settings: Settings, schema: str) -> None:
    with _client(settings, schema, associate_gateway_kw={"env": {"PZ_AI_PAID": "off"}}) as client:
        r = client.post("/api/associate/ask", json={"message": "How does the Radar work?"})
        assert r.status_code == 200, r.text
        body = r.json()
        conv = client.get("/api/associate/conversation", params={"id": body["conversation"]["id"]}).json()
    assert body["message"]["mode"] == "offline" and "saved" not in body  # the old answer, key for key
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    assert list(conv["messages"][1])[:4] == ["role", "at", "tools", "usd"]  # the stored json keeps the old key order


def test_a_draft_needs_the_confirmation(settings: Settings, schema: str) -> None:
    with _client(settings, schema) as client:
        refused = client.post("/api/associate/draft", json={"title": "t", "body": "Invented draft."})
        ok = client.post("/api/associate/draft", json={"title": "t", "body": "Invented draft.", "confirm": True})
        listed = client.get("/api/associate/drafts").json()["drafts"]
    assert refused.status_code == 400 and "confirm" in refused.json()["error"]
    assert ok.status_code == 200 and listed[0]["id"] == ok.json()["draft"]["id"]


def test_the_ask_deadline_cut_during_a_tool_read_ends_the_ask_with_nothing_saved(
    settings: Settings, schema: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex H-317: the ask's ONE deadline bounds every phase. Here the budget runs out DURING a tool read (the read's
    bounded snapshot is then refused). The ask answers 503: no further model call, no partial turn, and the
    dispatched attempt keeps its accounting."""
    import time

    from projectzero.associate import reader as reader_mod

    offset = [0.0]
    original = reader_mod.DbReader.today_missions

    def slow_read(self: Any) -> dict[str, Any]:
        offset[0] += 300.0  # the read takes longer than the whole ask's budget
        return original(self)

    monkeypatch.setattr(reader_mod.DbReader, "today_missions", slow_read)
    with transaction(settings.db_url) as conn:
        fp = _fingerprint(conn, schema)
    assoc_before = {t: v for t, v in fp.items() if t.startswith("associate_")}
    led_before, res_before = _accounting(settings, schema)
    provider = _scripted({"tool": "today_missions", "args": {}}, {"answer": "never asked"})
    with _client(settings, schema, associate_gateway_kw=_kw(provider),
                 monotonic=lambda: time.monotonic() + offset[0]) as client:  # fmt: skip
        r = client.post("/api/associate/ask", json={"message": "Invented: what should I focus on today?"})
    assert r.status_code == 503 and "nothing was saved" in r.json()["error"]
    assert provider.dispatches == 1  # no model call after the cut read
    with transaction(settings.db_url) as conn:
        fp = _fingerprint(conn, schema)
    assert {t: v for t, v in fp.items() if t.startswith("associate_")} == assoc_before  # no partial turn
    led, res = _accounting(settings, schema)
    assert (led - led_before) + (res - res_before) == 1  # the one dispatched attempt: settled, or a reservation

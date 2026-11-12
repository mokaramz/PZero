"""Review 028c, offline (no database, no network): the pure refresh run (``news/refresh.py``, ``news/evaluate.py``)
matches the OLD run's golden (``oracle_news_refresh.json``, ``python -m projectzero.ops.parity_news refresh-goldens``)
with only the declared differences; the News fetch policy refuses everything off the allowlist BEFORE it is sent; the
budgets hold; ``apply`` runs against the CURRENT inputs (a write committed during the fetch is kept) and never mutates
them; one Berlin clock; the old run id and answer shapes. Every test runs with a system resolver that fails the test
if anything calls it: only fixture transports and resolvers answer."""

from __future__ import annotations

import copy
import json
import re
import socket
import time
from collections.abc import Iterator, Mapping
from datetime import UTC, date, datetime
from typing import Any

import pytest

from projectzero.core import net
from projectzero.news import evaluate as news_evaluate
from projectzero.news import fetching, refresh, writes
from projectzero.news.fetching import FeedFetch
from projectzero.ops import parity_news
from projectzero.ops.parity_news import (
    FEED_URLS,
    FIXTURE_IP,
    REFRESH_GOLDEN,
    FixtureTransport,
    compare_refresh,
    fixture_resolver,
    item,
    read_golden,
    refresh_docs,
    refresh_feeds,
    rfc,
    rss,
)
from projectzero.validation import inputs_from_docs as validation_inputs

GOLDEN: dict[str, Any] = read_golden(REFRESH_GOLDEN)
NOW = datetime(2026, 11, 12, 10, 0)  # naive: Berlin wall time, as the goldens
TODAY = date(2026, 11, 12)


@pytest.fixture(autouse=True)
def no_system_resolver(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def refuse(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("the system resolver / network was called")

    monkeypatch.setattr(net, "default_resolver", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    yield


def run_inputs(docs: dict[str, Any] | None = None) -> refresh.RunInputs:
    v = validation_inputs(copy.deepcopy(docs if docs is not None else refresh_docs()), TODAY)
    doc, _changes = writes.ensure_seeded(v.news_inputs.events, v.news_inputs.cases, NOW)
    n, v = writes.with_events(v.news_inputs, v, doc)
    return refresh.RunInputs(n, v)


def one_feed(body: str, **spec: Any) -> dict[str, Any]:
    return {FEED_URLS["Sifted"]: {"body": body, **spec}}


def fetch_sifted(
    feeds: Mapping[str, Any], *, resolver: Any = fixture_resolver, **kw: Any
) -> tuple[refresh.FeedResult, FixtureTransport]:
    t = FixtureTransport(feeds)
    p = refresh.plan(run_inputs().news, TODAY, NOW, run_id="news-x", clock=lambda: 0.0)
    f = next(f for f in p.todo if f["name"] == "Sifted")
    return refresh.fetch_one(f, FeedFetch(transport=t, resolver=resolver, **kw), p), t


# ------------------------------------------------------------------ the golden
def test_the_new_run_matches_the_old_golden_with_only_the_declared_differences() -> None:
    assert compare_refresh(GOLDEN) == []


def test_the_golden_covers_the_planned_cases() -> None:
    got, _p = parity_news.new_refresh(GOLDEN, strict=False)
    first, second = (r["outcome"] for r in got["runs"])
    rec = first.record
    pf = rec["per_feed"]
    assert rec["new"] > 40 and rec["merged"] == 2 and rec["duplicates_skipped"] == 1 and rec["reclassified"] > 0
    assert pf["EU-Startups"]["items"] == 40  # 45 items, the old cap
    assert pf["Silicon Canals"]["stale_days"] == 20 and rec["stale_feeds"] == ["Silicon Canals"]
    assert pf["Startbase"]["rate_limited"] and pf["Startbase"]["cooldown_until"] == "2026-11-12T10:30:00"
    assert pf["deutsche-startups.de"]["ok"] is None and rec["cooldown"] == ["deutsche-startups.de"]
    assert pf["Munich Startup"]["error"] == "HTTPError: HTTP Error 500: Internal Server Error"
    assert pf["Invented Gazette"]["error"].startswith("ParseError: ")
    assert pf["Sifted"]["items"] == 9  # an orphan item without a link and a bad item skipped
    assert first.documents["news/feed_cooldown.json"] == {
        "deutsche-startups.de": "2026-11-12T10:20:00",
        "Startbase": "2026-11-12T10:30:00",
    }
    events = first.events_doc["events"]
    by_head = {e["headline"]: e for e in events.values()}
    assert by_head[parity_news.COLLIDE]["event_id"] != parity_news.collision_id()  # the collision suffix
    assert by_head["Invented Birch Analytics raises €2M for AI audits"]["event_date"] == "2026-11-12"  # future: today
    cobalt = by_head["Invented Cobalt Sensors secures €3M for industrial AI"]
    assert (
        cobalt["event_date"] == "2026-11-11" and cobalt["sources"][0]["published_ts"] == "2026-11-11T06:30"
    )  # Berlin day
    assert [s["independence"] for s in events["nw-r-synd"]["sources"]] == ["independent", "syndicated"]
    assert len(events["nw-early"]["sources"]) == 4  # merged by entity, type and date
    assert by_head["Invented Lumen Grid opens a second robotics plant"]["company_from"] == "known to Project Zero"
    assert any(e["publisher"] == "startupticker.ch" for c in first.new_events for e in c.record["sources"])
    passes = {c.event_id: c.passes for c in first.changed_events}
    assert passes["nw-r-other"] == ("rederive",) and events["nw-r-other"]["event_type"] == "funding"
    assert events["nw-r-broken"]["company"] == "" and events["nw-r-noise"]["materiality"] == "NOISE"
    assert passes["nw-early"] == ("ingest", "rederive")
    assert rec["cards"] == 12 and sum("card" in c.passes for c in (*first.new_events, *first.changed_events)) > 0
    ev = first.evaluation
    assert ev is not None and ev.lines("disagreements") and ev.lines("source_history") and ev.deferred_nominations
    logged = [json.loads(line)["event"] for line in ev.lines("source_log")]
    assert {"degraded", "recovered", "nomination_deferred", "evaluated"} <= set(logged)
    assert second.record["duplicates_skipped"] > 40 and second.record["cooldown"] == ["Startbase"]
    assert second.evaluation is not None and not second.evaluation.lines("source_history")  # not due again


def test_the_comparison_catches_a_changed_line_and_a_changed_order() -> None:
    bad = copy.deepcopy(GOLDEN)
    r = bad["expected"]["runs"][0]
    r["appended"][-1][1] = r["appended"][-1][1].replace('"status": "partial"', '"status": "ok"')
    ev = r["events"]["events"]
    first = next(iter(ev))
    r["events"]["events"] = {**{k: v for k, v in ev.items() if k != first}, first: ev[first]}
    problems = compare_refresh(bad)
    assert any("/appended" in p for p in problems) and any("key order" in p for p in problems)


# ------------------------------------------------------------------ the network policy
def test_the_policy_allows_the_feed_hosts_and_the_enabled_extra_feeds_only() -> None:
    p = refresh.plan(run_inputs().news, TODAY, NOW, run_id="news-x")
    assert "sifted.eu" in p.hosts and "ledger.invented.example" in p.hosts and "gazette.invented.example" in p.hosts
    assert "quill.invented.example" not in p.hosts  # a disabled extra feed
    policy = fetching.feed_policy(p.hosts)
    policy("https://sifted.eu/feed", 0)
    for url, why in (("http://sifted.eu/feed", "https only"), ("https://sifted.eu:8443/feed", "default https port"),
                     ("https://evil.invented.example/feed", "not a News feed host"),
                     ("https://www.sifted.eu/feed", "not a News feed host")):  # fmt: skip
        with pytest.raises(net.UnsafeURLError, match=why):
            policy(url, 0)
    with pytest.raises(net.UnsafeURLError, match="more than 5 redirects"):
        policy("https://sifted.eu/feed", 6)


def test_a_redirect_off_the_allowlist_is_never_sent() -> None:
    res, t = fetch_sifted({FEED_URLS["Sifted"]: {"status": 301, "headers": {"Location": "https://evil.invented.example/x"}},
                           "https://evil.invented.example/x": {"body": rss([])}})  # fmt: skip
    assert [q["url"] for q in t.requests] == [FEED_URLS["Sifted"]]
    assert (
        res.res["ok"] is False
        and res.res["error"].startswith("UnsafeURLError: ")
        and "not a News feed host" in res.res["error"]
    )


def test_a_redirect_to_http_and_too_many_redirects_are_refused_before_sending() -> None:
    res, t = fetch_sifted({FEED_URLS["Sifted"]: {"status": 302, "headers": {"Location": "http://sifted.eu/feed"}}})
    assert len(t.requests) == 1 and "https only" in res.res["error"]
    loop = {
        f"https://sifted.eu/r{i}": {"status": 302, "headers": {"Location": f"https://sifted.eu/r{i + 1}"}}
        for i in range(10)
    }
    loop[FEED_URLS["Sifted"]] = {"status": 302, "headers": {"Location": "https://sifted.eu/r0"}}
    res, t = fetch_sifted(loop)
    assert len(t.requests) == 6 and "more than 5 redirects" in res.res["error"]  # the first + 5 redirects


def test_an_http_feed_is_refused_before_anything_is_sent() -> None:
    t = FixtureTransport({})
    fetch = FeedFetch(transport=t, resolver=fixture_resolver)
    with pytest.raises(net.UnsafeURLError, match="https only"):
        fetch.get("http://sifted.eu/feed", fetching.allowed_hosts())
    assert t.requests == []


def test_a_private_address_is_refused() -> None:
    for ip in ("10.0.0.7", "127.0.0.1", "169.254.169.254", "::1"):
        res, t = fetch_sifted(one_feed(rss([])), resolver=lambda _h, ip=ip: [ip])
        assert t.requests == [] and "non-public address" in res.res["error"]


def test_a_resolver_that_refuses_everything_fails_the_feed_without_a_request() -> None:
    res, t = fetch_sifted(one_feed(rss([])), resolver=lambda _h: [])
    assert t.requests == [] and "DNS resolution failed" in res.res["error"]


def test_the_requests_carry_the_project_user_agent_and_the_budgets() -> None:
    res, t = fetch_sifted(one_feed(rss([item("Invented Oak Robotics raises €2M", "https://sifted.eu/oak", rfc(1))])))
    assert res.res["ok"] is True
    (q,) = t.requests
    assert q["headers"]["User-Agent"] == fetching.USER_AGENT and "Mozilla" not in json.dumps(q["headers"])
    assert q["ip"] == FIXTURE_IP and q["max_bytes"] == 8_000_000 and 19.0 < q["timeout"] <= 20.0
    assert 0 < q["deadline"] - time.monotonic() <= 20.0  # 20 s for the whole feed


def test_a_body_over_the_size_cap_fails_the_feed() -> None:
    res, _t = fetch_sifted(one_feed("", raw=b"<rss>" + b" " * fetching.MAX_BYTES + b"</rss>"))
    assert res.res["ok"] is False and res.res["error"].startswith("ResponseTooLargeError: ")


def test_a_run_past_its_deadline_sends_nothing() -> None:
    res, t = fetch_sifted(one_feed(rss([])), deadline=5.0, clock=lambda: 10.0)
    assert t.requests == [] and res.res["error"] == "DeadlineReached: source deadline reached"
    res, t = fetch_sifted(one_feed(rss([])), deadline=13.0, clock=lambda: 10.0)
    assert t.requests[0]["deadline"] - time.monotonic() <= 3.0  # the run's deadline bounds the feed's 20 s


def test_a_tls_failure_is_a_failed_feed_with_its_reason_and_no_fallback() -> None:
    res, t = fetch_sifted(one_feed(rss([]), tls=True))
    assert len(t.requests) == 1  # one attempt, verified; never retried without verification
    assert res.res == {"ok": False, "error": "SSLCertVerificationError: " + str(fetching_tls_error())[:100], "http": None,
                       "rate_limited": False, "seconds": 0.0}  # fmt: skip


def fetching_tls_error() -> Exception:
    import ssl

    return ssl.SSLCertVerificationError(1, parity_news.TLS_ERROR)


def test_a_doctype_feed_fails_alone_and_the_run_goes_on() -> None:
    feeds = refresh_feeds()
    feeds[FEED_URLS["Sifted"]] = {
        "body": '<!DOCTYPE rss [<!ENTITY a "x">]><rss><channel>'
        + item("&a;", "https://sifted.eu/a", rfc(1))
        + "</channel></rss>"
    }
    ri = run_inputs()
    p = refresh.plan(ri.news, TODAY, NOW, run_id="news-20261112-100000-abcd", clock=lambda: 0.0)
    results = refresh.fetch_all(
        p, FeedFetch(transport=FixtureTransport(feeds), resolver=fixture_resolver, clock=lambda: 0.0)
    )
    out = refresh.apply(ri, results, today=TODAY, now=NOW, run_id=p.run_id, clock=lambda: 0.0)
    sifted = out.record["per_feed"]["Sifted"]
    assert sifted["ok"] is False and sifted["error"].startswith("UnsafeXMLError: refused feed XML: DOCTYPE")
    assert out.record["per_feed"]["Tech.eu"]["ok"] is True and out.record["status"] == "partial"


# ------------------------------------------------------------------ the phases
def test_apply_reads_the_current_inputs_and_keeps_a_write_committed_during_the_fetch() -> None:
    """The pure analogue of the paused-fetch test: phase 1 and 2 over one snapshot, a backcast committed, then phase 3
    over the CURRENT inputs: the signal and the run's own re-derivation are both in the stored record."""
    before = run_inputs()
    p = refresh.plan(before.news, TODAY, NOW, run_id="news-20261112-100000-abcd", clock=lambda: 0.0)
    results = refresh.fetch_all(
        p, FeedFetch(transport=FixtureTransport(refresh_feeds()), resolver=fixture_resolver, clock=lambda: 0.0)
    )
    w = writes.add_backcast_signal(before.news, {"event_id": "nw-r-other", "date": "2026-10-01",
                                                 "url": "https://evidence.invented.example/birchwood", "text": "an early lab page"},
                                   today=TODAY, now=NOW, new_hex=lambda: "0" * 32, validation=before.validation)  # fmt: skip
    n, v = writes.applied(before.news, before.validation, w)
    current = refresh.RunInputs(n, v)
    snapshot = copy.deepcopy(current)
    out = refresh.apply(current, results, today=TODAY, now=NOW, run_id=p.run_id, clock=lambda: 0.0)
    assert current == snapshot  # never mutated
    rec = next(c for c in out.changed_events if c.event_id == "nw-r-other")
    assert rec.record["event_type"] == "funding" and rec.passes == ("rederive",)
    assert rec.record["backcast"][-1]["url"] == "https://evidence.invented.example/birchwood"
    stale = refresh.apply(before, results, today=TODAY, now=NOW, run_id=p.run_id, clock=lambda: 0.0)
    assert not stale.events_doc["events"]["nw-r-other"]["backcast"]  # the pre-fetch snapshot would have lost it


def test_the_answer_is_the_old_shape_after_a_completed_run() -> None:
    out = parity_news.new_refresh(GOLDEN, strict=True)[0]["runs"][0]["outcome"]
    a = out.answer
    assert list(a) == ["started", "run_id", "job", "last", "last_ok", "events_total"]
    assert (
        a["started"] is True
        and a["run_id"] == out.run_id
        and re.fullmatch(r"news-20261112-100000-[0-9a-f]{4}", out.run_id)
    )
    assert a["job"] == {"running": False, "run_id": out.run_id, "stage": "done", "trigger": "manual", "started_at": "2026-11-12T10:00:00",
                        "feeds_done": 12, "feeds_total": 12, "ingested": True, "new": out.record["new"], "merged": out.record["merged"]}  # fmt: skip
    assert a["last"] == json.loads(out.run_line) and out.run_line == json.dumps(
        out.record, ensure_ascii=False, sort_keys=True
    )
    assert out.appends[-1] == ("runs", out.run_line) and out.deferred == (refresh.WATCH_REASON,)
    assert out.documents["news/run_state.json"] == {"running": False}


def test_one_berlin_clock() -> None:
    aware = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)  # 10:00 in Berlin
    assert refresh.new_run_id(aware, lambda: "beef" + "0" * 28) == "news-20261112-100000-beef"
    assert refresh._pubdate("Tue, 10 Nov 2026 23:30:00 -0700") == "2026-11-11"  # Berlin, whatever the machine's zone
    assert refresh._pubdate("2026-11-11T23:30:00Z") == "2026-11-12"
    assert refresh._pubts("Tue, 10 Nov 2026 23:30:00 -0700") == "2026-11-11T06:30"
    assert refresh._pubts("Tue, 10 Nov 2026 00:00:00 +0000") == ""  # midnight: no time
    ri = run_inputs()
    p = refresh.plan(ri.news, TODAY, aware, run_id="news-x", clock=lambda: 0.0)
    results = refresh.fetch_all(
        p, FeedFetch(transport=FixtureTransport(refresh_feeds()), resolver=fixture_resolver, clock=lambda: 0.0)
    )
    out = refresh.apply(ri, results, today=TODAY, now=aware, run_id="news-x", clock=lambda: 0.0)
    assert out.record["started_at"] == out.record["completed_at"] == "2026-11-12T10:00:00"
    assert out.record["per_feed"]["Startbase"]["cooldown_until"] == "2026-11-12T10:30:00"


def test_remeasure_alone_defers_the_nominations_and_records_history_on_request() -> None:
    ri = run_inputs()
    ev = refresh.remeasure(ri, today=TODAY, now=NOW, record_history=True)
    assert ev.result["nominated"] == [] and ev.lines("source_history")
    deferred = [json.loads(line) for line in ev.lines("source_log") if '"nomination_deferred"' in line]
    assert deferred and all(d["reason"] == news_evaluate.NOMINATION_REASON for d in deferred)
    assert json.loads(ev.lines("source_log")[-1])["event"] == "evaluated"
    assert set(ev.documents) == {"news/source_state.json", "news/source_metrics.json"}
    again = refresh.remeasure(ri, today=TODAY, now=NOW)
    assert again.lines("source_history")  # no history line yet in these inputs: due


def test_a_second_run_over_the_written_documents_is_idempotent() -> None:
    got, problems = parity_news.new_refresh(GOLDEN, strict=False)
    assert problems == []
    second = got["runs"][1]["outcome"]
    assert second.record["merged"] == 0 and not any("ingest" in c.passes for c in second.changed_events)

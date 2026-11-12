"""Review 026b, offline (no database, no network): the scan and the research match the OLD code's goldens
(``oracle_founder_radar_fetch.json``, ``python -m projectzero.ops.parity_founder_radar_fetch goldens``) over fixture
sites; every request goes through ``core.net`` with the per-caller policies (checked BEFORE each send, the first one
included), the GitHub token reaches the GitHub API only, a 403 / 429 stops the later GitHub sources before they are
contacted, the deadline cuts a source off, the write phase merges onto the CURRENT documents, and no live name
resolution ever happens."""

from __future__ import annotations

import ast
import copy
import json
import socket
from collections.abc import Iterator, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from projectzero.core import net
from projectzero.founder_radar import collectors, fetching, research, routes, scanning
from projectzero.founder_radar.fetching import Fetch
from projectzero.ops import parity_founder_radar_fetch as parity
from projectzero.ops.parity_founder_radar_fetch import (
    CLOCK,
    LARK,
    QUILL,
    SETS,
    TOKEN,
    FixtureTransport,
    compare_goldens,
    expand,
    fixture_resolver,
    gh_search,
    gh_user,
)
from projectzero.ops.parity_ranking import OLD_REPO

GOLDEN: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "golden_v1" / "oracle_founder_radar_fetch.json").read_text(
        encoding="utf-8"
    )
)
NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)  # 10:00 in Berlin
TODAY = date(2026, 11, 12)
OLD_FR = OLD_REPO / "backend" / "src" / "projectzero" / "domain" / "founder_radar"


@pytest.fixture(autouse=True)
def no_system_resolver(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every test: the system resolver fails the test if anything calls it (only fixture resolvers answer)."""

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("the system resolver was called")

    monkeypatch.setattr(net, "default_resolver", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    yield


def inputs_of(docs: dict[str, Any]) -> routes.Inputs:
    st = parity.Store(docs)
    return st.inputs()


def frozen(inp: routes.Inputs) -> str:
    return json.dumps({k: (sorted(v) if isinstance(v, frozenset) else v) for k, v in inp.__dict__.items()})


class Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class SteppingTransport(FixtureTransport):
    """Advances ``clock`` past the deadline when it is asked for ``trip``."""

    def __init__(self, sites: Mapping[str, Any], clock: Clock, trip: str) -> None:
        super().__init__(sites)
        self.clock = clock
        self.trip = trip

    def send(self, target: net.Target, method: str, headers: Mapping[str, str], body: bytes | None, timeout: float,
             max_bytes: int, deadline: float | None = None, *, truncate: bool = False) -> net.Response:  # fmt: skip
        r = super().send(target, method, headers, body, timeout, max_bytes, deadline, truncate=truncate)
        if self.requests[-1]["url"] == self.trip:
            self.clock.t += 10_000
        return r


def run_scan(name: str, *, fetch: Fetch | None = None, token: Any = "set", docs: dict[str, Any] | None = None,
             sites: dict[str, Any] | None = None) -> tuple[scanning.ScanOutcome, FixtureTransport]:  # fmt: skip
    spec = SETS[name]
    docs = docs if docs is not None else spec["docs"]()
    transport = FixtureTransport(sites if sites is not None else spec["sites"]())
    fetch = fetch or Fetch(transport=transport, resolver=fixture_resolver(spec["names"]))
    inp = inputs_of(docs)
    before = frozen(inp)
    o = scanning.scan(inp, sources_doc=docs.get("radar_sources.json"), cursor_doc=docs.get("radar_cursor.json"),
                      fetch=fetch, now=NOW, token=spec["token"] if token == "set" else token, clock=lambda: 0.0)  # fmt: skip
    assert frozen(inp) == before, "the input was mutated"
    return o, (fetch.transport if isinstance(fetch.transport, FixtureTransport) else transport)


def rows(o: scanning.ScanOutcome) -> dict[str, dict[str, Any]]:
    return {r["id"]: r for r in o.health["sources"]}


# ------------------------------------------------------------------ the goldens
def test_the_new_side_matches_the_old_goldens() -> None:
    assert compare_goldens(GOLDEN) == []


def test_provenance_and_inputs_are_current() -> None:
    assert GOLDEN["provenance"]["old_revision"] == "6c739b9cb6ca2517b845e381d39a36c50eccc59e"
    assert GOLDEN["provenance"]["old_dirty"] is False
    assert GOLDEN["provenance"]["hashseed"] == "0"
    assert GOLDEN["clock"] == CLOCK
    assert set(GOLDEN["sets"]) == set(SETS)
    for name, spec in SETS.items():
        g = GOLDEN["sets"][name]
        assert json.dumps(g["docs"]) == json.dumps(json.loads(json.dumps(spec["docs"]()))), name
        assert g["sites"] == json.loads(json.dumps(spec["sites"]())), name
        assert g["steps"] == json.loads(json.dumps(spec["steps"])), name
        assert g["names"] == spec["names"] and g["token"] == spec["token"], name


def test_the_comparison_catches_a_changed_value_a_changed_order_and_an_extra_request() -> None:
    for mutate in ("answer", "order", "request"):
        g = copy.deepcopy(GOLDEN)
        s = g["sets"]["research"]
        steps = expand(s["expected"])
        if mutate == "answer":
            steps[0]["answer"]["body"]["researched"][0]["pages"] = 99
        elif mutate == "order":
            pages = steps[0]["stored"]["radar_research.json"]["domains"][LARK]["pages"]
            steps[0]["stored"]["radar_research.json"]["domains"][LARK]["pages"] = dict(reversed(list(pages.items())))
        else:
            steps[0]["requests"].append(steps[0]["requests"][0])
        s["expected"] = steps  # expanded rows are valid compact rows (nothing is marked repeated)
        assert compare_goldens({"clock": g["clock"], "sets": {"research": s}}), mutate


def test_the_golden_covers_the_planned_cases() -> None:
    scan_403 = expand(GOLDEN["sets"]["scan_403"]["expected"])[0]
    notes = {r["id"]: r for r in scan_403["answer"]["body"]["sources"]}
    assert notes["gh-corvath"]["note"].startswith("HTTPError: HTTP Error 403: Forbidden")
    assert notes["gh-dunmarrow"]["status"] == "not attempted — rate limited"
    assert "(reset: 10:00)" in notes["gh-dunmarrow"]["note"]  # 1794474000 = 09:00 UTC = 10:00 in Berlin
    scan_429 = expand(GOLDEN["sets"]["scan_429"]["expected"])[0]
    assert "(reset: 120 s)" in {r["id"]: r for r in scan_429["answer"]["body"]["sources"]}["gh-aldermoor"]["note"]
    res = expand(GOLDEN["sets"]["research"]["expected"])
    pages = res[0]["stored"]["radar_research.json"]["domains"][LARK]["pages"]
    reasons = {u.rsplit("/", 1)[-1]: p["reason"] for u, p in pages.items()}
    assert reasons["company"].startswith("blocked: non-HTML content type")
    assert reasons["press"].startswith("blocked: cross-origin redirect")
    assert reasons["blog"] == "blocked: scheme not allowed (https only)"
    assert reasons["careers"] == "skipped: robots.txt disallows"
    assert reasons["contact"] == "skipped: login / access restricted"
    assert pages["https://larkspur.example/news"]["chars"] < 400_001  # the oversize body, cut
    q = res[4]["stored"]["radar_research.json"]["domains"]
    assert {p["reason"] for p in q[QUILL]["pages"].values()} >= {"blocked: too many redirects", "fetch error: connection reset by the fixture"}  # fmt: skip
    assert all(p["reason"].startswith("blocked: DNS resolves to non-public address (10.0.0.7)")
               for p in res[5]["stored"]["radar_research.json"]["domains"]["dom:pellucid.example"]["pages"].values())  # fmt: skip


# ------------------------------------------------------------------ the policies, observed at the transport
def api_fetch(sites: dict[str, Any], names: dict[str, list[str]] | None = None) -> tuple[Fetch, FixtureTransport]:
    t = FixtureTransport(sites)
    return Fetch(transport=t, resolver=fixture_resolver(names or {})), t


def test_a_github_redirect_to_another_origin_is_never_sent_and_the_initial_url_must_be_the_api() -> None:
    f, t = api_fetch({"https://api.github.com/users/a": parity.redirect("https://evil.example/users/a")})
    with pytest.raises(net.UnsafeURLError, match=r"only https://api.github.com"):
        fetching.github_json(f, "https://api.github.com/users/a", TOKEN)
    assert [r["url"] for r in t.requests] == ["https://api.github.com/users/a"]  # no second request
    for bad in ("http://api.github.com/users/a", "https://api.github.com.evil.example/x", "https://user@api.github.com/x",
                "https://api.github.com:8443/x", "https://api.openalex.org/works"):  # fmt: skip
        with pytest.raises(net.UnsafeURLError):
            fetching.github_json(f, bad, TOKEN)
    assert len(t.requests) == 1  # a forbidden initial URL is never sent


def test_api_redirects_stay_on_the_origin_and_are_bounded() -> None:
    sites = {"https://api.github.com/a": parity.redirect("/b"), "https://api.github.com/b": parity.redirect("/c"),
             "https://api.github.com/c": parity.ok_json({"ok": 1}), "https://api.github.com/d": parity.redirect("/a")}  # fmt: skip
    f, t = api_fetch(sites)
    assert fetching.github_json(f, "https://api.github.com/a") == {"ok": 1}  # 2 redirects: allowed
    with pytest.raises(net.UnsafeURLError, match="more than 2 redirects"):
        fetching.github_json(f, "https://api.github.com/d")
    assert [r["url"].rsplit("/", 1)[-1] for r in t.requests] == ["a", "b", "c", "d", "a", "b"]  # /c never sent again


def test_the_token_reaches_the_github_api_only() -> None:
    _o, t = run_scan("scan_403")
    assert t.requests
    for r in t.requests:
        auth = r["headers"].get("Authorization")
        if r["url"].startswith("https://api.github.com/"):
            assert auth == "Bearer " + TOKEN
        else:
            assert auth is None, r["url"]  # OpenAlex
        assert r["headers"]["User-Agent"] == fetching.USER_AGENT
    _o2, t2 = run_scan("scan_403", token=None)
    assert all("Authorization" not in r["headers"] for r in t2.requests)  # no token, no header
    sites = parity.research_sites()
    f, rt = api_fetch(sites, parity.NAMES)
    inp = inputs_of(SETS["research"]["docs"]())
    research.research(inp, {"key": LARK}, fetch=f, now=NOW, today=TODAY)
    assert any(r["url"].startswith("https://github.com/") for r in rt.requests)
    assert all("Authorization" not in r["headers"] for r in rt.requests)  # company and github.com pages: never


def test_a_403_and_a_429_stop_the_later_github_sources_before_they_are_contacted() -> None:
    o, t = run_scan("scan_403")
    sent = [r["url"] for r in t.requests]
    assert gh_search("Corvath") in sent
    for city in ("Dunmarrow", "Eskerholm", "Fjellvik"):
        assert gh_search(city) not in sent
        assert rows(o)[f"gh-{city.lower()}"]["status"] == "not attempted — rate limited"
    assert o.cursor["rate_limited"] and "(reset: 10:00)" in o.cursor["note"] and o.cursor["next"] == 3
    assert scanning.TOKEN_HINT in rows(o)["gh-corvath"]["note"]  # decision b: the env token, not config.json
    assert any(u.startswith("https://api.openalex.org/") for u in sent)  # the other sources still ran
    o, t = run_scan("scan_429")
    sent = [r["url"] for r in t.requests]
    assert gh_user("tarnwick") in sent and gh_search("Aldermoor") not in sent
    assert "(reset: 120 s)" in o.cursor["note"] and o.cursor["next"] == 0


def test_an_error_status_that_is_not_a_rate_limit_is_just_a_failed_source() -> None:
    sites = SETS["scan_403"]["sites"]()
    sites[parity.gh_search("Corvath")] = {"status": 502, "headers": {}, "body": "bad gateway"}
    o, t = run_scan("scan_403", sites=sites)
    assert rows(o)["gh-corvath"]["note"] == "HTTPError: HTTP Error 502: Bad Gateway"
    assert gh_search("Dunmarrow") in [r["url"] for r in t.requests] and not o.cursor["rate_limited"]


def test_d_the_guard_makes_a_non_public_address_or_an_oversize_body_a_failed_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docs = SETS["scan_403"]["docs"]()
    t = FixtureTransport(SETS["scan_403"]["sites"]())
    f = Fetch(transport=t, resolver=fixture_resolver({"api.openalex.org": ["10.1.2.3"]}))
    o, _ = run_scan("scan_403", fetch=f, docs=docs)
    assert rows(o)["oa-de-robotics"]["status"] == "failed"
    assert rows(o)["oa-de-robotics"]["note"].startswith("UnsafeURLError: ")
    assert not any(r["url"].startswith("https://api.openalex.org/") for r in t.requests)  # never sent
    monkeypatch.setattr(fetching, "API_MAX_BYTES", 50)
    o, _ = run_scan("scan_403")
    assert rows(o)["gh-aldermoor"]["note"].startswith("ResponseTooLargeError: ")


def test_research_redirects_off_the_host_or_to_http_are_not_followed_and_forbidden_urls_never_sent() -> None:
    sites = {"https://co.example/a": parity.redirect("https://other.example/a"),
             "https://co.example/b": parity.redirect("http://co.example/b", 302),
             "https://co.example/c": parity.redirect("https://www.co.example/c"),
             "https://www.co.example/c": parity.html("<p>ok</p>"),
             "https://co.example/d": {"status": 302, "headers": {}, "body": ""},
             "https://co.example/e": parity.redirect("https://github.com/e"),
             "https://github.com/x": parity.redirect("https://www.github.com/x")}  # fmt: skip
    f, t = api_fetch(sites, {"private.co.example": ["192.168.1.4"]})
    rec = fetching.research_page(f, "https://co.example/a", "co.example")
    assert (rec["status"], rec["final_url"], rec["reason"]) == (301, "https://other.example/a", "blocked: cross-origin redirect to other.example")  # fmt: skip
    rec = fetching.research_page(f, "https://co.example/b", "co.example")
    assert (rec["status"], rec["reason"]) == (0, "blocked: scheme not allowed (https only)")
    rec = fetching.research_page(f, "https://co.example/c", "co.example")  # the old www. equivalence
    assert (rec["status"], rec["final_url"], rec["reason"], rec["body"]) == (
        200,
        "https://www.co.example/c",
        "",
        "<p>ok</p>",
    )
    rec = fetching.research_page(f, "https://co.example/d", "co.example")
    assert (rec["status"], rec["final_url"], rec["reason"]) == (
        302,
        "https://co.example/d",
        "blocked: redirect without location",
    )
    rec = fetching.research_page(f, "https://co.example/e", "co.example")  # the company rule: its own host only
    assert rec["reason"] == "blocked: cross-origin redirect to github.com"
    rec = fetching.research_page(f, "https://github.com/x", fetching.GITHUB_WEB, exact=True)  # github.com exactly
    assert rec["reason"] == "blocked: off the canonical company host (www.github.com)"
    sent = [r["url"] for r in t.requests]
    assert sent == ["https://co.example/a", "https://co.example/b", "https://co.example/c", "https://www.co.example/c",
                    "https://co.example/d", "https://co.example/e", "https://github.com/x"]  # fmt: skip
    for url, why in (("http://co.example/x", "scheme not allowed"), ("https://u:p@co.example/", "userinfo"),
                     ("https://private.co.example/", "non-public address (192.168.1.4)"), ("https://10.0.0.1/", "non-public IP literal"),
                     ("https://localhost/", "local host name"), ("https://elsewhere.example/", "off the canonical company host"),
                     ("https://github.com/acme", "off the canonical company host (github.com)")):  # fmt: skip
        rec = fetching.research_page(f, url, "co.example")
        assert rec["reason"].startswith("blocked: ") and why in rec["reason"], (url, rec["reason"])
    assert len(t.requests) == len(sent)  # none of the forbidden initial URLs was sent


def test_research_pages_are_pinned_to_the_checked_address_and_resolved_once() -> None:
    calls: list[str] = []

    def table(host: str) -> list[str]:
        calls.append(host)
        return ["93.184.216.40"]

    t = FixtureTransport({"https://co.example/": parity.html("<p>hi</p>")})
    rec = fetching.research_page(Fetch(transport=t, resolver=table), "https://co.example", "co.example")
    assert rec["status"] == 200 and rec["pinned_ip"] == "93.184.216.40"
    assert t.requests[0]["ip"] == "93.184.216.40" and calls == ["co.example"]


def test_the_research_body_is_cut_at_the_old_cap_and_only_html_is_read() -> None:
    sites = {"https://co.example/big": parity.html("<p>Founded in 2024.</p>", pad=500_000, tail="<p>Late Name, Co-Founder</p>"),
             "https://co.example/pdf": parity.html("%PDF", ctype="application/pdf")}  # fmt: skip
    f, _t = api_fetch(sites)
    rec = fetching.research_page(f, "https://co.example/big", "co.example")
    assert len(rec["body"]) == fetching.MAX_BODY and "Late Name" not in rec["body"]
    rec = fetching.research_page(f, "https://co.example/pdf", "co.example")
    assert (rec["status"], rec["body"], rec["reason"]) == (200, "", "blocked: non-HTML content type (application/pdf)")


# ------------------------------------------------------------------ the rate-limit reset
def test_reset_text_is_the_berlin_wall_time_or_the_retry_after_seconds() -> None:
    assert fetching.reset_text({"X-RateLimit-Reset": "1794474000"}) == "10:00"  # winter: UTC+1
    assert fetching.reset_text({"x-ratelimit-reset": "1782900000"}) == "12:00"  # 2026-07-01 10:00 UTC, summer: UTC+2
    assert fetching.reset_text({"Retry-After": "120"}) == "120 s"
    assert fetching.reset_text({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}) == "Wed, 21 Oct 2026 07:28:00 GMT s"
    assert fetching.reset_text({}) == "unknown" and fetching.reset_text(None) == "unknown"
    assert fetching.reset_text({"X-RateLimit-Reset": "9" * 30}) == "unknown"
    e = fetching.HTTPError("u", 429, {"Retry-After": "7"})
    assert str(e) == "HTTP Error 429: Too Many Requests" and e.headers == {"retry-after": "7"}
    assert fetching.is_rate_limit(e) and fetching.is_rate_limit(fetching.HTTPError("u", 403, {}))
    assert not fetching.is_rate_limit(fetching.HTTPError("u", 404, {})) and not fetching.is_rate_limit(
        ValueError("403")
    )


# ------------------------------------------------------------------ the deadline
def test_a_scan_past_its_deadline_fetches_nothing_and_keeps_the_cursor() -> None:
    clock = Clock()
    t = FixtureTransport(SETS["scan_403"]["sites"]())
    f = Fetch(transport=t, resolver=fixture_resolver({}), deadline=clock.t, clock=clock)
    o, _ = run_scan("scan_403", fetch=f)
    assert t.requests == []
    r = rows(o)
    assert {r[k]["note"] for k in r if r[k]["kind"] in ("github_users", "openalex_works")} == {scanning.DEADLINE_NOTE}
    assert r["pz-data"]["status"] == "ok" and r["epo"]["status"] == "config_required"  # no network needed
    assert o.cursor["next"] == 0 and o.health["totals"]["cities_attempted"] == 0  # the cities wait for the next run


def test_the_deadline_cutting_a_source_off_fails_it_and_the_later_sources_are_not_fetched() -> None:
    clock = Clock()
    trip = "https://api.github.com/users/orinthal"
    t = SteppingTransport(SETS["scan_403"]["sites"](), clock, trip)
    f = Fetch(transport=t, resolver=fixture_resolver({}), deadline=clock.t + 60, clock=clock)
    o, _ = run_scan("scan_403", fetch=f)
    r = rows(o)
    assert r["gh-aldermoor"]["status"] == "failed" and r["gh-aldermoor"]["note"] == scanning.CUT_NOTE
    assert (
        r["gh-brisenthal"]["note"] == scanning.DEADLINE_NOTE and r["oa-de-robotics"]["note"] == scanning.DEADLINE_NOTE
    )
    assert [x["url"] for x in t.requests] == [gh_search("Aldermoor"), trip]  # nothing after the cut
    assert o.outcome.people is not None  # pz_data still ingested
    assert not any("orinthal" in str(p.get("aliases")) for p in o.outcome.people)  # the cut source kept nothing
    assert o.cursor["next"] == 1  # only the cut city counted as attempted


def test_the_deadline_leaves_a_research_company_unfinished_and_unwritten() -> None:
    clock = Clock()
    sites = parity.research_sites()
    t = SteppingTransport(sites, clock, "https://larkspur.example/team")
    f = Fetch(transport=t, resolver=fixture_resolver(parity.NAMES), deadline=clock.t + 60, clock=clock)
    inp = inputs_of(SETS["research"]["docs"]())
    o = research.research(inp, {"keys": [LARK, QUILL]}, fetch=f, now=NOW, today=TODAY).outcome
    assert [(r["key"], r["ok"], r["error"]) for r in o.body["researched"]] == [
        (LARK, False, research.DEADLINE_NOTE), (QUILL, False, research.DEADLINE_NOTE)]  # fmt: skip
    assert not any("quillbright" in r["url"] for r in t.requests)  # the later company was never contacted
    assert o.research is None  # nothing finished, nothing written


def test_the_queue_resumes_a_company_the_deadline_cut_off() -> None:
    clock = Clock()
    docs = SETS["research"]["docs"]()
    inp = inputs_of(docs)
    plan = research.queue_plan(inp, None, {"batch": 2}, today=TODAY, now=NOW)
    first, second = (c["key"] for c in plan.companies)
    t = FixtureTransport(parity.research_sites())
    f = Fetch(transport=t, resolver=fixture_resolver(parity.NAMES), deadline=clock.t, clock=clock)
    out = research.research_apply(
        inp, research.research_fetch(plan, f, now=NOW, today=TODAY), queue_doc=None, now=NOW, today=TODAY
    )
    assert out.queue is not None and out.queue["pending"][:2] == [first, second] and out.queue["in_progress"]
    assert out.queue["failed"] == {} and out.queue["done"] == []
    assert [p["error"] for p in out.outcome.body["processed"]] == [research.DEADLINE_NOTE] * 2
    again = research.research_queue(inp, out.queue, {"batch": 2}, fetch=Fetch(transport=t, resolver=fixture_resolver(parity.NAMES)), now=NOW, today=TODAY)  # fmt: skip
    assert [p["ok"] for p in again.outcome.body["processed"]] == [True, True]
    assert again.queue is not None and again.queue["done"] == [first, second]


def test_fetch_turns_a_core_net_deadline_into_deadline_reached() -> None:
    class Slow(FixtureTransport):
        def send(self, *a: Any, **k: Any) -> net.Response:
            raise net.FetchError("source deadline reached")

    f = Fetch(transport=Slow({}), resolver=fixture_resolver({}))
    with pytest.raises(fetching.DeadlineReached):
        fetching.github_json(f, "https://api.github.com/x")
    with pytest.raises(fetching.DeadlineReached):  # never recorded as a page
        fetching.research_page(f, "https://co.example/", "co.example")


# ------------------------------------------------------------------ the write phase: onto the CURRENT documents
def test_scan_apply_merges_onto_the_people_as_they_are_at_write_time() -> None:
    spec = SETS["scan_403"]
    docs = spec["docs"]()
    inp = inputs_of(docs)
    plan = scanning.scan_plan(inp, sources_doc=docs["radar_sources.json"], cursor_doc=docs["radar_cursor.json"])
    f = Fetch(transport=FixtureTransport(spec["sites"]()), resolver=fixture_resolver({}))
    result = scanning.scan_fetch(plan, f, now=NOW, token=TOKEN, clock=lambda: 0.0)
    edited = copy.deepcopy(docs)
    kestrel = edited["people.json"]["people"][0]
    kestrel["human_judgment"] = "met at the demo day"  # an operator edit committed during the fetch
    edited["people.json"]["people"].append(
        {"id": "p-added-meanwhile", "name": "Added Meanwhile", "provenance": "user_provided"}
    )
    current = inputs_of(edited)
    o = scanning.scan_apply(current, result, cursor_doc={"next": 0, "batches_completed": 7}, now=NOW, clock=lambda: 0.0)
    assert o.outcome.people is not None
    by_id = {p["id"]: p for p in o.outcome.people}
    assert by_id["p-kestrel42-0102"]["human_judgment"] == "met at the demo day"  # kept, and merged into
    assert "p-added-meanwhile" in by_id and "p-added-meanwhile" not in o.outcome.people_changed
    assert o.cursor["batches_completed"] == 8  # the CURRENT cursor


def test_research_apply_keeps_decisions_made_during_the_crawl_and_only_adds_proposals() -> None:
    docs = SETS["research"]["docs"]()
    inp = inputs_of(docs)
    f = Fetch(transport=FixtureTransport(parity.research_sites()), resolver=fixture_resolver(parity.NAMES))
    first = research.research(inp, {"key": LARK}, fetch=f, now=NOW, today=TODAY).outcome
    assert first.research is not None and first.research_changed == [LARK]
    docs["radar_research.json"] = first.research
    inp = inputs_of(docs)
    plan = research.research_plan(inp, {"key": LARK, "refresh": True}, today=TODAY, now=NOW)
    fetched = research.research_fetch(plan, f, now=NOW, today=TODAY)
    current = copy.deepcopy(first.research)
    dom = current["domains"][LARK]
    some = next(iter(dom["proposals"]))
    dom["proposals"][some]["status"] = "confirmed"  # a review committed during the crawl
    dom["history"].append({"at": "2026-11-12 10:00:30", "confirmed": [some]})
    dom["pairings"] = {"x": {"person": "p-rhea-quintaval-0042"}}
    del dom["proposals"][next(k for k in dom["proposals"] if k != some)]  # (cannot happen; shows ADD-only)
    out = research.research_apply(
        routes.Inputs(**(inp.__dict__ | {"research": current})), fetched, now=NOW, today=TODAY
    )
    assert out.outcome.research is not None
    d2 = out.outcome.research["domains"][LARK]
    assert d2["proposals"][some]["status"] == "confirmed" and d2["history"][-1]["confirmed"] == [some]
    assert d2["pairings"] == {"x": {"person": "p-rhea-quintaval-0042"}}
    assert set(d2["proposals"]) == set(first.research["domains"][LARK]["proposals"])  # the missing one re-added by id
    assert d2["previous_runs"][-1]["pages"] == len(first.research["domains"][LARK]["pages"]) and d2["done"]
    assert out.outcome.body["researched"][0]["new"] == 0  # re-added from the working record, not counted new


def test_a_cached_or_unchanged_run_writes_nothing_and_the_inputs_are_never_mutated() -> None:
    docs = SETS["research"]["docs"]()
    f = Fetch(transport=FixtureTransport(parity.research_sites()), resolver=fixture_resolver(parity.NAMES))
    inp = inputs_of(docs)
    before = frozen(inp)
    first = research.research(inp, {"key": LARK}, fetch=f, now=NOW, today=TODAY).outcome
    assert frozen(inp) == before
    docs["radar_research.json"] = first.research
    inp = inputs_of(docs)
    before = frozen(inp)
    cached = research.research(inp, {"key": LARK}, fetch=f, now=NOW, today=TODAY).outcome
    assert cached.body["researched"][0]["cached"] is True and cached.research is None
    q = research.research_queue(inp, None, {"batch": 1}, fetch=f, now=NOW, today=TODAY)
    assert frozen(inp) == before
    assert q.queue is not None and q.queue["started"] == "2026-11-12 10:00"


def test_a_non_integer_batch_raises_as_before() -> None:
    with pytest.raises(ValueError):
        research.queue_plan(inputs_of(SETS["research"]["docs"]()), None, {"batch": "many"}, today=TODAY, now=NOW)


def test_one_berlin_clock_stamps_the_scan() -> None:
    o, _ = run_scan("scan_429")
    assert o.health["scan_time"] == o.cursor["last"] == "2026-11-12 10:00"  # 09:00 UTC
    assert {r["attempted_at"] for r in o.health["sources"] if r["attempted_at"]} == {"2026-11-12 10:00"}
    assert o.outcome.metrics is not None and o.outcome.metrics["latest"]["date"] == "2026-11-12"


# ------------------------------------------------------------------ the port carries the old literals
def _literals(path: Path) -> set[str]:
    return {n.value for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}  # fmt: skip


NEW_TEXTS = {
    scanning.TOKEN_HINT,
    scanning.DEADLINE_NOTE,
    scanning.CUT_NOTE,
    research.DEADLINE_NOTE,
    "crawl",
    "no_domain",
    "queue",
}  # the plan decisions, and the job kinds / route of the three-phase split


@pytest.mark.skipif(not OLD_FR.exists(), reason="the old repository is not checked out")
def test_the_ported_collectors_scan_and_research_carry_only_old_texts() -> None:
    old: set[str] = set()
    for p in [*OLD_FR.glob("*.py"), OLD_FR.parents[1] / "api" / "routers" / "founder_radar.py"]:
        old |= _literals(p)
    for module in (collectors, scanning, research):
        src = Path(module.__file__ or "")
        tree = ast.parse(src.read_text(encoding="utf-8"))
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body and isinstance(n.body[0], ast.Expr)}  # fmt: skip
        ours = {n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs}  # fmt: skip
        new_only = sorted(v for v in ours if v not in old and v not in NEW_TEXTS and not v.startswith("__"))
        assert new_only == [], (src.name, new_only[:12])


# ── Codex H-221: the read budget, the effective port, a plain-text robots.txt ───────────────────────────────────────
def _page_fetch(sites: dict[str, Any]) -> tuple[Fetch, FixtureTransport]:
    t = FixtureTransport(sites)
    return Fetch(transport=t, resolver=fixture_resolver({})), t


def test_research_reads_at_most_the_old_cap_and_keeps_the_prefix_even_beyond_the_shared_limit() -> None:
    from projectzero.founder_radar.catalog import MAX_BODY

    big = "<html><body>" + "x" * (net.MAX_BYTES + 10) + "</body></html>"  # beyond the shared 8 MB cap too
    f, t = _page_fetch(
        {"https://larkspur.example/": {"status": 200, "headers": {"Content-Type": "text/html"}, "body": big}}
    )
    rec = fetching.research_page(f, "https://larkspur.example/", "larkspur.example")
    assert rec["status"] == 200 and rec["reason"] == ""
    assert rec["body"] == big[:MAX_BODY]  # the old read(MAX_BODY) prefix, not lost
    assert [(r["max_bytes"], r["truncate"]) for r in t.requests] == [(MAX_BODY, True)]  # the READ budget


@pytest.mark.parametrize("exact", [False, True])
def test_a_same_host_redirect_to_another_port_is_never_sent(exact: bool) -> None:
    host = "github.com" if exact else "larkspur.example"
    start = f"https://{host}/team"
    f, t = _page_fetch({start: {"status": 301, "headers": {"Location": f"https://{host}:8443/team"}, "body": ""}})
    rec = fetching.research_page(f, start, host, exact=exact)
    assert rec["reason"] == f"blocked: cross-origin redirect to {host}:8443"
    assert [r["url"] for r in t.requests] == [start]  # no second request after the port change
    f2, t2 = _page_fetch({})
    rec2 = fetching.research_page(f2, f"https://{host}:8443/team", host, exact=exact)
    assert rec2["reason"] == "blocked: off the canonical company origin (port 8443)" and t2.requests == []


def test_a_plain_text_robots_txt_is_honoured_and_a_disallowed_path_is_never_requested() -> None:
    sites = dict(SETS["research"]["sites"]())
    sites["https://quillbright.example/robots.txt"] = {
        "status": 200, "headers": {"Content-Type": "text/plain"}, "body": "User-agent: *\nDisallow: /team\n"}  # fmt: skip
    t = FixtureTransport(sites)
    f = Fetch(transport=t, resolver=fixture_resolver(SETS["research"]["names"]))
    robots = fetching.research_robots(f, "https://quillbright.example/robots.txt", "quillbright.example")
    assert robots["status"] == 200 and "Disallow: /team" in robots["body"]  # the old code dropped it as non-HTML
    out = research.research(inputs_of(SETS["research"]["docs"]()), {"key": QUILL}, fetch=f, now=NOW, today=TODAY)
    assert out.outcome.body["ok"]
    urls = [r["url"] for r in t.requests]
    assert "https://quillbright.example/robots.txt" in urls
    assert not [u for u in urls if u.rstrip("/").endswith("quillbright.example/team")]  # disallowed: never requested

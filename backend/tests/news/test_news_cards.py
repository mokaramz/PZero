"""Review 028d, offline (no database, no network, no live model): the News card phase (``news/cards.py``) matches the
OLD ``_make_cards`` golden (``oracle_news_cards.json``, ``python -m projectzero.ops.parity_news cards-goldens``) with
only the declared differences; the prompt carries the untrusted-data sentence in its SYSTEM message; the selection,
the stale rule and the card-only write; the deadline (the fake-clock regression of plan revision 2: the budget
expires during a retry delay); the paused-provider stale cases; and paid calls off by default (the conftest)."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from projectzero.core.inference import budget, gateway
from projectzero.core.inference.budget import BERLIN
from projectzero.core.inference.providers import FakeProvider, ProviderError
from projectzero.core.inference.store import InMemoryBudgetStore
from projectzero.news import cards, refresh
from projectzero.ops.parity_news import CARD_CASES, CARDS_GOLDEN, cards_world, compare_cards, read_golden

GOLDEN: dict[str, Any] = read_golden(CARDS_GOLDEN)
WORLD: dict[str, Any] = cards_world()
NOW = datetime(2026, 11, 12, 10, 30, tzinfo=BERLIN)
ON = {"PZ_AI_PAID": "on"}
REPLY = json.dumps(
    {
        "what_happened": "Invented Volt Holdings bought an invented grid company.",
        "why_it_matters": "An invented consolidation signal.",
        "the_company": "An invented grid software company.",
        "vc_lesson": "Invented lesson: watch who buys.",
        "watch_next": ["an invented integration", "an invented second deal"],
    }
)


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


class Phase4:
    """Phase 4 over an in-memory events document: the gateway with a fake provider, an in-memory budget store and a
    writer that re-reads the current event, applies ``still_fits`` / ``with_card`` and records the history passes."""

    def __init__(self, responder: Callable[[Any, str], Any] | None = None, *, env: dict[str, str] | None = None,
                 providers: dict[str, Any] | None = None) -> None:  # fmt: skip
        self.doc = copy.deepcopy(WORLD)
        self.clock = Clock()
        self.store = InMemoryBudgetStore(monotonic=self.clock, sleep=self.clock.sleep)
        self.fake = FakeProvider(responder or (lambda m, model: REPLY), paid=True)
        self.env = ON if env is None else env
        self.providers = {"deepinfra": self.fake} if providers is None else providers
        self.history: list[tuple[str, str]] = []
        self.writes: list[str] = []
        self.waits: list[float] = []

    def sleep(self, s: float) -> None:
        self.waits.append(s)
        self.clock.sleep(s)

    def call(self, job: cards.CardJob, deadline: float | None) -> gateway.Result:
        return cards.call_card(job, deadline, run_id=cards.card_run_id(NOW), store=self.store, monotonic=self.clock,
                               clock=lambda: NOW, env=self.env, providers=self.providers, sleep=self.sleep)  # fmt: skip

    def write(self, job: cards.CardJob, card: dict[str, Any]) -> cards.WriteVerdict:
        self.writes.append(job.event_id)
        current = self.doc["events"].get(job.event_id)
        if not cards.still_fits(current, job):
            return "stale"
        assert current is not None
        self.doc["events"][job.event_id] = cards.with_card(current, card)
        self.history.append((job.event_id, "card"))
        return "written"

    def run(self, jobs: list[cards.CardJob] | None = None, within: float | None = None) -> cards.CardOutcome:
        jobs = cards.plan_cards(self.doc) if jobs is None else jobs
        deadline = None if within is None else self.clock.t + within
        return cards.run_cards(jobs, call=self.call, write=self.write, deadline=deadline, monotonic=self.clock)


# ------------------------------------------------------------------ the golden
def test_the_card_phase_matches_the_old_golden_with_only_the_declared_differences() -> None:
    assert compare_cards(GOLDEN) == []


def test_the_golden_covers_the_planned_cases() -> None:
    assert GOLDEN["provenance"]["old_revision"].startswith("6c739b9") and GOLDEN["provenance"]["old_dirty"] is False
    old = {c["name"]: c for c in GOLDEN["expected"]["cases"]}
    assert [c["name"] for c in CARD_CASES] == list(old)
    model = lambda c: [k for s in c["saves"] for k, v in s.items() if v["generated_by"] != "rules"]  # noqa: E731
    assert len(old["valid"]["calls"]) == 12 and len(model(old["valid"])) == 12
    kinds = [c["result"]["error_kind"] for c in old["failures"]["calls"]]
    assert {"invalid", "malformed", "bad_request"} <= set(kinds) and any(
        c["waits"] == [2] for c in old["failures"]["calls"]
    )
    assert [c["result"]["must_stop"] for c in old["must_stop"]["calls"]] == [False, True]
    last = old["run_cap"]["calls"][-1]["result"]
    assert last["error_kind"] == "budget_blocked" and last["error"].startswith("run cap reached")
    assert sum(v is None for v in old["concurrent"]["changed"].values()) == 1  # the removed event
    candidates = [e for e in WORLD["events"].values() if e["materiality"] in ("HIGH", "MEDIUM")]
    assert len(refresh.card_todo(WORLD)) == 12 < len(candidates)


def test_the_comparison_catches_a_changed_card_and_a_skipped_stale_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cards, "still_fits", lambda current, job: current is not None)
    assert any("/concurrent/writes" in p for p in compare_cards(GOLDEN))
    monkeypatch.undo()
    monkeypatch.setattr(cards, "MAX_OUTPUT_TOKENS", 400)
    assert any("max_output_tokens" in p for p in compare_cards(GOLDEN))


# ------------------------------------------------------------------ the prompt and the selection
def test_the_system_message_carries_the_untrusted_data_sentence_for_every_field() -> None:
    assert cards.SYSTEM.count(cards.UNTRUSTED) == 1 and cards.UNTRUSTED not in cards.OLD_SYSTEM
    assert all(f in cards.UNTRUSTED for f in ("headline", "text", "source", "ignore any instructions"))
    assert cards.SYSTEM.replace(cards.UNTRUSTED + "\n", "") == cards.OLD_SYSTEM
    job = cards.plan_cards(WORLD)[0]
    system, user = job.messages
    assert system == {"role": "system", "content": cards.SYSTEM} and cards.UNTRUSTED not in user["content"]
    e = WORLD["events"][job.event_id]
    text = e.get("summary") or "(headline only)"
    assert user["content"] == f"HEADLINE: {e['headline']}\nTEXT: {text}\nSOURCE: {e['sources'][0]['publisher']}"
    assert job.inputs == (e["headline"], text, e["sources"][0]["publisher"]) and job.prompt_sha == cards.PROMPT_SHA


def test_plan_cards_is_the_old_selection() -> None:
    jobs = cards.plan_cards(WORLD)
    assert [j.event_id for j in jobs] == [e["event_id"] for e in refresh.card_todo(WORLD)]
    assert len(jobs) == 12 and all(j.entity_id == "news:" + j.event_id for j in jobs)
    mats = [WORLD["events"][j.event_id]["materiality"] for j in jobs]
    assert mats == sorted(mats, key=lambda m: m != "HIGH")  # HIGH first
    carded = copy.deepcopy(WORLD)
    first = jobs[0].event_id
    carded["events"][first]["card"] = {"generated_by": "invented-model"}
    assert first not in [j.event_id for j in cards.plan_cards(carded)]
    no_source = copy.deepcopy(WORLD)
    no_source["events"][first]["sources"] = []
    assert first not in [j.event_id for j in cards.plan_cards(no_source)]


def test_still_fits_and_with_card() -> None:
    job = cards.plan_cards(WORLD)[0]
    e = WORLD["events"][job.event_id]
    assert cards.still_fits(e, job) and cards.still_fits({**e, "card": None}, job)
    assert not cards.still_fits(None, job)
    assert not cards.still_fits({**e, "card": {"generated_by": "invented-model"}}, job)
    assert not cards.still_fits({**e, "headline": e["headline"] + " (changed)"}, job)
    assert not cards.still_fits({**e, "summary": "An invented new text."}, job)
    assert not cards.still_fits({**e, "sources": [{**e["sources"][0], "publisher": "Invented Wire"}]}, job)
    assert not cards.still_fits({**e, "materiality": "LOW"}, job)
    assert not cards.still_fits({**e, "geo": ["US"]}, job)
    before = copy.deepcopy(e)
    out = cards.with_card({**e, "backcast": [{"date": "2026-01"}]}, {"x": 1, "generated_by": "m"})
    assert out["card"] == {"x": 1, "generated_by": "m"} and out["backcast"] == [{"date": "2026-01"}]
    assert list(out) == list(e) and {k: v for k, v in out.items() if k not in ("card", "backcast")} == {
        k: v for k, v in e.items() if k not in ("card", "backcast")
    }
    assert e == before


def test_the_note_and_the_run_id() -> None:
    out = cards.CardOutcome(made=2, attempted=3, stale=1, late=0, stopped="deadline", usd=0.000241)
    assert cards.card_note("news-20261112-103000-abcd", out) == (
        '{"cards": {"attempted": 3, "late": 0, "made": 2, "stale": 1, "stopped": "deadline", "usd": 0.000241}, '
        '"run_id": "news-20261112-103000-abcd"}'
    )
    assert cards.card_run_id(datetime(2026, 11, 12, 9, 30, 5, tzinfo=UTC)) == "news-20261112-103005"  # Berlin
    assert cards.card_run_id(datetime(2026, 11, 12, 10, 30, 5)) == "news-20261112-103005"  # naive: Berlin wall time


# ------------------------------------------------------------------ the loop
def _res(ok: bool = True, kind: str = "", error: str = "", usd: float = 0.0) -> gateway.Result:
    return gateway.Result(ok=ok, role="CHEAP", model="m", data={"what_happened": "x"} if ok else None,
                          error_kind=kind, error=error, usd=usd)  # fmt: skip


@pytest.mark.parametrize(
    ("failure", "stopped"),
    [
        (_res(False, "auth", "HTTP 401"), "must_stop"),
        (_res(False, "budget_blocked", "run cap reached for news-x ($0.0600 spent + $0.0001 next > $0.05)"), "run_cap"),
        (_res(False, "budget_blocked", "day budget reached ($1.0000 spent ...)"), "must_stop"),
        (_res(False, "deadline", "the deadline passed"), "deadline"),
        (_res(False, "invalid", "missing vc_lesson"), None),
    ],
)
def test_run_cards_stops_as_the_old_loop(failure: gateway.Result, stopped: str | None) -> None:
    jobs = cards.plan_cards(WORLD)[:3]
    results = [_res(usd=0.001), failure, _res(usd=0.001)]
    writes: list[str] = []

    def write(job: cards.CardJob, card: dict[str, Any]) -> cards.WriteVerdict:
        writes.append(job.event_id)
        assert card == {"what_happened": "x", "generated_by": "m"}
        return "written"

    out = cards.run_cards(jobs, call=lambda job, d: results.pop(0), write=write, deadline=None)
    assert out.stopped == stopped and out.attempted == (2 if stopped else 3)
    assert writes == [jobs[0].event_id] + ([] if stopped else [jobs[2].event_id]) and out.made == len(writes)


def test_a_late_write_and_a_failing_call() -> None:
    jobs = cards.plan_cards(WORLD)[:3]
    out = cards.run_cards(jobs, call=lambda job, d: _res(), write=lambda job, card: "late", deadline=None)
    assert (out.late, out.made, out.attempted, out.stopped) == (1, 0, 1, "deadline")

    def boom(job: cards.CardJob, d: float | None) -> gateway.Result:
        raise RuntimeError("invented bug")

    out = cards.run_cards(jobs, call=boom, write=lambda job, card: "written", deadline=None)
    assert (out.attempted, out.made, out.stopped) == (3, 0, None)  # the old loop: rules kept, the run goes on


def test_no_time_left_calls_nothing() -> None:
    p = Phase4()
    out = p.run(within=0.0)
    assert (out.attempted, out.stopped) == (0, "deadline") and p.fake.calls == [] and p.store.rows == []


# ------------------------------------------------------------------ plan revision 2: the deadline regression
def test_the_budget_expires_during_a_retry_delay() -> None:
    """The first card's first attempt fails with ``server``; the 2 s retry wait would end past the deadline: no second
    dispatch, no card write (the story keeps its rules card), the dispatched attempt settled (one row, its estimate),
    the note says ``deadline``."""
    p = Phase4(FakeProvider.scripted([ProviderError("server", "HTTP 503")]).responder)
    job = cards.plan_cards(p.doc)[0]
    rules = copy.deepcopy(p.doc["events"][job.event_id]["card"])
    out = p.run(within=1.0)
    assert p.fake.dispatches == 1 and p.waits == [] and p.writes == []
    assert p.doc["events"][job.event_id]["card"] == rules and rules["generated_by"] == "rules"
    est = budget.estimate_usd({"input": 0.09, "output": 0.18, "cached_input": 0.018},
                              len(json.dumps(job.messages, ensure_ascii=False)), cards.MAX_OUTPUT_TOKENS)  # fmt: skip
    (row,) = p.store.rows
    assert (row.outcome, row.error_kind, row.usd, row.usd_source, row.entity_ref) == (
        "error", "server", est, "estimated", job.entity_id)  # fmt: skip
    assert p.store.reservations == {}
    assert (out.attempted, out.made, out.stopped, out.usd) == (1, 0, "deadline", round(est, 6))
    assert json.loads(cards.card_note("news-run", out))["cards"]["stopped"] == "deadline"


def test_an_accepted_card_after_the_deadline_is_not_written_but_its_charge_is_kept() -> None:
    p = Phase4()

    def slow(messages: Any, model: str) -> str:
        p.clock.t += 30.0  # the provider answers after the deadline
        return REPLY

    p.fake.responder = slow
    out = p.run(within=10.0)
    assert (out.attempted, out.made, out.late, out.stopped) == (1, 0, 1, "deadline") and p.writes == []
    (row,) = p.store.rows
    assert row.outcome == "ok" and row.usd > 0 and p.store.reservations == {}


# ------------------------------------------------------------------ plan revision 2: stale results (paused provider)
def test_a_headline_changed_while_the_provider_is_paused_is_stale_and_keeps_its_charge() -> None:
    p = Phase4()
    job = cards.plan_cards(p.doc)[0]
    rules = copy.deepcopy(p.doc["events"][job.event_id]["card"])

    def paused(messages: Any, model: str) -> str:  # an operator edit committed while the call is out
        p.doc["events"][job.event_id]["headline"] += " (invented correction)"
        return REPLY

    p.fake.responder = paused
    out = p.run([job])
    assert (out.made, out.stale, out.stopped) == (0, 1, None)
    assert p.doc["events"][job.event_id]["card"] == rules
    (row,) = p.store.rows
    assert row.outcome == "ok" and row.usd > 0 and row.entity_ref == job.entity_id and out.usd == round(row.usd, 6)


def test_an_unrelated_backcast_while_the_provider_is_paused_is_kept_and_the_card_written() -> None:
    p = Phase4()
    job = cards.plan_cards(p.doc)[0]
    signal = {"date": "2026-03-01", "kind": "known_early_signal", "family": "lab_spinout", "text": "Invented signal"}

    def paused(messages: Any, model: str) -> str:
        p.doc["events"][job.event_id]["backcast"] = [signal]
        p.history.append((job.event_id, "backcast"))
        return REPLY

    p.fake.responder = paused
    out = p.run([job])
    stored = p.doc["events"][job.event_id]
    assert (out.made, out.stale) == (1, 0) and stored["backcast"] == [signal]
    assert stored["card"]["generated_by"] == "deepseek-ai/DeepSeek-V4-Flash"
    assert stored["card"]["what_happened"] == "Invented Volt Holdings bought an invented grid company."
    assert p.history == [(job.event_id, "backcast"), (job.event_id, "card")]


# ------------------------------------------------------------------ paid calls off (the default)
@pytest.mark.parametrize("fake", [True, False], ids=["fake-provider", "configured-provider"])
def test_paid_off_by_default_makes_no_dispatch_and_keeps_every_rules_card(fake: bool) -> None:
    """The conftest forces ``PZ_AI_PAID=off`` and empty keys; ``env=None`` reads them as production would."""
    p = Phase4(env={}, providers=None)
    p.env = None  # type: ignore[assignment]
    if not fake:
        p.providers = None  # type: ignore[assignment]  # the configured DeepInfra client: no key, nothing sent
    before = {k: copy.deepcopy(v.get("card")) for k, v in p.doc["events"].items()}
    out = p.run()
    assert p.fake.calls == [] and p.writes == []
    assert {k: v.get("card") for k, v in p.doc["events"].items()} == before
    assert (out.attempted, out.made, out.stopped, out.usd) == (1, 0, "must_stop", 0.0)
    (row,) = p.store.rows
    assert row.usd == 0.0 and row.outcome in ("disabled", "error") and p.store.reservations == {}
    assert row.error_kind == ("disabled" if fake else "not_configured")

"""Review 035b: the machine-triage cascade and automatic triage, pure parts (no database, no model, no network).

Ports the intent of the old ``test_shadow_triage.py`` (stage 0, schema retry, founders, reject support, the veto and
its bases, the locked prompt sha, the budget stop inside the veto), ``test_veto_repair.py`` (``basis_as_proposal``),
``test_auto_triage.py`` (selection, the skip rule, timeouts kept) and ``test_provider_resilience.py`` (plain reasons,
bounded retries then manual), plus the golden parity's pure check.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Any

import pytest

from projectzero.core.inference.gateway import Result
from projectzero.core.inference.providers import FakeProvider
from projectzero.dealflow.triage import auto, auto_rules, card, cascade
from projectzero.dealflow.triage import cascade_rules as rules
from projectzero.jobs.catalog import scan_note
from projectzero.ops import parity_triage_cascade as ptc

LOCKED = "e0d09eb2df5b733692b2a8ef7dfd1e69bf190db4e23b4a13b8e3ced08bb8cc63"
GOOD = {"proposal": "KEEP", "entity_type": "VENTURE", "capital_stage": "PRE_COMPANY", "sector": "industrial AI",
        "themes": ["industrial_autonomy"], "founders": [], "reasons": ["fits industrial autonomy"], "missing": [],
        "confidence": "medium"}  # fmt: skip
REJ = {**GOOD, "proposal": "REJECT", "reject_basis": "OFF_THESIS", "reject_evidence": "a consumer photo app"}


def cand(cid: str = "c1", desc: str = "Robo Labs builds a consumer photo app", **kw: Any) -> dict[str, Any]:
    return {"id": cid, "name": "Robo Labs", "description": desc, "geo": ["DACH"], "decision": "new", "source": "EPFL",
            "discovery_tier": "pre_company", "source_url": f"https://x.example/{cid}", **kw}  # fmt: skip


class Script:
    """A ``cascade.Call`` answering per model from a list (a dict: a JSON reply; a str: raw text; a ``Result``:
    as is); every call is recorded."""

    def __init__(self, flash: list[Any], veto: list[Any] | None = None) -> None:
        self.q = {card.CHEAP_MODEL: list(flash), card.VETO_MODEL: list(veto or [])}
        self.calls: list[dict[str, Any]] = []

    def __call__(self, role: str, messages: list[dict[str, str]], **kw: Any) -> Result:
        model = kw["model"] or card.CHEAP_MODEL
        self.calls.append({"role": role, "model": model, **{k: kw[k] for k in ("purpose", "use_cache", "extra_body")}})
        out = self.q[model].pop(0)
        if isinstance(out, Result):
            return out
        text = json.dumps(out) if isinstance(out, dict) else str(out)
        res = Result(ok=False, role=role, provider="fake", model=model, text=text, usd=0.001)
        data = None
        try:
            data = json.loads(text)
        except ValueError:
            res.error_kind, res.error = "malformed", "reply contained no parseable JSON"
            return res
        try:
            res.data, res.ok = kw["validate"](data), True
        except ValueError as e:
            res.error_kind, res.error = "invalid", str(e)
        return res


def one(c: dict[str, Any], s: Script, prev: Any = None) -> Any:
    return cascade.triage_one(c, prev, call=s, mdl=card.CHEAP_MODEL, run_id="triage-20261113-100000-abcd",
                              proposed_at="2026-11-13T10:00:00", counts=Counter())  # fmt: skip


# ------------------------------------------------------------------ the prompt and the rules
def test_the_system_prompt_is_the_locked_one() -> None:
    assert rules.system_prompt_sha() == rules.LOCKED_PROMPT_SHA == LOCKED and cascade.PROMPT_VERSION == "triage-v3"
    system = rules.messages_for(cand())[0]["content"]
    assert "Missing or thin information is never a reject basis: resolve it to RESEARCH." in system
    assert "A Series A or B, or a large first round, is NOT late-stage by itself" in system
    assert all(b in system for b in rules.REJECT_BASES)
    assert rules.messages_for(cand())[1]["content"] == f"<candidate>\n{card.candidate_card(cand())}\n</candidate>"


@pytest.mark.parametrize(("name", "desc", "junk"), [
    ("(406)", "", "J2"), ("05.10.2026 14:00", "", "J2"), ("Thursday, November 5, 2026 ·", "", "J2"),
    ("[vc_row]", "", "J1"), ("Robo Labs", "", ""), ("UNKNOWN", "Robo Labs builds robots", ""),
])  # fmt: skip
def test_stage0_is_junk_only(name: str, desc: str, junk: str) -> None:
    assert (
        rules.stage0_junk({"name": name, "description": desc}).startswith(junk)
        if junk
        else not rules.stage0_junk({"name": name, "description": desc})
    )


def test_late_stage_and_geography_need_the_deterministic_checks() -> None:
    text = "description: Robo raised a EUR 25 million Series A to scale its fusion reactor"
    assert rules.reject_support_problem("LATE_STAGE", "EUR 25 million Series A", text)
    text2 = "description: Robo was acquired by Siemens; it closed a Series C in 2024"
    assert rules.reject_support_problem("LATE_STAGE", "acquired by Siemens", text2) == ""
    loc = "location: Boston USA geo=US"
    assert rules.reject_support_problem("OUTSIDE_GEOGRAPHY", "Boston USA", loc, {"geo": ["US"], "country": "USA"}) == ""
    assert "workspace eu" in rules.reject_support_problem("OUTSIDE_GEOGRAPHY", "Boston USA", loc, {"geo": ["DACH"]})
    token = rules.OVERRIDE.set({"eu": set(), "na": {"DACH"}})  # the run's workspace override (the cut's one seam)
    try:
        assert rules.reject_support_problem("OUTSIDE_GEOGRAPHY", "Boston USA", loc, {"geo": ["DACH"]}) == ""
    finally:
        rules.OVERRIDE.reset(token)


def test_bases_agree_and_combine() -> None:
    assert rules.bases_agree("NOT_AN_ENTITY", "NON_VENTURE") and not rules.bases_agree("LATE_STAGE", "OFF_THESIS")
    assert rules._combine(REJ, None, "timeout") == ("RESEARCH", "veto unavailable (timeout) — reject not confirmed")
    assert rules._combine(REJ, {**REJ, "proposal": "WATCH", "model_proposal": "WATCH"})[0] == "WATCH"


# ------------------------------------------------------------------ the validator (old test_veto_repair)
def check(text: str, data: Any) -> dict[str, Any]:
    return cascade.validator_for(text)(data)


def test_the_observed_veto_replies_are_repaired_and_flagged() -> None:
    text = "name: Thursday, November 26, 2026 · BayWa Co-Working Space\nsectors: space"
    obs = {"proposal": "NOT_AN_ENTITY", "entity_type": "NOT_AN_ENTITY", "reject_basis": "NOT_AN_ENTITY",
           "confidence": "high", "reject_evidence": "Thursday, November 26, 2026 · BayWa Co-Working Space",
           "reasons": ["an event listing"]}  # fmt: skip
    out = check(text, obs)
    assert out["proposal"] == out["model_proposal"] == "REJECT" and any(
        "formatting repaired" in f for f in out["flags"]
    )
    weak = check(text, {**obs, "reject_evidence": "not in the text"})
    assert weak["proposal"] == "RESEARCH" and any("REJECT downgraded to RESEARCH" in f for f in weak["flags"])
    for bad in ({"reject_basis": "LATE_STAGE"}, {"entity_type": "VENTURE"}, {"proposal": "MAYBE"}, {"reasons": []},
                {"confidence": "absolute"}, {"proposal": None}):  # fmt: skip
        with pytest.raises(ValueError):
            check(text, {**obs, **bad})
    with pytest.raises(ValueError, match="reply is not a JSON object"):
        check(text, "NOT_AN_ENTITY")


def test_the_validator_keeps_the_old_error_texts() -> None:
    with pytest.raises(ValueError) as e:
        check("x", {})
    assert str(e.value) == "proposal: Field required; reasons: Field required; confidence: Field required"
    with pytest.raises(ValueError) as e:
        check("x", {**GOOD, "reasons": ["a", 2, None]})
    assert str(e.value) == "reasons.1: Input should be a valid string; reasons.2: Input should be a valid string"
    with pytest.raises(ValueError) as e:
        check("x", {**GOOD, "reasons": []})
    assert str(e.value) == "reasons: List should have at least 1 item after validation, not 0"


def test_founders_must_be_verbatim_and_unknown_themes_are_dropped() -> None:
    out = check("description: Ada Quill builds robots", {**GOOD, "founders": ["Ada Quill", "Nobody"],
                                                          "themes": ["defence", "made_up"]})  # fmt: skip
    assert out["founders"] == ["Ada Quill"] and out["themes"] == ["defence"]
    assert out["flags"] == ["dropped 1 founder name(s) not present in the candidate text",
                            "dropped unknown theme(s): made_up"]  # fmt: skip


# ------------------------------------------------------------------ one candidate (old test_shadow_triage)
def test_a_non_reject_makes_exactly_one_flash_call_and_no_veto() -> None:
    s = Script([GOOD])
    e = one(cand(), s)
    assert [c["model"] for c in s.calls] == [card.CHEAP_MODEL] and s.calls[0]["purpose"] == "shadow_triage"
    assert e["status"] == "proposed" and e["proposal"] == "KEEP" and e["veto_mode"] == "no_thinking"


def test_a_supported_reject_gets_one_veto_without_thinking() -> None:
    s = Script([REJ], [REJ])
    e = one(cand(), s)
    assert [(c["role"], c["model"]) for c in s.calls] == [("CHEAP", card.CHEAP_MODEL), ("STANDARD", card.VETO_MODEL)]
    assert s.calls[1]["purpose"] == "shadow_triage_veto" and s.calls[1]["extra_body"] == rules.NO_THINKING
    assert e["proposal"] == "REJECT" and e["stage"] == "veto" and "both reject" in e["path"]


@pytest.mark.parametrize("first", [{**REJ, "reject_basis": None}, {**REJ, "reject_evidence": ""},
                                   {**REJ, "reject_evidence": "based in California"}])  # fmt: skip
def test_an_unsupported_reject_is_downgraded_and_never_reaches_the_veto(first: dict[str, Any]) -> None:
    s = Script([first])
    e = one(cand(), s)
    assert len(s.calls) == 1 and e["proposal"] == "RESEARCH" and e["model_proposal"] == "REJECT"


def test_one_schema_retry_uncached_then_needs_human_never_a_reject() -> None:
    s = Script(["garbage", {**REJ, "proposal": "MAYBE"}])
    e = one(cand(), s)
    assert [c["use_cache"] for c in s.calls] == [True, False]
    assert (e["status"], e["proposal"], e["route"], e["schema_retry"]) == (
        "needs_human",
        "RESEARCH",
        "HUMAN_REVIEW",
        True,
    )
    s2 = Script(["garbage", GOOD])
    assert one(cand(), s2)["status"] == "proposed" and len(s2.calls) == 2


def test_a_timeout_is_an_error_entry_and_a_stop_kind_stops() -> None:
    timeout = Result(ok=False, role="CHEAP", model=card.CHEAP_MODEL, error_kind="timeout", error="timed out after 60s")
    e = one(cand(), Script([timeout]))
    assert e["status"] == "error" and e["proposal"] is None and e["error_kind"] == "timeout"
    blocked = Result(ok=False, role="STANDARD", error_kind="budget_blocked", error="run cap reached")
    out = one(cand(), Script([REJ], [blocked]))  # the first call fits, the veto does not: the run stops
    assert isinstance(out, cascade.Stop) and out.text == "budget_blocked: run cap reached"


def test_the_skip_rule_makes_no_call_and_stage0_none() -> None:
    c = cand()
    prev = {"status": "proposed", "input_sha": card.card_sha(c), "model": card.CHEAP_MODEL,
            "veto_model": card.VETO_MODEL, "veto_mode": "no_thinking"}  # fmt: skip
    s = Script([])
    assert isinstance(one(c, s, prev), cascade.Skipped) and s.calls == []
    assert not isinstance(one(c, Script([GOOD]), {**prev, "veto_mode": "thinking"}), cascade.Skipped)
    junk = one({**cand(), "name": "(406)", "description": ""}, Script([]))
    assert junk["stage"] == "stage0" and junk["proposal"] == "REJECT" and junk["usd"] == 0.0
    old = one(c, Script([GOOD]), {**prev, "prompt_version": "triage-v2", "input_sha": "f" * 16, "proposal": "WATCH"})
    assert old["previous"]["prompt_version"] == "triage-v2"


# ------------------------------------------------------------------ automatic triage (old test_auto_triage / resilience)
def state(cands: list[dict[str, Any]], props: dict[str, Any] | None = None, rs: dict[str, Any] | None = None,
          runs: list[dict[str, Any]] | None = None) -> auto.State:  # fmt: skip
    return auto.State(new=[c for c in cands if c.get("decision") == "new"], proposals=props or {}, runs=runs or [],
                      rs=rs or {}, aliases={}, seqs={}, config={})  # fmt: skip


RUN = "2026-10-10 09:00:00"
NOW = datetime(2026, 10, 10, 9, 30)


def test_the_selection_never_takes_the_backlog_or_decided_ones() -> None:
    cs = [cand("d1", decision="rejected", first_seen_run=RUN), cand("b1", first_seen_run="2026-09-01 00:00:00"),
          cand("n1", first_seen_run=RUN), cand("o1", last_observed=RUN)]  # fmt: skip
    assert auto.select(state(cs), RUN, NOW) == ["n1", "o1"]
    stale = {"b1": {"status": "proposed", "prompt_version": "triage-v3", "input_sha": "0" * 16}}
    assert auto.select(state(cs, stale), RUN, NOW) == ["b1", "n1", "o1"]  # stale: re-selected
    pending = [{"pending": [{"id": "b1", "reason": "x"}], "failed": []}]
    assert auto.select(state(cs, runs=pending), RUN, NOW) == ["b1", "n1", "o1"]


def test_retries_are_polite_bounded_then_manual_never_dropped() -> None:
    rs: dict[str, Any] = {}
    raw = 'HTTP 429: {"error":{"message":"Model busy, retry later","code":"engine_overloaded"}}'
    item = auto_rules._retry_item(rs, "a", "Co a", "rate_limited", raw, NOW)
    assert item["retry"] == "automatic" and "DeepInfra was temporarily overloaded" in item["reason"]
    assert rs["a"]["next_eligible"] == "2026-10-10T09:45:00" and rs["a"]["attempts"] == 1
    for _ in range(auto_rules.MAX_AUTO_RETRIES):
        item = auto_rules._retry_item(rs, "a", "Co a", "rate_limited", raw, NOW)
    assert item["retry"] == "manual" and "Retry now" in item["reason"] and rs["a"]["next_eligible"] is None
    st = state([cand("a")], rs=rs)
    assert auto.retry_due(st, NOW) == [] and auto.retry_due(st, NOW, force=True) == ["a"]  # still there for Retry now
    off = auto_rules._retry_item({}, "b", "Co b", "disabled", "", NOW, count=False)
    assert off["attempts"] == 0 and off["category"] == "BUDGET" and "PZ_AI_PAID is not 'on'" in off["reason"]


def test_reasons_come_from_the_error_kind_in_plain_words() -> None:
    assert auto.reason("disabled", "disabled: anything") == (
        "paid AI is switched off (PZ_AI_PAID is not 'on') — kept; it runs once paid AI is on again"
    )
    assert auto.reason("budget_blocked", "").startswith("the configured AI budget limit was reached — kept")
    assert auto.reason("not_configured", "").startswith("DeepInfra is not configured (DEEPINFRA_API_KEY missing)")
    assert (
        auto.reason("server", "error: RuntimeError: boom")
        == "DeepInfra had a temporary server error — kept for an automatic retry"
    )
    rec = {"state": "failed", "selected": 1, "counts": {}, "pending": [{"reason": "rate_limited: HTTP 429 {x}", "id": "m"}],
           "failed": []}  # fmt: skip
    shown = auto_rules.plain(rec)
    assert shown is not None and "{" not in shown["pending"][0]["reason"] and "No data was lost" in shown["summary"]


def test_the_hourly_job_sees_when_paid_calls_would_be_refused() -> None:
    fake = FakeProvider(paid=True, name="deepinfra")
    assert auto.would_refuse({"env": {}, "providers": {"deepinfra": fake}})
    assert not auto.would_refuse({"env": {"PZ_AI_PAID": "on"}, "providers": {"deepinfra": fake}})
    assert auto.would_refuse({"env": {"PZ_AI_PAID": "on"}})  # no key for the real provider
    assert not auto.would_refuse({"env": {}, "providers": {"deepinfra": FakeProvider(name="deepinfra")}})  # free
    assert not auto.enabled({"PZ_AUTO_TRIAGE": "off"}, {}) and not auto.enabled({}, {"auto_triage_after_scan": False})
    assert auto.enabled({}, None)


def test_the_scan_jobs_note_never_hides_a_partial_triage() -> None:
    res = {"new": 2, "baseline": 1}
    assert scan_note(res, None) == "2 genuinely new · 1 baseline"
    assert scan_note(res, {"state": "done"}) == "2 genuinely new · 1 baseline"
    tri = {"state": "partial", "triaged": 1, "selected": 3, "stopped": "disabled: paid inference is switched off"}
    assert scan_note(res, tri) == ("2 genuinely new · 1 baseline · machine triage PARTIAL: 1 of 3 — disabled: paid "
                                   "inference is switched off")  # fmt: skip


# ------------------------------------------------------------------ the golden parity's pure check
def test_the_golden_parity_pure_parts() -> None:
    golden = json.loads(ptc.GOLDEN.read_text(encoding="utf-8"))
    assert golden["provenance"]["old_revision"] == "6c739b9cb6ca2517b845e381d39a36c50eccc59e"
    assert golden["provenance"]["old_dirty"] is False and golden["expected"]["blocked"] == []
    assert golden["provenance"]["system_prompt_sha256"] == LOCKED
    assert ptc.compare_pure(golden) == []
    assert golden["input"] == json.loads(json.dumps(ptc.world_input(), ensure_ascii=False))

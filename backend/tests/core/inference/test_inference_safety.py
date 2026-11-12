"""The real provider client's safety (review 029a plan, Verification): a fake transport and fixture resolvers only.

* the key is sent only to the provider host, never on any other request;
* a redirect is never followed; another host or http is refused before anything is sent;
* no key value appears in a Result, the ledger, a log or an error;
* with no key, or with paid calls off, nothing is sent; with a resolver that refuses everything nothing is sent;
* under pytest the real provider refuses to run without an injected transport and resolver (decision b).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytest

from projectzero.core import net
from projectzero.core.inference import gateway
from projectzero.core.inference.budget import BERLIN
from projectzero.core.inference.providers import OpenAICompatibleProvider, ProviderError
from projectzero.core.inference.store import InMemoryBudgetStore

KEY = "sk-INVENTED-do-not-leak-7f3a"
HOST = "api.deepinfra.com"
BASE = "https://api.deepinfra.com/v1/openai"
PUBLIC = "93.184.215.14"
NOW = datetime(2026, 11, 12, 10, 0, tzinfo=BERLIN)
ENV = {"PZ_AI_PAID": "on", "DEEPINFRA_API_KEY": KEY}
MSG = [{"role": "user", "content": "Invented question?"}]
OK_BODY = {
    "model": "deepseek-ai/DeepSeek-V4-Flash",
    "choices": [{"message": {"content": '{"answer": 1}'}}],
    "usage": {"prompt_tokens": 12, "completion_tokens": 4, "estimated_cost": 0.0000021},
}


@dataclass
class FakeTransport:
    """Answers from a queue; records every request that reached it (host, pinned ip, path, headers, body)."""

    answers: list[net.Response | BaseException] = field(default_factory=list)
    sent: list[dict[str, Any]] = field(default_factory=list)

    def send(
        self,
        target: net.Target,
        method: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
        max_bytes: int,
        deadline: float | None = None,
    ) -> net.Response:
        self.sent.append({"host": target.host, "ip": target.ip, "scheme": target.scheme, "method": method,
                          "path": target.path, "headers": dict(headers), "body": body})  # fmt: skip
        answer = self.answers.pop(0) if self.answers else _resp(200, OK_BODY)
        if isinstance(answer, BaseException):
            raise answer
        return answer


def _resp(status: int, body: Any, headers: Mapping[str, str] | None = None) -> net.Response:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return net.Response(f"https://{HOST}/", status, dict(headers or {}), raw)


def provider_host_only(host: str) -> list[str]:
    return [PUBLIC] if host == HOST else []


def refuse_all(host: str) -> list[str]:
    return []


def client(transport: FakeTransport, resolver: net.Resolver = provider_host_only, base: str = BASE) -> Any:
    return OpenAICompatibleProvider("deepinfra", base, "DEEPINFRA_API_KEY", transport=transport, resolver=resolver)


def call(prov: Any, env: Mapping[str, str] = ENV, store: InMemoryBudgetStore | None = None) -> gateway.Result:
    return gateway.complete("CHEAP", MSG, purpose="t", store=store or InMemoryBudgetStore(), clock=lambda: NOW,
                            env=env, providers={"deepinfra": prov}, sleep=lambda s: None)  # fmt: skip


def _no_key_anywhere(r: gateway.Result, store: InMemoryBudgetStore, caplog: pytest.LogCaptureFixture) -> None:
    blob = json.dumps([r.__dict__, [(x.__dict__) for x in store.rows]], default=str)
    assert KEY not in blob and KEY not in caplog.text


def test_request_shape_and_key_only_to_the_provider_host(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    t = FakeTransport()
    store = InMemoryBudgetStore()
    r = call(client(t), store=store)
    assert r.ok and r.data == {"answer": 1} and r.usd == 0.0000021 and r.usd_source == "reported"
    (req,) = t.sent
    assert (req["host"], req["ip"], req["scheme"], req["method"], req["path"]) == (
        HOST, PUBLIC, "https", "POST", "/v1/openai/chat/completions",
    )  # fmt: skip
    assert req["headers"]["Authorization"] == "Bearer " + KEY
    assert req["headers"]["User-Agent"] == "ProjectZero-Inference"
    body = json.loads(req["body"])
    assert body["model"] == "deepseek-ai/DeepSeek-V4-Flash" and body["max_tokens"] == 700
    assert body["response_format"] == {"type": "json_object"} and body["messages"] == MSG
    _no_key_anywhere(r, store, caplog)
    prov = client(FakeTransport())
    call(prov)
    assert KEY not in json.dumps({k: v for k, v in prov.__dict__.items() if k != "_transport"}, default=str)


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_a_redirect_is_never_followed(status: int, caplog: pytest.LogCaptureFixture) -> None:
    t = FakeTransport([_resp(status, b"", {"location": "https://elsewhere.example/steal"})])
    store = InMemoryBudgetStore()
    r = call(client(t), store=store)
    assert len(t.sent) == 1 and t.sent[0]["host"] == HOST  # the redirect target was never contacted
    assert r.error_kind == "bad_request" and "redirects are not followed" in r.error
    assert r.usd_source == "estimated"  # the first request was answered: possibly billed
    _no_key_anywhere(r, store, caplog)


def test_same_host_redirect_is_refused_too() -> None:
    t = FakeTransport([_resp(307, b"", {"location": BASE + "/v2/chat/completions"})])
    r = call(client(t))
    assert len(t.sent) == 1 and r.error_kind == "bad_request"


@pytest.mark.parametrize("base", ["http://api.deepinfra.com/v1/openai", "https://api.deepinfra.com:8443/v1/openai"])
def test_http_or_another_port_is_refused_before_sending(base: str) -> None:
    t = FakeTransport()
    prov = OpenAICompatibleProvider("deepinfra", base, "DEEPINFRA_API_KEY", transport=t, resolver=lambda h: [PUBLIC])
    with pytest.raises(ProviderError) as e:
        prov.complete(model="m", messages=MSG, max_output_tokens=10, temperature=0.0, json_mode=True, timeout_s=5,
                      extra_body=None, env=ENV)  # fmt: skip
    assert e.value.kind == "bad_request" and e.value.dispatched is False and t.sent == []
    assert KEY not in str(e.value)


@pytest.mark.parametrize(
    "url",
    ["https://elsewhere.example/v1/openai/chat/completions", "http://api.deepinfra.com/v1/openai/chat/completions",
     "https://api.deepinfra.com:444/v1/openai/chat/completions", "https://u@api.deepinfra.com/v1/openai/chat/completions",
     "https://api.deepinfra.com.evil.example/v1/openai/chat/completions"],
)  # fmt: skip
def test_the_policy_allows_only_the_provider_origin(url: str) -> None:
    prov = client(FakeTransport())
    prov.policy(BASE + "/chat/completions", 0)
    with pytest.raises(net.UnsafeURLError):
        prov.policy(url, 0)
    with pytest.raises(net.UnsafeURLError):
        prov.policy(BASE + "/chat/completions", 1)  # any second hop is a redirect


def test_header_rule_per_url() -> None:
    prov = client(FakeTransport())
    auth = prov._auth(KEY)
    assert auth(BASE + "/chat/completions") == {"Authorization": "Bearer " + KEY}
    for other in ("http://api.deepinfra.com/v1", "https://api.deepinfra.com:444/x", "https://evil.example/x",
                  "https://user@api.deepinfra.com/x"):  # fmt: skip
        assert auth(other) == {}


def test_nothing_is_sent_without_a_key_or_with_paid_off() -> None:
    for env in ({"PZ_AI_PAID": "on"}, {"PZ_AI_PAID": "on", "DEEPINFRA_API_KEY": "  "}, {"DEEPINFRA_API_KEY": KEY},
                {"PZ_AI_PAID": "off", "DEEPINFRA_API_KEY": KEY}):  # fmt: skip
        t = FakeTransport()
        store = InMemoryBudgetStore()
        r = call(client(t), env=env, store=store)
        assert t.sent == [] and r.error_kind in ("not_configured", "disabled") and r.usd == 0.0
        assert store.reservations == {}
        prov = client(t)
        with pytest.raises(ProviderError) as e:  # the provider refuses on its own as well
            prov.complete(model="m", messages=MSG, max_output_tokens=1, temperature=0.0, json_mode=True,
                          timeout_s=1, extra_body=None, env=env)  # fmt: skip
        assert e.value.dispatched is False and t.sent == []


def test_a_resolver_that_refuses_everything_sends_nothing() -> None:
    t = FakeTransport()
    store = InMemoryBudgetStore()
    r = call(client(t, resolver=refuse_all), store=store)
    assert t.sent == [] and r.error_kind == "bad_request" and "DNS resolution failed" in r.error
    assert r.usd == 0.0 and r.usd_source == "none"  # before dispatch: nothing reached the provider
    assert [x.usd_source for x in store.rows] == ["none"]


def test_real_provider_refuses_under_pytest_without_injection() -> None:
    for prov in (
        OpenAICompatibleProvider("deepinfra", BASE, "DEEPINFRA_API_KEY"),
        OpenAICompatibleProvider("deepinfra", BASE, "DEEPINFRA_API_KEY", transport=FakeTransport()),
        OpenAICompatibleProvider("deepinfra", BASE, "DEEPINFRA_API_KEY", resolver=provider_host_only),
    ):
        r = call(prov)
        assert r.error_kind == "not_configured" and "never runs under tests" in r.error and r.usd == 0.0


def test_the_conftest_guard_blanks_keys_and_paid() -> None:
    import os

    assert os.environ.get("PZ_AI_PAID") == "off" and os.environ.get("DEEPINFRA_API_KEY") == ""
    r = gateway.complete("CHEAP", MSG, purpose="t", store=InMemoryBudgetStore())  # the process environment
    assert r.error_kind == "not_configured" and r.must_stop


@pytest.mark.parametrize(
    ("status", "kind", "retried"),
    [(401, "auth", False), (402, "billing", False), (403, "auth", False), (400, "bad_request", False),
     (408, "timeout", True), (429, "rate_limited", True), (500, "server", True), (503, "server", True)],
)  # fmt: skip
def test_status_mapping_without_the_key(
    status: int, kind: str, retried: bool, caplog: pytest.LogCaptureFixture
) -> None:
    echo = {"error": {"message": f"bad key {KEY}", "code": "invalid"}}  # a provider body echoing the key
    t = FakeTransport([_resp(status, echo, {"Retry-After": "3"})] * 3)
    store = InMemoryBudgetStore()
    waits: list[float] = []
    r = gateway.complete("CHEAP", MSG, purpose="t", store=store, clock=lambda: NOW, env=ENV,
                         providers={"deepinfra": client(t)}, sleep=waits.append)  # fmt: skip
    assert r.error_kind == kind and r.error.startswith(f"HTTP {status} invalid: bad key")
    assert len(t.sent) == (3 if retried else 1) and waits == ([3.0, 6.0] if retried else [])
    assert all(x.usd_source == "estimated" for x in store.rows)  # answered with an error: possibly billed
    _no_key_anywhere(r, store, caplog)


@pytest.mark.parametrize(
    ("exc", "kind", "dispatched"),
    [
        (TimeoutError("timed out"), "timeout", True),
        (ConnectionResetError("reset by peer"), "network", True),
        (ConnectionRefusedError("refused"), "network", False),
        (net.FetchError("source deadline reached"), "timeout", True),
        (net.ResponseTooLargeError("too big"), "malformed", True),
    ],
)
def test_transport_failures_report_their_side_of_dispatch(exc: BaseException, kind: str, dispatched: bool) -> None:
    t = FakeTransport([exc])
    prov = client(t)
    with pytest.raises(ProviderError) as e:
        prov.complete(model="m", messages=MSG, max_output_tokens=1, temperature=0.0, json_mode=True, timeout_s=1,
                      extra_body=None, env=ENV)  # fmt: skip
    assert e.value.kind == kind and e.value.dispatched is dispatched and KEY not in str(e.value)


def test_malformed_body_and_no_usage() -> None:
    t = FakeTransport([_resp(200, b"<html>not json</html>")])
    r = call(client(t))
    assert r.error_kind == "malformed" and r.usd_source == "estimated"
    t = FakeTransport([_resp(200, {"choices": [{"message": {"content": '{"answer": 2}'}}]})])
    store = InMemoryBudgetStore()
    r = call(client(t), store=store)
    assert r.ok and r.data == {"answer": 2} and r.usd_source == "estimated" and len(t.sent) == 1
    assert [(x.outcome, x.usd_source) for x in store.rows] == [("ok", "estimated")]


# ── Codex H-271 ──────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("where", ["caller", "role"])
@pytest.mark.parametrize("option", [{"max_tokens": 5000}, {"max_completion_tokens": 5000}, {"n": 3}, {"best_of": 2}])
def test_a_billing_option_is_refused_before_admission_and_dispatch(where: str, option: dict[str, Any]) -> None:
    from projectzero.core.inference import config as icfg

    t, store = FakeTransport(), InMemoryBudgetStore()
    cfg = icfg.load({"roles": {"CHEAP": {"extra_body": option}}}) if where == "role" else None
    r = gateway.complete("CHEAP", MSG, purpose="t", store=store, clock=lambda: NOW, env=ENV,
                         providers={"deepinfra": client(t)}, sleep=lambda s: None, config=cfg,
                         extra_body=option if where == "caller" else None)  # fmt: skip
    assert not r.ok and r.error_kind == "bad_request" and next(iter(option)) in (r.error or "")
    assert t.sent == [] and store.reservations == {}  # nothing admitted, nothing sent
    assert all(row.usd == 0 for row in store.rows)


def test_the_sent_request_fits_the_reservation() -> None:
    t, store = FakeTransport(), InMemoryBudgetStore()
    r = gateway.complete("CHEAP", MSG, purpose="t", store=store, clock=lambda: NOW, env=ENV,
                         providers={"deepinfra": client(t)}, sleep=lambda s: None, max_output_tokens=321,
                         extra_body={"chat_template_kwargs": {"thinking": False}})  # fmt: skip
    assert r.ok
    body = json.loads(t.sent[0]["body"])
    assert body["max_tokens"] == 321 and "n" not in body and "best_of" not in body  # what admission priced
    assert body["chat_template_kwargs"] == {"thinking": False}  # other provider options still pass


@pytest.mark.parametrize(
    "usage",
    [
        {"prompt_tokens": 12, "completion_tokens": 4, "estimated_cost": -0.5},  # a negative reported cost
        {"prompt_tokens": 12, "completion_tokens": 4, "estimated_cost": float("nan")},
        {"prompt_tokens": -1000, "completion_tokens": 4},  # a negative token count, no reported cost
        {"prompt_tokens": True, "completion_tokens": 4},  # a bool is not a count
        # Codex H-275: a JSON boolean cost is not a cost, through the real response parser
        {"prompt_tokens": 12, "completion_tokens": 4, "estimated_cost": True},  # usable counts: priced
        {"prompt_tokens": 12, "completion_tokens": 4, "estimated_cost": False},
        {"estimated_cost": True},  # no counts either: estimated
        {"estimated_cost": False},
    ],
)
def test_invalid_billing_metadata_never_makes_a_negative_debit(usage: dict[str, Any]) -> None:
    body = {**OK_BODY, "usage": usage}
    t, store = FakeTransport([_resp(200, json.loads(json.dumps(body, allow_nan=True)))]), InMemoryBudgetStore()
    r = call(client(t), store=store)
    assert r.ok and r.data == {"answer": 1} and len(t.sent) == 1  # one successful dispatch
    (row,) = store.rows
    assert row.usd >= 0 and r.usd >= 0
    assert row.tokens_in is None or row.tokens_in >= 0
    assert row.tokens_in is not True
    if usage.get("prompt_tokens") == 12:  # valid usage: priced from it
        assert r.usd_source == "priced" and r.usd > 0
    else:  # neither a usable cost nor usable counts: the estimate
        assert r.usd_source == "estimated" and r.usd > 0
    spend = store.spend(now=NOW, role="CHEAP", entity_id=None, run_id=None)
    assert spend.day == round(r.usd, 6)  # the headroom shrank by exactly that, never grew

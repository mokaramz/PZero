"""Model providers behind the gateway (review 029a): a deterministic fake and an OpenAI-compatible Chat Completions
client on ``core.net`` (the old ``inference/providers.py``, rev 6c739b9).

``OpenAICompatibleProvider`` (plan scope 2, decisions a-c):

* ``POST {base_url}/chat/completions`` through ``core.net.fetch`` (public addresses only, the connection pinned to
  the checked address, TLS verified, 8 MB cap) with a deadline of ``timeout_s`` over the whole exchange;
* a ``policy`` that allows ONLY the provider's own origin (``https``, its host, port 443; a configured ``http`` or
  other port is refused outright) and NO redirect: a
  redirect answer is refused before the next hop is sent; another host or ``http`` is refused before anything is
  sent;
* the key: read from the environment mapping AT CALL TIME, added ONLY by ``headers_for`` for the provider's origin,
  never stored on the object, never logged, never in a ``Reply``, an error message or the ledger (a provider error
  body that echoes it is redacted);
* ``raise_for_status=False``: an error status is mapped to the old kinds (401/403 auth, 402 billing, 429
  rate_limited, 408 timeout, >= 500 server, other 4xx bad_request) with the old compact message and ``Retry-After``;
* every ``ProviderError`` says whether the request was DISPATCHED (plan revision 2): a policy or guard refusal, a
  DNS failure, a refused connection, a missing key or the paid switch off are before dispatch; anything once the
  transport was entered (a timeout, a reset, an error status, a malformed body) is after dispatch;
* it refuses to run with the paid switch off (``PZ_AI_PAID`` not exactly ``on``) or without its key (nothing is
  sent), and UNDER PYTEST it refuses unless both a transport and a resolver were injected (decision b: no test ever
  reaches a live model).

``FakeProvider`` never touches the network: ``responder(messages, model)`` returns the reply text or a ``Reply``, or
raises ``ProviderError`` (``dispatched=False`` for a failure before dispatch); ``scripted`` replays a list.
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, NoReturn, Protocol
from urllib.parse import urlsplit

from projectzero.core import net
from projectzero.core.inference import budget
from projectzero.core.inference import config as icfg
from projectzero.core.inference import errors as perrors

USER_AGENT = "ProjectZero-Inference"
REDACTED = "[redacted]"


@dataclass
class Reply:
    text: str
    usage: dict[str, Any] = field(default_factory=dict)
    reported_usd: float | None = None  # what the provider says it billed, when it says so
    model: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)  # function calls for the CALLER to run


class ProviderError(Exception):
    """A failed provider call. ``kind`` decides whether the gateway may retry; ``dispatched`` whether the request may
    have reached (and been billed by) the provider."""

    RETRYABLE = frozenset({"timeout", "rate_limited", "server", "network"})

    def __init__(
        self,
        kind: str,
        message: str,
        status: int | None = None,
        retry_after: float | None = None,
        *,
        dispatched: bool = True,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after  # seconds the provider asked us to wait (Retry-After), if any
        self.dispatched = dispatched

    @property
    def retryable(self) -> bool:
        return self.kind in self.RETRYABLE


class Provider(Protocol):
    name: str
    paid: bool

    def ready(self, env: Mapping[str, str]) -> str:
        """'' when the provider can be called, else what is missing (never a key value)."""
        ...

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_output_tokens: int,
        temperature: float,
        json_mode: bool,
        timeout_s: float,
        extra_body: Mapping[str, Any] | None,
        env: Mapping[str, str],
    ) -> Reply: ...


def reported_cost(usage: Any) -> float | None:
    """Provider-reported USD: DeepInfra ``usage.estimated_cost``; None when not reported. (xAI's
    ``cost_in_usd_ticks`` is gone with the xAI provider, decision h.)"""
    if not isinstance(usage, Mapping):
        return None
    raw = usage.get("estimated_cost")
    # Codex H-275: validate the ORIGINAL value (a JSON true / false is not a cost; negative / non-finite neither)
    return float(raw) if budget.usable_usd(raw) else None


def status_kind(status: int) -> str:
    if status in (401, 403):
        return "auth"
    if status == 402:
        return "billing"
    if status == 429:
        return "rate_limited"
    if status == 408:
        return "timeout"
    if status >= 500:
        return "server"
    return "bad_request"


def retry_after(headers: Mapping[str, str]) -> float | None:
    """The old ``Retry-After`` parse: a plain number of seconds, else None (an HTTP date is ignored)."""
    ra = {str(k).lower(): v for k, v in headers.items()}.get("retry-after")
    if ra is not None and str(ra).strip().replace(".", "", 1).isdigit():
        return float(str(ra).strip())
    return None


def under_test() -> bool:
    """True inside a pytest run (decision b)."""
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


def origin_of(url: str) -> str:
    """``scheme://host:port`` (the effective port always spelled out); '' for an unparseable URL or userinfo."""
    try:
        u = urlsplit(str(url or "").strip())
        port = u.port
    except ValueError:
        return ""
    if u.username or u.password or "@" in (u.netloc or ""):
        return ""
    default = {"https": 443, "http": 80}.get(u.scheme)
    return f"{u.scheme}://{(u.hostname or '').lower().rstrip('.')}:{port or default}"


class _Sent:
    """Wraps the transport to learn whether the request reached it (after which it may have been dispatched)."""

    def __init__(self, inner: net.Transport) -> None:
        self.inner = inner
        self.entered = False

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
        self.entered = True
        return self.inner.send(target, method, headers, body, timeout, max_bytes, deadline)


class OpenAICompatibleProvider:
    """``POST {base_url}/chat/completions`` with a Bearer key from ``env[key_env]`` (DeepInfra)."""

    paid = True

    def __init__(
        self,
        name: str,
        base_url: str,
        key_env: str,
        *,
        transport: net.Transport | None = None,
        resolver: net.Resolver | None = None,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.key_env = key_env
        self.origin = origin_of(self.base_url)
        self._transport = transport
        self._resolver = resolver

    def ready(self, env: Mapping[str, str]) -> str:
        """'' when a key is present, else what is missing (never the key itself)."""
        return (
            "" if str(env.get(self.key_env) or "").strip() else f"API key not set (environment variable {self.key_env})"
        )

    def policy(self, url: str, hop: int) -> None:
        """Before every send: the provider's https origin only, no redirect."""
        if hop > 0:
            raise net.UnsafeURLError(f"refused {str(url)[:120]!r}: the provider's redirects are not followed")
        if not (self.origin.startswith("https://") and self.origin.endswith(":443")) or origin_of(url) != self.origin:
            raise net.UnsafeURLError(f"refused {str(url)[:120]!r}: only {self.origin} may be requested here")

    def _auth(self, key: str) -> Callable[[str], Mapping[str, str]]:
        origin = self.origin

        def headers_for(url: str) -> Mapping[str, str]:
            return {"Authorization": "Bearer " + key} if origin_of(url) == origin else {}

        return headers_for

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_output_tokens: int,
        temperature: float,
        json_mode: bool,
        timeout_s: float,
        extra_body: Mapping[str, Any] | None,
        env: Mapping[str, str],
    ) -> Reply:
        if not icfg.paid_enabled(env):
            raise ProviderError(
                "disabled", f"paid inference is switched off ({icfg.PAID_ENV} is not 'on')", dispatched=False
            )
        if under_test() and (self._transport is None or self._resolver is None):
            raise ProviderError(
                "not_configured",
                "a real provider never runs under tests (inject a fake transport and resolver)",
                dispatched=False,
            )
        key = str(env.get(self.key_env) or "").strip()
        if not key:
            raise ProviderError("not_configured", self.ready(env), dispatched=False)
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": int(max_output_tokens),
            "temperature": float(temperature),
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        for k, v in (extra_body or {}).items():  # provider-specific options, e.g. chat_template_kwargs
            if k not in ("model", "messages", "max_tokens", "max_completion_tokens", "n", "best_of"):
                body[k] = v  # never the priced limit or the completion count (Codex H-271; the gateway refuses them)
        sent = _Sent(self._transport or net.DEFAULT_TRANSPORT)

        def fail(
            kind: str, msg: str, *, dispatched: bool, status: int | None = None, wait: float | None = None
        ) -> NoReturn:
            raise ProviderError(kind, _redact(msg, key), status, retry_after=wait, dispatched=dispatched) from None

        try:
            resp = net.fetch(
                self.base_url + "/chat/completions",
                data=json.dumps(body).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT},
                timeout=timeout_s,
                deadline=time.monotonic() + timeout_s,
                resolver=self._resolver,
                transport=sent,
                policy=self.policy,
                headers_for=self._auth(key),
                raise_for_status=False,
            )
        except net.UnsafeURLError as e:
            fail("bad_request", str(e)[:200], dispatched=sent.entered)
        except net.ResponseTooLargeError as e:
            fail("malformed", str(e)[:200], dispatched=True)
        except net.FetchError as e:
            kind = "timeout" if "deadline" in str(e) else "network"
            text = f"timed out after {timeout_s:.0f}s" if kind == "timeout" else str(e)[:160]
            fail(kind, text, dispatched=sent.entered)
        except TimeoutError:
            fail("timeout", f"timed out after {timeout_s:.0f}s", dispatched=sent.entered)
        except ConnectionRefusedError as e:  # the connection never opened: nothing was sent
            fail("network", f"{type(e).__name__}: {str(e)[:160]}", dispatched=False)
        except (OSError, http.client.HTTPException) as e:
            fail("network", f"{type(e).__name__}: {str(e)[:160]}", dispatched=sent.entered)
        if resp.status >= 400:
            detail = resp.body[:400].decode("utf-8", "replace")
            # compact, no JSON body in the stored error ("HTTP 429 engine_overloaded: Model busy, retry later")
            fail(
                status_kind(resp.status),
                perrors.compact(f"HTTP {resp.status}: {detail[:400]}"),
                dispatched=True,
                status=resp.status,
                wait=retry_after(resp.headers),
            )
        try:
            data = json.loads(resp.body.decode("utf-8", "replace"))
            msg = data["choices"][0]["message"]
            text = msg.get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
            raise ProviderError(
                "malformed", f"unexpected response shape ({type(e).__name__})", dispatched=True
            ) from None
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return Reply(
            text=str(text),
            usage=usage,
            reported_usd=reported_cost(usage),
            model=str(data.get("model") or model),
            tool_calls=[tc for tc in (msg.get("tool_calls") or []) if isinstance(tc, dict)],
        )


def _redact(text: str, key: str) -> str:
    return text.replace(key, REDACTED) if key else text


Responder = Callable[[list[dict[str, str]], str], "str | Reply"]
DEFAULT_USAGE: dict[str, Any] = {"prompt_tokens": 1000, "completion_tokens": 200}


class FakeProvider:
    """Deterministic offline provider. ``responder(messages, model)`` returns the reply text (priced with ``usage``)
    or a ``Reply`` (as is: ``Reply(text)`` has NO usage), or raises ``ProviderError``. ``paid=True`` exercises the
    budget and the paid switch. ``calls`` records every request; ``dispatches`` counts those that were not refused
    before dispatch."""

    def __init__(
        self,
        responder: Responder | None = None,
        *,
        paid: bool = False,
        usage: Mapping[str, Any] | None = None,
        name: str = "fake",
    ) -> None:
        self.name = name
        self.paid = paid
        self.responder: Responder = responder or (lambda messages, model: '{"ok": true}')
        self.usage = dict(usage) if usage is not None else dict(DEFAULT_USAGE)
        self.calls: list[dict[str, Any]] = []
        self.dispatches = 0

    @classmethod
    def scripted(cls, outcomes: Iterable[str | Reply | ProviderError], **kw: Any) -> FakeProvider:
        """Replay ``outcomes`` in order (a text, a ``Reply``, or a ``ProviderError`` to raise); past the end the
        default reply."""
        queue = list(outcomes)

        def responder(messages: list[dict[str, str]], model: str) -> str | Reply:
            if not queue:
                return '{"ok": true}'
            item = queue.pop(0)
            if isinstance(item, ProviderError):
                raise item
            return item

        return cls(responder, **kw)

    def ready(self, env: Mapping[str, str]) -> str:
        return ""

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_output_tokens: int,
        temperature: float,
        json_mode: bool,
        timeout_s: float,
        extra_body: Mapping[str, Any] | None,
        env: Mapping[str, str],
    ) -> Reply:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "max_output_tokens": max_output_tokens,
                "temperature": temperature,
                "json_mode": json_mode,
                "timeout_s": timeout_s,
                "extra_body": dict(extra_body or {}),
            }
        )
        try:
            out = self.responder(messages, model)
        except ProviderError as e:
            if e.dispatched:
                self.dispatches += 1
            raise
        self.dispatches += 1
        if isinstance(out, Reply):
            return out
        return Reply(text=str(out), usage=dict(self.usage), reported_usd=reported_cost(self.usage), model=model)


def resolve(
    name: str,
    cfg: Mapping[str, Any],
    overrides: Mapping[str, Provider] | None = None,
    *,
    transport: net.Transport | None = None,
    resolver: net.Resolver | None = None,
) -> Provider:
    """The provider called ``name``: an override first (tests, tooling), else from the configuration."""
    if overrides and name in overrides:
        return overrides[name]
    p = (cfg.get("providers") or {}).get(name)
    if not isinstance(p, Mapping):
        raise ProviderError(
            "not_configured", f"provider '{name}' is not configured (inference.providers)", dispatched=False
        )
    if p.get("type") == "fake":
        return FakeProvider(name=name)
    if p.get("type") == "openai_compatible" and p.get("base_url") and p.get("key_env"):
        return OpenAICompatibleProvider(
            name, str(p["base_url"]), str(p["key_env"]), transport=transport, resolver=resolver
        )
    raise ProviderError(
        "not_configured", f"provider '{name}' needs type openai_compatible + base_url + key_env", dispatched=False
    )

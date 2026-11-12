"""Founder Radar's outbound requests (review 026b, plan revision 2 §1/§2/§4): ONE ``Fetch`` (``core.net`` with an
injected transport, resolver and deadline) and the per-caller rules on top of the public-address guard.

* **GitHub API** (``github_json``): ``https://api.github.com`` only, at most 2 redirects. ``Authorization: Bearer
  <token>`` is added by ``headers_for`` for THAT origin only (a redirect elsewhere never carries it; it is refused
  anyway). The token is a parameter: the caller reads ``PZ_GITHUB_TOKEN`` (``GITHUB_TOKEN_ENV``), never
  ``config.json``. An error status is returned by ``core.net`` with its headers (``raise_for_status=False``) and raised
  here as ``HTTPError`` (status + headers), so the scan can read the rate-limit reset.
* **OpenAlex** (``openalex_json``): ``https://api.openalex.org`` only, at most 2 redirects, no token. The ``mailto``
  stays the old placeholder (in the collector's URL).
* **Company research** (``research_page`` with the canonical domain): the old ``fetch._fetch_public`` (rev 6c739b9)
  on ``core.net``: before EVERY send (the first included) the policy runs the old ``safe_url`` checks (https only, no
  userinfo, no local name, every address public, the host the canonical domain with the old ``www.`` equivalence),
  the old cross-origin redirect refusal and the old limit of 3 redirects; a refused hop is never sent. After the
  response the old checks: a redirect without a location, ``http <status>``, ``text/html`` /
  ``application/xhtml+xml`` only, and the body cut at the old ``read(MAX_BODY)`` (400 000 bytes; the transport cap is
  ``core.net``'s default). The record is the old one (``requested_url``, ``final_url``, ``status``, ``content_type``,
  ``body``, ``reason``, ``hops``, ``pinned_ip``) with the old reason texts.
* **Public GitHub organisation page** (``research_page`` with ``GITHUB_WEB``, ``exact=True``): the same research rules
  with ``github.com`` as the only host (no token: no ``headers_for``).

Every hop still passes ``core.net.validate`` (public addresses, the connection pinned to the checked address). The
research policy resolves each host ONCE per page fetch through ``Fetch.resolve`` (bounded by the deadline) and hands
``core.net`` the same answer (``_Memo``), so the checked address is the pinned one.

The User-Agent is the project name alone (plan revision 2 §4); the old collectors sent
``ProjectZero-FounderRadar``, the old research fetch ``... (public research; contact via Project A)``.

The deadline (plan (a)): ``Fetch.deadline`` is the time fetching must stop (on ``Fetch.clock``, ``time.monotonic``
in production). A request that cannot start, or that ``core.net`` cuts off, raises ``DeadlineReached``; research
never records it as a page (the company is "not finished"), the scan records the source as failed.
"""

from __future__ import annotations

import ipaddress
import json
import re
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from datetime import datetime
from http import HTTPStatus
from typing import Any, cast
from urllib.parse import ParseResult, urljoin, urlparse, urlsplit

from projectzero.core import net
from projectzero.founder_radar.catalog import LINK_PRIORITY, MAX_BODY, MAX_REDIRECTS
from projectzero.network.view import BERLIN

USER_AGENT = "ProjectZero-FounderRadar (public research)"  # plan revision 2 §4
GITHUB_TOKEN_ENV = "PZ_GITHUB_TOKEN"  # plan (b): the optional token, read by the caller from the environment
GITHUB_API = "https://api.github.com"
OPENALEX_API = "https://api.openalex.org"
GITHUB_WEB = "github.com"
API_REDIRECTS = 2
API_TIMEOUT_S = 20.0  # the old collectors' urlopen(timeout=20)
PAGE_TIMEOUT_S = 15.0  # the old _fetch_public timeout
API_MAX_BYTES = net.MAX_BYTES  # the default cap (the old collectors had none)
PAGE_MAX_BYTES = net.MAX_BYTES  # the transport cap; the body kept is the old first MAX_BODY bytes
HTML_TYPES = ("text/html", "application/xhtml+xml")
REDIRECTS = (301, 302, 303, 307, 308)
GITHUB_HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
OPENALEX_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}
PAGE_HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}

Policy = Callable[[str, int], None]


class DeadlineReached(net.FetchError):
    """The run's fetch deadline passed before or during a request."""


class HTTPError(net.FetchError):
    """An error status from an API (the old ``urllib.error.HTTPError``: ``str`` is ``HTTP Error <code>: <phrase>``),
    with the response headers (lower-case names) for the rate-limit reset."""

    def __init__(self, url: str, code: int, headers: Mapping[str, str]) -> None:
        try:
            phrase = HTTPStatus(code).phrase
        except ValueError:
            phrase = ""
        super().__init__(f"HTTP Error {code}: {phrase}")
        self.url = url
        self.code = code
        self.headers = {str(k).lower(): str(v) for k, v in headers.items()}


_DNS = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pz-radar-dns")


@dataclass(frozen=True)
class Fetch:
    """What the domain receives: ``core.net.fetch`` with this transport (None: the pinned production transport), this
    resolver (None: the system resolver) and this deadline (``clock()`` time at which fetching stops; None: none).
    Tests pass a fixture transport and resolver, so nothing leaves the machine."""

    transport: net.Transport | None = None
    resolver: net.Resolver | None = None
    deadline: float | None = None
    clock: Callable[[], float] = field(default=time.monotonic)

    def left(self) -> float | None:
        return None if self.deadline is None else self.deadline - self.clock()

    def expired(self) -> bool:
        left = self.left()
        return left is not None and left <= 0

    def resolve(self, host: str) -> list[str]:
        """The resolver, waiting at most for the time left (``getaddrinfo`` takes no timeout)."""
        resolve = self.resolver or net.default_resolver
        left = self.left()
        if left is None:
            return resolve(host)
        if left <= 0:
            raise DeadlineReached("source deadline reached")
        try:
            return _DNS.submit(resolve, host).result(timeout=left)
        except FuturesTimeout as exc:
            raise DeadlineReached("source deadline reached (DNS resolution)") from exc

    def __call__(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        max_bytes: int,
        policy: Policy,
        headers_for: Callable[[str], Mapping[str, str]] | None = None,
        raise_for_status: bool = True,
        resolver: net.Resolver | None = None,
        tap: Callable[[net.Response], None] | None = None,
        truncate: bool = False,
    ) -> net.Response:
        """One guarded fetch. ``tap`` sees every response the transport returned (the research policy needs a
        redirect's status when it refuses the next hop)."""
        left = self.left()
        if left is not None and left <= 0:
            raise DeadlineReached("source deadline reached")
        transport: net.Transport = self.transport or net.DEFAULT_TRANSPORT
        if tap is not None:
            transport = _Tap(transport, tap)
        try:
            return net.fetch(
                url,
                headers=headers,
                timeout=timeout,
                deadline=None if left is None else time.monotonic() + left,
                max_bytes=max_bytes,
                resolver=resolver or self.resolver,
                transport=transport,
                policy=policy,
                headers_for=headers_for,
                raise_for_status=raise_for_status,
                truncate=truncate,
            )
        except DeadlineReached:
            raise
        except net.FetchError as exc:
            if "deadline" in str(exc):
                raise DeadlineReached(str(exc)) from exc
            raise


class _Tap:
    def __init__(self, inner: net.Transport, tap: Callable[[net.Response], None]) -> None:
        self.inner = inner
        self.tap = tap

    def send(
        self,
        target: net.Target,
        method: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
        max_bytes: int,
        deadline: float | None = None,
        *,
        truncate: bool = False,
    ) -> net.Response:
        if truncate:
            cut = cast(net.TruncatingTransport, self.inner)
            r = cut.send(target, method, headers, body, timeout, max_bytes, deadline, truncate=True)
        else:
            r = self.inner.send(target, method, headers, body, timeout, max_bytes, deadline)
        self.tap(r)
        return r


# ------------------------------------------------------------------ the API callers (GitHub, OpenAlex)
def origin_of(url: str) -> str:
    """``scheme://host[:port]`` (default port omitted); "" for an unparseable URL or one with userinfo."""
    try:
        u = urlsplit(str(url or "").strip())
        port = u.port
    except ValueError:
        return ""
    if u.username or u.password or "@" in (u.netloc or ""):
        return ""
    host = (u.hostname or "").lower()
    default = {"https": 443, "http": 80}.get(u.scheme)
    return f"{u.scheme}://{host}" + ("" if port in (None, default) else f":{port}")


def api_policy(origin: str, max_redirects: int = API_REDIRECTS) -> Policy:
    """One origin, at most ``max_redirects`` redirects, checked before every send."""

    def policy(url: str, hop: int) -> None:
        if hop > max_redirects:
            raise net.UnsafeURLError(f"refused {str(url)[:120]!r}: more than {max_redirects} redirects")
        if origin_of(url) != origin:
            raise net.UnsafeURLError(f"refused {str(url)[:120]!r}: only {origin} may be requested here")

    return policy


def github_auth(token: str | None) -> Callable[[str], Mapping[str, str]]:
    """The ``Authorization`` header for the GitHub API origin ONLY (per hop)."""

    def headers_for(url: str) -> Mapping[str, str]:
        return {"Authorization": "Bearer " + token} if token and origin_of(url) == GITHUB_API else {}

    return headers_for


def _json(fetch: Fetch, url: str, headers: Mapping[str, str], policy: Policy, headers_for: Any = None) -> Any:
    r = fetch(
        url,
        headers=headers,
        timeout=API_TIMEOUT_S,
        max_bytes=API_MAX_BYTES,
        policy=policy,
        headers_for=headers_for,
        raise_for_status=False,
    )
    if r.status >= 400:
        raise HTTPError(url, r.status, r.headers)
    return json.loads(r.body.decode("utf-8", "replace"))


def github_json(fetch: Fetch, url: str, token: str | None = None) -> Any:
    """The old ``collectors._get_json(url, _gh_headers())``."""
    return _json(fetch, url, GITHUB_HEADERS, api_policy(GITHUB_API), github_auth(token))


def openalex_json(fetch: Fetch, url: str) -> Any:
    """The old ``collectors._get_json(url)``."""
    return _json(fetch, url, OPENALEX_HEADERS, api_policy(OPENALEX_API))


def is_rate_limit(exc: BaseException) -> bool:
    """Plan revision 2 §2: a 403 or a 429 from the GitHub API stops the remaining GitHub sources."""
    return isinstance(exc, HTTPError) and exc.code in (403, 429)


def reset_text(headers: Mapping[str, str] | None) -> str:
    """The old scan's reset text: ``X-RateLimit-Reset`` (epoch seconds) as the Berlin wall time ``%H:%M`` (the old
    ``datetime.fromtimestamp`` used the machine's zone), else ``Retry-After`` as ``<n> s``, else ``unknown``."""
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    reset = h.get("x-ratelimit-reset") or h.get("retry-after")
    try:
        return (
            datetime.fromtimestamp(int(reset), BERLIN).strftime("%H:%M")
            if reset and str(reset).isdigit() and int(reset) > 10**6
            else (str(reset) + " s" if reset else "unknown")
        )
    except Exception:
        return "unknown"


# ------------------------------------------------------------------ research: the old fetch.py, line for line
def _norm_host(host: Any) -> str:
    h = (host or "").lower().rstrip(".")
    return str(h[4:] if h.startswith("www.") else h)


def safe_url(
    url: Any, allowed_host: str | None, resolver: net.Resolver, require_https: bool = True
) -> tuple[bool, str, ParseResult | None, list[str]]:
    """Public destination only: https, no userinfo, no localhost/.local/IP-literal private ranges, DNS answers all
    public, and (when given) the canonical company host (www-normalized) or github.com. Returns (ok, reason, parsed,
    addresses). The address test is ``core.net.ip_is_public`` (the old ``_ip_ok`` plus IPv4-mapped IPv6)."""
    try:
        u = urlparse(str(url or "").strip())
    except Exception:
        return False, "unparseable URL", None, []
    if u.scheme != "https" and (require_https or u.scheme != "http"):
        return False, "scheme not allowed (https only)", u, []
    if u.username or u.password or "@" in (u.netloc or ""):
        return False, "userinfo in URL", u, []
    host = (u.hostname or "").lower().rstrip(".")
    if not host or host in ("localhost",) or host.endswith(".local") or host.endswith(".localhost"):
        return False, "local host name", u, []
    try:
        ipaddress.ip_address(host.strip("[]"))
        lit = True
    except ValueError:
        lit = False
    if lit:
        if not net.ip_is_public(host.strip("[]")):
            return False, "non-public IP literal", u, []
        ips = [host.strip("[]")]
    else:
        ips = resolver(host)
        if not ips:
            return False, "DNS resolution failed", u, []
        bad = [ip for ip in ips if not net.ip_is_public(ip)]
        if bad:
            return False, f"DNS resolves to non-public address ({bad[0]})", u, []
    if allowed_host and _norm_host(host) != _norm_host(allowed_host) and _norm_host(host) != "github.com":
        return False, f"off the canonical company host ({host})", u, []
    return True, "", u, list(ips)


class Blocked(net.UnsafeURLError):
    """A research hop refused BEFORE it was sent: the old record's ``status`` / ``final_url`` / ``reason``."""

    def __init__(self, status: int, final_url: str, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.final_url = final_url
        self.reason = reason


class _Memo:
    """One page fetch's resolver: each host resolved once (``Fetch.resolve``); ``core.net`` pins that answer."""

    def __init__(self, fetch: Fetch) -> None:
        self.fetch = fetch
        self.seen: dict[str, list[str]] = {}

    def __call__(self, host: str) -> list[str]:
        if host not in self.seen:
            self.seen[host] = list(self.fetch.resolve(host))
        return list(self.seen[host])


class PagePolicy:
    """The old ``_fetch_public`` hop rules, run by ``core.net`` before each send: from the second hop on, the old
    cross-origin refusal (``www.``-normalized host of the previous hop) and the old ``MAX_REDIRECTS`` (3); then the old
    ``safe_url`` (https only) with the canonical host; then this caller's host rule: the canonical domain (``www.``
    equivalence) for a company page, exactly ``github.com`` for the GitHub organisation page (``exact``)."""

    def __init__(self, url: str, allowed_host: str, resolver: net.Resolver, *, exact: bool = False) -> None:
        self.url = url
        self.allowed = allowed_host
        self.resolver = resolver
        self.exact = exact
        self.prev = url
        self.last_status = 0
        self.hops: list[str] = []
        self.pinned_ip = ""

    def saw(self, r: net.Response) -> None:
        self.last_status = r.status

    def __call__(self, url: str, hop: int) -> None:
        if hop > 0:
            self.hops.append(url)
            if _origin_key(url)[0] != _origin_key(self.prev)[0]:  # the old rule: the www.-normalized host
                raise Blocked(
                    self.last_status,
                    url,
                    "blocked: cross-origin redirect to %s" % (urlparse(url).hostname or "?"),
                )
            if hop > MAX_REDIRECTS:
                raise Blocked(0, self.url, "blocked: too many redirects")
        ok, why, u, ips = safe_url(url, self.allowed, self.resolver, True)  # ONE resolution: checked here, pinned
        if not ok:
            raise Blocked(0, url, "blocked: " + why)
        host = ((u.hostname if u else "") or "").lower().rstrip(".")
        if self.exact and host != self.allowed:
            raise Blocked(0, url, f"blocked: off the canonical company host ({host})")
        if not self.exact and _norm_host(host) != _norm_host(self.allowed):
            raise Blocked(0, url, f"blocked: off the canonical company host ({host})")
        port = _effective_port(url)  # after the old https-only rule, so a downgrade keeps the old answer
        if port != 443:  # Codex H-221: https on its default port only; another port is another origin
            if hop > 0:
                raise Blocked(self.last_status, url, f"blocked: cross-origin redirect to {host}:{port}")
            raise Blocked(0, url, f"blocked: off the canonical company origin (port {port})")
        if not ips:
            raise Blocked(0, url, "blocked: no validated public address to pin")
        self.pinned_ip = ips[0]
        self.prev = url


def _effective_port(url: str) -> int | None:
    try:
        u = urlparse(url)
        return u.port or {"https": 443, "http": 80}.get(u.scheme)
    except ValueError:
        return None


def _origin_key(url: str) -> tuple[str, int | None]:
    """(the ``www.``-normalized host, the effective port): the cross-origin rule's notion of one origin."""
    return _norm_host(urlparse(url).hostname or ""), _effective_port(url)


ROBOTS_TYPES = ("text/plain", *HTML_TYPES)  # Codex H-221: robots.txt is plain text (the old code ignored it then)


def research_page(
    fetch: Fetch, url: str, allowed_host: str, *, exact: bool = False, accept: tuple[str, ...] = HTML_TYPES
) -> dict[str, Any]:
    """The old ``_fetch_public(url, allowed_host=...)`` record. ``DeadlineReached`` is raised, never recorded. At most
    ``MAX_BODY`` bytes are READ (the old ``resp.read(MAX_BODY)``: the transport stops there and the prefix is kept,
    Codex H-221). ``accept``: the media types kept (``ROBOTS_TYPES`` for robots.txt)."""
    rec: dict[str, Any] = {
        "requested_url": url,
        "final_url": url,
        "status": 0,
        "content_type": "",
        "body": "",
        "reason": "",
        "hops": [],
        "pinned_ip": "",
    }
    memo = _Memo(fetch)
    policy = PagePolicy(url, allowed_host, memo, exact=exact)
    try:
        r = fetch(
            url,
            headers=PAGE_HEADERS,
            timeout=PAGE_TIMEOUT_S,
            max_bytes=MAX_BODY,
            truncate=True,
            policy=policy,
            raise_for_status=False,
            resolver=memo,
            tap=policy.saw,
        )
    except Blocked as b:
        rec.update({"status": b.status, "final_url": b.final_url, "reason": b.reason})
        rec["hops"], rec["pinned_ip"] = list(policy.hops), policy.pinned_ip
        return rec
    except DeadlineReached:
        raise
    except Exception as e:
        rec.update({"reason": "fetch error: " + str(e)[:100], "hops": list(policy.hops), "pinned_ip": policy.pinned_ip})
        return rec
    rec["hops"], rec["pinned_ip"] = list(policy.hops), policy.pinned_ip
    status = r.status
    ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    if status in REDIRECTS:  # core.net returns a redirect only when it has no location
        rec.update({"status": status, "reason": "blocked: redirect without location"})
        return rec
    rec.update({"status": status, "final_url": r.url, "content_type": ctype})
    if status != 200:
        rec["reason"] = "http %d" % status  # noqa: UP031
        return rec
    if ctype not in accept:
        rec["reason"] = "blocked: non-HTML content type (%s)" % (ctype or "none")
        return rec
    rec["body"] = r.body[:MAX_BODY].decode("utf-8", "replace")  # the old resp.read(MAX_BODY)
    return rec


def research_robots(fetch: Fetch, url: str, allowed_host: str) -> dict[str, Any]:
    """robots.txt under the SAME origin, address, size and deadline controls as a page, with its own media types."""
    return research_page(fetch, url, allowed_host, accept=ROBOTS_TYPES)


def _robots_disallowed(domain: str, page: Callable[[str], dict[str, Any]]) -> set[str]:
    try:
        rec = page(f"https://{domain}/robots.txt")
    except DeadlineReached:
        raise
    except Exception:
        return set()
    if rec["status"] != 200 or rec.get("reason", "").startswith("blocked"):
        return set()
    dis, ua_all = set(), False
    for ln in rec["body"].splitlines():
        ln = ln.strip()
        if ln.lower().startswith("user-agent:"):
            ua_all = ln.split(":", 1)[1].strip() == "*"
        elif ua_all and ln.lower().startswith("disallow:"):
            p = ln.split(":", 1)[1].strip()
            if p:
                dis.add(p.rstrip("/") or "/")
    return dis


def discover_links(base_url: str, html: str, domain: str) -> list[str]:
    """Normalized same-domain links from fetched HTML, prioritized by relevance; fragments/queries stripped."""
    found = []
    for m in re.finditer(r"""href\s*=\s*["']([^"'#?]+)""", html or "", re.I):
        try:
            u = urlparse(urljoin(base_url, m.group(1).strip()))
        except Exception:
            continue
        if u.scheme not in ("http", "https") or _norm_host(u.hostname or "") != _norm_host(domain):
            continue
        path = re.sub(r"/+$", "", u.path or "") or "/"
        if re.search(r"\.(pdf|jpg|jpeg|png|gif|svg|zip|css|js|xml)$", path, re.I):
            continue
        found.append("https://{}{}".format(_norm_host(u.hostname), "" if path == "/" else path))
    found = list(dict.fromkeys(found))

    def pri(u: str) -> int:
        return next((i for i, k in enumerate(LINK_PRIORITY) if k in u.lower().split(domain, 1)[-1]), len(LINK_PRIORITY))

    return sorted([u for u in found if pri(u) < len(LINK_PRIORITY)], key=pri)

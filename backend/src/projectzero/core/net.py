"""The ONE outbound-HTTP boundary (review 017): the old ``net.py`` SSRF guard (rev 6c739b9), with each connection
BOUND to the address that was validated for that hop (Codex H-113).

A destination is refused unless:

* its scheme is http or https, it carries no userinfo, and its host is not a local name (``localhost``,
  ``*.local``, ``*.localhost``);
* EVERY address its host resolves to is public (private, loopback, link-local, multicast, reserved, unspecified and
  non-global v4 / v6 addresses, incl. IPv4-mapped IPv6, are refused).

Then the transport connects to one of THOSE addresses: the hostname is resolved once, checked, and the socket is
opened to the checked address (never re-resolved by the client), so a DNS answer that changes between the check and
the connect cannot redirect the request. TLS keeps the original hostname for SNI and certificate verification, and
verification is mandatory: there is no insecure fallback (review 017 (a); the old connectors retried without
verification). Each redirect hop (at most ``MAX_REDIRECTS``) is validated and pinned the same way. Bodies are capped
at ``MAX_BYTES``; every call has a timeout, and a caller may pass a ``deadline`` (``time.monotonic()``) that bounds
the WHOLE fetch in wall-clock time (Codex H-115 / H-117): it is checked before resolving, the DNS lookup waits only for
the time left, and the transport arms a watchdog that shuts the socket down at the deadline (connect, request, status
line and headers, body), besides re-setting the socket timeout to the time left before every chunk it reads, so
neither a slow resolver nor a server trickling its headers or body can hold a fetch past it.

The transport is injectable (``Transport``): tests pass one that records which address each hop used and answers
from fixtures, so no test ever touches the network. Proxies are not used (a pinned connection goes direct).
"""

from __future__ import annotations

import contextlib
import http.client
import ipaddress
import socket
import ssl
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Protocol, cast
from urllib.parse import urljoin, urlsplit

Resolver = Callable[[str], list[str]]

DEFAULT_TIMEOUT = 20.0
MAX_BYTES = 8_000_000
MAX_REDIRECTS = 5
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 "
    "Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de,en;q=0.8",
}  # the old connectors._BROWSER_HEADERS


class UnsafeURLError(ValueError):
    """The destination is not a public http(s) URL (SSRF guard)."""


class ResponseTooLargeError(ValueError):
    """The response body exceeds the size cap."""


class FetchError(RuntimeError):
    """A fetch that did not produce a usable response (HTTP error status, too many redirects, deadline)."""


def ip_is_public(ip: str) -> bool:
    """True only for a globally routable unicast address (an IPv4-mapped IPv6 address is judged as its IPv4)."""
    try:
        a = ipaddress.ip_address(ip.strip("[]"))
    except ValueError:
        return False
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped is not None:
        a = a.ipv4_mapped
    return not (
        a.is_private
        or a.is_loopback
        or a.is_link_local
        or a.is_multicast
        or a.is_reserved
        or a.is_unspecified
        or a.is_global is False
    )


def default_resolver(host: str) -> list[str]:
    try:
        return sorted({str(ai[4][0]) for ai in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)})
    except (OSError, UnicodeError):
        return []


@dataclass(frozen=True)
class Target:
    """One validated hop: where to connect (``ip``) and what to call it (``host``, for Host / SNI / certificate)."""

    scheme: str
    host: str
    port: int
    ip: str
    path: str  # path + query, the request target


_RESOLVERS = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pz-dns")


def remaining(deadline: float | None) -> float | None:
    return None if deadline is None else deadline - time.monotonic()


def _resolve(host: str, resolver: Resolver | None, deadline: float | None) -> list[str]:
    """``getaddrinfo`` cannot be given a timeout: with a deadline the lookup runs in a worker and the caller waits only
    for the time left (an abandoned lookup finishes in the background and is discarded)."""
    resolve = resolver or default_resolver
    left = remaining(deadline)
    if left is None:
        return resolve(host)
    if left <= 0:
        raise FetchError("source deadline reached")
    try:
        return _RESOLVERS.submit(resolve, host).result(timeout=left)
    except FuturesTimeout as exc:
        raise FetchError("source deadline reached (DNS resolution)") from exc


def validate(url: str, resolver: Resolver | None = None, deadline: float | None = None) -> Target:
    """Check ``url`` and pick the address to connect to. Raises ``UnsafeURLError`` (or ``FetchError`` when the
    deadline passes while resolving)."""
    try:
        u = urlsplit(str(url or "").strip())
        port = u.port
    except ValueError as exc:
        raise UnsafeURLError(f"refused {str(url)[:120]!r}: unparseable URL") from exc
    why = ""
    host = (u.hostname or "").lower().rstrip(".")
    if u.scheme not in ("http", "https"):
        why = "scheme not allowed (http / https only)"
    elif u.username or u.password or "@" in (u.netloc or ""):
        why = "userinfo in URL"
    elif not host:
        why = "no host"
    elif host == "localhost" or host.endswith((".local", ".localhost")):
        why = "local host name"
    if why:
        raise UnsafeURLError(f"refused {str(url)[:120]!r}: {why}")
    try:
        ipaddress.ip_address(host.strip("[]"))
        ips = [host.strip("[]")]
        literal = True
    except ValueError:
        ips = _resolve(host, resolver, deadline)
        literal = False
    if not ips:
        raise UnsafeURLError(f"refused {str(url)[:120]!r}: DNS resolution failed")
    bad = [ip for ip in ips if not ip_is_public(ip)]
    if bad:
        what = "non-public IP literal" if literal else f"DNS resolves to a non-public address ({bad[0]})"
        raise UnsafeURLError(f"refused {str(url)[:120]!r}: {what}")
    path = (u.path or "/") + (f"?{u.query}" if u.query else "")
    return Target(u.scheme, host, port or (443 if u.scheme == "https" else 80), ips[0], path)


@dataclass
class Response:
    url: str
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def text(self, encoding: str = "utf-8") -> str:
        return self.body.decode(encoding, errors="replace")


class Transport(Protocol):
    def send(
        self,
        target: Target,
        method: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
        max_bytes: int,
        deadline: float | None = None,
    ) -> Response:
        """Send ONE request to ``target.ip`` (named ``target.host``); never follow redirects. ``deadline`` bounds the
        WHOLE exchange (connect, request, every read), not just the inactivity between packets."""
        ...


class TruncatingTransport(Protocol):
    """A transport that can also read only a body's prefix (review 026b: ``fetch(truncate=True)``)."""

    def send(
        self,
        target: Target,
        method: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
        max_bytes: int,
        deadline: float | None = None,
        *,
        truncate: bool = False,
    ) -> Response:
        """As ``Transport.send``; ``truncate``: read at most ``max_bytes`` and return that prefix instead of refusing a
        longer body."""
        ...


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, target: Target, timeout: float) -> None:
        super().__init__(target.host, target.port, timeout=timeout)
        self._ip = target.ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, target: Target, timeout: float, context: ssl.SSLContext) -> None:
        super().__init__(target.host, target.port, timeout=timeout, context=context)
        self._ip = target.ip
        self._ctx = context

    def connect(self) -> None:
        raw = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._ctx.wrap_socket(raw, server_hostname=self.host)  # SNI + verification on the HOSTNAME


class PinnedTransport:
    """The production transport: ``http.client`` connected to the validated address, certificates always verified."""

    def __init__(self, context: ssl.SSLContext | None = None) -> None:
        self._ctx = context or ssl.create_default_context()  # CERT_REQUIRED + check_hostname

    def send(
        self,
        target: Target,
        method: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
        max_bytes: int,
        deadline: float | None = None,
        *,
        truncate: bool = False,
    ) -> Response:
        conn: http.client.HTTPConnection = (
            _PinnedHTTPSConnection(target, timeout, self._ctx)
            if target.scheme == "https"
            else _PinnedHTTPConnection(target, timeout)
        )
        watchdog = _Watchdog(conn, deadline)  # the ABSOLUTE deadline over connect, request, headers and body
        try:
            conn.request(method, target.path, body=body, headers=dict(headers))
            r = conn.getresponse()
            watchdog.response = r
            length = r.getheader("Content-Length")
            if length and length.isdigit() and int(length) > max_bytes and not truncate:
                raise ResponseTooLargeError(f"response of {length} bytes exceeds the {max_bytes}-byte cap")
            data = _read_bounded(r, max_bytes, timeout, deadline, truncate=truncate)
            url = f"{target.scheme}://{target.host}:{target.port}{target.path}"
            return Response(url, r.status, {k.lower(): v for k, v in r.getheaders()}, data)
        except (OSError, http.client.HTTPException) as exc:
            if watchdog.fired or (remaining(deadline) or 1) <= 0:
                raise FetchError("source deadline reached") from exc
            raise
        finally:
            watchdog.cancel()
            conn.close()


class _Watchdog:
    """At the deadline, shut the exchange's socket down, so ANY blocking step (connect, sending, the status line and
    headers inside ``getresponse()``, the body) returns at once instead of when the server pleases (Codex H-117).
    The per-step socket timeouts still bound inactivity; this bounds the total."""

    def __init__(self, conn: http.client.HTTPConnection, deadline: float | None) -> None:
        self.conn = conn
        self.response: http.client.HTTPResponse | None = None
        self.fired = False
        left = remaining(deadline)
        self._timer = None if left is None else threading.Timer(max(0.0, left), self._fire)
        if self._timer is not None:
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        self.fired = True
        socks = [self.conn.sock, _response_socket(self.response) if self.response is not None else None]
        for sock in socks:
            if sock is not None:
                with contextlib.suppress(OSError):
                    sock.shutdown(socket.SHUT_RDWR)

    def cancel(self) -> None:
        if self._timer is not None:
            self._timer.cancel()


CHUNK = 64 * 1024


def _response_socket(r: http.client.HTTPResponse) -> socket.socket | None:
    """The socket the response reads from (``conn.sock`` is dropped by ``getresponse()`` when the server will close
    the connection, so the response's own reader is the reliable handle)."""
    raw = getattr(getattr(r, "fp", None), "raw", None)
    sock = getattr(raw, "_sock", None)
    return sock if isinstance(sock, socket.socket) else None


def _read_bounded(
    r: http.client.HTTPResponse,
    max_bytes: int,
    timeout: float,
    deadline: float | None,
    *,
    truncate: bool = False,
) -> bytes:
    """The body in chunks, the socket timeout re-set to the time left before each one: a server that keeps a slow
    trickle going cannot hold the read past the deadline (a socket timeout alone bounds only the gap between
    packets). ``truncate``: each read asks for at most the bytes still wanted and the read returns as soon as
    ``max_bytes`` arrived (the old ``resp.read(n)``); otherwise a longer body is ``ResponseTooLargeError``."""
    parts: list[bytes] = []
    size = 0
    while True:
        if truncate and size >= max_bytes:  # the whole prefix is here: never wait for bytes nobody needs
            return b"".join(parts)
        left = remaining(deadline)
        if left is not None and left <= 0:
            raise FetchError("source deadline reached (reading the response)")
        bounded_by_deadline = left is not None and left < timeout
        sock = _response_socket(r)
        if sock is not None:
            sock.settimeout(max(0.01, left) if left is not None and bounded_by_deadline else timeout)
        try:
            # at most ONE socket read (read(n) would block until n bytes arrived); when truncating, never more than the
            # bytes still wanted, so nothing past the prefix is consumed (Codex H-223)
            chunk = r.read1(min(CHUNK, max_bytes - size) if truncate else CHUNK)
        except TimeoutError as exc:
            if bounded_by_deadline:  # the deadline, not the server's pause, set this timeout
                raise FetchError("source deadline reached (reading the response)") from exc
            raise
        if not chunk:
            return b"".join(parts)
        size += len(chunk)
        if size > max_bytes:  # never when truncating: each read asks for the remaining count at most
            raise ResponseTooLargeError(f"response exceeds the {max_bytes}-byte cap")
        parts.append(chunk)


DEFAULT_TRANSPORT: Transport = PinnedTransport()


def fetch(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    data: bytes | None = None,
    method: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    deadline: float | None = None,
    max_bytes: int = MAX_BYTES,
    resolver: Resolver | None = None,
    transport: Transport | None = None,
    policy: Callable[[str, int], None] | None = None,
    headers_for: Callable[[str], Mapping[str, str]] | None = None,
    raise_for_status: bool = True,
    truncate: bool = False,
) -> Response:
    """GET (or POST with ``data``) ``url`` behind the guard, following at most ``MAX_REDIRECTS`` redirects, each
    validated and pinned. A status >= 400 raises ``FetchError`` (the old ``HTTPError``).

    Per-caller rules (review 026b; all optional, the defaults are the behaviour every earlier caller relies on):
    ``policy(url, hop)`` runs BEFORE each send, the initial URL (hop 0) included, and raises ``UnsafeURLError`` to stop
    the fetch before that request leaves; ``headers_for(url)`` gives the extra headers of ONE hop (nothing it returns is
    carried to the next hop, so a credential reaches only the URLs it allows); ``raise_for_status=False`` returns an
    error status with its headers instead of raising (still through the guarded transport); ``truncate=True`` reads at
    most ``max_bytes`` of the body and keeps that prefix (the transport stops reading there)."""
    send = (transport or DEFAULT_TRANSPORT).send
    base = {"User-Agent": BROWSER_HEADERS["User-Agent"], **(headers or {})}
    current, verb = url, method or ("POST" if data is not None else "GET")
    for hop in range(MAX_REDIRECTS + 1):
        if policy is not None:
            policy(current, hop)  # the caller's origin / scheme / redirect-count rules, before anything is sent
        target = validate(current, resolver, deadline)  # refuses to start resolving after the deadline
        left = timeout if deadline is None else min(timeout, deadline - time.monotonic())
        if left <= 0:
            raise FetchError("source deadline reached")
        hdrs = {**base, **(headers_for(current) if headers_for is not None else {})}
        if truncate:
            cut = cast(TruncatingTransport, transport or DEFAULT_TRANSPORT)
            r = cut.send(target, verb, hdrs, data, left, max_bytes, deadline, truncate=True)
        else:
            r = send(target, verb, hdrs, data, left, max_bytes, deadline)
        if r.status in (301, 302, 303, 307, 308) and r.headers.get("location"):
            current = urljoin(current, r.headers["location"])
            if r.status in (301, 302, 303):
                verb, data = "GET", None
            continue
        if r.status >= 400 and raise_for_status:
            raise FetchError(f"HTTP Error {r.status}")
        return Response(current, r.status, r.headers, r.body)
    raise FetchError(f"more than {MAX_REDIRECTS} redirects")


def fetch_text(url: str, **kw: object) -> str:
    return fetch(url, **kw).text()  # type: ignore[arg-type]

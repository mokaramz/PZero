"""News' outbound requests (review 028c decisions (a) and (f)): the feed fetch, the only network call in News, on
``core.net`` with the News fetch policy, through ONE injectable ``FeedFetch`` (the 026b ``Fetch`` pattern).

The policy (``feed_policy``), checked by ``core.net.fetch`` BEFORE every send, the first one included:

* https only, on the default port;
* the host must be one of the feed hosts: the 10 old ``FEEDS`` plus the enabled ``news/feeds_extra.json`` entries
  (``allowed_hosts``; exact host names, lower case); a redirect off that list is refused before it is sent;
* at most ``MAX_REDIRECTS`` (5) redirects;
* ``core.net`` itself then refuses userinfo, local names and every non-public address, and pins the connection to the
  address it checked.

The budgets: the old size cap (``MAX_BYTES``, 8 MB) and 20 s per feed (``FEED_TIMEOUT_S``: the socket timeout AND a
wall-clock deadline for the whole feed, bounded by the run's deadline when there is one). TLS is always verified: there
is no insecure fallback (the old connectors retried a certificate error without verification); a TLS error is a failed
feed with its reason. The User-Agent is the project's own (decision (f)), sent per host through ``headers_for``.

An error status is raised as ``HTTPError`` whose text is the old ``urllib.error.HTTPError`` one (``HTTP Error <code>:
<phrase>``): the run reads the status from it (``HTTP Error 429`` is the old cooldown) exactly as before.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any
from urllib.parse import urlsplit

from projectzero.core import net
from projectzero.news.catalog import FEEDS

USER_AGENT = "ProjectZero-News (feed reader)"  # decision (f): honest, instead of the old browser string
FEED_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
    "Accept-Language": "de,en;q=0.8",  # the old connectors' language preference
}
MAX_REDIRECTS = 5
MAX_BYTES = net.MAX_BYTES  # the old cap, 8 MB
FEED_TIMEOUT_S = 20.0  # the old PZ_TIMEOUT default, per feed

Policy = Callable[[str, int], None]


class DeadlineReached(net.FetchError):
    """The run's (or the feed's) deadline passed before or during the request."""


class HTTPError(net.FetchError):
    """An error status (the old ``urllib.error.HTTPError``: ``str`` is ``HTTP Error <code>: <phrase>``)."""

    def __init__(self, url: str, code: int, headers: Mapping[str, str]) -> None:
        try:
            phrase = HTTPStatus(code).phrase
        except ValueError:
            phrase = ""
        super().__init__(f"HTTP Error {code}: {phrase}")
        self.url = url
        self.code = code
        self.headers = {str(k).lower(): str(v) for k, v in headers.items()}


def host_of(url: str) -> str:
    try:
        return (urlsplit(str(url or "").strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def allowed_hosts(extra_feeds: Iterable[Mapping[str, Any]] = ()) -> frozenset[str]:
    """The feed hosts: the 10 old ``FEEDS`` plus the given (already filtered: enabled) extra feeds' URLs."""
    urls = [f["url"] for f in FEEDS] + [str(f.get("url") or "") for f in extra_feeds]
    return frozenset(h for h in (host_of(u) for u in urls) if h)


def feed_policy(hosts: Iterable[str], max_redirects: int = MAX_REDIRECTS) -> Policy:
    """https on the default port, a feed host, at most ``max_redirects`` redirects: checked before EVERY send."""
    allowed = frozenset(hosts)

    def policy(url: str, hop: int) -> None:
        if hop > max_redirects:
            raise net.UnsafeURLError(f"refused {str(url)[:120]!r}: more than {max_redirects} redirects")
        try:
            u = urlsplit(str(url or "").strip())
            port = u.port
        except ValueError as exc:
            raise net.UnsafeURLError(f"refused {str(url)[:120]!r}: unparseable URL") from exc
        if u.scheme != "https":
            raise net.UnsafeURLError(f"refused {str(url)[:120]!r}: https only")
        if port not in (None, 443):
            raise net.UnsafeURLError(f"refused {str(url)[:120]!r}: the default https port only")
        if host_of(url) not in allowed:
            raise net.UnsafeURLError(f"refused {str(url)[:120]!r}: not a News feed host")

    return policy


def feed_headers(hosts: Iterable[str]) -> Callable[[str], Mapping[str, str]]:
    """The per-hop headers (decision (f)): the project's own User-Agent, for a feed host only."""
    allowed = frozenset(hosts)

    def headers_for(url: str) -> Mapping[str, str]:
        return dict(FEED_HEADERS) if host_of(url) in allowed else {}

    return headers_for


@dataclass(frozen=True)
class FeedFetch:
    """What the run receives: ``core.net.fetch`` with this transport (None: the pinned production transport), this
    resolver (None: the system resolver) and this run deadline (``clock()`` time at which fetching stops; None: none).
    Tests and the parity pass a fixture transport and resolver, so nothing leaves the machine."""

    transport: net.Transport | None = None
    resolver: net.Resolver | None = None
    deadline: float | None = None
    clock: Callable[[], float] = field(default=time.monotonic)
    timeout: float = FEED_TIMEOUT_S
    max_bytes: int = MAX_BYTES

    def left(self) -> float | None:
        return None if self.deadline is None else self.deadline - self.clock()

    def get(self, url: str, hosts: Iterable[str]) -> str:
        """The feed body as text (the old ``connectors._get`` -> ``net.fetch_text``: UTF-8 with replacement), fetched
        behind the News policy. Raises ``HTTPError`` for an error status, ``DeadlineReached``, ``UnsafeURLError``,
        ``ResponseTooLargeError``, or the transport's ``OSError`` (a TLS failure is an ``ssl.SSLError``)."""
        allowed = frozenset(hosts)
        left = self.left()
        budget = self.timeout if left is None else min(self.timeout, left)
        if budget <= 0:
            raise DeadlineReached("source deadline reached")
        try:
            r = net.fetch(
                url,
                headers=FEED_HEADERS,
                timeout=self.timeout,
                deadline=time.monotonic() + budget,
                max_bytes=self.max_bytes,
                resolver=self.resolver,
                transport=self.transport,
                policy=feed_policy(allowed),
                headers_for=feed_headers(allowed),
                raise_for_status=False,
            )
        except DeadlineReached:
            raise
        except net.FetchError as exc:
            if "deadline" in str(exc):
                raise DeadlineReached(str(exc)) from exc
            raise
        if r.status >= 300:  # an error, or a redirect without a location (the old urllib raised both)
            raise HTTPError(r.url, r.status, r.headers)
        return r.text()

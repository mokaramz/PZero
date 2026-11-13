"""What the cut parsers (``parsers.py``, ``sources_v2.py``) reach outside themselves, per source (review 034a).

The old ``connectors`` read the machine clock, fetched through the old ``net`` (with a TLS-insecure retry), kept the
page-watcher baselines in ``<data>/.watch/`` and marked cursors in place. Here every one of those goes through a
``SourceContext`` the run installs on the worker thread for ONE source:

* ``today()``: the scan's day (the frozen clock of a test or the oracle; Berlin's date in production);
* ``get_raw`` / ``request_json``: ``core/net`` (SSRF guard, pinned addresses, size cap, at most 5 redirects, verified
  TLS: decision e) with the run's transport and resolver (fixtures in every test), each request bounded by the
  source's cooperative deadline as well as by its timeout;
* ``load_snapshot`` / ``save_snapshot``: the watcher's baseline as phase 1 resolved it (revision 2: the
  ``scan_watch_snapshots`` row, else the archived ``.watch/<uid>.json``, else none) and the new lines, kept in memory
  for phase 3;
* ``note_key`` / ``note_record``: which cursor key each record was made under (revision 2's cursor rule).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from projectzero.core import net
from projectzero.events import when

USER_AGENT = "Mozilla/5.0 (ProjectZero personal research tool)"  # the old ``net.USER_AGENT``


@dataclass
class SourceContext:
    today: date
    transport: net.Transport | None = None
    resolver: net.Resolver | None = None
    baselines: Mapping[str, Any] = field(default_factory=dict)  # snapshot key -> the lines phase 1 resolved
    deadline: float | None = None  # wall clock (``time.time()``), the source's cooperative deadline
    saved: dict[str, list[str]] = field(default_factory=dict)  # snapshot key -> the page's new lines
    current_key: str | None = None
    records: list[tuple[dict[str, Any], str | None]] = field(default_factory=list)


_LOCAL = threading.local()


@contextmanager
def source(ctx: SourceContext) -> Iterator[SourceContext]:
    prev = getattr(_LOCAL, "ctx", None)
    _LOCAL.ctx = ctx
    try:
        yield ctx
    finally:
        _LOCAL.ctx = prev


def current() -> SourceContext:
    ctx: SourceContext | None = getattr(_LOCAL, "ctx", None)
    if ctx is None:
        raise RuntimeError("a scan parser ran outside a scan source context")
    return ctx


def today() -> date:
    return current().today


class _Evmod:
    """The old ``domain/events`` as the page watcher used it: ``extract_date`` at the scan's day."""

    @staticmethod
    def extract_date(text: Any) -> str:
        return when.extract_date(text, today=today())


evmod = _Evmod()


def _deadline(ctx: SourceContext) -> float | None:
    if ctx.deadline is None:
        return None
    return time.monotonic() + (ctx.deadline - time.time())


def get_raw(url: str, timeout: float) -> str:
    ctx = current()
    return net.fetch(
        url,
        headers=net.BROWSER_HEADERS,
        timeout=float(timeout),
        deadline=_deadline(ctx),
        transport=ctx.transport,
        resolver=ctx.resolver,
    ).text()


def request_json(url: str, data: bytes | None, headers: Mapping[str, str], timeout: float) -> Any:
    ctx = current()
    r = net.fetch(
        url,
        data=data,
        headers=headers,
        timeout=float(timeout),
        deadline=_deadline(ctx),
        transport=ctx.transport,
        resolver=ctx.resolver,
    )
    return json.loads(r.text())


def load_snapshot(key: str) -> Any:
    got = current().baselines.get(key)
    return list(got) if isinstance(got, list) else []


def save_snapshot(key: str, lines: list[str]) -> None:
    current().saved[key] = list(lines)


def note_key(key: str) -> None:
    current().current_key = key


def note_record(record: dict[str, Any]) -> None:
    ctx = current()
    ctx.records.append((record, ctx.current_key))

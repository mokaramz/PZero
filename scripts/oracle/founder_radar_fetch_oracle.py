"""ORACLE: the OLD Founder Radar scan and research (review 026b) over FIXTURE sites, FIXED clock, pinned ids, no network.
Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/founder_radar_fetch_oracle.py IN.json OUT.json

IN = {clock, sites, names, steps: [{op, body?, at?}]} over a scratch PZ_DATA (a COPY). ``sites`` maps a URL
(``https://host/path?query``) to ``{status, headers?, body?, json?, pad?, tail?, error?}``; ``names`` maps a host to
its addresses (any other host: the old ``FIXTURE_RESOLVER`` address). Ops, through the old route functions of
``api/routers/founder_radar.py``:

* ``scan``  POST /api/radar_scan;  ``research``  POST /api/radar_research;  ``queue``  POST /api/radar_research_queue;
* ``review`` / ``pair``  POST /api/radar_review / radar_pair (operator decisions between two research runs).

Each step records the answer ({code, body} or {raises}), ``wrote`` (the documents whose bytes changed), ``stored``
(people.json and the radar documents, bodies as stored, key order included) and ``requests``: every request the old
code sent, in order (URL and headers).

The fetch entry points are the old code's own, fed by fixtures:
* the collectors' ``_get_json`` answers from ``sites`` (an error status raises the old ``urllib.error.HTTPError``
  with its headers) and records the URL and the headers the old code passed;
* research runs the REAL old ``fetch._fetch_public`` (redirects, cross-origin, https, content type, body cap) with a
  fixture ``connector`` (the old test seam), and ``RESEARCH_RESOLVER`` / the crawl's checks use the ``names`` table.

Pinned (so the new side can reproduce every value): ``date.today()`` / ``datetime.now()`` are frozen in every Founder
Radar module that reads them, the router and ``people``; ``datetime.fromtimestamp`` (the rate-limit reset) gives the
Berlin wall time (the old one used the machine's zone; plan revision 2 §2); the old import id suffix is
``int(sha1(str(key)))`` and the theme terms are sorted (review 026a decision b); ``PYTHONHASHSEED=0``.

No network: ``socket`` DNS / connect, ``urllib.request.urlopen`` and ``http.client.HTTPConnection.connect`` raise.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import subprocess
import sys
import urllib.error
from datetime import date, datetime
from functools import partial
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

NOW: list[datetime] = []
BERLIN = ZoneInfo("Europe/Berlin")
DOCS = ("people.json", "radar_companies.json", "radar_research.json", "radar_metrics.json", "radar_cursor.json",
        "radar_health.json", "radar_research_queue.json")  # fmt: skip
REQUESTS: list[dict[str, Any]] = []
FIXTURE_IP = "93.184.216.34"  # the old research.FIXTURE_RESOLVER answer


class NetworkForbidden(RuntimeError):
    pass


def _refuse(*_a: Any, **_k: Any) -> Any:
    raise NetworkForbidden("the oracle never touches the network")


def _no_network() -> None:
    import socket
    import urllib.request

    socket.getaddrinfo = _refuse  # type: ignore[assignment]
    socket.create_connection = _refuse  # type: ignore[assignment]
    socket.socket.connect = _refuse  # type: ignore[method-assign]
    socket.socket.connect_ex = _refuse  # type: ignore[method-assign]
    urllib.request.urlopen = _refuse  # type: ignore[assignment]
    http.client.HTTPConnection.connect = _refuse  # type: ignore[method-assign]


def _body(spec: dict[str, Any]) -> bytes:
    if "json" in spec:
        return json.dumps(spec["json"]).encode("utf-8")
    return (spec.get("body", "") + " " * int(spec.get("pad", 0)) + spec.get("tail", "")).encode("utf-8")


def _fixtures(inp: dict[str, Any]) -> None:
    from projectzero.domain.founder_radar import collectors, research
    from projectzero.domain.founder_radar import fetch as old_fetch

    sites: dict[str, Any] = inp["sites"]
    names: dict[str, list[str]] = inp.get("names") or {}

    def get_json(url: str, headers: dict[str, str] | None = None) -> Any:
        sent = headers or {"User-Agent": "ProjectZero-FounderRadar", "Accept": "application/json"}  # the old default
        REQUESTS.append({"url": url, "headers": dict(sent)})
        spec = sites.get(url, {"status": 404})
        if spec.get("status", 200) >= 400:
            msg = http.client.HTTPMessage()
            for k, v in (spec.get("headers") or {}).items():
                msg[k] = v
            phrase = http.client.responses.get(spec["status"], "")
            raise urllib.error.HTTPError(url, spec["status"], phrase, msg, None)
        return json.loads(_body(spec).decode("utf-8", "replace"))

    class Resp:
        def __init__(self, spec: dict[str, Any]) -> None:
            self.status = spec.get("status", 200)
            self.headers = {k.lower(): v for k, v in (spec.get("headers") or {}).items()}
            self.data = _body(spec)

        def getheader(self, name: str) -> str | None:
            return self.headers.get(name.lower())

        def read(self, n: int = -1) -> bytes:
            return self.data if n < 0 else self.data[:n]

    class Conn:
        def __init__(self, ip: str, host: str, port: int, timeout: float) -> None:
            self.host, self.ip = host, ip
            self.spec: dict[str, Any] = {}

        def request(self, method: str, path: str, headers: dict[str, str]) -> None:
            url = f"https://{self.host}{path}"
            REQUESTS.append({"url": url, "headers": dict(headers), "ip": self.ip})
            self.spec = sites.get(url, {"status": 404, "headers": {"Content-Type": "text/html"}, "body": ""})
            if self.spec.get("error"):
                raise OSError(self.spec["error"])

        def getresponse(self) -> Resp:
            return Resp(self.spec)

        def close(self) -> None:
            pass

    def resolver(host: str) -> list[str]:
        return list(names.get(host, [FIXTURE_IP]))

    collectors._get_json = get_json
    research._fetch_public = partial(old_fetch._fetch_public, connector=Conn)
    research.RESEARCH_FETCH = None
    research.RESEARCH_RESOLVER = resolver


def _freeze() -> None:
    from projectzero.domain import people
    from projectzero.domain.founder_radar import (
        boardy,
        collectors,
        companies,
        constants,
        csv_import,
        evidence,
        extraction,
        ingestion,
        metrics,
        records,
        research,
        review,
        scanning,
        scoring,
        sources,
        store,
    )

    from projectzero.api.routers import founder_radar as router

    class FixedDate(date):
        @classmethod
        def today(cls) -> FixedDate:  # type: ignore[override]
            n = NOW[-1]
            return cls(n.year, n.month, n.day)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> FixedDateTime:  # type: ignore[override]
            n = NOW[-1]
            return cls(n.year, n.month, n.day, n.hour, n.minute, n.second)

        @classmethod
        def fromtimestamp(cls, t: float, tz: Any = None) -> datetime:  # type: ignore[override]
            return datetime.fromtimestamp(t, BERLIN).replace(tzinfo=None)  # the Berlin wall time (plan rev. 2 §2)

    mods = (router, people, boardy, collectors, companies, csv_import, evidence, extraction, ingestion, metrics,
            records, research, review, scanning, scoring, sources, store)  # fmt: skip
    for mod in mods:
        if hasattr(mod, "date"):
            mod.date = FixedDate  # type: ignore[attr-defined]
        if hasattr(mod, "datetime"):
            mod.datetime = FixedDateTime  # type: ignore[attr-defined]
    ingestion.hash = lambda v: int(hashlib.sha1(str(v).encode("utf-8")).hexdigest(), 16)  # type: ignore[attr-defined]
    terms = constants._theme_terms
    companies._theme_terms = lambda: sorted(terms())


def _answer(fn: Any) -> dict[str, Any]:
    from fastapi.responses import JSONResponse

    try:
        r = fn()
    except Exception as exc:  # the old route would have answered 500
        return {"raises": type(exc).__name__}
    if isinstance(r, JSONResponse):
        return {"code": r.status_code, "body": json.loads(r.body)}
    return {"code": 200, "body": json.loads(json.dumps(r, ensure_ascii=False, default=str))}


def _stored(root: Path) -> dict[str, Any]:
    out = {}
    for name in DOCS:
        p = root / name
        out[name] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    return out


def replay(inp: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    from projectzero.api.routers import founder_radar as r

    ops = {"scan": r.radar_scan, "research": r.radar_research, "queue": r.radar_research_queue,
           "review": r.radar_review, "pair": r.radar_pair}  # fmt: skip
    out: list[dict[str, Any]] = []
    for step in inp["steps"]:
        if step.get("at"):
            NOW.append(datetime.fromisoformat(step["at"]))
        body = step.get("body") or {}
        before = {n: (root / n).read_bytes() if (root / n).exists() else None for n in DOCS}
        REQUESTS.clear()
        row: dict[str, Any] = {"answer": _answer(lambda op=step["op"], body=body: ops[op](body))}
        after = {n: (root / n).read_bytes() if (root / n).exists() else None for n in DOCS}
        row["wrote"] = [n for n in DOCS if before[n] != after[n]]
        row["stored"] = _stored(root)
        row["requests"] = list(REQUESTS)
        out.append(row)
    return out


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and Path(data_dir).name != "project-zero-data", "PZ_DATA must be a scratch folder"
    for k in list(os.environ):
        if k == "SUPABASE_DB_URL" or k.endswith("_API_KEY") or k.endswith("_TOKEN"):
            del os.environ[k]
    os.environ.setdefault("PZ_TESTING", "1")
    inp = json.loads(src.read_text(encoding="utf-8"))
    NOW.append(datetime.fromisoformat(inp["clock"]))
    _no_network()
    _freeze()
    _fixtures(inp)
    from projectzero.domain import taste  # the OLD package

    steps = replay(inp, Path(data_dir))
    old_root = Path(taste.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()  # fmt: skip
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "clock": inp["clock"], "mode": "founder_radar_fetch",
            "hashseed": os.environ.get("PYTHONHASHSEED", "")}  # fmt: skip
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps({"meta": meta, "steps": steps}, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

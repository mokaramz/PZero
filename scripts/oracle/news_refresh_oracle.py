"""ORACLE: the OLD News refresh run (review 028c) driven SYNCHRONOUSLY over a scratch data folder, with a FIXED clock,
the feed fetch replaced by recorded fixture bytes, the model path disabled and EVERY write in memory. Never imported by
new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/news_refresh_oracle.py IN.json OUT.json

IN = {cases_dir, feeds: {url: {status, body, tls}}, runs: [{clock, seam}]} over a scratch PZ_DATA (``cases_dir``: the
old ``SEED_CASES``, as in the 028a / 028b oracles).

1. ``seed``: the old GET-time seeding exactly as the old ``news.view()`` ran it (its guard, then ``seed_cases()``),
   which the store's ``ensure_seeded`` applies before every News write transaction (028b revision 2): recorded as
   ``{added, events}`` (the whole events document after it) or ``null``.
2. Per run, in order and on the SAME in-memory store (run 2 sees run 1's writes): the old ``POST /api/news_refresh``
   (``news.start_refresh("manual")``) with ``threading.Thread`` running its target at once, so the old ``run()``
   completes before ``start_refresh`` builds its answer (decision e); the fetch pool is sequential (the old code
   consumed results in feed order anyway). Recorded: ``answer``; ``events`` (the events document after the run, as
   the next ``load()`` reads it); ``events_saves`` (how many times the run rewrote it); ``appended`` (every
   ``storage.append_line`` as ``[path, text]``, in order); ``saved`` (every other ``storage.save_json`` as ``[path,
   document]``, in order); ``nominated`` (the stubbed ``source_network.nominate`` calls: decision d, the source
   network is not ported); ``views`` (the next old ``news.view()``, ``news_sources.view("90")`` and
   ``news_sources.view("all")``).

The fixture fetch: ``connectors._get`` (the old ``_fetch_feed``'s only network call) answers from ``feeds``: a
status >= 400 raises the old ``urllib.error.HTTPError`` (``HTTP Error <code>: <phrase>``); a ``tls`` feed is served as
the OLD insecure fallback served it (decision a declares the difference: the new fetch fails it); the body is decoded
as the old ``Response.text()`` decoded it (UTF-8, replacement). Nothing reaches the network.

The clock: ``date.today()``, ``datetime.now()`` and ``ledger.now_ts()`` frozen at the run's ``clock`` (naive Berlin
wall time); a feed time is read in Europe/Berlin (decision h: the old ``dt.astimezone()`` used the machine's zone; here
the machine's zone IS Berlin); ``time.time()`` is constant (every elapsed time is 0.0); ``uuid4().hex`` answers the
run's ``seam`` (the new ``new_hex``); ``os.getpid()`` is 4242. The model: ``gateway.complete`` refuses with
``must_stop`` (the old answer without a key or budget), so the old code writes its deterministic ``rules`` cards
(decision b). System health answers no rows (028a decision e) and the deferred views are unavailable, as in the 028a
oracles. The data folder is checked unchanged (``changed``).
"""

from __future__ import annotations

import copy
import email.utils as _email_utils
import hashlib
import importlib
import json
import os
import sys
import threading
import types
import urllib.error
from datetime import date, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from news_oracle import EVENTS, meta, no_health  # the 028a oracle, shared
from validation_oracle import _defer  # the 027a oracle's stubs, shared

BERLIN = ZoneInfo("Europe/Berlin")


class Seam:
    values: ClassVar[list[str]] = []


def _freeze(iso: str) -> type[datetime]:
    from projectzero.domain import taste
    from projectzero.inference import ledger
    from projectzero.services import compressor, health, news, news_sources, pipeline, source_network, validation

    fixed = datetime.fromisoformat(iso)

    class FixedDate(date):
        @classmethod
        def today(cls) -> FixedDate:  # type: ignore[override]
            return cls(fixed.year, fixed.month, fixed.day)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> FixedDateTime:  # type: ignore[override]
            return cls(fixed.year, fixed.month, fixed.day, fixed.hour, fixed.minute, fixed.second)

        def astimezone(self, tz: Any = None) -> Any:  # the machine's zone is Berlin (decision h)
            return super().astimezone(tz or BERLIN)

    for module in (validation, taste, compressor, news, news_sources, health, pipeline, source_network, ledger):
        if hasattr(module, "date"):
            module.date = FixedDate  # type: ignore[attr-defined]
        if hasattr(module, "datetime"):
            module.datetime = FixedDateTime  # type: ignore[attr-defined]
    ledger.now_ts = lambda: fixed.strftime(ledger.TS_FORMAT)  # type: ignore[attr-defined]
    return FixedDateTime


def _install_clockwork(fixed_dt: type[datetime]) -> None:
    """``time.time()`` constant, ``uuid4`` from the seam, ``getpid`` fixed, a synchronous thread and fetch pool, and
    feed times parsed into the Berlin-zoned datetime class."""
    from projectzero.services import news

    def parsedate_to_datetime(s: str) -> Any:
        dt = _email_utils.parsedate_to_datetime(s)
        return fixed_dt(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond, tzinfo=dt.tzinfo)

    class SyncThread:
        def __init__(self, target: Any = None, kwargs: Any = None, **_k: Any) -> None:
            self.target, self.kwargs = target, kwargs or {}

        def start(self) -> None:
            self.target(**self.kwargs)

    class SyncPool:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        def __enter__(self) -> SyncPool:
            return self

        def __exit__(self, *_a: Any) -> None:
            return None

        def map(self, fn: Any, items: Any) -> Any:
            return [fn(x) for x in items]

    def uuid4() -> Any:
        if not Seam.values:
            raise RuntimeError("the id seam ran out of values")
        return types.SimpleNamespace(hex=Seam.values.pop(0))

    news.email = types.SimpleNamespace(utils=types.SimpleNamespace(parsedate_to_datetime=parsedate_to_datetime))  # type: ignore[attr-defined]
    news.time = types.SimpleNamespace(time=lambda: 1000.0)  # type: ignore[attr-defined]
    news.uuid = types.SimpleNamespace(uuid4=uuid4)  # type: ignore[attr-defined]
    news.os = types.SimpleNamespace(getpid=lambda: 4242)  # type: ignore[attr-defined]
    news.threading = types.SimpleNamespace(Thread=SyncThread, Lock=threading.Lock)  # type: ignore[attr-defined]
    news.ThreadPoolExecutor = SyncPool  # type: ignore[attr-defined]


def _install_store(files: dict[str, str], logs: dict[str, list[str]], trace: list[list[Any]]) -> None:
    """Every JSON save in ``files`` (read back by ``load_json``), every appended line in ``logs`` (read back by
    ``read_text``); ``trace`` records them in order. ``write_text`` raises."""
    storage = importlib.import_module("projectzero.storage")
    load_json, read_text = storage.load_json, storage.read_text

    def norm(name: Any) -> str:
        return str(name).replace("\\", "/")

    def save_json(name: Any, data: Any, *, indent: int | None = 1) -> None:
        key = norm(name)
        files[key] = json.dumps(data, ensure_ascii=False, indent=indent)
        trace.append(["save", key, json.loads(files[key])])

    def load(name: Any, default: Any = None, *, tolerant: bool = False) -> Any:
        key = norm(name)
        if key in files:
            return json.loads(files[key])
        return load_json(name, copy.deepcopy(default), tolerant=tolerant)

    def append_line(name: Any, line: str) -> None:
        key = norm(name)
        text = line.replace("\n", " ") + "\n"
        logs.setdefault(key, []).append(text)
        trace.append(["append", key, text])

    def read(name: Any, default: str = "") -> str:
        key = norm(name)
        return read_text(name, default) + "".join(logs.get(key, []))

    def blocked(name: Any, *_a: Any, **_k: Any) -> None:
        raise RuntimeError(f"write {name}")

    storage.save_json = save_json
    storage.load_json = load
    storage.append_line = append_line
    storage.read_text = read
    storage.write_text = blocked


def _install_feeds(feeds: dict[str, Any], fetched: list[str]) -> None:
    from projectzero.domain import connectors

    def _get(url: str) -> str:
        fetched.append(url)
        spec = feeds.get(url)
        if spec is None:
            raise urllib.error.URLError("no fixture for this URL")
        status = int(spec.get("status", 200))
        if status >= 400:
            raise urllib.error.HTTPError(url, status, HTTPStatus(status).phrase, None, None)  # type: ignore[arg-type]
        return spec["body"].encode("utf-8").decode("utf-8", errors="replace")  # the old Response.text()

    connectors._get = _get  # type: ignore[attr-defined]


def _no_model(nominated: list[dict[str, Any]]) -> None:
    from projectzero.inference import gateway
    from projectzero.services import source_network

    def complete(*_a: Any, **_k: Any) -> Any:  # the gateway's refusal without key / budget
        return types.SimpleNamespace(ok=False, must_stop=True, usd=0.0, data=None, model=None)

    def nominate(url: str, *, name: str, family: str, why: str, via: list[dict[str, Any]]) -> str:
        nominated.append({"url": url, "name": name, "family": family, "why": why, "via": via})
        return f"cand-{len(nominated)}"

    gateway.complete = complete  # type: ignore[attr-defined]
    source_network.nominate = nominate  # type: ignore[attr-defined]


def _js(r: Any) -> Any:
    return json.loads(json.dumps(r, ensure_ascii=False, default=str))


def _answer(fn: Any) -> dict[str, Any]:
    try:
        return {"code": 200, "body": _js(fn())}
    except Exception as exc:  # the old route would have answered 500
        return {"raises": type(exc).__name__}


def _hashes(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and Path(data_dir).name != "project-zero-data", "PZ_DATA must be a scratch folder"
    assert not os.environ.get("SUPABASE_DB_URL"), "the oracle never sees the database"
    os.environ.setdefault("PZ_TESTING", "1")
    os.environ["PZ_CASE_PREP"] = "0"
    inp = json.loads(src.read_text(encoding="utf-8"))
    before_files = _hashes(Path(data_dir))
    files: dict[str, str] = {}
    logs: dict[str, list[str]] = {}
    trace: list[list[Any]] = []
    fetched: list[str] = []
    nominated: list[dict[str, Any]] = []
    fixed_dt = _freeze(inp["runs"][0]["clock"])
    _install_store(files, logs, trace)
    _install_clockwork(fixed_dt)
    _install_feeds(inp["feeds"], fetched)
    _no_model(nominated)
    no_health()
    _defer()
    from projectzero.services import news, news_sources  # the OLD package

    storage = importlib.import_module("projectzero.storage")
    if inp["cases_dir"] is not None:
        news.SEED_CASES = Path(inp["cases_dir"])  # type: ignore[attr-defined]
    # 1. the store's ensure_seeded: the old view's guard, then seed_cases()
    seed: Any = None
    if news.SEED_CASES.exists() and len(news.load()["seeded"]) < len(list(news.SEED_CASES.glob("*.json"))):
        with storage.state_lock:
            added = news.seed_cases()
        if EVENTS in files:
            seed = {"added": added, "events": json.loads(files[EVENTS])}
    trace.clear()
    # 2. the runs
    runs: list[dict[str, Any]] = []
    for r in inp["runs"]:
        fixed_dt = _freeze(r["clock"])
        _install_clockwork(fixed_dt)
        Seam.values = list(r["seam"])
        trace.clear()
        fetched.clear()
        nominated.clear()
        answer = _answer(lambda: news.start_refresh("manual"))
        steps = list(trace)
        appended = [[path, text] for kind, path, text in steps if kind == "append"]
        saved = [[path, doc] for kind, path, doc in steps if kind == "save" and path != EVENTS]
        events_saves = sum(1 for kind, path, _doc in steps if kind == "save" and path == EVENTS)
        run_nominated = _js(nominated)
        run_fetched = list(fetched)
        trace.clear()
        views = {
            "news": _answer(news.view),
            "sources:90": _answer(lambda: news_sources.view("90")),
            "sources:all": _answer(lambda: news_sources.view("all")),
        }
        if trace:  # a view never persists here (no seeding left to do)
            raise RuntimeError(f"a view wrote {trace[:2]}")
        runs.append({"answer": answer, "events": json.loads(files[EVENTS]) if EVENTS in files else None,
                     "events_saves": events_saves, "appended": appended, "saved": saved,
                     "nominated": run_nominated, "fetched": run_fetched, "views": views})  # fmt: skip
    after_files = _hashes(Path(data_dir))
    changed = sorted(k for k in {**before_files, **after_files} if before_files.get(k) != after_files.get(k))
    out = {"meta": meta("news-refresh", inp["runs"][0]["clock"]), "seed": seed, "runs": runs, "changed": changed}
    dst.write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

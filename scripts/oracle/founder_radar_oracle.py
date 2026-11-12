"""ORACLE: the OLD Founder Radar routes (review 026a), FIXED clock, pinned ids, no network. Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/founder_radar_oracle.py IN.json OUT.json

IN = {clock, steps: [{op, body?, at?, args?}]} over a scratch PZ_DATA (a COPY: the writes rewrite people.json and
the radar documents). ``at`` moves the fixed clock from that step on (ISO datetime, Berlin wall clock). Ops, through
the old route functions of ``api/routers/founder_radar.py``:

* ``get``  GET /api/founder_radar;  ``proposals``  POST /api/radar_proposals;
* ``action`` / ``import`` / ``company`` / ``promote`` / ``boardy`` / ``pair`` / ``review``: POST radar_action,
  radar_import, radar_company, radar_promote, boardy_brief, radar_pair, radar_review. Each write is followed by the
  whole GET body (``view``) and the stored documents (``stored``: people.json, radar_companies.json,
  radar_research.json, radar_metrics.json, each its body as stored, key order included), and ``wrote``: which of
  them the step rewrote (bytes changed);
* ``region_health`` / ``next_batch``: the old ``sources`` functions over the stored regions / cursor (``args``).

Each answer is {code, body}; a raised exception is {raises: name}.

Pinned (so the new side can reproduce every value):
* the clock: ``date.today()`` / ``datetime.now()`` are frozen in every Founder Radar module that reads them, the
  router and ``people`` (``listing``);
* decision b: the old import id suffix ``abs(hash(key)) % 10000`` used Python's per-process string hash. The oracle
  shadows the builtin in ``ingestion``'s globals with ``int(sha1(str(key)))`` (the new ``ingestion.id_suffix``), and
  ``companies._theme_terms`` returns the theme terms SORTED (the new catalog's); ``PYTHONHASHSEED=0`` pins every
  other set order;
* decision a, normalised: the two READS (``get``, ``proposals``) run over the data folder and every file they wrote
  (migrations, founder references, default regions, the metrics snapshot) is restored byte for byte afterwards, so
  the old store evolves through the writes only, as the new one does.

No network: every old network entry point (``socket`` connect / DNS, ``urllib.request.urlopen``,
``http.client.HTTPConnection.connect``, the collectors, the hardened fetch and the research hook) raises if called.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

NOW: list[datetime] = []
DOCS = ("people.json", "radar_companies.json", "radar_research.json", "radar_metrics.json")


class NetworkForbidden(RuntimeError):
    pass


def _refuse(*_a: Any, **_k: Any) -> Any:
    raise NetworkForbidden("the oracle never touches the network")


def _no_network() -> None:
    import http.client
    import socket
    import urllib.request

    socket.getaddrinfo = _refuse  # type: ignore[assignment]
    socket.create_connection = _refuse  # type: ignore[assignment]
    socket.socket.connect = _refuse  # type: ignore[method-assign]
    socket.socket.connect_ex = _refuse  # type: ignore[method-assign]
    urllib.request.urlopen = _refuse  # type: ignore[assignment]
    http.client.HTTPConnection.connect = _refuse  # type: ignore[method-assign]
    from projectzero.domain.founder_radar import collectors, fetch, research

    for name in ("_get_json", "collect_github", "collect_openalex", "collect_pz_data"):
        setattr(collectors, name, _refuse)
    fetch._fetch_public = _refuse
    research.RESEARCH_FETCH = _refuse
    research.RESEARCH_RESOLVER = _refuse
    research._crawl = _refuse


def _freeze() -> None:
    from projectzero.domain import people
    from projectzero.domain.founder_radar import (
        boardy,
        companies,
        constants,
        csv_import,
        evidence,
        extraction,
        ingestion,
        metrics,
        records,
        review,
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

    mods = (router, people, boardy, companies, csv_import, evidence, extraction, ingestion, metrics, records, review,
            scoring, sources, store)  # fmt: skip
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


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _restore(root: Path, snap: dict[str, bytes]) -> None:
    for p in list(root.rglob("*")):
        if p.is_file() and str(p.relative_to(root)) not in snap:
            p.unlink()
    for rel, raw in snap.items():
        p = root / rel
        if not p.exists() or p.read_bytes() != raw:
            p.write_bytes(raw)


def _read(root: Path, fn: Any) -> dict[str, Any]:
    """A read with decision a applied: whatever it wrote is restored."""
    snap = _snapshot(root)
    try:
        return _answer(fn)
    finally:
        _restore(root, snap)


def _stored(root: Path) -> dict[str, Any]:
    out = {}
    for name in DOCS:
        p = root / name
        out[name] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    return out


def replay(inp: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    from projectzero.domain.founder_radar import sources

    from projectzero import storage
    from projectzero.api.routers import founder_radar as r

    writes = {"action": r.radar_action, "import": r.radar_import, "company": r.radar_company,
              "promote": r.radar_promote, "boardy": r.boardy_brief, "pair": r.radar_pair, "review": r.radar_review}  # fmt: skip
    out: list[dict[str, Any]] = []
    for step in inp["steps"]:
        if step.get("at"):
            NOW.append(datetime.fromisoformat(step["at"]))
        op = step["op"]
        body = step.get("body") or {}
        row: dict[str, Any] = {}
        if op == "get":
            row["answer"] = _read(root, r.get_founder_radar)
        elif op == "proposals":
            row["answer"] = _read(root, lambda body=body: r.radar_proposals(body))
        elif op == "region_health":
            a = step.get("args") or {}
            row["answer"] = _read(root, lambda a=a: sources.region_health(a.get("rows_by_id") or {}, a.get("prev") or []))
        elif op == "next_batch":
            row["answer"] = _read(root, lambda: list(sources.next_batch()))
        else:
            before = {n: (root / n).read_bytes() if (root / n).exists() else None for n in DOCS}
            with storage.state_lock:
                row["answer"] = _answer(lambda op=op, body=body: writes[op](body))
            after = {n: (root / n).read_bytes() if (root / n).exists() else None for n in DOCS}
            row["wrote"] = [n for n in DOCS if before[n] != after[n]]
            row["stored"] = _stored(root)
            row["view"] = _read(root, r.get_founder_radar)
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
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "clock": inp["clock"], "mode": "founder_radar",
            "hashseed": os.environ.get("PYTHONHASHSEED", "")}  # fmt: skip
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps({"meta": meta, "steps": steps}, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

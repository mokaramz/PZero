"""ORACLE: the OLD Deal Flow scan (review 034a), with a FIXED clock and recorded responses. Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/scan_oracle.py IN.json OUT.json

IN = {max_workers, steps: [{clock, days, responses: {key: spec}}]}. ``PZ_DATA`` is a scratch folder holding the
world's files (``sources.json``, ``inbox.json``, ``real_data.json``, ``scan_history.json``, ``.watch/*.json``, ...).

Per step, at the step's clock: the old ``connectors.run_registry_concurrent(days, max_workers, 240, source_budget=90)``
then ``discovery.ingest_scan(cands, report)`` (the old ``run_scan_job`` without its auto-triage start, decision d), and
the record of: the pure output of the registry scan (the batch and the report, before the ingest), the summary, and
the files after the step (``inbox.json``, ``sources.json``, ``scan_history.json`` and every ``.watch/`` baseline).

The network: the old ``connectors._get_raw`` (the page fetch behind ``_get``, so the old fetch telemetry stays) and
``connectors._request_json`` answer from ``responses``, keyed by the URL (a POST by ``"POST <url> <body>"``). A spec
is ``{"body": text}``, ``{"status": n}`` (the old ``HTTPError``) or ``{"error": text}`` (an ``OSError``); an unknown
key is a 404. The clock: ``date.today()`` and ``datetime.now()`` of every loaded ``projectzero`` module. Writes:
``storage.save_json`` / ``write_text`` / ``append_line`` outside the scratch data folder are refused and recorded as
``blocked``. Refused: a ``PZ_DATA`` inside ``project-zero-data``, and any ``SUPABASE_DB_URL``.
"""

from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import sys
import urllib.error
from datetime import date, datetime
from email.message import Message
from pathlib import Path
from typing import Any

NOW: list[datetime] = []
BLOCKED: list[str] = []


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


def _freeze() -> list[str]:
    frozen = []
    for name, module in sorted(sys.modules.items()):
        if not name.startswith("projectzero") or module is None:
            continue
        if getattr(module, "date", None) is date:
            module.date = FixedDate  # type: ignore[attr-defined]
            frozen.append(f"{name}.date")
        if getattr(module, "datetime", None) is datetime:
            module.datetime = FixedDateTime  # type: ignore[attr-defined]
            frozen.append(f"{name}.datetime")
    return frozen


def _block(root: Path) -> None:
    from projectzero import storage

    def inside(name: str, fn: Any) -> Any:
        def guarded(target: Any, *a: Any, **k: Any) -> Any:
            p = Path(str(target))
            full = (p if p.is_absolute() else storage.data_dir() / p).resolve()
            if root not in full.parents:
                BLOCKED.append(f"{name}:{full}")
                raise RuntimeError(f"the scan oracle blocks {name} outside the scratch folder: {full}")
            return fn(target, *a, **k)

        return guarded

    storage.save_json = inside("save_json", storage.save_json)  # type: ignore[assignment]
    storage.write_text = inside("write_text", storage.write_text)  # type: ignore[assignment]
    storage.append_line = inside("append_line", storage.append_line)  # type: ignore[assignment]


def _answer(responses: dict[str, Any], key: str, url: str) -> str:
    spec = responses.get(key) or {"status": 404}
    if "error" in spec:
        raise OSError(spec["error"])
    status = int(spec.get("status", 200))
    if status >= 400:
        reason = {404: "Not Found", 500: "Internal Server Error", 403: "Forbidden"}.get(status, "Error")
        raise urllib.error.HTTPError(url, status, reason, Message(), io.BytesIO(b""))
    return str(spec.get("body", ""))


def _state(root: Path) -> dict[str, Any]:
    def load(rel: str) -> Any:
        p = root / rel
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    watch = {
        f".watch/{p.name}": json.loads(p.read_text(encoding="utf-8"))
        for p in sorted((root / ".watch").glob("*.json"))
    } if (root / ".watch").exists() else {}  # fmt: skip
    return {"inbox": load("inbox.json"), "sources": load("sources.json"), "history": load("scan_history.json"),
            "watch": watch}  # fmt: skip


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and "project-zero-data" not in Path(data_dir).resolve().parts, "PZ_DATA must be a scratch folder"
    assert not os.environ.get("SUPABASE_DB_URL"), "the oracle never sees the database"
    os.environ.setdefault("PZ_TESTING", "1")
    root = Path(data_dir).resolve()
    inp = json.loads(src.read_bytes().decode("utf-8"))
    NOW.append(datetime.fromisoformat(inp["steps"][0]["clock"]))
    from projectzero.domain import connectors, entity_repair, events, sources_v2, taste  # noqa: F401
    from projectzero.services import discovery

    from projectzero import storage

    storage.configure(root)
    frozen = _freeze()
    _block(root)
    steps = []
    for step in inp["steps"]:
        NOW.append(datetime.fromisoformat(step["clock"]))
        responses = step["responses"]

        def get_raw(url: str, responses: dict[str, Any] = responses) -> str:
            return _answer(responses, url, url)

        def request_json(url: str, data: Any = None, headers: Any = None, responses: dict[str, Any] = responses) -> Any:
            key = url if data is None else f"POST {url} {data.decode('utf-8')}"
            return json.loads(_answer(responses, key, url))

        connectors._get_raw = get_raw  # type: ignore[assignment]
        connectors._request_json = request_json  # type: ignore[assignment]
        cands, report = connectors.run_registry_concurrent(
            int(step.get("days", 7)), max_workers=int(inp.get("max_workers", 1)), time_budget=240, source_budget=90
        )
        pure = copy.deepcopy({"merged": cands, "report": report})
        summary = discovery.ingest_scan(cands, report)
        steps.append({"clock": step["clock"], "pure": pure, "summary": summary, **_state(root)})
    old_root = Path(connectors.__file__).resolve().parents[4]
    revision = subprocess.run(["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()  # fmt: skip
    dirty = subprocess.run(["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
                           capture_output=True, text=True, check=True).stdout.strip()  # fmt: skip
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "mode": "scan", "frozen": frozen}
    out = {"meta": meta, "steps": steps, "blocked": list(BLOCKED)}
    dst.write_bytes(json.dumps(out, ensure_ascii=False, indent=1).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

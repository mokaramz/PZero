"""ORACLE: the OLD Network people code (review 013), with a FIXED clock. Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/network_oracle.py MODE IN.json OUT.json

MODE
  reads   IN = {clocks: [iso], sets: [{name, doc}] | null, slugs: [name]}
                -> per set and clock: people.listing(), ecosys.talent_tree(), the /api/watchlist body (each as
                   {ok: value} or {raises: ExceptionType}); plus STRENGTHS, POTENTIAL, FIELDS and people._slug(name).
                   ``sets: null`` reads the data folder as it is (the real snapshot copy); otherwise each set's ``doc``
                   is written as people.json first.
  writes  IN = {clock, steps: [{op: person_save | upsert | talented | watch_log, body}]}
                -> per step: the HTTP code and body the old route returned, then the stored people.json people.
                   ``person_save`` is the old route (founder_radar.operator_save); ``upsert`` is the same route check
                   with the bare people.upsert (no Founder Radar recompute).

Both need PZ_DATA = a scratch folder (empty, or a byte-exact COPY of the old data folder): they write people.json.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any


def _clock(iso: str) -> tuple[type[date], type[datetime]]:
    fixed = datetime.fromisoformat(iso)

    class FixedDate(date):
        @classmethod
        def today(cls) -> FixedDate:  # type: ignore[override]
            return cls(fixed.year, fixed.month, fixed.day)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> FixedDateTime:  # type: ignore[override]
            return cls(fixed.year, fixed.month, fixed.day, fixed.hour, fixed.minute, fixed.second)

    return FixedDate, FixedDateTime


def _freeze(iso: str) -> None:
    from projectzero.api.routers import network
    from projectzero.domain import people
    from projectzero.domain.founder_radar import ingestion

    fd, fdt = _clock(iso)
    people.date = fd  # type: ignore[attr-defined]
    network.datetime = fdt  # type: ignore[attr-defined]
    ingestion.date = fd  # type: ignore[attr-defined]
    ingestion.datetime = fdt  # type: ignore[attr-defined]


def _try(fn: Any) -> Any:
    try:
        return {"ok": fn()}
    except Exception as exc:  # the goldens record WHICH cases raise, not only what the others return
        return {"raises": type(exc).__name__}


def reads(inp: dict[str, Any]) -> dict[str, Any]:
    from projectzero import storage
    from projectzero.api.routers import network
    from projectzero.domain import ecosys, people

    out: dict[str, Any] = {"sets": {}}
    sets = inp.get("sets")
    for s in sets if sets is not None else [{"name": "data", "doc": None}]:
        if s["doc"] is not None:
            storage.save_json("people.json", s["doc"], indent=2)
        per: dict[str, Any] = {}
        for clock in inp["clocks"]:
            _freeze(clock)
            per[clock] = {
                "listing": _try(people.listing),
                "tree": _try(ecosys.talent_tree),
                "watchlist": _try(network.watchlist),
            }
        out["sets"][s["name"]] = per
    out["strengths"] = people.STRENGTHS
    out["potential"] = people.POTENTIAL
    out["fields"] = people.FIELDS
    out["slugs"] = [people._slug(n) for n in inp.get("slugs", [])]
    return out


def writes(inp: dict[str, Any]) -> dict[str, Any]:
    from projectzero.api.errors import ApiError
    from projectzero.api.routers import network
    from projectzero.domain import people

    _freeze(inp["clock"])
    out = []
    for step in inp["steps"]:
        body = copy.deepcopy(step["body"])
        try:
            if step["op"] == "person_save":
                code, payload = 200, network.person_save(body)
            elif step["op"] == "upsert":
                if not body.get("id") and not str(body.get("name") or "").strip():
                    raise ApiError("name required")
                code, payload = 200, {"ok": True, "id": people.upsert(body)}
            elif step["op"] == "talented":
                code, payload = 200, network.talented(body)
            else:
                code, payload = 200, network.watch_log(body)
        except ApiError as exc:
            code, payload = exc.status_code, {"ok": False, "error": exc.message, **exc.payload}
        except Exception as exc:
            code, payload = 500, {"ok": False, "error": f"internal error ({type(exc).__name__})"}
        out.append({"code": code, "body": payload, "people": people.load().get("people", [])})
    return {"steps": out}


def main() -> int:
    mode, src, dst = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and Path(data_dir).name != "project-zero-data", "PZ_DATA must be a scratch folder"
    os.environ.setdefault("PZ_TESTING", "1")
    inp = json.loads(src.read_text(encoding="utf-8"))
    from projectzero.domain import people  # the OLD package

    old_root = Path(people.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()  # fmt: skip
    result = {"reads": reads, "writes": writes}[mode](inp)
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "mode": mode}
    dst.write_text(json.dumps({"meta": meta, **result}, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

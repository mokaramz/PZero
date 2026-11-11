"""ORACLE: runs the OLD Project Zero ranking modules on given inputs. Never imported by the new code.

Run with the OLD repository's interpreter and package (the parity tooling does this for you):

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/ranking_oracle.py IN.json OUT.json

IN.json  = {"last_run": ..., "candidates": [...], "ledgers": {"name": ledger, ...}}
OUT.json = {"meta": {...}, "per_candidate": {key: {themes, lens, attention_v2, feedback: {ledger_name: ...}}}}

Candidates are keyed by their position-qualified key ``"<index>:<id>"`` so duplicate or missing ids are visible.
PZ_DATA must point at an empty scratch folder: the old modules read settings on import and must never see real data.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and "project-zero-data" not in data_dir, "PZ_DATA must be a scratch folder"
    os.environ.setdefault("PZ_TESTING", "1")

    from projectzero.domain import attention, feedback, themes  # the OLD package (sys.path set by the caller)

    old_root = Path(attention.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero/domain"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()

    inp = json.loads(src.read_text(encoding="utf-8"))
    last_run = inp["last_run"]
    # Each ledger goes through the OLD production read path: written as <PZ_DATA>/feedback.json, read by
    # feedback.table() (tolerant load -> _normalize, signature cache). A ledger of None means "no file at all".
    ledger_file = Path(data_dir) / "feedback.json"
    tables = {}
    for name, led in inp["ledgers"].items():
        if led is None:
            ledger_file.unlink(missing_ok=True)
        else:
            ledger_file.write_text(json.dumps(led), encoding="utf-8")
        feedback._CACHE["sig"] = None
        tables[name] = feedback.table()
    per = {}
    for index, c in enumerate(inp["candidates"]):
        sc, sig = themes.lens_signals(c)
        per[f"{index}:{c.get('id')}"] = {
            "themes": themes.themes_for(c),
            "lens": {"score": sc, "signals": sig},
            "attention_v2": attention.annotate_v31(c, last_run),
            "feedback": {name: feedback.for_candidate(c, tbl) for name, tbl in tables.items()},
        }
    out = {
        "meta": {
            "old_revision": revision,
            "old_domain_dirty": bool(dirty),
            "candidates": len(inp["candidates"]),
            "last_run": last_run,
            "ledgers": sorted(inp["ledgers"]),
        },
        "per_candidate": per,
    }
    dst.write_text(json.dumps(out, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

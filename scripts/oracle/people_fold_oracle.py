"""ORACLE: the OLD person-identity key ``services/identity.fold`` (review 012). Never imported by the new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/people_fold_oracle.py IN.json OUT.json

IN.json = {"values": [...]} (any JSON values: the old fold takes ``Any``); OUT.json = {"meta": {...}, "folded": [...]}.
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

    from projectzero.services import identity  # the OLD package (sys.path set by the caller)

    old_root = Path(identity.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    values = json.loads(src.read_text(encoding="utf-8"))["values"]
    out = {"meta": {"old_revision": revision, "old_dirty": bool(dirty)}, "folded": [identity.fold(v) for v in values]}
    dst.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

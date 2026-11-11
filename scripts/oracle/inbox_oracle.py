"""ORACLE: the OLD ``GET /api/inbox`` payload (``services/discovery.inbox_view``) for review 009. Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/inbox_oracle.py OUT.json

PZ_DATA must point at a scratch COPY of the old data folder: ``inbox_view`` persists migrations and milestones
(``save_inbox``), so it must never run on the real folder.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    dst = Path(sys.argv[1])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and Path(data_dir).name != "project-zero-data", "PZ_DATA must be a scratch copy"
    os.environ.setdefault("PZ_TESTING", "1")

    from projectzero.services import discovery  # the OLD package

    old_root = Path(discovery.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    view = discovery.inbox_view()
    out = {"meta": {"old_revision": revision, "old_dirty": bool(dirty)}, "view": view}
    dst.write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

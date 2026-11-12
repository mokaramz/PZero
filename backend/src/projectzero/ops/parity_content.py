"""Public work parity: the port against the OLD routes as oracle, with a FIXED clock (review 020).

    python -m projectzero.ops.parity_content goldens   # (re)generate tests/fixtures/golden_v1/oracle_content.json

The oracle (``scripts/oracle/content_oracle.py``) replays ``SCRIPT`` on the old ``content_save`` / ``content_delete``
over a scratch data folder seeded with ``SEED`` (two ordered items and an extra top-level key) and records, per step,
the response and the whole ``GET /api/content``. ``NUMERIC`` records what the old app did with a JSON-number id (it
stored it). The hosted test ``tests/hosted/test_content_hosted.py`` imports the same seed through the archived
document + ``backfill_content_items()`` and replays the script on the new endpoints: 0 differences expected.
The deliberate changes (a second new item in the same second; a non-string id) are tested on their own.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from projectzero.core.paths import REPO_ROOT
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO

ORACLE = REPO_ROOT / "scripts" / "oracle" / "content_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_content.json"
CLOCK = "2026-11-11T12:00:00"
SEED: dict[str, Any] = {
    "note": "an extra top-level key the old file carried",
    "items": [
        {"id": "c-261101090000", "created": "2026-11-01", "title": "Seeded draft", "platform": "blog", "kind": "draft"},
        {"id": "c-261020080000", "created": "2026-10-20", "title": "Seeded idea", "inbound": "One reply"},
    ],
}


def _at(seconds: int) -> str:
    return f"2026-11-11T12:00:{seconds:02d}"


SCRIPT: list[dict[str, Any]] = [
    {
        "op": "save",
        "at": _at(0),
        "body": {"title": "First idea", "platform": "linkedin", "kind": "idea", "url": "", "inbound": "", "notes": ""},
    },
    {"op": "save", "at": _at(1), "body": {"title": "Second", "kind": "draft", "url": "https://example.com/p"}},
    {"op": "save", "at": _at(2), "body": {"id": "c-261111120000", "title": "First idea, edited", "inbound": "Two DMs"}},
    {"op": "save", "at": _at(3), "body": {"id": "c-261111120000", "kind": "published"}},
    {"op": "save", "at": _at(4), "body": {"id": "c-261111120001", "inbound": 3, "notes": ["a", "b"], "status": True}},
    {"op": "save", "at": _at(5), "body": {"id": "c-261111120001", "inbound": 3}},  # unchanged
    {"op": "save", "at": _at(6), "body": {"id": "my-own-id", "title": "Own id"}},
    {"op": "save", "at": _at(7), "body": {}},
    {"op": "save", "at": _at(8), "body": {"id": "", "title": "Falsy id", "extra": "ignored"}},
    {"op": "save", "at": _at(9), "body": {"id": "c-261101090000", "title": "Seeded draft, edited"}},
    {"op": "delete", "at": _at(10), "body": {"id": "no-such-item"}},
    {"op": "delete", "at": _at(11), "body": {"id": "c-261111120001"}},
    {"op": "delete", "at": _at(12), "body": {"id": "c-261111120001"}},
    {"op": "delete", "at": _at(13), "body": {}},
    {"op": "save", "at": _at(14), "body": {"id": "c-261111120001", "title": "Back again"}},
    {"op": "delete", "at": _at(15), "body": {"id": "c-261020080000"}},
]
NUMERIC: list[dict[str, Any]] = [{"op": "save", "at": _at(20), "body": {"id": 7, "title": "A number id"}}]


def run_oracle(inp: dict[str, Any], seed: dict[str, Any] | None) -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-content-oracle-") as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        if seed is not None:
            (data / "content.json").write_text(json.dumps(seed, indent=2), encoding="utf-8")
        src, dst = Path(tmp) / "in.json", Path(tmp) / "out.json"
        src.write_text(json.dumps(inp), encoding="utf-8")
        env = {**os.environ, "PZ_DATA": str(data), "PZ_TESTING": "1", "PYTHONPATH": str(OLD_REPO / "backend" / "src")}
        env.pop("SUPABASE_DB_URL", None)
        run = subprocess.run([str(python), str(ORACLE), str(src), str(dst)], env=env, capture_output=True, text=True)
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_text(encoding="utf-8"))
        return out


def write_goldens() -> int:
    main_run = run_oracle({"clock": CLOCK, "steps": SCRIPT}, SEED)
    numeric = run_oracle({"clock": CLOCK, "steps": NUMERIC}, {"items": []})
    meta = main_run.pop("meta")
    numeric.pop("meta")
    golden = {"provenance": meta, "seed": SEED, "script": SCRIPT, "expected": main_run["steps"],
              "numeric": {"script": NUMERIC, "expected": numeric["steps"]}}  # fmt: skip
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    raises = sum(1 for s in main_run["steps"] if "raises" in s)
    final = main_run["steps"][-1]["view"]
    print(f"content goldens written: {len(SCRIPT)} steps ({raises} raise), final items "
          f"{[i.get('id') for i in final['items']]}; numeric id stored as "
          f"{type(numeric['steps'][0]['view']['items'][0]['id']).__name__}; provenance "
          f"{meta['old_revision'][:7]} dirty={meta['old_dirty']}")  # fmt: skip
    return 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["goldens"]:
        return write_goldens()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

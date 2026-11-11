"""ORACLE: runs the OLD Project Zero ingest tagging on given inputs. Never imported by the new code (review 007).

Run with the OLD repository's interpreter and package (``python -m projectzero.ops.parity_tagging`` does this):

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/tagging_oracle.py IN.json OUT.json

IN.json = {"cases": [{"key", "source": {...old source config...}, "records": [{"name", "description", "tier"}],
                      "absorb": [{"source": {...}, "records": [...]}] (optional), "rank": bool (optional)}],
           "run_id": "...", "last_run": ...}

Each case runs the REAL old per-source step: a fake parser is registered in ``connectors.PARSERS`` that returns the
old ``connectors.make(...)`` records, and ``connectors._scan_one`` does the rest (interstitial drop, src_quality,
sectors, bio, the ``priority or 5`` bonus, probation). ``absorb`` sources are scanned the same way and folded into
every kept host record with the old ``discovery.absorb``. With ``rank``, each kept record is also ranked by the old
``attention.annotate_v31`` as a live lead (decision ``new``, no notes - decision 0002 #7).

OUT.json = {"meta": {...}, "tables": {...}, "cases": {key: {"kept": [...], "report": {...}, "attention": [...]}}}
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

    from projectzero.domain import attention, connectors, taste  # the OLD package (sys.path set by the caller)
    from projectzero.services import discovery

    old_root = Path(connectors.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()

    inp = json.loads(src.read_text(encoding="utf-8"))

    def scan(source: dict, records: list[dict]) -> tuple[list[dict], dict]:
        def fake_parser(s: dict) -> list[dict]:
            return [
                connectors.make(r["name"], s["name"], r["tier"], "", "", "", r["description"], "", "")
                for r in records
            ]

        connectors.PARSERS["pz_oracle"] = fake_parser
        config = {"enabled": True, "kind": "oracle", **source, "parser": "pz_oracle"}
        kept, report = connectors._scan_one(config, 7, "2026-11-11 00:00:00")
        assert report["status"] == "ok", report
        return kept, report

    cases = {}
    for case in inp["cases"]:
        kept, report = scan(case["source"], case["records"])
        for extra in case.get("absorb") or []:
            others, _ = scan(extra["source"], extra["records"])
            for host in kept:
                for other in others:
                    discovery.absorb(host, other, inp["run_id"])
        out = {"kept": kept, "report": {k: report[k] for k in ("raw", "count", "interstitial")}}
        if case.get("rank"):
            out["attention"] = [
                attention.annotate_v31({**c, "decision": "new", "notes": ""}, inp.get("last_run")) for c in kept
            ]
        cases[case["key"]] = out

    tables = {
        "archetypes": [[aid, name, list(kws)] for aid, name, _test, kws in taste.ARCHETYPES],
        "portfolio": [[name, list(kws)] for name, _what, kws in taste.PORTFOLIO],
        "noise": list(connectors.NOISE),
        "ambiguous_kw": sorted(connectors.AMBIGUOUS_KW),
        "sector_keywords": dict(connectors.SECTOR_KEYWORDS),
        "interstitial": [connectors.INTERSTITIAL.pattern, int(connectors.INTERSTITIAL.flags)],
    }
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "cases": len(cases)}
    dst.write_text(json.dumps({"meta": meta, "tables": tables, "cases": cases}, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

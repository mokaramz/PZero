"""Tagging parity: the ported ingest tagging against the OLD code as oracle (review 007).

    python -m projectzero.ops.parity_tagging goldens   # (re)generate tests/fixtures/golden_v1/oracle_tagging.json

The oracle (``scripts/oracle/tagging_oracle.py``) runs in the OLD repository's interpreter and package, in a scratch
``PZ_DATA``: the real old ``connectors.make`` and ``connectors._scan_one`` (through an injected fake parser) and the
old ``discovery.absorb``. The goldens it writes are checked offline by the test suite, so the gate never needs the
old repository.

The corpus covers what the old rules are sensitive to: keywords beyond the 120 / 600 truncation, broad vs
distinctive vs multi-word keywords, noise, bio, every tier, every reliability (and a missing one), probation, the
``priority or 5`` quirk, interstitial text before and after character 400, cross-source absorption, and the Grok
Cycle 008 sample through the decision 0002 mapping, ranked by the old ``annotate_v31``.
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
from projectzero.dealflow.ranking import attention, tagging
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff

ORACLE = REPO_ROOT / "scripts" / "oracle" / "tagging_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_tagging.json"
SAMPLE = REPO_ROOT / "docs" / "team" / "samples" / "grok_cycle_sample.json"
RUN_ID = "submission-0001"  # the sighting stamp: a submission id on the new side, a run id on the old
LAST_RUN = "2026-11-08 19:09:09"

# Old-record fields that are not ranking inputs and are not ported: clock / url / location / run plumbing.
NOT_PORTED = frozenset({
    "source_url", "date", "date_kind", "detected_on", "location", "country", "first_seen", "source_date",
    "geo_scope", "last_observed", "seen_runs", "entity_ids", "q_found",
})  # fmt: skip
# Decision 0002 #7, applied on top of the old record for live leads: kept new, no generated note.
LIVE_DEVIATION = {"decision": "new", "notes": ""}


def _source(sid: str, reliability: str | None, *, probation: bool = False, **extra: Any) -> dict[str, Any]:
    src: dict[str, Any] = {"id": sid, "name": f"Oracle {sid}", "probation": probation, "geo": ["DE"],
                           "sectors": ["ai"], **extra}  # fmt: skip
    if reliability is not None:
        src["reliability"] = reliability
    return src


def _rec(name: str, description: str, tier: str) -> dict[str, str]:
    return {"name": name, "description": description, "tier": tier}


def synthetic_cases() -> list[dict[str, Any]]:
    pad = "Industrial company building tools for operators across Europe. " * 12  # > 600 characters
    assert len(pad) > 600
    records = [
        _rec("Plain GmbH", "We sell things to people.", "registry"),
        _rec("Freight Agents AG", "AI agents for freight forwarders and customs paperwork", "registry"),
        _rec("Chem One", "A chemical distributor", "announcement"),  # one broad keyword: no archetype
        _rec("Chem Two", "chemical packaging for industry", "announcement"),  # two broad hits: archetype
        _rec("Longword", "underwriting automation", "grant"),  # a distinctive single keyword (>= 8 chars)
        _rec("Phrase Co", "a counter-drone sensor fusion stack", "pre_company"),  # multi-word phrases
        _rec("Beyond600", pad + " stablecoin e-money licence", "registry"),  # keywords only after 600
        _rec("N" * 125 + " freight", "short description", "registry"),  # keyword only after name 120
        _rec("Holding Verwaltung GmbH", "holding and consulting", "registry"),  # noise
        _rec("Handel Shop", "handel mit waren", "registry"),  # "handel " keeps its trailing space
        _rec("Quirk Zero", "holding stablecoin payments mica drone uav defence military nato freight", "pre_company"),
        _rec("Bio Spinout", "biotech antibody platform for oncology diagnostics", "pre_company"),
        _rec("Twin Seeker", "accounting ledger bookkeeping vat for SMEs", "manual"),
        _rec("Cookie Wall", "We use cookies to improve your experience", "registry"),  # interstitial: dropped
        _rec("Late Cookie", pad[:390] + " we use cookies", "registry"),  # the match starts after 400: kept
    ]
    late = records[-1]
    assert len(tagging.interstitial_check_text(late["name"], late["description"])) == 400
    cases = []
    for sid, reliability, probation in (("hi", "high", True), ("med", "medium", False), ("lo", "low", False),
                                        ("none", None, False)):  # fmt: skip
        cases.append({"key": f"synthetic-{sid}", "source": _source(sid, reliability, probation=probation),
                      "records": records, "rank": True})  # fmt: skip
    return cases


def live_source(origin: str) -> dict[str, Any]:
    s = tagging.LIVE_SOURCES[origin]
    return {"id": s["id"], "name": s["name"], "reliability": s["reliability"], "probation": s["probation"],
            "geo": [], "sectors": []}  # fmt: skip


def sample_entities() -> list[dict[str, Any]]:
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    return [e for e in sample["entities"] if e["kind"] in ("company", "opportunity")]


def live_cases() -> list[dict[str, Any]]:
    cases = []
    for index, entity in enumerate(sample_entities()):
        inputs = tagging.live_inputs("grok", entity["name"], entity.get("key_fact"), entity.get("stage"),
                                     entity.get("flags"))  # fmt: skip
        records = [_rec(inputs["name"], inputs["description"], inputs["tier"])]
        cases.append({"key": f"cycle008-{index}", "source": live_source("grok"), "records": records, "rank": True})
    # a cross-source sighting: the first Cycle 008 company re-reported by an operator paste (manual origin)
    first = sample_entities()[0]
    host = tagging.live_inputs("grok", first["name"], first.get("key_fact"), first.get("stage"), first.get("flags"))
    other = tagging.live_inputs("manual", first["name"], "pasted by the operator", None, ["pre_company"])
    cases.append({"key": "absorb-grok-manual", "source": live_source("grok"),
                  "records": [_rec(host["name"], host["description"], host["tier"])],
                  "absorb": [{"source": live_source("manual"),
                              "records": [_rec(other["name"], other["description"], other["tier"])]}],
                  "rank": True})  # fmt: skip
    return cases


def run_oracle(cases: list[dict[str, Any]]) -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-tag-oracle-") as tmp:
        tmpdir = Path(tmp)
        (tmpdir / "data").mkdir()
        src, dst = tmpdir / "in.json", tmpdir / "out.json"
        src.write_text(json.dumps({"cases": cases, "run_id": RUN_ID, "last_run": LAST_RUN}), encoding="utf-8")
        env = {**os.environ, "PZ_DATA": str(tmpdir / "data"), "PYTHONPATH": str(OLD_REPO / "backend" / "src")}
        env.pop("SUPABASE_DB_URL", None)
        run = subprocess.run([str(python), str(ORACLE), str(src), str(dst)], env=env, capture_output=True, text=True)
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_text(encoding="utf-8"))
        return out


# ------------------------------------------------------------ the new side
def new_tables() -> dict[str, Any]:
    return {
        "archetypes": [[aid, name, list(kws)] for aid, name, kws in tagging.ARCHETYPES],
        "portfolio": [[name, list(kws)] for name, kws in tagging.PORTFOLIO],
        "noise": list(tagging.NOISE),
        "ambiguous_kw": sorted(tagging.AMBIGUOUS_KW),
        "sector_keywords": dict(tagging.SECTOR_KEYWORDS),
        "interstitial": [tagging.INTERSTITIAL.pattern, int(tagging.INTERSTITIAL.flags)],
    }


def _scan(case_source: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept = []
    for r in records:
        if tagging.is_interstitial(tagging.interstitial_check_text(r["name"], r["description"])):
            continue
        rec = tagging.make_core(r["name"], r["description"], r["tier"], case_source["name"])
        kept.append(tagging.per_source(rec, case_source))
    return kept


def new_case(case: dict[str, Any]) -> dict[str, Any]:
    kept = _scan(case["source"], case["records"])
    for extra in case.get("absorb") or []:
        for other in _scan(extra["source"], extra["records"]):
            sighting = {"source": other["source"], "url": "", "source_id": other["source_id"],
                        "discovery_tier": other["discovery_tier"], "source_date": "", "first_seen": RUN_ID}  # fmt: skip
            for host in kept:
                tagging.absorb(host, sighting)
    out: dict[str, Any] = {"kept": kept}
    if case.get("rank"):
        out["attention"] = [attention.annotate_v31({**c, **LIVE_DEVIATION}, LAST_RUN) for c in kept]
    return out


def project(old: dict[str, Any], new_keys: set[str]) -> tuple[dict[str, Any], list[str]]:
    """The old record restricted to ported fields; any other unexpected old field is reported as a problem."""
    problems = [f"old field '{k}' is neither ported nor listed in NOT_PORTED" for k in sorted(old.keys() - new_keys)
                if k not in NOT_PORTED]  # fmt: skip
    return {k: v for k, v in old.items() if k in new_keys}, problems


def compare_case(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if len(old["kept"]) != len(new["kept"]):
        return [f"kept: old {len(old['kept'])} records, new {len(new['kept'])}"]
    for i, (o, n) in enumerate(zip(old["kept"], new["kept"], strict=True)):
        projected, problems = project(o, set(n))
        out += [f"kept/{i}: {p}" for p in problems]
        out += [f"kept/{i}" + d for d in diff(json.loads(json.dumps(projected)), json.loads(json.dumps(n)))]
    if "attention" in old:
        out += ["attention" + d for d in diff(old["attention"], json.loads(json.dumps(new["attention"])))]
    return out


def write_goldens() -> int:
    cases = synthetic_cases() + live_cases()
    oracle = run_oracle(cases)
    problems = ["tables" + d for d in diff(oracle["tables"], new_tables())]
    for case in cases:
        problems += [f"{case['key']}: {p}" for p in compare_case(oracle["cases"][case["key"]], new_case(case))]
    golden = {"provenance": oracle["meta"], "run_id": RUN_ID, "last_run": LAST_RUN, "not_ported": sorted(NOT_PORTED),
              "cases": cases, "tables": oracle["tables"], "expected": oracle["cases"]}  # fmt: skip
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    kept = sum(len(v["kept"]) for v in oracle["cases"].values())
    print(f"tagging goldens written: {len(cases)} cases, {kept} kept records; new code differences: {len(problems)}")
    for p in problems[:40]:
        print("  DIFF", p)
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["goldens"]:
        return write_goldens()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

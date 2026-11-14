"""Review 032c, offline (no database): the stored runner goldens against the pure parts, the catalog, the switches,
the oracle's refusals and the CLI's argument handling. The database behaviour is ``tests/hosted/test_jobs_hosted.py``
and ``python -m projectzero.ops.parity_jobs hosted``."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from projectzero.core.config import Settings
from projectzero.core.occurrence import ALREADY_RAN, AlreadyRan, check
from projectzero.health import core as health_core
from projectzero.health.catalog import JOBS, classify
from projectzero.jobs import __main__ as cli
from projectzero.jobs import runner
from projectzero.jobs.catalog import REAL
from projectzero.jobs.ported import PORTED, RUNNER
from projectzero.ops import parity_jobs as pj
from projectzero.ops.parity_ranking import OLD_REPO

GOLDEN = pj.read_golden()


def test_the_goldens_match_the_pure_parts_and_were_made_by_the_clean_old_revision() -> None:
    assert pj.check(GOLDEN) == []
    assert GOLDEN["provenance"]["old_revision"] == "6c739b9cb6ca2517b845e381d39a36c50eccc59e"
    assert GOLDEN["provenance"]["old_dirty"] is False
    assert [c["name"] for c in GOLDEN["cases"]] == [c["name"] for c in pj.cases()]
    assert all(c["blocked"] == [] for c in GOLDEN["cases"])  # the old runner wrote only under schedule/
    dry = next(c for c in GOLDEN["cases"] if c["name"] == "dry")["steps"][0]["out"]
    assert dry["wrote"] is False  # the old dry run wrote nothing
    assert "MohamedKaram" not in json.dumps(GOLDEN) and "<scratch folder>" in json.dumps(GOLDEN)  # no local path


def test_only_the_ported_jobs_are_runnable_and_their_rows_are_the_old_ones() -> None:
    assert (
        set(REAL) == PORTED and len(PORTED) == 8
    )  # review 034a: deal_flow_scan; 035b: triage_retry; 037b: watch_checks
    rows = {r["id"]: r for r in JOBS}
    for jid, job in REAL.items():
        assert (job.label, job.interval_h, job.last) == (
            rows[jid]["label"],
            float(rows[jid]["interval_h"]),
            rows[jid]["last"],
        )
    cat = runner.catalog()
    assert [r["id"] for r in cat.rows] == [j["id"] for j in health_core.active_jobs()]
    assert len(set(cat.rows[i]["id"] for i in range(len(cat.rows))) - set(cat.runnable)) == 3  # 037b: watch_checks runs
    assert health_core.RUNNER is RUNNER


def test_the_occurrence_check_and_the_skipped_note() -> None:
    assert classify(ALREADY_RAN, True) == "skipped"
    check(None, None)  # type: ignore[arg-type]  # no check: nothing happens
    check(lambda conn: True, None)  # type: ignore[arg-type]
    with pytest.raises(AlreadyRan, match=ALREADY_RAN):
        check(lambda conn: False, None)  # type: ignore[arg-type]


def test_the_switches_are_off_under_tests_and_follow_config(monkeypatch: pytest.MonkeyPatch) -> None:
    assert os.environ["PZ_CATCHUP"] == "0" and runner.env_enabled() is False  # tests/conftest.py
    assert runner.app_start("postgresql://unused", "pz_itest_00000000") == {"started": False, "reason": "disabled"}
    monkeypatch.setenv("PZ_CATCHUP", "1")
    assert runner.enabled({}) and runner.enabled({"catch_up": {"enabled": True}})
    assert not runner.enabled({"catch_up": {"enabled": False}})
    monkeypatch.setenv("PZ_CATCHUP", "off")
    assert not runner.enabled({})


def test_the_cli_without_a_mode_prints_its_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([], settings=Settings(db_url="postgresql://unused", schema="pz_itest_00000000")) == 2
    assert "--lock-status" in capsys.readouterr().out


@pytest.mark.skipif(not (OLD_REPO / "backend" / ".venv").exists(), reason="the old repository is not checked out")
@pytest.mark.parametrize("env", [{"PZ_DATA": r"C:\nowhere\project-zero-data\x"}, {"SUPABASE_DB_URL": "postgresql://x"}])
def test_the_oracle_refuses_the_real_data_folder_and_the_database(tmp_path: Path, env: dict[str, str]) -> None:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    (tmp_path / "in.json").write_text(json.dumps({"cases": [], "classify": []}), encoding="utf-8")
    base = {k: v for k, v in os.environ.items() if k != "SUPABASE_DB_URL"}
    res = subprocess.run([str(python), str(pj.ORACLE), str(tmp_path / "in.json"), str(tmp_path / "out.json")],
                         env={**base, "PZ_DATA": str(tmp_path / "data"), **env}, capture_output=True, text=True)  # fmt: skip
    assert res.returncode != 0 and "AssertionError" in res.stderr
    assert not (tmp_path / "out.json").exists()

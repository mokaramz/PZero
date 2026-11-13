"""Review 036a: a failing test never prints the database password (the conftest's report scrubber)."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

from tests import conftest

FAKE = "postgresql://postgres.invented:S3cr%40t-pw-0000@db.invented.example:5432/postgres"


def test_scrub_removes_the_url_and_every_form_of_its_password(monkeypatch: object) -> None:
    conftest.SECRETS[:] = []
    conftest.SECRETS.extend(sorted({FAKE, "S3cr%40t-pw-0000", "S3cr@t-pw-0000"}, key=len, reverse=True))
    try:
        text = f"db_url = '{FAKE}' and again S3cr@t-pw-0000 and S3cr%40t-pw-0000"
        out = conftest.scrub(text)
        assert "S3cr" not in out and out.count(conftest.REDACTED) == 3
    finally:
        conftest.SECRETS[:] = conftest._secrets()


def test_a_failing_test_with_the_url_in_its_arguments_prints_no_password(tmp_path: Path) -> None:
    """A real pytest run: a test whose failing frame holds the URL as a plain argument (a long traceback prints it)."""
    (tmp_path / "test_leak.py").write_text(
        textwrap.dedent(
            """
            def connect(db_url):
                raise RuntimeError("boom")

            def test_it():
                connect(DB)
            """
        ).replace("DB", repr(FAKE)),
        encoding="utf-8",
    )
    backend = Path(__file__).resolve().parents[2]
    (tmp_path / "conftest.py").write_text(
        f"import sys\nsys.path.insert(0, {str(backend)!r})\nfrom tests.conftest import pytest_runtest_makereport\n",
        encoding="utf-8",
    )
    env = {"SUPABASE_DB_URL": FAKE, "PATH": "", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    res = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=long", "-l", str(tmp_path)],
        capture_output=True, text=True, env=env, cwd=tmp_path,
    )  # fmt: skip
    out = res.stdout + res.stderr
    assert "1 failed" in out, out[-2000:]
    assert "S3cr" not in out, "the password leaked into the failure output"
    assert conftest.REDACTED in out


SHORT = "postgresql://postgres.invented:Zq9@db.invented.example:5432/postgres"  # an invented 3-character password


def test_the_discovery_keeps_a_short_password() -> None:
    """H-371: every non-empty password is redacted, however short; the URL comes first (longest first)."""
    assert conftest.secrets_of(SHORT) == [SHORT, "Zq9"]
    assert conftest.secrets_of("") == [] and conftest.secrets_of("postgresql://u@h/db") == ["postgresql://u@h/db"]


def test_a_short_password_alone_in_an_exception_and_in_captured_output_is_redacted(tmp_path: Path) -> None:
    """A real pytest run: the short password ALONE in the exception message and in printed (captured) output."""
    (tmp_path / "test_short.py").write_text(
        textwrap.dedent(
            """
            def test_it():
                print("captured: Zq9")
                raise RuntimeError("password was Zq9")
            """
        ),
        encoding="utf-8",
    )
    backend = Path(__file__).resolve().parents[2]
    (tmp_path / "conftest.py").write_text(
        f"import sys\nsys.path.insert(0, {str(backend)!r})\nfrom tests.conftest import pytest_runtest_makereport\n",
        encoding="utf-8",
    )
    env = {"SUPABASE_DB_URL": SHORT, "PATH": "", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    res = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=long", "-rA", str(tmp_path)],
        capture_output=True, text=True, env=env, cwd=tmp_path,
    )  # fmt: skip
    out = res.stdout + res.stderr
    assert "1 failed" in out and "Captured stdout call" in out, out[-2000:]
    assert "Zq9" not in out, "the short password leaked into the traceback or the captured output"
    assert out.count(conftest.REDACTED) >= 2  # the exception and the captured line

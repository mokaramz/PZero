"""The whole backend suite: no test ever reaches a live model (review 029a, decision b).

Before every test, every provider key variable is set to the EMPTY string (not deleted: ``core.config.load_dotenv``
only fills variables that are absent, so a key in ``.env`` cannot reappear mid-test) and the paid switch is forced
off, and the background-jobs catch-up at app start is switched off (``PZ_CATCHUP=0``, review 032c). A test that
exercises the gateway passes its own ``env`` mapping and a fake provider or a fake transport; the real provider also
refuses to run under pytest without an injected transport and resolver.
"""

from __future__ import annotations

import os
from collections.abc import Generator, Iterator
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import pytest

from projectzero.core.config import load_dotenv
from projectzero.core.inference.config import KEY_ENVS, PAID_ENV

REDACTED = "<redacted>"


def _secrets() -> list[str]:
    """The database password (raw, decoded and quoted forms) and the whole URL, longest first. ``Settings`` keeps the
    URL out of its repr, but a long traceback prints every frame's arguments, and many functions take ``db_url`` as a
    plain string (review 036a: a hosted failure printed it into a local log)."""
    load_dotenv()
    return secrets_of(os.environ.get("SUPABASE_DB_URL", ""))


def secrets_of(url: str) -> list[str]:
    """Every non-empty form of the URL's password, however short (H-371: a short password alone in a message must go
    too), and the whole URL; longest first, so the URL is replaced before its password."""
    if not url:
        return []
    raw = urlsplit(url).password or ""
    out = {url} | ({raw, unquote(raw), quote(unquote(raw), safe="")} if raw else set())
    return sorted((s for s in out if s), key=len, reverse=True)


SECRETS = _secrets()


def scrub(text: str) -> str:
    for s in SECRETS:
        text = text.replace(s, REDACTED)
    return text


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]) -> Generator[None, Any, None]:
    """Every report's traceback and captured sections are scrubbed of the database password before pytest prints or
    writes them anywhere (the terminal, a ``--junitxml`` file, a CI log)."""
    outcome = yield
    rep = outcome.get_result()
    if not SECRETS:
        return
    if rep.longrepr is not None:
        text = str(rep.longrepr)
        if any(s in text for s in SECRETS):
            rep.longrepr = scrub(text)
    rep.sections = [(title, scrub(content)) for title, content in rep.sections]


@pytest.fixture(autouse=True)
def _no_live_model(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in KEY_ENVS:
        monkeypatch.setenv(name, "")
    monkeypatch.setenv(PAID_ENV, "off")
    monkeypatch.setenv("PZ_SCOUT00_PAID", "off")  # the old alias, in case any old-side helper reads it
    monkeypatch.setenv("PZ_CATCHUP", "0")  # review 032c: no catch-up at app start under tests (the old e2e switch)
    yield

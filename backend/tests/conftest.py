"""The whole backend suite: no test ever reaches a live model (review 029a, decision b).

Before every test, every provider key variable is set to the EMPTY string (not deleted: ``core.config.load_dotenv``
only fills variables that are absent, so a key in ``.env`` cannot reappear mid-test) and the paid switch is forced
off, and the background-jobs catch-up at app start is switched off (``PZ_CATCHUP=0``, review 032c). A test that
exercises the gateway passes its own ``env`` mapping and a fake provider or a fake transport; the real provider also
refuses to run under pytest without an injected transport and resolver.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from projectzero.core.inference.config import KEY_ENVS, PAID_ENV


@pytest.fixture(autouse=True)
def _no_live_model(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in KEY_ENVS:
        monkeypatch.setenv(name, "")
    monkeypatch.setenv(PAID_ENV, "off")
    monkeypatch.setenv("PZ_SCOUT00_PAID", "off")  # the old alias, in case any old-side helper reads it
    monkeypatch.setenv("PZ_CATCHUP", "0")  # review 032c: no catch-up at app start under tests (the old e2e switch)
    yield

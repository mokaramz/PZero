"""The due-occurrence check of the background-jobs runner (review 032c, plan revision 3).

A scheduled run decides that a job is due BEFORE it holds the job's own lock, so that decision can be stale by the
time the lock is held (a predecessor committed meanwhile, or this runner was replaced). Every job entry point the
runner dispatches therefore takes an optional ``still_due(conn)`` check and calls it right after acquiring its OWN
lock, before fetching or writing, on the connection that holds that lock. ``None`` (every route and existing caller)
means no check. When the check answers ``False`` the entry point does nothing and raises ``AlreadyRan``; the runner
records the old ``skipped`` note ``ALREADY_RAN`` (classified ``skipped``, no effect).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import psycopg

ALREADY_RAN = "skipped — already ran"

StillDue = Callable[[psycopg.Connection[Any]], bool]


class AlreadyRan(Exception):
    """The occurrence a scheduled run planned was already run (or the run no longer owns the scheduler)."""

    def __init__(self) -> None:
        super().__init__(ALREADY_RAN)


def check(still_due: StillDue | None, conn: psycopg.Connection[Any]) -> None:
    """Raise ``AlreadyRan`` unless there is no check or the check passes on ``conn``."""
    if still_due is not None and not still_due(conn):
        raise AlreadyRan

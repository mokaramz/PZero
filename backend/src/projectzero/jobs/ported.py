"""Which background jobs the new runner can run, as System health sees it (review 032c, decisions b and c).

Pure, with no import of the runner (``health.core`` imports this module; the runner imports ``health``).

* ``PORTED``: the jobs with a NEW equivalent. The other six active jobs (``watch_checks``, ``deal_flow_scan``,
  ``triage_retry``, ``source_network``, ``triage_compression``, ``case_refresh``) stay in ``JOBS`` with their imported
  history but never run (b); their plan rows say ``NOT_PORTED`` in place of overdue.
* ``JobsRunner``: the ``health.core.Runner`` the views take. ``ported(job_id)`` drives the per-job texts (c);
  ``alive(record)`` replaces the old ``pid == os.getpid() or pid_alive(pid)``: a record marked ``running`` is still
  running only if the runner holding the scheduler lock NOW claimed it (its ``generation``). An imported record, or
  one claimed under an older generation, is interrupted.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

PORTED: frozenset[str] = frozenset(
    {"event_scan", "validation_snapshot", "news_refresh", "news_weekly_review", "news_source_review"}
)
NOT_PORTED = "not ported yet"


@dataclass(frozen=True)
class JobsRunner:
    ported_ids: frozenset[str] = PORTED
    generation: int | None = None  # the generation of the runner holding the scheduler lock now; None: nobody holds it

    def ported(self, job_id: str) -> bool:
        return job_id in self.ported_ids

    def alive(self, record: dict[str, Any]) -> bool:
        return self.generation is not None and record.get("generation") == self.generation

    def holding(self, generation: int | None) -> JobsRunner:
        """This runner as seen while ``generation`` holds the scheduler lock (``None``: the lock is free)."""
        return replace(self, generation=generation)

    def over(self, job_ids: Iterable[str]) -> JobsRunner:
        """A runner whose ported jobs are ``job_ids`` (the parity's and the tests' fake jobs)."""
        return replace(self, ported_ids=frozenset(job_ids))


RUNNER = JobsRunner()

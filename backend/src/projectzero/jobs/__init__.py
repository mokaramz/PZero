"""The background-jobs runner (review 032c): the old ``services/scheduler.py`` over the database.

* ``ported``: which jobs the runner can run (read by System health; no import of the runner);
* ``store``: the lease (the fencing generation), the job records, the history and the runner records (one overlay
  reader over the archived ``schedule/runner.json``), and the lock status;
* ``catalog``: the runnable jobs and their occurrence readers;
* ``writers``: the two new idempotent writers (the weekly News review, the daily Validation snapshot);
* ``runner``: ``run_due``, ``dry_run``, ``status``, ``recover_on_start``, ``start_catch_up``;
* ``__main__``: ``python -m projectzero.jobs --background | --run-due | --dry-run | --lock-status``.

This package's ``__init__`` imports nothing, so ``health.core`` can import ``jobs.ported`` without a cycle.
"""

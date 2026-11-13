/**
 * The background-job runner on System health (review 032c), decided from the payload, never from a constant:
 *
 * - **the runner is live** when `job_runner.lock` is a real lock object. While the server still sends it as
 *   `{"deferred": reason}` (032a), the page keeps the 032a snapshot: the "Background jobs are not ported yet" line,
 *   the deferred lock reason and "Run overdue now" disabled with its reason;
 * - **a job is ported** unless its row carries `"ported": false` (the six jobs whose own ports are still to come), or
 *   the same mark spelled `"availability": "not ported yet"`. An
 *   unported job never runs: its row says "not ported yet" in place of an overdue or next-run time, it keeps its
 *   imported history and timestamps, and "Run overdue now" never sends it;
 * - **"Run overdue now"** sends `only`: the ids of the ported jobs that are overdue, in the server's order.
 */
import { isDeferred } from "./deferred";
import type { Health, Job } from "./types";

/** Does the server run the 032c runner? (its lock is real, not deferred) */
export const runnerLive = (d: Health): boolean => !!d.job_runner && d.job_runner.lock != null && !isDeferred(d.job_runner.lock);

/** An unported job's label, in place of "overdue" or its next run. */
export const JOB_NOT_PORTED = "not ported yet";

/** Can the runner run this job? Only `"ported": false` (or `"availability": "not ported yet"`) says no. */
export const isPortedJob = (j: Pick<Job, "ported" | "availability">): boolean => j.ported !== false && j.availability !== JOB_NOT_PORTED;

/** The ids "Run overdue now" sends: overdue AND ported, never a job with `ported: false`. */
export const portedOverdue = (jobs: Job[]): string[] => jobs.filter((j) => j.overdue && isPortedJob(j)).map((j) => j.id);

/** The jobs the runner cannot run yet. */
export const unportedJobs = (jobs: Job[]): Job[] => jobs.filter((j) => !isPortedJob(j));

/** With the runner: where the jobs run (the old Diagnostics line, "Project Zero runs on your computer, so these catch
 *  up when the app opens (or with “projectzero --run-due”)", reworded for the new app and its new task). */
export const JOBS_LIVE =
  "Project Zero runs these jobs in its catch-up when the app opens, with Run overdue now, and in the optional Windows task “Project Zero v2 - background jobs” (registered disabled until the cutover).";

/** With the runner, next to the outcomes, when some jobs are not ported. */
export const JOBS_UNPORTED = "A job marked “not ported yet” does not run until its own port: its state and history are the imported snapshot.";

/** A job period's drawer, per job (decision c): the old texts for a ported job under the live runner, the revision 2
 *  wording otherwise (./deferred for the snapshot). */
export const JOB_TEXT = {
  retryLive: "runs again automatically when due",
  retryUnported: "This job is not ported yet: nothing runs it again.",
  downstreamLive: "Work that did not complete is kept for the next run; nothing already stored was changed. Spending caps are never overridden.",
  downstreamUnported: "Work that did not complete is not run again until this job is ported; nothing already stored was changed. Spending caps are never overridden.",
  snapshotUnported: "This job is not ported yet: its state and history are the imported snapshot.",
} as const;

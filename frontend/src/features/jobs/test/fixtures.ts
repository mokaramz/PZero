/**
 * The background-jobs runner test data (review 032c), invented names only, kept as JSON so the mocked Playwright spec
 * reads the same shapes (`e2e/tests/fixtures/jobs/`, byte-identical copies). The world is the 032a `jobs_unrun` one
 * (`features/health/test/health_jobs_unrun.json`) with the runner live:
 * - `health_runner.json`: `system_health` with the real, idle runner lock; the six jobs the runner cannot run yet carry
 *   `"ported": false` and the note "not ported yet" (some still flagged overdue in their imported record, so a test can
 *   show they are never sent); four ported jobs are overdue (event_scan, validation_snapshot, news_refresh,
 *   news_weekly_review); the issue texts of the ported jobs are the old ones, the unported jobs' keep their revision 2
 *   wording; the runners are the overlay (a new `app` record, the imported `background` and `cli` ones);
 * - `catchup_idle.json`, `catchup_running.json` (the second of four jobs running, one done, the lock held by `app`),
 *   `catchup_done.json` (all four done) and `catchup_disabled.json` (`enabled: false`, idle): `GET catchup`.
 */
import type { Health } from "@/features/health/model/types";
import type { CatchUp } from "../api";
import disabledJson from "./catchup_disabled.json";
import doneJson from "./catchup_done.json";
import idleJson from "./catchup_idle.json";
import runningJson from "./catchup_running.json";
import runnerJson from "./health_runner.json";

export const healthRunner = (): Health => structuredClone(runnerJson) as unknown as Health;
export const catchupIdle = (): CatchUp => structuredClone(idleJson) as unknown as CatchUp;
export const catchupRunning = (): CatchUp => structuredClone(runningJson) as unknown as CatchUp;
export const catchupDone = (): CatchUp => structuredClone(doneJson) as unknown as CatchUp;
export const catchupDisabled = (): CatchUp => structuredClone(disabledJson) as unknown as CatchUp;

/** The six jobs the runner cannot run yet (032c decision b). */
export const UNPORTED = ["watch_checks", "deal_flow_scan", "triage_retry", "source_network", "triage_compression", "case_refresh"];
/** The ported overdue jobs, in the server's order: what "Run overdue now" must send. */
export const PORTED_OVERDUE = ["event_scan", "validation_snapshot", "news_refresh", "news_weekly_review"];

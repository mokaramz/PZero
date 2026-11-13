/**
 * The System health test data (invented names only), kept as JSON so the mocked Playwright spec reads the same shapes
 * (`e2e/tests/fixtures/health/`, byte-identical copies). The shapes and key order are the old answers
 * (`services/health.py::system`, `services/health_overview.py::overview`), without the retired Scout keys (decision
 * c), with the deferred keys as `{"deferred": reason}` (d) and the reworded job guidance while no runner exists (k):
 * - `health_jobs_unrun.json`: the `jobs_unrun` world — imported jobs that are overdue, failing twice in a row,
 *   interrupted (an imported `running`), budget-blocked, partial and waiting-external, plus a failing source on the
 *   Project Zero side: "Action required" with "1 item needs you" (only the source counts); an external source, the
 *   triage pending, paid AI off, validation warnings; coverage, news and the job runner's imported runners;
 * - `health_jobs_only.json`: the same jobs and no actionable problem — "Status unknown" with the runner sentence;
 * - `health_empty.json`: an empty snapshot — no source, every job never run, no job report (no timestamp);
 * - `overview.json`: 30 days of imported runs (every state, a skipped run), two models with errors, spend on three days,
 *   the pipeline counts; `backups`, `integrity` and `releases` deferred;
 * - `overview_empty.json`: no run, no model call, empty pipeline counts.
 */
import type { Health, Overview } from "../model/types";
import emptyJson from "./health_empty.json";
import jobsOnlyJson from "./health_jobs_only.json";
import unrunJson from "./health_jobs_unrun.json";
import overviewJson from "./overview.json";
import overviewEmptyJson from "./overview_empty.json";

export const health = (): Health => structuredClone(unrunJson) as unknown as Health;
export const jobsOnly = (): Health => structuredClone(jobsOnlyJson) as unknown as Health;
export const emptyHealth = (): Health => structuredClone(emptyJson) as unknown as Health;
export const overview = (): Overview => structuredClone(overviewJson) as unknown as Overview;
export const emptyOverview = (): Overview => structuredClone(overviewEmptyJson) as unknown as Overview;

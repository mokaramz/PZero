/**
 * The Today test data (invented names only), kept as JSON so the mocked Playwright spec reads the same shapes
 * (`e2e/tests/fixtures/today/`). The shapes, key order and texts are the old answers (`services/today.py::view`), minus
 * the dropped Scout sections (decision c), plus the snapshot note at the end:
 * - `today.json`: a full day, ranked — CONTACT_FOUNDER, the pipeline ASK_OMAR_CONFLICT (high), a founder-call follow-up
 *   (overdue), a fresh CASE_READY, REVIEW_VERIFICATION (the `Verify X (missing)` variant, decision e), an event in 2
 *   days and TRIAGE_REVIEW with judgments, calibration samples and the budget overflow; 3 more not shown; every
 *   exceptions row the backend sends today; the compression summary; the snapshot note with both timestamps;
 * - `today_variants.json`: the other branches — the research-queue founder call after the contact step ("Contact the
 *   founders: X"), WATCH_TRIGGER high (to a candidate) and low (to the Watchlist), CASE_READY waiting ("Next: …") and
 *   weak, the triage ASK_OMAR_CONFLICT (one candidate: the old "… for Omars" exception text, decision h), an event in 11
 *   days with no city; `triage: null`; a section that failed ("temporarily unavailable"); no snapshot note;
 * - `today_empty.json`: nothing needs you, after the last prepared case expired (2026-11-16): the note with the newest
 *   case's time and no triage run;
 * - `pipeline.json`: the Conviction read the page joins (company facts, the four tiles), with one dropped company.
 */
import type { Pipeline } from "@/features/conviction/model/types";
import type { TodayView } from "../model/types";
import emptyJson from "./today_empty.json";
import fullJson from "./today.json";
import pipelineJson from "./pipeline.json";
import variantsJson from "./today_variants.json";

export const today = (): TodayView => structuredClone(fullJson) as unknown as TodayView;
export const variants = (): TodayView => structuredClone(variantsJson) as unknown as TodayView;
export const emptyDay = (): TodayView => structuredClone(emptyJson) as unknown as TodayView;
export const pipeline = (): Pipeline => structuredClone(pipelineJson) as unknown as Pipeline;

/** The day's actions as the server sent them, by type (the first of each). */
export const actionOf = (d: TodayView, type: string) => d.actions.find((a) => a.type === type)!;

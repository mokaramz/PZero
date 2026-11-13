/**
 * The Investment Desk test data (invented names only), kept as JSON so the mocked Playwright spec reads the same shapes
 * (`e2e/tests/fixtures/desk/`, byte-identical copies). The shapes and key order are the old answers:
 * - `home.json`: the old `/api/home` body — a verified best opportunity (its next move names the Manager by name, so
 *   the role wording shows), a weekend event with a deadline and a link, two due follow-ups (one without a date), the
 *   Manager list (one with feedback), the progress counts;
 * - `home_variants.json`: a provisional best opportunity without a next move, and an event without a date, city,
 *   reason, deadline or link;
 * - `home_quiet.json`: no best opportunity, no event, nothing due, nothing sent;
 * - `inbox.json`: Deal Flow's inbox — new candidates of every tier, one gated by the attention queue, one without a
 *   final score (the `att` fallback), one without `attention_v2`, a kept and a rejected one, the last scan's summary and
 *   theme labels;
 * - `pipeline.json`: Conviction's pipeline (Today's, plus the desk's cases): a possible conflict with a twin, one
 *   CONFLICT GATED by its operator state, two more possible conflicts, two founders holding the ball, and a dropped
 *   company that is both (never counted);
 * - `today.json`: Today's own `today.json`, unchanged;
 * - `sources.json`: one healthy source, two failing, one never scanned (`last_ok: null`, not a warning) and one off.
 */
import type { HomePayload, Inbox, Pipeline, Sources, TodayView } from "../model/types";
import homeJson from "./home.json";
import inboxJson from "./inbox.json";
import pipelineJson from "./pipeline.json";
import quietJson from "./home_quiet.json";
import sourcesJson from "./sources.json";
import todayJson from "./today.json";
import variantsJson from "./home_variants.json";

export const home = (): HomePayload => structuredClone(homeJson) as unknown as HomePayload;
export const homeVariants = (): HomePayload => structuredClone(variantsJson) as unknown as HomePayload;
export const homeQuiet = (): HomePayload => structuredClone(quietJson) as unknown as HomePayload;
export const inbox = (): Inbox => structuredClone(inboxJson) as unknown as Inbox;
export const pipeline = (): Pipeline => structuredClone(pipelineJson) as unknown as Pipeline;
export const today = (): TodayView => structuredClone(todayJson) as unknown as TodayView;
export const sources = (): Sources => structuredClone(sourcesJson) as unknown as Sources;

/** The clock every desk test runs at: Friday 13 November 2026, 09:30 on this machine's calendar. */
export const NOW = new Date(2026, 10, 13, 9, 30);

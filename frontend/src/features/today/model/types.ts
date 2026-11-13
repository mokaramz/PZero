/**
 * The Today payload as the rewrite serves it (review 030a): the old `GET /api/today` body (`TodayPayload`, kept in
 * ../missions with the old types, line for line, for the Investment Desk) plus, at its end, the snapshot note the
 * backend adds for the Machine details (decision f): `snapshot: {note, triage_at, cases_prepared_at}`. Without the key
 * (or with an empty note) nothing shows.
 *
 * Changed on purpose (decisions c, d): `considered` has no `native` / `scout00` keys (both sections are dropped), and the
 * exceptions never carry a `jobs` row.
 */
import type { TodayPayload } from "../missions";

/** "Triage routes and prepared cases are the imported snapshot until their runs are ported", with the original run
 *  timestamps: the routes' `triage.at` and the newest prepared case's `prepared_at` (either may be null). */
export type SnapshotNote = { note: string; triage_at: string | null; cases_prepared_at: string | null };

export type TodayView = TodayPayload & { snapshot?: SnapshotNote | null };

/** The Missions filter (local state, as before). */
export type Only = "all" | "company" | "signal";

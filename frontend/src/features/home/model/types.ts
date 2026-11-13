/**
 * The payloads the Investment Desk reads (review 031a). `GET home` is the old `/api/home` body, key for key and in the
 * old order; the other four reads are the NEW views' own payloads, under their new paths (../api):
 * - `deal-flow/inbox` (the old `inbox`): Deal Flow's `InboxPayload`, the old shape;
 * - `conviction/pipeline` (the old `pipeline`): Conviction's `Pipeline`;
 * - `today`: Today's `TodayView` (the old `TodayPayload` plus the snapshot note, which the desk does not read);
 * - `sources`: the Sources `SourcesPayload`.
 * The old `review_queue` read is deferred until the analysis port (decision d): the desk reads no rows.
 */
export type { Candidate, InboxPayload as Inbox } from "@/features/deal-flow/model/types";
export type { Pipeline, Signal } from "@/features/conviction/model/types";
export type { SourcesPayload as Sources } from "@/features/sources/model/types";
export type { TodayView } from "@/features/today/model/types";

export type HomePayload = {
  priority: { slug: string; company: string; score: number; verified: boolean; verdict: string; next: string; timing: string; op?: { status: string; action: string } } | null;
  best_event: {
    name: string;
    start: string;
    city: string;
    rank: number | string;
    weekend?: boolean;
    reason?: string;
    url?: string;
    deadline?: string;
    event_score?: number | null;
  } | null;
  due: Array<{ id: string; name: string; action: string; date: string }>;
  new_signals: number;
  latest_signals: Array<{ name: string; source: string }>;
  /** `feedback` is `bool(omar_feedback)` on the server (the old type said string; the page only tests it). */
  omar: Array<{ company: string; sent: string; feedback?: boolean | string }>;
  progress: { found?: number; contacted?: number; sent_omar?: number; people_added?: number; events_planned?: number; verified?: number };
  watch: unknown[];
  weekday: string;
  date: string;
};

/** One row of the old `/api/review_queue` (deferred, decision d: the desk passes none). */
export type ReviewRow = {
  id: string;
  name: string;
  decision?: string;
  proposed?: number | null;
  recommendation?: string;
  thesis?: string;
  created?: string;
  level?: string;
};

/** A Priority missions row. */
export type Row = {
  key: string;
  name: string;
  reason: string;
  unknown?: string;
  state: string;
  tone: "neutral" | "attention" | "risk" | "progress";
  action: string;
  to: string;
};

/** A Recent activity item: `t` is the stored date (or date and time) it is ordered and labelled by. */
export type Ev = { t: string; title: string; sub: string; to: string; key: string };

/**
 * A fake WATCH backend (review 037a) for the Watchlist and Deal Flow page tests: it answers `GET /api/watch` from an
 * invented world and applies `POST /api/watch_target` / `POST /api/watch_ack` with the old rules (first 6 URLs, the old
 * URL regex, "no such trigger", the last status wins), so the refetch shows what a write did. `POST /api/watch_check`
 * (review 037b) records an "unchanged" check on each of the named company's pages and answers
 * `{fired: 0, pages: [one "unchanged" entry per page], failures: 0, skipped: 0}`, unless a test's `check` answers (and changes the world) itself.
 */
import type { WatchAckBody, WatchCheckBody, WatchPayload, WatchTargetBody } from "../model/types";
import inboxJson from "./inbox.json";
import watchJson from "./watch.json";

export type Answer = { status: number; body: unknown };

export type WatchRoutes = {
  /** replaces the world the server starts from */
  payload?: WatchPayload;
  target?: (body: WatchTargetBody) => Answer | undefined;
  ack?: (body: WatchAckBody) => Answer | undefined;
  /** Check now: may change `db` (a new trigger, a failed check) so the refetch shows it */
  check?: (body: WatchCheckBody, db: WatchPayload) => Answer | undefined;
};

/** A fresh copy of the invented world: Halvard Optics (2 open, pages, every trigger kind), Brisa Hydrogen (manual, no
 *  pages) and Quellbrook Labs (no pages, one reviewed trigger). */
export const watchWorld = (): WatchPayload => structuredClone(watchJson) as WatchPayload;
/** The Deal Flow inbox those companies come from (two WATCH candidates and one new one). */
export const watchInbox = () => structuredClone(inboxJson);

export const ACK_AT = "2026-11-13T10:00:00";
export const CHECK_AT = "2026-11-13T10:05:00";
const PUBLIC_URL = /^https?:\/\/[^\s/]+\.[^\s]+/;

function saveTarget(db: WatchPayload, body: WatchTargetBody): Answer {
  const name = String(body.name ?? "").trim();
  if (!name) return { status: 400, body: { ok: false, error: "company name required" } };
  const urls = (body.urls ?? []).map((u) => String(u).trim()).filter(Boolean).slice(0, 6);
  const bad = urls.find((u) => !PUBLIC_URL.test(u));
  if (bad) return { status: 400, body: { ok: false, error: `not a public http(s) URL: ${bad}` } };
  const key = name.toLowerCase();
  let c = db.companies.find((x) => x.key === key);
  if (!c) {
    c = { key, name, candidate_id: body.candidate_id ?? "", urls: [], checks: {}, triggers: [], open: 0, triage_predates_evidence: false, machine_proposal: null };
    db.companies.push(c);
  }
  c.urls = urls;
  return { status: 200, body: { ok: true, target: { name, urls, candidate_id: body.candidate_id ?? "", active: true, added_at: ACK_AT, updated_at: ACK_AT, checks: c.checks } } };
}

function acknowledge(db: WatchPayload, body: WatchAckBody): Answer {
  if (body.status !== "reviewed" && body.status !== "dismissed") return { status: 400, body: { ok: false, error: "status must be reviewed or dismissed" } };
  const c = db.companies.find((x) => x.triggers.some((t) => t.id === body.id));
  const t = c?.triggers.find((x) => x.id === body.id);
  if (!c || !t) return { status: 400, body: { ok: false, error: "no such trigger" } };
  t.status = body.status;
  t.status_at = ACK_AT;
  c.open = c.triggers.filter((x) => x.status === "new").length;
  db.companies.sort((x, y) => y.open - x.open || x.name.toLowerCase().localeCompare(y.name.toLowerCase()));
  return { status: 200, body: { ok: true, kind: "status", trigger_id: body.id, status: body.status, at: ACK_AT, note: "" } };
}

function checkNow(db: WatchPayload, body: WatchCheckBody): Answer {
  const c = db.companies.find((x) => x.name === body.name);
  const urls = c ? c.urls : [];
  for (const u of urls) c!.checks[u] = { last_checked: CHECK_AT, last_state: "unchanged", last_ok: CHECK_AT, failures_in_row: 0, last_error: "" };
  const pages = urls.map((url) => ({ entity: c!.name, url, state: "unchanged", fired: [], new_lines: 0, error: "" }));
  return { status: 200, body: { fired: 0, pages, failures: 0, skipped: 0 } };
}

/** The WATCH routes over one world; `handle` answers a request or returns undefined when it is not a WATCH route. */
export function fakeWatch(routes: WatchRoutes = {}) {
  const db = routes.payload ? structuredClone(routes.payload) : watchWorld();
  const handle = (method: string, path: string, body: unknown): Answer | undefined => {
    if (method === "GET" && path === "/api/watch") return { status: 200, body: structuredClone(db) };
    if (method === "POST" && path === "/api/watch_target") return routes.target?.(body as WatchTargetBody) ?? saveTarget(db, body as WatchTargetBody);
    if (method === "POST" && path === "/api/watch_ack") return routes.ack?.(body as WatchAckBody) ?? acknowledge(db, body as WatchAckBody);
    if (method === "POST" && path === "/api/watch_check") return routes.check?.(body as WatchCheckBody, db) ?? checkNow(db, body as WatchCheckBody);
    return undefined;
  };
  return { db, handle };
}

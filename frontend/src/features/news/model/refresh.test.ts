/** The old `features/news/refresh.test.ts`, ported as it was (the refresh wording and the plain-English causes). */
import { describe, expect, it } from "vitest";

import { friendlyError, plainSourceProblem } from "@/lib/activity";
import { refreshStatus } from "../test/fixtures";
import { lastOkText, plainFailure, progressText, refreshSummary, showsLastOk, STAGE } from "./refresh";
import type { NewsRun } from "./types";

const base: NewsRun = {
  at: "2026-10-12T17:40:00",
  completed_at: "2026-10-12T17:40:14",
  status: "ok",
  feeds_checked: 10,
  sources_ok: 10,
  sources_failed: [],
  items: 200,
  new: 0,
  merged: 0,
  duplicates_skipped: 200,
  events_total: 165,
  duration_s: 14,
};

describe("news refresh outcome wording (failed ≠ nothing new ≠ new stories)", () => {
  it("B: success with zero new stories still reads as success", () => {
    const s = refreshSummary(base);
    expect(s.tone).toBe("ok");
    expect(s.title).toBe("Refresh complete — no new stories");
    expect(s.detail).toContain("10 sources checked · 200 articles fetched");
    expect(s.detail).toContain("200 already known · 165 stories stored");
  });
  it("C: new stories are counted", () => {
    const s = refreshSummary({ ...base, new: 4, material_new: 3, merged: 2, duplicates_skipped: 194 });
    expect(s.title).toBe("Refresh complete");
    expect(s.detail).toContain("4 new stories (3 material) · 2 new article(s) on existing stories");
  });
  it("A: failed and partial never look like success", () => {
    expect(refreshSummary({ ...base, status: "failed", sources_ok: 0, sources_failed: Array(10).fill("x: y") }).title).toBe("News refresh failed");
    const p = refreshSummary({ ...base, status: "partial", sources_ok: 9, sources_failed: ["deutsche-startups.de: HTTPError: HTTP Error 429: Too Many Requests"] });
    expect(p.tone).toBe("warn");
    expect(p.title).toBe("Refresh partly done — no new stories");
    expect(p.detail).toContain("(1 failed)");
  });
  it("old run records (before the fix) render without placeholders", () => {
    const s = refreshSummary({ at: "2026-10-12T17:06:16", sources_ok: 10, sources_failed: [], items: 215, new: 0, merged: 1, duplicates_skipped: 214 });
    expect(s.detail).not.toContain("?");
  });
  it("stale feeds are named", () => {
    expect(refreshSummary({ ...base, stale_feeds: ["Silicon Canals"] }).detail).toContain("not publishing lately: Silicon Canals");
  });
  it("an interrupted run says so, with its note", () => {
    expect(refreshSummary({ ...base, status: "interrupted", note: "the app stopped" })).toEqual({
      tone: "fail",
      title: "Last refresh was interrupted",
      detail: "the app stopped (2026-10-12 17:40)",
    });
  });
  it("the fixture's partial run: every part of the sentence", () => {
    expect(refreshSummary(refreshStatus("partial").last!)).toEqual({
      tone: "warn",
      title: "Refresh partly done",
      detail:
        "6 sources checked (1 failed) · 184 articles fetched · 3 new stories (2 material) · 2 new article(s) on existing stories · 179 already known · 8 stories stored · 2026-11-12 07:00 · 38 s · stories from the working sources are saved; the failed source(s) are tried again at the next refresh — nothing to do",
    });
  });
});

describe("the status line around the summary", () => {
  it("names the stage and the feed progress only while fetching", () => {
    expect(progressText({ running: true, stage: "fetching", feeds_done: 4, feeds_total: 10, elapsed_s: 3 })).toBe("checking sources (4/10) · 3 s");
    expect(progressText({ running: true, stage: "cards", feeds_done: 10, feeds_total: 10 })).toBe(STAGE.cards);
    expect(progressText({ running: true, stage: "something new" })).toBe("something new");
  });
  it("shows the last successful refresh after a failed or interrupted attempt only", () => {
    expect(showsLastOk(refreshStatus("failed").last)).toBe(true);
    expect(showsLastOk({ ...base, status: "interrupted" })).toBe(true);
    expect(showsLastOk(refreshStatus("partial").last)).toBe(false);
    expect(showsLastOk({ ...base, status: undefined })).toBe(false);
    expect(showsLastOk(null)).toBe(false);
    expect(lastOkText(refreshStatus("failed"))).toBe("Last successful refresh: 2026-11-12 07:00.");
    expect(lastOkText({ ...refreshStatus("failed"), last_ok: null })).toBe("Last successful refresh: none yet.");
  });
  it("the job is idle in every 028a status", () => {
    for (const c of ["partial", "failed", "never"] as const) expect(refreshStatus(c).job.running).toBe(false);
  });
});

describe("plain-English failures", () => {
  it.each([
    ["deutsche-startups.de: HTTPError: HTTP Error 429: Too Many Requests", "rate limit"],
    ["X: HTTPError: HTTP Error 403: Forbidden", "refused automated access"],
    ["X: HTTPError: HTTP Error 404: Not Found", "not found"],
    ["X: HTTPError: HTTP Error 503: Unavailable", "server had an error"],
    ["Maddyness: ParseError: junk after document element", "feed format changed"],
    ["X: URLError: <urlopen error [Errno 11001] getaddrinfo failed>", "DNS"],
  ])("%s", (line, want) => {
    expect(plainFailure(line)).toContain(want);
    expect(plainFailure(line)).not.toMatch(/HTTPError|Errno/);
  });
  it("friendlyError never leads with a status code", () => {
    expect(friendlyError("HTTP 429", 429)).toContain("rate-limited");
    expect(friendlyError("Failed to fetch")).toContain("did not answer");
  });
});

describe("provider payloads never reach the UI raw", () => {
  it("DeepInfra 429 engine_overloaded JSON becomes a plain sentence", () => {
    const raw = 'rate_limited: HTTP 429: {"error":{"message":"Model busy, retry later","type":"invalid_request_error","param":null,"code":"engine_overloaded"}}';
    const t = friendlyError(raw);
    expect(t).toContain("temporarily overloaded");
    expect(t).not.toMatch(/[{}]|invalid_request_error|engine_overloaded/);
  });
  it("exception names and tracebacks are stripped", () => {
    expect(friendlyError("RuntimeError: provider exploded")).toBe("provider exploded");
    expect(friendlyError('Bad thing Traceback (most recent call last): File "x.py"')).not.toContain("Traceback");
  });
});

describe("failed sources get the RIGHT plain cause (scan banner)", () => {
  it("a parser result mentioning 'resolved' is not called a DNS problem", () => {
    expect(plainSourceProblem("ValueError: CORDIS items fetched but no commercial participants resolved (page for")).toContain("no usable companies");
  });
  it("an external site change says so", () => {
    expect(plainSourceProblem("ValueError: CORDIS no longer offers its search RSS feed (the site became a web app) — external change")).toContain("site changed (external)");
  });
  it("real DNS and 403 stay correct", () => {
    expect(plainSourceProblem("URLError: <urlopen error [Errno 11001] getaddrinfo failed>")).toContain("DNS");
    expect(plainSourceProblem("UnsafeURLError: refused 'https://x': DNS")).toContain("DNS");
    expect(plainSourceProblem("HTTPError: HTTP Error 403: Forbidden")).toContain("refused automated access");
  });
});

describe("external failures read as external, in plain words", () => {
  it("408, dropped connections, JS-only and empty pages", () => {
    expect(plainSourceProblem("HTTPError: HTTP Error 408: Request Timeout")).toBe("did not answer in time");
    expect(plainSourceProblem("ConnectionResetError: connection reset by peer")).toContain("dropped the connection");
    expect(plainSourceProblem("RemoteDisconnected: Remote end closed connection")).toContain("dropped the connection");
    expect(plainSourceProblem("page is script-rendered (JavaScript only)")).toContain("JavaScript");
    expect(plainSourceProblem("empty response body")).toContain("empty page");
  });
});

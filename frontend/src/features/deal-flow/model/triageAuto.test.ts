/** The post-scan machine-triage texts (review 035b): the old running wording, the backend's sentence, the heading's
 *  tone, Retry now's count and toasts, and which run is new. */
import { describe, expect, it } from "vitest";

import { autoStatus, retryAnswer } from "../test/fixtures";
import { AUTO_POLL_MS, autoTriageText, autoTriageTone, finishedRun, RETRY_STARTED, retryToast, retryWaiting, runKey, TRIAGE_AUTO, TRIAGE_RETRY, WATCH_MS } from "./triageAuto";

describe("the post-scan machine-triage model", () => {
  it("the paths and the old pace: every 2 s, and a 60 s watch after a scan", () => {
    expect([TRIAGE_AUTO, TRIAGE_RETRY]).toEqual(["deal-flow/triage_auto", "deal-flow/triage_retry"]);
    expect([AUTO_POLL_MS, WATCH_MS]).toEqual([2000, 60_000]);
  });

  it("the line: the old running wording, else the backend's one sentence, else the old fallback", () => {
    expect(autoTriageText(null, false)).toBe("");
    expect(autoTriageText(autoStatus("running").last, true)).toBe("3 new or changed candidate(s) — machine triage running…");
    // a record still running while the flag is already down says running too (the old rule)
    expect(autoTriageText(autoStatus("running").last, false)).toBe("3 new or changed candidate(s) — machine triage running…");
    // the flag up over a finished record (a Retry now starting) also says running
    expect(autoTriageText(autoStatus("done").last, true)).toBe("3 new or changed candidate(s) — machine triage running…");
    expect(autoTriageText(autoStatus("done").last, false)).toBe("Machine triage complete — 3 processed (1 KEEP · 1 WATCH · 1 REJECT) · $0.0031.");
    expect(autoTriageText(autoStatus("partial").last, false)).toBe(
      "Machine triage partially complete — 1 processed (1 KEEP); 2 preserved for automatic retry because the model provider did not answer in time (next try after 22:34) · $0.0012. No data was lost; these are proposals only.",
    );
    const bare = { ...autoStatus("done").last!, summary: undefined };
    expect(autoTriageText(bare, false)).toBe("Machine triage finished.");
  });

  it("the tone: red for a manual retry, amber for items kept for a retry, none otherwise", () => {
    expect(autoTriageTone(autoStatus("done").last!)).toBeNull();
    expect(autoTriageTone(autoStatus("partial").last!)).toBe("pending");
    expect(autoTriageTone(autoStatus("failed").last!)).toBe("failed");
    expect(autoTriageTone({ ...autoStatus("partial").last!, failed: autoStatus("failed").last!.failed })).toBe("failed");
  });

  it("Retry now (N): the waiting count, never while a run is going", () => {
    expect(retryWaiting(autoStatus("partial"))).toBe(2);
    expect(retryWaiting(autoStatus("failed"))).toBe(1);
    expect(retryWaiting(autoStatus("done"))).toBe(0);
    expect(retryWaiting(autoStatus("retry_running"))).toBe(0);
    expect(retryWaiting({ ...autoStatus("done"), retry: undefined })).toBe(0);
  });

  it("Retry now's toast: the old started line, or the server's reason", () => {
    expect(retryToast(retryAnswer("started"))).toBe(RETRY_STARTED);
    expect(RETRY_STARTED).toBe("Retrying the preserved candidates — see Background activity");
    expect(retryToast(retryAnswer("nothing_waiting"))).toBe("Nothing is waiting for a retry.");
    expect(retryToast(retryAnswer("in_progress"))).toBe("A machine triage run is already in progress.");
  });

  it("a finished run and its key: none while running; the key is the run and its finish", () => {
    expect(finishedRun(undefined)).toBeNull();
    expect(finishedRun(autoStatus("none"))).toBeNull();
    expect(finishedRun(autoStatus("running"))).toBeNull();
    expect(finishedRun({ ...autoStatus("done"), running: true })).toBeNull();
    expect(runKey(finishedRun(autoStatus("done"))!)).toBe("2026-11-12 22:15|2026-11-12 22:19:05");
    expect(runKey(finishedRun(autoStatus("partial"))!)).toBe("2026-11-12 22:15|2026-11-12 22:19:30");
    expect(runKey(finishedRun(autoStatus("retry_done"))!)).toBe("retry-now 2026-11-12 22:25:10|2026-11-12 22:25:31");
  });
});

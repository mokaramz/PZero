/**
 * System health with the background-jobs runner (review 032c), on the invented `health_runner.json` (the real runner
 * lock, six jobs with `"ported": false`, four ported jobs overdue) and on the deferred fallback. What is decided from
 * the payload: the runner is live when `job_runner.lock` is a real lock; a job is ported unless it says `ported: false`.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { notStarted, RUN_INVALIDATES, RUN_STARTED } from "@/features/jobs/api";
import { healthRunner, PORTED_OVERDUE, UNPORTED } from "@/features/jobs/test/fixtures";
import { JOBS_SNAPSHOT, NOT_PORTED } from "./model/deferred";
import { isPortedJob, JOB_NOT_PORTED, JOB_TEXT, JOBS_LIVE, JOBS_UNPORTED, portedOverdue, runnerLive } from "./model/jobs";
import type { Health } from "./model/types";
import { health } from "./test/fixtures";
import { fakeServer, renderPage } from "./test/server";

/** The 032a phrases that promise a mechanism; they must stay away from every unported job. */
const FORBIDDEN = ["retries automatically", "kept for retry", "run again when due", "starts them immediately", "next background trigger", "let catch-up run it", "asleep", "runs again automatically", "kept for the next run"];

const tick = () => new Promise((r) => setTimeout(r, 20));
const pageText = () => document.body.textContent ?? "";
const runOverdue = () => screen.queryAllByRole("button", { name: "Run overdue now" });
const label = (id: string) => healthRunner().jobs.find((j) => j.id === id)!.label;

async function settled(routes: Parameters<typeof fakeServer>[0] = {}) {
  const server = fakeServer({ health: healthRunner, ...routes });
  const view = renderPage();
  await screen.findByRole("heading", { level: 1, name: "System health" });
  await waitFor(() => expect(document.querySelector("[data-node]")).not.toBeNull());
  return { server, ...view };
}

async function expand(testId: string) {
  const d = screen.getByTestId(testId) as HTMLDetailsElement;
  if (!d.open) fireEvent.click(d.querySelector("summary")!);
  await waitFor(() => expect((screen.getByTestId(testId) as HTMLDetailsElement).open).toBe(true));
  return screen.getByTestId(testId);
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the runner model", () => {
  it("live only with a real lock; the deferred lock (or none) is the 032a snapshot", () => {
    expect(runnerLive(healthRunner())).toBe(true);
    expect(runnerLive(health())).toBe(false);
    const h = healthRunner();
    delete h.job_runner;
    expect(runnerLive(h)).toBe(false);
  });

  it("Run overdue now sends the overdue jobs that are ported, in the server's order — never a ported: false job", () => {
    const h = healthRunner();
    expect(portedOverdue(h.jobs)).toEqual(PORTED_OVERDUE);
    // the fixture keeps some unported jobs flagged overdue in their imported record: still never sent
    expect(h.jobs.filter((j) => j.ported === false && j.overdue).length).toBeGreaterThan(0);
    for (const id of UNPORTED) expect(portedOverdue(h.jobs)).not.toContain(id);
    expect(h.jobs.filter((j) => j.ported === false).map((j) => j.id).sort()).toEqual([...UNPORTED].sort());
  });

  it('the same mark spelled `availability: "not ported yet"` is unported too', () => {
    const h = healthRunner();
    for (const j of h.jobs)
      if (j.ported === false) {
        delete j.ported;
        delete j.note;
        j.availability = "not ported yet";
      }
    expect(h.jobs.filter((j) => !isPortedJob(j)).map((j) => j.id).sort()).toEqual([...UNPORTED].sort());
    expect(portedOverdue(h.jobs)).toEqual(PORTED_OVERDUE);
    expect(isPortedJob({ availability: "available" })).toBe(true);
    expect(isPortedJob({})).toBe(true);
  });
});

describe("Run overdue now — the live runner", () => {
  it("enabled in both places; posts catchup_run with only the ported overdue ids; the old toast and invalidations", async () => {
    const { server, qc } = await settled();
    const invalidate = vi.spyOn(qc, "invalidateQueries");
    const [inPanel, inGroup] = runOverdue();
    expect(runOverdue()).toHaveLength(2);
    expect(screen.getByTestId("health-job-history")).toContainElement(inPanel);
    expect(screen.getByTestId("issues-auto")).toContainElement(inGroup);
    for (const b of [inPanel, inGroup]) {
      expect(b).not.toHaveAttribute("aria-disabled");
      expect(b).not.toHaveAttribute("data-deferred");
      expect(b).toBeEnabled();
    }
    expect(screen.queryByTestId("health-run-overdue-note")).toBeNull();
    expect(pageText()).not.toContain(NOT_PORTED.runner);
    const gets = server.gets().length;
    fireEvent.click(inPanel);
    await screen.findByText(RUN_STARTED);
    expect(server.writes()).toEqual([{ method: "POST", path: "/api/catchup_run", body: { only: PORTED_OVERDUE } }]);
    for (const k of RUN_INVALIDATES) expect(invalidate).toHaveBeenCalledWith({ queryKey: [k] });
    expect(RUN_INVALIDATES).toEqual(["catchup", "system_health", "system_health_overview"]);
    await waitFor(() => expect(server.gets().length).toBeGreaterThanOrEqual(gets + 2)); // system_health and the overview again
    expect(screen.queryByTestId("health-run-overdue-result")).toBeNull();
  });

  it("the second place posts the same body", async () => {
    const { server } = await settled();
    fireEvent.click(runOverdue()[1]);
    await screen.findByText(RUN_STARTED);
    expect(server.writes().map((w) => w.body)).toEqual([{ only: PORTED_OVERDUE }]);
  });

  it("{started: false}: the reason is shown next to both buttons and in the toast; no success toast", async () => {
    const { server } = await settled({ run: () => ({ started: false, reason: "already running" }) });
    fireEvent.click(runOverdue()[0]);
    const why = notStarted("already running");
    expect(why).toBe("Not started — already running.");
    await waitFor(() => expect(screen.getAllByTestId("health-run-overdue-result")).toHaveLength(2));
    for (const n of screen.getAllByTestId("health-run-overdue-result")) expect(n).toHaveTextContent(why);
    expect(screen.getAllByText(why).length).toBeGreaterThanOrEqual(3); // both notes and the toast
    expect(screen.queryByText(RUN_STARTED)).toBeNull();
    expect(server.writes()).toHaveLength(1);
  });

  it("a later run that starts clears the reason", async () => {
    let n = 0;
    await settled({ run: () => (n++ === 0 ? { started: false, reason: "already running" } : { started: true }) });
    fireEvent.click(runOverdue()[0]);
    await waitFor(() => expect(screen.getAllByTestId("health-run-overdue-result")).toHaveLength(2));
    fireEvent.click(runOverdue()[0]);
    await screen.findByText(RUN_STARTED);
    await waitFor(() => expect(screen.queryByTestId("health-run-overdue-result")).toBeNull());
  });

  it("only unported jobs overdue: no Run overdue now (there is nothing the runner could run)", async () => {
    await settled({
      health: (): Health => {
        const h = healthRunner();
        for (const j of h.jobs) if (j.ported !== false) j.overdue = false;
        h.overdue = 2;
        return h;
      },
    });
    expect(runOverdue()).toEqual([]);
    expect(screen.getByTestId("health-job-history")).toHaveTextContent("2 job(s) overdue.");
  });

  it("the deferred fallback: with the lock still deferred, Run overdue now stays disabled with its reason and posts nothing", async () => {
    const { server } = await settled({
      health: (): Health => {
        const h = healthRunner();
        h.job_runner!.lock = { deferred: "The job runner lock is not ported yet: no runner is alive." };
        return h;
      },
    });
    const btns = runOverdue();
    expect(btns).toHaveLength(2);
    for (const b of btns) {
      expect(b).toHaveAttribute("aria-disabled", "true");
      expect(b).toHaveAccessibleDescription(NOT_PORTED.runner);
      fireEvent.click(b);
    }
    await tick();
    expect(server.writes()).toEqual([]);
    expect(screen.getByTestId("health-jobs-snapshot").textContent).toBe(JOBS_SNAPSHOT);
  });
});

describe("the unported jobs — labelled, never sent, their history kept", () => {
  it("diagnostics: each of the six says 'not ported yet' in place of overdue or its next run, and keeps its last ok and note", async () => {
    await settled();
    const jobs = await expand("health-jobs");
    const rows = within(jobs).getAllByTestId("health-job");
    expect(rows).toHaveLength(11);
    const unported = rows.filter((r) => r.getAttribute("data-ported") === "false");
    expect(unported.map((r) => r.getAttribute("data-job-id")).sort()).toEqual([...UNPORTED].sort());
    for (const r of unported) {
      expect(within(r).getByTestId("health-job-not-ported")).toHaveTextContent(new RegExp(`^${JOB_NOT_PORTED}$`));
      expect(r).not.toHaveTextContent(/· overdue|· next /);
    }
    const watch = unported.find((r) => r.getAttribute("data-job-id") === "watch_checks")!;
    expect(watch).toHaveTextContent("WATCH checks every 24 h · last ok 2026-11-09T07:00:00 · not ported yet");
    expect(watch).toHaveTextContent("3 pages checked");
    const tc = unported.find((r) => r.getAttribute("data-job-id") === "triage_compression")!;
    expect(tc).toHaveTextContent("interrupted"); // the imported state stays
    const ported = rows.filter((r) => r.getAttribute("data-ported") !== "false");
    expect(ported.filter((r) => within(r).queryByText("overdue")).map((r) => r.getAttribute("data-job-id"))).toEqual(PORTED_OVERDUE);
    expect(ported.find((r) => r.getAttribute("data-job-id") === "news_source_review")).toHaveTextContent("next 2026-11-19T08:00:00");
  });

  it("the job matrix: an unported row says 'not ported yet' and keeps its imported runs", async () => {
    await settled();
    const mx = screen.getByTestId("job-matrix");
    for (const id of UNPORTED) {
      const row = mx.querySelector(`[data-job="${id}"]`)!;
      expect(row.lastElementChild).toHaveTextContent(new RegExp(`^${JOB_NOT_PORTED}$`));
    }
    expect(mx.querySelectorAll('[data-job="watch_checks"] button[data-state]').length).toBeGreaterThan(0);
    expect(mx.querySelector('[data-job="event_scan"]')!.lastElementChild).toHaveTextContent(/^overdue$/);
  });

  it("the pipeline: the Deal Flow scan step says Not ported yet; its next due too", async () => {
    await settled();
    const scan = document.querySelector('[data-node="df-scan"]') as HTMLElement;
    expect(scan).toHaveTextContent("Not ported yet");
    fireEvent.click(scan);
    expect(screen.getByTestId("health-detail")).toHaveTextContent(`Next due${JOB_NOT_PORTED}`);
  });

  it("an unported job's period: the snapshot line for that job, no promised run", async () => {
    await settled();
    fireEvent.click(screen.getByTestId("job-matrix").querySelector('[data-job="case_refresh"] button[data-state="budget_blocked"]') as HTMLElement);
    const d = screen.getByTestId("health-detail");
    expect(d).toHaveTextContent(`Next run${JOB_NOT_PORTED}`);
    expect(within(d).getByTestId("health-runs-snapshot").textContent).toBe(JOB_TEXT.snapshotUnported);
    expect(d).toHaveTextContent(JOB_TEXT.downstreamUnported);
    for (const p of FORBIDDEN) expect(d.textContent, p).not.toContain(p);
  });

  it("a ported job's period has the old texts again, and no snapshot line", async () => {
    await settled();
    fireEvent.click(screen.getByTestId("job-matrix").querySelector('[data-job="event_scan"] button[data-state="failed"]') as HTMLElement);
    const d = screen.getByTestId("health-detail");
    expect(d).toHaveTextContent(`Retry${JOB_TEXT.retryLive}`);
    expect(d).toHaveTextContent(JOB_TEXT.downstreamLive);
    expect(within(d).queryByTestId("health-runs-snapshot")).toBeNull();
    expect(d).not.toHaveTextContent(NOT_PORTED.runner);
  });

  it("no forbidden phrase near an unported job: its rows, its issues, its drawer — with every section open", async () => {
    await settled();
    const names = UNPORTED.map(label);
    const items = screen.getAllByTestId("health-issue").filter((i) => names.some((n) => (i.textContent ?? "").includes(n.split(" (")[0])));
    expect(items.length).toBeGreaterThanOrEqual(2); // the interrupted compression, the budget-blocked case refresh
    for (const i of items) for (const p of FORBIDDEN) expect(i.textContent, p).not.toContain(p);
    const jobs = await expand("health-jobs");
    for (const r of within(jobs).getAllByTestId("health-job").filter((x) => x.getAttribute("data-ported") === "false"))
      for (const p of FORBIDDEN) expect(r.textContent, p).not.toContain(p);
    // and the ported jobs' old texts are back, from the server
    expect(within(screen.getByTestId("issues-auto")).getAllByTestId("health-issue")[0]).toHaveTextContent("“Run overdue now” starts them immediately.");
  });
});

describe("the job panels with the live runner", () => {
  it("no 'Background jobs are not ported yet' line; where the jobs run, and the unported label, instead", async () => {
    await settled();
    expect(screen.queryByTestId("health-jobs-snapshot")).toBeNull();
    expect(screen.getByTestId("health-jobs-unported").textContent).toBe(JOBS_UNPORTED);
    const jobs = await expand("health-jobs");
    expect(within(jobs).getByTestId("health-jobs-note").textContent).toBe(JOBS_LIVE);
    expect(within(jobs).getByTestId("health-jobs-unported-note").textContent).toBe(JOBS_UNPORTED);
    expect(pageText()).not.toContain(JOBS_SNAPSHOT);
    expect(pageText()).not.toContain("Background jobs are not ported yet");
    expect(JOBS_LIVE).toContain("“Project Zero v2 - background jobs”");
  });

  it("every job ported: no unported label at all", async () => {
    await settled({
      health: (): Health => {
        const h = healthRunner();
        for (const j of h.jobs) delete j.ported;
        return h;
      },
    });
    expect(screen.queryByTestId("health-jobs-unported")).toBeNull();
    expect(pageText()).not.toContain(JOB_NOT_PORTED);
    const jobs = await expand("health-jobs");
    expect(within(jobs).queryByTestId("health-jobs-unported-note")).toBeNull();
  });

  it("the runner line renders the real lock: idle, with the overlaid runners", async () => {
    await settled();
    const jobs = await expand("health-jobs");
    const runner = within(jobs).getByTestId("health-job-runner");
    expect(runner).toHaveTextContent(
      "Job runner: idle · last background run 2026-11-09 22:05 (completed) · last app run 2026-11-13 09:00 (ok) · last manual run 2026-11-06 10:03 (partial)",
    );
    expect(runner.querySelector("[data-reason]")).toBeNull();
  });

  it("the runner line: busy, and a gone process", async () => {
    await settled({
      health: (): Health => {
        const h = healthRunner();
        h.job_runner!.lock = { held: true, source: "app", pid: 4242, since: "2026-11-13T09:30:04", alive: true, suspect: false };
        return h;
      },
    });
    const jobs = await expand("health-jobs");
    expect(within(jobs).getByTestId("health-job-runner")).toHaveTextContent("Job runner: busy — app (pid 4242) since 2026-11-13T09:30:04 · last background run");
    expect(within(jobs).getByTestId("health-job-runner")).not.toHaveTextContent("process gone");
  });

  it("the deferred fallback: the runner line shows the lock's reason, the snapshot line returns, unported rows stay labelled", async () => {
    await settled({
      health: (): Health => {
        const h = healthRunner();
        h.job_runner!.lock = { deferred: "The job runner lock is not ported yet: no runner is alive." };
        return h;
      },
    });
    const jobs = await expand("health-jobs");
    expect(within(jobs).getByTestId("health-jobs-note").textContent).toBe(JOBS_SNAPSHOT);
    expect(within(jobs).queryByTestId("health-jobs-unported-note")).toBeNull();
    expect(within(jobs).getByTestId("health-job-runner").querySelector("[data-reason]")).toHaveTextContent("The job runner lock is not ported yet: no runner is alive.");
    expect(within(jobs).getAllByTestId("health-job-not-ported")).toHaveLength(6);
  });

  it("no Scout text anywhere, with every section open", async () => {
    await settled();
    for (const id of ["health-glance", "health-sources", "health-coverage", "health-jobs", "health-ai", "health-news", "health-hardening", "health-build-d"]) {
      await expand(id);
      expect(pageText()).not.toMatch(/Scout|Grok|search bridge|repair research/i);
    }
  });
});

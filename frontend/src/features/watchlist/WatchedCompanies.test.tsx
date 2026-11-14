/**
 * The watched companies panel on the Watchlist (review 037a): the rows, the "{n} new" and "machine triage predates new
 * evidence" badges, the TriggerList (tones, evidence, source kind, dates, the source link), Reviewed / Dismiss, the
 * official pages with Save pages (split on any whitespace; a 400 keeps the text), the empty state, and "Check now"
 * (review 037b: `{name}` posted, the old toast with the failures and the skipped suffixes, the busy 409 as the error
 * toast, the trigger-log readers invalidated). Invented names only (`test/watch.json`).
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fakeServer, renderWatchlist } from "@/features/network/test/server";
import { ACK_KEYS, CHECK_KEYS, TARGET_KEYS } from "./api";
import type { Trigger, WatchCheckedPage } from "./model/types";
import { checkToast } from "./model/watch";
import { CHECK_AT, watchWorld } from "./test/fakeWatch";

const panel = () => screen.getByTestId("watched-companies");
const companies = () => screen.queryAllByTestId("watched-company");
const company = (name: string) => companies().find((r) => r.textContent?.includes(name))!;
const trigger = (scope: HTMLElement, text: string) => within(scope).getAllByTestId("watch-trigger").find((t) => t.textContent?.includes(text))!;
const tone = (el: HTMLElement) => el.querySelector("span")?.className.match(/tone_(\w+?)_/)?.[1];
const watchReads = (server: ReturnType<typeof fakeServer>) => server.reads("/api/watch");
const invalidated = (spy: { mock: { calls: unknown[][] } }) => spy.mock.calls.map((c) => ((c[0] as { queryKey?: unknown[] } | undefined)?.queryKey ?? [])[0]);

async function open() {
  const server = fakeServer();
  const view = renderWatchlist();
  await waitFor(() => expect(companies()).toHaveLength(3));
  return { server, ...view };
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("Watched companies — reading", () => {
  it("lists the watched companies in the view's order with their names, badges and the old texts; nothing is posted", async () => {
    const { server } = await open();
    expect(panel()).not.toHaveAttribute("data-deferred");
    expect(panel()).toHaveTextContent("Watched companies — WATCH is active, not a graveyard");
    expect(panel()).toHaveTextContent("Deterministic sensors · no model · nothing changes a decision");
    expect(panel()).toHaveTextContent(/Why am I seeing this\? Companies you put on WATCH come back automatically when reality changes\./);
    expect(within(panel()).queryByTestId("watch-checks-deferred")).toBeNull();
    expect(panel()).not.toHaveTextContent("Page checks arrive");
    expect(companies().map((c) => c.getAttribute("data-key"))).toEqual(["halvard optics", "brisa hydrogen", "quellbrook labs"]);

    const halvard = company("Halvard Optics");
    expect(within(halvard).getByRole("link", { name: "Halvard Optics" })).toHaveAttribute("href", "/deal-flow?candidate=c-wt-01");
    expect(within(halvard).getByText("2 new").className).toMatch(/tone_red/);
    const stale = within(halvard).getByText("machine triage predates new evidence");
    expect(stale.className).toMatch(/tone_amber/);
    expect(stale).toHaveAttribute("title", "The machine triage judged the company before this evidence existed");

    // a manual target has no candidate: its name is not a link; no open trigger, no badge
    const brisa = company("Brisa Hydrogen");
    expect(within(brisa).queryByRole("link", { name: "Brisa Hydrogen" })).toBeNull();
    expect(brisa).toHaveTextContent("Brisa Hydrogen");
    expect(within(brisa).queryByText(/\d+ new$/)).toBeNull();
    expect(within(brisa).queryByText("machine triage predates new evidence")).toBeNull();
    expect(brisa).toHaveTextContent("No triggers yet.");

    const quell = company("Quellbrook Labs");
    expect(within(quell).getByRole("link", { name: "Quellbrook Labs" })).toHaveAttribute("href", "/deal-flow?candidate=c-wt-03");
    expect(within(quell).queryByText(/\d+ new$/)).toBeNull();
    expect(server.calls.filter((c) => c.method === "POST")).toEqual([]);
    expect(watchReads(server)).toBe(1);
  });

  it("the trigger list: tone, the evidence's first 160 characters, the source kind, the dates, the source link, and the status", async () => {
    await open();
    const halvard = company("Halvard Optics");
    expect(within(halvard).getAllByTestId("watch-trigger").map((t) => t.getAttribute("data-status"))).toEqual(["new", "new", "dismissed", "reviewed"]);

    // an open high-value page trigger: red, cut evidence, dated, with its source and the two acknowledgements
    const evidence = watchWorld().companies[0].triggers[0].evidence;
    expect(evidence.length).toBeGreaterThan(160);
    const funding = trigger(halvard, "Funding round");
    expect(tone(funding)).toBe("red");
    expect(funding).toHaveTextContent(evidence.slice(0, 160));
    expect(funding).not.toHaveTextContent(evidence.slice(0, 161));
    expect(funding).toHaveTextContent("· page check · first seen 2026-11-12 · dated 2026-11-10");
    const src = within(funding).getByRole("link", { name: "source" });
    expect(src).toHaveAttribute("href", "https://halvard-optics.example/news");
    expect(src).toHaveAttribute("target", "_blank");
    expect(src).toHaveAttribute("rel", "noreferrer");
    expect(within(funding).getAllByRole("button").map((b) => b.textContent)).toEqual(["Reviewed", "Dismiss"]);

    // an open scan re-hit: amber, "new source in a scan", no date
    const pilot = trigger(halvard, "Pilot");
    expect(tone(pilot)).toBe("amber");
    expect(pilot).toHaveTextContent("· new source in a scan · first seen 2026-11-11");
    expect(pilot).not.toHaveTextContent("dated");

    // a dismissed news trigger: neutral, still "page check" (the old label, decision e), no source link, no buttons
    const customer = trigger(halvard, "Customer");
    expect(tone(customer)).toBe("neutral");
    expect(customer).toHaveTextContent("· page check · first seen 2026-11-03 · dated 2026-11-02");
    expect(within(customer).queryByRole("link")).toBeNull();
    expect(within(customer).queryAllByRole("button")).toHaveLength(0);
    expect(customer).toHaveTextContent(/· dismissed$/);

    const hire = trigger(halvard, "Key hire");
    expect(tone(hire)).toBe("neutral");
    expect(hire).toHaveTextContent(/· reviewed$/);
  });

  it("the official pages: their count, the textarea with one URL per line, and each page's last check", async () => {
    await open();
    const halvard = company("Halvard Optics");
    expect(within(halvard).getByText("Official pages to watch (2)").tagName).toBe("SUMMARY");
    const box = within(halvard).getByLabelText("Pages to watch for Halvard Optics");
    expect(box).toHaveValue("https://halvard-optics.example/news\nhttps://halvard-optics.example/careers");
    expect(box).toHaveAttribute("placeholder", "One public URL per line: company news page, careers page, product page…");
    expect(within(halvard).getAllByTestId("watch-page-check").map((d) => d.textContent)).toEqual([
      "https://halvard-optics.example/news: changed · 2026-11-12T08:00:00",
      "https://halvard-optics.example/careers: failed · 2026-11-12T08:00:05 · 2 failure(s) in a row: HTTP 503",
    ]);
    expect(within(company("Brisa Hydrogen")).getByText("Official pages to watch (0)")).toBeInTheDocument();
    expect(within(company("Brisa Hydrogen")).getByLabelText("Pages to watch for Brisa Hydrogen")).toHaveValue("");
    expect(within(company("Brisa Hydrogen")).queryAllByTestId("watch-page-check")).toHaveLength(0);
  });

  it("no companies on WATCH: the old empty state", async () => {
    const server = fakeServer({ watch: { payload: { ...watchWorld(), companies: [] } } });
    renderWatchlist();
    expect(await screen.findByText("No companies on WATCH. In Deal Flow, choose WATCH for a company that is not interesting yet but could become so.")).toBeInTheDocument();
    expect(companies()).toHaveLength(0);
    expect(within(panel()).queryByTestId("watch-check")).toBeNull();
    expect(server.calls.filter((c) => c.method === "POST")).toEqual([]);
  });

  it("a failed read says so in the panel, with Retry", async () => {
    fakeServer({ watch: { payload: watchWorld() } });
    const fetchMock = vi.mocked(globalThis.fetch);
    const real = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) =>
      String(input) === "/api/watch" ? new Response(JSON.stringify({ ok: false, error: "watch view unavailable" }), { status: 400 }) : real(input, init),
    );
    renderWatchlist();
    expect(await within(panel()).findByRole("alert")).toHaveTextContent("watch view unavailable");
    expect(within(panel()).getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});

describe("Watched companies — Save pages", () => {
  it("posts the pages split on any whitespace with the company's name and candidate, toasts, and reads the view again", async () => {
    const { server, qc } = await open();
    const spy = vi.spyOn(qc, "invalidateQueries");
    const brisa = company("Brisa Hydrogen");
    fireEvent.change(within(brisa).getByLabelText("Pages to watch for Brisa Hydrogen"), {
      target: { value: "  https://brisa-hydrogen.example/news \n\n https://brisa-hydrogen.example/jobs\thttps://brisa-hydrogen.example/product  " },
    });
    expect(server.watchPosts()).toEqual([]);
    fireEvent.click(within(brisa).getByRole("button", { name: "Save pages" }));
    await screen.findByText("Pages saved — first check records a baseline");
    expect(server.watchPosts().map((c) => [c.path, c.body])).toEqual([
      [
        "/api/watch_target",
        { name: "Brisa Hydrogen", urls: ["https://brisa-hydrogen.example/news", "https://brisa-hydrogen.example/jobs", "https://brisa-hydrogen.example/product"], candidate_id: "" },
      ],
    ]);
    await waitFor(() => expect(within(company("Brisa Hydrogen")).getByText("Official pages to watch (3)")).toBeInTheDocument());
    expect(watchReads(server)).toBe(2);
    expect(invalidated(spy)).toEqual(expect.arrayContaining(TARGET_KEYS));
    expect(invalidated(spy)).not.toContain("today");

    // a candidate's row sends its candidate id
    fireEvent.click(within(company("Halvard Optics")).getByRole("button", { name: "Save pages" }));
    await waitFor(() => expect(server.watchPosts("watch_target")).toHaveLength(2));
    expect(server.watchPosts("watch_target")[1].body).toEqual({
      name: "Halvard Optics",
      urls: ["https://halvard-optics.example/news", "https://halvard-optics.example/careers"],
      candidate_id: "c-wt-01",
    });
  });

  it("a refused page is the server's error in the toast; the text stays and nothing is saved", async () => {
    const { server } = await open();
    const brisa = company("Brisa Hydrogen");
    const box = within(brisa).getByLabelText("Pages to watch for Brisa Hydrogen");
    fireEvent.change(box, { target: { value: "https://brisa-hydrogen.example/news ftp://brisa-hydrogen.example/files" } });
    fireEvent.click(within(brisa).getByRole("button", { name: "Save pages" }));
    await screen.findByText("✕ Saving watched pages failed — not a public http(s) URL: ftp://brisa-hydrogen.example/files");
    expect(server.watchPosts("watch_target")).toHaveLength(1);
    expect(screen.queryByText("Pages saved — first check records a baseline")).toBeNull();
    expect(box).toHaveValue("https://brisa-hydrogen.example/news ftp://brisa-hydrogen.example/files");
    expect(within(company("Brisa Hydrogen")).getByText("Official pages to watch (0)")).toBeInTheDocument();
    expect(server.watch.companies.find((c) => c.key === "brisa hydrogen")!.urls).toEqual([]);
  });
});

describe("Watched companies — Reviewed / Dismiss", () => {
  it("Reviewed and Dismiss post {id, status}, toast, and the refetch shows the status and the open count", async () => {
    const { server, qc } = await open();
    const spy = vi.spyOn(qc, "invalidateQueries");
    fireEvent.click(within(trigger(company("Halvard Optics"), "Funding round")).getByRole("button", { name: "Reviewed" }));
    await screen.findByText("Trigger updated (kept on record)");
    expect(server.watchPosts().map((c) => [c.path, c.body])).toEqual([["/api/watch_ack", { id: "wt-a1b2c3d4e5f6", status: "reviewed" }]]);
    await waitFor(() => expect(trigger(company("Halvard Optics"), "Funding round")).toHaveTextContent(/· reviewed$/));
    expect(tone(trigger(company("Halvard Optics"), "Funding round"))).toBe("neutral");
    expect(within(company("Halvard Optics")).getByText("1 new")).toBeInTheDocument();
    expect(invalidated(spy)).toEqual(expect.arrayContaining(ACK_KEYS));
    expect(ACK_KEYS).toEqual(expect.arrayContaining(["watch", "today"]));

    fireEvent.click(within(trigger(company("Halvard Optics"), "Pilot")).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(server.watchPosts("watch_ack")).toHaveLength(2));
    expect(server.watchPosts("watch_ack")[1].body).toEqual({ id: "wt-b2c3d4e5f6a7", status: "dismissed" });
    await waitFor(() => expect(trigger(company("Halvard Optics"), "Pilot")).toHaveTextContent(/· dismissed$/));
    expect(within(company("Halvard Optics")).queryByText(/\d+ new$/)).toBeNull();
    // no open trigger left: the view's order puts it after Brisa Hydrogen (by name)
    expect(companies().map((c) => c.getAttribute("data-key"))).toEqual(["brisa hydrogen", "halvard optics", "quellbrook labs"]);
  });

  it("a refused acknowledgement is the error toast and changes nothing", async () => {
    const server = fakeServer({ watch: { ack: () => ({ status: 400, body: { ok: false, error: "no such trigger" } }) } });
    renderWatchlist();
    await waitFor(() => expect(companies()).toHaveLength(3));
    fireEvent.click(within(trigger(company("Halvard Optics"), "Funding round")).getByRole("button", { name: "Dismiss" }));
    await screen.findByText("✕ Acknowledging failed — no such trigger");
    expect(server.watchPosts("watch_ack")).toHaveLength(1);
    expect(trigger(company("Halvard Optics"), "Funding round")).toHaveAttribute("data-status", "new");
    expect(within(company("Halvard Optics")).getByText("2 new")).toBeInTheDocument();
  });
});

/** A new open trigger the check "fired" on Halvard Optics' news page (invented). */
const firedTrigger = (): Trigger => ({
  id: "wt-c9d8e7f6a5b4",
  name: "Halvard Optics",
  candidate_id: "c-wt-01",
  predicate: "customer",
  label: "Customer",
  high_value: false,
  source: "halvard-optics.example",
  source_kind: "page_check",
  url: "https://halvard-optics.example/news",
  source_date: "2026-11-13",
  first_observed: CHECK_AT,
  evidence: "Halvard Optics signs an invented regional rail operator as its first inspection-camera customer.",
  status: "new",
  status_at: "",
});

/** One checked page of the answer (a page skipped at the deadline is not listed). */
const checked = (url: string, state: WatchCheckedPage["state"], fired: Trigger[] = [], error = ""): WatchCheckedPage => ({
  entity: "Halvard Optics",
  url,
  state,
  fired,
  ...(state === "unchanged" || state === "changed" ? { new_lines: fired.length } : {}),
  error,
});

describe("Watched companies — Check now (review 037b)", () => {
  it("the toast: the old wording, the failures only when some failed, the skipped suffix only when the budget left pages", () => {
    expect(checkToast({ fired: 0, failures: 0, skipped: 0 })).toBe("0 new trigger(s)");
    expect(checkToast({ fired: 2, failures: 0, skipped: 0 })).toBe("2 new trigger(s)");
    expect(checkToast({ fired: 1, failures: 2, skipped: 0 })).toBe("1 new trigger(s) · 2 page(s) failed");
    expect(checkToast({ fired: 0, failures: 0, skipped: 3 })).toBe("0 new trigger(s) · 3 page(s) left for the next run");
    expect(checkToast({ fired: 1, failures: 1, skipped: 1 })).toBe("1 new trigger(s) · 1 page(s) failed · 1 page(s) left for the next run");
  });

  it("every row has a live Check now that posts its company's name; nothing is posted before a click", async () => {
    const { server } = await open();
    const checks = within(panel()).getAllByTestId("watch-check");
    expect(checks).toHaveLength(3);
    for (const b of checks) {
      expect(b).toHaveTextContent("Check now");
      expect(b).toBeEnabled();
      expect(b).not.toHaveAttribute("aria-disabled");
      expect(b).not.toHaveAttribute("data-deferred");
      expect(b).not.toHaveAttribute("title");
    }
    expect(server.watchPosts()).toEqual([]);

    // a company with no pages: the re-hits only, "0 new trigger(s)" (the old e2e's answer)
    fireEvent.click(within(company("Brisa Hydrogen")).getByRole("button", { name: "Check now" }));
    await screen.findByText(/^0 new trigger\(s\)$/);
    expect(server.watchPosts().map((c) => [c.path, c.body])).toEqual([["/api/watch_check", { name: "Brisa Hydrogen" }]]);
    fireEvent.click(within(company("Quellbrook Labs")).getByRole("button", { name: "Check now" }));
    await waitFor(() => expect(server.watchPosts("watch_check")).toHaveLength(2));
    expect(server.watchPosts("watch_check")[1].body).toEqual({ name: "Quellbrook Labs" });
  });

  it("fired: the toast counts the new triggers, every trigger-log reader is invalidated, and the refetch shows the trigger", async () => {
    const server = fakeServer({
      watch: {
        check: (body, db) => {
          const c = db.companies.find((x) => x.name === body.name)!;
          c.triggers.unshift(firedTrigger());
          c.open += 1;
          c.checks["https://halvard-optics.example/news"] = { last_checked: CHECK_AT, last_state: "changed", last_ok: CHECK_AT, failures_in_row: 0 };
          const pages = [checked("https://halvard-optics.example/news", "changed", [firedTrigger()]), checked("https://halvard-optics.example/careers", "unchanged")];
          return { status: 200, body: { fired: 1, pages, failures: 0, skipped: 0 } };
        },
      },
    });
    const { qc } = renderWatchlist();
    await waitFor(() => expect(companies()).toHaveLength(3));
    const spy = vi.spyOn(qc, "invalidateQueries");
    fireEvent.click(within(company("Halvard Optics")).getByRole("button", { name: "Check now" }));
    await screen.findByText(/^1 new trigger\(s\)$/);
    expect(screen.queryByText(/page\(s\) failed|left for the next run/)).toBeNull();
    expect(server.watchPosts().map((c) => [c.path, c.body])).toEqual([["/api/watch_check", { name: "Halvard Optics" }]]);
    expect(invalidated(spy)).toEqual(expect.arrayContaining(CHECK_KEYS));
    expect(CHECK_KEYS).toEqual(expect.arrayContaining(["watch", "today", "home", "system_health", "conviction/pipeline", "conviction/case", "map/intel"]));
    expect(CHECK_KEYS).toEqual(expect.arrayContaining(ACK_KEYS));
    await waitFor(() => expect(within(company("Halvard Optics")).getByText("3 new")).toBeInTheDocument());
    expect(watchReads(server)).toBe(2);
    const fresh = trigger(company("Halvard Optics"), "first inspection-camera customer");
    expect(fresh).toHaveAttribute("data-status", "new");
    expect(fresh).toHaveTextContent("· page check · first seen 2026-11-13 · dated 2026-11-13");
    expect(within(company("Halvard Optics")).getAllByTestId("watch-page-check")[0]).toHaveTextContent(`https://halvard-optics.example/news: changed · ${CHECK_AT}`);
  });

  it("failures: ' · N page(s) failed', and the refetch shows the failure streak", async () => {
    fakeServer({
      watch: {
        check: (_body, db) => {
          db.companies[0].checks["https://halvard-optics.example/careers"] = { last_checked: CHECK_AT, last_state: "failed", failures_in_row: 3, last_error: "HTTP 503" };
          const pages = [checked("https://halvard-optics.example/news", "unchanged"), checked("https://halvard-optics.example/careers", "failed", [], "HTTPError: HTTP 503")];
          return { status: 200, body: { fired: 0, pages, failures: 1, skipped: 0 } };
        },
      },
    });
    renderWatchlist();
    await waitFor(() => expect(companies()).toHaveLength(3));
    fireEvent.click(within(company("Halvard Optics")).getByRole("button", { name: "Check now" }));
    await screen.findByText(/^0 new trigger\(s\) · 1 page\(s\) failed$/);
    await waitFor(() =>
      expect(within(company("Halvard Optics")).getAllByTestId("watch-page-check")[1]).toHaveTextContent(
        `https://halvard-optics.example/careers: failed · ${CHECK_AT} · 3 failure(s) in a row: HTTP 503`,
      ),
    );
  });

  it("skipped: the budget's pages left for the next run are the toast's last part", async () => {
    // a re-hit fired, the news page failed, and the careers page was left at the deadline (not listed)
    fakeServer({ watch: { check: () => ({ status: 200, body: { fired: 1, pages: [checked("https://halvard-optics.example/news", "failed", [], "TimeoutError: timed out")], failures: 1, skipped: 1 } }) } });
    renderWatchlist();
    await waitFor(() => expect(companies()).toHaveLength(3));
    fireEvent.click(within(company("Halvard Optics")).getByRole("button", { name: "Check now" }));
    await screen.findByText(/^1 new trigger\(s\) · 1 page\(s\) failed · 1 page\(s\) left for the next run$/);
  });

  it("busy: the 409 'A WATCH check is already running.' is the error toast; nothing is read again and the button is usable", async () => {
    const server = fakeServer({ watch: { check: () => ({ status: 409, body: { ok: false, error: "A WATCH check is already running." } }) } });
    const { qc } = renderWatchlist();
    await waitFor(() => expect(companies()).toHaveLength(3));
    const spy = vi.spyOn(qc, "invalidateQueries");
    const btn = within(company("Halvard Optics")).getByRole("button", { name: "Check now" });
    fireEvent.click(btn);
    await screen.findByText("✕ Checking watched pages failed — A WATCH check is already running.");
    expect(server.watchPosts("watch_check")).toHaveLength(1);
    expect(screen.queryByText(/new trigger\(s\)/)).toBeNull();
    expect(invalidated(spy)).not.toContain("watch");
    expect(watchReads(server)).toBe(1);
    await waitFor(() => expect(btn).toBeEnabled());
    expect(within(company("Halvard Optics")).getByText("2 new")).toBeInTheDocument();
  });
});

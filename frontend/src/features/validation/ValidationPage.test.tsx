import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ALL_ITEMS } from "@/app/nav";
import { NOT_PORTED } from "./model/deferred";
import type { NativeBridgeMetrics } from "./model/types";
import { emptyValidation, packet, validation } from "./test/fixtures";
import { fakeServer, renderPage } from "./test/server";

const WRITES = NOT_PORTED.writes;
const questions = () => screen.getByTestId("val-questions");
const tab = (name: string) => within(questions()).getByRole("tab", { name });
const ask = (name: string) => fireEvent.click(tab(name));

async function opened() {
  const r = renderPage();
  await screen.findByTestId("val-edge");
  return r;
}

/** A deferred control stays inert for a pointer AND a keyboard (a browser turns Enter / Space into a click). */
function pressEveryWay(el: Element) {
  fireEvent.click(el);
  for (const key of ["Enter", " "]) {
    fireEvent.keyDown(el, { key });
    fireEvent.keyUp(el, { key });
    fireEvent.click(el, { detail: 0 });
  }
}

/** Visible, named, focusable, disabled with the 027b reason (title + accessible description). */
function expectDeferred(el: HTMLElement) {
  expect(el).toBeVisible();
  expect(el).toHaveAttribute("aria-disabled", "true");
  expect(el).toHaveAttribute("title", WRITES);
  expect(el).toHaveAccessibleDescription(WRITES);
  expect(el).not.toBeDisabled();
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Validation — the page", () => {
  it("is a ported nav view at /validation", () => {
    expect(ALL_ITEMS.find((i) => i.legacyView === "validation")).toMatchObject({ path: "/validation", label: "Validation", page: expect.anything() });
  });

  it("opens on 'Are we early?' after ONE read, with the old header, note, tabs and footer", async () => {
    const server = fakeServer();
    await opened();
    expect(server.gets()).toEqual(["/api/validation"]);
    expect(screen.getByRole("heading", { level: 1, name: "Validation & Learning" })).toBeInTheDocument();
    expect(screen.getByText(/^Is Project Zero making you better/)).toHaveTextContent(
      "Is Project Zero making you better at finding exceptional companies early — or only giving you more information?",
    );
    expect(screen.getByText(/^Read-only evidence about Project Zero itself/)).toHaveTextContent(
      "Read-only evidence about Project Zero itself. Outcomes count only from real-world events, your decisions, Manager and the deterministic gates — machine proposals never validate themselves. Rates appear once a group has 5+ cases; before that you see counts and “collecting”. UNKNOWN means “no outcome yet”, not failure.",
    );
    expect(within(questions()).getByRole("tablist", { name: "Question" })).toBeInTheDocument();
    expect(within(questions()).getAllByRole("tab").map((t) => t.textContent)).toEqual([
      "Are we early?",
      "Are we right?",
      "Which sources work?",
      "Where do we miss?",
      "What does it cost?",
    ]);
    expect(tab("Are we early?")).toHaveAttribute("aria-selected", "true");
    expect(within(questions()).getAllByRole("tabpanel")).toHaveLength(1);
    expect(screen.getByTestId("val-footer")).toHaveTextContent(
      "Validation spends no model money ($0.00); all paid inference this month: $3.42. Balanced on purpose: recall, earliness, quality, novelty and your attention are shown side by side — there is no single score to optimise. Daily snapshots kept: 5.",
    );
  });

  it("Are we early?: the eight edge stats, the grounded sparklines and today's evidence", async () => {
    fakeServer();
    await opened();
    const edge = screen.getByTestId("val-edge");
    expect(within(edge).getByRole("heading", { name: "Project Zero edge" })).toBeInTheDocument();
    expect(edge).toHaveTextContent("2026-11-12");
    const t = edge.textContent!;
    for (const s of [
      "14companies first seen this month",
      "57%pre-funding (8 this month)",
      "61 dmedian lead time before a later public event (n=6)",
      "4found only through their own funding news (lead 0)",
      "collecting (3/5)exceptional recall (1 of 3 strong cases)",
      "1 early · 1 latestrong cases we saw before their public event",
      "1false negatives · 1 never seen",
      "9single-source discoveries this month",
    ])
      expect(t, s).toContain(s);
    const trends = screen.getByTestId("val-trends");
    expect(trends).toHaveAttribute("data-signature", "data");
    expect(within(trends).getAllByRole("img").map((i) => i.getAttribute("aria-label"))).toEqual([
      "first seen this month: 9, 10, 12, 13, 14",
      "median lead days: 58, 60, 61",
      "Conviction size: 2, 2, 3, 3, 3",
    ]);
    expect(trends).toHaveTextContent("Direction over 5 daily snapshots — not a significance claim.");
    expect(edge).toHaveTextContent(
      "Outcome evidence today: unknown 31 · external signal 4 · promising human 3 · negative 2 · strong verified 1 · strong human 1. Age of discoveries: immediate 14 · 30-90 days 18 · 3-6 months 9 · unknown 1.",
    );
  });

  it("What can we measure yet?: collapsed, with the state counts; open shows six metrics and the data warnings", async () => {
    fakeServer();
    await opened();
    const d = screen.getByTestId("val-measurement-d");
    expect(d).not.toHaveAttribute("open");
    expect(d).toHaveTextContent("4 collecting · 1 known · 1 partly known");
    expect(screen.queryByTestId("val-measurement")).toBeNull();
    fireEvent.click(within(d).getByText("What can we measure yet?", { selector: "summary *" }));
    const rows = await screen.findAllByTestId("val-measure");
    expect(rows.map((r) => r.dataset.state)).toEqual(["COLLECTING", "KNOWN", "COLLECTING", "COLLECTING", "PARTLY KNOWN", "COLLECTING"]);
    expect(rows[0]).toHaveTextContent(
      "COLLECTINGExceptional recall — Of the companies that later proved strong, how many did we catch?3 so far · needs: real-world outcomes (rounds, customers) and miss audits — months, not days",
    );
    expect(rows[1]).toHaveTextContent("KNOWNSignal lead time — How many days before a later public event did we first see the company?");
    expect(rows[1]).not.toHaveTextContent("needs:");
    expect(rows[4]).toHaveTextContent("PARTLY KNOWNSource alpha");
    expect(rows[4]).not.toHaveTextContent("so far");
    expect(screen.getByTestId("val-data-issues")).toHaveTextContent(
      "Data warnings (excluded from the numbers, nothing was changed): Vessra Robotics: first-seen date 2027-02-01 is in the future — ignored",
    );
  });

  it("Are we right?: conversion by grouping (kept across questions), calibration and the newest-first outcome ledger", async () => {
    fakeServer();
    await opened();
    ask("Are we right?");
    expect(tab("Are we right?")).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByTestId("val-edge")).toBeNull();
    const conv = screen.getByTestId("val-conversion");
    expect(within(conv).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Discovery type",
      "Discovered",
      "Machine KEEP / RESEARCH",
      "Mohamed accepted",
      "Conviction",
      "Fully verified",
      "Radar",
      "IMQ qualified",
      "Sent to Omar",
    ]);
    const body = () => within(conv).getAllByRole("row").slice(1);
    expect(body().map((r) => r.textContent)).toEqual(["pre company225221100", "grant122110000", "announcement81000000"]);
    expect(within(body()[2]).getAllByRole("cell")[3]).toHaveClass("faint");
    const groupBy = within(conv).getByRole("tablist", { name: "Group by" });
    fireEvent.click(within(groupBy).getByRole("tab", { name: "Country" }));
    expect(within(conv).getAllByRole("columnheader")[0]).toHaveTextContent("Country");
    expect(body().map((r) => (r as HTMLTableRowElement).cells[0].textContent)).toEqual(["DE", "AT", "CH"]);
    // the grouping survives a visit to another question
    ask("Are we early?");
    ask("Are we right?");
    expect(within(screen.getByTestId("val-conversion")).getAllByRole("columnheader")[0]).toHaveTextContent("Country");
    fireEvent.click(within(screen.getByRole("tablist", { name: "Group by" })).getByRole("tab", { name: "Scout lane" }));
    expect(screen.getByTestId("val-conversion")).toHaveTextContent("No companies in this grouping yet.");

    const cal = screen.getByTestId("val-calibration");
    expect(within(cal).getByRole("heading", { name: "Smooth Operator calibration — human vs machine" })).toBeInTheDocument();
    for (const s of [
      "4your triage decisions",
      "collecting (4/5)agreement with machine",
      "1machine REJECTs you overturned",
      "1machine KEEPs you rejected",
      "7 minreview time (est. from timestamps)",
      "When you disagreed, who was right? pending 1 · mohamed 1",
      "Patterns appear once a decision group has 5+ resolved outcomes. They describe — they never change your scoring.",
      "Real operating decisions only — the development and holdout labels are excluded on purpose.",
    ])
      expect(cal.textContent, s).toContain(s);
    expect(screen.getByTestId("val-verification-cal")).toHaveTextContent("Verification proposals you decided: founder_unverified: 2 accepted · 1 rejected");

    const ledger = screen.getAllByTestId("val-outcome");
    expect(ledger.map((o) => o.querySelector("b")?.textContent)).toEqual(["Lumenfold AI", "Aurelith Systems"]);
    expect(ledger[0]).toHaveTextContent("Lumenfold AI — Visible in an external database (Dealroom / Crunchbase / …) · 2026-10-07");
    expect(within(ledger[0]).queryByRole("link")).toBeNull();
    expect(ledger[1]).toHaveTextContent("Aurelith Systems — Institutional funding round announced · 2026-09-18");
    const src = within(ledger[1]).getByRole("link", { name: "source" });
    expect(src).toHaveAttribute("href", "https://news.example/aurelith-seed-round");
    expect(src).toHaveAttribute("target", "_blank");
    expect(src).toHaveAttribute("rel", "noreferrer");
  });

  it("patterns are listed once the server states them", async () => {
    fakeServer({ validation: () => ({ ...validation(), patterns: ["Your KEEP calls on pre-company companies: 4/5 resolved cases turned out promising or strong (9 decisions in total)."] }) });
    await opened();
    ask("Are we right?");
    expect(within(screen.getByTestId("val-calibration")).getByRole("listitem")).toHaveTextContent(
      "Your KEEP calls on pre-company companies: 4/5 resolved cases turned out promising or strong (9 decisions in total).",
    );
    expect(screen.getByTestId("val-calibration")).not.toHaveTextContent("Patterns appear once");
  });

  it("Which sources work?: twelve source rows, the benchmarks, and the News panel's reason", async () => {
    fakeServer();
    await opened();
    ask("Which sources work?");
    const s = screen.getByTestId("val-sources");
    expect(within(s).getByRole("heading", { name: "Best sources — value, not volume" })).toBeInTheDocument();
    const heads = within(s).getAllByRole("columnheader");
    expect(heads.map((h) => h.textContent)).toEqual([
      "Source",
      "Found",
      "Unique",
      "Pre-funding",
      "Machine K/R",
      "You accepted",
      "Conviction",
      "Strong",
      "Median lead",
      "Via own funding news",
      "Value / found",
    ]);
    expect(heads[10]).toHaveAttribute("title", expect.stringMatching(/^Ranking aid only/));
    const rows = within(s).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(12); // 13 sources: the 13th (lowest value) is not shown
    expect(s).not.toHaveTextContent("Quarry startup press");
    expect([...(rows[0] as HTMLTableRowElement).cells].map((c) => c.textContent)).toEqual(["Northgate University spin-outs", "14", "11", "50%", "29%", "1", "1", "1", "74 d (n=3)", "0", "1.40"]);
    expect([...(rows[1] as HTMLTableRowElement).cells].map((c) => c.textContent)[8]).toBe("58.5 d (n=2)");
    expect([...(rows[2] as HTMLTableRowElement).cells].map((c) => c.textContent)[8]).toBe("—");

    const b = screen.getByTestId("val-benchmarks");
    expect(b).toHaveTextContent("No private database access is assumed");
    const systems = within(b).getAllByTestId("val-benchmark");
    expect(systems[0]).toHaveTextContent("Dealroom: 1 company · PZ earlier for 1, same day or later for 0 · median shown from 5 companies");
    expect(systems[1]).toHaveTextContent("Public funding news (seen by a scan): 5 companies · PZ earlier for 4, same day or later for 1 · median 47 days");
    expect(within(systems[1]).getAllByRole("listitem")).toHaveLength(5);

    const news = screen.getByTestId("val-news");
    expect(within(news).getByRole("heading", { name: "News benchmark — did we know them before the news?" })).toBeInTheDocument();
    expect(screen.getByTestId("val-news-deferred")).toHaveTextContent(/^News & Learning arrives with its port$/);
  });

  it("the News panel shows the old numbers once News is available", async () => {
    fakeServer({
      validation: () => ({
        ...validation(),
        news: { available: true, reviewed: 9, caught_early: 3, known_late: 2, operational_misses: 1, historical_cases: 2, not_yet_reviewed: 1, median_lead_days: 21, preventable_misses: 1, most_common_miss_cause: "source_not_covered", early_discovery_sources: [] },
      }),
    });
    await opened();
    ask("Which sources work?");
    const news = screen.getByTestId("val-news");
    expect(news).toHaveTextContent(
      "9 material stories about companies with a verdict: 3 caught early · 2 known late · 1 operational misses · 2 historical cases · 1 not yet reviewed · median lead 21 days · 1 preventable · most common miss cause: source not covered.",
    );
    expect(screen.queryByTestId("val-news-deferred")).toBeNull();
  });

  it("Where do we miss?: the audits, the false-positive watch and the Scout 00 summary", async () => {
    fakeServer();
    await opened();
    ask("Where do we miss?");
    const m = screen.getByTestId("val-misses");
    const audits = within(m).getAllByTestId("val-audit");
    expect(audits.map((a) => a.textContent)).toEqual([
      "MISS Orbelle Health · never seenearliest signal: Grant award listed on the Riverside register (2026-06-03) · should have been found by grants lane · why: source covered but failed · preventable: yes→ Read the grant register weekly, not monthly",
      "MISS Nordquill Sensors · seen early, rejectedearliest signal: Demo day pitch  · should have been found by — · why: machine reject · preventable: unclear",
      "FALSE POSITIVE Graniteleaf Labsweak source, late stage mistaken for early — A Series B press release is not an early signal",
    ]);
    expect(m).toHaveTextContent("Prioritised but now negative (worth a false-positive audit): Graniteleaf Labs");
    expect(m).not.toHaveTextContent("Nothing recorded yet.");
    const sc = screen.getByTestId("val-scout");
    expect(sc).toHaveTextContent("5 Scout intake item(s) across cycle(s) c-2026-10-02, c-2026-10-16: PENDING 3 · PROGRESSING 1 · DID NOT HOLD UP 1.");
    expect(sc).not.toHaveTextContent("Last packet handed over");
    expect(sc).toHaveTextContent("Manual copy/paste into grok.com — nothing is sent automatically.");
  });

  it("the last handed-over packet is named", async () => {
    const d = validation();
    fakeServer({ validation: () => ({ ...d, scout: { ...d.scout, last_packet: { at: "2026-10-30T11:02:00", cycle: "c-2026-10-16", companies: 3 } } }) });
    await opened();
    ask("Where do we miss?");
    expect(screen.getByTestId("val-scout")).toHaveTextContent("Last packet handed over 2026-10-30T11:02:00 (cycle c-2026-10-16).");
  });

  it("prepares the Scout 00 packet for the latest cycle with one read; marking it as sent is deferred", async () => {
    const server = fakeServer();
    await opened();
    ask("Where do we miss?");
    expect(screen.queryByTestId("scout-packet-copy")).toBeNull();
    expect(screen.queryByTestId("scout-packet-text")).toBeNull();
    fireEvent.click(screen.getByTestId("scout-packet"));
    const text = await screen.findByTestId("scout-packet-text");
    expect(server.gets()).toEqual(["/api/validation", "/api/validation/scout_packet?cycle=c-2026-10-16"]);
    expect(text.textContent).toBe(packet().text);
    expect(text).toHaveTextContent("PROJECT ZERO → CHIEF SCOUT 00");
    expect(text).toHaveTextContent("Orbelle Health"); // misses are fed back to the scouts
    expect(screen.getByTestId("scout-packet-deferred")).toHaveTextContent("News and source-network learnings: News & Learning arrives with its port.");
    const copy = screen.getByTestId("scout-packet-copy");
    expect(copy).toHaveTextContent("Copy & log handover");
    expectDeferred(copy);
    const write = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText: write }, configurable: true });
    pressEveryWay(copy);
    expect(write).not.toHaveBeenCalled();
    // the packet survives a visit to another question
    ask("Are we early?");
    ask("Where do we miss?");
    expect(screen.getByTestId("scout-packet-text")).toBeInTheDocument();
    expect(server.writes()).toEqual([]);
  });

  it("no cycle yet: the packet is asked for every cycle; a failure is a toast", async () => {
    const server = fakeServer({ validation: emptyValidation, scoutPacket: () => ({ status: 500, body: { ok: false, error: "Project Zero hit an internal error (boom)" } }) });
    await opened();
    ask("Where do we miss?");
    fireEvent.click(screen.getByTestId("scout-packet"));
    expect(await screen.findByText(/✕ Preparing the Scout 00 packet failed — Project Zero hit an internal error \(boom\)/)).toBeInTheDocument();
    expect(server.gets()[1]).toBe("/api/validation/scout_packet");
    expect(screen.queryByTestId("scout-packet-text")).toBeNull();
    await waitFor(() => expect(screen.getByTestId("scout-packet")).not.toBeDisabled());
  });

  it("What does it cost?: the native search bridge pilot keeps its place with its reason", async () => {
    fakeServer();
    await opened();
    ask("What does it cost?");
    const nb = screen.getByTestId("val-native-bridge");
    expect(within(nb).getByRole("heading", { name: "Native search bridge — production pilot" })).toBeInTheDocument();
    expect(screen.getByTestId("val-native-bridge-deferred")).toHaveTextContent(NOT_PORTED.bridge);
  });

  it("the old null answer for the pilot shows the same reason", async () => {
    fakeServer({ validation: () => ({ ...validation(), native_bridge: null }) });
    await opened();
    ask("What does it cost?");
    expect(screen.getByTestId("val-native-bridge-deferred")).toHaveTextContent(NOT_PORTED.bridge);
  });

  it("the old pilot metrics would still render (the server never sends them in the rewrite)", async () => {
    const m: NativeBridgeMetrics = {
      label: "pilot",
      status: { state: "ACTIVE", day_usd: 0.5, month_usd: 4, daily_cap: 2, monthly_cap: 30, x_hunts_this_week: 3, x_hunts_per_week: 5 },
      spend_usd: 4,
      convergence: 2,
      funnel: { hunts: 9, new: 4, investigate: 2 },
      cost_per: { hunt: 0.44, investigate: null },
      alpha: { lane: [{ key: "energy", found: 4, investigate: 2, contact_yes: 1 }], geography: [], query: [], web_vs_x: [], source: [] },
      note: "Measurement only.",
    };
    fakeServer({ validation: () => ({ ...validation(), native_bridge: m }) });
    await opened();
    ask("What does it cost?");
    const nb = screen.getByTestId("val-native-bridge");
    expect(nb).toHaveTextContent("9 hunts → 4 new companies → 2 credible INVESTIGATE → 0 would contact");
    expect(nb).toHaveTextContent("· 2 cross-scout convergence.");
    expect(nb).toHaveTextContent("Spend $4.00 (today $0.50 of $2.00 · month $4.00 of $30.00 · X 3/5 this week · ACTIVE). Cost per hunt $0.44 · credible INVESTIGATE —");
    expect(nb).toHaveTextContent("Alpha (INVESTIGATE / found) — lane: energy 2/4; geography: —; web vs X: —; source: —.");
    expect(screen.queryByTestId("val-native-bridge-deferred")).toBeNull();
  });
});

describe("Validation — the writes are deferred to review 027b", () => {
  it("every write control is visible, disabled with its reason, and sends nothing", async () => {
    const server = fakeServer();
    const prompt = vi.spyOn(window, "prompt").mockReturnValue("a reason long enough");
    await opened();

    const record = screen.getByTestId("record-outcome");
    expect(record).toHaveTextContent("Record outcome");
    expectDeferred(record);
    pressEveryWay(record);
    expect(screen.queryByRole("dialog")).toBeNull();

    const more = screen.getByTestId("more-actions");
    fireEvent.click(within(more).getByText("More"));
    const miss = within(more).getByTestId("record-miss");
    expect(miss).toHaveTextContent("Record a miss");
    expect(miss).toBeDisabled();
    expect(miss).toHaveAttribute("title", WRITES);
    pressEveryWay(miss);

    ask("Are we right?");
    const retracts = screen.getAllByRole("button", { name: "Retract" });
    expect(retracts).toHaveLength(2);
    for (const r of retracts) {
      expectDeferred(r);
      pressEveryWay(r);
    }
    expect(prompt).not.toHaveBeenCalled();

    ask("Which sources work?");
    const bench = screen.getByTestId("val-benchmarks");
    fireEvent.click(within(bench).getByText("Import a benchmark export (e.g. a Dealroom CSV you downloaded)"));
    fireEvent.change(within(bench).getByPlaceholderText("Dealroom"), { target: { value: "Dealroom" } });
    fireEvent.change(bench.querySelector("textarea")!, { target: { value: "Name,Date added\nKestrel Labs,2026-07-01\n" } });
    const preview = within(bench).getByRole("button", { name: "Preview" });
    expectDeferred(preview);
    pressEveryWay(preview);
    expect(within(bench).queryByRole("button", { name: /^Import \d+ dates$/ })).toBeNull();

    ask("Where do we miss?");
    const fp = screen.getByTestId("record-fp");
    expect(fp).toHaveTextContent("Record false positive");
    expectDeferred(fp);
    pressEveryWay(fp);
    expect(screen.queryByRole("dialog")).toBeNull();

    await new Promise((r) => setTimeout(r, 0));
    expect(server.writes()).toEqual([]);
    expect(server.posts()).toEqual([]);
    expect(server.gets()).toEqual(["/api/validation"]);
  });
});

describe("Validation — honest empty and failing states", () => {
  it("an empty data folder: nothing measurable, nothing recorded, no trend line", async () => {
    fakeServer({ validation: emptyValidation });
    await opened();
    expect(screen.getByTestId("val-measurement-d")).toHaveTextContent("5 not yet measurable · 1 partly known");
    fireEvent.click(within(screen.getByTestId("val-measurement-d")).getByText("What can we measure yet?", { selector: "summary *" }));
    expect(await screen.findByTestId("val-measurement")).toHaveTextContent("NOT YET MEASURABLE");
    expect(screen.queryByTestId("val-data-issues")).toBeNull();
    expect(screen.queryByTestId("val-trends")).toBeNull();
    const edge = screen.getByTestId("val-edge");
    expect(edge).toHaveTextContent("—pre-funding (0 this month)");
    expect(edge).toHaveTextContent("—median lead time before a later public event (n=0)");
    expect(edge).toHaveTextContent("collecting (0/5)exceptional recall (0 of 0 strong cases)");
    expect(edge).toHaveTextContent("Outcome evidence today: . Age of discoveries: .");
    ask("Are we right?");
    expect(screen.getByTestId("val-conversion")).toHaveTextContent("No companies in this grouping yet.");
    expect(screen.getByTestId("val-calibration")).toHaveTextContent("When you disagreed, who was right? no disagreements with a known outcome yet");
    expect(screen.getByTestId("val-verification-cal")).toHaveTextContent("none yet (founder / funding proposals appear in Conviction → Verification)");
    expect(screen.getByTestId("val-outcomes")).toHaveTextContent(/^Outcome ledgerNo outcomes recorded yet\./);
    expect(screen.queryByRole("button", { name: "Retract" })).toBeNull();
    ask("Which sources work?");
    expect(within(screen.getByTestId("val-sources")).getAllByRole("row")).toHaveLength(1);
    expect(screen.getByTestId("val-benchmarks")).toHaveTextContent("No benchmark dates yet.");
    ask("Where do we miss?");
    expect(screen.getByTestId("val-misses")).toHaveTextContent("Nothing recorded yet. When you learn about a strong company Project Zero missed");
    expect(screen.getByTestId("val-misses")).not.toHaveTextContent("Prioritised but now negative");
    expect(screen.getByTestId("val-scout")).toHaveTextContent("0 Scout intake item(s) across cycle(s) —: none yet.");
    expect(screen.getByTestId("val-footer")).toHaveTextContent("Daily snapshots kept: 1.");
  });

  it("a failed read shows the error with a retry", async () => {
    let n = 0;
    fakeServer({ validation: () => (++n === 1 ? { status: 500, body: { ok: false, error: "Project Zero hit an internal error (db)" } } : validation()) });
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Project Zero hit an internal error (db)");
    // the header and its (deferred) actions stay in place
    expect(screen.getByTestId("record-outcome")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByTestId("val-edge")).toBeInTheDocument();
  });
});

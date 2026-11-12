import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ALL_ITEMS } from "@/app/nav";
import { REFRESH_STATUS, VALIDATION } from "./api";
import { NOT_PORTED } from "./model/deferred";
import type { NewsPayload, Story, Window } from "./model/types";
import { EMPTY, THEMES_EMPTY } from "./model/view";
import { SIGNAL_FORM } from "./model/writes";
import { emptyNews, emptyWeekly, news, refreshStatus, sources, writeAnswer } from "./test/fixtures";
import { fakeServer, renderPage } from "./test/server";

const sections = () => screen.getByRole("tablist", { name: "News sections" });
const open = (name: string) => fireEvent.click(within(sections()).getByRole("tab", { name }));
const stories = () => screen.queryAllByTestId("news-story");
const card = (company: string) => stories().find((s) => within(s).queryByText(company, { selector: "div" }))!;
const settle = () => new Promise((r) => setTimeout(r, 0));
const type = (el: Element, value: string) => fireEvent.change(el, { target: { value } });
const dialog = () => screen.getByRole("dialog");

async function opened() {
  const r = renderPage();
  await screen.findByTestId("news-concept");
  return r;
}

/** A deferred control: visible, focusable, named, says why — and a click, Enter or Space does nothing. */
function expectDeferred(el: HTMLElement, reason: string) {
  expect(el).toBeVisible();
  expect(el).toHaveAttribute("aria-disabled", "true");
  expect(el).toHaveAttribute("title", reason);
  expect(document.getElementById(el.getAttribute("aria-describedby")!)?.textContent).toBe(reason);
  fireEvent.click(el);
  for (const key of ["Enter", " "]) {
    fireEvent.keyDown(el, { key });
    fireEvent.keyUp(el, { key });
    fireEvent.click(el, { detail: 0 });
  }
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("News & Learning — the page", () => {
  it("is a ported nav view at /news", () => {
    expect(ALL_ITEMS.find((i) => i.legacyView === "news")).toMatchObject({ path: "/news", label: "News & Learning", page: expect.anything() });
  });

  it("opens on Today after two reads, with the old header, intro cards, nine sections and footer", async () => {
    const server = fakeServer();
    await opened();
    expect([...server.gets()].sort()).toEqual(["/api/news", "/api/news/refresh_status"]);
    expect(screen.getByRole("heading", { level: 1, name: "News & Learning" })).toBeInTheDocument();
    expect(screen.getByText(/^What happened in European startups/)).toHaveTextContent(
      "What happened in European startups — why it matters, and whether Project Zero saw it coming.",
    );
    expect(screen.getByTestId("news-concept")).toHaveTextContent(
      "VC concept of the dayWhat is a lead investor?The fund that sets the terms and usually invests the most. Who leads tells you who did the deepest diligence.",
    );
    expect(screen.getByText("One thing to notice earlier next time").parentElement).toHaveTextContent(
      "The earliest public signal was a grant signal (2026-10). Today this is covered by: grant sources (EXIST, Innosuisse, EIC, UKRI, NIH/NSF).",
    );
    expect(screen.getByTestId("news-vs")).toHaveTextContent(
      "Project Zero vs the news1 caught early · 1 known late · 1 missed · 1 historical · median lead 61 days1 noise and 2 minor stories kept out of the top. News is context and a benchmark — not sourcing alpha. Learnings are proposals; nothing here changes scores, sources, themes, Radar or IMQ.",
    );
    expect(within(sections()).getAllByRole("tab").map((t) => t.textContent)).toEqual([
      "Today",
      "All stories",
      "Caught early",
      "Misses",
      "Historical cases",
      "What's moving",
      "My companies",
      "Weekly review",
      "News sources",
    ]);
    expect(within(sections()).getByRole("tab", { name: "Today" })).toHaveAttribute("aria-selected", "true");
    expect(stories().map((s) => s.dataset.state)).toEqual(["CAUGHT_EARLY", "UNKNOWN", "KNOWN_LATE"]);
    expect(screen.getByTestId("news-footer")).toHaveTextContent(
      "Last refresh: 2026-11-12 07:00 · 5 feeds · 3 new events · 1 feed(s) failed (retried tomorrow). Project Zero started on 27 Sept 2026.",
    );
  });

  it("an early catch: badges, the card, why the source matters, the disagreement, the check and the proposal", async () => {
    fakeServer();
    await opened();
    const v = card("Vantor Kinetics");
    expect(v).toHaveTextContent("🔥 IMPORTANTEARLY CATCHYOUR DEAL FLOWFunding round · 10 Nov 2026 · 3 sources");
    expect(within(v).getByRole("heading", { level: 3 })).toHaveTextContent("Munich robotics start-up Vantor Kinetics raises €18M Series A led by Lindqvist Partners");
    expect(v).toHaveTextContent("What happenedVantor Kinetics, a Munich maker of autonomous handling robots");
    expect(v).toHaveTextContent("Why it mattersInvestors committed money: a signal about the market and the stage the company has reached.");
    expect(v).not.toHaveTextContent("The company"); // the rules card has no company text
    expect(v).toHaveTextContent("VC lessonUsually €5–20M once a repeatable way to win customers exists.");
    expect(within(v).getByTestId("news-source-note")).toHaveTextContent(
      "Why this source matters: Isar Startup Post: regional intelligence — covered 9/14 Munich events reported elsewhere. Alpine Wire: core european intelligence",
    );
    expect(within(v).getByTestId("news-disagreement")).toHaveTextContent(
      "Sources disagree — amount: Isar Startup Post 18M vs Alpine Wire 18.4M (settled by primary source). Project Zero does not pick a winner silently.",
    );
    expect(within(v).getByTestId("news-check")).toHaveTextContent(
      "Project Zero check Project Zero edge: detected 61 days before this event. First seen 10 Sept 2026 via northgate-spinouts (pre-company), capital stage then: pre seed. Machine said STRONG, you decided PURSUE.",
    );
    const p = within(v).getByTestId("news-outcome-proposal");
    expect(p).toHaveTextContent(
      "Propose outcome: this looks like a real-world institutional round for Vantor Kinetics. Project Zero first saw Vantor Kinetics 61 day(s) before this event. Only your confirmation records it in Validation.",
    );
    expect(within(p).getAllByRole("button").map((b) => b.textContent)).toEqual(["Confirm outcome", "Reject", "Not enough evidence"]);
    expect(within(v).queryByTestId("news-audit")).toBeNull();
  });

  it("the outcome decision buttons are enabled (no click, no write); a story already decided shows no proposal", async () => {
    const server = fakeServer();
    await opened();
    const p = within(card("Vantor Kinetics")).getByTestId("news-outcome-proposal");
    for (const b of within(p).getAllByRole("button")) {
      expect(b).toBeEnabled();
      expect(b).not.toHaveAttribute("aria-disabled");
    }
    await settle();
    expect(server.writes()).toEqual([]);
    expect(card("Lumora Grid")).toBeTruthy();
    expect(within(card("Lumora Grid")).queryByTestId("news-outcome-proposal")).toBeNull(); // rejected before
  });

  it("Sources & learning: no backcast yet, 'Add an early signal' enabled, the sources and the card's provenance — no Scout Bridge", async () => {
    const server = fakeServer();
    await opened();
    const v = card("Vantor Kinetics");
    fireEvent.click(within(v).getByRole("button", { name: "Sources & learning" }));
    expect(within(v).getByRole("button", { name: "Hide analysis" })).toBeInTheDocument();
    expect(v).toHaveTextContent("No backcast yet: what public signals existed before this story? Add one signal with its source.");
    expect(within(v).getByRole("button", { name: "Add an early signal" })).toBeEnabled();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(within(v).queryByRole("button", { name: /Prepare backcast research/ })).toBeNull();
    expect(screen.queryByText(/Scout Bridge/)).toBeNull();
    const items = within(v).getByText("Sources").parentElement!.querySelectorAll("li");
    expect(Array.from(items).map((li) => li.textContent)).toEqual([
      "Isar Startup Post · 10 Nov 2026 independent media",
      "Alpine Wire · 11 Nov 2026 independent media",
      "Vantor Kinetics · 10 Nov 2026 primary source",
    ]);
    expect(within(v).getByRole("link", { name: "Alpine Wire" })).toHaveAttribute("href", "https://alpinewire.example/vantor-kinetics-20m");
    expect(v).toHaveTextContent("Summary built by rules (no model) from the article text.");
    expect(within(v).queryByText("What to watch next")).toBeNull();
    await settle();
    expect(server.writes()).toEqual([]);
  });

  it("Today: an unreviewed possible miss with its audit recorded, an open disagreement and a model-written card", async () => {
    fakeServer();
    await opened();
    const q = card("Quillon Labs");
    expect(q).toHaveTextContent("🔥 IMPORTANTNOT SEEN BY PZFunding round · 8 Nov 2026 · 2 sources");
    expect(within(q).getByTestId("news-check")).toHaveTextContent(
      "Project Zero has not seen Quillon Labs. Not yet reviewed — it may be a miss, or the early signals may predate Project Zero. Add a backcast or audit it.",
    );
    expect(within(q).getByTestId("news-disagreement")).toHaveTextContent("round: Alpine Wire series b vs Harbour Post series c (not settled yet)");
    expect(within(q).queryByTestId("news-audit")).toBeNull();
    expect(q).toHaveTextContent("miss audit recorded");
    expect(q).toHaveTextContent("The companyQuillon Labs sells software");
    fireEvent.click(within(q).getByRole("button", { name: "Sources & learning" }));
    expect(q).toHaveTextContent("What to watch nextWhether the round included a strategic investor from the automotive sideFirst customer outside Germany");
    expect(q).toHaveTextContent("Baltic Founders · 9 Nov 2026 copy of another article");
    expect(q).toHaveTextContent("Summary written by gemma-mini from the article text only.");
    const l = card("Lumora Grid");
    expect(l).toHaveTextContent("KNOWN, BUT LATEYOUR DEAL FLOWFunding round · 6 Nov 2026 · 1 source");
    expect(l).not.toHaveTextContent("🔥 IMPORTANT");
    expect(within(l).getByTestId("news-check")).toHaveTextContent(
      "Project Zero knew Lumora Grid, but only at the time of this news — it was found through funding news itself. No sourcing edge claimed.",
    );
    expect(within(l).queryByTestId("news-teach")).toBeInTheDocument();
    fireEvent.click(within(l).getByRole("button", { name: "Sources & learning" }));
    expect(within(l).queryByRole("button", { name: "Add an early signal" })).toBeNull(); // MEDIUM
    expect(l).not.toHaveTextContent("No backcast yet");
  });

  it("Misses: the missed story can be audited; its backcast reads in full", async () => {
    const server = fakeServer();
    await opened();
    open("Misses");
    expect(stories().map((s) => s.dataset.state)).toEqual(["UNKNOWN", "MISSED"]);
    const b = card("Brightwell Bio");
    expect(b).toHaveTextContent("🔥 IMPORTANTMISSEDAcquisition · 3 Nov 2026 · 1 source");
    expect(within(b).getByTestId("news-check")).toHaveTextContent("A public signal existed while Project Zero was running, and Project Zero did not detect it.");
    expect(within(b).getByTestId("news-audit")).toBeEnabled();
    expect(within(b).getByTestId("news-audit")).toHaveTextContent("Audit this miss");
    fireEvent.click(within(b).getByRole("button", { name: "Backcast & sources" }));
    const bc = within(b).getByTestId("news-backcast");
    expect(bc).toHaveTextContent("Backcast — what could we have seen?");
    expect(Array.from(bc.querySelectorAll("li")).map((li) => li.textContent)).toEqual([
      "Apr 2025 Founders publish the blood-marker model paper (only clear in hindsight). only clear in retrospect source",
      "2 Oct 2026 Brightwell Bio named in a regional health-innovation grant list (EUR 1.2M). known early signal source",
    ]);
    expect(bc).toHaveTextContent(
      "Earliest plausible signal: Brightwell Bio named in a regional health-innovation grant list (EUR 1.2M). (2 Oct 2026)Best sensor today: grant sources (EXIST, Innosuisse, EIC, UKRI, NIH/NSF)",
    );
    expect(bc).toHaveTextContent("Learning: The earliest public signal was a grant signal (2026-10).");
    expect(bc).toHaveTextContent("A learning is a proposal for sourcing — it never changes scores, sources or themes on its own.");
    expect(within(b).queryByText(/No backcast yet/)).toBeNull();
    expect(within(b).getByRole("button", { name: "Add an early signal" })).toBeEnabled();
    await settle();
    expect(server.writes()).toEqual([]);
  });

  it("Historical cases: the curated case teaches its concepts and shows a sourced backcast", async () => {
    fakeServer();
    await opened();
    open("Historical cases");
    const h = card("Halvard Robotics");
    expect(h).toHaveTextContent("🔥 IMPORTANTHISTORICAL CASEValuation milestone · 5 Oct 2026 · 3 sources");
    expect(within(h).getByTestId("news-check")).toHaveTextContent("Its early signals predate Project Zero (started 27 Sept 2026) — a learning case, not a miss.");
    expect(within(h).getByTestId("news-source-note")).toHaveTextContent("Ledger Gazette is used here as confirmation / authority");
    fireEvent.click(within(h).getByTestId("news-teach"));
    expect(h).toHaveTextContent("What does a valuation mean?");
    expect(h).toHaveTextContent("What is a secondary sale?");
    fireEvent.click(within(h).getByTestId("news-teach"));
    expect(h).not.toHaveTextContent("What is a secondary sale?");
    fireEvent.click(within(h).getByRole("button", { name: "Backcast & sources" }));
    const bc = within(h).getByTestId("news-backcast");
    expect(bc).toHaveTextContent("only clear in retrospect");
    expect(bc).toHaveTextContent("university spinout");
    expect(bc.querySelectorAll("li")[0]).toHaveTextContent(/^2020 Years of research/);
    expect(bc.querySelectorAll("li")[2]).toHaveTextContent(/^Jun 2021 Seed round/);
    expect(bc).toHaveTextContent("Learning: Halvard Robotics' earliest public signal was a university robotics spinout (2020)");
    expect(h).toHaveTextContent("Curated from the linked sources.");
    expect(h).toHaveTextContent("What to watch nextWhether a primary round follows the secondary saleHiring for a US sales team");
  });

  it("All stories, Caught early and My companies list the payload's stories (no noise)", async () => {
    fakeServer();
    await opened();
    open("All stories");
    expect(stories().map((s) => s.dataset.state)).toEqual(["CAUGHT_EARLY", "UNKNOWN", "MISSED", "HISTORICAL", "KNOWN_LATE", "UNKNOWN", "NOT_RELEVANT"]);
    expect(screen.queryByText("Top 10 robotics startups to watch this winter")).toBeNull();
    const o = card("Ostra Systems");
    expect(o).toHaveTextContent("NOT SEEN BY PZProduct launch · 9 Nov 2026 · 1 source");
    expect(o).toHaveTextContent("What happenedOnly the headline is available — open the source.");
    expect(within(o).getByTestId("news-check")).toHaveTextContent(/^Project Zero check Project Zero has not seen Ostra Systems\.$/);
    expect(within(o).queryByTestId("news-teach")).toBeNull();
    fireEvent.click(within(o).getByRole("button", { name: "Sources & learning" }));
    expect(o).not.toHaveTextContent("Summary built by rules"); // no card, no provenance
    const p = card("Pinecrest Capital");
    expect(p).toHaveTextContent("NOT RELEVANT TO PZVC fund news · 7 Nov 2026 · 1 source");
    expect(within(p).getByTestId("news-check")).toHaveTextContent("Outside Project Zero's geography or themes — context only.");
    open("Caught early");
    expect(stories().map((s) => s.dataset.state)).toEqual(["CAUGHT_EARLY"]);
    open("My companies");
    expect(stories().map((s) => within(s).getByRole("heading").textContent)).toEqual([
      "Munich robotics start-up Vantor Kinetics raises €18M Series A led by Lindqvist Partners",
      "Lumora Grid secures €3M seed round to balance neighbourhood grids",
    ]);
    expect(within(sections()).getByRole("tab", { name: "My companies" })).toHaveAttribute("aria-selected", "true");
  });

  it("What's moving: market signals with their supporting stories", async () => {
    fakeServer();
    await opened();
    open("What's moving");
    const themes = screen.getAllByTestId("news-theme");
    expect(themes).toHaveLength(2);
    expect(themes[0]).toHaveTextContent("MARKET SIGNALconfidence: early signal3 ai companies in Germany with funding round, acquisition in the last 30 days");
    expect(themes[0]).toHaveTextContent("Why it could matterRepeated activity can mean investor attention");
    expect(Array.from(themes[0].querySelectorAll("li")).map((li) => li.textContent)).toEqual([
      "Munich robotics start-up Vantor Kinetics raises €18M Series A led by Lindqvist Partners",
      "Quillon Labs raises €25M Series B for battery diagnostics",
      "Brightwell Bio acquired by Corvane Diagnostics",
    ]);
    expect(themes[0]).toHaveTextContent("Project Zero already holds 7 companies with this theme.");
    expect(themes[1]).toHaveTextContent("confidence: moderate");
    expect(themes[1]).toHaveTextContent("Project Zero already holds 1 company with this theme.");
    expect(stories()).toEqual([]);
  });

  it("Weekly review: its own read, every section", async () => {
    const server = fakeServer();
    await opened();
    open("Weekly review");
    const w = await screen.findByTestId("news-weekly");
    expect(server.gets().filter((p) => p === "/api/news/weekly")).toHaveLength(1);
    expect(w).toHaveTextContent("Week ending 12 Nov 2026Weekly learning review");
    expect(Array.from(w.querySelectorAll("ol li")).map((li) => li.textContent)).toEqual([
      "Munich robotics start-up Vantor Kinetics raises €18M Series A led by Lindqvist Partners — Caught early",
      "Quillon Labs raises €25M Series B for battery diagnostics — Not seen by Project Zero — not yet reviewed",
      "Lumora Grid secures €3M seed round to balance neighbourhood grids — Known, but late",
    ]);
    expect(w).toHaveTextContent("Caught earlyVantor Kinetics");
    expect(w).toHaveTextContent("MissedNone confirmed this week.");
    expect(w).toHaveTextContent("Strongest pattern3 ai companies in Germany with funding round, acquisition in the last 30 days");
    expect(w).toHaveTextContent("One sourcing lessonMost documented early signals pointed to: grant sources (EXIST, Innosuisse, EIC, UKRI, NIH/NSF).");
    expect(w).toHaveTextContent("One VC lessonWhat is a lead investor? The fund that sets the terms");
  });

  it("Weekly review of a quiet week", async () => {
    fakeServer({ weekly: emptyWeekly });
    await opened();
    open("Weekly review");
    const w = await screen.findByTestId("news-weekly");
    expect(w).toHaveTextContent("Biggest relevant developmentsA quiet week.");
    expect(w).toHaveTextContent("Caught earlyNone this week.");
    expect(w).toHaveTextContent("Strongest patternNo pattern with enough evidence this week.");
    expect(w).toHaveTextContent("One sourcing lessonToo few backcasts yet for a sourcing lesson — add a backcast to one important story this week.");
    expect(w).toHaveTextContent("One VC lessonWhat does an accelerator signal?");
  });
});

describe("News & Learning — the refresh line", () => {
  it("after a partial run: the outcome, the failed source in plain words, and 'Refresh news' disabled with the 028c reason", async () => {
    const server = fakeServer();
    const { qc } = await opened();
    const box = screen.getByTestId("news-refresh");
    const result = await within(box).findByTestId("news-refresh-result");
    expect(result).toHaveAttribute("data-tone", "warn");
    expect(result).toHaveTextContent("Refresh partly done 6 sources checked (1 failed) · 184 articles fetched · 3 new stories (2 material)");
    expect(within(box).queryByTestId("news-last-ok")).toBeNull();
    expect(within(box).getByText("Which sources failed?")).toBeInTheDocument();
    expect(box).toHaveTextContent("Channel Tech Review — ");
    expect(box).not.toHaveTextContent("HTTPError");
    const button = within(box).getByTestId("news-refresh-button");
    expect(button).toHaveTextContent("Refresh news");
    expectDeferred(button, NOT_PORTED.refresh);
    await settle();
    expect(server.writes()).toEqual([]);
    // read once, never polled (the job is idle; nothing runs in 028a)
    expect(server.gets().filter((p) => p === "/api/news/refresh_status")).toHaveLength(1);
    expect(qc.getQueryCache().find({ queryKey: [REFRESH_STATUS, {}] })!.options).not.toHaveProperty("refetchInterval");
  });

  it("after a failed attempt: says so and shows the last successful refresh", async () => {
    fakeServer({ refreshStatus: () => refreshStatus("failed") });
    await opened();
    const result = await screen.findByTestId("news-refresh-result");
    expect(result).toHaveAttribute("data-tone", "fail");
    expect(result).toHaveTextContent("News refresh failed 2/6 sources could not be fetched · 2026-11-12 12:00");
    expect(screen.getByTestId("news-last-ok")).toHaveTextContent("Last successful refresh: 2026-11-12 07:00.");
    expect(screen.getByTestId("news-refresh")).toHaveTextContent("Alpine Wire — refused automated access");
  });

  it("before any run: 'Not refreshed yet.'", async () => {
    fakeServer({ refreshStatus: () => refreshStatus("never") });
    await opened();
    await waitFor(() => expect(screen.getByTestId("news-refresh")).toHaveTextContent("Not refreshed yet."));
    expect(screen.queryByTestId("news-refresh-result")).toBeNull();
    expect(screen.queryByText("Which sources failed?")).toBeNull();
  });
});

describe("News & Learning — News sources", () => {
  async function sourcesTab() {
    const server = fakeServer();
    await opened();
    open("News sources");
    const box = screen.getByTestId("news-sources");
    await within(box).findByTestId("news-sources-best");
    return { server, box };
  }

  it("90 days by default: best by purpose, collecting groups, the bias, missing publications, declining and every source", async () => {
    const { server, box } = await sourcesTab();
    expect(server.gets()).toContain("/api/news/sources?window=90");
    expect(within(box).getByRole("tablist", { name: "Time window" })).toBeInTheDocument();
    expect(within(box).getByRole("tab", { name: "90 days" })).toHaveAttribute("aria-selected", "true");
    expect(box).toHaveTextContent("How to read thisA news source has several jobs");
    expect(box).toHaveTextContent("Each job is measured separately on 41 material European events in this window. Each source is measured per purpose");
    const best = within(box).getByTestId("news-sources-best");
    const cards = Array.from(best.children);
    expect(cards).toHaveLength(12);
    expect(cards[0]).toHaveTextContent("Best for Europe-wide coverageAlpine Wire more reliablecovered 21/38 Europe events reported elsewhereNext: Isar Startup Post⚠ 24/41 benchmark events were first (or only) reported by Alpine Wire");
    expect(cards[3]).toHaveTextContent("Best for MunichIsar Startup Post");
    expect(cards[9]).toHaveTextContent("Best for FranceCOLLECTING DATAneeds ≥ 8 France events reported by other sources, and a source covering ≥ 3 of them");
    expect(within(box).getByTestId("news-sources-bias")).toHaveTextContent(
      "How fair is this benchmark? 14 of 41 material events were reported by two or more sources.24/41 benchmark events were first (or only) reported by Alpine Wire — recall is measured leave-one-out, but the event universe itself leans on that sourcethe benchmark is the union of Project Zero's monitored feeds",
    );
    const missing = within(box).getByTestId("news-sources-missing");
    expect(missing).toHaveTextContent("Being tested by the source network: Harbour Post PROBATION Lakeside Tech DISCOVERED — decide in System health → New sources.");
    expect(Array.from(missing.querySelectorAll("li")).map((li) => li.textContent)).toEqual([
      "Harbour Post — seen on 3 material event(s) handed to source network",
      "startupdb.example — seen on 2 material event(s) (startup database, not a news source)",
      "Lakeside Tech — seen on 1 material event(s) (needs 3 before it becomes a candidate)",
    ]);
    expect(within(box).getByTestId("news-sources-declining")).toHaveTextContent(
      "Declining sourcesChannel Tech Review: 2 failed fetches in a row (rate limited); relevance fell from 21% to 9% in this window",
    );
    const rows = within(box).getAllByTestId("news-source-row");
    expect(rows.map((r) => r.querySelector("b")!.textContent)).toEqual([
      "Alpine Wire",
      "Isar Startup Post",
      "Channel Tech Review",
      "Swiss deal ticker",
      "Baltic Founders",
      "Ledger Gazette",
    ]);
    expect(rows[1]).toHaveTextContent("Isar Startup Postactiveregional intelligenceearly signalMunich · 96 articles · more reliable");
    expect(rows[1]).toHaveTextContent("Best use: regional intelligence (covered 9/14 Munich events reported elsewhere); early signal");
    expect(rows[1]).toHaveTextContent("· Not designed for: Europe-wide recall — it is a Munich source by design");
    expect(rows[4]).toHaveTextContent("Best use: Collecting data — hypothesis to test: covers Baltic and Finnish seed rounds");
    expect(rows[5]).toHaveTextContent("externalconfirmation / authorityexternal benchmark · 3 articles · insufficient data");
    expect(box).toHaveTextContent("Last measured: 2026-11-12 07:00 (daily after the news refresh).");
  });

  it("a source's details, and the Swiss ticker's health UNKNOWN until System health is ported", async () => {
    const { box } = await sourcesTab();
    const row = (name: string) => within(box).getAllByTestId("news-source-row").find((r) => r.querySelector("b")!.textContent === name)!;
    const isar = row("Isar Startup Post");
    fireEvent.click(within(isar).getByRole("button", { name: "Details" }));
    const d = within(isar).getByTestId("news-source-detail");
    expect(Array.from(d.querySelectorAll("li")).map((li) => li.textContent)).toEqual([
      "Coverage (of events other sources reported): Europe 36% (12/33) · Germany 56% (9/16) · Munich 64% (9/14)",
      "Speed behind the first report: median 6.5 h · within 24 h 82% (9/11) · first 46% (5/11) (11 shared events, hour-precision)",
      "Early signal: 4 companies mentioned ≥ 14 days before their material event (median 52 days) — e.g. Vantor Kinetics 61 days, Fennick Audio 33 days, Trellis Mobility 21 days",
      "Unique value: 6 material events and 3 early companies no other source had",
      "Relevance: 33% (32/96) of its articles were material European events · noise 20% (19/96)",
      "Originality (headline-level estimate): syndicated copies 4% (4/96) · press-release markers 9% (9/96)",
      "Authority: specialist media · facts agreed 7, contradicted 1, open 1 (observed)",
      "Technical: healthy · fetched 28/28 runs (News run log)",
      "Hypothesis to test: sees Munich university spinouts weeks before national media",
    ]);
    fireEvent.click(within(isar).getByRole("button", { name: "Hide details" }));
    expect(within(isar).queryByTestId("news-source-detail")).toBeNull();

    const channel = row("Channel Tech Review");
    fireEvent.click(within(channel).getByRole("button", { name: "Details" }));
    expect(within(channel).getByTestId("news-source-detail")).toHaveTextContent(
      "Why degraded: 2 failed fetches in a row (rate limited); relevance fell from 21% to 9% in this window",
    );

    const swiss = row("Swiss deal ticker");
    fireEvent.click(within(swiss).getByRole("button", { name: "Details" }));
    expect(within(swiss).getByTestId("news-source-health-deferred")).toHaveTextContent("Technical: UNKNOWN (System health arrives with its port)");
    expect(within(swiss).getByTestId("news-source-detail")).toHaveTextContent(
      "Limits: articles come from the Deal Flow scan and are dated by scan day (speed is approximate)",
    );
  });

  it("'Re-measure now' is disabled with the 028c reason and sends nothing", async () => {
    const { server, box } = await sourcesTab();
    expectDeferred(within(box).getByRole("button", { name: "Re-measure now" }), NOT_PORTED.refresh);
    await settle();
    expect(server.writes()).toEqual([]);
  });

  it("each window is its own read; 30 days is mostly COLLECTING DATA", async () => {
    const { server, box } = await sourcesTab();
    fireEvent.click(within(box).getByRole("tab", { name: "30 days" }));
    await waitFor(() => expect(within(box).getByTestId("news-sources-bias")).toHaveTextContent("4 of 10 material events"));
    expect(server.gets()).toContain("/api/news/sources?window=30");
    const best = within(box).getByTestId("news-sources-best");
    expect(Array.from(best.children).map((c) => c.querySelector("div")!.textContent)).toEqual([
      "Best technical reliability",
      "Best for Europe-wide coverage · Germany · France · the UK · Switzerland · the Nordics · Munich · unique discovery · physical AI / deeptech",
      "Best for early signals",
      "Best for fact confirmation",
    ]);
    expect(within(box).getByTestId("news-sources-bias")).toHaveTextContent(
      "6/10 benchmark events were first (or only) reported by Alpine Wire — recall is measured leave-one-out, but the event universe itself leans on that source",
    );
    expect(within(box).getByTestId("news-sources-missing")).toHaveTextContent("No unmonitored publication shows up repeatedly yet.");
    expect(within(box).getByTestId("news-sources-missing")).not.toHaveTextContent("Being tested by the source network");
    fireEvent.click(within(box).getByRole("tab", { name: "180 days" }));
    await waitFor(() => expect(within(box).getByTestId("news-sources-bias")).toHaveTextContent("22 of 66 material events"));
    expect(within(box).getByTestId("news-sources-best")).toHaveTextContent("Best for SwitzerlandSwiss deal ticker");
    fireEvent.click(within(box).getByRole("tab", { name: "All time" }));
    await waitFor(() => expect(within(box).getByTestId("news-sources-bias")).toHaveTextContent("31 of 90 material events"));
    expect(server.gets().filter((p) => p.startsWith("/api/news/sources"))).toEqual([
      "/api/news/sources?window=90",
      "/api/news/sources?window=30",
      "/api/news/sources?window=180",
      "/api/news/sources?window=all",
    ]);
    expect(server.writes()).toEqual([]);
  });
});

describe("News & Learning — empty and failing", () => {
  it("an empty data folder: every section says what it is waiting for", async () => {
    fakeServer({ news: emptyNews, weekly: emptyWeekly, refreshStatus: () => refreshStatus("never") });
    await opened();
    expect(screen.getByTestId("news-concept")).toHaveTextContent("VC concept of the dayWhat does an accelerator signal?"); // the day's concept by ordinal
    expect(screen.getByText("One thing to notice earlier next time").parentElement).toHaveTextContent(
      "Once a story has a backcast (what signals existed before it), its lesson appears here.",
    );
    expect(screen.getByTestId("news-vs")).toHaveTextContent("0 caught early · 0 known late · 0 missed · 0 historical0 noise and 0 minor stories");
    expect(screen.getByTestId("news-vs")).not.toHaveTextContent("median lead");
    for (const [tab, key] of [
      ["Today", "today"],
      ["All stories", "all"],
      ["Caught early", "caught"],
      ["Misses", "misses"],
      ["Historical cases", "historical"],
      ["My companies", "mine"],
    ] as const) {
      open(tab);
      expect(screen.getByText(EMPTY[key])).toBeInTheDocument();
    }
    open("What's moving");
    expect(screen.getByText(THEMES_EMPTY)).toBeInTheDocument();
    expect(screen.getByTestId("news-footer")).toHaveTextContent("Last refresh: not yet. Project Zero started on 27 Sept 2026.");
  });

  it("a failed read shows the error with a retry", async () => {
    let fail = true;
    fakeServer({ news: () => (fail ? { status: 500, body: { ok: false, error: "News could not be read" } } : emptyNews()) });
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("News could not be read");
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByTestId("news-concept")).toBeInTheDocument();
  });

  it("only the refresh controls stay deferred (028c); the decisions are enabled and nothing is sent without a click", async () => {
    const server = fakeServer();
    await opened();
    const off = () => Array.from(document.querySelectorAll<HTMLElement>('[aria-disabled="true"]'));
    open("All stories");
    for (const s of stories()) fireEvent.click(within(s).getByRole("button", { name: /^(Backcast & sources|Sources & learning)$/ }));
    expect(off().map((e) => [e.textContent, e.getAttribute("title")])).toEqual([["Refresh news", NOT_PORTED.refresh]]);
    expect(Object.keys(NOT_PORTED)).toEqual(["refresh", "health"]); // the 028b reason is gone
    const enabled = (name: string) => screen.getAllByRole("button", { name }).filter((b) => !b.hasAttribute("aria-disabled") && !(b as HTMLButtonElement).disabled);
    expect(enabled("Confirm outcome")).toHaveLength(1);
    expect(enabled("Reject")).toHaveLength(1);
    expect(enabled("Not enough evidence")).toHaveLength(1);
    expect(enabled("Audit this miss")).toHaveLength(1); // Brightwell Bio
    expect(enabled("Add an early signal")).toHaveLength(4); // Vantor Kinetics, Quillon Labs, Brightwell Bio, Halvard Robotics
    for (const el of off()) expectDeferred(el, el.getAttribute("title")!);
    open("News sources");
    await screen.findByTestId("news-sources-best");
    expect(off().map((e) => e.textContent)).toEqual(["Refresh news", "Re-measure now"]);
    for (const el of off()) expectDeferred(el, el.getAttribute("title")!);
    await settle();
    expect(server.writes()).toEqual([]);
    expect(server.calls.every((c) => c.method === "GET")).toBe(true);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

/* ------------------------------------------------------------------ the decisions (028b) */

const VANTOR = "nw-3f9a1c0b7d2e";
const BRIGHTWELL = "nw-1e8b5a6c4d90";

/** The page with Validation's read in the cache, to see whether a write makes it stale. */
async function openedWithValidation() {
  const r = await opened();
  r.qc.setQueryData([VALIDATION, {}], { cached: true });
  const validationStale = () => r.qc.getQueryState([VALIDATION, {}])?.isInvalidated;
  expect(validationStale()).toBe(false);
  return { ...r, validationStale };
}

/** The server's next news answer after a write: the story carries the decision. */
function after(id: string, patch: Partial<Story>): NewsPayload {
  const d = news();
  for (const list of [d.today, d.stories, d.caught_early, d.known_late, d.misses, d.historical, d.my_companies])
    for (const s of list) if (s.event_id === id) Object.assign(s, patch);
  return d;
}

describe("News & Learning — the outcome proposal", () => {
  it("Confirm outcome takes two clicks; then one POST, the old toast, and News and Validation are read again", async () => {
    let n = 0;
    const server = fakeServer({ news: () => (++n === 1 ? news() : after(VANTOR, { outcome_decision: "confirm" })) });
    const { validationStale } = await openedWithValidation();
    const p = within(card("Vantor Kinetics")).getByTestId("news-outcome-proposal");
    const confirm = within(p).getByRole("button", { name: "Confirm outcome" });
    fireEvent.click(confirm);
    expect(confirm).toHaveTextContent("Click again to confirm — records a verified outcome in Validation");
    expect(confirm).toHaveAttribute("data-armed", "true");
    await settle();
    expect(server.posts()).toEqual([]); // the first click only arms it
    fireEvent.click(confirm);
    expect(await screen.findByText("Recorded")).toBeInTheDocument();
    expect(server.posts()).toEqual([{ method: "POST", path: "/api/news/outcome", body: { event_id: VANTOR, decision: "confirm" } }]);
    await waitFor(() => expect(server.reads()).toBe(2));
    expect(validationStale()).toBe(true);
    await waitFor(() => expect(within(card("Vantor Kinetics")).queryByTestId("news-outcome-proposal")).toBeNull());
  });

  it("Reject and Not enough evidence post their decision; News and Validation are read again, as the old page did", async () => {
    const server = fakeServer();
    const { validationStale } = await openedWithValidation();
    const p = () => within(card("Vantor Kinetics")).getByTestId("news-outcome-proposal");
    fireEvent.click(within(p()).getByRole("button", { name: "Reject" }));
    expect(await screen.findByText("Recorded")).toBeInTheDocument();
    await waitFor(() => expect(server.reads()).toBe(2));
    fireEvent.click(within(p()).getByRole("button", { name: "Not enough evidence" }));
    await waitFor(() => expect(server.reads()).toBe(3));
    expect(server.posts()).toEqual([
      { method: "POST", path: "/api/news/outcome", body: { event_id: VANTOR, decision: "reject" } },
      { method: "POST", path: "/api/news/outcome", body: { event_id: VANTOR, decision: "not_enough" } },
    ]);
    expect(validationStale()).toBe(true); // the old page re-read Validation after every decision
  });

  it("an `already` answer (the event was confirmed before) is a success like any other, as before", async () => {
    const server = fakeServer({ outcome: () => writeAnswer("already") });
    await opened();
    fireEvent.click(within(within(card("Vantor Kinetics")).getByTestId("news-outcome-proposal")).getByRole("button", { name: "Reject" }));
    expect(await screen.findByText("Recorded")).toBeInTheDocument();
    expect(screen.queryByText(/^✕/)).toBeNull();
    expect(server.posts()).toEqual([{ method: "POST", path: "/api/news/outcome", body: { event_id: VANTOR, decision: "reject" } }]);
    await waitFor(() => expect(server.reads()).toBe(2));
  });

  it("a refusal (400) is the failure toast with the old text; nothing is read again", async () => {
    const server = fakeServer({ outcome: () => ({ status: 400, body: { ok: false, error: "this news event cannot become an outcome" } }) });
    const { validationStale } = await openedWithValidation();
    const confirm = within(within(card("Vantor Kinetics")).getByTestId("news-outcome-proposal")).getByRole("button", { name: "Confirm outcome" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(await screen.findByText("✕ Recording the outcome failed — this news event cannot become an outcome")).toBeInTheDocument();
    expect(server.posts()).toHaveLength(1);
    await settle();
    expect(server.reads()).toBe(1);
    expect(validationStale()).toBe(false);
    expect(within(card("Vantor Kinetics")).getByTestId("news-outcome-proposal")).toBeInTheDocument();
  });
});

describe("News & Learning — Audit this miss", () => {
  it("posts the event alone; the old toast; News and Validation are read again and the button gives way to 'miss audit recorded'", async () => {
    let n = 0;
    const server = fakeServer({ news: () => (++n === 1 ? news() : after(BRIGHTWELL, { audit_id: "au-20261112-brightwell-bio" })) });
    const { validationStale } = await openedWithValidation();
    open("Misses");
    fireEvent.click(within(card("Brightwell Bio")).getByTestId("news-audit"));
    expect(await screen.findByText("Miss audit created in Validation (prefilled)")).toBeInTheDocument();
    expect(server.posts()).toEqual([{ method: "POST", path: "/api/news/audit_miss", body: { event_id: BRIGHTWELL } }]);
    await waitFor(() => expect(server.reads()).toBe(2));
    expect(validationStale()).toBe(true);
    await waitFor(() => expect(within(card("Brightwell Bio")).queryByTestId("news-audit")).toBeNull());
    expect(card("Brightwell Bio")).toHaveTextContent("miss audit recorded");
  });

  it("a refusal (400) is the failure toast; nothing is read again", async () => {
    const server = fakeServer({ auditMiss: () => ({ status: 400, body: { ok: false, error: "no such news event with a named company" } }) });
    await opened();
    open("Misses");
    fireEvent.click(within(card("Brightwell Bio")).getByTestId("news-audit"));
    expect(await screen.findByText("✕ Creating the miss audit failed — no such news event with a named company")).toBeInTheDocument();
    expect(server.posts()).toHaveLength(1);
    await settle();
    expect(server.reads()).toBe(1);
    expect(within(card("Brightwell Bio")).getByTestId("news-audit")).toBeInTheDocument();
  });
});

describe("News & Learning — Add an early signal", () => {
  function fields(d: HTMLElement) {
    return {
      d,
      date: within(d).getByRole("textbox", { name: "Date (YYYY, YYYY-MM or YYYY-MM-DD)" }),
      text: within(d).getByRole("textbox", { name: "What was visible" }),
      url: within(d).getByRole("textbox", { name: "Source URL" }),
      family: within(d).getByRole("combobox", { name: "Signal family" }),
      kind: within(d).getByRole("combobox", { name: "Knowable at the time?" }),
      add: within(d).getByRole("button", { name: "Add" }),
    };
  }
  function form(company = "Vantor Kinetics") {
    const c = card(company);
    fireEvent.click(within(c).getByRole("button", { name: /^(Backcast & sources|Sources & learning)$/ }));
    fireEvent.click(within(c).getByRole("button", { name: "Add an early signal" }));
    return fields(dialog());
  }

  it("the old form: its help, fields, placeholders, defaults and options; Add starts disabled", async () => {
    fakeServer();
    await opened();
    const f = form();
    expect(within(f.d).getByRole("heading", { name: "Add an early signal" })).toBeInTheDocument();
    expect(f.d).toHaveTextContent(
      "A public signal that existed BEFORE the story, with its source. Mark honestly whether it was knowable then, or only important in hindsight.",
    );
    expect(f.date).toHaveAttribute("placeholder", "2021-06");
    expect(f.url).toHaveAttribute("placeholder", "https://…");
    expect(f.date).toHaveValue("");
    expect(f.text).toHaveValue("");
    expect(f.family).toHaveValue("university_lab");
    expect(f.kind).toHaveValue("known_early_signal");
    expect(Array.from((f.family as HTMLSelectElement).options).map((o) => [o.value, o.textContent])).toEqual(
      news().signal_families.map((x) => [x, x.replace(/_/g, " ")]),
    );
    expect(Array.from((f.kind as HTMLSelectElement).options).map((o) => [o.value, o.textContent])).toEqual([
      ["known_early_signal", "Yes — a known early signal"],
      ["in_retrospect", "No — only clear in retrospect"],
    ]);
    expect(f.add).toBeDisabled();
  });

  it("Add needs a date and an http URL — nothing is sent before; then the exact body, the toast, the form closes and News is read again", async () => {
    const server = fakeServer();
    const { validationStale } = await openedWithValidation();
    const f = form();
    type(f.date, "2026-06");
    expect(f.add).toBeDisabled();
    type(f.url, "meetups.example/munich-robotics-june");
    expect(f.add).toBeDisabled(); // not an http URL
    fireEvent.click(f.add);
    type(f.date, "");
    type(f.url, "https://meetups.example/munich-robotics-june");
    expect(f.add).toBeDisabled(); // no date
    fireEvent.click(f.add);
    await settle();
    expect(server.posts()).toEqual([]);

    type(f.date, "2026-06");
    type(f.text, "Vantor Kinetics demo at a Munich robotics meetup");
    type(f.family, "event");
    type(f.kind, "in_retrospect");
    expect(f.add).toBeEnabled();
    fireEvent.click(f.add);
    expect(await screen.findByText("Signal added to the backcast")).toBeInTheDocument();
    expect(server.posts()).toEqual([
      {
        method: "POST",
        path: "/api/news/backcast",
        body: {
          date: "2026-06",
          text: "Vantor Kinetics demo at a Munich robotics meetup",
          url: "https://meetups.example/munich-robotics-june",
          family: "event",
          kind: "in_retrospect",
          event_id: VANTOR,
        },
      },
    ]);
    expect(Object.keys(server.posts()[0].body!)).toEqual(["date", "text", "url", "family", "kind", "event_id"]); // the old key order
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(server.reads()).toBe(2));
    expect(validationStale()).toBe(false); // a backcast writes no Validation row
  });

  it("the defaults are posted as they are, and the body names the card's own event", async () => {
    const server = fakeServer();
    await opened();
    open("Misses");
    const f = form("Brightwell Bio");
    type(f.date, "2026");
    type(f.url, "http://grants.example/2026");
    fireEvent.click(f.add);
    await screen.findByText("Signal added to the backcast");
    expect(server.posts()).toEqual([
      { method: "POST", path: "/api/news/backcast", body: { ...SIGNAL_FORM, date: "2026", url: "http://grants.example/2026", event_id: BRIGHTWELL } },
    ]);
  });

  it("a refusal (400) is the failure toast; the form stays open with what was typed; nothing is read again", async () => {
    const server = fakeServer({ backcast: () => ({ status: 400, body: { ok: false, error: "date as YYYY, YYYY-MM or YYYY-MM-DD" } }) });
    await opened();
    const f = form();
    type(f.date, "June 2026");
    type(f.url, "https://meetups.example/munich-robotics-june");
    fireEvent.click(f.add);
    expect(await screen.findByText("✕ Adding the early signal failed — date as YYYY, YYYY-MM or YYYY-MM-DD")).toBeInTheDocument();
    expect(server.posts()).toHaveLength(1);
    expect(dialog()).toBeInTheDocument();
    expect(f.date).toHaveValue("June 2026");
    await settle();
    expect(server.reads()).toBe(1);
  });

  it("opening and closing (✕ or Escape) writes nothing; reopening keeps what was typed, as before", async () => {
    const server = fakeServer();
    await opened();
    const f = form();
    type(f.date, "2026-06");
    type(f.url, "https://meetups.example/munich-robotics-june");
    fireEvent.click(within(f.d).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(within(card("Vantor Kinetics")).getByRole("button", { name: "Add an early signal" }));
    const again = fields(dialog());
    expect(again.date).toHaveValue("2026-06");
    expect(again.url).toHaveValue("https://meetups.example/munich-robotics-june");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    await settle();
    expect(server.writes()).toEqual([]);
  });
});

describe("News & Learning — Codex H-253: a confirm refreshes the cached Sources windows", () => {
  it("opens Sources, confirms a story, returns to the same window within its freshness period and sees the new benchmark", async () => {
    let reads = 0;
    const server = fakeServer({
      sources: (w) => ({ ...sources(w as Window), benchmark_events: ++reads === 1 ? 11 : 12 }),
      news: () => news(),
    });
    await opened();
    open("News sources");
    const box = await screen.findByTestId("news-sources");
    await waitFor(() => expect(box).toHaveTextContent("separately on 11 material European events"));
    open("Today");
    const confirm = within(within(card("Vantor Kinetics")).getByTestId("news-outcome-proposal")).getByRole("button", { name: "Confirm outcome" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(await screen.findByText("Recorded")).toBeInTheDocument();
    open("News sources"); // well within the 60 s freshness period: only the invalidation makes it read again
    await waitFor(() => expect(screen.getByTestId("news-sources")).toHaveTextContent("separately on 12 material European events"));
    expect(server.gets().filter((p) => p === "/api/news/sources?window=90")).toHaveLength(2);
  });
});

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ALL_ITEMS } from "@/app/nav";
import { NOT_PORTED } from "@/features/deal-flow/model/deferred";
import { FIND_LINK } from "./components/Machine";
import { NOTHING } from "./model/desk";
import { home, homeQuiet, homeVariants, NOW, today } from "./test/fixtures";
import { fakeServer, renderPage } from "./test/server";

const GREETING = "Good morning, Smooth Operator.";
const region = (name: string) => screen.getByRole("region", { name });
const machine = () => screen.getByTestId("desk-machine") as HTMLDetailsElement;
const reviewQueue = () => screen.getByRole("button", { name: "Open Agent Review Queue" });
const hrefs = () => Array.from(document.querySelectorAll("a[href]")).map((a) => a.getAttribute("href") ?? "");

async function opened(routes: Parameters<typeof fakeServer>[0] = {}) {
  const server = fakeServer(routes);
  const view = renderPage();
  await screen.findByRole("heading", { level: 1, name: GREETING });
  return { server, ...view };
}

/** The desk with the three later reads arrived (the missions come from Today, the tiles from Conviction). */
async function settled(routes: Parameters<typeof fakeServer>[0] = {}) {
  const r = await opened(routes);
  await waitFor(() => expect(screen.getAllByTestId("desk-job")).toHaveLength(5));
  await waitFor(() => expect(screen.getByTestId("desk-pulse")).toHaveTextContent("2 source health warnings"));
  return r;
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Investment Desk — the page", () => {
  it("is a ported nav view at /", () => {
    expect(ALL_ITEMS.find((i) => i.legacyView === "home")).toMatchObject({ path: "/", label: "Investment Desk", page: expect.anything() });
  });

  it("loads home and the inbox first, the other three once the inbox is there — never the deferred review queue, never a write", async () => {
    const server = fakeServer({ holdInbox: true });
    renderPage();
    expect(await screen.findByText("Loading the desk…")).toBeInTheDocument();
    await waitFor(() => expect(server.gets()).toEqual(expect.arrayContaining(["/api/home", "/api/deal-flow/inbox"])));
    expect([...server.gets()].sort()).toEqual(["/api/deal-flow/inbox", "/api/home"]);
    server.release();
    await screen.findByRole("heading", { level: 1, name: GREETING });
    await waitFor(() => expect(server.gets()).toHaveLength(5));
    expect(server.gets().slice(2).sort()).toEqual(["/api/conviction/pipeline", "/api/sources", "/api/today"]);
    expect(server.gets().some((p) => p.includes("review"))).toBe(false);
    expect(server.writes()).toEqual([]);
  });

  it("the brief: the context line, the greeting in role wording, the one situational sentence", async () => {
    await settled();
    expect(screen.getByTestId("desk-context")).toHaveTextContent(/^Friday, 13 Nov · 09:30$/);
    expect(screen.getByTestId("desk-summary")).toHaveTextContent(
      "Deal flow is active: 7 missions need judgment, 4 Manager decisions are blocked and 2 founders hold the ball.",
    );
    expect(document.body.textContent).not.toMatch(/\b(Omar|Mohamed)\b/);
  });

  it("the flow graphic: four stages from the desk's own counts", async () => {
    await settled();
    const flow = screen.getByTestId("desk-flow");
    expect(flow).toHaveAttribute("data-signature", "data");
    expect(within(flow).getByRole("img")).toHaveAttribute(
      "aria-label",
      "Today's operating flow: Signals 8 (new · 14 days) → Review 7 (need you) → Manager 4 (blocked) → Decision 10 (in Conviction)",
    );
    expect(Array.from(flow.querySelectorAll("li")).map((li) => li.textContent)).toEqual(["8Signalsnew · 14 days", "7Reviewneed you", "4Managerblocked", "10Decisionin Conviction"]);
    expect(flow.querySelector("figcaption")).toHaveTextContent("Today's operating flow · signals to decisions");
  });

  it("the four tiles: counts and where they open", async () => {
    await settled();
    const tiles = within(screen.getByRole("list", { name: "Orientation" })).getAllByRole("listitem");
    expect(tiles.map((t) => [t.textContent, t.getAttribute("href"), t.dataset.tone])).toEqual([
      ["7Priority missions", "/today", "blue"],
      ["4Manager decisions", "/conviction?seg=gated", "cocoa"],
      ["2Awaiting founder reply", "/conviction", "slate"],
      ["8Candidates to decide", "/deal-flow", "forest"],
    ]);
  });

  it("Priority missions: five rows, each with its reason, top unknown, state and one link; the rest one click away", async () => {
    await settled();
    const card = region("Priority missions");
    expect(card).toHaveAttribute("data-testid", "desk-missions");
    const rows = within(card).getAllByTestId("desk-job");
    expect(rows.map((r) => r.querySelector("b")?.textContent)).toEqual(["Halvorsen Robotics", "Ilse Marquardt", "Tessaro Grid", "Nordvik Materials", "Review 10"]);
    expect(rows[0]).toHaveTextContent("Two plant pilots converted to paid contracts in October; the seed…");
    expect(rows[0]).toHaveTextContent("Top unknownCore facts verified");
    expect(rows[0]).toHaveTextContent("Your move");
    expect(rows[2]).toHaveTextContent("Unverified: traction");
    expect(rows[2]).toHaveTextContent("Case prepared");
    expect(rows.map((r) => within(r).getByRole("link").getAttribute("href"))).toEqual([
      "/conviction?company=halvorsen-robotics",
      "/founder-calls",
      "/conviction?company=tessaro-grid",
      "/conviction?company=nordvik-materials",
      "/deal-flow?filter=triage&route=NEEDS_MOHAMED",
    ]);
    const more = within(card).getByRole("link", { name: /View remaining 2/ });
    expect(more).toHaveAttribute("href", "/today");
  });

  it("the due follow-ups follow Today's missions (shown when Today has none)", async () => {
    const t = today();
    t.actions = [];
    await opened({ today: () => t });
    await waitFor(() => expect(screen.getAllByTestId("desk-job")).toHaveLength(2));
    const [dated, undated] = screen.getAllByTestId("desk-job");
    expect(dated).toHaveTextContent("Ilse MarquardtSend the pilot data you promisedTop unknowndue 2026-11-12Follow-upOpen");
    expect(within(dated).getByRole("link")).toHaveAttribute("href", "/network?person=p-ilse-marquardt");
    expect(undated).toHaveTextContent("no date set");
    expect(within(region("Priority missions")).queryByRole("link", { name: /View remaining/ })).toBeNull();
  });

  it("Manager decisions: the first three gated companies, the twin overlap or a possible conflict, then View all", async () => {
    await settled();
    const card = region("Manager decisions");
    const items = within(card).getAllByRole("listitem");
    expect(items.map((li) => li.textContent?.trim())).toEqual([
      "Brightwell AnalyticsPossible overlap with Fennwick PayDecision dueOpen",
      "Corvane SystemsPossible portfolio conflictDecision dueOpen",
      "Lumora HealthPossible portfolio conflictDecision dueOpen",
    ]);
    expect(within(items[0]).getByRole("link")).toHaveAttribute("href", "/conviction?company=brightwell-analytics");
    expect(within(card).getByRole("link", { name: /View all 4/ })).toHaveAttribute("href", "/conviction?seg=gated");
  });

  it("the best opportunity: the server's pick, verified, its thesis, state, signal and move; the name and Open the case open it", async () => {
    const { router } = await settled();
    const best = screen.getByTestId("desk-best");
    expect(within(best).getByRole("heading", { level: 2 })).toHaveTextContent("Best opportunity");
    expect(best).toHaveTextContent("Halvorsen RoboticsVerified");
    expect(best).toHaveTextContent("Autonomous palletising cells for mid-sized food plants");
    expect(best).toHaveTextContent("StateReady for outreach");
    expect(best).toHaveTextContent("SignalVerified 78");
    expect(best).toHaveTextContent("Your move: Ask Manager whether the plant pilots overlap the portfolio");
    expect(within(best).getByRole("link", { name: /Open the case/ })).toHaveAttribute("href", "/conviction?company=halvorsen-robotics");
    expect(best.querySelector('[data-decorative="true"]')).not.toBeNull();
    fireEvent.click(within(best).getByRole("button", { name: "Halvorsen Robotics" }));
    expect(await screen.findByTestId("landed")).toHaveTextContent("/conviction?company=halvorsen-robotics");
    await router.navigate("/");
  });

  it("a provisional best opportunity without a move, and an event without a date", async () => {
    await settled({ home: homeVariants });
    const best = screen.getByTestId("desk-best");
    expect(best).toHaveTextContent("Tessaro GridProvisional");
    expect(best).toHaveTextContent("StateCase prepared");
    expect(best).toHaveTextContent("SignalProvisional 66 → Radar high-confidence if verified ≥ 65");
    expect(best).not.toHaveTextContent("Your move");
    const ev = screen.getByTestId("desk-event");
    expect(within(ev).getByRole("heading", { level: 2 })).toHaveTextContent("Upcoming event");
    expect(ev.querySelector("[class*=dateTile] svg")).not.toBeNull(); // the calendar icon instead of a date
    expect(ev).toHaveTextContent("Copper Valley Founders NightTBA");
    expect(ev).not.toHaveTextContent("Register by");
    expect(within(ev).queryByRole("link", { name: /Details/ })).toBeNull();
    expect(within(ev).getByRole("link", { name: /Plan/ })).toHaveAttribute("href", "/events");
  });

  it("no best opportunity, no event, nothing waiting: the quiet lines", async () => {
    const t = today();
    t.actions = [];
    await opened({ home: homeQuiet, today: () => t, pipeline: () => ({ signals: [] }) });
    await waitFor(() => expect(screen.getByTestId("desk-pulse")).toHaveTextContent("2 source health warnings"));
    expect(screen.getByTestId("desk-best")).toHaveTextContent("No clear leader yet — no Conviction company stands out on the current evidence.");
    expect(screen.getByTestId("desk-event")).toHaveTextContent("No dated upcoming event — scan sources in Events.");
    expect(region("Priority missions")).toHaveTextContent("Nothing waits on your judgment.");
    expect(region("Manager decisions")).toHaveTextContent("Nothing waits on the Manager.");
    expect(screen.getByTestId("desk-summary")).toHaveTextContent(NOTHING);
  });

  it("the upcoming event: this weekend, the date tile, city and start, the reason, Plan, the deadline and the link", async () => {
    await settled();
    const ev = screen.getByTestId("desk-event");
    expect(within(ev).getByRole("heading", { level: 2 })).toHaveTextContent("This weekend");
    expect(ev.querySelector("[class*=dateTile]")).toHaveTextContent("Nov14Sat");
    expect(ev).toHaveTextContent("Alpine Deep Tech SummitZurich · 2026-11-14Three Conviction founders speak on the robotics track");
    expect(ev).toHaveTextContent("Register by 2026-11-13");
    const details = within(ev).getByRole("link", { name: /Details/ });
    expect(details).toHaveAttribute("href", "https://example.org/alpine-deep-tech-summit");
    expect(details).toHaveAttribute("target", "_blank");
  });

  it("promising signals: the best six, tier, themes and score; a row opens the candidate", async () => {
    await settled();
    const card = region("Promising signals");
    const rows = within(card).getAllByRole("button");
    expect(rows.map((b) => b.textContent)).toEqual([
      "Pre-companyQuillon RoboticsRobotics & automation · Climate & energyF 82",
      "AnnouncementTarnhelm BioDigital healthF 74",
      "GrantMarlowe GridClimate & energyF 74",
      "AnnouncementIlvara SystemsFintech · unmapped-themeF 60",
      "GrantCorrib HealthDigital healthF 55",
      "Pre-companySorrel Opticsatt 8",
    ]);
    expect(within(rows[5]).getByText("att 8")).toHaveAttribute("title", expect.stringMatching(/^attention 8 = freshness 4 \(source date 2026-10-18\)/));
    expect(within(card).getByRole("link", { name: /See all signals/ })).toHaveAttribute("href", "/deal-flow");
    fireEvent.click(rows[0]);
    expect(await screen.findByTestId("landed")).toHaveTextContent("/deal-flow?candidate=c-0101");
  });

  it("recent activity: the newest four, a time or a day each; an item opens where it happened", async () => {
    await settled();
    const card = region("Recent activity");
    const items = within(card).getAllByRole("button");
    expect(items.map((b) => b.textContent)).toEqual([
      "22:18Tarnhelm Bio surfacedvia Northfield Startup Press",
      "22:17Marlowe Grid surfacedvia Copper Valley Awards",
      "22:16Quillon Robotics surfacedvia Isarwerk Venture Lab (official)",
      "11 NovLumora Health sent to Managerfeedback logged",
    ]);
    expect(within(card).getByRole("link", { name: /See the full signal flow/ })).toHaveAttribute("href", "/deal-flow");
    fireEvent.click(items[3]);
    expect(await screen.findByTestId("landed")).toHaveTextContent(/^\/conviction$/);
  });

  it("the machine work, folded: the line, the pulse, the last scan and the five next actions in the old order", async () => {
    await settled();
    expect(machine().open).toBe(false);
    expect(machine().querySelector("summary")).toHaveTextContent("Machine work in progress5 new in the last scan · 3 analyses · 2 source warnings");
    expect(screen.getByTestId("desk-pulse").textContent).toBe(
      "6 new candidates2 pre-company signals3 research completed1 kept2 sent to Manager2 source health warnings",
    );
    expect(machine()).toHaveTextContent("Last scan 2026-11-12 22:15: 5 genuinely new (2 from pre-company channels) · 3 noise set aside.");
    const group = screen.getByRole("group", { name: "Next actions" });
    expect(within(group).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Find New Candidates",
      "Open Deal Flow",
      "Open Agent Review Queue",
      "Open Conviction",
      "Compose weekly update",
    ]);
  });

  it.each([
    ["Find New Candidates", FIND_LINK],
    ["Open Deal Flow", "/deal-flow"],
    ["Open Conviction", "/conviction"],
  ])("%s navigates to %s — nothing is posted", async (name, to) => {
    const { server } = await settled();
    fireEvent.click(screen.getByRole("button", { name }));
    expect(await screen.findByTestId("landed")).toHaveTextContent(new RegExp(`^${to.replace(/[?]/g, "\\?")}$`));
    expect(server.writes()).toEqual([]);
  });

  it("the Agent Review Queue is deferred: disabled, described by the visible note below the controls; a click does nothing", async () => {
    const { server } = await settled();
    const btn = reviewQueue();
    expect(btn).toHaveAttribute("aria-disabled", "true");
    expect(btn).toHaveAttribute("data-deferred");
    expect(btn).not.toBeDisabled(); // focusable, named, inert
    const note = screen.getByTestId("desk-review-note");
    expect(note).toHaveTextContent(/^The Agent Review Queue arrives with the analysis port$/);
    expect(note.textContent).toBe(NOT_PORTED.reviewQueue);
    expect(note).not.toHaveClass("sr-only");
    expect(btn.getAttribute("aria-describedby")).toBe(note.id);
    expect(btn).toHaveAccessibleDescription(NOT_PORTED.reviewQueue);
    // right below the controls, inside the machine body
    expect(screen.getByRole("group", { name: "Next actions" }).nextElementSibling).toBe(note);
    const before = server.calls.length;
    fireEvent.click(btn);
    fireEvent.keyDown(btn, { key: "Enter" });
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId("landed")).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: GREETING })).toBeInTheDocument();
    expect(server.calls.length).toBe(before);
  });

  it("the desk builds no review link anywhere", async () => {
    await settled();
    machine().open = true;
    const all = hrefs();
    expect(all.length).toBeGreaterThan(15);
    expect(all.filter((h) => h.includes("review=") || h.includes("filter=review"))).toEqual([]);
  });

  it("Compose weekly update opens Conviction's weekly drawer, which posts conviction/weekly", async () => {
    const { server } = await settled();
    fireEvent.click(screen.getByRole("button", { name: "Compose weekly update" }));
    const dlg = await screen.findByRole("dialog", { name: "Weekly Sourcing Update" });
    fireEvent.click(within(dlg).getByRole("button", { name: "Generate" }));
    expect(await within(dlg).findByTestId("weekly-text")).toHaveTextContent("Weekly Sourcing Update — invented week");
    expect(server.writes()).toEqual([{ method: "POST", path: "/api/conviction/weekly" }]);
  });

  it("a failing inbox: the desk shows home's parts and makes none of the later reads", async () => {
    const { server } = await opened({ inbox: () => ({ status: 500, body: { ok: false, error: "inbox unavailable" } }) });
    expect(screen.getByTestId("desk-best")).toHaveTextContent("Halvorsen Robotics");
    expect(screen.getByTestId("desk-event")).toHaveTextContent("Alpine Deep Tech Summit");
    expect(screen.getAllByTestId("desk-job")).toHaveLength(2); // the due follow-ups only
    expect(region("Promising signals")).toHaveTextContent("Nothing in the attention queue yet — Find New Candidates in Deal Flow.");
    expect(machine().querySelector("summary")).toHaveTextContent("6 new in the last scan · 0 analyses · 0 source warnings");
    expect([...server.gets()].sort()).toEqual(["/api/deal-flow/inbox", "/api/home"]);
  });

  it("a failing home read is the error box with Retry", async () => {
    fakeServer({ home: () => ({ status: 500, body: { ok: false, error: "The desk could not be computed" } }) });
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("The desk could not be computed");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
  });

  it("the old payload, key for key", () => {
    expect(Object.keys(home())).toEqual(["priority", "best_event", "due", "new_signals", "latest_signals", "omar", "progress", "watch", "weekday", "date"]);
  });
});

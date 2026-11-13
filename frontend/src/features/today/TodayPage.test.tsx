import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ALL_ITEMS } from "@/app/nav";
import { QUEUE_LINK, REVIEW_LINK } from "./components/Machine";
import type { TodayView } from "./model/types";
import { emptyDay, today, variants } from "./test/fixtures";
import { fakeServer, renderPage } from "./test/server";

const NOTE = "Triage routes and prepared cases are the imported snapshot until their runs are ported";
const RULES = "Deterministic ranking over existing state; nothing is sent, registered, scored or forwarded.";

const rows = () => screen.queryAllByTestId("today-action");
const missionRows = () => within(screen.getByTestId("today-list")).getAllByTestId("today-action");
const row = (type: string, n = 0) => rows().filter((r) => r.dataset.type === type)[n];
const openLink = (el: HTMLElement) => within(el).getByRole("link", { name: /^Open: / });
const machine = () => screen.getByTestId("today-triage") as HTMLDetailsElement;

async function opened(routes: Parameters<typeof fakeServer>[0] = {}) {
  const server = fakeServer(routes);
  const view = renderPage();
  await screen.findByRole("heading", { level: 1, name: "Today" });
  return { server, ...view };
}

/** The page with the pipeline joined (the tiles appear once it has arrived). */
async function joined(routes: Parameters<typeof fakeServer>[0] = {}) {
  const r = await opened(routes);
  await screen.findByRole("list", { name: "Orientation" });
  return r;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Today — the page", () => {
  it("is a ported nav view at /today", () => {
    expect(ALL_ITEMS.find((i) => i.legacyView === "today")).toMatchObject({ path: "/today", label: "Today", page: expect.anything() });
  });

  it("reads `today` and Conviction's pipeline once each, and writes nothing", async () => {
    const { server } = await joined();
    expect([...server.gets()].sort()).toEqual(["/api/conviction/pipeline", "/api/today"]);
    expect(server.writes()).toEqual([]);
  });

  it("the hero: the date, Today, the purpose line and the flow graphic from the real counts", async () => {
    await joined();
    expect(screen.getByTestId("today-date").textContent).toMatch(/^\w+day, \d{1,2} \w+ · \d{2}:\d{2}$/);
    expect(screen.getByText("Your daily brief for sourcing, investigation and decisions.")).toBeInTheDocument();
    const flow = screen.getByTestId("today-flow");
    expect(flow).toHaveAttribute("data-signature", "data");
    expect(within(flow).getByRole("img")).toHaveAttribute(
      "aria-label",
      "Today's flow: 487 signals handled by the machine → 5 missions for review → 2 decisions due",
    );
    const step = (s: string) => flow.querySelector(`text[data-step="${s}"]`)?.textContent;
    expect([step("signals"), step("missions"), step("decisions")]).toEqual(["487 handled", "5 missions", "2 decisions due"]);
  });

  it("the briefing and the four tiles (the dropped company is not counted)", async () => {
    await joined();
    expect(screen.getByTestId("today-brief")).toHaveTextContent(
      "Today's briefing5 priority missions · 1 Manager decision due · 1 event decisionHalvorsen Robotics — Two plant pilots converted to paid contracts in October; the seed…",
    );
    const tiles = within(screen.getByRole("list", { name: "Orientation" })).getAllByRole("link");
    expect(tiles.map((t) => [t.textContent, t.getAttribute("href")])).toEqual([
      ["9in Conviction", "/conviction"],
      ["1fully verified", "/conviction"],
      ["5missions", "#today-missions"],
      ["1Manager decision", "/conviction?seg=gated"],
    ]);
  });

  it("Missions: the companies and signals in the server's order, the first one featured, each with one Open link", async () => {
    await joined();
    expect(screen.getByRole("heading", { level: 2, name: "Missions" }).nextSibling).toHaveTextContent("5");
    expect(missionRows().map((r) => r.dataset.type)).toEqual(["CONTACT_FOUNDER", "PREPARE_FOUNDER_CALL", "CASE_READY", "REVIEW_VERIFICATION", "TRIAGE_REVIEW"]);
    expect(missionRows().map((r) => r.querySelector("article")?.dataset.featured ?? null)).toEqual(["true", null, null, null, null]);
    expect(missionRows().map((r) => [openLink(r).getAttribute("aria-label"), openLink(r).getAttribute("href")])).toEqual([
      ["Open: Halvorsen Robotics", "/conviction?company=halvorsen-robotics"],
      ["Open: Ilse Marquardt", "/founder-calls"],
      ["Open: Tessaro Grid", "/conviction?company=tessaro-grid"],
      ["Open: Nordvik Materials", "/conviction?company=nordvik-materials"],
      ["Open: Review 10", REVIEW_LINK],
    ]);
    expect(openLink(missionRows()[0])).toHaveAttribute("data-primary", "true");
    expect(missionRows().filter((r) => openLink(r).hasAttribute("data-primary"))).toHaveLength(1);
  });

  it("a mission row: name and score, the one-liner, why now, the biggest unknown, the state and the next move", async () => {
    await joined();
    const contact = row("CONTACT_FOUNDER");
    expect(within(contact).getByRole("heading", { level: 3 })).toHaveTextContent("Halvorsen Robotics78");
    expect(within(contact).getByTitle("Verified score")).toHaveTextContent("78");
    expect(contact.querySelector("article")).toHaveAttribute("data-accent", "neutral");
    expect(contact.querySelector("article")).toHaveAttribute("data-group", "company");
    for (const text of [
      "Autonomous palletising cells for mid-sized food plants",
      "Why now",
      "Two plant pilots converted to paid contracts in October; the seed…",
      "Biggest unknown",
      "Core facts verified",
      "State",
      "Your move",
      "Next move",
      "Contact the founder",
    ])
      expect(contact).toHaveTextContent(text);
    const kase = row("CASE_READY");
    expect(kase.querySelector("article")).toHaveAttribute("data-accent", "attention");
    expect(kase).toHaveTextContent("Unverified: traction");
    expect(kase).toHaveTextContent("Case prepared"); // the operator state from the prepared case
    expect(kase).toHaveTextContent("Prepare a founder call"); // the move, parsed from "Recommended next action:"
    const verify = row("REVIEW_VERIFICATION");
    expect(verify).toHaveTextContent("Verify Nordvik Materials (founders, traction)"); // decision e: never "1-click verification ready"
    expect(verify).toHaveTextContent("Unverified: founders, traction");
    expect(verify).toHaveTextContent("Verify the evidence");
    const call = row("PREPARE_FOUNDER_CALL");
    expect(within(call).getByRole("heading", { level: 3 })).toHaveTextContent(/^Ilse Marquardt$/); // no company joined: no score
    expect(call).not.toHaveTextContent("Biggest unknown");
    expect(call).toHaveTextContent("Prepare the call");
    const triage = row("TRIAGE_REVIEW");
    expect(triage.querySelector("article")).toHaveAttribute("data-group", "signal");
    expect(triage).toHaveTextContent("Your judgment, not the machine's");
    expect(triage).toHaveTextContent("Signal review");
    expect(triage).toHaveTextContent("Review the queue");
  });

  it("the details, folded: the full texts in role wording, the conflict and whether founder contact is appropriate", async () => {
    await joined();
    const details = (el: HTMLElement) => el.querySelector("details") as HTMLDetailsElement;
    for (const r of rows()) expect(details(r).open).toBe(false);
    expect(details(row("CONTACT_FOUNDER"))).toHaveTextContent(
      "DetailsReach out to Halvorsen RoboticsOn Radar (high, verified 78), conflict none, founders resolved.IMQ state: IMQ QUALIFIEDwhy-now trigger older than 90 daysYour next step: Write to the founder yourself — nothing is sent by Project Zero. · Project A conflict: none · founder contact appropriate",
    );
    expect(details(row("PREPARE_FOUNDER_CALL"))).toHaveTextContent(
      "Your next step: Do the follow-up you committed to (owner: you). · founder contact not yet appropriate",
    );
    expect(details(row("PREPARE_FOUNDER_CALL"))).not.toHaveTextContent("Project A conflict");
    const omar = details(row("ASK_OMAR_CONFLICT"));
    expect(omar).toHaveTextContent("Ask Manager about 3 possible portfolio conflict(s)");
    expect(omar).toHaveTextContent("One message to Manager listing them; record his answer on each company (Conviction → conflict).");
    expect(omar).toHaveTextContent("Lumora Health: known portfolio");
    expect(omar).toHaveTextContent("· Project A conflict: potential_conflict / unclear");
    expect(omar).not.toHaveTextContent("founder contact");
  });

  it("the segmented filter: All, Companies or Signals (only when both kinds exist); the feature mark is for All only", async () => {
    await joined();
    const seg = screen.getByRole("group", { name: "Mission filter" });
    const buttons = within(seg).getAllByRole("button");
    expect(buttons.map((b) => [b.textContent, b.getAttribute("aria-pressed")])).toEqual([
      ["All 5", "true"],
      ["Companies 4", "false"],
      ["Signals 1", "false"],
    ]);
    fireEvent.click(buttons[2]);
    expect(missionRows().map((r) => r.dataset.type)).toEqual(["TRIAGE_REVIEW"]);
    expect(missionRows()[0].querySelector("article")).not.toHaveAttribute("data-featured");
    expect(buttons[2]).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(buttons[1]);
    expect(missionRows()).toHaveLength(4);
    fireEvent.click(buttons[0]);
    expect(missionRows()).toHaveLength(5);
  });

  it("Manager decisions and Events: two sibling panels with their counts, rows and View all links", async () => {
    await joined();
    const ctx = screen.getByTestId("today-context");
    const mgr = within(ctx).getByRole("region", { name: "Manager decisions" });
    expect(mgr).toHaveTextContent("1 blocked until the Manager answers");
    expect(within(mgr).getByRole("link", { name: /View all/ })).toHaveAttribute("href", "/conviction?seg=gated");
    const m = row("ASK_OMAR_CONFLICT");
    expect(within(m).getByRole("heading", { level: 3 })).toHaveTextContent("3 possible portfolio conflict(s)");
    expect(m).toHaveTextContent("These companies cannot move until Manager / Project A confirms whether they are investable (some are,…");
    expect(m).toHaveTextContent("Decision due");
    expect(openLink(m)).toHaveAttribute("href", "/conviction");
    const ev = within(ctx).getByRole("region", { name: "Events" });
    expect(ev).toHaveTextContent("1 decide before the date");
    expect(within(ev).getByRole("link", { name: /View all/ })).toHaveAttribute("href", "/events");
    const e = row("EVENT_ACTION");
    expect(e.querySelector("[aria-hidden]")).toHaveTextContent("Nov15");
    expect(within(e).getByRole("heading", { level: 3 })).toHaveTextContent("Alpine Deep Tech Summit");
    expect(e).toHaveTextContent(/· Zurich/);
    expect(openLink(e)).toHaveAttribute("href", "/events");
  });

  it("the Machine work, folded: the counts, the exceptions, the triage buttons, the snapshot note and the footer", async () => {
    await joined();
    expect(machine().open).toBe(false);
    expect(machine().querySelector("summary")).toHaveTextContent("Machine workMachine487 handled · 129 researching · 331 watchingDetails");
    expect(screen.getByTestId("today-exceptions")).toHaveTextContent(
      "1 company needs your judgment · 2 founder calls worth preparing · 5 possible portfolio conflicts for Manager · 2 events worth deciding on · 10 machine proposals need your judgment",
    );
    expect(screen.getByTestId("today-exceptions")).not.toHaveTextContent("background job");
    for (const text of [
      "487 machine proposals handled",
      "14 need your judgment",
      "3 queued for case preparation",
      "129 in the machine research queue",
      "331 watched / deferred",
      "5 conflict-gated (Manager)",
      "5 calibration samples",
      "20 resurfaced by new evidence",
      "4 more wait beyond today’s budget of 10",
    ])
      expect(machine()).toHaveTextContent(text);
    expect(screen.getByTestId("triage-needs")).toHaveTextContent("14 need your judgment");
    expect(screen.getByTestId("triage-review")).toHaveTextContent("Review 10");
    expect(screen.getByTestId("today-snapshot")).toHaveTextContent(`${NOTE} (triage run 2026-11-12 23:05 · newest prepared case 2026-11-01 19:36).`);
    expect(screen.getByTestId("today-footer")).toHaveTextContent(
      `3 lower-priority action(s) not shown. ${RULES} Sources considered: pipeline 4 · calls 1 · events 2 · triage 2 · watch 1 · cases 1.`,
    );
  });

  it("the triage buttons are links: Review opens the compressed list, View queue the queue — nothing is posted", async () => {
    const { server, router } = await joined();
    fireEvent.click(screen.getByTestId("triage-review"));
    expect(await screen.findByTestId("landed")).toHaveTextContent(REVIEW_LINK);
    await router.navigate("/today");
    fireEvent.click(await screen.findByTestId("triage-queue"));
    expect(await screen.findByTestId("landed")).toHaveTextContent(QUEUE_LINK);
    expect(server.writes()).toEqual([]);
  });

  it("an Open link lands on its route: the verification card opens the company in Conviction", async () => {
    await joined();
    fireEvent.click(openLink(row("REVIEW_VERIFICATION")));
    expect(await screen.findByTestId("landed")).toHaveTextContent("/conviction?company=nordvik-materials");
  });

  it("the other branches: watch triggers, a waiting and a weak case, the triage conflict, a far event, no triage run", async () => {
    await joined({ today: variants });
    expect(rows().map((r) => r.dataset.type)).toEqual([
      "PREPARE_FOUNDER_CALL",
      "WATCH_TRIGGER",
      "CASE_READY",
      "WATCH_TRIGGER",
      "CASE_READY",
      "ASK_OMAR_CONFLICT",
      "EVENT_ACTION",
    ]);
    // every mission is a company: no filter
    expect(screen.queryByRole("group", { name: "Mission filter" })).toBeNull();
    const call = row("PREPARE_FOUNDER_CALL");
    expect(call).toHaveTextContent("Mirava Labs59");
    expect(call).toHaveTextContent("Unverified: traction");
    expect(call.querySelector("details")).toHaveTextContent(
      "Contact the founders: Mirava Labs" +
        "Provisional 74; founders and funding are verified — only traction is open, and traction is founder-answerable.missing: traction" +
        "Your next step: Decide whether to reach out — you send, Project Zero never does; record the outreach once sent (the traction questions are prepared). · Project A conflict: complementary · founder contact appropriate",
    );
    const [high, low] = [row("WATCH_TRIGGER", 0), row("WATCH_TRIGGER", 1)];
    expect(high.querySelector("article")).toHaveAttribute("data-accent", "progress");
    expect(high).toHaveTextContent("New intel");
    expect(high).toHaveTextContent("Review the change");
    expect(openLink(high)).toHaveAttribute("href", "/deal-flow?candidate=c-0412");
    expect(openLink(low)).toHaveAttribute("href", "/watchlist");
    expect(within(low).getByRole("heading", { level: 3 })).toHaveTextContent("Pellucid Optics");
    const [waiting, weak] = [row("CASE_READY", 0), row("CASE_READY", 1)];
    expect(waiting).toHaveTextContent("Awaiting founder");
    expect(waiting).toHaveTextContent("Await the founder's response");
    expect(waiting.querySelector("article")).toHaveAttribute("data-accent", "neutral");
    expect(weak).toHaveTextContent("Decide: watch or drop");
    expect(weak).toHaveTextContent("Case ready"); // a score-band state is not an operator state
    const omar = row("ASK_OMAR_CONFLICT");
    expect(within(omar).getByRole("heading", { level: 3 })).toHaveTextContent("1 new candidate(s) touch the Project…");
    expect(openLink(omar)).toHaveAttribute("href", "/deal-flow?filter=triage");
    expect(omar.querySelector("details")).toHaveTextContent("Fennick Pay: KNOWN_PORTFOLIO");
    expect(omar.querySelector("details")).toHaveTextContent("Do not contact; mention them to Manager, then accept or override in Deal Flow.");
    const ev = row("EVENT_ACTION");
    expect(ev.querySelector("[aria-hidden]")).toHaveTextContent("Nov24");
    expect(ev).toHaveTextContent(/· —/);
    expect(screen.getByTestId("today-flow").querySelector('text[data-step="signals"]')).toBeNull();
  });

  it("triage: null — the Machine line says working, no counts and no triage buttons; a failed section and the Omars text stay as sent", async () => {
    await joined({ today: variants });
    expect(machine().querySelector("summary")).toHaveTextContent("Machine workMachineworkingDetails");
    expect(screen.queryByTestId("triage-needs")).toBeNull();
    expect(screen.queryByTestId("triage-review")).toBeNull();
    expect(screen.queryByTestId("triage-queue")).toBeNull();
    expect(screen.getByTestId("today-exceptions")).toHaveTextContent("1 possible portfolio conflict for Omars"); // decision h
    expect(screen.getByTestId("today-footer")).toHaveTextContent(
      `${RULES} Sources considered: pipeline 1 · calls temporarily unavailable — the rest of Today is complete · events 1 · triage 1 · watch 2 · cases 2.`,
    );
    expect(screen.getByTestId("today-footer")).not.toHaveTextContent("lower-priority");
    expect(screen.getByTestId("today-footer")).not.toHaveTextContent(/native|scout00/);
    expect(screen.queryByTestId("today-snapshot")).toBeNull(); // no snapshot key: nothing
  });

  it("no triage proposal needs you: View queue only", async () => {
    const d = today();
    d.triage = { ...d.triage!, needs_mohamed: 0, calibration: 0 };
    await joined({ today: () => d });
    expect(screen.queryByTestId("triage-review")).toBeNull();
    expect(screen.getByTestId("triage-queue")).toBeInTheDocument();
  });

  it("a quiet day: nothing needs you, no panels, the rest is handled; the note keeps the newest case's time", async () => {
    await joined({ today: emptyDay });
    expect(screen.getByTestId("today-empty")).toHaveTextContent("Nothing needs you today.");
    expect(screen.queryByTestId("today-list")).toBeNull();
    expect(screen.queryByTestId("today-context")).toBeNull();
    expect(screen.getByTestId("today-brief")).toHaveTextContent("Today's briefingNothing needs you today");
    expect(screen.getByTestId("today-exceptions")).toHaveTextContent(/^Project Zero is handling the rest\.$/);
    expect(screen.getByTestId("today-snapshot")).toHaveTextContent(`${NOTE} (newest prepared case 2026-11-01 19:36).`);
    expect(screen.getByTestId("today-footer")).toHaveTextContent(`${RULES} Sources considered: pipeline 0 · calls 0 · events 0 · triage 0 · watch 0 · cases 0.`);
  });

  it("only an event: the Events panel without the Manager one; Missions says none of this kind", async () => {
    const d = emptyDay();
    d.actions = [today().actions[5]];
    await joined({ today: () => d });
    expect(screen.queryByRole("region", { name: "Manager decisions" })).toBeNull();
    expect(screen.getByRole("region", { name: "Events" })).toHaveTextContent("1 decide before the date");
    expect(screen.getByText("No mission of this kind today.")).toBeInTheDocument();
  });

  it("only a Manager decision: the Events panel says no event needs a decision", async () => {
    const d = emptyDay();
    d.actions = [today().actions[1]];
    await joined({ today: () => d });
    expect(screen.getByRole("region", { name: "Events" })).toHaveTextContent("0 decide before the date");
    expect(screen.getByText("No event needs a decision today.")).toBeInTheDocument();
  });

  it("the machine's own work in progress is added to the exceptions line", async () => {
    const d: TodayView = { ...emptyDay(), machine_working: "Project Zero is preparing 1 case in the background." };
    await joined({ today: () => d });
    expect(screen.getByTestId("today-exceptions")).toHaveTextContent("Project Zero is handling the rest. · Project Zero is preparing 1 case in the background.");
  });

  it("before the pipeline arrives (or when it fails) the day shows without the tiles and the company facts", async () => {
    await opened({ pipeline: () => ({ status: 500, body: { ok: false, error: "pipeline unavailable" } }) });
    await waitFor(() => expect(missionRows()).toHaveLength(5));
    expect(screen.queryByRole("list", { name: "Orientation" })).toBeNull();
    expect(row("CONTACT_FOUNDER")).toHaveTextContent("On Radar (high, verified 78), conflict…");
    expect(row("CONTACT_FOUNDER")).not.toHaveTextContent("Biggest unknown");
  });

  it("a failing day read is the error box with Retry", async () => {
    fakeServer({ today: () => ({ status: 500, body: { ok: false, error: "Today could not be computed" } }) });
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Today could not be computed");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1, name: "Today" })).toBeNull();
  });
});

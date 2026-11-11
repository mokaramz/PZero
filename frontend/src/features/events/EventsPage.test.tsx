import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NOT_PORTED } from "./model/deferred";
import { TODAY } from "./test/fixtures";
import { fakeServer, renderEvents } from "./test/server";

const search = (router: { state: { location: { search: string } } }) => new URLSearchParams(router.state.location.search);
const cardIds = () => screen.queryAllByTestId("event-card").map((c) => c.getAttribute("data-event-id"));

async function loaded() {
  await waitFor(() => expect(screen.getByTestId("event-counts")).toBeInTheDocument());
}

/** A disabled control must stay inert for a pointer AND a keyboard (a browser turns Enter / Space into a click). */
function pressEveryWay(el: Element) {
  fireEvent.click(el);
  for (const key of ["Enter", " "]) {
    fireEvent.keyDown(el, { key });
    fireEvent.keyUp(el, { key });
    fireEvent.click(el, { detail: 0 });
  }
}

function expectDeferred(el: HTMLElement, reason: string) {
  expect(el).toHaveAttribute("aria-disabled", "true");
  expect(el).toHaveAttribute("title", reason);
  expect(el).toHaveAccessibleDescription(reason);
  pressEveryWay(el);
}

function openMenu() {
  fireEvent.click(screen.getByRole("button", { name: "More ▾" }));
  return screen.getByRole("menu", { name: "More event actions" });
}

beforeEach(() => {
  localStorage.clear();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(`${TODAY}T12:00:00Z`));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("Events — the timeline (read-only)", () => {
  it("shows the counts, the views and the day groups of the next two weeks from the four reads", async () => {
    const srv = fakeServer();
    renderEvents();
    await loaded();
    expect(screen.getByRole("heading", { level: 1, name: "Events" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("event-counts")).toHaveTextContent("4 upcoming · 1 planned · 1 Scout 00 suggestion not on Events yet · last scan 10 Nov"));
    const tabs = screen.getAllByRole("tab").map((t) => t.textContent);
    expect(tabs).toEqual(["Upcoming4", "Priority3", "Planned1", "Scout suggestions1"]);
    expect(cardIds()).toEqual(["ev-alpha", "ev-quiet", "ev-gamma"]);
    expect(screen.getAllByTestId("suggestion-card")).toHaveLength(1);
    expect(screen.getByText("1 listing not yet reviewed · the source gives a title only", { exact: false })).toBeInTheDocument();
    expect(srv.reads("/api/events/wsig")).toEqual(["/api/events/wsig?days=14"]);
    expect(srv.reads("/api/events/health")).toHaveLength(1);
    expect(srv.reads("/api/network/people")).toHaveLength(1);
    expect(srv.writes()).toEqual([]);
  });

  it("Priority shows Where should I go; its window is a new read", async () => {
    const srv = fakeServer();
    renderEvents();
    await loaded();
    fireEvent.click(screen.getByRole("tab", { name: /Priority/ }));
    const ws = await screen.findByTestId("wsig");
    await waitFor(() => expect(ws).toHaveTextContent("Berlin — Founders Breakfast Alpha"));
    fireEvent.change(within(ws).getByLabelText("Where should I go window"), { target: { value: "30" } });
    await waitFor(() => expect(ws).toHaveTextContent("No dated upcoming events in this window."));
    expect(srv.reads("/api/events/wsig")).toEqual(["/api/events/wsig?days=14", "/api/events/wsig?days=30"]);
  });
});

describe("Events — deep links", () => {
  it("?event=<id>&edit=1 shows the event (with the score breakdown) and never opens a form", async () => {
    fakeServer();
    const { router } = renderEvents("/events?event=ev-gamma&edit=1");
    await loaded();
    const dlg = await screen.findByRole("dialog", { name: "Gamma Demo Day" });
    expect(within(dlg).getByTestId("event-detail")).toBeInTheDocument();
    expect(within(dlg).getByTestId("score-breakdown")).toBeInTheDocument();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    await waitFor(() => expect(search(router).has("edit")).toBe(false));
    expect(search(router).get("event")).toBe("ev-gamma");
  });

  it("?debrief=1 likewise only shows the event; an unknown id says so", async () => {
    fakeServer();
    const { router } = renderEvents("/events?event=ev-alpha&debrief=1");
    await loaded();
    expect(await screen.findByRole("dialog", { name: "Founders Breakfast Alpha" })).toBeInTheDocument();
    await waitFor(() => expect(search(router).has("debrief")).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(search(router).has("event")).toBe(false);

    fakeServer();
    renderEvents("/events?event=nope");
    expect(await screen.findByRole("dialog", { name: "Event not found" })).toBeInTheDocument();
  });

  it("a Scout 00 suggestion opens by its key, labelled as not on Events yet", async () => {
    fakeServer();
    renderEvents("/events?event=scout-harbor");
    const dlg = await screen.findByRole("dialog", { name: "Harbor Summit 2026" });
    expect(within(dlg).getByTestId("suggestion-detail")).toHaveTextContent("Scout 00 suggestion · not on Events yet");
  });
});

describe("Events — every write is visible, disabled and says why", () => {
  it("cards, details, hero, menu, leads, table, health and the empty state never send a request", async () => {
    const srv = fakeServer();
    const { router } = renderEvents();
    await loaded();

    const alpha = screen.getAllByTestId("event-card")[0];
    expectDeferred(within(alpha).getByRole("button", { name: "Plan" }), NOT_PORTED.status);
    expect(search(router).has("event")).toBe(false); // the inert Plan never opens the card
    const sug = screen.getByTestId("suggestion-card");
    for (const name of ["Add to Events", "Monitor", "Ignore"]) expectDeferred(within(sug).getByRole("button", { name }), NOT_PORTED.scout);
    expectDeferred(screen.getByRole("button", { name: "+ Event" }), NOT_PORTED.add);
    expectDeferred(within(openMenu()).getByRole("menuitem", { name: "Scan sources" }), NOT_PORTED.scan);
    expect(screen.getByRole("menu")).toBeInTheDocument(); // an inert item leaves the menu open, as any non-action
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();

    // the details of a needs-review planned event: decision, verify, edit, debrief
    fireEvent.click(within(screen.getAllByTestId("event-card")[2]).getByRole("button", { name: "Details" }));
    const dlg = await screen.findByRole("dialog", { name: "Gamma Demo Day" });
    for (const name of ["GO", "MAYBE", "SKIP"]) expectDeferred(within(dlg).getByRole("button", { name }), NOT_PORTED.status);
    expect(within(dlg).getByRole("button", { name: "GO" })).toHaveAttribute("aria-pressed", "true");
    expectDeferred(within(dlg).getByRole("button", { name: "Mark as verified" }), NOT_PORTED.verify);
    expectDeferred(within(dlg).getByRole("button", { name: "Edit event & notes" }), NOT_PORTED.edit);
    expectDeferred(within(dlg).getByRole("button", { name: "Debrief after the event" }), NOT_PORTED.debrief);
    expect(within(dlg).getByRole("button", { name: "Sold out" })).toBeDisabled();
    expect(within(dlg).queryByText(/Register/)).toBeNull();
    fireEvent.click(within(dlg).getByRole("button", { name: "Close" }));

    // leads
    fireEvent.click(within(openMenu()).getByRole("menuitem", { name: "Leads (1)" }));
    const leads = screen.getByTestId("leads");
    expectDeferred(within(leads).getByRole("button", { name: "Convert" }), NOT_PORTED.lead);
    expectDeferred(within(leads).getByRole("button", { name: "Dismiss" }), NOT_PORTED.lead);

    // table: the status select shows the stored status and is disabled with the reason
    fireEvent.click(within(openMenu()).getByRole("menuitem", { name: "Table view" }));
    const sel = screen.getByRole("combobox", { name: "Status of Gamma Demo Day" });
    expect(sel).toBeDisabled();
    expect(sel).toHaveValue("planned");
    expect(sel).toHaveAccessibleDescription(NOT_PORTED.status);

    // source health: Scan sources
    fireEvent.click(within(openMenu()).getByRole("menuitem", { name: "Source health & scanner log" }));
    const h = await screen.findByRole("dialog", { name: "Source health & scanner log" });
    expectDeferred(within(h).getByRole("button", { name: "Scan sources" }), NOT_PORTED.scan);
    fireEvent.click(within(h).getByRole("button", { name: "Close" }));

    // the empty state of the Planned view filtered to nothing
    fireEvent.click(screen.getByRole("button", { name: "← Back to events" }));
    fireEvent.click(screen.getByRole("tab", { name: /Planned/ }));
    fireEvent.change(screen.getByLabelText("Date"), { target: { value: "7" } });
    const empty = await screen.findByTestId("events-empty");
    expectDeferred(within(empty).getByRole("button", { name: "Scan sources" }), NOT_PORTED.scan);
    expectDeferred(within(empty).getByRole("button", { name: "+ Add an event you know" }), NOT_PORTED.add);

    expect(srv.writes()).toEqual([]);
  });
});

describe("Events — the sourcing weekend", () => {
  it("builds the missions with a GET for the typed window (Friday before the weekend → Sunday)", async () => {
    const srv = fakeServer();
    renderEvents();
    await loaded();
    fireEvent.click(within(openMenu()).getByRole("menuitem", { name: "Weekend plan" }));
    const dlg = await screen.findByRole("dialog", { name: "Sourcing weekend" });
    expect(within(dlg).getByLabelText("From")).toHaveValue("2026-11-13");
    expect(within(dlg).getByLabelText("To")).toHaveValue("2026-11-15");
    fireEvent.click(within(dlg).getByRole("button", { name: "Build missions" }));
    await waitFor(() => expect(within(dlg).getByText("#1 Berlin")).toBeInTheDocument());
    expect(srv.reads("/api/events/weekend")).toEqual(["/api/events/weekend?start=2026-11-13&end=2026-11-15"]);
    expect(srv.writes()).toEqual([]);
  });
});

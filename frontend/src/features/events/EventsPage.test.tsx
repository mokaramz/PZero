import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { health, TODAY } from "./test/fixtures";
import { fakeServer, ok, renderEvents, type Answer } from "./test/server";

const search = (router: { state: { location: { search: string } } }) => new URLSearchParams(router.state.location.search);
const cardIds = () => screen.queryAllByTestId("event-card").map((c) => c.getAttribute("data-event-id"));

async function loaded() {
  await waitFor(() => expect(screen.getByTestId("event-counts")).toBeInTheDocument());
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

describe("Events — the timeline", () => {
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
  it("?event=<id>&edit=1 opens that event's edit form once, then the parameter is removed", async () => {
    fakeServer();
    const { router } = renderEvents("/events?event=ev-gamma&edit=1");
    await loaded();
    const dlg = await screen.findByRole("dialog", { name: "Gamma Demo Day" });
    expect(within(dlg).getByRole("form", { name: "Event form" })).toBeInTheDocument();
    expect(within(dlg).getByLabelText("Event name")).toHaveValue("Gamma Demo Day");
    await waitFor(() => expect(search(router).has("edit")).toBe(false));
    expect(search(router).get("event")).toBe("ev-gamma");
    fireEvent.click(within(dlg).getByRole("button", { name: "Close" }));
    // the form closed, the event stays open
    const detail = await screen.findByRole("dialog", { name: "Gamma Demo Day" });
    expect(within(detail).getByTestId("score-breakdown")).toBeInTheDocument();
  });

  it("?debrief=1 opens the debrief; an unknown id never turns into a form", async () => {
    fakeServer();
    const { router } = renderEvents("/events?event=ev-alpha&debrief=1");
    await loaded();
    const dlg = await screen.findByRole("dialog", { name: "Debrief: Founders Breakfast Alpha" });
    expect(within(dlg).getByTestId("debrief-form")).toBeInTheDocument();
    await waitFor(() => expect(search(router).has("debrief")).toBe(false));
    cleanup();

    fakeServer();
    renderEvents("/events?event=nope&edit=1");
    expect(await screen.findByRole("dialog", { name: "Event not found" })).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Event form" })).toBeNull();
  });

  it("a Scout 00 suggestion opens by its key, labelled as not on Events yet", async () => {
    fakeServer();
    renderEvents("/events?event=scout-harbor");
    const dlg = await screen.findByRole("dialog", { name: "Harbor Summit 2026" });
    expect(within(dlg).getByTestId("suggestion-detail")).toHaveTextContent("Scout 00 suggestion · not on Events yet");
  });
});

describe("Events — status, verify and leads (the old bodies under the new paths)", () => {
  it("MAYBE in the details, Plan on a card and the table select post a status save", async () => {
    const srv = fakeServer();
    renderEvents("/events?event=ev-gamma");
    const dlg = await screen.findByRole("dialog", { name: "Gamma Demo Day" });
    expect(within(dlg).getByRole("button", { name: "GO" })).toHaveAttribute("aria-pressed", "true");
    expect(within(dlg).getByRole("button", { name: "Sold out" })).toBeDisabled();
    expect(within(dlg).queryByText(/Register/)).toBeNull();
    fireEvent.click(within(dlg).getByRole("button", { name: "MAYBE" }));
    expect(await screen.findByText("Status → new")).toBeInTheDocument();
    expect(srv.posts("save")).toEqual([{ id: "ev-gamma", status: "new" }]);
    fireEvent.click(within(dlg).getByRole("button", { name: "Close" }));

    fireEvent.click(within(screen.getAllByTestId("event-card")[0]).getByRole("button", { name: "Plan" }));
    await waitFor(() => expect(srv.posts("save")).toHaveLength(2));
    expect(srv.posts("save")[1]).toEqual({ id: "ev-alpha", status: "planned" });

    fireEvent.click(within(openMenu()).getByRole("menuitem", { name: "Table view" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Status of Past Robotics Meetup" }), { target: { value: "skipped" } });
    await waitFor(() => expect(srv.posts("save")).toHaveLength(3));
    expect(srv.posts("save")[2]).toEqual({ id: "ev-went", status: "skipped" });
    // every status save refreshes the Events reads
    await waitFor(() => expect(srv.reads("/api/events/wsig").length).toBeGreaterThan(1));
  });

  it("Mark as verified posts {id, verified: true} with the old toast", async () => {
    const srv = fakeServer();
    renderEvents("/events?event=ev-gamma");
    const dlg = await screen.findByRole("dialog", { name: "Gamma Demo Day" });
    fireEvent.click(within(dlg).getByRole("button", { name: "Mark as verified" }));
    expect(await screen.findByText("Marked as verified by you — now eligible (HUMAN JUDGMENT)")).toBeInTheDocument();
    expect(srv.posts("verify")).toEqual([{ id: "ev-gamma", verified: true }]);
  });

  it("Dismiss posts the lead decision", async () => {
    const srv = fakeServer();
    renderEvents();
    await loaded();
    fireEvent.click(within(openMenu()).getByRole("menuitem", { name: "Leads (1)" }));
    expect(screen.getByText("Event leads — convert the real ones, dismiss the rest")).toBeInTheDocument();
    fireEvent.click(within(screen.getByTestId("leads")).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(srv.posts("lead")).toEqual([{ id: "lead-1", decision: "dismissed" }]));
  });
});

describe("Events — the event form", () => {
  it("an edit keeps the structured price, sends every ladder value and toasts a merge", async () => {
    const srv = fakeServer({ save: () => ok({ ok: true, id: "ev-alpha|merged:Founders Breakfast Alpha" }) });
    renderEvents("/events?event=ev-alpha");
    const detail = await screen.findByRole("dialog", { name: "Founders Breakfast Alpha" });
    fireEvent.click(within(detail).getByRole("button", { name: "Edit event & notes" }));
    const form = await screen.findByRole("form", { name: "Event form" });
    expect(within(form).getByLabelText("Price")).toHaveValue("25 EUR");
    await waitFor(() => expect(within(form).getByLabelText("Network value (max 15)")).toHaveValue("9"));
    fireEvent.change(within(form).getByLabelText("Notes"), { target: { value: "bring a demo (edited)" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save event" }));
    expect(await screen.findByText("Merged into existing event: Founders Breakfast Alpha")).toBeInTheDocument();
    const [b] = srv.posts("save");
    expect(b?.id).toBe("ev-alpha");
    expect(b?.price).toEqual({ amount: 25, currency: "EUR" });
    expect(b?.notes).toBe("bring a demo (edited)");
    expect(b?.score_parts).toEqual({ founder_density: 16, network_value: 9 }); // no human ladder yet: auto-suggested on open
    expect(b).not.toHaveProperty("convert_lead");
    await waitFor(() => expect(screen.queryByRole("form", { name: "Event form" })).toBeNull());
  });

  it("+ Event auto-suggests the ladder; a 409 collision offers the existing event", async () => {
    const srv = fakeServer({
      save: () => ({
        status: 409,
        body: { ok: false, collision: true, id: "ev-alpha", error: "an event with this name and date already exists with different details (city) — open the existing event to edit it; nothing was saved" },
      }),
    });
    const { router } = renderEvents();
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "+ Event" }));
    const form = await screen.findByRole("form", { name: "Event form" });
    expect(screen.getByRole("dialog", { name: "Add event" })).toBeInTheDocument();
    // the new event's ladder follows the suggestion (closest rung): 15 → 16, 10 → 9
    await waitFor(() => expect(within(form).getByLabelText("Founder density (max 25)")).toHaveValue("16"));
    expect(within(form).getByLabelText("Network value (max 15)")).toHaveValue("9");
    expect(srv.reads("/api/events/suggest")[0]).toBe("/api/events/suggest?type=founder_meetup");
    fireEvent.change(within(form).getByLabelText("Event name"), { target: { value: "Founders Breakfast Alpha" } });
    fireEvent.change(within(form).getByLabelText("City"), { target: { value: "Hamburg" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save event" }));
    const alert = await screen.findByTestId("save-collision");
    expect(alert).toHaveTextContent("an event with this name and date already exists with different details (city)");
    expect(srv.posts("save")[0]).not.toHaveProperty("id");
    fireEvent.click(within(alert).getByRole("button", { name: "Open existing event" }));
    expect(await screen.findByRole("dialog", { name: "Founders Breakfast Alpha" })).toBeInTheDocument();
    expect(search(router).get("event")).toBe("ev-alpha");
    expect(screen.queryByRole("form", { name: "Event form" })).toBeNull();
  });

  it("a lead converts in ONE save carrying convert_lead (a replayed answer is a success)", async () => {
    const srv = fakeServer({ save: () => ok({ ok: true, id: "spring-hack-weekend-2026-12-05", replayed: true }) });
    const { router } = renderEvents();
    await loaded();
    fireEvent.click(within(openMenu()).getByRole("menuitem", { name: "Leads (1)" }));
    fireEvent.click(within(screen.getByTestId("leads")).getByRole("button", { name: "Convert" }));
    const form = await screen.findByRole("form", { name: "Event form" });
    expect(within(form).getByLabelText("Event name")).toHaveValue("Spring Hack Weekend");
    expect(within(form).getByLabelText("Start (YYYY-MM-DD)")).toHaveValue("2026-12-05");
    fireEvent.click(within(form).getByRole("button", { name: "Save event" }));
    expect(await screen.findByText("Event saved & scored")).toBeInTheDocument();
    expect(srv.writes().map((c) => c.path)).toEqual(["/api/events/save"]);
    const [b] = srv.posts("save");
    expect(b).toMatchObject({ name: "Spring Hack Weekend", start: "2026-12-05", city: "Berlin", url: "https://example.org/lead", convert_lead: "lead-1" });
    expect(b).not.toHaveProperty("id");
    expect(srv.posts("lead")).toEqual([]);
    await waitFor(() => expect(screen.queryByRole("form", { name: "Event form" })).toBeNull());
    expect(search(router).has("event")).toBe(false); // only an add opens the saved event
  });
});

describe("Events — the debrief", () => {
  const openDebrief = async () => {
    renderEvents("/events?event=ev-alpha");
    const detail = await screen.findByRole("dialog", { name: "Founders Breakfast Alpha" });
    fireEvent.click(within(detail).getByRole("button", { name: "Debrief after the event" }));
    return screen.findByTestId("debrief-form");
  };
  const type = (f: HTMLElement, label: string, value: string) => fireEvent.change(within(f).getByLabelText(label, { exact: true }), { target: { value } });

  it("posts the old body with each lead's evidence URL and the old toast", async () => {
    const srv = fakeServer({ debrief: () => ok({ ok: true, people: ["p-a", "p-b"], leads: 1 }) });
    const f = await openDebrief();
    expect(f).toHaveTextContent("The loop: Event → Person → Talent Graph → Founder → Startup.");
    type(f, "Person 1", "Ada Synthetic");
    type(f, "Person 1 — why interesting / what they do", "Builds test batteries");
    type(f, "Startup/team 1", "Gridlet Labs");
    type(f, "Startup/team 1 — what they do", "Battery analytics");
    type(f, "Startup/team 1 — Evidence URL (optional — the event's URL is used otherwise)", "https://example.org/gridlet");
    type(f, "Startup/team 2", "Quiet Co");
    fireEvent.change(within(f).getByRole("textbox", { name: "Notes / promised follow-ups / introductions" }), { target: { value: "Intro promised" } });
    fireEvent.click(within(f).getByRole("button", { name: "Save debrief" }));
    expect(await screen.findByText("2 people added, 1 startup leads → Deal Flow")).toBeInTheDocument();
    expect(srv.posts("debrief")).toEqual([
      {
        id: "ev-alpha",
        people_met: [{ name: "Ada Synthetic", note: "Builds test batteries" }],
        leads: [
          { name: "Gridlet Labs", desc: "Battery analytics", url: "https://example.org/gridlet" },
          { name: "Quiet Co", desc: "", url: "" },
        ],
        notes: "Intro promised",
      },
    ]);
    await waitFor(() => expect(screen.queryByTestId("debrief-form")).toBeNull());
  });

  it("a lead without public evidence is refused at its own row and nothing closes", async () => {
    const msg = "startup lead 2 (Third Team) has no public evidence URL: give the lead a URL or add the event's URL first — nothing was saved";
    const srv = fakeServer({ debrief: () => ({ status: 400, body: { ok: false, error: msg, lead: 1 } }) });
    const f = await openDebrief();
    type(f, "Startup/team 1", "First Team");
    type(f, "Startup/team 3", "Third Team"); // row 2 stays empty: the refused lead is the second one SENT, i.e. row 3
    fireEvent.click(within(f).getByRole("button", { name: "Save debrief" }));
    const alert = await within(f).findByTestId("debrief-lead-error");
    expect(alert).toHaveTextContent(msg);
    expect(alert.parentElement).toContainElement(within(f).getByLabelText("Startup/team 3", { exact: true }));
    expect(within(f).getAllByTestId("debrief-lead-error")).toHaveLength(1);
    expect(srv.posts("debrief")[0]?.leads).toEqual([
      { name: "First Team", desc: "", url: "" },
      { name: "Third Team", desc: "", url: "" },
    ]);
    expect(screen.getByTestId("debrief-form")).toBeInTheDocument();
  });
});

describe("Events — Scout 00 suggestions", () => {
  it("Add posts once per merged report and says where the event now is", async () => {
    const srv = fakeServer({ scout: () => ok({ ok: true, status: "ADDED TO EVENTS", event_id: "harbor-summit-2026" }) });
    renderEvents();
    await loaded();
    const sug = screen.getByTestId("suggestion-card");
    expect(sug).toHaveTextContent("Scout 00 · P2 · EV-A · 2 cycles");
    fireEvent.click(within(sug).getByRole("button", { name: "Add to Events" }));
    expect(await screen.findByText("Harbor Summit 2026 is on Events — verify it there before planning")).toBeInTheDocument();
    expect(srv.posts("scout")).toEqual([
      { id: "se-008-1", action: "add" },
      { id: "se-mw-2", action: "add" },
    ]);
  });

  it("Ignore from the details closes it; a refused report says so", async () => {
    const srv = fakeServer({ scout: (b) => (b.id === "se-mw-2" ? ok({ ok: false, error: "unknown Scout 00 report" }) : ok({ ok: true, status: "IGNORED" })) });
    const { router } = renderEvents("/events?event=scout-harbor");
    const dlg = await screen.findByRole("dialog", { name: "Harbor Summit 2026" });
    fireEvent.click(within(dlg).getByRole("button", { name: "Ignore" }));
    expect(await screen.findByText("Scout 00 report not updated: unknown Scout 00 report")).toBeInTheDocument();
    expect(srv.posts("scout")).toEqual([
      { id: "se-008-1", action: "ignore" },
      { id: "se-mw-2", action: "ignore" },
    ]);
    expect(search(router).get("event")).toBe("scout-harbor"); // not updated: the details stay open
  });
});

describe("Events — the source scan", () => {
  const FOUND = {
    added: 2,
    accepted: 1,
    dropped_past: 4,
    dropped_dupe: 1,
    health: { ...health(), scan_time: "2026-11-12 09:30" },
    report: [
      { source: "Example events API", status: "ok", kind: "api", note: "3 future events" },
      { source: "Sample city feed", status: "failed", kind: "api", note: "HTTP 429" },
    ],
  };
  /** The scan answer, held until the test releases it (the real scan runs for minutes). */
  function held() {
    let release: (a: Answer) => void = () => undefined;
    const answer = new Promise<Answer>((r) => (release = r));
    return { answer, release };
  }

  it("Scan sources (More menu) posts {}, says Scanning… while it runs, toasts the counts and fills the scanner log", async () => {
    const scan = held();
    const srv = fakeServer({ find: () => scan.answer });
    renderEvents();
    await loaded();
    fireEvent.click(within(openMenu()).getByRole("menuitem", { name: "Scan sources" }));
    expect(await screen.findByRole("button", { name: "Scanning…" })).toBeInTheDocument();
    expect(screen.queryByRole("menu")).toBeNull();
    await waitFor(() => expect(srv.posts("find")).toEqual([{}]));
    scan.release(ok(FOUND));
    expect(await screen.findByText("2 leads added · 4 past events dropped · 1 duplicates skipped")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "More ▾" })).toBeInTheDocument();
    // the scan's own health wins over the stored one
    await waitFor(() => expect(screen.getByTestId("event-counts")).toHaveTextContent("last scan 12 Nov"));
    fireEvent.click(within(openMenu()).getByRole("menuitem", { name: "Source health & scanner log" }));
    const h = await screen.findByRole("dialog", { name: "Source health & scanner log" });
    expect(within(h).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Example events API 3 future events", "Sample city feed HTTP 429"]);
    expect(srv.writes().map((c) => c.path)).toEqual(["/api/events/find"]);
  });

  it("the source-health button runs the same scan and shows its busy label", async () => {
    const scan = held();
    const srv = fakeServer({ find: () => scan.answer });
    renderEvents();
    await loaded();
    fireEvent.click(within(openMenu()).getByRole("menuitem", { name: "Source health & scanner log" }));
    const h = await screen.findByRole("dialog", { name: "Source health & scanner log" });
    expect(within(h).queryByRole("list")).toBeNull();
    fireEvent.click(within(h).getByRole("button", { name: "Scan sources" }));
    const busy = await within(h).findByRole("button", { name: "Scanning…" });
    expect(busy).toBeDisabled();
    scan.release(ok(FOUND));
    await waitFor(() => expect(within(h).getAllByRole("listitem")).toHaveLength(2));
    expect(within(h).getByRole("button", { name: "Scan sources" })).toBeEnabled();
    expect(srv.posts("find")).toEqual([{}]);
  });

  it("a scan already running (409) shows its message; the empty state offers the scan too", async () => {
    const srv = fakeServer({ find: () => ({ status: 409, body: { ok: false, error: "an event source scan is already running — wait for it to finish" } }) });
    renderEvents();
    await loaded();
    fireEvent.click(screen.getByRole("tab", { name: /Planned/ }));
    fireEvent.change(screen.getByLabelText("Date"), { target: { value: "7" } });
    const empty = await screen.findByTestId("events-empty");
    fireEvent.click(within(empty).getByRole("button", { name: "Scan sources" }));
    expect(await screen.findByText("✕ Searching for events failed — an event source scan is already running — wait for it to finish")).toBeInTheDocument();
    expect(srv.posts("find")).toEqual([{}]);
    expect(screen.getByRole("button", { name: "More ▾" })).toBeInTheDocument();
    fireEvent.click(within(empty).getByRole("button", { name: "+ Add an event you know" }));
    expect(await screen.findByRole("form", { name: "Event form" })).toBeInTheDocument();
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

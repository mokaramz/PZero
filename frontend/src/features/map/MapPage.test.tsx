import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ALL_ITEMS } from "@/app/nav";
import { loadMapLibre } from "./components/loadMapLibre";
import { GEO_COLOR, VIS_COLOR } from "./model/colors";
import { NOT_PORTED, SNAPSHOT_NOTE } from "./model/deferred";
import { TEXT } from "./model/text";
import { intel, INTEL_NOW, munich, NOTE, pins, PINS_NOW } from "./test/fixtures";
import { FakeMap, fakeMapLibre } from "./test/maplibre";
import { fakeServer, renderPage } from "./test/server";

vi.mock("./components/loadMapLibre", () => ({ loadMapLibre: vi.fn() }));

const controls = () => screen.getByTestId("map-controls");
const results = () => within(screen.getByTestId("map-results")).queryAllByRole("button");
/** a layer checkbox — its label also holds the count, "Startups (8)" */
const layer = (name: string) => within(controls()).getByLabelText(new RegExp(String.raw`^\s*${name}\s*\(\d+\)$`));
const layerCount = (name: string) => Number(/\((\d+)\)/.exec(layer(name).closest("label")?.textContent ?? "")?.[1]);
const panel = () => screen.getByTestId("map-panel");
const geoPanel = () => screen.getByTestId("geo-panel");
const tab = (name: string) => screen.getByRole("tab", { name });
const select = (label: string, value: string) => fireEvent.change(within(controls()).getByLabelText(label), { target: { value } });
const toasts = () => screen.getByRole("status");

async function mapReady() {
  await waitFor(() => expect(screen.getByTestId("map-canvas")).toHaveAttribute("data-ready", "true"));
}

async function explore(path = "/map") {
  const server = fakeServer();
  renderPage(path);
  await mapReady();
  fireEvent.click(tab("Explore"));
  return server;
}

function search(q: string) {
  const box = screen.getByLabelText("Search the map");
  fireEvent.change(box, { target: { value: q } });
  fireEvent.keyDown(box, { key: "Enter" });
}

async function openMunich() {
  fireEvent.click(within(await screen.findByTestId("geo-list")).getByRole("button", { name: /Munich/ }));
  await within(geoPanel()).findByTestId("geo-why");
}

beforeEach(() => {
  FakeMap.reset();
  vi.mocked(loadMapLibre).mockResolvedValue(fakeMapLibre);
  // the browser clock (decision e): the pins' weekend of 26-27 Sep 2026; only Date is faked, timers stay real
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(PINS_NOW);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Map — the page", () => {
  it("is a ported nav view at /map", () => {
    expect(ALL_ITEMS.find((i) => i.legacyView === "map")).toMatchObject({ path: "/map", label: "Map", page: expect.anything() });
  });

  it("shows the header, opens in Opportunity mode on a ready map and reads the pins, the intelligence and the side reads", async () => {
    const server = fakeServer();
    renderPage();
    await mapReady();
    expect(screen.getByRole("heading", { level: 1, name: "Map" })).toBeInTheDocument();
    expect(screen.getByText("Where is opportunity forming, where should you go, who is there — and where is Project Zero blind?")).toBeInTheDocument();
    expect(within(screen.getByRole("tablist", { name: "Map mode" })).getAllByRole("tab").map((t) => t.textContent)).toEqual([
      "Opportunity",
      "Where to go",
      "Coverage gaps",
      "Explore",
    ]);
    expect(tab("Opportunity")).toHaveAttribute("aria-selected", "true");
    await screen.findByTestId("geo-controls");
    expect([...new Set(server.gets())].sort()).toEqual([
      "/api/conviction/pipeline",
      "/api/events",
      "/api/events/wsig?days=14",
      "/api/map/intel",
      "/api/map/pins",
      "/api/network/people",
    ]);
    expect(server.posts()).toEqual([]);
    // the map starts at the home base, on OpenFreeMap's style
    expect(FakeMap.last.options).toMatchObject({ style: "https://tiles.openfreemap.org/styles/positron", center: [8.4037, 49.0069], zoom: 5.2 });
  });

  it("feeds the filtered pins and the ecosystem circles to the map", async () => {
    fakeServer();
    renderPage();
    await mapReady();
    await screen.findByTestId("geo-controls");
    const m = FakeMap.last;
    expect(m.layers).toEqual(expect.arrayContaining(["eco-c", "st-cl", "st-pt", "ev-pt", "ppl-pt", "org-pt"]));
    expect(m.props("startups")).toHaveLength(8);
    expect(m.props("events")).toHaveLength(7);
    expect(m.props("ppl")).toEqual([]);
    await waitFor(() => expect(m.props("eco").map((p) => p.city)).toEqual(["Munich", "Berlin", "Tallinn"]));
    expect(m.props("eco")[0]).toEqual({ city: "Munich", color: GEO_COLOR["VERY ACTIVE"], blind: false, r: 18.5 });
    expect(m.props("eco")[2]).toMatchObject({ city: "Tallinn", blind: true });
    // Coverage gaps colours the circles by visibility; Explore hides them
    fireEvent.click(tab("Coverage gaps"));
    await waitFor(() => expect(m.props("eco").map((p) => p.color)).toEqual([VIS_COLOR.GOOD, VIS_COLOR["NOT ASSESSED"], VIS_COLOR.POOR]));
    fireEvent.click(tab("Explore"));
    await waitFor(() => expect(m.props("eco")).toEqual([]));
  });

  it("a click on a pin or a circle opens its panel", async () => {
    fakeServer();
    renderPage();
    await mapReady();
    await screen.findByTestId("geo-controls");
    await FakeMap.last.click("st-pt", { slug: "skylark-freight" });
    expect(await screen.findByTestId("map-panel")).toHaveTextContent("Skylark Freight");
    expect(panel()).toHaveTextContent("→ OMAR");
    expect(panel()).toHaveTextContent("Sent to Manager: 2026-09-20");
    expect(controls()).toHaveAttribute("data-receded", "");
    await FakeMap.last.click("eco-c", { city: "Munich" });
    expect(await screen.findByTestId("geo-panel")).toHaveTextContent("Munich");
    expect(screen.queryByTestId("map-panel")).not.toBeInTheDocument();
  });
});

describe("Map — Explore: layers, filters and visible results", () => {
  it("the default layers and their counts, then the filters (the old e2e)", async () => {
    await explore();
    const c = within(controls());
    expect(layer("Startups")).toBeChecked();
    expect(layer("Events")).toBeChecked();
    expect(layer("People")).not.toBeChecked();
    expect(layer("Universities & labs")).not.toBeChecked();
    expect(layer("Hubs & accelerators")).not.toBeChecked();
    expect(["Startups", "Events", "People", "Universities & labs", "Hubs & accelerators"].map(layerCount)).toEqual([8, 7, 4, 4, 2]);
    expect(within(controls()).getByText("Visible results").textContent).toBe("Visible results (15)");

    const before = results().length;
    fireEvent.click(layer("People"));
    fireEvent.click(layer("Universities & labs"));
    fireEvent.click(layer("Hubs & accelerators"));
    expect(results().length).toBeGreaterThan(before);
    expect(FakeMap.last.props("orgs")).toHaveLength(6);

    select("Distance from home base", "100");
    expect(layerCount("Startups")).toBe(2);
    select("Distance from home base", "0");
    fireEvent.change(c.getByLabelText("Min startup score"), { target: { value: "60" } });
    expect(layerCount("Startups")).toBe(5);
    fireEvent.change(c.getByLabelText("Min startup score"), { target: { value: "" } });
    expect(layerCount("Startups")).toBe(8);
    select("Time", "weekend");
    expect(layerCount("Events")).toBe(1);
    select("Time", "all");
    select("Status", "gated");
    expect(layerCount("Startups")).toBe(1);
    select("Status", "");
    select("Project A theme", "defence");
    expect(layerCount("Startups")).toBe(2);
    select("Project A theme", "");
    select("Event type", "hackathon");
    expect(layerCount("Events")).toBe(1);
    expect(within(c.getByLabelText("Event type")).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "All event types",
      "Demo day",
      "Accelerator event",
      "Hackathon",
      "University entrepreneurship",
      "Founder meetup / pitch night",
      "Type not evidenced",
    ]);
    expect(within(c.getByLabelText("Status")).getByRole("option", { name: "Sent to Manager" })).toBeInTheDocument();
    expect(c.getByText("No coordinates (edit location): Quiet Harbor Systems")).toBeInTheDocument();
  });

  it("nothing visible says so", async () => {
    await explore();
    fireEvent.click(layer("Startups"));
    fireEvent.click(layer("Events"));
    expect(screen.getByTestId("map-results")).toHaveTextContent("Nothing visible with these filters.");
    expect(FakeMap.last.props("startups")).toEqual([]);
  });

  it("a result opens the company panel, flies there, and links to its Conviction workspace", async () => {
    await explore();
    fireEvent.click(within(screen.getByTestId("map-results")).getByRole("button", { name: /Northwind Assure/ }));
    expect(panel()).toHaveTextContent("COMPANY");
    expect(panel()).toHaveTextContent("CONFLICT-GATED");
    expect(panel()).toHaveTextContent("Potential portfolio conflict — Manager first.");
    expect(panel()).toHaveTextContent("Next action: none set — open the Conviction workspace");
    expect(within(panel()).getByRole("link", { name: "Open workspace" })).toHaveAttribute("href", "/conviction?company=northwind-assure");
    expect(FakeMap.last.flights.at(-1)).toEqual({ center: [24.9384, 60.1699], zoom: 9 });
    // the pipeline's next action, linked people and events nearby
    fireEvent.click(within(screen.getByTestId("map-results")).getByRole("button", { name: /Fernhollow Materials/ }));
    expect(panel()).toHaveTextContent("Next action: Book founder call");
    fireEvent.click(within(screen.getByTestId("map-results")).getByRole("button", { name: /Kestrel Robotics/ }));
    expect(panel()).toHaveTextContent("Linked people: Jonah Weller");
    fireEvent.click(within(panel()).getByRole("button", { name: "Isar Defence Founders Meetup" }));
    expect(panel()).toHaveTextContent("EVENT");
    expect(FakeMap.last.flights.at(-1)).toEqual({ center: [11.582, 48.1351], zoom: 9 });
    fireEvent.click(within(panel()).getByRole("button", { name: "Close detail" }));
    expect(screen.queryByTestId("map-panel")).not.toBeInTheDocument();
  });

  it("the cards: the best event this weekend, the undecided Deal Flow candidates (from the pins) and the first follow-up due", async () => {
    await explore();
    expect(screen.getByRole("link", { name: /Best this weekend/ })).toHaveTextContent("Best this weekendForge Demo Day & Pitch Night · Karlsruhe 1");
    expect(screen.getByRole("link", { name: /Best this weekend/ })).toHaveAttribute("href", "/events");
    expect(screen.getByRole("link", { name: /Deal Flow/ })).toHaveTextContent("Deal Flow241 undecided candidates");
    expect(screen.getByRole("link", { name: /Deal Flow/ })).toHaveAttribute("href", "/deal-flow");
    expect(screen.getByRole("link", { name: /Follow-ups due/ })).toHaveTextContent("Follow-ups dueInes Halvorsen · follow up within 48h while the c");
    expect(screen.queryByTestId("geo-cards")).not.toBeInTheDocument();
  });

  it("without new_signals the Deal Flow card shows a dash", async () => {
    fakeServer({ pins: () => ({ ...pins(), new_signals: undefined }) });
    renderPage("/map?mode=explore");
    await mapReady();
    expect(screen.getByRole("link", { name: /Deal Flow/ })).toHaveTextContent("Deal Flow— undecided candidates");
  });
});

describe("Map — the event deep link and search", () => {
  it("?event= opens that event once the map is ready", async () => {
    fakeServer();
    renderPage("/map?event=alpine-robotics-hackathon");
    await mapReady();
    expect(await screen.findByTestId("map-panel")).toHaveTextContent("Alpine Robotics Hackathon");
    expect(within(panel()).getByRole("link", { name: "Open workspace" })).toHaveAttribute("href", "/events?event=alpine-robotics-hackathon");
    expect(within(panel()).getByRole("link", { name: "Edit score" })).toHaveAttribute("href", "/events?event=alpine-robotics-hackathon&edit=1");
    expect(within(panel()).getByRole("link", { name: "Debrief" })).toHaveAttribute("href", "/events?event=alpine-robotics-hackathon&debrief=1");
    expect(panel()).toHaveTextContent("Next action: decide GO / MAYBE / SKIP in Events");
    expect(panel()).not.toHaveTextContent("People to meet there"); // person pins carry no city (decision e)
    expect(FakeMap.last.flights).toEqual([{ center: [8.5417, 47.3769], zoom: 9 }]);
  });

  it("?event= for an event without coordinates says so in a toast", async () => {
    fakeServer();
    renderPage("/map?event=no-such-event");
    await mapReady();
    await waitFor(() => expect(toasts()).toHaveTextContent(TEXT.noCoordinates));
    expect(screen.queryByTestId("map-panel")).not.toBeInTheDocument();
  });

  it("a local hit opens its panel without asking the server; the org links to its ecosystem, the person to Network", async () => {
    const server = await explore();
    search("Rheinfeld");
    expect(within(panel()).getByRole("link", { name: "Open Karlsruhe ecosystem" })).toHaveAttribute("href", "/ecosystems?city=Karlsruhe");
    expect(server.reads("map/search")).toBe(0);
    fireEvent.click(layer("People"));
    fireEvent.click(within(screen.getByTestId("map-results")).getByRole("button", { name: /Mara Lindqvist/ }));
    expect(within(panel()).getByRole("link", { name: "Open profile" })).toHaveAttribute("href", "/network?person=p-mara-lindqvist");
    expect(within(panel()).getByRole("link", { name: "Edit / log" })).toHaveAttribute("href", "/network?person=p-mara-lindqvist&edit=1");
    fireEvent.click(within(panel()).getByRole("link", { name: "Open profile" }));
    expect(await screen.findByTestId("elsewhere")).toHaveTextContent("/network?person=p-mara-lindqvist");
  });

  it("a local miss asks map/search and opens the first result's city", async () => {
    const server = fakeServer();
    renderPage();
    await mapReady();
    await screen.findByTestId("geo-controls");
    search("Torvane");
    expect(await screen.findByTestId("geo-panel")).toHaveTextContent("Munich");
    expect(server.gets()).toContain("/api/map/search?q=Torvane");
    expect(server.gets()).toContain("/api/map/ecosystem?city=Munich");
    expect(FakeMap.last.flights.at(-1)).toEqual({ center: [11.582, 48.1351], zoom: 8 });
  });

  it("no match anywhere, or a failed search, says so", async () => {
    let fail = false;
    fakeServer({ search: () => (fail ? { status: 500, body: { ok: false, error: "boom" } } : { results: [] }) });
    renderPage();
    await mapReady();
    search("zzz");
    await waitFor(() => expect(toasts()).toHaveTextContent(TEXT.noMatch));
    fail = true;
    search("yyy");
    await waitFor(() => expect(within(toasts()).getAllByText(TEXT.noMatch)).toHaveLength(2));
    expect(screen.queryByTestId("geo-panel")).not.toBeInTheDocument();
  });
});

describe("Map — ground sourcing", () => {
  beforeEach(() => vi.setSystemTime(INTEL_NOW));

  it("Opportunity: the note, the snapshot note (decision b), the legend, the active areas and the cards", async () => {
    fakeServer();
    renderPage();
    const ctl = await screen.findByTestId("geo-controls");
    expect(ctl).toHaveTextContent("not company investment scores");
    expect(within(ctl).getByText(NOTE)).toBeInTheDocument();
    expect(within(ctl).getByTestId("geo-snapshot-note")).toHaveTextContent(SNAPSHOT_NOTE);
    expect(SNAPSHOT_NOTE).toBe("News and source candidates come from the imported snapshot until their own views are ported.");
    expect(ctl).toHaveTextContent("very active (1)");
    expect(ctl).toHaveTextContent("under-covered (1)");
    const list = within(screen.getByTestId("geo-list")).getAllByRole("button");
    expect(list.map((b) => b.textContent)).toEqual(["Munich5 early signal(s) from 3 source(s)", "Berlin3 companies, none early"]);
    const cards = screen.getByTestId("geo-cards");
    expect(within(cards).getAllByRole("button").map((b) => b.textContent)).toEqual(["Where to goMunich — 5 early signal(s)", "Coverage gapMunich: founder formation weak"]);
    fireEvent.click(within(cards).getByRole("button", { name: /Coverage gap/ }));
    expect(await screen.findByTestId("geo-panel")).toHaveTextContent("Munich");
  });

  it("no cards and no active area say so", async () => {
    fakeServer({ intel: () => ({ ...intel(), cards: [], ecosystems: [intel().ecosystems[2]] }) });
    renderPage();
    expect(await screen.findByTestId("geo-list")).toHaveTextContent("No area has current Project Zero signals yet.");
    expect(screen.getByTestId("geo-cards")).toHaveTextContent("Not enough geographic signal yet.");
  });

  it("the Why here? panel: why, convergence, the next best action, companies, people, events, coverage, sources, news, notes", async () => {
    fakeServer();
    renderPage();
    await openMunich();
    const p = geoPanel();
    expect(p).toHaveAttribute("aria-label", "Ecosystem");
    expect(within(p).getByText("VERY ACTIVE")).toBeInTheDocument();
    expect(within(p).getByTestId("geo-why")).toHaveTextContent("Scout 00 discovery");
    expect(p).toHaveTextContent("Signal convergence: 6 independent signals across 3 families — event, university / research spinout, scout 00 discovery.");
    expect(within(p).getByTestId("geo-nba")).toHaveTextContent("Next best action: Decide on Isar Pitch Night (2026-10-20) — registration is yours to do.");
    expect(within(p).getByTestId("geo-coverage")).toHaveTextContent("NOT COVERED");
    expect(within(p).getByTestId("geo-coverage")).toHaveTextContent("STRONG");
    expect(p).toHaveTextContent("Source candidates: Isar Founder Directory — discovered (System health → New sources)");
    expect(p).toHaveTextContent("What changed (News)");
    expect(p).toHaveTextContent("2026-10-05 · Torvane Systems joins a regional accelerator (Example Wire)");
    expect(p).toHaveTextContent("Institutions: Isar Polytechnic · Isar Founder Works");
    expect(p).toHaveTextContent("only verified scores are official.");
    expect(within(p).getByTestId("geo-snapshot-note")).toHaveTextContent(SNAPSHOT_NOTE);
    expect(p).toHaveTextContent("Jonah Weller CTO · Kestrel Robotics · relationship: strong");
    expect(p).toHaveTextContent("2026-10-20 18:00 · high-signal · free · registration: open (yours to do)");
    expect(p).toHaveTextContent("Scout 00 · cycle 009");
    expect(p).toHaveTextContent("News: Torvane Systems joins a regional accelerator");
  });

  it("links (decision d): Deal Flow, Conviction by name, Network and Events are links; a Scout 00 card without a candidate is text with the reason", async () => {
    fakeServer();
    renderPage();
    await openMunich();
    const p = within(geoPanel());
    expect(p.getByRole("link", { name: "Torvane Systems" })).toHaveAttribute("href", "/deal-flow?candidate=cand-torvane");
    expect(p.getByRole("link", { name: "Kestrel Robotics" }).getAttribute("href")).toMatch(/^\/conviction\?company=Kestrel(%20| )Robotics$/);
    expect(p.getByRole("link", { name: "Jonah Weller" })).toHaveAttribute("href", "/network?person=p-jonah-weller");
    expect(p.getByRole("link", { name: "Isar Pitch Night" })).toHaveAttribute("href", "/events?event=isar-pitch-night");
    expect(p.queryByRole("link", { name: "Pallas Grip" })).not.toBeInTheDocument();
    const pallas = p.getByText("Pallas Grip").closest("[data-deferred]")!;
    expect(pallas).toHaveAttribute("title", NOT_PORTED.scoutIntake);
    expect(pallas).toHaveAccessibleDescription(`(${NOT_PORTED.scoutIntake})`);
    expect(p.getByText(`(${NOT_PORTED.scoutIntake})`)).toBeVisible();
  });

  it("a /news link the server sends is plain text with the News reason", async () => {
    fakeServer({ ecosystem: (city) => (city === "Munich" ? { ...munich(), companies: [{ ...munich().companies[1], name: "Torvane news story", link: "/news" }] } : undefined) });
    renderPage();
    await openMunich();
    const p = within(geoPanel());
    expect(p.queryByRole("link", { name: "Torvane news story" })).not.toBeInTheDocument();
    expect(p.getByText("Torvane news story").closest("[data-deferred]")).toHaveAttribute("title", NOT_PORTED.news);
    expect(p.getByText(`(${NOT_PORTED.news})`)).toBeInTheDocument();
    expect(NOT_PORTED.news).toBe("News arrives with the News & Learning port");
  });

  it("coverage not assessed, and an unknown city", async () => {
    fakeServer({ ecosystem: (city) => (city === "Berlin" ? { ...munich(), city: "Berlin", coverage: intel().ecosystems[1].coverage, source_candidates: [], news: [] } : undefined) });
    renderPage();
    fireEvent.click(within(await screen.findByTestId("geo-list")).getByRole("button", { name: /Berlin/ }));
    expect(await within(geoPanel()).findByText("Coverage not assessed for this place — treat “no signals” as “we do not know”.")).toBeInTheDocument();
    expect(geoPanel()).not.toHaveTextContent("What changed (News)");
    expect(geoPanel()).not.toHaveTextContent("Source candidates");
    search("Tallinn"); // a local miss → the server search finds nothing → a toast; open it from the gaps list instead
    fireEvent.click(tab("Coverage gaps"));
    fireEvent.click(within(screen.getByTestId("coverage-gaps")).getByRole("button", { name: /Tallinn/ }));
    expect(await within(geoPanel()).findByText(/unknown or unplaced ecosystem: Tallinn/)).toBeInTheDocument();
  });

  it("the sourcing day: Berlin day + 7 by default, exactly one POST, PLAN ONLY, nothing made stale", async () => {
    const server = fakeServer();
    const { qc } = renderPage();
    await openMunich();
    const invalidate = vi.spyOn(qc, "invalidateQueries");
    const readsBefore = server.gets().length;
    fireEvent.click(within(geoPanel()).getByTestId("build-day"));
    const date = within(geoPanel()).getByLabelText("Sourcing day date");
    expect(date).toHaveValue("2026-10-19");
    fireEvent.change(date, { target: { value: "2026-10-20" } });
    fireEvent.click(within(geoPanel()).getByRole("button", { name: "Build plan" }));
    const plan = await within(geoPanel()).findByTestId("sourcing-plan");
    expect(plan).toHaveTextContent("PLAN ONLY");
    expect(plan).toHaveTextContent("18:00 — Isar Pitch Night");
    expect(plan).toHaveTextContent("Munich — Tuesday 2026-10-20");
    expect(plan).toHaveTextContent("Mission objective: University / research spinout");
    expect(plan).toHaveTextContent("Blind spots here: founder formation.");
    expect(plan).toHaveTextContent("People worth contacting (you decide, no automatic outreach)");
    expect(within(plan).getByRole("link", { name: "Torvane Systems" })).toHaveAttribute("href", "/deal-flow?candidate=cand-torvane");
    expect(within(plan).queryByRole("link", { name: "Pallas Grip" })).not.toBeInTheDocument();
    expect(within(plan).getByText(`(${NOT_PORTED.scoutIntake})`)).toBeInTheDocument();
    expect(server.posts()).toEqual([{ method: "POST", path: "/api/map/sourcing_day", body: { city: "Munich", date: "2026-10-20" } }]);
    await waitFor(() => expect(toasts()).toHaveTextContent("✓ Building plan — done"));
    expect(invalidate.mock.calls.map(([f]) => f?.queryKey)).toEqual([["activity"]]);
    expect(server.gets().length).toBe(readsBefore);
    fireEvent.click(within(geoPanel()).getByRole("button", { name: "← back" }));
    expect(within(geoPanel()).getByTestId("geo-why")).toBeInTheDocument();
  });

  it("a refused plan shows the failure and stores nothing", async () => {
    const server = fakeServer({ sourcingDay: () => ({ status: 400, body: { ok: false, error: "date as YYYY-MM-DD" } }) });
    renderPage();
    await openMunich();
    fireEvent.click(within(geoPanel()).getByTestId("build-day"));
    fireEvent.click(within(geoPanel()).getByRole("button", { name: "Build plan" }));
    await waitFor(() => expect(toasts()).toHaveTextContent("Building plan failed"));
    expect(within(geoPanel()).queryByTestId("sourcing-plan")).not.toBeInTheDocument();
    expect(server.posts()).toHaveLength(1);
  });

  it("Where to go: the ranked cities with travel and why, then the note", async () => {
    fakeServer();
    renderPage("/map?mode=go");
    const w = await screen.findByTestId("where-to-go");
    expect(tab("Where to go")).toHaveAttribute("aria-selected", "true");
    expect(w).toHaveTextContent("Where should I go?");
    expect(w).toHaveTextContent("1. Munich day trip · ~3 h from Karlsruhe (approximate city table)Why: 5 early signal(s) from 3 source(s) · 1 high-signal event");
    expect(w).toHaveTextContent("Ranked by early signals — not by volume. Open a city, then “Build a sourcing day”.");
    fireEvent.click(within(w).getByRole("button", { name: /1\. Munich/ }));
    expect(await screen.findByTestId("geo-panel")).toHaveTextContent("Munich");
  });

  it("Where to go with nothing ranked shows the note alone", async () => {
    fakeServer({ intel: () => ({ ...intel(), where_to_go: { ranked: [], note: "Nothing to rank yet." } }) });
    renderPage("/map?mode=go");
    const w = await screen.findByTestId("where-to-go");
    expect(w.textContent).toBe("Where should I go?Nothing to rank yet.");
  });

  it("Coverage gaps: weak or unassessed areas, under-covered is not 'cold', and what was never guessed", async () => {
    fakeServer();
    renderPage("/map?mode=gaps");
    const g = await screen.findByTestId("coverage-gaps");
    expect(g).toHaveTextContent("Where is Project Zero blind?");
    expect(g).toHaveTextContent("visibility good");
    expect(g).toHaveTextContent("visibility not assessed");
    expect(within(g).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Munichweak: founder formation",
      "Berlincoverage not assessed",
      "Tallinnweak: universities / research · under-covered (not 'cold')",
    ]);
    expect(g).toHaveTextContent("Not placed (no city in their own location — never guessed): 12 deal flow");
  });

  it("when the intelligence fails, the modes say so and Explore still works", async () => {
    fakeServer({ intel: () => ({ status: 500, body: { ok: false, error: "boom" } }) });
    renderPage();
    await mapReady();
    expect(await within(controls()).findByText(TEXT.intelUnavailable)).toBeInTheDocument();
    expect(TEXT.intelUnavailable).toBe("Ecosystem intelligence unavailable — the Explore layers still work.");
    expect(screen.getByTestId("geo-cards")).toBeEmptyDOMElement();
    expect(screen.queryByTestId("geo-controls")).not.toBeInTheDocument();
    fireEvent.click(tab("Explore"));
    expect(layerCount("Startups")).toBe(8);
  });
});

describe("Map — the base map", () => {
  it("a base-map error before the style loads moves the pins to the plain canvas, with a toast", async () => {
    FakeMap.autoLoad = false;
    fakeServer();
    renderPage();
    await waitFor(() => expect(FakeMap.instances).toHaveLength(1));
    expect(screen.getByTestId("map-canvas")).not.toHaveAttribute("data-ready");
    await FakeMap.last.fire("error");
    expect(FakeMap.last.style).toEqual(expect.objectContaining({ name: "offline" }));
    await waitFor(() => expect(toasts()).toHaveTextContent(TEXT.tilesError));
    await mapReady(); // the plain style loads without the network; the pins are there
    expect(FakeMap.last.props("startups")).toHaveLength(8);
    // a later error changes nothing (once loaded, the base map stays)
    await FakeMap.last.fire("error");
    expect(within(toasts()).getAllByText(TEXT.tilesError)).toHaveLength(1);
  });

  it("when MapLibre cannot load, the plain message shows and the controls still work", async () => {
    vi.mocked(loadMapLibre).mockRejectedValue(new Error("offline"));
    fakeServer();
    renderPage("/map?mode=explore");
    expect(await screen.findByText(TEXT.mapFail)).toBeInTheDocument();
    expect(screen.getByTestId("map-canvas")).not.toHaveAttribute("data-ready");
    expect(layerCount("Startups")).toBe(8);
  });
});

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ALL_ITEMS } from "@/app/nav";
import { SOURCES } from "@/features/sources/api";
import { coverage, fakeServer, renderPage } from "./test/server";

const panel = () => screen.getByTestId("coverage");
const table = () => within(panel()).getByRole("table");
const rows = () => within(table()).queryAllByRole("row").slice(1);
const cities = () => rows().map((r) => within(r).getByRole("button").textContent);
const row = (city: string) => rows().find((r) => within(r).getByRole("button").textContent === city)!;
const cells = (city: string) => within(row(city)).getAllByRole("cell").map((c) => c.textContent);
const detail = () => screen.getByTestId("coverage-detail");
const family = (id: string) => screen.getByTestId(`family-${id}`);
const dialog = () => screen.getByRole("dialog", { name: "Adopt as watcher?" });
const reg = () => screen.getByTestId("city-registry");
const chips = (group: "curated" | "detected") => within(screen.getByTestId(`registry-${group}`)).queryAllByRole("button");
const chip = (name: string) => within(reg()).getByRole("button", { name: new RegExp(`^${name}`) });
const dots = (name: string) => Array.from(chip(name).querySelectorAll("i")).map((i) => /dotOn/.test(i.className));
const city = () => screen.getByTestId("city-page");
const sec = (title: string) => within(city()).getByRole("heading", { level: 3, name: title }).closest("section")!;

async function loaded() {
  await waitFor(() => expect(rows()).toHaveLength(3));
  await screen.findByTestId("city-registry");
}

function open(cityName: string) {
  fireEvent.click(within(row(cityName)).getByRole("button", { name: cityName }));
}

afterEach(() => vi.unstubAllGlobals());

describe("Ecosystems — the page", () => {
  it("is a ported nav view at /ecosystems", () => {
    expect(ALL_ITEMS.find((i) => i.legacyView === "eco")).toMatchObject({ path: "/ecosystems", label: "Ecosystems", page: expect.anything() });
  });

  it("shows the header and the scope callout, and reads coverage, the registry and the home city's page", async () => {
    const server = fakeServer();
    renderPage();
    await loaded();
    expect(screen.getByRole("heading", { level: 1, name: "Ecosystems" })).toBeInTheDocument();
    expect(screen.getByText(/^One page per city: startups in pipeline, upcoming events, your people, universities & hubs\./)).toBeInTheDocument();
    expect(screen.getByText("curated city registry plus detected coverage").parentElement).toHaveTextContent(
      "This page is a curated city registry plus detected coverage — it does not limit where Project Zero sources from.",
    );
    expect(server.calls.map((c) => `${c.method} ${c.path}`).sort()).toEqual([
      "GET /api/ecosystems/coverage",
      "GET /api/ecosystems/eco?city=Karlsruhe",
      "GET /api/ecosystems/registry",
    ]);
  });
});

describe("Ecosystems — coverage intelligence", () => {
  it("the heading, the note, the summary line and the four state counts", async () => {
    fakeServer();
    renderPage();
    await loaded();
    expect(within(panel()).getByRole("heading", { level: 3 })).toHaveTextContent("Coverage intelligence — where Project Zero can and cannot see");
    expect(within(panel()).getByText("Computed from configured sources and recorded runs.")).toBeInTheDocument();
    expect(screen.getByTestId("coverage-summary").textContent).toBe(
      "3 ecosystems · 14 configured sources declared (3 from coverage_sources.json) · Grok audit candidates: 2 declared, 0 adopted — a candidate never counts as coverage until you adopt it and a scan retrieves records",
    );
    expect(["HEALTHY", "PARTIAL", "GAP", "UNKNOWN"].map((s) => screen.getByTestId(`coverage-count-${s}`).textContent)).toEqual([
      "HEALTHY 1",
      "PARTIAL 1",
      "GAP 1",
      "UNKNOWN 0",
    ]);
  });

  it("the new-ecosystems callout lists each place with its country, signals, kinds, examples and action", async () => {
    fakeServer();
    renderPage();
    await loaded();
    const callout = screen.getByTestId("new-ecosystems");
    expect(within(callout).getByText("New ecosystems appearing in your data").tagName).toBe("B");
    expect(Array.from(callout.querySelectorAll("div")).map((d) => d.textContent)).toEqual([
      "Duneholm (XC) — 5 signals (startups, events): Kestrel Labs, Duneholm Robot Fair · add it to ecosystems.json",
      "Fernvale — 2 signals (people): a founder dinner · keep watching",
    ]);
  });

  it("no new ecosystems → no callout", async () => {
    fakeServer({}, { coverage: { ...coverage(), new_ecosystems: [] } });
    renderPage();
    await loaded();
    expect(screen.queryByTestId("new-ecosystems")).not.toBeInTheDocument();
  });

  it("the table: the family columns, state + counters per cell, candidates, last retrieval and the audit", async () => {
    fakeServer();
    renderPage();
    await loaded();
    expect(within(table()).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Ecosystem",
      "Coverage",
      "Founder formation",
      "Emerging companies",
      "Universities",
      "Last successful retrieval",
    ]);
    expect(within(table()).getAllByRole("columnheader")[4]).toHaveAttribute("title", "Universities / research spinouts");
    expect(cities()).toEqual(["Alderwick", "Brightmoor", "Cobbleton"]);
    expect(cells("Alderwick")).toEqual([
      "Alderwick Westmark · North",
      "PARTIAL12 FINDINGS — COVERAGE PARTIAL",
      "GAP0 cfg · 0 ok · 0 prod · +2 cand.",
      "HEALTHY9 cfg · 2 ok · 1 prod",
      "UNKNOWN2 cfg · 0 ok · 0 prod",
      "2026-11-10 08:00audit: GAP",
    ]);
    expect(within(row("Alderwick")).getAllByRole("cell")[2]).toHaveAttribute("title", "no source configured");
    // a family the ecosystem does not have counts zero under an empty state; no retrieval and no audit → "—"
    expect(cells("Brightmoor")).toEqual(["Brightmoor Eastland", "HEALTHY40 FINDINGS — COVERAGE HEALTHY", "HEALTHY3 cfg · 3 ok · 2 prod", "HEALTHY4 cfg · 4 ok · 4 prod", "0 cfg · 0 ok · 0 prod", "—"]);
    const tone = (el: Element) => el.querySelector("span")?.className.match(/tone_(\w+?)_/)?.[1];
    expect(within(row("Alderwick")).getAllByRole("cell").slice(1, 5).map(tone)).toEqual(["amber", "red", "green", "neutral"]);
  });

  it("the local filter matches city, country name and region", async () => {
    fakeServer();
    renderPage();
    await loaded();
    const filter = screen.getByRole("textbox", { name: "Filter ecosystems" });
    expect(filter).toHaveAttribute("placeholder", "Filter ecosystems…");
    fireEvent.change(filter, { target: { value: "WESTMARK" } });
    expect(cities()).toEqual(["Alderwick", "Cobbleton"]);
    fireEvent.change(filter, { target: { value: "south" } });
    expect(cities()).toEqual(["Cobbleton"]);
    fireEvent.change(filter, { target: { value: "bright" } });
    expect(cities()).toEqual(["Brightmoor"]);
    fireEvent.change(filter, { target: { value: "nowhere" } });
    expect(rows()).toHaveLength(0);
    fireEvent.change(filter, { target: { value: "" } });
    expect(cities()).toHaveLength(3);
  });

  it("a row opens its detail: the headline, the audit opinion and each family's sources and candidates", async () => {
    fakeServer();
    renderPage();
    await loaded();
    expect(screen.queryByTestId("coverage-detail")).not.toBeInTheDocument();
    open("Alderwick");
    expect(row("Alderwick").className).toMatch(/covSel/);
    expect(detail().firstElementChild).toHaveTextContent(
      "Alderwick — PARTIAL 12 FINDINGS — COVERAGE PARTIAL · covered: emerging_companies · missing: founder_formation, spinouts",
    );
    expect(detail()).toHaveTextContent(
      "Chief Scout coverage audit (audit 2026-10) — Alderwick region: opinion GAP · biggest blind spot: student founders — reference only; the states above are computed from configured sources and recorded runs.",
    );
    expect(family("founder_formation")).toHaveTextContent("Founder formation / talent exits GAP no source configured");
    expect(family("founder_formation")).toHaveTextContent("Candidate watchers (audit, not activated):");
    const cands = Array.from(family("founder_formation").querySelectorAll(":scope > div > div")).map((d) => d.textContent);
    expect(cands).toEqual([
      "• Alderwick Founder Guild — community page · access html Adopt as watcher",
      "• Alderwick Alumni Board — alumni list · access html · rate limited Adopt as watcher",
    ]);
    expect(within(family("founder_formation")).getByRole("link", { name: "Alderwick Founder Guild" })).toHaveAttribute("href", "https://guild.example.org/members");
    expect(within(family("founder_formation")).getByRole("link", { name: "Alderwick Founder Guild" })).toHaveAttribute("target", "_blank");
    // eight sources shown, then "… 1 more"
    const lines = Array.from(family("emerging_companies").querySelector("div")!.children).map((d) => d.textContent);
    expect(lines).toHaveLength(9);
    expect(lines[0]).toBe("Watcher 1 [discovery] — retrieved 2026-11-10 08:00 · productive (source metadata)");
    expect(lines[1]).toBe("Watcher 2 [discovery] — retrieved 2026-11-10 08:00 · no records (source metadata)");
    expect(lines[8]).toBe("… 1 more");
    expect(family("spinouts")).toHaveTextContent("Spinout list [founder_radar] — never retrieved · no records (source metadata)");
    expect(family("spinouts")).toHaveTextContent("Lab news [discovery] — never retrieved · no records · failing (coverage_sources.json)");
    // an ecosystem without an audit and without covered / missing families
    open("Cobbleton");
    expect(detail().firstElementChild).toHaveTextContent("Cobbleton — GAP 0 FINDINGS — COVERAGE GAP · covered: none · missing: none");
    expect(detail()).not.toHaveTextContent("Chief Scout coverage audit");
  });

  it("no Scout / bridge control renders on GAP or UNKNOWN families", async () => {
    const server = fakeServer();
    renderPage();
    await loaded();
    open("Alderwick");
    expect(within(family("founder_formation")).getAllByRole("button").map((b) => b.textContent)).toEqual(["Adopt as watcher", "Adopt as watcher"]);
    expect(within(family("spinouts")).queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryByText(/ask Scout/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /scout/i })).not.toBeInTheDocument();
    open("Cobbleton");
    for (const id of ["founder_formation", "emerging_companies", "spinouts"]) expect(within(family(id)).queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /scout/i })).not.toBeInTheDocument();
    expect(server.calls.some((c) => /bridge/.test(c.path))).toBe(false);
  });
});

describe("Ecosystems — adopting a candidate", () => {
  async function ready() {
    const view = renderPage();
    await loaded();
    open("Alderwick");
    return view;
  }
  const adoptGuild = () => fireEvent.click(within(family("founder_formation")).getAllByRole("button", { name: "Adopt as watcher" })[0]);

  it("Adopt → the confirmation → POST {id, confirm: true} → toast, the modal closes, coverage and Sources refetch", async () => {
    const server = fakeServer();
    const { qc } = await ready();
    qc.setQueryData([SOURCES, {}], { sources: [] });
    expect(qc.getQueryState([SOURCES, {}])?.isInvalidated).toBe(false);
    adoptGuild();
    expect(dialog()).toHaveTextContent(
      'Adopt "Alderwick Founder Guild" as a configured watcher? It stays UNKNOWN until a scan retrieves it and becomes HEALTHY only with productive records. One source, explicit — nothing else is activated.',
    );
    expect(server.adopts()).toHaveLength(0); // nothing is posted before the confirmation
    fireEvent.click(within(dialog()).getByRole("button", { name: "Adopt as watcher" }));
    expect(await screen.findByText("Adopted as watcher cov-aw-guild — stays UNKNOWN until a scan retrieves it")).toBeInTheDocument();
    expect(server.adopts()).toEqual([{ id: "cand-aw-guild", confirm: true }]);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByTestId("coverage-summary")).toHaveTextContent("2 declared, 1 adopted"));
    expect(server.reads("ecosystems/coverage")).toBe(2);
    expect(qc.getQueryState([SOURCES, {}])?.isInvalidated).toBe(true);
  });

  it("Cancel closes the confirmation without posting", async () => {
    const server = fakeServer();
    await ready();
    adoptGuild();
    fireEvent.click(within(dialog()).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(server.adopts()).toHaveLength(0);
  });

  it("an `already` answer toasts the existing watcher, as before", async () => {
    const server = fakeServer({ adopt: () => ({ status: 200, body: { ok: true, already: true, source_id: "cov-aw-earlier" } }) });
    await ready();
    adoptGuild();
    fireEvent.click(within(dialog()).getByRole("button", { name: "Adopt as watcher" }));
    expect(await screen.findByText("Adopted as watcher cov-aw-earlier —")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(server.adopts()).toEqual([{ id: "cand-aw-guild", confirm: true }]);
  });

  it("an {ok:false, error} refusal (HTTP 200) is a failure toast; the modal closes and nothing is refetched", async () => {
    const server = fakeServer({
      adopt: () => ({ status: 200, body: { ok: false, error: "access limitation recorded by the audit (login) — not adopted; keep as manual check" } }),
    });
    const { qc } = await ready();
    qc.setQueryData([SOURCES, {}], { sources: [] });
    adoptGuild();
    fireEvent.click(within(dialog()).getByRole("button", { name: "Adopt as watcher" }));
    expect(
      await screen.findByText("✕ Adopting the source failed — access limitation recorded by the audit (login) — not adopted; keep as manual check"),
    ).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(server.reads("ecosystems/coverage")).toBe(1);
    expect(qc.getQueryState([SOURCES, {}])?.isInvalidated).toBe(false);
  });

  it("a 409 before the legacy import is a failure toast too", async () => {
    fakeServer({ adopt: () => ({ status: 409, body: { ok: false, error: "legacy data not imported yet" } }) });
    await ready();
    adoptGuild();
    fireEvent.click(within(dialog()).getByRole("button", { name: "Adopt as watcher" }));
    expect(await screen.findByText("✕ Adopting the source failed — legacy data not imported yet")).toBeInTheDocument();
  });
});

describe("Ecosystems — the city registry", () => {
  it("curated chips, then detected ones; the home city is pressed; the counts and the note", async () => {
    fakeServer();
    renderPage();
    await loaded();
    expect(chips("curated").map((c) => c.textContent)).toEqual(["Karlsruhe", "Alderwick", "Brightmoor"]);
    expect(chips("detected").map((c) => c.textContent)).toEqual(["Cobbleton detected"]);
    expect(screen.getByTestId("registry-curated")).toHaveTextContent("Curated ecosystem intelligence — 3 cities with verified institutions and deeper pages");
    expect(screen.getByTestId("registry-detected")).toHaveTextContent(
      "Detected sourcing coverage — 1 more cities/regions appearing in your startup, event and people data (no curated intelligence yet)",
    );
    expect(reg()).toHaveTextContent(
      "Built from ecosystems.json and your data. Dots: startups · events · people · verified institutions. Add curated cities or institutions in ecosystems.json — no code change needed.",
    );
    expect(chip("Karlsruhe")).toHaveAttribute("aria-pressed", "true");
    expect(chip("Alderwick")).toHaveAttribute("aria-pressed", "false");
    expect(chip("Karlsruhe").className).toMatch(/cityOn/);
    expect(chip("Karlsruhe")).toHaveAttribute("title", "startups 2 · events 2 · people 1 · institutions 2 · last refresh 2026-11-01");
    expect(chip("Alderwick")).toHaveAttribute("title", "startups 1 · events 0 · people 0 · institutions 1");
  });

  it("the four dots: startups, events, people (yes) and verified institutions", async () => {
    fakeServer();
    renderPage();
    await loaded();
    expect(dots("Karlsruhe")).toEqual([true, true, true, true]);
    expect(dots("Alderwick")).toEqual([true, false, false, true]);
    expect(dots("Brightmoor")).toEqual([false, false, false, false]);
    expect(dots("Cobbleton")).toEqual([true, true, false, false]);
  });

  it("the city search filters both groups, with their empty texts", async () => {
    fakeServer();
    renderPage();
    await loaded();
    const search = screen.getByRole("textbox", { name: "Search cities" });
    expect(search).toHaveAttribute("placeholder", "Search cities…");
    fireEvent.change(search, { target: { value: "ALDER" } });
    expect(chips("curated").map((c) => c.textContent)).toEqual(["Alderwick"]);
    expect(screen.getByTestId("registry-detected")).toHaveTextContent("none detected yet — run scans, add events and people");
    fireEvent.change(search, { target: { value: "cobble" } });
    expect(chips("curated")).toHaveLength(0);
    expect(screen.getByTestId("registry-curated")).toHaveTextContent("no match");
    expect(chips("detected").map((c) => c.textContent)).toEqual(["Cobbleton detected"]);
  });

  it("a chip sets ?city= and opens that city's page", async () => {
    const server = fakeServer();
    const { router } = renderPage("/ecosystems?tab=x");
    await loaded();
    fireEvent.click(chip("Alderwick"));
    await waitFor(() => expect(within(city()).getByRole("heading", { level: 2 })).toHaveTextContent("Alderwick"));
    expect(new URLSearchParams(router.state.location.search).get("city")).toBe("Alderwick");
    expect(new URLSearchParams(router.state.location.search).get("tab")).toBe("x"); // other params are kept
    expect(chip("Alderwick")).toHaveAttribute("aria-pressed", "true");
    expect(chip("Karlsruhe")).toHaveAttribute("aria-pressed", "false");
    await waitFor(() => expect(server.calls.map((c) => c.path)).toContain("/api/ecosystems/eco?city=Alderwick"));
  });
});

describe("Ecosystems — the city page", () => {
  it("the home city by default: the coverage line, the note with the travel hours and the four panels", async () => {
    fakeServer();
    renderPage();
    await loaded();
    expect(within(city()).getByRole("heading", { level: 2 })).toHaveTextContent("Karlsruhe");
    expect(screen.getByTestId("city-coverage").textContent).toBe(
      "Coverage: startups 2 · events 2 · people 1 · universities/labs/hubs 2 · last refresh 2026-11-01",
    );
    expect(await screen.findByTestId("city-note")).toHaveTextContent("Home base — relationships here pay off over time. · ~0h from Karlsruhe");
    expect(within(city()).getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
      "Startups in pipeline (2)",
      "Upcoming events (2)",
      "Your people (1)",
      "Universities, labs & hubs",
    ]);

    const startups = sec("Startups in pipeline (2)");
    expect(within(startups).getByRole("link", { name: "Kestrel Labs" })).toHaveAttribute("href", "/conviction?company=kestrel-labs");
    expect(within(startups).getByRole("link", { name: "Otter Mill" })).toHaveAttribute("href", "/conviction?company=otter%20mill");
    expect(startups).toHaveTextContent("Robot arms for small workshops");
    expect(startups).toHaveTextContent("seed · → Manager");
    expect(startups).not.toHaveTextContent("pre-seed · → Manager");
    expect(within(startups).getByText("81").className).toMatch(/tone_green/);
    expect(within(startups).getByText("55").className).toMatch(/tone_blue/);

    const events = sec("Upcoming events (2)");
    expect(within(events).getByRole("link", { name: "Founder Breakfast" })).toHaveAttribute("href", "/events?event=ev-1");
    expect(within(events).getByRole("link", { name: "Demo Night" })).toHaveAttribute("href", "/events?event=ev%202");
    expect(events).toHaveTextContent("2026-11-20 · meetup");
    expect(within(events).getByText("80").className).toMatch(/tone_green/);
    expect(within(events).getByText("—").className).toMatch(/tone_blue/);

    const people = sec("Your people (1)");
    expect(within(people).getByRole("link", { name: "Robin Example" })).toHaveAttribute("href", "/network?person=p-1");
    expect(people).toHaveTextContent("Robin Example Founder · Kestrel Labs");
    expect(people).toHaveTextContent("Ask for the deck");

    const orgs = sec("Universities, labs & hubs");
    expect(within(orgs).getByText("university").className).toMatch(/tone_green/);
    expect(within(orgs).getByText("hub").className).toMatch(/tone_amber/);
    expect(orgs).toHaveTextContent("Robotics faculty · site ↗");
    const site = within(orgs).getAllByRole("link", { name: "site ↗" })[0];
    expect(site).toHaveAttribute("href", "https://ait.example.edu");
    expect(site).toHaveAttribute("target", "_blank");
  });

  it("a ?city= deep link opens a detected city: the detected callout and the empty panels", async () => {
    const server = fakeServer();
    renderPage("/ecosystems?city=Cobbleton");
    await loaded();
    expect(within(city()).getByRole("heading", { level: 2 })).toHaveTextContent("Cobbleton");
    expect(chip("Cobbleton")).toHaveAttribute("aria-pressed", "true");
    expect(city()).toHaveTextContent(
      "Detected city — appears in your data (startups 3 · events 1 · people 0) but has no curated institutions yet.",
    );
    expect(screen.getByTestId("city-coverage")).toHaveTextContent("Coverage: startups 3 · events 1 · people 0 · universities/labs/hubs 0 · no refresh yet");
    await waitFor(() => expect(within(city()).getAllByRole("heading", { level: 3 })).toHaveLength(4));
    expect(sec("Startups in pipeline (0)")).toHaveTextContent("None yet — that is information too.");
    expect(sec("Upcoming events (0)")).toHaveTextContent("No dated events here yet.");
    expect(sec("Your people (0)")).toHaveTextContent("Nobody here yet — an event debrief fixes that.");
    expect(sec("Universities, labs & hubs")).toHaveTextContent("—");
    expect(screen.queryByTestId("city-note")).not.toBeInTheDocument();
    expect(server.calls.map((c) => c.path)).toContain("/api/ecosystems/eco?city=Cobbleton");
  });

  it("the travel-hours note: hours from the home city when known, the note alone when not", async () => {
    fakeServer();
    renderPage("/ecosystems?city=Alderwick");
    await loaded();
    expect(await screen.findByTestId("city-note")).toHaveTextContent("A day trip by train. · ~2.5h from Karlsruhe");
    expect(city()).not.toHaveTextContent("Detected city");
    fireEvent.click(chip("Brightmoor"));
    await waitFor(() => expect(screen.getByTestId("city-note").textContent).toBe("No trip planned yet."));
  });

  it("a city outside the registry shows its page without a coverage line", async () => {
    fakeServer();
    renderPage("/ecosystems?city=Nowhereton");
    await loaded();
    expect(within(city()).getByRole("heading", { level: 2 })).toHaveTextContent("Nowhereton");
    expect(screen.queryByTestId("city-coverage")).not.toBeInTheDocument();
    expect(within(reg()).queryAllByRole("button", { pressed: true })).toHaveLength(0);
  });
});

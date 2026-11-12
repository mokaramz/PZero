import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ALL_ITEMS } from "@/app/nav";
import { fakeServer, payload, renderPage, sources, type Answer } from "./test/server";

const table = () => screen.getByTestId("source-table");
const rows = () => within(table()).queryAllByRole("row").slice(1);
const names = () => rows().map((r) => within(r).getAllByRole("button")[0].textContent);
const row = (name: string) => rows().find((r) => r.textContent?.includes(name))!;
const cells = (name: string) => within(row(name)).getAllByRole("cell").map((c) => c.textContent);
const checkbox = (name: string) => within(table()).getByRole("checkbox", { name: `Enable ${name}` }) as HTMLInputElement;
const detail = () => screen.getByTestId("source-detail");
const sections = () => within(detail()).getAllByRole("heading", { level: 4 }).map((h) => h.textContent);
const section = (title: string) => within(detail()).getByRole("heading", { level: 4, name: title }).nextElementSibling as HTMLElement;
const matrix = () => screen.getByTestId("coverage-matrix");
const matrixRows = () =>
  within(matrix())
    .getAllByRole("row")
    .slice(1)
    .map((r) => [within(r).getByRole("rowheader").textContent, ...within(r).getAllByRole("cell").map((c) => c.textContent)]);
const tab = (name: string) => screen.getByRole("tab", { name });

async function loaded(n = 3) {
  await waitFor(() => expect(rows()).toHaveLength(n));
}

function select(name: string) {
  fireEvent.click(within(row(name)).getByRole("button", { name }));
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("Sources — the page", () => {
  it("is a ported nav view at /sources", () => {
    expect(ALL_ITEMS.find((i) => i.legacyView === "src")).toMatchObject({ path: "/sources", label: "Sources", page: expect.anything() });
  });

  it("makes ONE call (no inbox read) and shows the header, the workspace row and the method block", async () => {
    const server = fakeServer();
    renderPage();
    await loaded();
    expect(screen.getByRole("heading", { level: 1, name: "Sources" })).toBeInTheDocument();
    expect(screen.getByText("Where Project Zero gets its edge.")).toBeInTheDocument();
    expect(screen.getByText("Shared with Deal Flow — the registry table and coverage matrix follow the workspace.")).toBeInTheDocument();
    expect(within(screen.getByRole("tablist", { name: "Workspace" })).getAllByRole("tab").map((t) => t.textContent)).toEqual([
      "Europe",
      "North America",
      "All workspaces",
    ]);
    expect(screen.getByText("How Project Zero sources")).toBeInTheDocument();
    expect(screen.getByText("Project Zero does NOT search the whole internet or LinkedIn.")).toBeInTheDocument();
    expect(server.calls.map((c) => `${c.method} ${c.path}`)).toEqual(["GET /api/sources"]);
  });

  it("the health summary counts every configured source (not just the workspace's) by the health rules", async () => {
    fakeServer();
    renderPage();
    await loaded();
    const sum = screen.getByTestId("source-health");
    const tiles = Array.from(sum.children)
      .slice(0, 4)
      .map((t) => t.textContent);
    expect(tiles).toEqual(["1healthy", "2warning", "1failed", "1disabled"]);
    expect(sum.lastElementChild).toHaveTextContent(
      "5 sources configured · 4 enabled · 1 failing · 2 with a warning or not yet scanned — recorded calmly and retried on the next scan",
    );
    expect(screen.getByRole("heading", { level: 3, name: /Source registry/ })).toHaveTextContent("Source registry 4 enabled of 5");
  });

  it("an all-healthy registry says so without the warning tail", async () => {
    fakeServer({}, payload([sources()[0]]));
    renderPage();
    await loaded(1);
    expect(screen.getByTestId("source-health").lastElementChild?.textContent).toBe("1 sources configured · 1 enabled · no failing sources");
  });

  it("the table columns, the quality counters and the Fb. prio column (adjustment when active, else reviewed / minimum)", async () => {
    fakeServer();
    renderPage();
    await loaded();
    expect(within(table()).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Source",
      "Type",
      "Geo",
      "Sectors",
      "Rel.",
      "Health",
      "Last OK",
      "Found",
      "Attn",
      "Res.",
      "Kept",
      "Sent",
      "Manager ±",
      "Fb. prio",
      "On",
    ]);
    expect(cells("Alpine Grant Board (DACH)")).toEqual([
      "Alpine Grant Board (DACH)",
      "api",
      "DACH/EU",
      "ai, robotics +1",
      "hig",
      "ok",
      "11-11 07:30",
      "20",
      "8",
      "6",
      "3",
      "2",
      "1 / 1",
      "+2",
      "",
    ]);
    expect(cells("Fjord Accelerator Feed")).toEqual(["Fjord Accelerator Feed", "rss", "NORD", "climate", "med", "warn", "11-09 18:05", "5", "0", "0", "1", "0", "0 / 0", "0 · 2/5", ""]);
    expect(cells("Quiet Ridge Watcher")).toEqual(["Quiet Ridge Watcher", "watcher", "UK", "fintech", "", "off", "09-01 10:00", "0", "0", "0", "0", "0", "0 / 0", "0 · 0/5", ""]);
    expect(within(row("Fjord Accelerator Feed")).getAllByRole("cell")[5]).toHaveAttribute("title", "Warning — 1 recent failure");
    expect(within(row("Fjord Accelerator Feed")).getAllByRole("cell")[13]).toHaveAttribute("title", "2 of 5 reviewed");
    expect(checkbox("Alpine Grant Board (DACH)").checked).toBe(true);
    expect(checkbox("Quiet Ridge Watcher").checked).toBe(false);
  });

  it("the minimum reviewed count comes from the payload", async () => {
    fakeServer({}, { ...payload(), feedback_min_reviewed: 8 });
    renderPage();
    await loaded();
    expect(cells("Fjord Accelerator Feed")[13]).toBe("0 · 2/8");
  });
});

describe("Sources — the workspace", () => {
  it("defaults to Europe: only sources tagged with a Europe geo", async () => {
    fakeServer();
    renderPage();
    await loaded();
    expect(tab("Europe")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("src-ws-note")).toHaveTextContent("Europe workspace");
    expect(names()).toEqual(["Alpine Grant Board (DACH)", "Fjord Accelerator Feed", "Quiet Ridge Watcher"]);
  });

  it("reads the Deal Flow workspace preference, and a change is remembered for Deal Flow too", async () => {
    localStorage.setItem("pz:workspace", JSON.stringify("na"));
    fakeServer();
    renderPage();
    await loaded(2);
    expect(tab("North America")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("src-ws-note")).toHaveTextContent("North America workspace");
    expect(names()).toEqual(["Harbor Lab Spinouts", "Maple Seed Registry"]);
    expect(cells("Maple Seed Registry")[6]).toBe(""); // "never".slice(5), as before
    fireEvent.click(tab("All workspaces"));
    await loaded(5);
    expect(screen.getByTestId("src-ws-note")).toHaveTextContent("all workspaces");
    expect(localStorage.getItem("pz:workspace")).toBe('"all"');
  });

  it("Deal Flow's Unresolved view shows all sources here", async () => {
    localStorage.setItem("pz:workspace", JSON.stringify("unk"));
    fakeServer();
    renderPage();
    await loaded(5);
    expect(tab("All workspaces")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("src-ws-note")).toHaveTextContent("all workspaces");
  });

  it("without ws_geos in the payload the default workspace geos apply", async () => {
    const { ws_geos: _drop, ...rest } = payload();
    fakeServer({}, rest);
    renderPage();
    await loaded(3); // DACH, NORD and UK are Europe by default
    expect(names()).toEqual(["Alpine Grant Board (DACH)", "Fjord Accelerator Feed", "Quiet Ridge Watcher"]);
  });
});

describe("Sources — the detail aside", () => {
  it("the first row is selected; the sections come in the old order", async () => {
    fakeServer();
    renderPage();
    await loaded();
    expect(within(detail()).getByText("Alpine Grant Board (DACH)")).toBeInTheDocument();
    expect(sections()).toEqual([
      "What it monitors",
      "Why it matters",
      "Current health",
      "Coverage",
      "Recent yield",
      "Feedback-adjusted sourcing priority",
      "Quality funnel",
      "Limitations / known issues",
      "Latest scan result",
    ]);
    expect(screen.getByRole("complementary", { name: "Source detail" })).toContainElement(detail());
    expect(within(detail()).getByText("API")).toBeInTheDocument();
    expect(within(detail()).getByText("HIGH RELIABILITY")).toBeInTheDocument();
    expect(within(detail()).getByText("PRE COMPANY")).toBeInTheDocument();
    expect(within(detail()).getByText("DACH, EU · ai, robotics, energy · weekly")).toBeInTheDocument();
    expect(within(section("What it monitors")).getByRole("link", { name: "grants.example.org/alpine/awards ↗" })).toHaveAttribute(
      "href",
      "https://grants.example.org/alpine/awards",
    );
    expect(section("What it monitors")).toHaveTextContent("parser: json_awards");
    expect(section("Why it matters")).toHaveTextContent("Public award list of a regional deep-tech grant.");
    expect(section("Current health")).toHaveTextContent("Healthy");
    expect(section("Current health")).toHaveTextContent("last successful scan: 2026-11-11 07:30 · last count: 14 · consecutive failures: 0");
    expect(within(section("Current health")).getByRole("button", { name: "Disable source" })).toBeEnabled();
    expect(Array.from(section("Coverage").firstElementChild!.children).map((t) => t.textContent)).toEqual(["DACH", "EU", "ai", "robotics", "energy"]);
    expect(section("Coverage")).toHaveTextContent("scope: country");
    expect(section("Recent yield")).toHaveTextContent("kept 3 · research 5 · rejected 6 · last scan returned 14");
    expect(section("Feedback-adjusted sourcing priority")).toHaveTextContent("+2 4 kept of 7 reviewed");
    expect(section("Feedback-adjusted sourcing priority")).toHaveTextContent("adjusted after 5 reviewed companies");
    expect(section("Feedback-adjusted sourcing priority")).toHaveTextContent("capped at ±3.");
    const funnel = Array.from(section("Quality funnel").firstElementChild!.children).map((r) => r.textContent);
    expect(funnel).toEqual(["found20", "attention8", "researched6", "kept3", "radar2", "sent to team2", "Manager +1", "Manager −1"]);
    expect(section("Limitations / known issues")).toHaveTextContent("None recorded.");
    expect(section("Latest scan result")).toHaveTextContent("OK 14 rows parsed"); // matched by the name before " ("
  });

  it("clicking a row selects it; a sparse source shows the empty texts", async () => {
    localStorage.setItem("pz:workspace", JSON.stringify("na"));
    fakeServer();
    renderPage();
    await loaded(2);
    select("Maple Seed Registry");
    await waitFor(() => expect(within(detail()).getByText("Maple Seed Registry")).toBeInTheDocument());
    expect(section("What it monitors")).toHaveTextContent("no URL");
    expect(section("Why it matters")).toHaveTextContent("No description on file.");
    expect(section("Current health")).toHaveTextContent("Not yet scanned");
    expect(section("Current health")).toHaveTextContent("last successful scan: never · last count: — · consecutive failures: 0");
    expect(section("Recent yield").textContent).toBe("kept 0 · research 0 · rejected 0");
    expect(section("Feedback-adjusted sourcing priority")).toHaveTextContent("0 neutral");
    expect(section("Limitations / known issues")).toHaveTextContent("A recent failure or no scan yet; monitored on the next run.");
    expect(section("Latest scan result")).toHaveTextContent("No entry in the last scan report.");
  });

  it("the limitations text: partial / lazy notes win; the latest scan result matches the name before ' ('", async () => {
    localStorage.setItem("pz:workspace", JSON.stringify("na"));
    fakeServer();
    renderPage();
    await loaded(2);
    expect(within(detail()).getByText("Harbor Lab Spinouts")).toBeInTheDocument();
    expect(section("Current health")).toHaveTextContent("Failing — 3 consecutive failures");
    expect(section("Limitations / known issues")).toHaveTextContent("Lists only a partial cohort; older entries load lazily.");
    expect(section("Latest scan result")).toHaveTextContent("SKIPPED page unchanged");
  });

  it("an exact-name scan row and a warning source", async () => {
    fakeServer();
    renderPage();
    await loaded();
    select("Fjord Accelerator Feed");
    await waitFor(() => expect(within(detail()).getByText("Fjord Accelerator Feed")).toBeInTheDocument());
    expect(section("Latest scan result")).toHaveTextContent("FAIL feed timed out");
    expect(section("Limitations / known issues")).toHaveTextContent("A recent failure or no scan yet; monitored on the next run.");
    expect(within(detail()).getByText("MEDIUM RELIABILITY")).toBeInTheDocument();
  });

  it("a failing source shows the failure sentence when its notes do not explain it", async () => {
    const list = sources().map((s) => (s.id === "s-harbor" ? { ...s, notes: "University spinout page." } : s));
    localStorage.setItem("pz:workspace", JSON.stringify("na"));
    fakeServer({}, payload(list));
    renderPage();
    await loaded(2);
    expect(section("Limitations / known issues")).toHaveTextContent(
      "Consecutive failures — the site may have changed or be unreachable; the scan retries automatically and nothing is invented.",
    );
  });

  it("no Scout Bridge control, even for a source failing 3 times in a row", async () => {
    localStorage.setItem("pz:workspace", JSON.stringify("na"));
    const server = fakeServer();
    renderPage();
    await loaded(2);
    expect(within(detail()).getByText("Harbor Lab Spinouts")).toBeInTheDocument();
    expect(within(detail()).getByText("US · bio")).toBeInTheDocument();
    expect(screen.queryByText(/Scout 00/)).toBeNull();
    expect(screen.queryByText(/replacement/)).toBeNull();
    expect(within(detail()).getAllByRole("button").map((b) => b.textContent)).toEqual(["Disable source"]);
    expect(server.calls.some((c) => c.path.includes("bridge"))).toBe(false);
  });

  it("a disabled source says so in its health", async () => {
    fakeServer();
    renderPage();
    await loaded();
    select("Quiet Ridge Watcher");
    await waitFor(() => expect(within(detail()).getByText("Quiet Ridge Watcher")).toBeInTheDocument());
    expect(section("Current health")).toHaveTextContent("Disabled");
    expect(section("Current health")).toHaveTextContent("consecutive failures: 0 · disabled");
    expect(within(section("Current health")).getByRole("button", { name: "Enable source" })).toBeInTheDocument();
    expect(within(detail()).getByText("WATCHER")).toBeInTheDocument();
  });
});

describe("Sources — coverage and lists", () => {
  it("the coverage matrix: thresholds, the potential tail and the workspace's rows", async () => {
    fakeServer();
    renderPage();
    await loaded();
    expect(within(matrix()).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["", "AI", "Robotics"]);
    expect(matrixRows()).toEqual([
      ["DACH", "4.5", "1.0 /3.0"],
      ["Nordics", "2.5", "— /1.5"],
      ["United Kingdom", "—", "—"],
    ]);
    const levels = within(matrix())
      .getAllByRole("cell")
      .map((c) => c.getAttribute("data-level"));
    expect(levels).toEqual(["strong", "weak", "ok", "none", "none", "none"]);
    expect(within(matrix()).getAllByRole("cell")[1]).toHaveAttribute("title", "verified 1.0 of potential 3.0");
    fireEvent.click(tab("North America"));
    await loaded(2);
    expect(matrixRows()).toEqual([
      ["United States", "2.0", "4.0"],
      ["Canada", "0.5", "—"],
    ]);
    expect(
      within(matrix())
        .getAllByRole("cell")
        .map((c) => c.getAttribute("data-level")),
    ).toEqual(["ok", "strong", "weak", "none"]);
    fireEvent.click(tab("All workspaces"));
    await loaded(5);
    expect(matrixRows().map((r) => r[0])).toEqual(["DACH", "Nordics", "United Kingdom", "United States", "Canada"]);
    expect(screen.getByText("Bold = VERIFIED")).toBeInTheDocument();
  });

  it("the manual sources, watched pages and feeds come from the same payload", async () => {
    fakeServer();
    renderPage();
    await loaded();
    const manual = screen.getByTestId("manual-sources");
    expect(manual).toHaveTextContent("Manual & relationship sources — the real edge lives here; no tool can do these");
    expect(manual).toHaveTextContent("Lakeside founder dinnersopen ↗Ask two hosts each month who is leaving to build.");
    expect(within(manual).getAllByRole("link", { name: "open ↗" }).map((a) => a.getAttribute("href"))).toEqual([
      "https://dinners.example.org",
      "https://alumni.example.org",
    ]);
    const checked = screen.getByTestId("checked-sources");
    expect(within(checked).getByRole("heading", { level: 3 })).toHaveTextContent("What the button checks");
    expect(checked).toHaveTextContent("Cedar Institute ventures pagePRE-COMPANY · the edgePage watcher: we detect new text, you read it. Archetypes 3, 7. open ↗");
    expect(within(checked).getByRole("link", { name: "open ↗" })).toHaveAttribute("href", "https://cedar.example.edu/ventures");
    expect(checked).toHaveTextContent(
      "Northwind funding newsANNOUNCEMENT · discovery onlyRSS feed of funding/spinout news. Usually recently funded → low urgency, relationship value.",
    );
  });
});

describe("Sources — enable / disable", () => {
  it("the table checkbox flips the row at once, posts {id, enabled}, toasts and refetches", async () => {
    let release: () => void = () => {};
    const server = fakeServer({ toggle: () => new Promise<Answer | undefined>((r) => (release = () => r(undefined))) });
    renderPage();
    await loaded();
    fireEvent.click(checkbox("Alpine Grant Board (DACH)"));
    await waitFor(() => expect(server.toggles()).toEqual([{ id: "s-alpine", enabled: false }]));
    expect(checkbox("Alpine Grant Board (DACH)").checked).toBe(false); // optimistic, before the server answers
    expect(within(detail()).getByRole("button", { name: "Enable source" })).toBeDisabled(); // in flight
    release();
    expect(await screen.findByText("Source disabled")).toBeInTheDocument();
    expect(screen.getByText("✓ Switching the source — done")).toBeInTheDocument();
    await waitFor(() => expect(server.reads()).toBe(2));
    expect(checkbox("Alpine Grant Board (DACH)").checked).toBe(false);
  });

  it("the detail button switches the selected source", async () => {
    const server = fakeServer();
    renderPage();
    await loaded();
    select("Quiet Ridge Watcher");
    fireEvent.click(await within(detail()).findByRole("button", { name: "Enable source" }));
    await waitFor(() => expect(checkbox("Quiet Ridge Watcher").checked).toBe(true));
    expect(await screen.findByText("Source enabled")).toBeInTheDocument();
    expect(server.toggles()).toEqual([{ id: "s-ridge", enabled: true }]);
    await waitFor(() => expect(server.reads()).toBe(2));
    expect(server.stored().sources.find((s) => s.id === "s-ridge")?.enabled).toBe(true);
    expect(within(detail()).getByRole("button", { name: "Disable source" })).toBeEnabled();
    expect(screen.getByTestId("source-health").lastElementChild).toHaveTextContent("5 sources configured · 5 enabled");
  });

  it("a refused toggle refetches, so the row shows what the server holds", async () => {
    const server = fakeServer({ toggle: () => ({ status: 500, body: { ok: false, error: "registry locked" } }) });
    renderPage();
    await loaded();
    fireEvent.click(checkbox("Fjord Accelerator Feed"));
    expect(await screen.findByText(/✕ Switching the source failed/)).toBeInTheDocument();
    expect(server.toggles()).toEqual([{ id: "s-fjord", enabled: false }]);
    await waitFor(() => expect(server.reads()).toBe(2));
    await waitFor(() => expect(checkbox("Fjord Accelerator Feed").checked).toBe(true));
    expect(screen.queryByText("Source disabled")).toBeNull();
  });
});

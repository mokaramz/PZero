import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ALL_ITEMS } from "@/app/nav";
import { sig } from "@/features/conviction/test/fixtures";
import { emptySlotsLabel } from "./model/slots";
import { fakeServer, radar, renderPage } from "./test/server";

const HIGH = "High-confidence (8 slots) — fully verified only";
const EMERGING = "Emerging / adjacent thesis (1 slot) — fully verified only";
const WILDCARD = "Wildcard — outlier route (1 slot) — fully verified only";
const QUEUE = "Research Queue — promising (Provisional ≥ 65) but NOT verified; do the 10-minute checks to promote";
const GATED = "Conflict-gated — for Manager, not for forwarding";
const WATCH = "Watchlist (50–64)";

const region = (name: string) => screen.getByRole("region", { name });
const cards = (name: string) => within(region(name)).queryAllByTestId("radar-card");
const card = (company: string) => screen.getByRole("link", { name: company }).closest("article") as HTMLElement;

async function loaded() {
  await waitFor(() => expect(screen.getAllByTestId("radar-card").length).toBeGreaterThan(0));
}

afterEach(() => vi.unstubAllGlobals());

describe("Radar — the page", () => {
  it("is a ported nav view at /radar", () => {
    expect(ALL_ITEMS.find((i) => i.legacyView === "radar")).toMatchObject({ path: "/radar", label: "Radar", page: expect.anything() });
  });

  it("shows the 8 / 1 / 1 slots, each section's empty slots as one quiet line, and hides the empty lists", async () => {
    const server = fakeServer();
    renderPage();
    await loaded();
    expect(screen.getByRole("heading", { level: 1, name: "PROJECT A RADAR — TOP 10" })).toBeInTheDocument();
    expect(screen.getByText("Fully verified companies only, ranked by Verified score — empty slots stay empty on purpose.")).toBeInTheDocument();
    // the method is one click below, collapsed
    const method = screen.getByTestId("radar-method") as HTMLDetailsElement;
    expect(method.open).toBe(false);
    fireEvent.click(within(method).getByText("How the radar is built"));
    await waitFor(() => expect(method).toHaveTextContent("Conflict-gated companies are listed for Manager, never forwarded."));

    expect(cards(HIGH).map((c) => within(c).getByRole("link").textContent)).toEqual(["Zentro", "Lumora"]);
    const highEmpty = within(region(HIGH)).getByTestId("radar-empty");
    expect(highEmpty).toHaveAttribute("data-empty", "6");
    expect(highEmpty).toHaveTextContent("Slots 3–8: empty — no candidate met the bar (left empty on purpose)");
    expect(cards(EMERGING)).toEqual([]);
    expect(within(region(EMERGING)).getByTestId("radar-empty")).toHaveTextContent("Slot 1: empty — no candidate met the bar (left empty on purpose)");
    expect(within(region(EMERGING)).getByTestId("radar-empty")).toHaveAttribute("data-empty", "1");
    expect(cards(WILDCARD)).toHaveLength(1);
    expect(within(region(WILDCARD)).queryByTestId("radar-empty")).not.toBeInTheDocument();
    // the research queue has a company; the conflict-gated list and the watchlist are empty, so they are not shown
    expect(cards(QUEUE)).toHaveLength(1);
    expect(screen.queryByRole("region", { name: GATED })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: WATCH })).not.toBeInTheDocument();
    expect(server.calls).toEqual(expect.arrayContaining(["GET /api/conviction/radar", "GET /api/conviction/meta"]));
  });

  it("shows the conflict-gated list and the watchlist when they have companies; a fully empty Radar names every slot", async () => {
    fakeServer({ ...radar(), high: [], wildcard: [], gated: [sig("tessaly", 81, { conflict: "potential_conflict", twin: "Portfolio Co" })], watch: [sig("orvane", 55)] });
    renderPage();
    await loaded();
    expect(cards(GATED)).toHaveLength(1);
    expect(cards(WATCH)).toHaveLength(1);
    expect(within(card("Tessaly")).getByText("Portfolio Co — Potential conflict", { exact: false })).toBeInTheDocument();
    expect(within(region(HIGH)).getByTestId("radar-empty")).toHaveTextContent("Slots 1–8: empty");
    expect(within(region(WILDCARD)).getByTestId("radar-empty")).toHaveTextContent("Slot 1: empty");
  });

  it("names the exact empty slots", () => {
    expect(emptySlotsLabel(0, 8)).toBe("Slots 1–8");
    expect(emptySlotsLabel(7, 8)).toBe("Slot 8");
    expect(emptySlotsLabel(0, 1)).toBe("Slot 1");
  });
});

describe("Radar — a card", () => {
  it("links to the company in Conviction", async () => {
    fakeServer();
    const { router } = renderPage();
    await loaded();
    const link = screen.getByRole("link", { name: "Zentro" });
    expect(link).toHaveAttribute("href", "/conviction?company=zentro");
    fireEvent.click(link);
    await waitFor(() => expect(router.state.location.pathname).toBe("/conviction"));
    expect(router.state.location.search).toBe("?company=zentro");
    expect(screen.getByText("conviction page")).toBeInTheDocument();
  });

  it("a verified company shows its verified score; an unverified one is PROVISIONAL with what is missing", async () => {
    fakeServer();
    renderPage();
    await loaded();
    const z = card("Zentro");
    expect(z).toHaveTextContent("82verified");
    expect(z).not.toHaveTextContent("PROVISIONAL");
    const b = card("Brindle");
    expect(b).toHaveTextContent("68PROVISIONAL · unverified: founders, traction, funding");
  });

  it("shows WHY PROJECT A, WHY NOW and NEXT ACTION first and the rest behind one click", async () => {
    fakeServer();
    renderPage();
    await loaded();
    const z = card("Zentro");
    expect(z).toHaveTextContent("WHY PROJECT A: Vertical agent for freight brokers");
    expect(z).toHaveTextContent("WHY NOW: EU customs rules change in 2027");
    // an operator state from a prepared case replaces the recorded next action
    expect(z).toHaveTextContent("NEXT ACTION: READY — Contact the founder");
    const more = z.querySelector("details") as HTMLDetailsElement;
    expect(more.open).toBe(false);
    expect(within(more).getByText("Founder, timing, portfolio & what to verify")).toBeInTheDocument();
    expect(more).toHaveTextContent("WHY FOUND: EU-Startups · Manual");
    expect(more).toHaveTextContent("FOUNDER SIGNAL: Second-time founder");
    expect(more).toHaveTextContent("EARLINESS · TIMING: Pre-seed · timing unknown —");
    expect(more).toHaveTextContent("PORTFOLIO: no twin — None");
    expect(more).toHaveTextContent("WHAT I NEED TO VERIFY: cap table; pilot contracts");
    // a mere score band never replaces the recorded next action
    expect(card("Lumora")).toHaveTextContent("NEXT ACTION: Book a call with Lumora");
  });

  it("'N sources' opens the company's real convergence trace; one source draws none", async () => {
    fakeServer();
    renderPage();
    await loaded();
    const z = card("Zentro");
    const toggle = within(z).getByRole("button", { name: "3 sources" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByTestId("radar-convergence")).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(z).toHaveAttribute("data-selected", "true");
    expect(within(z).getByTestId("radar-convergence")).toHaveTextContent("3 independent inputs converge");
    fireEvent.click(toggle);
    expect(z).not.toHaveAttribute("data-selected");
    expect(screen.queryByTestId("radar-convergence")).not.toBeInTheDocument();
    expect(within(card("Lumora")).queryByRole("button", { name: /sources/ })).not.toBeInTheDocument();
  });
});

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TODAY } from "@/features/network/test/fixtures";
import { fakeServer, renderWatchlist } from "@/features/network/test/server";

const rows = () => screen.queryAllByTestId("watch-row");
const row = (name: string) => rows().find((r) => r.textContent?.includes(name))!;

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("Watchlist — the people table", () => {
  it("lists the watched people with their public signal links and the last check", async () => {
    const server = fakeServer();
    renderWatchlist();
    await waitFor(() => expect(rows()).toHaveLength(2));
    expect(screen.getByRole("heading", { level: 1, name: "Signal watchlist" })).toBeInTheDocument();
    expect(screen.getByText(/Manual-first and ToS-safe:/)).toBeInTheDocument();
    expect(screen.getByText(/Add someone to the watchlist via Network → open person → tick "Watch"/)).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Person", "Why watching", "Public signal links", "Last checked", "Log a signal"]);

    const jonas = row("Jonas Albrecht");
    expect(within(jonas).getByRole("link", { name: "Jonas Albrecht" })).toHaveAttribute("href", "/network?person=p-jonas-albrecht");
    expect(jonas).toHaveTextContent("CTO · Aereus");
    expect(jonas).toHaveTextContent("Built the flight stack at a drone startup");
    expect(jonas).toHaveTextContent("never");
    const links = within(jonas)
      .getAllByRole("link")
      .slice(1)
      .map((a) => [a.textContent, a.getAttribute("href")]);
    expect(links).toEqual([
      ["Google", "https://www.google.com/search?q=Jonas%20Albrecht"],
      ["News", "https://news.google.com/search?q=Jonas%20Albrecht"],
      ["GitHub", "https://github.com/search?q=Jonas%20Albrecht&type=users"],
      ["Scholar", "https://scholar.google.com/scholar?q=Jonas%20Albrecht"],
    ]);
    for (const a of within(jonas).getAllByRole("link").slice(1)) {
      expect(a).toHaveAttribute("target", "_blank");
      expect(a).toHaveAttribute("rel", "noreferrer");
    }
    // their own profiles follow when on record
    const sofia = row("Sofia Brandt");
    expect(within(sofia).getByRole("link", { name: "LinkedIn" })).toHaveAttribute("href", "https://www.linkedin.com/in/sofia-brandt");
    expect(within(sofia).getByRole("link", { name: "X" })).toHaveAttribute("href", "https://x.com/sofiab");
    expect(sofia).toHaveTextContent("Google · News · GitHub · Scholar · LinkedIn · X");
    expect(server.posts()).toEqual([]);
  });

  it("Log & mark checked posts {id, note}, says what it did and clears the input; an empty note only marks checked", async () => {
    const server = fakeServer();
    renderWatchlist();
    await waitFor(() => expect(rows()).toHaveLength(2));
    fireEvent.change(screen.getByLabelText("Signal for Jonas Albrecht"), { target: { value: "new repo: e2e" } });
    fireEvent.click(within(row("Jonas Albrecht")).getByRole("button", { name: "Log & mark checked" }));
    await screen.findByText("Signal logged");
    expect(server.posts("watch_log").map((c) => c.body)).toEqual([{ id: "p-jonas-albrecht", note: "new repo: e2e" }]);
    await waitFor(() => expect(row("Jonas Albrecht")).toHaveTextContent(TODAY));
    expect(screen.getByLabelText("Signal for Jonas Albrecht")).toHaveValue("");

    fireEvent.click(within(row("Sofia Brandt")).getByRole("button", { name: "Log & mark checked" }));
    await screen.findByText("Marked checked");
    expect(server.posts("watch_log")[1].body).toEqual({ id: "p-sofia-brandt", note: "" });
    await waitFor(() => expect(server.reads("/api/network/watchlist")).toBeGreaterThanOrEqual(3));
  });

  it("a refused log keeps the note", async () => {
    const server = fakeServer({ watchLog: () => ({ status: 404, body: { ok: false, error: "unknown person" } }) });
    renderWatchlist();
    await waitFor(() => expect(rows()).toHaveLength(2));
    fireEvent.change(screen.getByLabelText("Signal for Jonas Albrecht"), { target: { value: "left the company" } });
    fireEvent.click(within(row("Jonas Albrecht")).getByRole("button", { name: "Log & mark checked" }));
    await screen.findByText(/unknown person/);
    expect(server.posts("watch_log")).toHaveLength(1);
    expect(screen.queryByText("Signal logged")).toBeNull();
    expect(screen.getByLabelText("Signal for Jonas Albrecht")).toHaveValue("left the company");
    expect(row("Jonas Albrecht")).toHaveTextContent("never");
  });

  it("an empty watchlist says how to add someone", async () => {
    fakeServer({ people: [] });
    renderWatchlist();
    expect(await screen.findByText(/Watchlist empty\. People → open a person → tick Watch\./)).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("Watchlist — the watched companies panel (review 037a)", () => {
  it("sits above the people table and reads the WATCH view (its controls are covered by WatchedCompanies.test.tsx)", async () => {
    const server = fakeServer();
    renderWatchlist();
    await waitFor(() => expect(rows()).toHaveLength(2));
    const panel = screen.getByTestId("watched-companies");
    await waitFor(() => expect(within(panel).getAllByTestId("watched-company")).toHaveLength(3));
    expect(panel.compareDocumentPosition(screen.getByRole("table")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(server.calls.map((c) => c.path).sort()).toEqual(["/api/network/watchlist", "/api/watch"]);
  });
});

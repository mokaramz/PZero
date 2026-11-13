/**
 * The Deal Flow candidate detail's "On WATCH — sensors" section (review 037a, the old `WatchSection`): a WATCH
 * candidate's pages line (with pages, and without), the "manage on Watchlist" link, its triggers with Reviewed /
 * Dismiss (the same TriggerList and invalidations as the Watchlist), the loading text, "Check now"'s one deferral
 * wording, and no read at all for a candidate that is not on WATCH. Invented names only (`watchlist/test/*.json`).
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ACK_KEYS } from "@/features/watchlist/api";
import { watchInbox, watchWorld } from "@/features/watchlist/test/fakeWatch";
import type { InboxPayload } from "./model/types";
import { fakeServer, gate, renderPage, type Routes } from "./test/server";

const section = () => screen.getByTestId("watch-section");
const detailName = () => within(screen.getByTestId("cand-detail")).getByRole("heading", { level: 2 }).textContent;
const triggers = () => within(section()).queryAllByTestId("watch-trigger");

function serve(over: Partial<Routes> = {}) {
  return fakeServer({ inbox: () => watchInbox() as InboxPayload, watch: {}, ...over });
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("Deal Flow — the WATCH section", () => {
  it("a WATCH candidate with pages: the heading, the pages line, the Watchlist link, the deferral and its triggers", async () => {
    const server = serve();
    renderPage("/deal-flow?candidate=c-wt-01");
    await waitFor(() => expect(detailName()).toBe("Halvard Optics"));
    await waitFor(() => expect(triggers()).toHaveLength(4));
    expect(within(section()).getByRole("heading", { level: 4 })).toHaveTextContent("On WATCH — sensors");
    expect(section()).toHaveTextContent("2 official page(s) watched · manage on Watchlist");
    expect(within(section()).getByRole("link", { name: "manage on Watchlist" })).toHaveAttribute("href", "/watchlist");
    expect(within(section()).getByTestId("watch-checks-deferred")).toHaveTextContent(/^Page checks arrive with the WATCH sensors port\.$/);
    expect(section()).not.toHaveTextContent("Loading watch state…");
    expect(triggers().map((t) => t.getAttribute("data-status"))).toEqual(["new", "new", "dismissed", "reviewed"]);
    expect(triggers()[0]).toHaveTextContent("· page check · first seen 2026-11-12 · dated 2026-11-10");
    expect(triggers()[1]).toHaveTextContent("· new source in a scan · first seen 2026-11-11");
    // the old section has no Check now: nothing here can start a page check
    expect(within(section()).queryByRole("button", { name: "Check now" })).toBeNull();
    expect(server.posts()).toEqual([]);
    expect(server.gets("/api/watch")).toBe(1);
  });

  it("a WATCH candidate without pages says scans still watch for new sources", async () => {
    serve();
    renderPage("/deal-flow?candidate=c-wt-03");
    await waitFor(() => expect(detailName()).toBe("Quellbrook Labs"));
    await waitFor(() => expect(triggers()).toHaveLength(1));
    expect(section()).toHaveTextContent("No official pages attached yet — scans still watch for new sources · manage on Watchlist");
    expect(triggers()[0]).toHaveTextContent(/· reviewed$/);
    expect(within(section()).queryAllByRole("button")).toHaveLength(0);
  });

  it("Reviewed posts {id, status}, toasts, and the section shows the new status after the refetch", async () => {
    const server = serve();
    const { qc } = renderPage("/deal-flow?candidate=c-wt-01");
    await waitFor(() => expect(triggers()).toHaveLength(4));
    const spy = vi.spyOn(qc, "invalidateQueries");
    fireEvent.click(within(triggers()[0]).getByRole("button", { name: "Reviewed" }));
    await screen.findByText("Trigger updated (kept on record)");
    expect(server.posts()).toEqual([{ method: "POST", path: "/api/watch_ack", body: { id: "wt-a1b2c3d4e5f6", status: "reviewed" } }]);
    await waitFor(() => expect(triggers()[0]).toHaveTextContent(/· reviewed$/));
    expect(server.gets("/api/watch")).toBe(2);
    const keys = spy.mock.calls.map((c) => ((c[0] as { queryKey?: unknown[] } | undefined)?.queryKey ?? [])[0]);
    expect(keys).toEqual(expect.arrayContaining(ACK_KEYS));

    fireEvent.click(within(triggers()[1]).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(server.posts()).toHaveLength(2));
    expect(server.posts()[1].body).toEqual({ id: "wt-b2c3d4e5f6a7", status: "dismissed" });
    await waitFor(() => expect(triggers()[1]).toHaveTextContent(/· dismissed$/));
    expect(detailName()).toBe("Halvard Optics"); // an acknowledgement never changes the Deal Flow decision
  });

  it("while the view is read, the old loading text", async () => {
    const held = gate<void>();
    serve();
    const fetchMock = vi.mocked(globalThis.fetch);
    const real = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === "/api/watch") await held.promise;
      return real(input, init);
    });
    renderPage("/deal-flow?candidate=c-wt-01");
    await waitFor(() => expect(detailName()).toBe("Halvard Optics"));
    expect(section()).toHaveTextContent("On WATCH — sensorsLoading watch state…");
    held.open();
    await waitFor(() => expect(triggers()).toHaveLength(4));
  });

  it("a view that does not list the company keeps the loading text, as the old section did", async () => {
    const server = serve({ watch: { payload: { ...watchWorld(), companies: watchWorld().companies.filter((c) => c.candidate_id !== "c-wt-03") } } });
    renderPage("/deal-flow?candidate=c-wt-03");
    await waitFor(() => expect(detailName()).toBe("Quellbrook Labs"));
    await waitFor(() => expect(server.gets("/api/watch")).toBe(1));
    await new Promise((r) => setTimeout(r, 50));
    expect(section()).toHaveTextContent("On WATCH — sensorsLoading watch state…");
    expect(triggers()).toHaveLength(0);
  });

  it("a candidate that is not on WATCH has no section and the page never reads the WATCH view", async () => {
    const server = serve();
    renderPage("/deal-flow?candidate=c-wt-05");
    await waitFor(() => expect(detailName()).toBe("Ostrand Marine"));
    expect(screen.queryByTestId("watch-section")).toBeNull();
    await new Promise((r) => setTimeout(r, 50));
    expect(server.gets("/api/watch")).toBe(0);
  });
});

import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { meta } from "@/features/conviction/test/fixtures";
import { INBOX_KEY } from "./hooks/useDealFlowData";
import { wsCounts } from "./model/geo";
import { buildList, type ListOptions } from "./model/list";
import { isNonStartup } from "./model/triage";
import type { Candidate, InboxPayload } from "./model/types";
import { cand, inbox, triage } from "./test/fixtures";
import { fakeServer, gate, renderPage, type Routes } from "./test/server";

const rowIds = () => screen.queryAllByTestId("cand-row").map((r) => r.getAttribute("data-id"));
const detailName = () => within(screen.getByTestId("cand-detail")).getByRole("heading", { level: 2 }).textContent;
const row = (qc: ReturnType<typeof renderPage>["qc"], id: string) => qc.getQueryData<InboxPayload>(INBOX_KEY)?.candidates.find((c) => c.id === id);
const TOP: ListOptions = { ws: "eu", naf: "both", theme: "", im: false, filter: "top", lastRun: "r1" };

function serve(over: Partial<Routes> = {}) {
  return fakeServer({ inbox: () => inbox(), triage: () => triage(), ...over });
}

const DECISION_OF: Record<string, Candidate["decision"]> = { new: "new", reviewing: "research", watch: "watch", rejected: "rejected", baseline: "baseline" };

/** A server that keeps the decisions it accepts, so a refetch returns them (a fresh read). */
function statefulServe() {
  const db = inbox();
  return serve({
    inbox: () => structuredClone(db),
    decide: (id, body) => {
      const c = db.candidates.find((x) => x.id === id)!;
      const previous = c.pz_status;
      const status = String(body.status);
      Object.assign(c, { pz_status: status, decision: DECISION_OF[status] }, body.notes !== undefined ? { notes: body.notes } : {});
      return { status: 200, body: { ok: true, id, status, previous_status: previous, changed: true, feedback: null } };
    },
  });
}

async function loaded() {
  await waitFor(() => expect(screen.getAllByTestId("cand-row").length).toBeGreaterThan(0));
}

function openMore() {
  fireEvent.click(screen.getByTestId("more-filters"));
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

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("Deal Flow — the list", () => {
  it("renders the Attention queue in buildList order, without the non-startup and gated records", async () => {
    serve();
    renderPage();
    await loaded();
    const expected = buildList(inbox().candidates, { ...TOP, skip: isNonStartup(triage().proposals) });
    expect(rowIds()).toEqual(expected.list.map((c) => c.id));
    expect(rowIds()).toHaveLength(15);
    expect(buildList(inbox().candidates, TOP).list.map((c) => c.id)).toContain("ns"); // routed out, though its score would enter
    expect(rowIds()).not.toContain("ns");
    expect(rowIds()).not.toContain("gated");
    expect(screen.getByText(/more undecided/).parentElement).toHaveTextContent(`Attention queue shows the top 15 by signal — ${expected.hidden} more undecided under All to decide.`);
  });

  it("the Investment manager lens re-ranks the queue by attention v2 final", async () => {
    const ib = inbox();
    ib.candidates = ib.candidates.map((c, i) => ({ ...c, attention_v2: { ...c.attention_v2, score: i, final: (i * 7) % 11, lens: 1 } }));
    serve({ inbox: () => ib });
    renderPage();
    await loaded();
    openMore();
    fireEvent.click(screen.getByRole("button", { name: "Investment manager lens" }));
    const skip = isNonStartup(triage().proposals);
    expect(rowIds()).toEqual(buildList(ib.candidates, { ...TOP, im: true, skip }).list.map((c) => c.id));
    expect(rowIds()).not.toEqual(buildList(ib.candidates, { ...TOP, skip }).list.map((c) => c.id));
    expect(screen.getByTestId("more-filters")).toHaveTextContent("More filters · IM lens");
  });

  it("names repaired entities and shows the proposal badge", async () => {
    serve();
    renderPage();
    await loaded();
    const tri = screen.getAllByTestId("cand-row").find((r) => r.getAttribute("data-id") === "tri1")!;
    expect(tri).toHaveTextContent("Real Name GmbH");
    expect(within(tri).getByTestId("row-triage")).toHaveTextContent("KEEP");
  });

  it("filters: All to decide, Researching (under More filters) and the counts line", async () => {
    serve();
    renderPage();
    await loaded();
    expect(screen.getByTestId("ib-count")).toHaveTextContent("20 to decide · 1 researching · 1 watching · 1 kept · 1 rejected · 1 baseline");
    fireEvent.click(screen.getByRole("button", { name: "All to decide" }));
    expect(rowIds()).toEqual(buildList(inbox().candidates, { ...TOP, filter: "new" }).list.map((c) => c.id));
    openMore();
    fireEvent.click(screen.getByRole("button", { name: "Researching" }));
    expect(rowIds()).toEqual(["r1"]);
    expect(screen.getByTestId("more-filters")).toHaveTextContent("More filters · Researching");
  });

  it("workspaces: segments with undecided counts, the NA sub-filter, and the remembered choice", async () => {
    serve();
    renderPage();
    await loaded();
    const n = wsCounts(inbox().candidates);
    const seg = (ws: string) => document.querySelector(`[data-ws="${ws}"]`)!;
    expect(seg("eu")).toHaveTextContent(`EUROPE${n.eu}`);
    expect(seg("na")).toHaveTextContent(`NORTH AMERICA${n.na}`);
    expect(seg("unk")).toHaveTextContent(`Unresolved${n.unk}`);
    expect(seg("eu")).toHaveAttribute("aria-selected", "true");
    fireEvent.click(seg("na"));
    expect(rowIds().sort()).toEqual(["ca1", "us1"]);
    expect(screen.getByTestId("ws-label")).toHaveTextContent("Exceptional opportunity hunting");
    fireEvent.click(screen.getByRole("button", { name: "USA" }));
    expect(rowIds()).toEqual(["us1"]);
    expect(localStorage.getItem("pz:workspace")).toBe('"na"');
    fireEvent.click(seg("unk"));
    expect(rowIds()).toEqual(["u1"]);
  });

  it("selecting a row opens it in the inspector", async () => {
    serve();
    renderPage();
    await loaded();
    expect(detailName()).toBe(`Company ${rowIds()[0]}`);
    const third = screen.getAllByTestId("cand-row")[2];
    fireEvent.click(third);
    expect(third).toHaveAttribute("aria-pressed", "true");
    expect(detailName()).toBe(`Company ${third.getAttribute("data-id")}`);
  });

  it("without a triage endpoint the list is the plain queue (no proposals)", async () => {
    serve({ triage: () => null });
    renderPage();
    await loaded();
    expect(rowIds()).toEqual(buildList(inbox().candidates, TOP).list.map((c) => c.id));
    expect(screen.queryByTestId("row-triage")).toBeNull();
  });
});

describe("Deal Flow — decisions", () => {
  it("Reject sends the mapped status with expected_status, patches the row, then refetches the inbox", async () => {
    const refetch = gate<InboxPayload>();
    const server = serve({
      inbox: (n) => (n === 1 ? inbox() : refetch.promise),
      decide: (id) => ({ status: 200, body: { ok: true, id, status: "rejected", previous_status: "new", changed: true, feedback: { label: "src-b", adjustment: -1, reason: "you rejected 5" } } }),
    });
    const { qc } = renderPage();
    await loaded();
    const id = rowIds()[0]!;
    fireEvent.click(within(screen.getByTestId("cand-detail")).getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(server.posts()).toHaveLength(1));
    expect(server.posts()[0]).toEqual({ method: "POST", path: `/api/deal-flow/candidates/${id}/decision`, body: { status: "rejected", expected_status: "new" } });
    // patched in place while the refetch is still in flight
    await waitFor(() => expect(row(qc, id)?.decision).toBe("rejected"));
    expect(row(qc, id)).toMatchObject({ pz_status: "rejected", feedback: { adjustment: -1, reason: "you rejected 5" } });
    expect(rowIds()).not.toContain(id);
    await waitFor(() => expect(server.inboxReads()).toBe(2));
    // the server's answer: the same source's feedback crossed its threshold, so another candidate moved too
    const fresh = inbox();
    fresh.candidates = fresh.candidates.map((c) =>
      c.id === id ? { ...c, decision: "rejected", pz_status: "rejected" } : c.source === "src-b" ? { ...c, feedback: { adjustment: -1, reason: "you rejected 5" } } : c,
    );
    await act(async () => refetch.open(fresh));
    const other = fresh.candidates.find((c) => c.source === "src-b" && c.id !== id)!;
    await waitFor(() => expect(row(qc, other.id)?.feedback?.adjustment).toBe(-1));
    expect(await screen.findByText("✓ Saving your decision — done")).toBeInTheDocument();
  });

  it("a stale decision (409) shows the error and refetches, so the cached row equals the server", async () => {
    let serverRow: Candidate | undefined;
    const server = serve({
      inbox: (n) => {
        const ib = inbox();
        if (n > 1) ib.candidates = ib.candidates.map((c) => (c.id === serverRow?.id ? serverRow : c));
        return ib;
      },
      decide: (id) => {
        serverRow = cand(id, { ...inbox().candidates.find((c) => c.id === id), decision: "research", pz_status: "reviewing" });
        return { status: 409, body: { ok: false, error: "the candidate changed meanwhile; reload and decide again", current: "reviewing" } };
      },
    });
    const { qc } = renderPage();
    await loaded();
    const id = rowIds()[0]!;
    fireEvent.click(within(screen.getByTestId("cand-detail")).getByRole("button", { name: "Reject" }));
    expect(await screen.findByText(/Saving your decision failed — the candidate changed meanwhile/)).toBeInTheDocument();
    await waitFor(() => expect(server.inboxReads()).toBe(2));
    await waitFor(() => expect(row(qc, id)).toEqual(serverRow));
    expect(row(qc, id)?.decision).toBe("research");
  });

  it("Undo decides back to new with the stored status as expected_status", async () => {
    const server = statefulServe();
    const { qc } = renderPage();
    await loaded();
    openMore();
    fireEvent.click(screen.getByRole("button", { name: "Researching" }));
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(server.posts()).toHaveLength(1));
    expect(server.posts()[0]).toEqual({ method: "POST", path: "/api/deal-flow/candidates/r1/decision", body: { status: "new", expected_status: "reviewing" } });
    await waitFor(() => expect(server.inboxReads()).toBe(2));
    await waitFor(() => expect(row(qc, "r1")).toMatchObject({ decision: "new", pz_status: "new" }));
  });

  it("notes are written in the Research drawer and saved with the decision", async () => {
    const server = statefulServe();
    const { qc } = renderPage();
    await loaded();
    const id = rowIds()[0]!;
    fireEvent.click(within(screen.getByTestId("cand-detail")).getByRole("button", { name: "Research" }));
    const drawer = screen.getByRole("dialog");
    expect(drawer).toHaveTextContent(`Research: Company ${id}`);
    fireEvent.change(within(drawer).getByLabelText(/Notes/), { target: { value: "Founder ex-Celonis; raising Q1" } });
    fireEvent.click(within(drawer).getByRole("button", { name: "Save & decide later" }));
    await waitFor(() => expect(server.posts()).toHaveLength(1));
    expect(server.posts()[0].body).toEqual({ status: "reviewing", notes: "Founder ex-Celonis; raising Q1", expected_status: "new" });
    expect(await screen.findByText("Saved as researching")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(server.inboxReads()).toBe(2));
    expect(row(qc, id)).toMatchObject({ decision: "research", pz_status: "reviewing", notes: "Founder ex-Celonis; raising Q1" });
  });
});

describe("Deal Flow — Keep (a Conviction save, review 011)", () => {
  /** A server that also answers the scoring tables and the Conviction save. */
  function keepServe(save: (body: Record<string, unknown>) => { status: number; body: unknown }) {
    const db = inbox();
    return serve({
      inbox: () => structuredClone(db),
      meta: () => meta(),
      save,
      decide: (id, body) => {
        const c = db.candidates.find((x) => x.id === id)!;
        const previous = c.pz_status;
        Object.assign(c, { pz_status: String(body.status), decision: DECISION_OF[String(body.status)] }, body.notes !== undefined ? { notes: body.notes } : {});
        return { status: 200, body: { ok: true, id, status: body.status, previous_status: previous, changed: true, feedback: null } };
      },
    });
  }

  async function openKeep(name: string) {
    const dlg = await screen.findByRole("dialog", { name });
    await waitFor(() => expect(within(dlg).getByTestId("livescore")).toBeInTheDocument());
    return dlg;
  }

  it("“Keep — score it” opens the scoring form prefilled from the candidate, saves with inbox_id and opens the entry", async () => {
    const server = keepServe(() => ({ status: 200, body: { ok: true, slug: "company-e1" } }));
    const { router } = renderPage();
    await loaded();
    const id = rowIds()[0]!;
    const c = inbox().candidates.find((x) => x.id === id)!;
    fireEvent.click(within(screen.getByTestId("cand-detail")).getByRole("button", { name: "Keep — score it" }));
    const dlg = await openKeep(`Keep & score: ${c.name}`);
    expect(dlg.querySelector<HTMLInputElement>('[name="company"]')).toHaveValue(c.name);
    expect(dlg.querySelector<HTMLInputElement>('[name="discovery_source"]')).toHaveValue(c.source);
    expect(server.posts()).toEqual([]);
    fireEvent.click(within(dlg).getByRole("button", { name: "Save to pipeline" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/conviction"));
    expect(router.state.location.search).toBe("?company=company-e1");
    const [save] = server.posts();
    expect(save.path).toBe("/api/conviction/save");
    expect(save.body).toMatchObject({ inbox_id: id, company: c.name, one_liner: c.description, location: c.location, discovery_source: c.source });
    expect(save.body).not.toHaveProperty("slug");
    // the Deal Flow inbox is stale now (the candidate became kept on the server)
    await waitFor(() => expect(server.inboxReads()).toBeGreaterThanOrEqual(2));
  });

  it("“Keep — go to scoring” saves the notes as researching first, then keeps through the form", async () => {
    const server = keepServe(() => ({ status: 200, body: { ok: true, slug: "company-x" } }));
    const { router } = renderPage();
    await loaded();
    const id = rowIds()[0]!;
    fireEvent.click(within(screen.getByTestId("cand-detail")).getByRole("button", { name: "Research" }));
    const drawer = screen.getByRole("dialog");
    fireEvent.change(within(drawer).getByLabelText(/Notes/), { target: { value: "strong founder" } });
    fireEvent.click(within(drawer).getByRole("button", { name: "Keep — go to scoring" }));
    const dlg = await openKeep(`Keep & score: Company ${id}`);
    expect(server.posts()[0]).toEqual({ method: "POST", path: `/api/deal-flow/candidates/${id}/decision`, body: { status: "reviewing", notes: "strong founder", expected_status: "new" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save to pipeline" }));
    await waitFor(() => expect(router.state.location.search).toBe("?company=company-x"));
    expect(server.posts()[1].body).toMatchObject({ inbox_id: id });
  });

  it("a Keep whose company already has an entry (409) offers to open it; the lead is not decided here", async () => {
    const server = keepServe(() => ({ status: 409, body: { ok: false, duplicate: true, slug: "alpha", error: "a company with this name already exists — open it in Conviction to edit it" } }));
    const { router, qc } = renderPage();
    await loaded();
    const id = rowIds()[0]!;
    fireEvent.click(within(screen.getByTestId("cand-detail")).getByRole("button", { name: "Keep — score it" }));
    const dlg = await openKeep(`Keep & score: Company ${id}`);
    fireEvent.click(within(dlg).getByRole("button", { name: "Save to pipeline" }));
    const offer = await within(dlg).findByTestId("save-duplicate");
    expect(router.state.location.pathname).toBe("/deal-flow");
    expect(row(qc, id)).toMatchObject({ decision: "new" });
    fireEvent.click(within(offer).getByRole("button", { name: "Open existing entry" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/conviction"));
    expect(router.state.location.search).toBe("?company=alpha");
    expect(server.posts()).toHaveLength(1);
  });
});

describe("Deal Flow — entry points that are not ported yet", () => {
  function checkInert(server: ReturnType<typeof serve>) {
    const off = Array.from(document.querySelectorAll('[aria-disabled="true"]'));
    expect(off.length).toBeGreaterThan(0);
    for (const el of off) {
      const reason = el.getAttribute("aria-describedby");
      expect(reason && document.getElementById(reason)?.textContent).toBeTruthy();
      expect(el.getAttribute("title")).toBeTruthy();
      pressEveryWay(el);
    }
    expect(server.posts()).toEqual([]);
    return off;
  }

  it("every disabled control says why and sends nothing, by click or keyboard", async () => {
    const server = serve();
    renderPage();
    await loaded();
    // the Attention view, the review-queue chip and Analyze Top N (Keep is live since review 011, the scan since 034a)
    openMore();
    let off = checkInert(server);
    expect(off.map((e) => e.textContent)).toEqual(expect.arrayContaining(["Analyze Top Candidates", "Agent Review Queue"]));
    expect(off.map((e) => e.textContent)).not.toEqual(expect.arrayContaining(["Find New Candidates"]));
    expect(off.map((e) => e.textContent)).not.toEqual(expect.arrayContaining(["Scan history"]));
    expect(screen.getByRole("button", { name: "Keep — score it" })).not.toHaveAttribute("aria-disabled");
    expect(screen.getByTestId("find-btn")).not.toHaveAttribute("aria-disabled");
    expect(screen.getByTestId("scan-history")).not.toHaveAttribute("data-deferred");
    expect(screen.getByLabelText("Feed window")).toBeEnabled();
    expect(screen.getByLabelText("Number of candidates to analyze")).toBeDisabled();

    // the triage view's batch actions and the selected candidate's triage panel + analyst
    fireEvent.click(screen.getByRole("button", { name: "Machine triage" }));
    await waitFor(() => expect(rowIds()).toEqual(["tri1"]));
    fireEvent.click(within(screen.getByTestId("cand-models")).getByText("Analyst · Red Team · Reviewer"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Analyzed — review" })).toBeInTheDocument());
    off = checkInert(server);
    expect(off.map((e) => e.textContent)).toEqual(
      expect.arrayContaining(["Analyze top KEEPs…", "Red-team analysed…", "Accept obvious REJECTs…", "Accept KEEP — score it", "Override", "Analyzed — review"]),
    );
    expect(screen.getByTestId("red-team")).toHaveTextContent("The red team arrives with the analysis port");
    expect(screen.getByLabelText("Override verdict")).toBeDisabled();

    // the Research drawer's Keep is live as well
    fireEvent.click(within(screen.getByTestId("cand-detail")).getByRole("button", { name: "Research" }));
    expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Keep — go to scoring" })).not.toHaveAttribute("aria-disabled");
    expect(server.posts()).toEqual([]);
  });
});

describe("Deal Flow — deep links", () => {
  it("?candidate= opens the candidate's decision view, selects it and leaves the URL", async () => {
    const server = serve();
    const { router } = renderPage("/deal-flow?candidate=w1");
    await waitFor(() => expect(rowIds()).toEqual(["w1"]));
    expect(detailName()).toBe("Company w1");
    expect(screen.getByTestId("more-filters")).toHaveTextContent("Watch");
    expect(screen.getByTestId("watch-section")).toHaveTextContent("Watch sensors arrive with the Watchlist port");
    await waitFor(() => expect(router.state.location.search).toBe(""));
    expect(server.posts()).toEqual([]);
  });

  it("?candidate= with an absorbed id selects its survivor", async () => {
    const server = serve({ candidate: (id) => ({ status: 200, body: { ok: true, resolved_from: { namespace: "candidate", id }, candidate: { id: "us1" } } }) });
    const { router } = renderPage("/deal-flow?candidate=old-42");
    await waitFor(() => expect(detailName()).toBe("Company us1"));
    expect(document.querySelector('[data-ws="na"]')).toHaveAttribute("aria-selected", "true");
    expect(server.calls.some((c) => c.path === "/api/deal-flow/candidates/old-42")).toBe(true);
    expect(router.state.location.search).toBe("");
    expect(server.posts()).toEqual([]);
  });

  it("an old Scout Intake link resolves in its own namespace, even when a current id has the same string", async () => {
    // w1 is ALSO a current candidate id: the old Scout Intake item "w1" must not select it
    const server = serve({
      candidate: (id, ns) =>
        ns === "scout_intake" && id === "w1"
          ? { status: 200, body: { ok: true, resolved_from: { namespace: ns, id }, candidate: { id: "us1" } } }
          : { status: 404, body: { ok: false, error: "candidate not found" } },
    });
    const { router } = renderPage("/scout-intake?item=w1");
    await waitFor(() => expect(detailName()).toBe("Company us1"));
    expect(server.calls.some((c) => c.path === "/api/deal-flow/candidates/w1?ns=scout_intake")).toBe(true);
    expect(router.state.location.pathname).toBe("/deal-flow");
    await waitFor(() => expect(router.state.location.search).toBe(""));
    expect(server.posts()).toEqual([]);
  });

  it("an unknown namespace in a link is ignored and sends nothing", async () => {
    const server = serve();
    const { router } = renderPage("/deal-flow?candidate=w1&ns=bogus");
    await waitFor(() => expect(router.state.location.search).toBe(""));
    expect(server.calls.some((c) => c.path.startsWith("/api/deal-flow/candidates/"))).toBe(false);
    expect(server.posts()).toEqual([]);
  });

  it("?review= selects the candidate and opens nothing else", async () => {
    const server = serve();
    renderPage("/deal-flow?review=e5");
    await waitFor(() => expect(detailName()).toBe("Company e5"));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(server.posts()).toEqual([]);
  });

  it("?find=1 focuses the Find control and never scans by itself", async () => {
    const server = serve();
    renderPage("/deal-flow?find=1");
    await waitFor(() => expect(document.activeElement).toBe(screen.getByTestId("find-btn")));
    expect(screen.getByTestId("find-btn")).not.toHaveAttribute("aria-disabled");
    expect(server.posts()).toEqual([]);
  });

  it("?filter= preselects a chip; the not-ported review queue is ignored", async () => {
    serve();
    renderPage("/deal-flow?filter=rejected");
    await waitFor(() => expect(rowIds()).toEqual(["x1"]));
  });

  it("?filter=review stays on the Attention queue", async () => {
    const server = serve();
    const { router } = renderPage("/deal-flow?filter=review");
    await loaded();
    await waitFor(() => expect(router.state.location.search).toBe(""));
    expect(rowIds()).toHaveLength(15);
    expect(server.posts()).toEqual([]);
  });

  it("?route= preselects the routing view of Machine triage", async () => {
    serve();
    renderPage("/deal-flow?filter=triage&route=NEEDS_MOHAMED");
    await waitFor(() => expect(rowIds()).toEqual(["tri1"]));
    expect(document.querySelector('[data-route="NEEDS_MOHAMED"]')).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByTestId("triage-bar")).toBeNull();
  });
});

describe("Deal Flow — Revisit (review 018)", () => {
  const FLAG = {
    kind: "funding_round",
    since: "2026-11-03",
    date_source: "since",
    rejected_on: "2026-10-01",
    evidence_url: "https://example.org/round",
    evidence: [{ url: "https://example.org/round" }],
    note: "Seed round announced",
    submission_id: "sub-1",
    flagged_at: "2026-11-10T23:15:00+00:00", // 00:15 on 11 Nov in Berlin: the day shown is the server's Berlin day
    flagged_on: "2026-11-11",
  };
  /** x1 (rejected, Europe) and x2 (rejected, North America) flagged; x3 rejected without a flag. */
  function flagged(): InboxPayload {
    const ib = inbox();
    ib.candidates.find((c) => c.id === "x1")!.revisit = { ...FLAG };
    ib.candidates.push(
      cand("x2", { decision: "rejected", location: "Austin, TX", revisit: { ...FLAG, kind: "founder_or_key_hire", note: null, flagged_at: "2026-11-11T09:00:00+00:00" } }),
      cand("x3", { decision: "rejected", revisit: null }),
    );
    ib.revisit_count = 2;
    return ib;
  }
  const revisitChip = () => screen.queryByRole("button", { name: /^Revisit/ });

  it("no flags: no Revisit chip, and the Attention queue is as before", async () => {
    serve();
    renderPage();
    await loaded();
    expect(revisitChip()).toBeNull();
    expect(rowIds()).toEqual(buildList(inbox().candidates, { ...TOP, skip: isNonStartup(triage().proposals) }).list.map((c) => c.id));
  });

  it("the chip shows the count and lists exactly the flagged (rejected) candidates; the default list is unchanged", async () => {
    serve({ inbox: () => flagged() });
    renderPage();
    await loaded();
    const plain = { ...inbox(), candidates: flagged().candidates.map((c) => ({ ...c, revisit: undefined })) };
    expect(rowIds()).toEqual(buildList(plain.candidates, { ...TOP, skip: isNonStartup(triage().proposals) }).list.map((c) => c.id));
    const chip = revisitChip()!;
    expect(chip).toHaveTextContent("Revisit 2");
    expect(chip.closest('[role="group"]')).toHaveAttribute("aria-label", "Attention");
    fireEvent.click(chip);
    expect(chip).toHaveAttribute("aria-pressed", "true");
    expect(rowIds()).toEqual(["x2", "x1"]); // across workspaces, newest flag first; x3 (rejected, no flag) stays out
    expect(screen.getByTestId("more-filters")).toHaveTextContent(/^More filters$/);
    // the protected Rejected list still lists every rejected candidate of the workspace
    openMore();
    fireEvent.click(screen.getByRole("button", { name: "Rejected" }));
    expect(rowIds()).toEqual(["x1", "x3"]);
  });

  it("the detail says why, links the evidence and points at the existing reopen; nothing for an unflagged candidate", async () => {
    serve({ inbox: () => flagged() });
    renderPage("/deal-flow?filter=revisit");
    await waitFor(() => expect(rowIds()).toEqual(["x2", "x1"]));
    fireEvent.click(screen.getAllByTestId("cand-row")[1]);
    expect(detailName()).toBe("Company x1");
    const box = screen.getByTestId("cand-revisit");
    expect(box).toHaveTextContent("Revisit suggested: New funding round since 2026-11-03 — evidence ↗ · Seed round announced");
    expect(box).toHaveTextContent("rejected on 2026-10-01 · flagged 2026-11-11 · Reopen with Undo under Your decision if it is worth another look.");
    const link = within(box).getByRole("link", { name: "evidence ↗" });
    expect(link).toHaveAttribute("href", "https://example.org/round");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(within(box).queryByRole("button")).toBeNull(); // no new action: the reopen stays the decision row
    expect(within(screen.getByTestId("cand-detail")).getByRole("button", { name: "Undo" })).toBeInTheDocument();

    fireEvent.click(screen.getAllByTestId("cand-row")[0]);
    expect(detailName()).toBe("Company x2");
    expect(screen.getByTestId("cand-revisit")).toHaveTextContent("Revisit suggested: New founder or key hire since 2026-11-03 — evidence ↗");
    expect(screen.getByTestId("cand-revisit")).not.toHaveTextContent("·  ·");
    expect(screen.getByTestId("cand-revisit")).not.toHaveTextContent("also reported at");

    openMore();
    fireEvent.click(screen.getByRole("button", { name: "Rejected" }));
    fireEvent.click(screen.getAllByTestId("cand-row")[1]);
    expect(detailName()).toBe("Company x3");
    expect(screen.queryByTestId("cand-revisit")).toBeNull();
  });

  it("a corroboration links the earlier report's source too (Codex H-129)", async () => {
    const ib = flagged();
    ib.candidates.find((c) => c.id === "x1")!.revisit = {
      ...FLAG,
      kind: "independent_corroboration",
      corroboration: [
        { evidence_url: "https://www.registry.example.org/notice", submission_id: "sub-0" },
        { evidence_url: "https://example.org/round", submission_id: "sub-1" },
      ],
    };
    serve({ inbox: () => ib });
    renderPage("/deal-flow?filter=revisit");
    await waitFor(() => expect(rowIds()).toEqual(["x2", "x1"]));
    fireEvent.click(screen.getAllByTestId("cand-row")[1]);
    const box = screen.getByTestId("cand-revisit");
    expect(box).toHaveTextContent("Revisit suggested: Independent corroboration since 2026-11-03 — evidence ↗ · Seed round announced · also reported at registry.example.org ↗");
    expect(within(box).getByRole("link", { name: "registry.example.org ↗" })).toHaveAttribute("href", "https://www.registry.example.org/notice");
  });
});

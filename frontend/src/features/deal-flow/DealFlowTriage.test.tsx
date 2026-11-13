/**
 * Machine triage writes on the page (review 035a): the panel's "Accept {proposal}" (a KEEP opens the existing Keep &
 * score form), the Override select + button with `expected_status`, the 400 and 409 answers as the error toast, and
 * "Accept obvious REJECTs…" — nothing for an empty view, the server's preview, the old confirm dialog ("Reject N"), then
 * the confirm and the old toast — with the old invalidations. Nothing is posted until a click. Invented names only
 * (`test/triage/*.json`).
 */
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { meta } from "@/features/conviction/test/fixtures";
import { INBOX_KEY } from "./hooks/useDealFlowData";
import { TRIAGE_INVALIDATES } from "./hooks/useTriageDecide";
import type { InboxPayload } from "./model/types";
import { triageAnswer, triageInbox, triageWorld, type TriageAnswer } from "./test/fixtures";
import { fakeServer, gate, renderPage, type Routes } from "./test/server";

const DECIDE = "/api/deal-flow/triage/decide";
const BATCH = "/api/deal-flow/triage/batch_reject";

const rowIds = () => screen.queryAllByTestId("cand-row").map((r) => r.getAttribute("data-id"));
const detail = () => screen.getByTestId("cand-detail");
const panel = () => screen.getByTestId("triage-panel");
const row = (qc: ReturnType<typeof renderPage>["qc"], id: string) => qc.getQueryData<InboxPayload>(INBOX_KEY)?.candidates.find((c) => c.id === id);
const ok = (name: TriageAnswer) => ({ status: 200, body: triageAnswer(name) });

/** The operating queue's undecided proposals in the triage order (t-0205 has no confidence, so it sorts last). */
const TRIAGE_ORDER = ["t-0201", "t-0202", "t-0203", "t-0204", "t-0206", "t-0205"];

const STORED = { rejected: "rejected", watch: "watch", research: "reviewing" } as const;
type Stored = keyof typeof STORED;

/**
 * A server that keeps what it applies, so a refetch returns it (a fresh read): a decide stores its `inbox_decision`; a
 * confirmed batch rejects every id sent. Later inbox reads can be held by passing `inbox`.
 */
function serve(over: Partial<Routes> = {}) {
  const db = triageInbox();
  const store = (id: string, d: Stored) => Object.assign(db.candidates.find((c) => c.id === id)!, { decision: d, pz_status: STORED[d] });
  const decide = over.triageDecide;
  const batch = over.batchReject;
  return fakeServer({
    inbox: () => structuredClone(db),
    triage: () => triageWorld(),
    meta: () => meta(),
    ...over,
    triageDecide: decide
      ? async (body) => {
          const a = await decide(body);
          const applied = (a.body as { inbox_decision?: Stored | null }).inbox_decision;
          if (a.status === 200 && applied) store(String(body.id), applied);
          return a;
        }
      : undefined,
    batchReject: batch
      ? async (body) => {
          const a = await batch(body);
          if (a.status === 200 && body.confirm) for (const id of body.ids as string[]) store(id, "rejected");
          return a;
        }
      : undefined,
  });
}

/** Open the Machine triage view and select `id` (the list starts with the KEEP). */
async function openTriage(id?: string) {
  const view = renderPage("/deal-flow?filter=triage");
  // the triage order (KEEP, RESEARCH, WATCH, then the REJECTs by confidence), once the view has switched from the queue
  await waitFor(() => expect(screen.getByTestId("triage-bar")).toBeInTheDocument());
  await waitFor(() => expect(rowIds()).toEqual(TRIAGE_ORDER));
  if (id) fireEvent.click(screen.getAllByTestId("cand-row").find((r) => r.getAttribute("data-id") === id)!);
  await waitFor(() => expect(within(detail()).getByRole("heading", { level: 2 })).toHaveTextContent(triageInbox().candidates.find((c) => c.id === (id ?? "t-0201"))!.name));
  const invalidated = vi.spyOn(view.qc, "invalidateQueries");
  const keys = () => invalidated.mock.calls.map((c) => (c[0]?.queryKey as unknown[] | undefined)?.[0]);
  return { ...view, keys };
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("Machine triage — accept / override (review 035a)", () => {
  it("nothing is posted until a click: selecting, picking an override and waiting send nothing", async () => {
    const server = serve({ triageDecide: () => ok("accept_reject") });
    await openTriage("t-0204");
    expect(within(panel()).getByTestId("triage-accept")).toHaveTextContent("Accept REJECT");
    expect(within(panel()).getByTestId("triage-accept")).toBeEnabled();
    expect(within(panel()).getByTestId("triage-override")).toBeDisabled();
    const select = within(panel()).getByLabelText("Override verdict");
    expect(Array.from(select.querySelectorAll("option")).map((o) => o.textContent)).toEqual(["Override…", "KEEP", "RESEARCH", "WATCH"]);
    fireEvent.change(select, { target: { value: "WATCH" } });
    expect(within(panel()).getByTestId("triage-override")).toBeEnabled();
    fireEvent.click(screen.getAllByTestId("cand-row")[1]);
    // another candidate: its own panel, nothing picked
    await waitFor(() => expect(within(panel()).getByTestId("triage-accept")).toHaveTextContent("Accept RESEARCH"));
    expect(within(panel()).getByLabelText("Override verdict")).toHaveValue("");
    await new Promise((r) => setTimeout(r, 50));
    expect(server.posts()).toEqual([]);
  });

  it("Accept REJECT posts the verdict with the status the panel showed, patches the row, toasts and reads the views again", async () => {
    const server = serve({ triageDecide: () => ok("accept_reject") });
    const { qc, keys } = await openTriage("t-0204");
    const triageReads = server.gets("/api/deal-flow/triage");
    fireEvent.click(within(panel()).getByTestId("triage-accept"));
    await waitFor(() => expect(server.posts()).toHaveLength(1));
    expect(server.posts()[0]).toEqual({ method: "POST", path: DECIDE, body: { id: "t-0204", verdict: "REJECT", mode: "accept", expected_status: "new" } });
    expect(await screen.findByText("Accepted REJECT")).toBeInTheDocument();
    expect(row(qc, "t-0204")).toMatchObject({ decision: "rejected", pz_status: "rejected" });
    await waitFor(() => expect(rowIds()).not.toContain("t-0204"));
    expect(keys()).toEqual(expect.arrayContaining([...TRIAGE_INVALIDATES]));
    await waitFor(() => expect(server.gets("/api/deal-flow/triage")).toBeGreaterThan(triageReads));
    await waitFor(() => expect(server.inboxReads()).toBe(2));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("Accept RESEARCH stores the reviewing status (the old research)", async () => {
    const server = serve({ triageDecide: () => ok("accept_research") });
    const { qc } = await openTriage("t-0202");
    fireEvent.click(within(panel()).getByTestId("triage-accept"));
    expect(await screen.findByText("Accepted RESEARCH")).toBeInTheDocument();
    expect(server.posts()[0].body).toEqual({ id: "t-0202", verdict: "RESEARCH", mode: "accept", expected_status: "new" });
    expect(row(qc, "t-0202")).toMatchObject({ decision: "research", pz_status: "reviewing" });
  });

  it("Override posts the verdict picked in the select with mode override", async () => {
    const server = serve({ triageDecide: () => ok("override_watch") });
    const { qc } = await openTriage();
    fireEvent.change(within(panel()).getByLabelText("Override verdict"), { target: { value: "WATCH" } });
    fireEvent.click(within(panel()).getByTestId("triage-override"));
    await waitFor(() => expect(server.posts()).toHaveLength(1));
    expect(server.posts()[0]).toEqual({ method: "POST", path: DECIDE, body: { id: "t-0201", verdict: "WATCH", mode: "override", expected_status: "new" } });
    expect(await screen.findByText("Overrode to WATCH")).toBeInTheDocument();
    expect(row(qc, "t-0201")).toMatchObject({ decision: "watch", pz_status: "watch" });
  });

  it("“Accept KEEP — score it” logs the verdict and opens the existing Keep & score form; no status is written", async () => {
    const server = serve({ triageDecide: () => ok("accept_keep") });
    const { qc, keys } = await openTriage();
    const accept = within(panel()).getByTestId("triage-accept");
    expect(accept).toHaveTextContent("Accept KEEP — score it");
    fireEvent.click(accept);
    const dlg = await screen.findByRole("dialog", { name: "Keep & score: Corvane Thermal" });
    await waitFor(() => expect(within(dlg).getByTestId("livescore")).toBeInTheDocument());
    expect(dlg.querySelector<HTMLInputElement>('[name="company"]')).toHaveValue("Corvane Thermal");
    expect(server.posts()).toEqual([{ method: "POST", path: DECIDE, body: { id: "t-0201", verdict: "KEEP", mode: "accept", expected_status: "new" } }]);
    expect(row(qc, "t-0201")).toMatchObject({ decision: "new", pz_status: "new" });
    expect(screen.queryByText("Accepted KEEP")).toBeNull();
    expect(keys()).toEqual(expect.arrayContaining([...TRIAGE_INVALIDATES]));
  });

  it("a 409 (changed meanwhile) is the error toast saying to reload; nothing opens and the inbox and triage are read again", async () => {
    const server = serve({ triageDecide: () => ({ status: 409, body: triageAnswer("conflict") }) });
    const { qc } = await openTriage();
    const triageReads = server.gets("/api/deal-flow/triage");
    fireEvent.click(within(panel()).getByTestId("triage-accept"));
    expect(await screen.findByText("✕ Saving your triage decision failed — the candidate changed meanwhile; reload and decide again")).toBeInTheDocument();
    await waitFor(() => expect(server.inboxReads()).toBe(2));
    await waitFor(() => expect(server.gets("/api/deal-flow/triage")).toBeGreaterThan(triageReads));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(row(qc, "t-0201")).toMatchObject({ decision: "new" });
    expect(server.posts()).toHaveLength(1);
  });

  it("a 400 shows the server's rule as the error toast; the row and the views stay as they are", async () => {
    const server = serve({ triageDecide: () => ({ status: 400, body: triageAnswer("invalid") }) });
    const { qc, keys } = await openTriage();
    fireEvent.change(within(panel()).getByLabelText("Override verdict"), { target: { value: "WATCH" } });
    fireEvent.click(within(panel()).getByTestId("triage-override"));
    expect(await screen.findByText("✕ Saving your triage decision failed — accept means taking the machine proposal (KEEP); use override for WATCH")).toBeInTheDocument();
    expect(row(qc, "t-0201")).toMatchObject({ decision: "new" });
    expect(keys()).not.toContain("deal-flow/inbox");
    expect(server.inboxReads()).toBe(1);
    expect(rowIds()).toContain("t-0201");
  });

  it("a decided candidate keeps its proposal but no accept / override", async () => {
    serve();
    renderPage("/deal-flow?candidate=t-0208");
    await waitFor(() => expect(within(detail()).getByRole("heading", { level: 2 })).toHaveTextContent("Brindle Works"));
    expect(within(panel()).queryByTestId("triage-accept")).toBeNull();
    expect(within(panel()).queryByTestId("triage-override")).toBeNull();
  });
});

describe("Machine triage — Accept obvious REJECTs… (review 035a)", () => {
  const ELIGIBLE = ["t-0204", "t-0205"]; // undecided obvious REJECTs of the operating queue, in inbox order

  it("previews the view's obvious REJECTs, asks “Reject N”, and only the confirm applies; then the old toast", async () => {
    const server = serve({ batchReject: (b) => ok(b.confirm ? "applied" : "preview") });
    const { qc, keys } = await openTriage();
    expect(server.posts()).toEqual([]);
    fireEvent.click(screen.getByTestId("triage-batch"));
    const dlg = await screen.findByRole("dialog", { name: "Batch-accept obvious REJECTs" });
    expect(server.posts()).toEqual([{ method: "POST", path: BATCH, body: { ids: ELIGIBLE } }]);
    expect(dlg).toHaveTextContent("Accept 2 machine REJECT proposals where both models agreed on a supported reason (or the record is junk)?");
    expect(dlg).toHaveTextContent("Each becomes rejected in Deal Flow and is logged as your decision — Undo works per candidate.");
    expect(within(dlg).queryByTestId("batch-skipped")).toBeNull();
    const confirm = within(dlg).getByTestId("confirm-ok");
    expect(confirm).toHaveTextContent("Reject 2");
    fireEvent.click(confirm);
    await waitFor(() => expect(server.posts()).toHaveLength(2));
    expect(server.posts()[1]).toEqual({ method: "POST", path: BATCH, body: { ids: ELIGIBLE, confirm: true } });
    expect(await screen.findByText("Rejected 2")).toBeInTheDocument();
    for (const id of ELIGIBLE) expect(row(qc, id)).toMatchObject({ decision: "rejected", pz_status: "rejected" });
    await waitFor(() => expect(rowIds()).not.toContain("t-0204"));
    expect(keys()).toEqual(expect.arrayContaining([...TRIAGE_INVALIDATES]));
  });

  it("Cancel sends only the preview; nothing is applied", async () => {
    const server = serve({ batchReject: (b) => ok(b.confirm ? "applied" : "preview") });
    const { qc } = await openTriage();
    fireEvent.click(screen.getByTestId("triage-batch"));
    const dlg = await screen.findByRole("dialog", { name: "Batch-accept obvious REJECTs" });
    fireEvent.click(within(dlg).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await new Promise((r) => setTimeout(r, 50));
    expect(server.posts()).toHaveLength(1);
    expect(server.posts()[0].body).toEqual({ ids: ELIGIBLE });
    expect(row(qc, "t-0204")).toMatchObject({ decision: "new" });
  });

  it("the preview's count is the dialog's; skipped ones are named, the toast counts them and the refetch shows the rest", async () => {
    const refetch = gate<InboxPayload>();
    const server = serve({ inbox: (n) => (n === 1 ? triageInbox() : refetch.promise), batchReject: (b) => ok(b.confirm ? "applied_partial" : "preview_partial") });
    const { qc } = await openTriage();
    fireEvent.click(screen.getByTestId("triage-batch"));
    const dlg = await screen.findByRole("dialog", { name: "Batch-accept obvious REJECTs" });
    expect(dlg).toHaveTextContent("Accept 1 machine REJECT proposals");
    expect(within(dlg).getByTestId("batch-skipped")).toHaveTextContent("Left out: 1 already decided.");
    expect(within(dlg).getByTestId("confirm-ok")).toHaveTextContent("Reject 1");
    fireEvent.click(within(dlg).getByTestId("confirm-ok"));
    expect(await screen.findByText("Rejected 1 · skipped 1")).toBeInTheDocument();
    // which one was applied is the server's: nothing is patched blindly while the inbox is read again
    await waitFor(() => expect(server.inboxReads()).toBe(2));
    expect(row(qc, "t-0204")).toMatchObject({ decision: "new" });
    expect(row(qc, "t-0205")).toMatchObject({ decision: "new" });
    const fresh = triageInbox();
    fresh.candidates = fresh.candidates.map((c) =>
      c.id === "t-0204" ? { ...c, decision: "watch", pz_status: "watch" } : c.id === "t-0205" ? { ...c, decision: "rejected", pz_status: "rejected" } : c,
    );
    await act(async () => refetch.open(fresh));
    await waitFor(() => expect(row(qc, "t-0205")).toMatchObject({ decision: "rejected", pz_status: "rejected" }));
    expect(row(qc, "t-0204")).toMatchObject({ decision: "watch" });
  });

  it("the scope decides the ids: Everything adds the global obvious REJECT; a view with none says so and sends nothing", async () => {
    const server = serve({ batchReject: () => ok("preview_none") });
    await openTriage();
    fireEvent.click(document.querySelector('[data-scope="all"]')!);
    fireEvent.click(screen.getByTestId("triage-batch"));
    await waitFor(() => expect(server.posts()).toHaveLength(1));
    expect(server.posts()[0].body).toEqual({ ids: ["t-0204", "t-0205", "t-0207"] });
    // the server found none eligible: the old "none" toast, no dialog
    expect(await screen.findByText("No obvious machine REJECTs in this view")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(document.querySelector('[data-scope="non_startup"]')!);
    fireEvent.click(screen.getByTestId("triage-batch"));
    await new Promise((r) => setTimeout(r, 50));
    expect(server.posts()).toHaveLength(1);
  });

  it("a confirm refused with 409 (a company moved) is the error toast, and the inbox and triage are read again", async () => {
    const server = serve({ batchReject: (b) => (b.confirm ? { status: 409, body: triageAnswer("moved") } : ok("preview")) });
    const { qc } = await openTriage();
    const triageReads = server.gets("/api/deal-flow/triage");
    fireEvent.click(screen.getByTestId("triage-batch"));
    fireEvent.click(within(await screen.findByRole("dialog", { name: "Batch-accept obvious REJECTs" })).getByTestId("confirm-ok"));
    expect(await screen.findByText("✕ Saving your triage decision failed — the candidate moved to another company meanwhile; reload and decide again")).toBeInTheDocument();
    await waitFor(() => expect(server.inboxReads()).toBe(2));
    await waitFor(() => expect(server.gets("/api/deal-flow/triage")).toBeGreaterThan(triageReads));
    expect(row(qc, "t-0204")).toMatchObject({ decision: "new" });
  });

  it("the Analyst and Red Team batches stay deferred and silent", async () => {
    const server = serve();
    await openTriage();
    for (const id of ["triage-analyst", "triage-redteam"]) {
      const b = screen.getByTestId(id);
      expect(b).toHaveAttribute("aria-disabled", "true");
      expect(b.getAttribute("title")).toMatch(/arrives with the analysis port/);
      fireEvent.click(b);
    }
    await new Promise((r) => setTimeout(r, 50));
    expect(server.posts()).toEqual([]);
  });
});

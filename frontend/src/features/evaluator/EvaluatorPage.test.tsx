import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ALL_ITEMS } from "@/app/nav";
import { NOT_PORTED as CONVICTION } from "@/features/conviction/model/deferred";
import { PIPELINE } from "@/features/conviction/api";
import { CALLS } from "@/features/founder-calls/api";
import { SESSION, SESSIONS } from "./api";
import { NOT_PORTED } from "./model/deferred";
import { fakeServer, renderPage, type Answer } from "./test/server";

const strip = () => screen.getByTestId("eval-sessions");
const rows = () => within(strip()).queryAllByRole("listitem");
const row = (id: string) => strip().querySelector(`[data-session="${id}"]`) as HTMLElement;
const left = () => screen.getByTestId("eval-left");
const center = () => screen.getByTestId("eval-center");
const right = () => screen.getByTestId("eval-right");
const claimEl = (id: string) => left().querySelector(`[data-claim="${id}"]`) as HTMLElement;
const ledgerOrder = () => Array.from(left().querySelectorAll("[data-claim]")).map((c) => c.getAttribute("data-claim"));
const dialog = (name: string) => screen.findByRole("dialog", { name });
const refuse = (error: string): Answer => ({ status: 200, body: { ok: false, error } });

async function loaded() {
  await screen.findByTestId("eval-sessions");
}

async function opened(id: string) {
  renderPage(`/evaluator?session=${id}`);
  await screen.findByTestId("eval-workspace");
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

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Active Evaluator — the page", () => {
  it("is a ported nav view at /evaluator", () => {
    expect(ALL_ITEMS.find((i) => i.legacyView === "evaluator")).toMatchObject({ path: "/evaluator", label: "Active Evaluator", page: expect.anything() });
  });

  it("shows the header disclaimer, the counts and the strip (newest first), and makes ONE read", async () => {
    const server = fakeServer();
    renderPage();
    await loaded();
    expect(screen.getByRole("heading", { level: 1, name: "Active Evaluator" })).toBeInTheDocument();
    expect(screen.getByText(/^Live diligence support for a founder conversation/)).toHaveTextContent(
      "Live diligence support for a founder conversation — collects the evidence the existing judgment model needs. Every founder statement stays FOUNDER-REPORTED — unverified, every deck statement starts as DECK CLAIM — UNVERIFIED; nothing here changes a Verified score, records audio or sends anything to Manager. Input is what you type.",
    );
    expect(screen.getByTestId("eval-counts").textContent).toBe("3 evaluations · 2 live · 1 ended");
    expect(screen.getByRole("button", { name: "New external evaluation" })).toBeInTheDocument();
    expect(rows().map((r) => r.textContent)).toEqual([
      "Pine Robotics live · 0 answers · 0 ledger items (0 founder-reported · 0 deck)2026-11-11 08:00",
      "Kestrel Labs liveAda Quill · 1 answers · 5 ledger items (1 founder-reported · 1 deck) · 1 contradiction(s)2026-11-10 10:00",
      "Otter Mill endedBen Rook · 1 answers · 1 ledger items (1 founder-reported · 0 deck)2026-11-05 14:00",
    ]);
    expect(rows().some((r) => r.hasAttribute("aria-current"))).toBe(false);
    expect(screen.getByText("Select or start an evaluation.")).toBeInTheDocument();
    expect(server.calls.map((c) => `${c.method} ${c.path}`)).toEqual(["GET /api/evaluator/sessions"]);
  });

  it("no evaluation yet → the old empty line; one evaluation → singular", async () => {
    fakeServer({}, []);
    renderPage();
    await loaded();
    expect(screen.getByTestId("eval-counts").textContent).toBe("0 evaluations · 0 live · 0 ended");
    expect(strip().textContent).toBe("No evaluation yet. Start one from a Conviction company (Start Active Evaluator) or New external evaluation.");
  });

  it("?session= selects a session and reads it by id; a click on another row selects that one", async () => {
    const server = fakeServer();
    const { router } = renderPage("/evaluator?session=ev-1");
    await screen.findByTestId("eval-workspace");
    expect(row("ev-1")).toHaveAttribute("aria-current", "true");
    expect(server.calls.some((c) => c.path === "/api/evaluator/session?id=ev-1")).toBe(true);
    fireEvent.click(row("ev-3"));
    await waitFor(() => expect(new URLSearchParams(router.state.location.search).get("session")).toBe("ev-3"));
    await waitFor(() => expect(within(left()).getByText("Pine Robotics")).toBeInTheDocument());
    expect(row("ev-3")).toHaveAttribute("aria-current", "true");
    expect(row("ev-1")).not.toHaveAttribute("aria-current");
  });

  it("an unknown session shows the server's message in place", async () => {
    fakeServer();
    renderPage("/evaluator?session=nope");
    await loaded();
    expect(await screen.findByText("unknown session")).toBeInTheDocument();
  });
});

describe("Active Evaluator — the workspace", () => {
  it("left: the subject with its Conviction link, the deck, the existing evidence and the ledger newest first", async () => {
    fakeServer();
    await opened("ev-1");
    expect(within(left()).getByText("Kestrel Labs", { selector: "b" })).toBeInTheDocument();
    expect(within(left()).getByRole("link", { name: "Kestrel Labs" })).toHaveAttribute("href", "/conviction?company=kestrel-labs");
    expect(left()).toHaveTextContent("Ada Quill · company · Conviction: Kestrel Labs");
    expect(within(left()).getByText("Pitch deck (paste text — statements become DECK CLAIM — UNVERIFIED)")).toBeInTheDocument();
    expect(left()).toHaveTextContent("imported 2026-11-10 10:05 · 1 claims");
    expect(screen.getByTestId("eval-existing").textContent).toBe(
      "Provisional 66 · Verified 40 · verified flags: founders true, traction false, funding false · conflict: noneAdjacent known: Fernley Tools, Gantry AIResearch facts: funding — Pre-seed round led by a Berlin angel group in 2026",
    );
    expect(within(left()).getByText("Claim ledger (5)")).toBeInTheDocument();
    expect(ledgerOrder()).toEqual(["c-5", "c-4", "c-3", "c-2", "c-1"]);
    expect(within(claimEl("c-1")).getByText("DECK CLAIM")).toBeInTheDocument();
    expect(within(claimEl("c-1")).getByText("Traction")).toBeInTheDocument();
    expect(within(claimEl("c-1")).getByRole("button", { name: "attach public source" })).toBeInTheDocument();
    expect(within(claimEl("c-3")).getByRole("button", { name: "resolve with note" })).toBeInTheDocument();
    expect(claimEl("c-4")).toHaveTextContent("resolved: 200M is the DACH share");
    expect(within(claimEl("c-5")).queryByRole("button")).toBeNull();
  });

  it("an external session is not linked: no Conviction link, no trigger, the old existing-evidence line", async () => {
    fakeServer();
    await opened("ev-3");
    expect(left()).toHaveTextContent("founder UNKNOWN · external");
    expect(within(left()).queryByRole("link")).toBeNull();
    expect(screen.getByTestId("eval-existing").textContent).toBe("not linked to a Conviction company");
    expect(within(left()).getByText("empty")).toBeInTheDocument();
    expect(within(right()).queryByRole("button", { name: "Record dated why-now trigger (sourced)" })).toBeNull();
    expect(screen.getByTestId("eval-imq")).toHaveTextContent("not linked to a Conviction company");
    expect(center()).toHaveTextContent("none — the next question comes from the highest-priority open family: Traction");
  });

  it("centre: the current question, Then ask with the question bank, and Asked so far", async () => {
    fakeServer();
    await opened("ev-1");
    const q = screen.getByTestId("eval-question");
    expect(q.textContent).toBe("challenge TractionWhich of the pilots pay, and how much?Why: traction is not covered yet · verify via: invoices or a customer call");
    expect(screen.getAllByTestId("eval-next").map((x) => x.textContent)).toEqual(["• Who signs the pilot contracts?", "• What happens when a pilot ends?"]);
    const bank = screen.getByTestId("eval-bank");
    fireEvent.click(within(bank).getByText("View full question bank (2 more)"));
    await waitFor(() => expect(bank).toHaveTextContent("• [opening] Why is now the moment for this?• [opening] How big is the first market?"));
    const asked = screen.getByTestId("eval-asked");
    fireEvent.click(within(asked).getByText("Asked so far (1)"));
    await waitFor(() => expect(asked).toHaveTextContent("Founder & team · openingQ: Why are you the one to build this?A: Eight years building arms FOUNDER-REPORTED"));
  });

  it("right: judgment inputs, gaps, contradictions, movement and IMQ readiness", async () => {
    fakeServer();
    await opened("ev-1");
    const founder = right().querySelector('[data-group="founder"]')!;
    expect(founder.textContent).toBe("Founder 1 claimsFOUNDER-REPORTED 1");
    expect(right().querySelector('[data-group="product"]')!.textContent).toBe("Product 0 claims—");
    expect(screen.getByTestId("eval-gaps").textContent).toBe("Founder & team · Traction · Market");
    expect(screen.getByTestId("eval-contradictions").textContent).toBe("⚠ Deck says three pilots; the founder says five");
    expect(Array.from(screen.getByTestId("eval-movement").children).map((x) => x.textContent)).toEqual([
      "Founder (15 ✓): → founder-reported only (no score change)",
      "Why now (— unverified): ↑ evidence attached — re-score manually",
      "Taste (10): → no new input",
    ]);
    expect(right()).toHaveTextContent("Founder statements never change the Verified score.");
    expect(screen.getByTestId("eval-imq")).toHaveTextContent("NOT YET IMQ");
    expect(right()).toHaveTextContent("open contradictionsno dated why-now triggertraction unverified");
  });

  it("staged Scout 00 evidence is read-only: the awaiting row only, its Attach / Dismiss and 'verify via Scout 00' disabled with the reason", async () => {
    const server = fakeServer();
    await opened("ev-1");
    const staged = screen.getByTestId("eval-staged");
    expect(within(staged).getByText("Scout 00 evidence awaiting your review")).toBeInTheDocument();
    expect(staged).toHaveTextContent("claim: Three paid pilots with machine shops");
    expect(within(staged).getByRole("link", { name: "Sifted on the pilots" })).toHaveAttribute("href", "https://sifted.eu/kestrel-pilots");
    expect(within(staged).getByText("yes")).toBeInTheDocument();
    expect(staged).toHaveTextContent("names two shops · 2026-11-01 · job-9");
    expect(staged).not.toHaveTextContent("job-8");

    const off = Array.from(screen.getByTestId("eval-workspace").querySelectorAll('[aria-disabled="true"]'));
    expect(off.map((e) => e.textContent)).toEqual(["verify via Scout 00", "verify via Scout 00", "Attach as public source", "Dismiss"]);
    expect(NOT_PORTED.bridge).toBe(CONVICTION.bridge);
    for (const el of off) {
      expect(el).toHaveAttribute("title", NOT_PORTED.bridge);
      expect(document.getElementById(el.getAttribute("aria-describedby")!)?.textContent).toBe(NOT_PORTED.bridge);
      pressEveryWay(el);
    }
    expect(server.posts()).toEqual([]);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("Active Evaluator — starting", () => {
  it("?start=1 with a slug opens the prefilled linked start dialog; starting takes a click and posts the old body", async () => {
    const server = fakeServer();
    const { router } = renderPage("/evaluator?start=1&slug=kestrel-labs&name=Kestrel%20Labs&founder=Ada%20Quill");
    const dlg = await dialog("Start Active Evaluator");
    expect(dlg).toHaveTextContent("Linked to the Conviction company Kestrel Labs. Nothing is recorded, nothing is sent.");
    expect(within(dlg).getByLabelText("Company / project name (external founder meeting)")).toHaveValue("Kestrel Labs");
    expect(within(dlg).getByLabelText("Founder name (as introduced — stays founder-reported)")).toHaveValue("Ada Quill");
    await waitFor(() => expect(router.state.location.search).toBe(""));
    expect(server.posts()).toEqual([]);
    fireEvent.click(within(dlg).getByRole("button", { name: "Start evaluation" }));
    expect(await screen.findByText("Active Evaluator started — nothing is recorded, nothing is sent")).toBeInTheDocument();
    expect(server.posts()).toEqual([
      { method: "POST", path: "/api/evaluator/start", body: { subject: { kind: "company", slug: "kestrel-labs", name: "Kestrel Labs", founder: "Ada Quill" } } },
    ]);
    await waitFor(() => expect(router.state.location.search).toBe("?session=ev-new-1"));
    await waitFor(() => expect(row("ev-new-1")).toHaveAttribute("aria-current", "true"));
    expect(await screen.findByTestId("eval-question")).toHaveTextContent("Why are you the one to build this?");
  });

  it("?start=1 without a slug opens 'New external evaluation' prefilled and starts an external session", async () => {
    const server = fakeServer();
    renderPage("/evaluator?start=1&name=Otter%20Two&founder=Cleo%20Marsh");
    const dlg = await dialog("New external evaluation");
    expect(dlg).not.toHaveTextContent("Linked to the Conviction company");
    expect(within(dlg).getByLabelText("Company / project name (external founder meeting)")).toHaveValue("Otter Two");
    fireEvent.change(within(dlg).getByLabelText("Founder name (as introduced — stays founder-reported)"), { target: { value: "  Cleo Marsh-Vale " } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Start evaluation" }));
    await screen.findByText("Active Evaluator started — nothing is recorded, nothing is sent");
    expect(server.posts()[0].body).toEqual({ subject: { kind: "external", name: "Otter Two", founder: "Cleo Marsh-Vale" } });
  });

  it("'New external evaluation' opens an empty dialog; Cancel posts nothing", async () => {
    const server = fakeServer();
    renderPage();
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "New external evaluation" }));
    const dlg = await dialog("New external evaluation");
    expect(within(dlg).getByLabelText("Company / project name (external founder meeting)")).toHaveValue("");
    fireEvent.click(within(dlg).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(server.posts()).toEqual([]);
  });

  it("a write before the legacy import (409) is a failure toast and selects nothing", async () => {
    fakeServer({ start: () => ({ status: 409, body: { ok: false, error: "the legacy data has not been imported yet" } }) });
    const { router } = renderPage();
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "New external evaluation" }));
    const dlg = await dialog("New external evaluation");
    fireEvent.change(within(dlg).getByLabelText("Company / project name (external founder meeting)"), { target: { value: "Late Co" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Start evaluation" }));
    expect(await screen.findByText("✕ Starting the evaluator failed — the legacy data has not been imported yet")).toBeInTheDocument();
    expect(router.state.location.search).toBe("");
    expect(screen.queryByText("Active Evaluator started — nothing is recorded, nothing is sent")).toBeNull();
  });
});

describe("Active Evaluator — the question flow", () => {
  it("Record answer posts {id, qid, text}, refreshes, and the next question starts empty", async () => {
    const server = fakeServer();
    await opened("ev-1");
    const reads = server.reads(SESSION);
    fireEvent.change(screen.getByLabelText("Founder's answer"), { target: { value: "Two pay, four thousand each" } });
    fireEvent.click(screen.getByRole("button", { name: "Record answer → next" }));
    expect(await screen.findByText("✓ Working — done")).toBeInTheDocument();
    expect(server.posts()).toEqual([{ method: "POST", path: "/api/evaluator/answer", body: { id: "ev-1", qid: "q-2", text: "Two pay, four thousand each" } }]);
    await waitFor(() => expect(screen.getByTestId("eval-question")).toHaveTextContent("Who signs the pilot contracts?"));
    expect(server.reads(SESSION)).toBe(reads + 1);
    expect(screen.getByLabelText("Founder's answer")).toHaveValue("");
    expect(within(left()).getByText("Claim ledger (6)")).toBeInTheDocument();
  });

  it("UNKNOWN posts the text 'unknown'; Skip posts {id, qid}", async () => {
    const server = fakeServer();
    await opened("ev-1");
    fireEvent.change(screen.getByLabelText("Founder's answer"), { target: { value: "typed but not used" } });
    fireEvent.click(screen.getByRole("button", { name: "UNKNOWN" }));
    await waitFor(() => expect(screen.getByTestId("eval-question")).toHaveTextContent("Who signs the pilot contracts?"));
    const qid = server.sessions[0].questions.at(-1)!.id;
    fireEvent.click(screen.getByRole("button", { name: "Skip" }));
    await waitFor(() => expect(screen.getByTestId("eval-question")).toHaveTextContent("What happens when a pilot ends?"));
    expect(server.posts().map((p) => [p.path, p.body])).toEqual([
      ["/api/evaluator/answer", { id: "ev-1", qid: "q-2", text: "unknown" }],
      ["/api/evaluator/skip", { id: "ev-1", qid }],
    ]);
    expect(screen.getByRole("button", { name: "Skip" })).toHaveAttribute("title", "Park this question — it comes back as an end-of-call follow-up");
  });

  it("a refused answer is a failure toast: the question, the text and the session stay as they were", async () => {
    const server = fakeServer({ answer: () => refuse("unknown question") });
    await opened("ev-1");
    const reads = [server.reads(SESSION), server.reads(SESSIONS)];
    fireEvent.change(screen.getByLabelText("Founder's answer"), { target: { value: "Two pay" } });
    fireEvent.click(screen.getByRole("button", { name: "Record answer → next" }));
    expect(await screen.findByText("✕ Working failed — unknown question")).toBeInTheDocument();
    expect(screen.getByLabelText("Founder's answer")).toHaveValue("Two pay");
    expect(screen.getByTestId("eval-question")).toHaveTextContent("Which of the pilots pay, and how much?");
    expect([server.reads(SESSION), server.reads(SESSIONS)]).toEqual(reads);
  });

  it("the deck posts {id, text}, clears the box and adds the deck claims; a refused deck keeps the text", async () => {
    let refusing = true;
    const server = fakeServer({ deck: () => (refusing ? refuse("paste the deck text first") : undefined) });
    await opened("ev-1");
    const box = screen.getByLabelText("Pitch deck text");
    fireEvent.change(box, { target: { value: "Revenue 40k MRR\n12 customers" } });
    fireEvent.click(screen.getByRole("button", { name: "Import deck claims" }));
    expect(await screen.findByText("✕ Working failed — paste the deck text first")).toBeInTheDocument();
    expect(box).toHaveValue("Revenue 40k MRR\n12 customers");
    refusing = false;
    fireEvent.click(screen.getByRole("button", { name: "Import deck claims" }));
    await waitFor(() => expect(within(left()).getByText("Claim ledger (7)")).toBeInTheDocument());
    expect(screen.getByLabelText("Pitch deck text")).toHaveValue("");
    expect(server.posts().map((p) => p.body)).toEqual([
      { id: "ev-1", text: "Revenue 40k MRR\n12 customers" },
      { id: "ev-1", text: "Revenue 40k MRR\n12 customers" },
    ]);
    expect(left()).toHaveTextContent("imported 2026-11-12 09:00 · 3 claims");
    expect(left().querySelector("[data-claim]")).toHaveTextContent("12 customers");
  });
});

describe("Active Evaluator — evidence and contradictions", () => {
  it("attach public source posts the old public body and the claim becomes a PUBLIC SOURCED FACT", async () => {
    const server = fakeServer();
    await opened("ev-1");
    fireEvent.click(within(claimEl("c-1")).getByRole("button", { name: "attach public source" }));
    const dlg = await dialog("Attach public source");
    expect(dlg).toHaveTextContent("Public source URL for THIS claim only (not LinkedIn, not a search result).");
    fireEvent.change(within(dlg).getByLabelText("Public source URL"), { target: { value: "https://sifted.eu/kestrel-pilots" } });
    fireEvent.change(within(dlg).getByLabelText("Source label"), { target: { value: "Sifted" } });
    fireEvent.change(within(dlg).getByLabelText("What the source states"), { target: { value: "Three paying shops" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Attach source" }));
    await waitFor(() => expect(within(claimEl("c-1")).getByText("PUBLIC SOURCED FACT")).toBeInTheDocument());
    expect(server.posts()).toEqual([
      {
        method: "POST",
        path: "/api/evaluator/evidence",
        body: { id: "ev-1", claim_id: "c-1", url: "https://sifted.eu/kestrel-pilots", label: "Sifted", note: "Three paying shops", kind: "public" },
      },
    ]);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("a refused source is a failure toast and the claim is unchanged", async () => {
    fakeServer();
    await opened("ev-1");
    fireEvent.click(within(claimEl("c-1")).getByRole("button", { name: "attach public source" }));
    const dlg = await dialog("Attach public source");
    fireEvent.change(within(dlg).getByLabelText("Public source URL"), { target: { value: "https://www.linkedin.com/in/someone" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Attach source" }));
    expect(await screen.findByText("✕ Working failed — a public source URL is required (not LinkedIn, not a search result)")).toBeInTheDocument();
    expect(within(claimEl("c-1")).getByText("DECK CLAIM")).toBeInTheDocument();
  });

  it("operator verified asks first, and only its confirmation posts {kind: 'operator', confirm: true, note}", async () => {
    const server = fakeServer();
    await opened("ev-1");
    fireEvent.click(within(claimEl("c-2")).getByRole("button", { name: "operator verified" }));
    let dlg = await dialog("Operator verified");
    expect(dlg).toHaveTextContent("Mark THIS claim as OPERATOR VERIFIED (you checked it yourself)? Other claims and the Verified score stay unchanged.");
    fireEvent.click(within(dlg).getByRole("button", { name: "Cancel" }));
    expect(server.posts()).toEqual([]);
    fireEvent.click(within(claimEl("c-2")).getByRole("button", { name: "operator verified" }));
    dlg = await dialog("Operator verified");
    fireEvent.change(within(dlg).getByLabelText("How did you verify it?"), { target: { value: "Called a former employer" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Mark operator verified" }));
    await waitFor(() => expect(within(claimEl("c-2")).getByText("OPERATOR VERIFIED")).toBeInTheDocument());
    expect(server.posts()).toEqual([
      { method: "POST", path: "/api/evaluator/evidence", body: { id: "ev-1", claim_id: "c-2", kind: "operator", confirm: true, note: "Called a former employer" } },
    ]);
  });

  it("resolve with note posts {id, claim_id, note}; the contradiction shows resolved and leaves the panel", async () => {
    const server = fakeServer();
    await opened("ev-1");
    fireEvent.click(within(claimEl("c-3")).getByRole("button", { name: "resolve with note" }));
    const dlg = await dialog("Resolve contradiction");
    fireEvent.change(within(dlg).getByLabelText("Resolution note (what settled the contradiction)"), { target: { value: "Five signed, three paying" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Resolve" }));
    await waitFor(() => expect(claimEl("c-3")).toHaveTextContent("resolved: Five signed, three paying"));
    expect(server.posts()).toEqual([{ method: "POST", path: "/api/evaluator/resolve", body: { id: "ev-1", claim_id: "c-3", note: "Five signed, three paying" } }]);
    expect(screen.getByTestId("eval-contradictions").textContent).toBe("none");
    await waitFor(() => expect(row("ev-1")).not.toHaveTextContent("contradiction(s)"));
  });
});

describe("Active Evaluator — ending a session", () => {
  it("End evaluation asks first; its confirmation posts {id}, refreshes the evaluator, the calls and Conviction, and shows the summary", async () => {
    const server = fakeServer();
    const { qc } = renderPage("/evaluator?session=ev-1");
    await screen.findByTestId("eval-workspace");
    qc.setQueryData([CALLS, {}], { calls: [] });
    qc.setQueryData([PIPELINE, {}], { signals: [] });
    fireEvent.click(screen.getByRole("button", { name: "End evaluation" }));
    let dlg = await dialog("End evaluation");
    expect(dlg).toHaveTextContent(
      "End evaluation? This creates the Founder Call record, verification tasks and provisional notes. Verified score unchanged, nothing sent to Manager.",
    );
    fireEvent.click(within(dlg).getByRole("button", { name: "Cancel" }));
    expect(server.posts()).toEqual([]);
    expect(qc.getQueryState([CALLS, {}])?.isInvalidated).toBe(false);

    const reads = [server.reads(SESSION), server.reads(SESSIONS)];
    fireEvent.click(screen.getByRole("button", { name: "End evaluation" }));
    dlg = await dialog("End evaluation");
    fireEvent.click(within(dlg).getByTestId("confirm-ok"));
    await waitFor(() => expect(screen.getByTestId("eval-ended")).toBeInTheDocument());
    expect(server.posts()).toEqual([{ method: "POST", path: "/api/evaluator/end", body: { id: "ev-1" } }]);
    expect(qc.getQueryState([CALLS, {}])?.isInvalidated).toBe(true);
    expect(qc.getQueryState([PIPELINE, {}])?.isInvalidated).toBe(true);
    expect(server.reads(SESSION)).toBe(reads[0] + 1);
    expect(server.reads(SESSIONS)).toBe(reads[1] + 1);

    expect(within(center()).getByText("Evaluation ended")).toBeInTheDocument();
    expect(screen.getByTestId("eval-ended")).toHaveTextContent(
      "Ended 2026-11-12 09:30 · Founder Call record created1 answers → 1 founder-reported claims · 1 deck claims · 0 UNKNOWN · 1 contradiction(s) · 5 ledger items · 2 verification task(s)Verified score changed: no · sent to Manager: no · IMQ: NOT YET IMQ — open contradictions",
    );
    expect(within(screen.getByTestId("eval-ended")).getByRole("link", { name: "Open the Founder Call record" })).toHaveAttribute(
      "href",
      "/founder-calls?call=call-ev-1",
    );
    expect(center()).toHaveTextContent("Contradictions (unresolved)⚠ Deck says three pilots; the founder says five");
    expect(screen.getAllByTestId("eval-task").map((t) => t.textContent)).toEqual([
      "☐ Verify: Three paid pilots with machine shops (public source or operator check)",
      "☐ Verify: Built robot arms for eight years (public source or operator check)",
    ]);
    expect(screen.getAllByTestId("eval-followup")).toHaveLength(4);
    expect(screen.getAllByTestId("eval-delta").map((t) => t.textContent)).toEqual([
      "• traction: Three paid pilots with machine shops (unverified)",
      "• founder_team: Built robot arms for eight years (unverified)",
    ]);
    // an ended session takes no more input
    expect(screen.queryByRole("button", { name: "End evaluation" })).toBeNull();
    expect(screen.queryByLabelText("Pitch deck text")).toBeNull();
    expect(screen.queryByText("Then ask")).toBeNull();
    expect(within(left()).queryByRole("button", { name: "attach public source" })).toBeNull();
    expect(within(left()).queryByRole("button", { name: "resolve with note" })).toBeNull();
    expect(screen.queryByTestId("eval-staged")?.querySelector('[aria-disabled="true"]') ?? null).toBeNull();
    await waitFor(() => expect(row("ev-1")).toHaveTextContent("ended"));
  });

  it("an ended session links to its Founder Call record", async () => {
    fakeServer();
    const { router } = renderPage("/evaluator?session=ev-2");
    await screen.findByTestId("eval-workspace");
    const ended = screen.getByTestId("eval-ended");
    expect(ended).toHaveTextContent(
      "Ended 2026-11-05 15:00 · Founder Call record created (1 of 6 canonical sections mapped from founder-reported answers; the rest stay UNKNOWN)",
    );
    expect(screen.getAllByTestId("eval-followup").map((f) => f.textContent)).toEqual(["• Ask again: why now?"]);
    fireEvent.click(within(ended).getByRole("link", { name: "Open the Founder Call record" }));
    await screen.findByTestId("elsewhere");
    expect(router.state.location.pathname + router.state.location.search).toBe("/founder-calls?call=call-7");
  });

  it("a refused end is a failure toast and nothing is refreshed", async () => {
    const server = fakeServer({ end: () => refuse("already ended") });
    const { qc } = renderPage("/evaluator?session=ev-1");
    await screen.findByTestId("eval-workspace");
    qc.setQueryData([CALLS, {}], { calls: [] });
    fireEvent.click(screen.getByRole("button", { name: "End evaluation" }));
    fireEvent.click(within(await dialog("End evaluation")).getByTestId("confirm-ok"));
    expect(await screen.findByText("✕ Working failed — already ended")).toBeInTheDocument();
    expect(qc.getQueryState([CALLS, {}])?.isInvalidated).toBe(false);
    expect(screen.getByRole("button", { name: "End evaluation" })).toBeInTheDocument();
    expect(server.posts()).toHaveLength(1);
  });
});

describe("Active Evaluator — the dated why-now trigger", () => {
  async function openTrigger() {
    fireEvent.click(within(right()).getByRole("button", { name: "Record dated why-now trigger (sourced)" }));
    return dialog("Record dated why-now trigger (sourced)");
  }
  function fill(dlg: HTMLElement, date: string) {
    fireEvent.change(within(dlg).getByLabelText("Trigger kind"), { target: { value: "fundraising" } });
    fireEvent.change(within(dlg).getByLabelText("Date of the trigger (when it happened, not today)"), { target: { value: date } });
    fireEvent.change(within(dlg).getByLabelText("Public source URL that documents it (not LinkedIn, not a search result)"), {
      target: { value: "https://tech.eu/kestrel-seed" },
    });
    fireEvent.change(within(dlg).getByLabelText("The dated fact as the source states it"), { target: { value: "Kestrel Labs raised a seed round" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Review trigger" }));
  }

  it("the form (old kinds) leads to a second confirmation; only that posts to Conviction's imq_trigger, then refreshes the session and Conviction", async () => {
    const server = fakeServer();
    const { qc } = renderPage("/evaluator?session=ev-1");
    await screen.findByTestId("eval-workspace");
    qc.setQueryData([PIPELINE, {}], { signals: [] });
    let dlg = await openTrigger();
    expect(dlg).toHaveTextContent("Same public-evidence rules as Conviction: a dated fact and the public source that documents it. Nothing is sent.");
    const kinds = within(dlg).getByLabelText("Trigger kind") as HTMLSelectElement;
    expect(Array.from(kinds.options).map((o) => o.value)).toEqual(["trigger", "founder_formation", "fundraising", "incorporation", "window"]);
    fill(dlg, "2026-10-20");
    let confirm = await dialog("Record why-now trigger");
    expect(confirm).toHaveTextContent('Record why-now trigger: fundraising · 2026-10-20 "Kestrel Labs raised a seed round" https://tech.eu/kestrel-seed');
    fireEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(server.posts()).toEqual([]);

    const reads = server.reads(SESSION);
    dlg = await openTrigger();
    fill(dlg, "2026-10-20");
    confirm = await dialog("Record why-now trigger");
    fireEvent.click(within(confirm).getByRole("button", { name: "Record trigger" }));
    expect(await screen.findByText("Dated why-now trigger recorded — IMQ re-evaluated")).toBeInTheDocument();
    expect(server.posts()).toEqual([
      {
        method: "POST",
        path: "/api/conviction/imq_trigger",
        body: { slug: "kestrel-labs", kind: "fundraising", date: "2026-10-20", url: "https://tech.eu/kestrel-seed", fact: "Kestrel Labs raised a seed round", confirm: true },
      },
    ]);
    await waitFor(() => expect(right()).not.toHaveTextContent("no dated why-now trigger"));
    expect(server.reads(SESSION)).toBe(reads + 1);
    expect(qc.getQueryState([PIPELINE, {}])?.isInvalidated).toBe(true);
  });

  it("a refused trigger is a failure toast and nothing is refreshed", async () => {
    const server = fakeServer();
    const { qc } = renderPage("/evaluator?session=ev-1");
    await screen.findByTestId("eval-workspace");
    qc.setQueryData([PIPELINE, {}], { signals: [] });
    const reads = server.reads(SESSION);
    fill(await openTrigger(), "2027-01-05");
    fireEvent.click(within(await dialog("Record why-now trigger")).getByRole("button", { name: "Record trigger" }));
    expect(await screen.findByText("✕ Recording the why-now trigger failed — trigger date must be YYYY-MM-DD and not in the future")).toBeInTheDocument();
    expect(server.reads(SESSION)).toBe(reads);
    expect(qc.getQueryState([PIPELINE, {}])?.isInvalidated).toBe(false);
    expect(right()).toHaveTextContent("no dated why-now trigger");
  });
});

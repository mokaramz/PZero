import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ALL_ITEMS } from "@/app/nav";
import { PIPELINE } from "@/features/conviction/api";
import { NOT_PORTED as CONVICTION } from "@/features/conviction/model/deferred";
import { CALLS } from "./api";
import { NOT_PORTED } from "./model/deferred";
import { companies, fakeServer, renderPage } from "./test/server";

const tree = () => screen.getByTestId("calls-tree");
const detail = () => screen.getByTestId("calls-detail");
const due = () => screen.getByTestId("calls-due");
const form = () => screen.getByTestId("call-form");
const toasts = () => screen.getAllByRole("status").find((s) => s.getAttribute("aria-live") === "polite")!;
const companyRow = (name: string) => within(tree()).getAllByTestId("tree-company").find((c) => c.firstElementChild?.firstElementChild?.textContent === name)!;
const founderRow = (name: string) => within(tree()).getAllByTestId("tree-founder").find((f) => within(f).queryByText(name, { selector: "b" }))!;
const callRows = (founder: string) => Array.from(founderRow(founder).querySelectorAll("button[class*=callRow]")) as HTMLButtonElement[];
const field = (label: string) => within(form()).getByLabelText(label) as HTMLInputElement;

async function loaded() {
  await screen.findByTestId("calls-tree");
}

function select(founder: string, i = 0) {
  fireEvent.click(callRows(founder)[i]);
}

/** navigator.clipboard as a spy (jsdom has none). */
function stubClipboard() {
  const writeText = vi.fn(async (_text: string) => {});
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  return writeText;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Founder Calls — the page", () => {
  it("is a ported nav view at /founder-calls", () => {
    expect(ALL_ITEMS.find((i) => i.legacyView === "calls")).toMatchObject({ path: "/founder-calls", label: "Founder Calls", page: expect.anything() });
  });

  it("shows the header disclaimer and the counts bar, and makes ONE read", async () => {
    const server = fakeServer();
    renderPage();
    await loaded();
    expect(screen.getByRole("heading", { level: 1, name: "Founder Calls" })).toBeInTheDocument();
    expect(screen.getByText(/^Private call notes — Company → Founder → conversations\./)).toHaveTextContent(
      "Private call notes — Company → Founder → conversations. Everything a founder says is Founder-reported — unverified: notes never verify identity or founder status, never change Gold/Strong, rankings or evidence gates, and never trigger outreach or Network promotion. Public verification stays in the sourced-evidence workflow.",
    );
    expect(screen.getByTestId("calls-counts").textContent).toBe("3 companies · 4 founders · 5 calls · 2 follow-ups due");
    expect(screen.getByRole("button", { name: "Add external founder call" })).toBeInTheDocument();
    expect(detail()).toHaveTextContent("Select a call, or log a new one.");
    expect(server.calls.map((c) => `${c.method} ${c.path}`)).toEqual(["GET /api/founder-calls/calls"]);
  });

  it("the due box lists overdue, due today and due soon only (not an open action without a date), in the server's order", async () => {
    fakeServer();
    renderPage();
    await loaded();
    expect(within(due()).getByRole("heading", { level: 3 })).toHaveTextContent("Due follow-ups");
    expect(within(due()).getAllByTestId("due-row").map((r) => r.textContent)).toEqual([
      "OVERDUEAda QuillKestrel LabsSend the deck to RobinMohamed · due 2026-11-10Mark done",
      "DUE TODAYDana ValePine RoboticsCheck the patentMohamed · due 2026-11-12Mark done",
      "DUE SOONBen RookOtter MillBook a site visitMohamed · due 2026-11-15Mark done",
    ]);
    expect(within(due()).queryByText("Meet the CTO")).not.toBeInTheDocument();
  });

  it("no due follow-ups → the old empty line; no companies → the old empty tree", async () => {
    fakeServer({}, []);
    renderPage();
    await loaded();
    expect(due()).toHaveTextContent("No follow-ups due. Every next action with a date shows here when it is due.");
    expect(tree().textContent).toBe(
      "No calls yet. Add external founder call, or use Log founder call on a Conviction company, a Founder Radar lead or a Network person.",
    );
    expect(screen.getByTestId("calls-counts").textContent).toBe("0 companies · 0 founders · 0 calls · 0 follow-ups due");
  });

  it("a failed read is shown as an error", async () => {
    fakeServer({ calls: () => ({ status: 500, body: { error: "database unavailable" } }) });
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("database unavailable");
  });
});

describe("Founder Calls — the tree", () => {
  it("Company → Founder → calls with the tags, call counts and link buttons", async () => {
    fakeServer();
    renderPage();
    await loaded();
    const head = (name: string) => companyRow(name).firstElementChild!;
    expect(head("Kestrel Labs").textContent).toBe("Kestrel Labspipeline2 calls");
    expect(within(head("Kestrel Labs") as HTMLElement).getByText("pipeline")).toHaveAttribute("title", "linked to an existing Project Zero record");
    expect(head("Otter Mill").textContent).toBe("Otter Millexternal1 calllink");
    expect(within(head("Otter Mill") as HTMLElement).getByText("external")).toHaveAttribute("title", "not yet linked to a Project Zero company record");
    expect(head("Pine Robotics").textContent).toBe("Pine Roboticsradar2 calls");

    const fhead = (name: string) => founderRow(name).firstElementChild!.textContent;
    expect(fhead("Ada Quill")).toBe("Ada Quilllinked+ Log call");
    expect(within(founderRow("Ada Quill")).getByText("linked")).toHaveAttribute("title", "linked to an existing Project Zero person");
    expect(fhead("Ben Rook")).toBe("Ben Rookexternallink+ Log call");
    expect(fhead("Cleo Marsh")).toBe("Cleo Marshexternallink+ Log call");
    expect(founderRow("Cleo Marsh")).toHaveTextContent("no calls yet");
    expect(callRows("Ada Quill").map((b) => b.textContent)).toEqual(["2026-11-02First scout callOVERDUE", "2026-11-09Follow-up / diligence callDONE"]);
    expect(callRows("Dana Vale").map((b) => b.textContent)).toEqual(["2026-11-05First scout callDUE TODAY", "2026-11-08First scout callOPEN"]);
    // a link button only where something is not linked yet
    expect(within(tree()).getAllByRole("button", { name: "link" })).toHaveLength(3);
  });
});

describe("Founder Calls — a call", () => {
  it("selecting a call shows its detail and puts ?call= in the URL", async () => {
    fakeServer();
    const { router } = renderPage();
    await loaded();
    select("Ada Quill");
    const d = await screen.findByTestId("call-detail");
    expect(router.state.location.search).toBe("?call=call-1");
    expect(callRows("Ada Quill")[0]).toHaveAttribute("aria-current", "true");
    const bar = d.firstElementChild!;
    expect(bar.textContent).toBe("Ada QuillKestrel LabsFirst scout call2026-11-02 10:30 · videoOVERDUEEditExport memo (.md)Prepare Manager briefing");
    expect(d).toHaveTextContent("Ada Quill (Kestrel Labs) — First scout call on 2026-11-02 via video.");
    expect(d).toHaveTextContent("Participants: Mohamed, Ada Quill");
    expect(d).toHaveTextContent("Discovery origin: scan · Introduction path: Robin → Ada");
    expect(d).toHaveTextContent("1. Why this company, problem and timing? Founder-reported — unverifiedSmall workshops cannot afford integrators.");
    expect(d).toHaveTextContent("Why did you personally start this? — Saw it at her father's shop.");
    expect(d).toHaveTextContent("2. What customer pull, usage, pilots or revenue exists? Founder-reported — unverifiedUNKNOWN — not answered");
    expect(d).toHaveTextContent("“Three paid pilots” Founder-reported — unverified");
    expect(d).toHaveTextContent("Risks: Hardware margins");
    expect(d).toHaveTextContent("Unanswered: Who is the buyer?");
    expect(d).toHaveTextContent("OVERDUE Send the deck to Robin — Mohamed · due 2026-11-10 Mark done");
    expect(d).toHaveTextContent("Why exceptional: Builder from the shop floor");
    expect(d).toHaveTextContent("Main concerns: UNKNOWN");
    expect(d).toHaveTextContent("Recommendation: Follow up · Confidence: Medium");
  });

  it("?call=<id> opens that call directly", async () => {
    fakeServer();
    renderPage("/founder-calls?call=call-3");
    await loaded();
    expect((await screen.findByTestId("call-detail")).firstElementChild).toHaveTextContent("Ben RookOtter Mill");
  });

  it("Call intelligence keeps its two tabs, each disabled with the one reason; nothing reads call_prep or post_call", async () => {
    const server = fakeServer();
    renderPage();
    await loaded();
    select("Ada Quill");
    const intel = await screen.findByTestId("call-intel");
    expect(within(intel).getByRole("heading", { level: 3 })).toHaveTextContent("Call intelligence");
    expect(within(intel).getAllByRole("button").map((b) => b.textContent)).toEqual(["Prep card", "After the call"]);
    expect(within(intel).getByTestId("call-prep")).toHaveTextContent(`Prep card${NOT_PORTED.intel}`);
    expect(within(intel).getByTestId("call-prep")).toHaveAttribute("data-deferred");
    fireEvent.click(screen.getByTestId("call-after-tab"));
    expect(within(intel).getByTestId("post-call")).toHaveTextContent(`After the call${NOT_PORTED.intel}`);
    expect(within(intel).queryByTestId("call-prep")).not.toBeInTheDocument();
    expect(server.calls.map((c) => c.path)).toEqual(["/api/founder-calls/calls"]);
  });

  it("the Scout Bridge button keeps its place, disabled with the bridge reason, and sends nothing", async () => {
    const server = fakeServer();
    renderPage();
    await loaded();
    select("Ada Quill");
    fireEvent.click(await screen.findByTestId("call-after-tab"));
    const scout = screen.getByRole("button", { name: "Approve paid research (Scout Bridge, capped)" });
    expect(NOT_PORTED.bridge).toBe(CONVICTION.bridge);
    expect(scout).toHaveAttribute("aria-disabled", "true");
    expect(scout).toHaveAttribute("title", "External research jobs arrive with the bridge port");
    expect(scout).toHaveAccessibleDescription("External research jobs arrive with the bridge port");
    fireEvent.click(scout);
    expect(server.posts()).toEqual([]);
    expect(server.calls).toHaveLength(1);
  });
});

describe("Founder Calls — logging and editing", () => {
  it("?log=1 with the context keys opens the form prefilled, drops the keys from the URL and POSTs the old body", async () => {
    const server = fakeServer();
    const { router } = renderPage(`/founder-calls?${new URLSearchParams({ log: "1", person_id: "p-eve", name: "Eve Example", company: "Wren Works", radar_key: "wren" })}`);
    await screen.findByTestId("call-form");
    await waitFor(() => expect(router.state.location.search).toBe(""));
    expect(within(form()).getByTestId("call-form-bar")).toHaveTextContent("Log founder call");
    expect(field("Founder").value).toBe("Eve Example");
    expect(field("Founder")).not.toHaveAttribute("readonly");
    expect(field("Company").value).toBe("Wren Works");
    expect(field("Date").value).toBe("2026-11-12");
    expect(field("Participants (comma-separated)").value).toBe("Mohamed, Eve Example");
    expect(within(form()).getAllByTestId("call-section").map((s) => s.querySelector("h3")?.textContent)).toEqual([
      "1. Why this company, problem and timing?",
      "2. What customer pull, usage, pilots or revenue exists?",
    ]);
    fireEvent.change(field("Objective of this call"), { target: { value: " First look " } });
    fireEvent.change(field("Answer: Why this company, problem and timing?"), { target: { value: "Robots for bakeries " } });
    fireEvent.change(within(form()).getByLabelText("Why did you personally start this?"), { target: { value: " grew up in one " } });
    fireEvent.click(within(within(form()).getAllByTestId("call-section")[1]).getByRole("checkbox"));
    fireEvent.change(field("Exact founder claims — one per line (Founder-reported — unverified)"), { target: { value: "Two pilots\nOne LOI" } });
    fireEvent.change(field("Next action"), { target: { value: "Send deck " } });
    fireEvent.change(field("Due date"), { target: { value: "2026-11-20" } });
    fireEvent.change(field("Why exceptional"), { target: { value: " Ex-baker " } });
    fireEvent.change(field("Recommendation"), { target: { value: "Monitor" } });
    fireEvent.click(within(within(form()).getByTestId("call-form-bar")).getByRole("button", { name: "Save call" }));
    await waitFor(() => expect(server.posts()).toHaveLength(1));
    expect(server.posts()[0]).toEqual({
      method: "POST",
      path: "/api/founder-calls/save",
      body: {
        id: "",
        founder: "Eve Example",
        company: "Wren Works",
        founder_id: "",
        company_id: "",
        person_id: "p-eve",
        pipeline_slug: "",
        radar_key: "wren",
        call_type: "first",
        date: "2026-11-12",
        time: "",
        channel: "video",
        participants: "Mohamed, Eve Example",
        discovery_origin: "",
        intro_path: "",
        objective: "First look",
        answers: {
          why: { a: "Robots for bakeries", unknown: false, followups: { "1": "grew up in one" } },
          pull: { a: "", unknown: true, followups: {} },
        },
        claims: "Two pilots\nOne LOI",
        observations: "",
        risks: "",
        open_questions: "",
        next_action: { text: "Send deck", owner: "Mohamed", due: "2026-11-20" },
        assessment: { why_exceptional: "Ex-baker", concerns: "", recommendation: "Monitor", confidence: "", next_action: "" },
      },
    });
    expect(await within(toasts()).findByText("Call saved (private, unverified)")).toBeInTheDocument();
    expect(within(toasts()).getByText("✓ Saving the call — done")).toBeInTheDocument();
    // the saved call is selected
    await waitFor(() => expect(router.state.location.search).toMatch(/^\?call=call-new-/));
    expect((await screen.findByTestId("call-detail")).firstElementChild).toHaveTextContent("Eve ExampleWren Works");
    expect(companyRow("Wren Works")).toBeTruthy();
  });

  it("changing the call type switches the template and starts with empty answers", async () => {
    fakeServer();
    renderPage("/founder-calls?log=1&name=Eve%20Example&company=Wren%20Works");
    await screen.findByTestId("call-form");
    fireEvent.change(field("Answer: Why this company, problem and timing?"), { target: { value: "x" } });
    fireEvent.change(field("Call type"), { target: { value: "followup" } });
    expect(within(form()).getAllByTestId("call-section").map((s) => s.querySelector("h3")?.textContent)).toEqual(["1. Metrics"]);
    fireEvent.change(field("Call type"), { target: { value: "first" } });
    expect(field("Answer: Why this company, problem and timing?").value).toBe("");
  });

  it("+ Log call on a founder opens the form with the founder and company read-only and their ids in the body", async () => {
    const server = fakeServer();
    renderPage();
    await loaded();
    fireEvent.click(within(founderRow("Cleo Marsh")).getByRole("button", { name: "+ Log call" }));
    expect(field("Founder").value).toBe("Cleo Marsh");
    expect(field("Founder")).toHaveAttribute("readonly");
    expect(field("Company").value).toBe("Otter Mill");
    expect(field("Company")).toHaveAttribute("readonly");
    fireEvent.click(within(form()).getAllByRole("button", { name: "Save call" })[1]);
    await waitFor(() => expect(server.posts()).toHaveLength(1));
    expect(server.posts()[0].body).toMatchObject({ id: "", founder: "Cleo Marsh", company: "Otter Mill", founder_id: "f-cleo", company_id: "co-otter" });
  });

  it("Add external founder call opens an empty form; Cancel closes it", async () => {
    fakeServer();
    renderPage();
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Add external founder call" }));
    expect(field("Founder").value).toBe("");
    expect(field("Participants (comma-separated)").value).toBe("Mohamed");
    expect(form()).toHaveTextContent("Private notes only. Nothing here verifies identity or founder status");
    fireEvent.click(within(within(form()).getByTestId("call-form-bar")).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByTestId("call-form")).not.toBeInTheDocument();
  });

  it("Edit → Save with nothing changed says “No changes”; a change says it was saved", async () => {
    const server = fakeServer();
    renderPage();
    await loaded();
    select("Ada Quill");
    fireEvent.click(within(await screen.findByTestId("call-detail")).getByRole("button", { name: "Edit" }));
    expect(within(form()).getByTestId("call-form-bar")).toHaveTextContent("Edit call");
    expect(field("Objective of this call").value).toBe("Understand the robot arm pilot");
    expect(field("Time").value).toBe("10:30");
    expect(within(form()).getByText("Post-call judgment (private) — fill after the call").closest("details")).toHaveAttribute("open");
    fireEvent.click(within(form()).getAllByRole("button", { name: "Save call" })[0]);
    expect(await within(toasts()).findByText("No changes")).toBeInTheDocument();
    expect(server.posts()[0].body).toMatchObject({
      id: "call-1",
      founder_id: "f-ada",
      company_id: "co-kestrel",
      participants: "Mohamed, Ada Quill",
      claims: "Three paid pilots",
      risks: "Hardware margins",
      open_questions: "Who is the buyer?",
      answers: { why: { a: "Small workshops cannot afford integrators.", unknown: false, followups: { "1": "Saw it at her father's shop." } }, pull: { a: "", unknown: true, followups: {} } },
      assessment: { why_exceptional: "Builder from the shop floor", concerns: "", recommendation: "Follow up", confidence: "Medium", next_action: "" },
    });
    // back on the detail; edit again and change something
    fireEvent.click(within(await screen.findByTestId("call-detail")).getByRole("button", { name: "Edit" }));
    fireEvent.change(field("Objective of this call"), { target: { value: "Understand the pilot economics" } });
    fireEvent.click(within(form()).getAllByRole("button", { name: "Save call" })[0]);
    expect(await within(toasts()).findByText("Call saved (private, unverified)")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("call-detail")).toHaveTextContent("Objective: Understand the pilot economics"));
  });

  it("a save from a Conviction company (?new=1 with pipeline_slug) offers the way back and returns there after the save", async () => {
    const server = fakeServer();
    const ctx = { new: "1", company: "Kestrel Labs", pipeline_slug: "kestrel-labs", name: "Ada Quill", discovery_origin: "scan" };
    const { router, qc } = renderPage(`/founder-calls?${new URLSearchParams(ctx)}`);
    await screen.findByTestId("call-form");
    qc.setQueryData([PIPELINE, {}], { signals: [] });
    const back = screen.getByTestId("call-back");
    expect(back).toHaveTextContent("← Back to Kestrel Labs (Conviction)");
    expect(back).toHaveAttribute("href", "/conviction?company=kestrel-labs");
    expect(field("Discovery origin").value).toBe("scan");
    fireEvent.click(within(form()).getAllByRole("button", { name: "Save call" })[0]);
    await waitFor(() => expect(router.state.location.pathname).toBe("/conviction"));
    expect(router.state.location.search).toBe("?company=kestrel-labs");
    expect(server.posts()[0].body).toMatchObject({ founder: "Ada Quill", company: "Kestrel Labs", pipeline_slug: "kestrel-labs", discovery_origin: "scan" });
    expect(await within(toasts()).findByText("Call saved — back on Kestrel Labs")).toBeInTheDocument();
    // Conviction reads the same founder calls
    expect(qc.getQueryState([PIPELINE, {}])?.isInvalidated).toBe(true);
  });

  it("a refused save (400 / 409 error bodies) is a failure: the toast says why and the form stays open", async () => {
    let answer = { status: 400, body: { error: "founder name and company are required" } };
    fakeServer({ save: () => answer });
    renderPage("/founder-calls?log=1&name=Eve&company=Wren");
    await screen.findByTestId("call-form");
    fireEvent.click(within(form()).getAllByRole("button", { name: "Save call" })[0]);
    expect(await within(toasts()).findByText("✕ Saving the call failed — founder name and company are required")).toBeInTheDocument();
    expect(screen.getByTestId("call-form")).toBeInTheDocument();
    expect(within(toasts()).queryByText("Call saved (private, unverified)")).not.toBeInTheDocument();
    answer = { status: 409, body: { ok: false, error: "the legacy data has not been imported yet" } as never };
    fireEvent.click(within(form()).getAllByRole("button", { name: "Save call" })[0]);
    expect(await within(toasts()).findByText("✕ Saving the call failed — the legacy data has not been imported yet")).toBeInTheDocument();
    expect(screen.getByTestId("call-form")).toBeInTheDocument();
  });
});

describe("Founder Calls — follow-ups", () => {
  it("Mark done in the due box POSTs {id, done: true} and refreshes the calls and Conviction", async () => {
    const server = fakeServer();
    const { qc } = renderPage();
    await loaded();
    qc.setQueryData([PIPELINE, {}], { signals: [] });
    fireEvent.click(within(within(due()).getAllByTestId("due-row")[0]).getByRole("button", { name: "Mark done" }));
    expect(await within(toasts()).findByText("Follow-up marked done")).toBeInTheDocument();
    expect(server.posts()).toEqual([{ method: "POST", path: "/api/founder-calls/followup", body: { id: "call-1", done: true } }]);
    await waitFor(() => expect(within(due()).getAllByTestId("due-row")).toHaveLength(2));
    expect(server.reads(CALLS)).toBe(2);
    expect(qc.getQueryState([PIPELINE, {}])?.isInvalidated).toBe(true);
    expect(screen.getByTestId("calls-counts")).toHaveTextContent("1 follow-ups due");
  });

  it("a done next action can be reopened from the detail", async () => {
    const server = fakeServer();
    renderPage("/founder-calls?call=call-2");
    const d = await screen.findByTestId("call-detail");
    expect(d).toHaveTextContent("DONE Ask for references — Founder · due 2026-11-11 · done 2026-11-11 Reopen");
    fireEvent.click(within(d).getByRole("button", { name: "Reopen" }));
    expect(await within(toasts()).findByText("Follow-up reopened")).toBeInTheDocument();
    expect(server.posts()).toEqual([{ method: "POST", path: "/api/founder-calls/followup", body: { id: "call-2", done: false } }]);
    await waitFor(() => expect(within(screen.getByTestId("call-detail")).getByRole("button", { name: "Mark done" })).toBeInTheDocument());
  });

  it("an unknown call (404 {error}) is a failure toast", async () => {
    fakeServer({ followup: () => ({ status: 404, body: { error: "unknown call" } }) });
    renderPage();
    await loaded();
    fireEvent.click(within(within(due()).getAllByTestId("due-row")[1]).getByRole("button", { name: "Mark done" }));
    expect(await within(toasts()).findByText("✕ Saving the follow-up failed — unknown call")).toBeInTheDocument();
    expect(within(toasts()).queryByText("Follow-up marked done")).not.toBeInTheDocument();
  });
});

describe("Founder Calls — linking", () => {
  it("link on a founder: the people picker (filterable) → POST {founder_id, person_id} → linked", async () => {
    const server = fakeServer();
    const { qc } = renderPage();
    await loaded();
    qc.setQueryData([PIPELINE, {}], { signals: [] });
    fireEvent.click(within(founderRow("Ben Rook")).getByRole("button", { name: "link" }));
    const dlg = screen.getByRole("dialog", { name: "Link founder to an existing Project Zero person" });
    expect(dlg).toHaveTextContent("Linking stores the link in your private call notes only — the existing record is not modified, and no call is lost or duplicated.");
    const rows = () => within(dlg).queryAllByRole("button").filter((b) => b.getAttribute("aria-label") !== "Close");
    expect(rows().map((b) => b.textContent)).toEqual(["Benjamin RookOtter Mill · CEO", "Gus FernleyFernley Tools"]);
    fireEvent.change(within(dlg).getByLabelText("Filter"), { target: { value: "fernley" } });
    expect(rows().map((b) => b.textContent)).toEqual(["Gus FernleyFernley Tools"]);
    fireEvent.change(within(dlg).getByLabelText("Filter"), { target: { value: "nobody" } });
    expect(dlg).toHaveTextContent("nothing to link to");
    fireEvent.change(within(dlg).getByLabelText("Filter"), { target: { value: "" } });
    fireEvent.click(within(dlg).getByRole("button", { name: /Benjamin Rook/ }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(await within(toasts()).findByText("Founder linked — calls kept under one record")).toBeInTheDocument();
    expect(server.posts()).toEqual([{ method: "POST", path: "/api/founder-calls/link", body: { founder_id: "f-ben", person_id: "p-ben" } }]);
    await waitFor(() => expect(founderRow("Ben Rook").firstElementChild!.textContent).toBe("Ben Rooklinked+ Log call"));
    expect(qc.getQueryState([PIPELINE, {}])?.isInvalidated).toBe(true);
  });

  it("link on a company: the Conviction picker → POST {company_id, pipeline_slug} → pipeline", async () => {
    const server = fakeServer();
    renderPage();
    await loaded();
    fireEvent.click(within(companyRow("Otter Mill").firstElementChild as HTMLElement).getByRole("button", { name: "link" }));
    const dlg = screen.getByRole("dialog", { name: "Link company to an existing pipeline company" });
    expect(within(dlg).getByRole("button", { name: /Otter Mill GmbH/ })).toHaveTextContent("Otter Mill GmbHBenjamin Rook, Cleo Marsh");
    fireEvent.click(within(dlg).getByRole("button", { name: /Otter Mill GmbH/ }));
    expect(await within(toasts()).findByText("Company linked")).toBeInTheDocument();
    expect(server.posts()).toEqual([{ method: "POST", path: "/api/founder-calls/link", body: { company_id: "co-otter", pipeline_slug: "otter-mill" } }]);
    await waitFor(() => expect(companyRow("Otter Mill").firstElementChild!.textContent).toBe("Otter Millpipeline1 call"));
  });

  it("an unknown founder (200 {ok: false}) says “link failed”; an unknown person (404 {error}) is a failure toast", async () => {
    let answer = { status: 200, body: { ok: false, founder_id: null } as unknown };
    fakeServer({ link: () => answer as { status: number; body: unknown } });
    renderPage();
    await loaded();
    fireEvent.click(within(founderRow("Ben Rook")).getByRole("button", { name: "link" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: /Gus Fernley/ }));
    expect(await within(toasts()).findByText("link failed")).toBeInTheDocument();
    answer = { status: 404, body: { error: "unknown person" } };
    fireEvent.click(within(founderRow("Ben Rook")).getByRole("button", { name: "link" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: /Gus Fernley/ }));
    expect(await within(toasts()).findByText("✕ Working failed — unknown person")).toBeInTheDocument();
  });
});

describe("Founder Calls — memo and briefing", () => {
  let clicked: Array<{ href: string; download: string }>;
  beforeEach(() => {
    clicked = [];
    Object.defineProperty(URL, "createObjectURL", { value: vi.fn((_b: Blob) => "blob:memo"), configurable: true });
    Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push({ href: this.getAttribute("href") ?? "", download: this.download });
    });
  });

  it("Export memo reads the memo fresh and shows it; Copy and Download .md stay in the browser", async () => {
    const writeText = stubClipboard();
    const server = fakeServer();
    renderPage("/founder-calls?call=call-1");
    const d = await screen.findByTestId("call-detail");
    fireEvent.click(within(d).getByRole("button", { name: "Export memo (.md)" }));
    const dlg = await screen.findByRole("dialog", { name: "Call memo — Ada Quill" });
    expect(within(dlg).getByTestId("call-md").textContent).toBe("# Call memo — Ada Quill\n\nAda Quill (Kestrel Labs) — First scout call on 2026-11-02 via video.");
    expect(dlg).toHaveTextContent("Founder-reported — unverified Private research note — not a sourced fact, not sent anywhere.");
    expect(server.reads("founder-calls/memo")).toBe(1);
    expect(server.calls.find((c) => c.path.startsWith("/api/founder-calls/memo"))?.path).toBe("/api/founder-calls/memo?id=call-1");
    fireEvent.click(within(dlg).getByRole("button", { name: "Copy" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(within(dlg).getByTestId("call-md").textContent));
    fireEvent.click(within(dlg).getByRole("button", { name: "Download .md" }));
    expect(clicked).toEqual([{ href: "blob:memo", download: "call-memo-ada-quill-2026-11-02.md" }]);
    const blob = vi.mocked(URL.createObjectURL).mock.calls[0][0] as Blob;
    expect(blob.type).toBe("text/markdown");
    expect(await blob.text()).toBe("# Call memo — Ada Quill\n\nAda Quill (Kestrel Labs) — First scout call on 2026-11-02 via video.");
    expect(server.posts()).toEqual([]);
    // closing and exporting again reads it again (never served from the cache)
    fireEvent.click(within(dlg).getByRole("button", { name: "Close" }));
    fireEvent.click(within(screen.getByTestId("call-detail")).getByRole("button", { name: "Export memo (.md)" }));
    await screen.findByRole("dialog", { name: "Call memo — Ada Quill" });
    expect(server.reads("founder-calls/memo")).toBe(2);
  });

  it("an unknown memo (404 {error}) is an error toast and no drawer", async () => {
    fakeServer({ memo: () => ({ status: 404, body: { error: "unknown call" } }) });
    renderPage("/founder-calls?call=call-1");
    fireEvent.click(within(await screen.findByTestId("call-detail")).getByRole("button", { name: "Export memo (.md)" }));
    expect(await within(toasts()).findByText("unknown call")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("Prepare Manager briefing asks first; Cancel sends nothing, confirming POSTs {founder_id, confirm: true} and shows it", async () => {
    const server = fakeServer();
    renderPage("/founder-calls?call=call-1");
    fireEvent.click(within(await screen.findByTestId("call-detail")).getByRole("button", { name: "Prepare Manager briefing" }));
    let ask = screen.getByRole("dialog", { name: "Prepare Manager briefing" });
    expect(ask).toHaveTextContent(
      "Prepare an Manager / Project A briefing from your private call notes? It is generated only on your request, stays unverified and is not sent anywhere.",
    );
    fireEvent.click(within(ask).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(server.posts()).toEqual([]);

    fireEvent.click(within(screen.getByTestId("call-detail")).getByRole("button", { name: "Prepare Manager briefing" }));
    ask = screen.getByRole("dialog", { name: "Prepare Manager briefing" });
    fireEvent.click(within(ask).getByRole("button", { name: "Prepare briefing" }));
    const dlg = await screen.findByRole("dialog", { name: "Project A briefing — Ada Quill" });
    expect(server.posts()).toEqual([{ method: "POST", path: "/api/founder-calls/briefing", body: { founder_id: "f-ada", confirm: true } }]);
    expect(within(dlg).getByTestId("call-md").textContent).toBe("# Project A briefing — Ada Quill\n\n2 call(s). Founder-reported — unverified");
    fireEvent.click(within(dlg).getByRole("button", { name: "Download .md" }));
    expect(clicked).toEqual([{ href: "blob:memo", download: "omar-briefing-ada-quill.md" }]);
    // nothing is stored, so nothing is refetched
    expect(server.reads(CALLS)).toBe(1);
  });

  it("a refused briefing (404 {error}) is a failure toast and no drawer", async () => {
    fakeServer({ briefing: () => ({ status: 404, body: { error: "no calls for this founder" } }) });
    renderPage("/founder-calls?call=call-1");
    fireEvent.click(within(await screen.findByTestId("call-detail")).getByRole("button", { name: "Prepare Manager briefing" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Prepare briefing" }));
    expect(await within(toasts()).findByText("✕ Working failed — no calls for this founder")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

it("the fixtures are invented and consistent: five calls, two of them counted as due", () => {
  const all = companies().flatMap((c) => c.founders.flatMap((f) => f.calls));
  expect(all.map((c) => c.due_state)).toEqual(["overdue", "done", "upcoming", "due", "open"]);
});

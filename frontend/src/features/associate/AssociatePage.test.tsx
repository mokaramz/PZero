import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ALL_ITEMS } from "@/app/nav";
import { searchHits } from "@/app/CommandPalette/searchHits";
import { fakeServer as convictionServer, renderPage as renderConviction } from "@/features/conviction/test/server";
import { SUGGESTIONS } from "./model/associate";
import type { AskRes, Msg } from "./model/types";
import { askOffline, askUnsaved, conversation, statusReady } from "./test/fixtures";
import { fakeServer, renderPage } from "./test/server";

const FIRST = "c-0a1b2c3d4e5f";
const SECOND = "c-1f2e3d4c5b6a";
const NEW = "c-5e6f7a8b9c0d";
const NOTICE = "This conversation was deleted while the answer was being prepared; the answer was not saved.";
const BANNER =
  "Model not available — paid AI is switched off. PZ Associate still answers from the Project Zero documentation; record lookups need the model.";

const tick = () => new Promise((r) => setTimeout(r, 20));
const answers = () => screen.queryAllByTestId("associate-answer");
const box = () => screen.getByRole("textbox", { name: "Ask PZ Associate" });
const drawer = () => screen.getByRole("complementary", { name: "Conversations" });
const headerAvatar = () => document.querySelector("header [data-testid=ardea-avatar]")!;
const asks = (server: ReturnType<typeof fakeServer>) => server.posts().filter((p) => p.path === "/api/associate/ask");

async function opened(path = "/associate", routes: Parameters<typeof fakeServer>[0] = {}) {
  const server = fakeServer(routes);
  const view = renderPage(path);
  await screen.findByRole("heading", { level: 1, name: "PZ Associate" });
  return { server, ...view };
}

/** The page with a saved conversation open (the model answer with every part). */
async function withConversation(routes: Parameters<typeof fakeServer>[0] = {}) {
  const r = await opened(`/associate?c=${FIRST}`, routes);
  await waitFor(() => expect(answers()).toHaveLength(1));
  return r;
}

function type(text: string) {
  fireEvent.change(box(), { target: { value: text } });
  fireEvent.keyDown(box(), { key: "Enter" });
}

/** A model answer with no dropped reference: Ardea is done. */
const modelAnswer = (over: Partial<Msg> = {}): AskRes => ({
  conversation: { id: NEW, title: "Lumenfold" },
  message: { role: "assistant", at: "2026-11-13T08:35:00Z", text: "Lumenfold is verified.", mode: "model", tools: [{ tool: "company_detail", ok: true }], notes: [], ...over },
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("PZ Associate — the page, its reads, loading and errors", () => {
  it("is a ported nav view at /associate", () => {
    expect(ALL_ITEMS.find((i) => i.legacyView === "associate")).toMatchObject({ path: "/associate", label: "PZ Associate", icon: "heron", page: expect.anything() });
  });

  it("the identity, the welcome and the offline banner; reads only the status and the conversations", async () => {
    const { server } = await opened();
    expect(screen.getByText("Explains, investigates and prepares — read-only. Every decision and message stays with you.")).toBeInTheDocument();
    expect(headerAvatar()).toHaveAttribute("aria-hidden", "true");
    expect(headerAvatar()).toHaveAttribute("data-state", "ready");
    expect(screen.getByRole("img", { name: "Ardea, the PZ Associate heron" })).toBeInTheDocument();
    expect(await screen.findByTestId("associate-offline")).toHaveTextContent(BANNER);
    const welcome = screen.getByTestId("associate-welcome");
    expect(within(welcome).getByText("Meet Ardea")).toBeInTheDocument();
    expect(within(welcome).getByRole("heading", { level: 2, name: "Patient, selective, and always grounded in your records." })).toBeInTheDocument();
    expect(within(welcome).getByRole("list", { name: "Suggested questions" })).toBeInTheDocument();
    expect(within(welcome).getAllByRole("button").map((b) => b.textContent)).toEqual([...SUGGESTIONS]);
    for (const n of ["Your context", "Drafts", "New conversation"]) expect(screen.getByRole("button", { name: n })).toBeInTheDocument();
    expect(screen.getByText("Enter to ask · Shift+Enter for a new line · Read-only: nothing in Project Zero is changed. With paid model access on, your question and the records used to answer go to the configured model provider.")).toBeInTheDocument();
    await within(drawer()).findByRole("button", { name: /^Which Conviction companies/ });
    await tick();
    expect([...new Set(server.gets())].sort()).toEqual(["/api/associate/conversations", "/api/associate/status"]);
    expect(server.writes()).toEqual([]);
  });

  it("no banner while the status loads, when a model is ready, or when the status read fails; 'no model is configured' as the fallback reason", async () => {
    fakeServer({ status: () => statusReady() });
    const v = renderPage();
    await screen.findByRole("heading", { level: 1, name: "PZ Associate" });
    await tick();
    expect(screen.queryByTestId("associate-offline")).toBeNull();
    v.unmount();
    fakeServer({ status: () => ({ status: 500, body: { ok: false, error: "status down" } }) });
    const w = renderPage();
    await tick();
    expect(screen.queryByTestId("associate-offline")).toBeNull();
    w.unmount();
    fakeServer({ status: () => ({ ...statusReady(), model: { ready: false, problem: null } }) });
    renderPage();
    expect(await screen.findByTestId("associate-offline")).toHaveTextContent("Model not available — no model is configured.");
  });

  it("the drawer: a spinner while it loads, then the empty note", async () => {
    fakeServer({ holdConversations: true });
    const v = renderPage();
    await screen.findByRole("heading", { level: 1, name: "PZ Associate" });
    expect(within(drawer()).getByRole("status")).toHaveTextContent("Loading…");
    v.unmount();
    fakeServer({ conversations: () => ({ conversations: [] }) });
    renderPage();
    expect(await screen.findByText("Nothing yet. Your conversations are saved in the Project Zero database.")).toBeInTheDocument();
    expect(within(drawer()).getByTestId("ardea-mark")).toHaveAttribute("aria-hidden", "true");
  });

  it("opening a conversation: 'Opening conversation…' instead of the welcome; a failed read shows its error with a retry", async () => {
    fakeServer({ holdConversation: true });
    const v = renderPage(`/associate?c=${FIRST}`);
    expect(await screen.findByText("Opening conversation…")).toBeInTheDocument();
    expect(screen.queryByTestId("associate-welcome")).toBeNull();
    v.unmount();
    const server = fakeServer();
    renderPage("/associate?c=c-000000000000");
    expect(await screen.findByRole("alert")).toHaveTextContent("conversation not found");
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(server.reads("/api/associate/conversation?id=c-000000000000")).toBe(2));
  });

  it("a failed ask shows its error; the question is no longer pending", async () => {
    await opened("/associate", { ask: () => ({ status: 500, body: { ok: false, error: "the Associate is unavailable" } }) });
    type("Which events are coming up?");
    expect(await screen.findByRole("alert")).toHaveTextContent("the Associate is unavailable");
    expect(screen.queryByTestId("associate-thinking")).toBeNull();
    expect(answers()).toHaveLength(0);
  });
});

describe("PZ Associate — an answer and its parts", () => {
  it("every part of a model answer: text, sources, documentation, actions, the tool trace and the notes", async () => {
    await withConversation();
    const a = answers()[0];
    expect(screen.getByText("Which Conviction companies are waiting on a Manager decision?")).toBeInTheDocument();
    expect(within(a).getByText("PZ Associate")).toBeInTheDocument();
    expect(within(a).queryByText("Documentation only")).toBeNull();
    // Markdown: bold, a list, an internal link and an external address as text
    expect(within(a).getByText("Lumenfold", { selector: "strong" })).toBeInTheDocument();
    expect(within(a).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Seed round led from Lisbon", "Founder call logged on 4 November"]);
    expect(within(a).getByRole("link", { name: "the case" })).toHaveAttribute("href", "/conviction?company=lumenfold");
    expect(within(a).getByText("their site (https://lumenfold.example)")).toBeInTheDocument();
    expect(within(a).queryByRole("link", { name: /their site/ })).toBeNull();
    // sources: a linked one and an unlinked one
    expect(within(a).getByText("Sources")).toBeInTheDocument();
    expect(within(a).getByRole("link", { name: "Lumenfold" })).toHaveAttribute("href", "/conviction?company=lumenfold");
    expect(within(a).getByText("Nimbra Labs").tagName).toBe("SPAN");
    // documentation
    expect(within(a).getByText("Documentation").parentElement).toHaveTextContent("Documentation PZ_OPERATING_MODEL.md › Manager gates");
    // actions
    expect(within(a).getByRole("link", { name: "Open Lumenfold" })).toHaveAttribute("href", "/conviction?company=lumenfold");
    expect(within(a).getByRole("button", { name: "Save as draft" })).toBeInTheDocument();
    // the trace: the tools read, then the notes
    const trace = within(a).getByTestId("associate-trace");
    expect([...trace.children].map((s) => s.textContent)).toEqual([
      "Read: manager decisions, company detail, candidate detail",
      "1 uncited reference(s) removed",
      "kept with you: sending a message to the Manager",
    ]);
    // Ardea: an uncited reference was dropped → not certain, in the answer and the header
    expect(within(a).getByTestId("ardea-avatar")).toHaveAttribute("data-state", "uncertain");
    expect(headerAvatar()).toHaveAttribute("data-state", "uncertain");
    // the drawer marks the open conversation
    expect(within(drawer()).getByRole("button", { name: /^Which Conviction companies/ })).toHaveAttribute("aria-current", "true");
  });

  it("the open action goes to its page", async () => {
    const { at } = await withConversation();
    fireEvent.click(screen.getByRole("link", { name: "Open Lumenfold" }));
    expect(await screen.findByTestId("landed")).toHaveTextContent("/conviction?company=lumenfold");
    expect(at()).toBe("/conviction?company=lumenfold");
  });

  it("an answer without sources, docs, actions, tools or notes shows only its text", async () => {
    await opened("/associate", { ask: () => modelAnswer({ tools: [], notes: [] }) });
    type("Is Lumenfold verified?");
    const a = await screen.findByTestId("associate-answer");
    expect(a).toHaveTextContent("Lumenfold is verified.");
    for (const t of ["Sources", "Documentation", "Read:"]) expect(within(a).queryByText(t, { exact: false })).toBeNull();
    expect(within(a).queryByTestId("associate-trace")).toBeNull();
    expect(within(a).queryAllByRole("button")).toHaveLength(0);
    expect(headerAvatar()).toHaveAttribute("data-state", "done");
  });

  it("an earlier answer rests (ready); only the latest shows its state", async () => {
    await withConversation({ ask: (b) => ({ ...modelAnswer(), conversation: { id: b.conversation_id!, title: "x" } }) });
    type("And is it verified?");
    await waitFor(() => expect(answers()).toHaveLength(2));
    expect(within(answers()[0]).getByTestId("ardea-avatar")).toHaveAttribute("data-state", "ready");
    expect(within(answers()[1]).getByTestId("ardea-avatar")).toHaveAttribute("data-state", "done");
  });
});

describe("PZ Associate — asking, offline", () => {
  it("a suggestion is asked from the documentation, cited and remembered; the follow-up stays in the conversation", async () => {
    const { server, at } = await opened();
    fireEvent.click(screen.getByRole("button", { name: SUGGESTIONS[2] }));
    const a = await screen.findByTestId("associate-answer");
    expect(asks(server)).toEqual([{ path: "/api/associate/ask", body: { message: SUGGESTIONS[2], conversation_id: null, context: null } }]);
    expect(a).toHaveTextContent("The model is not available right now (paid AI is switched off). Nothing was changed.");
    expect(within(a).getByText("Documentation only")).toBeInTheDocument();
    expect(within(a).getByText("Documentation", { exact: true }).parentElement).toHaveTextContent("PZ_DEAL_FLOW.md › Deal Flow triage · PZ_DEAL_FLOW.md › Your queue");
    expect(within(a).queryByTestId("associate-trace")).toBeNull(); // no tool, no note offline
    expect(headerAvatar()).toHaveAttribute("data-state", "uncertain");
    expect(at()).toBe(`/associate?c=${NEW}`);
    expect(await within(drawer()).findByRole("button", { name: new RegExp(`^${SUGGESTIONS[2].slice(0, 20)}`) })).toHaveAttribute("aria-current", "true");
    expect(screen.queryByTestId("associate-welcome")).toBeNull();
    // Shift+Enter is a new line, Enter asks — in the same conversation
    fireEvent.change(box(), { target: { value: "And what does Radar mean?" } });
    fireEvent.keyDown(box(), { key: "Enter", shiftKey: true });
    await tick();
    expect(asks(server)).toHaveLength(1);
    fireEvent.submit(box().closest("form")!);
    await waitFor(() => expect(answers()).toHaveLength(2));
    expect(asks(server)[1].body).toEqual({ message: "And what does Radar mean?", conversation_id: NEW, context: null });
    expect(box()).toHaveValue("");
  });

  it("while the answer is prepared: the question, Ardea thinking, the Ask button busy; a second send is ignored", async () => {
    const { server } = await opened("/associate", { holdAsk: true });
    type("What should I focus on today?");
    expect(await screen.findByTestId("associate-thinking")).toHaveTextContent("Reading Project Zero…");
    expect(screen.getByText("What should I focus on today?")).toBeInTheDocument();
    expect(headerAvatar()).toHaveAttribute("data-state", "thinking");
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    expect(screen.queryByTestId("associate-welcome")).toBeNull();
    type("Again?");
    await tick();
    expect(asks(server)).toHaveLength(1);
  });

  it("an empty question is not sent", async () => {
    const { server } = await opened();
    type("   ");
    await tick();
    expect(asks(server)).toEqual([]);
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
  });
});

describe("PZ Associate — an answer that was not saved (revision 2)", () => {
  it("deleted elsewhere while the answer was prepared: the reply and the notice, and the conversation is not added back", async () => {
    const server = fakeServer({
      ask: (b) => {
        if (b.conversation_id !== FIRST) return askOffline(); // a later question: saved, in a new conversation
        server.drop(FIRST);
        return askUnsaved();
      },
    });
    const { at } = renderPage(`/associate?c=${FIRST}`);
    await waitFor(() => expect(answers()).toHaveLength(1));
    type("Explain how a company reaches Radar.");
    const notice = await screen.findByTestId("associate-unsaved");
    expect(notice).toHaveTextContent(NOTICE);
    expect(notice).toHaveAttribute("role", "status");
    expect(answers()).toHaveLength(1);
    expect(answers()[0]).toHaveTextContent("A company reaches Radar only once every claim on its case is verified.");
    expect(answers()[0]).toContainElement(notice);
    expect(screen.getByText("Explain how a company reaches Radar.", { selector: "div" })).toBeInTheDocument();
    expect(at()).toBe("/associate");
    await waitFor(() => expect(within(drawer()).queryByRole("button", { name: /^Which Conviction companies/ })).toBeNull());
    expect(within(drawer()).getAllByRole("button", { name: /^Explain how/ })).toHaveLength(1); // the other conversation only
    expect(within(drawer()).queryByRole("button", { current: true })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    await tick();
    expect(server.reads(`/api/associate/conversation?id=${FIRST}`)).toBe(1); // never re-read
    expect(headerAvatar()).toHaveAttribute("data-state", "uncertain");
    // the next question starts afresh, and the unsaved turn gives way
    type("Anything new on the desk?"); // (a question no other test leaves in flight)
    await waitFor(() => expect(asks(server)).toHaveLength(2));
    expect(asks(server)[1].body).toMatchObject({ conversation_id: null });
    await waitFor(() => expect(at()).toBe(`/associate?c=${NEW}`));
    await waitFor(() => expect(answers()).toHaveLength(1));
    expect(screen.queryByTestId("associate-unsaved")).toBeNull();
  });

  it("removed from the drawer while the answer was prepared: the same, and nothing is recreated", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const server = fakeServer({ askGate: gate, ask: () => askUnsaved() });
    const { at } = renderPage(`/associate?c=${FIRST}`);
    await waitFor(() => expect(answers()).toHaveLength(1));
    type("Explain how a company reaches Radar.");
    await screen.findByTestId("associate-thinking");
    fireEvent.click(within(drawer()).getByRole("button", { name: /Remove conversation: Which Conviction/ }));
    await waitFor(() => expect(server.posts().map((p) => p.path)).toContain("/api/associate/conversation_delete"));
    await act(async () => release());
    expect(await screen.findByTestId("associate-unsaved")).toHaveTextContent(NOTICE);
    expect(at()).toBe("/associate");
    expect(server.index().map((c) => c.id)).toEqual([SECOND]);
    expect(within(drawer()).queryByRole("button", { name: /^Which Conviction companies/ })).toBeNull();
    // a draft of the unsaved answer belongs to no conversation
    expect(screen.queryByRole("button", { name: "Save as draft" })).toBeNull();
  });

  it("opening another conversation or starting a new one clears the unsaved turn", async () => {
    await opened("/associate", { ask: () => ({ ...askUnsaved(), notice: undefined }) });
    type("Explain how a company reaches Radar.");
    expect(await screen.findByTestId("associate-unsaved")).toHaveTextContent(NOTICE); // the fallback wording
    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    expect(screen.queryByTestId("associate-unsaved")).toBeNull();
    expect(screen.getByTestId("associate-welcome")).toBeInTheDocument();
  });
});

describe("PZ Associate — drafts, only after confirmation", () => {
  it("Save as draft opens the confirmation; Cancel, Escape and the close button send nothing", async () => {
    const { server } = await withConversation();
    for (const close of [
      () => fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" })),
      () => fireEvent.keyDown(document, { key: "Escape" }),
      () => fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: /close/i })),
    ]) {
      fireEvent.click(screen.getByRole("button", { name: "Save as draft" }));
      const dlg = await screen.findByRole("dialog", { name: "Save as a draft" });
      expect(dlg).toHaveTextContent("Saved only to your PZ Associate drafts in the Project Zero database. It is not sent to anyone and changes no record.");
      expect(within(dlg).getByRole("textbox", { name: "Title" })).toHaveValue("Manager questions for Lumenfold");
      expect(within(dlg).getByRole("textbox", { name: "Text" })).toHaveValue(conversation().messages[1].text);
      close();
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    }
    await tick();
    expect(server.writes()).toEqual([]);
  });

  it("Save draft sends one confirmed draft with the answer's record and conversation; an empty text cannot be saved", async () => {
    const { server } = await withConversation();
    fireEvent.click(screen.getByRole("button", { name: "Save as draft" }));
    const dlg = await screen.findByRole("dialog", { name: "Save as a draft" });
    const text = within(dlg).getByRole("textbox", { name: "Text" });
    fireEvent.change(text, { target: { value: "  " } });
    expect(within(dlg).getByRole("button", { name: "Save draft" })).toBeDisabled();
    fireEvent.change(text, { target: { value: "Ask who leads the Lumenfold seed round." } });
    fireEvent.change(within(dlg).getByRole("textbox", { name: "Title" }), { target: { value: "Lumenfold seed" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText("Draft saved to your PZ Associate drafts — nothing was sent")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(server.posts()).toEqual([
      {
        path: "/api/associate/draft",
        body: {
          title: "Lumenfold seed",
          body: "Ask who leads the Lumenfold seed round.",
          ref: { kind: "company", id: "lumenfold", label: "Lumenfold", link: "/conviction?company=lumenfold" },
          conversation_id: FIRST,
          confirm: true,
        },
      },
    ]);
  });

  it("the Drafts drawer: read only when opened, newest first, copy and remove", async () => {
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const { server } = await opened();
    await tick();
    expect(server.gets()).not.toContain("/api/associate/drafts");
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
    const dlg = await screen.findByRole("dialog", { name: "Drafts" });
    expect(dlg).toHaveTextContent("Prepared text you chose to keep. Nothing here has been sent — copy it into your own email or message when you decide.");
    await within(dlg).findByText("Manager questions for Lumenfold");
    expect([...dlg.querySelectorAll("li strong")].map((s) => s.textContent)).toEqual(["Manager questions for Lumenfold", "Intro note to Orvella"]);
    expect(within(dlg).getByText(/Who leads the seed round\?/)).toBeInTheDocument();
    fireEvent.click(within(dlg).getAllByRole("button", { name: "Copy" })[0]);
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("1. Who leads the seed round?\n2. Which pilot customer signed first?"));
    expect(await screen.findByText("Draft copied")).toBeInTheDocument();
    fireEvent.click(within(dlg).getAllByRole("button", { name: "Remove" })[1]);
    await waitFor(() => expect(within(dlg).queryByText("Intro note to Orvella")).toBeNull());
    expect(server.posts()).toEqual([{ path: "/api/associate/draft_delete", body: { id: "d-9f8e7d6c5b" } }]);
  });

  it("the Drafts drawer: loading, empty and a failed read", async () => {
    fakeServer({ holdDrafts: true });
    const v = renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Drafts" }));
    expect(within(await screen.findByRole("dialog", { name: "Drafts" })).getByText("Loading…")).toBeInTheDocument();
    v.unmount();
    fakeServer({ drafts: () => ({ drafts: [] }) });
    const w = renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Drafts" }));
    expect(await screen.findByText("No drafts yet.")).toBeInTheDocument();
    w.unmount();
    fakeServer({ drafts: () => ({ status: 500, body: { ok: false, error: "drafts unreadable" } }) });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Drafts" }));
    expect(await within(await screen.findByRole("dialog", { name: "Drafts" })).findByRole("alert")).toHaveTextContent("drafts unreadable");
  });
});

describe("PZ Associate — your context (the profile)", () => {
  it("six fields read when opened, prefilled; Save sends all six", async () => {
    const { server } = await opened();
    await tick();
    expect(server.gets()).not.toContain("/api/associate/profile");
    fireEvent.click(screen.getByRole("button", { name: "Your context" }));
    const dlg = await screen.findByRole("dialog", { name: "Your context" });
    expect(dlg).toHaveTextContent("How you like to work — PZ Associate reads this as your preferences. It never changes Project Zero's methodology, scoring or schedules.");
    await waitFor(() => expect(within(dlg).getAllByRole("textbox")).toHaveLength(6));
    const labels = ["Investment interests", "Sourcing priorities", "Quality standards", "Working routines", "Preferred output formats", "Decision boundaries"];
    for (const l of labels) expect(within(dlg).getByRole("textbox", { name: l })).toHaveAttribute("maxlength", "1200");
    expect(within(dlg).getByRole("textbox", { name: "Investment interests" })).toHaveValue("Climate software and industrial AI across the Nordics and Iberia");
    expect(within(dlg).getByRole("textbox", { name: "Working routines" })).toHaveValue("");
    fireEvent.change(within(dlg).getByRole("textbox", { name: "Working routines" }), { target: { value: "Deal Flow every morning" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Your context is saved")).toBeInTheDocument();
    expect(server.posts()).toEqual([
      {
        path: "/api/associate/profile",
        body: {
          interests: "Climate software and industrial AI across the Nordics and Iberia",
          sourcing_priorities: "",
          quality_standards: "Two independent sources for every traction claim",
          routines: "Deal Flow every morning",
          output_preferences: "Short bullet lists, the decision first",
          boundaries: "",
        },
      },
    ]);
    await waitFor(() => expect(server.reads("/api/associate/profile")).toBe(2)); // re-read after the save
    expect(within(dlg).getByRole("textbox", { name: "Working routines" })).toHaveValue("Deal Flow every morning");
  });

  it("loading and a failed read", async () => {
    fakeServer({ holdProfile: true });
    const v = renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Your context" }));
    expect(within(await screen.findByRole("dialog", { name: "Your context" })).getByText("Loading…")).toBeInTheDocument();
    v.unmount();
    fakeServer({ profile: () => ({ status: 500, body: { ok: false, error: "profile unreadable" } }) });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Your context" }));
    expect(await within(await screen.findByRole("dialog", { name: "Your context" })).findByRole("alert")).toHaveTextContent("profile unreadable");
  });
});

describe("PZ Associate — the conversation drawer", () => {
  it("lists newest first; a click opens one; New conversation clears it", async () => {
    const { server, at } = await opened();
    const rows = await within(drawer()).findAllByRole("button", { name: /^(Which|Explain)/ });
    expect(rows.map((r) => r.querySelector("span")!.textContent)).toEqual(["Which Conviction companies are waiting on a Manager", "Explain how a company reaches Radar."]);
    fireEvent.click(rows[1]);
    await waitFor(() => expect(answers()).toHaveLength(1));
    expect(at()).toBe(`/associate?c=${SECOND}`);
    expect(server.reads(`/api/associate/conversation?id=${SECOND}`)).toBe(1);
    expect(within(drawer()).getByRole("button", { name: /^Explain how/ })).toHaveAttribute("aria-current", "true");
    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    expect(at()).toBe("/associate");
    expect(screen.getByTestId("associate-welcome")).toBeInTheDocument();
    expect(box()).toHaveFocus();
  });

  it("removing a conversation: another one stays open; the open one gives way to a new conversation", async () => {
    const { server, at } = await withConversation();
    fireEvent.click(within(drawer()).getByRole("button", { name: "Remove conversation: Explain how a company reaches Radar." }));
    await waitFor(() => expect(within(drawer()).queryByRole("button", { name: /^Explain how/ })).toBeNull());
    expect(at()).toBe(`/associate?c=${FIRST}`);
    expect(answers()).toHaveLength(1);
    fireEvent.click(within(drawer()).getByRole("button", { name: "Remove conversation: Which Conviction companies are waiting on a Manager" }));
    expect(at()).toBe("/associate");
    expect(await screen.findByText("Nothing yet. Your conversations are saved in the Project Zero database.")).toBeInTheDocument();
    expect(screen.getByTestId("associate-welcome")).toBeInTheDocument();
    expect(server.posts()).toEqual([
      { path: "/api/associate/conversation_delete", body: { id: SECOND } },
      { path: "/api/associate/conversation_delete", body: { id: FIRST } },
    ]);
  });
});

describe("PZ Associate — the page context and the palette hand-over", () => {
  it("?company= (from Conviction) travels with the question until cleared", async () => {
    const { server, at } = await opened("/associate?company=lumenfold");
    expect(screen.getByTestId("associate-context")).toHaveTextContent("About: Company lumenfold");
    type("What is missing on this case?");
    await screen.findByTestId("associate-answer");
    expect(asks(server)[0].body).toEqual({ message: "What is missing on this case?", conversation_id: null, context: { company: "lumenfold" } });
    expect(at()).toBe(`/associate?company=lumenfold&c=${NEW}`);
    await tick(); // the router commits its location in a transition
    fireEvent.click(screen.getByRole("button", { name: "Clear the selected record" }));
    expect(screen.queryByTestId("associate-context")).toBeNull();
    expect(at()).toBe(`/associate?c=${NEW}`);
    type("And in general?");
    await waitFor(() => expect(asks(server)).toHaveLength(2));
    expect(asks(server)[1].body).toMatchObject({ context: null });
  });

  it("Conviction's 'Ask PZ Associate' hands the company over as ?company=", async () => {
    convictionServer();
    const { router } = renderConviction("/conviction?company=alpha");
    fireEvent.click(within(await screen.findByTestId("company-actions")).getByText("Actions"));
    fireEvent.click(screen.getByRole("button", { name: "Ask PZ Associate" }));
    await waitFor(() => expect(router.state.location.pathname + router.state.location.search).toBe("/associate?company=alpha"));
  });

  it("?candidate= (from Deal Flow) is a Deal Flow candidate", async () => {
    const { server } = await opened("/associate?candidate=cand-nimbra");
    expect(screen.getByTestId("associate-context")).toHaveTextContent("About: Deal Flow candidate cand-nimbra");
    type("Should I keep it?");
    await waitFor(() => expect(asks(server)).toHaveLength(1));
    expect(asks(server)[0].body).toMatchObject({ context: { candidate: "cand-nimbra" } });
  });

  it("the retired ?item= context is ignored: no chip, no context sent", async () => {
    const { server } = await opened("/associate?item=s-0042");
    expect(screen.queryByTestId("associate-context")).toBeNull();
    type("What is this item?");
    await waitFor(() => expect(asks(server)).toHaveLength(1));
    expect(asks(server)[0].body).toEqual({ message: "What is this item?", conversation_id: null, context: null });
  });

  it("the palette's ?q= is asked once, in a fresh conversation, then leaves the URL", async () => {
    const hit = searchHits("what needs my attention", { pages: ALL_ITEMS }).find((h) => h.kind === "ASK")!;
    expect(hit.to).toBe("/associate?q=what%20needs%20my%20attention");
    const server = fakeServer();
    const { at } = renderPage(hit.to);
    await screen.findByTestId("associate-answer");
    expect(screen.getAllByText("what needs my attention")[0]).toBeInTheDocument();
    expect(asks(server)).toEqual([{ path: "/api/associate/ask", body: { message: "what needs my attention", conversation_id: null, context: null } }]);
    expect(at()).toBe(`/associate?c=${NEW}`);
    await tick();
    expect(asks(server)).toHaveLength(1);
  });

  it("?q= with ?c= continues that conversation; a new ?q= on the open page is asked too", async () => {
    const server = fakeServer();
    const { router, at } = renderPage(`/associate?c=${SECOND}&q=and%20Radar%3F`);
    await waitFor(() => expect(answers()).toHaveLength(2));
    expect(asks(server)[0].body).toEqual({ message: "and Radar?", conversation_id: SECOND, context: null });
    expect(at()).toBe(`/associate?c=${SECOND}`);
    await act(() => router.navigate("/associate?q=which%20events%3F"));
    await waitFor(() => expect(asks(server)).toHaveLength(2));
    expect(asks(server)[1].body).toEqual({ message: "which events?", conversation_id: null, context: null });
  });
});

describe("PZ Associate — writes invalidate only the Associate's own reads", () => {
  it("an ask, a delete, a draft and a profile save leave every other cached read alone", async () => {
    const { qc } = await withConversation();
    qc.setQueryData(["conviction/pipeline", {}], { signals: [] });
    qc.setQueryData(["today", {}], { actions: [] });
    const spy = vi.spyOn(qc, "invalidateQueries");
    type("And is it verified?");
    await waitFor(() => expect(answers()).toHaveLength(2));
    fireEvent.click(screen.getAllByRole("button", { name: "Save as draft" })[0]);
    fireEvent.click(within(await screen.findByRole("dialog", { name: "Save as a draft" })).getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Your context" }));
    const dlg = await screen.findByRole("dialog", { name: "Your context" });
    await waitFor(() => expect(within(dlg).getAllByRole("textbox")).toHaveLength(6));
    fireEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    await screen.findByText("Your context is saved");
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(within(drawer()).getByRole("button", { name: /Remove conversation: Explain/ }));
    await waitFor(() => expect(within(drawer()).queryByRole("button", { name: /^Explain how/ })).toBeNull());
    const keys = spy.mock.calls.map(([f]) => String((f as { queryKey?: unknown[] })?.queryKey?.[0]));
    expect(new Set(keys)).toEqual(new Set(["associate/conversations", "associate/conversation", "associate/drafts", "associate/profile", "activity"]));
    expect(qc.getQueryState(["conviction/pipeline", {}])!.isInvalidated).toBe(false);
    expect(qc.getQueryState(["today", {}])!.isInvalidated).toBe(false);
  });
});

describe("PZ Associate — no Scout text or link anywhere", () => {
  const SCOUT = /scout/i;
  const expectNoScout = () => {
    expect(document.body.textContent).not.toMatch(SCOUT);
    expect([...document.querySelectorAll("a")].map((a) => a.getAttribute("href") ?? "").filter((h) => SCOUT.test(h))).toEqual([]);
  };

  it("the welcome, an answer, both drawers and the draft confirmation", async () => {
    await withConversation();
    expectNoScout();
    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    expectNoScout();
    fireEvent.click(screen.getByRole("button", { name: "Your context" }));
    await waitFor(() => expect(within(screen.getByRole("dialog")).getAllByRole("textbox")).toHaveLength(6));
    expectNoScout();
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
    await screen.findByText("Intro note to Orvella");
    expectNoScout();
  });

  it("a retired link in an answer is never a link: the source is plain text, the open action is dropped, the Markdown link is its label", async () => {
    await opened("/associate", {
      ask: () =>
        modelAnswer({
          text: "See [the Orvella item](/scout-intake?item=s-1) and [its signals](/scout-intake?tab=native).",
          sources: [{ kind: "company", id: "orvella", label: "Orvella", link: "/scout-bridge" }],
          actions: [
            { kind: "open", label: "Open Orvella", link: "/scout-intake?item=s-1" },
            { kind: "open", label: "Open Deal Flow", link: "/deal-flow" },
          ],
        }),
    });
    type("What about Orvella?");
    const a = await screen.findByTestId("associate-answer");
    expect(within(a).getByText("Orvella").tagName).toBe("SPAN");
    expect(within(a).queryByRole("link", { name: "Open Orvella" })).toBeNull();
    expect(within(a).queryByText("Open Orvella")).toBeNull();
    expect(within(a).getByRole("link", { name: /Open Deal Flow/ })).toHaveAttribute("href", "/deal-flow");
    expect(a).toHaveTextContent("See the Orvella item and its signals.");
    expectNoScout();
  });

  it("the offline answer fixture names no retired view", () => {
    expect(JSON.stringify(askOffline())).not.toMatch(SCOUT);
    expect(JSON.stringify(askUnsaved())).not.toMatch(SCOUT);
    expect(JSON.stringify(conversation())).not.toMatch(SCOUT);
  });
});

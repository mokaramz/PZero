import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ALL_ITEMS } from "@/app/nav";
import { fieldsOf, kindTone } from "./model/item";
import { fakeServer, items, renderPage } from "./test/server";

const rows = () => screen.queryAllByTestId("work-row");
const row = (title: string) => rows().find((r) => r.textContent?.includes(title))!;
const form = () => screen.getByRole("form", { name: "Public work item" });
const field = (name: string) => form().querySelector(`[name="${name}"]`) as HTMLInputElement;
const values = () => Object.fromEntries(["title", "platform", "kind", "url", "inbound", "notes"].map((n) => [n, field(n).value]));

async function loaded(n = 3) {
  await waitFor(() => expect(rows()).toHaveLength(n));
}

async function open(title: string) {
  fireEvent.click(within(row(title)).getByRole("button", { name: title }));
  await screen.findByRole("dialog");
}

afterEach(() => vi.unstubAllGlobals());

describe("Public work — the page", () => {
  it("is a ported nav view at /public-work", () => {
    expect(ALL_ITEMS.find((i) => i.legacyView === "work")).toMatchObject({ path: "/public-work", label: "Public work", page: expect.anything() });
  });

  it("lists the items in the order returned, with the header, the positioning rule and the columns", async () => {
    const server = fakeServer();
    renderPage();
    await loaded();
    expect(screen.getByRole("heading", { level: 1, name: "Public work" })).toBeInTheDocument();
    expect(
      screen.getByText("Good work → reputation → relationships → inbound. Track ideas, drafts, published pieces and the inbound they generate."),
    ).toBeInTheDocument();
    expect(screen.getByText("Positioning rule (from Manager):").parentElement).toHaveTextContent(
      "Positioning rule (from Manager): never present yourself publicly as a Project A Scout. Public identity = Porsche / automotive / engineering. This tracker will remind you on every item.",
    );
    expect(screen.getByRole("button", { name: "+ New item" })).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Status", "Title", "Platform", "Created", "Inbound / notes"]);
    expect(rows().map((r) => within(r).getAllByRole("button")[0].textContent)).toEqual([
      "What a gearbox line taught me about agents",
      "Vision QA on the paint shop",
      "Predictive maintenance myths",
    ]);
    const cells = (title: string) => within(row(title)).getAllByRole("cell").map((c) => c.textContent);
    // inbound wins over notes; notes when there is no inbound; the platform / kind are shown as stored
    expect(cells("What a gearbox line taught me about agents")).toEqual([
      "published",
      "What a gearbox line taught me about agents ↗",
      "linkedin",
      "2026-10-02",
      "Two DMs from plant engineers",
    ]);
    expect(cells("Vision QA on the paint shop")).toEqual(["draft", "Vision QA on the paint shop", "blog", "2026-10-20", "needs a diagram"]);
    expect(cells("Predictive maintenance myths")).toEqual(["someday", "Predictive maintenance myths", "mastodon", "2026-11-01", ""]);
    expect(server.calls.map((c) => `${c.method} ${c.path}`)).toEqual(["GET /api/content"]);
  });

  it("an item without kind, platform or created shows 'idea' and empty cells", async () => {
    fakeServer({}, [{ id: "w-9", title: "Bare idea" }]);
    renderPage();
    await loaded(1);
    expect(within(row("Bare idea")).getAllByRole("cell").map((c) => c.textContent)).toEqual(["idea", "Bare idea", "", "", ""]);
  });

  it("an empty list says what the right first item is", async () => {
    fakeServer({}, []);
    renderPage();
    expect(
      await screen.findByText("Nothing yet. One useful post about industrial AI (from your automotive seat) is the right first item."),
    ).toBeInTheDocument();
    expect(rows()).toHaveLength(0);
  });

  it("the status badge tone: published green, draft amber, anything else neutral", async () => {
    fakeServer({}, [...items(), { id: "w-9", title: "Bare idea" }]);
    renderPage();
    await loaded(4);
    const tone = (title: string) => within(row(title)).getAllByRole("cell")[0].firstElementChild?.className.match(/tone_(\w+?)_/)?.[1];
    expect(tone("What a gearbox line taught me about agents")).toBe("green");
    expect(tone("Vision QA on the paint shop")).toBe("amber");
    expect(tone("Predictive maintenance myths")).toBe("neutral");
    expect(tone("Bare idea")).toBe("neutral");
    expect(kindTone("published")).toBe("green");
    expect(kindTone("draft")).toBe("amber");
    expect(kindTone("idea")).toBe("neutral");
    expect(kindTone("someday")).toBe("neutral");
    expect(kindTone(undefined)).toBe("neutral");
  });

  it("the url opens in a new tab as ↗ named after the item; no url, no link", async () => {
    fakeServer();
    renderPage();
    await loaded();
    const link = within(row("What a gearbox line taught me about agents")).getByRole("link", { name: "Open What a gearbox line taught me about agents" });
    expect(link).toHaveTextContent("↗");
    expect(link).toHaveAttribute("href", "https://example.com/posts/gearbox-agents");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
    expect(within(row("Vision QA on the paint shop")).queryByRole("link")).toBeNull();
  });
});

describe("Public work — the drawer", () => {
  it("opens an item prefilled, with the publishing check", async () => {
    fakeServer();
    renderPage();
    await loaded();
    await open("What a gearbox line taught me about agents");
    expect(screen.getByRole("heading", { level: 2, name: "Edit item" })).toBeInTheDocument();
    expect(screen.getByText("Before publishing, check:").parentElement).toHaveTextContent(
      "Before publishing, check: does this describe you as a Project A Scout? It must not. Porsche / automotive / engineering positioning only.",
    );
    expect(values()).toEqual({
      title: "What a gearbox line taught me about agents",
      platform: "linkedin",
      kind: "published",
      url: "https://example.com/posts/gearbox-agents",
      inbound: "Two DMs from plant engineers",
      notes: "repost in spring",
    });
    expect(within(form()).getAllByRole("option").map((o) => o.textContent)).toEqual(["linkedin", "x", "blog", "other", "idea", "draft", "published"]);
    expect(within(form()).getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("an unknown platform / kind falls back to linkedin / idea", async () => {
    fakeServer();
    renderPage();
    await loaded();
    await open("Predictive maintenance myths");
    expect(values()).toMatchObject({ platform: "linkedin", kind: "idea", url: "", inbound: "", notes: "" });
    expect(fieldsOf(null)).toEqual({ title: "", platform: "linkedin", kind: "idea", url: "", inbound: "", notes: "" });
  });

  it("saving an edit posts {id, …fields}, toasts Saved, closes and refetches", async () => {
    const server = fakeServer();
    renderPage();
    await loaded();
    await open("Vision QA on the paint shop");
    fireEvent.change(field("kind"), { target: { value: "published" } });
    fireEvent.change(field("url"), { target: { value: "https://example.com/blog/vision-qa" } });
    fireEvent.click(within(form()).getByRole("button", { name: "Save" }));
    await screen.findByText("Saved");
    expect(server.posts("save")).toEqual([
      { id: "w-2", title: "Vision QA on the paint shop", platform: "blog", kind: "published", url: "https://example.com/blog/vision-qa", inbound: "", notes: "needs a diagram" },
    ]);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(server.reads()).toBe(2));
    await waitFor(() => expect(within(row("Vision QA on the paint shop")).getAllByRole("cell")[0]).toHaveTextContent("published"));
    expect(within(row("Vision QA on the paint shop")).getByRole("link", { name: "Open Vision QA on the paint shop" })).toBeInTheDocument();
  });

  it("JSON values the server kept render as text and survive an edit of another field (Codex H-149)", async () => {
    const odd = { id: "a", title: "Draft", inbound: { replies: 2 }, notes: ["x", "y"], url: "javascript:alert(1)", kind: 7 };
    const server = fakeServer({}, [odd, items()[1]]);
    renderPage();
    await loaded(2);
    const cells = within(row("Draft")).getAllByRole("cell");
    expect(cells[0]).toHaveTextContent("7");
    expect(cells[4]).toHaveTextContent('{"replies":2}');
    expect(within(row("Draft")).queryByRole("link")).toBeNull(); // not an http(s) url: no link
    expect(row("Vision QA on the paint shop")).toBeInTheDocument();
    await open("Draft");
    expect(field("inbound").value).toBe('{"replies":2}');
    fireEvent.change(field("title"), { target: { value: "Draft, retitled" } });
    fireEvent.click(within(form()).getByRole("button", { name: "Save" }));
    await screen.findByText("Saved");
    const [sent] = server.posts("save");
    expect(sent).toEqual({ id: "a", title: "Draft, retitled", platform: "linkedin", url: "javascript:alert(1)" });
    await waitFor(() => expect(row("Draft, retitled")).toBeInTheDocument());
    expect(within(row("Draft, retitled")).getAllByRole("cell")[4]).toHaveTextContent('{"replies":2}'); // kept as stored
  });

  it("an explicit null survives a title-only edit; an absent field gets the form default (Codex H-151)", async () => {
    const server = fakeServer({}, [{ id: "n", title: "Nully", inbound: null, notes: "kept" }]);
    renderPage();
    await loaded(1);
    await open("Nully");
    expect(field("inbound").value).toBe("");
    fireEvent.change(field("title"), { target: { value: "Nully, retitled" } });
    fireEvent.click(within(form()).getByRole("button", { name: "Save" }));
    await screen.findByText("Saved");
    expect(server.posts("save")[0]).toEqual({ id: "n", title: "Nully, retitled", platform: "linkedin", kind: "idea", url: "", notes: "kept" });
    await waitFor(() => expect(server.reads()).toBe(2));
    await waitFor(() => expect(row("Nully, retitled")).toBeInTheDocument());
    expect(server.stored()[0]).toMatchObject({ title: "Nully, retitled", inbound: null, url: "" }); // null kept; absent url → ""
  });

  it("a non-text value the operator edits is sent as the new text", async () => {
    const server = fakeServer({}, [{ id: "a", title: "Draft", inbound: { replies: 2 } }]);
    renderPage();
    await loaded(1);
    await open("Draft");
    fireEvent.change(field("inbound"), { target: { value: "Two replies" } });
    fireEvent.click(within(form()).getByRole("button", { name: "Save" }));
    await screen.findByText("Saved");
    expect(server.posts("save")[0]).toMatchObject({ id: "a", inbound: "Two replies" });
  });

  it("a new item posts only the fields (no id), then closes and the list shows it", async () => {
    const server = fakeServer();
    renderPage();
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "+ New item" }));
    await screen.findByRole("dialog");
    expect(screen.getByRole("heading", { level: 2, name: "New public-work item" })).toBeInTheDocument();
    expect(within(form()).queryByRole("button", { name: "Delete" })).toBeNull();
    expect(values()).toEqual({ title: "", platform: "linkedin", kind: "idea", url: "", inbound: "", notes: "" });
    fireEvent.change(field("title"), { target: { value: "Torque curves for product people" } });
    fireEvent.change(field("platform"), { target: { value: "x" } });
    fireEvent.change(field("notes"), { target: { value: "thread, 6 posts" } });
    fireEvent.click(within(form()).getByRole("button", { name: "Save" }));
    await screen.findByText("Saved");
    expect(server.posts("save")).toEqual([{ title: "Torque curves for product people", platform: "x", kind: "idea", url: "", inbound: "", notes: "thread, 6 posts" }]);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await loaded(4);
    expect(rows()[3]).toHaveTextContent("Torque curves for product people");
  });

  it("delete posts {id}, toasts Deleted, closes and the row is gone", async () => {
    const server = fakeServer();
    renderPage();
    await loaded();
    await open("Predictive maintenance myths");
    fireEvent.click(within(form()).getByRole("button", { name: "Delete" }));
    await screen.findByText("Deleted");
    expect(server.posts("delete")).toEqual([{ id: "w-3" }]);
    expect(server.posts("save")).toEqual([]);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await loaded(2);
  });

  it("a refused save keeps the drawer open with the edits and shows the error", async () => {
    const server = fakeServer({ save: () => ({ status: 400, body: { ok: false, error: "id must be a string" } }) });
    renderPage();
    await loaded();
    await open("Vision QA on the paint shop");
    fireEvent.change(field("notes"), { target: { value: "add the before/after photos" } });
    fireEvent.click(within(form()).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("✕ Saving failed — id must be a string")).toBeInTheDocument();
    expect(server.posts("save")).toHaveLength(1);
    expect(screen.queryByText("Saved")).toBeNull();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(field("notes").value).toBe("add the before/after photos");
    expect(server.reads()).toBe(1);
  });
});

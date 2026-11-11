import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { preparedCase } from "./test/fixtures";
import { fakeServer, renderPage, type Routes } from "./test/server";

const rowSlugs = () => Array.from(document.querySelectorAll("[data-slug]")).map((r) => r.getAttribute("data-slug"));
const detailName = () => screen.getByRole("article").querySelector("h2")?.textContent;
const groupNames = () => screen.queryAllByRole("group").map((g) => g.getAttribute("aria-label")).filter((n) => n && !["View", "Operations", "System", "Company actions"].includes(n));

async function loaded() {
  await waitFor(() => expect(rowSlugs().length).toBeGreaterThan(0));
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

/** Every disabled control on screen says why (title + an sr-only description) and sends nothing when pressed. */
function checkInert(server: ReturnType<typeof fakeServer>) {
  const off = Array.from(document.querySelectorAll('[aria-disabled="true"]'));
  for (const el of off) {
    const reason = el.getAttribute("aria-describedby");
    expect(reason && document.getElementById(reason)?.textContent).toBeTruthy();
    expect(el.getAttribute("title")).toBeTruthy();
    pressEveryWay(el);
  }
  expect(server.posts()).toEqual([]);
  return off.map((e) => e.textContent);
}

function openSection(testId: string, title: string) {
  fireEvent.click(within(screen.getByTestId(testId)).getByText(title));
}

function openActions() {
  fireEvent.click(within(screen.getByTestId("company-actions")).getByText("Actions"));
}

async function openForm(name: string) {
  const dlg = await screen.findByRole("dialog", { name });
  await waitFor(() => expect(within(dlg).getByTestId("livescore")).toBeInTheDocument());
  return dlg;
}

const field = (dlg: HTMLElement, name: string) => dlg.querySelector(`[name="${name}"]`) as HTMLInputElement | HTMLSelectElement;

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("Conviction — the list", () => {
  it("groups by the client rules, hides dropped entries and counts the active ones", async () => {
    fakeServer();
    renderPage();
    await loaded();
    expect(groupNames()).toEqual(["Investigate & research", "Watch", "Conflict-gated · Manager first"]);
    // Investigate: provisional ≥ 63, sorted by provisional; WATCHING is listed under Watch; only potential_conflict gates
    expect(rowSlugs()).toEqual(["alpha", "unclear", "beta", "held", "gamma", "gate"]);
    expect(screen.getByTestId("pipe-counts")).toHaveTextContent("6 companies · 1 gated");
    expect(screen.getByTestId("pipe-counts")).toHaveAttribute("title", "0 fully verified");
    // nothing selected in the URL: the first listed company opens
    expect(detailName()).toBe("Alpha");
  });

  it("segments and the filter narrow the list; the segment lives in the URL (replace)", async () => {
    fakeServer();
    const { router } = renderPage();
    await loaded();
    fireEvent.click(screen.getByRole("tab", { name: "Gated" }));
    await waitFor(() => expect(groupNames()).toEqual(["Conflict-gated · Manager first"]));
    expect(router.state.location.search).toBe("?seg=gated");
    expect(router.state.historyAction).toBe("REPLACE");
    fireEvent.click(screen.getByRole("tab", { name: "All" }));
    await waitFor(() => expect(router.state.location.search).toBe(""));

    fireEvent.change(screen.getByLabelText("Filter companies"), { target: { value: "gamma" } });
    expect(rowSlugs()).toEqual(["gamma"]);
    fireEvent.change(screen.getByLabelText("Filter companies"), { target: { value: "zzz-nothing" } });
    expect(screen.getByText("No matches.")).toBeInTheDocument();
  });

  it("selecting a row writes ?company= with history replace", async () => {
    fakeServer();
    const { router } = renderPage("/conviction?seg=watch");
    await loaded();
    expect(groupNames()).toEqual(["Watch"]);
    fireEvent.click(document.querySelector('[data-slug="gamma"]')!);
    await waitFor(() => expect(detailName()).toBe("Gamma"));
    expect(new URLSearchParams(router.state.location.search).get("company")).toBe("gamma");
    expect(new URLSearchParams(router.state.location.search).get("seg")).toBe("watch");
    expect(router.state.historyAction).toBe("REPLACE");
    expect(document.querySelector('[data-slug="gamma"]')).toHaveAttribute("aria-current", "true");
  });
});

describe("Conviction — deep links", () => {
  it("?company= opens any entry, a dropped one included", async () => {
    const server = fakeServer();
    renderPage("/conviction?company=gone");
    await loaded();
    expect(detailName()).toBe("Gone");
    expect(rowSlugs()).not.toContain("gone");
    expect(server.posts()).toEqual([]);
  });

  it("an unknown ?company= or ?seg= falls back quietly", async () => {
    fakeServer();
    renderPage("/conviction?company=nobody&seg=bogus");
    await loaded();
    expect(screen.getByText("Select a company.")).toBeInTheDocument();
    expect(groupNames()).toHaveLength(3);
  });
});

describe("Conviction — the company workspace", () => {
  it("shows the header, the scores, the highlights, the trace and the current state", async () => {
    fakeServer();
    renderPage("/conviction?company=held");
    await loaded();
    expect(detailName()).toBe("Held");
    expect(screen.getByTestId("score-block")).toHaveTextContent("75 provisional");
    expect(screen.getByTestId("score-block")).toHaveTextContent("45 verified");
    // WATCHING (a human outcome) shows the band separately
    expect(screen.getByTestId("score-band")).toHaveTextContent("score band: INVESTIGATE");
    expect(screen.getByTestId("op-status")).toHaveTextContent("Watching");
    expect(screen.getByTestId("company-highlights")).toHaveTextContent("1 named");
    expect(screen.getByTestId("company-highlights")).toHaveTextContent("0 of 3 core facts");
    expect(screen.getByRole("meter", { name: "0 of 3 core facts verified" })).toBeInTheDocument();

    fireEvent.click(document.querySelector('[data-slug="alpha"]')!);
    await waitFor(() => expect(detailName()).toBe("Alpha"));
    expect(screen.getByTestId("company-convergence")).toHaveTextContent("3 independent inputs converge");
    expect(screen.getByTestId("op-status")).toHaveTextContent("Case not prepared yet");
  });

  it("without a prepared case (404) the panel is 'not started' and never starts one", async () => {
    const server = fakeServer();
    renderPage();
    await loaded();
    await waitFor(() => expect(screen.getByTestId("case-state")).toHaveTextContent("NOT STARTED"));
    expect(screen.getByTestId("case-panel")).toHaveAttribute("data-state", "NOT STARTED");
    expect(screen.getByTestId("case-empty")).toHaveTextContent("Not prepared yet.");
    expect(server.calls.some((c) => c.path === "/api/conviction/case?slug=alpha")).toBe(true);
    const refresh = screen.getByTestId("case-refresh");
    expect(refresh).toHaveTextContent("Prepare case");
    expect(refresh).toHaveAttribute("title", "Case preparation arrives with the case-preparation port");
    pressEveryWay(refresh);
    expect(server.posts()).toEqual([]);
    // the seven sections, collapsed
    for (const id of ["sec-case", "sec-evidence", "sec-founders", "sec-funding", "sec-risks", "sec-omar", "case-details"])
      expect((screen.getByTestId(id) as HTMLDetailsElement).open).toBe(false);
  });

  it("an imported case shows read-only: its move and its recording actions are disabled, editing works", async () => {
    const server = fakeServer({ case: (slug) => (slug === "alpha" ? preparedCase() : undefined) });
    renderPage();
    await loaded();
    await waitFor(() => expect(screen.getByTestId("case-next")).toHaveAttribute("data-code", "CONTACT_FOUNDER"));
    expect(screen.getByTestId("case-state")).toHaveTextContent("READY FOR MOHAMED");
    expect(screen.getByTestId("pz-view")).toHaveTextContent("Investigate");
    const primary = screen.getByTestId("case-primary");
    expect(primary).toHaveTextContent("Record outreach…");
    expect(primary).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("button", { name: "Accept founders (your click)" })).toHaveAttribute("aria-disabled", "true");
    // the workflow opens the section it needs (founders), with its deferred contact record
    await waitFor(() => expect((screen.getByTestId("sec-founders") as HTMLDetailsElement).open).toBe(true));
    expect(screen.getByTestId("contact-record")).toHaveAttribute("aria-disabled", "true");
    expect(checkInert(server)).toEqual(expect.arrayContaining(["Refresh case", "Record outreach…", "Accept founders (your click)", "Record: outreach sent…"]));

    openSection("case-details", "Full audit");
    await waitFor(() => expect(screen.getByTestId("case-convene-chair")).toBeInTheDocument());
    expect(checkInert(server)).toEqual(expect.arrayContaining(["Convene the IC Chair (≈$0.04, ~3 min)", "Ask the committee to look", "Create research job (your click)", "view packet"]));

    // "Edit archetype" is a live move: it opens Edit & verify
    fireEvent.click(screen.getByRole("button", { name: "Edit archetype" }));
    await openForm("Edit & verify: Alpha");
    expect(server.posts()).toEqual([]);
  });

  it("every deferred control says why and sends nothing, by click or keyboard", async () => {
    const server = fakeServer();
    renderPage();
    await loaded();
    await waitFor(() => expect(screen.getByTestId("case-state")).toHaveTextContent("NOT STARTED"));
    openActions();
    expect(checkInert(server)).toEqual(expect.arrayContaining(["Weekly update", "Generate Radar", "Email draft", "Send to Manager", "Prepare case"]));
    expect(screen.getByRole("button", { name: "Weekly update" })).toHaveAttribute("title", "The weekly update arrives with the memo & email port");
    expect(screen.getByRole("button", { name: "Generate Radar" })).toHaveAttribute("title", "Generating the Radar arrives with the Radar port");
    expect(screen.getByRole("button", { name: "Send to Manager" })).toHaveAttribute("title", "The Manager handoff arrives with the Manager / IMQ port");

    openSection("sec-funding", "Funding & timing");
    await waitFor(() => expect(screen.getByRole("button", { name: "Record a dated trigger (sourced)" })).toBeInTheDocument());
    checkInert(server);

    openSection("sec-omar", "Manager / Team");
    await waitFor(() => expect(screen.getByTestId("imq")).toHaveTextContent("NOT YET IMQ"));
    expect((screen.getByTestId("sec-funding") as HTMLDetailsElement).open).toBe(false); // one open section at a time
    expect(checkInert(server)).toEqual(
      expect.arrayContaining(["Record dated why-now trigger (sourced)", "ask Scout 00 for a dated source ↗", "Start Active Evaluator"]),
    );
    expect(screen.getByTestId("omar-card")).toHaveTextContent("The Manager handoff arrives with the Manager / IMQ port");

    openSection("sec-founders", "Founders & relationship");
    await waitFor(() => expect(screen.getByTestId("founders-block")).toHaveTextContent("Founders and registries arrive with the identity port"));
    expect(screen.getByTestId("outreach-draft")).toHaveTextContent("Memos and emails arrive with the memo & email port");
    checkInert(server);
  });
});

describe("Conviction — writes", () => {
  it("the status select posts {slug, status} and the list follows the refetch", async () => {
    const server = fakeServer();
    renderPage();
    await loaded();
    openActions();
    fireEvent.change(screen.getByLabelText("Change status"), { target: { value: "contacted" } });
    await screen.findByText("Status → contacted");
    expect(server.posts()).toEqual([{ method: "POST", path: "/api/conviction/status", body: { slug: "alpha", status: "contacted" } }]);
    await waitFor(() => expect(screen.getByTestId("op-status")).toHaveTextContent("Contacted"));
    expect(screen.getByLabelText("Change status")).toHaveValue("contacted");
  });

  it("a checklist tick saves {slug, company, verified} and the row re-scores from the server", async () => {
    const server = fakeServer();
    renderPage();
    await loaded();
    const score = () => document.querySelector('[data-slug="alpha"] [data-testid="row-score"]')?.textContent;
    expect(score()).toBe("40");
    openSection("sec-evidence", "Evidence & verification");
    const box = await waitFor(() => screen.getByTestId("checklist").querySelector("[data-verify=traction]") as HTMLInputElement);
    fireEvent.click(box);
    await screen.findByText("Verified: traction");
    expect(server.posts()).toEqual([
      { method: "POST", path: "/api/conviction/save", body: { slug: "alpha", company: "Alpha", verified: { founders: false, traction: true, funding: false } } },
    ]);
    await waitFor(() => expect(score()).toBe("50"));
    expect(screen.getByTestId("checklist").querySelector("[data-verify=traction]")).toBeChecked();
  });

  it("Edit & verify previews the score live and saves the whole entry under its slug", async () => {
    const server = fakeServer();
    const { router } = renderPage();
    await loaded();
    openActions();
    fireEvent.click(within(screen.getByRole("group", { name: "Company actions" })).getByRole("button", { name: "Edit & verify" }));
    const dlg = await openForm("Edit & verify: Alpha");
    const live = within(dlg).getByTestId("livescore");
    expect(live).toHaveTextContent("Provisional 66");
    expect(live).toHaveTextContent("Verified 40");
    expect(live).toHaveTextContent("unverified: founders, traction, funding");
    fireEvent.change(field(dlg, "founder"), { target: { value: "25" } });
    expect(live).toHaveTextContent("Provisional 76");
    expect(live).toHaveTextContent("Verified 40");
    fireEvent.click(field(dlg, "v_founders"));
    expect(live).toHaveTextContent("Verified 65");
    fireEvent.click(within(dlg).getByRole("button", { name: "Save to pipeline" }));
    await screen.findByText("Saved & scored");
    const [save] = server.posts();
    expect(save.path).toBe("/api/conviction/save");
    expect(save.body).toMatchObject({
      slug: "alpha",
      company: "Alpha",
      archetype: 1,
      scores: { founder: 25, venture_scale: 15, why_now: 10, taste: 10, insight: 10 },
      verified: { founders: true, traction: false, funding: false },
      founders: [{ name: "alpha founder", background: "ex-somewhere" }],
      sources: ["https://tech.eu/a", "https://sifted.eu/b"],
      verify_list: [],
      earliness: "pre_seed",
      conflict: "none",
    });
    expect(save.body).not.toHaveProperty("inbox_id");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(new URLSearchParams(router.state.location.search).get("company")).toBe("alpha");
  });

  it("+ Add company creates an entry and selects it", async () => {
    const server = fakeServer();
    const { router } = renderPage();
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "+ Add company" }));
    const dlg = await openForm("Add company");
    expect(field(dlg, "archetype")).toHaveValue("0");
    fireEvent.change(field(dlg, "company"), { target: { value: "Newco" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save to pipeline" }));
    await waitFor(() => expect(detailName()).toBe("Newco"));
    const [save] = server.posts();
    expect(save.body).toMatchObject({ company: "Newco", discovery_tier: "manual", verify_list: ["Founders", "Traction", "Funding status / timing", "Portfolio conflict"] });
    expect(save.body).not.toHaveProperty("slug");
    expect(save.body).not.toHaveProperty("inbox_id");
    expect(router.state.location.search).toBe("?company=newco");
  });

  it("a duplicate name (409) offers the existing entry, which opens on click", async () => {
    const server = fakeServer();
    const { router } = renderPage("/conviction?company=gamma");
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "+ Add company" }));
    const dlg = await openForm("Add company");
    fireEvent.change(field(dlg, "company"), { target: { value: "Alpha" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save to pipeline" }));
    const alert = await within(dlg).findByTestId("save-duplicate");
    expect(alert).toHaveTextContent("a company with this name already exists — open it in Conviction to edit it");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(within(alert).getByRole("button", { name: "Open existing entry" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(router.state.location.search).toBe("?company=alpha");
    await waitFor(() => expect(detailName()).toBe("Alpha"));
    expect(server.posts()).toHaveLength(1);
  });

  it("a duplicate without a message still names the way out", async () => {
    const routes: Routes = { save: () => ({ status: 409, body: { ok: false, duplicate: true, slug: "beta" } }) };
    fakeServer(routes);
    renderPage();
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "+ Add company" }));
    const dlg = await openForm("Add company");
    fireEvent.change(field(dlg, "company"), { target: { value: "Beta" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save to pipeline" }));
    expect(await within(dlg).findByTestId("save-duplicate")).toHaveTextContent("A company with this name already exists in Conviction.");
  });

  it("a refused save (400) keeps the form open without a duplicate offer", async () => {
    fakeServer({ save: () => ({ status: 400, body: { ok: false, error: "signal date is in the future" } }) });
    renderPage();
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "+ Add company" }));
    const dlg = await openForm("Add company");
    fireEvent.change(field(dlg, "company"), { target: { value: "Later" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save to pipeline" }));
    await screen.findByText(/signal date is in the future/);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(within(dlg).queryByTestId("save-duplicate")).toBeNull();
  });
});

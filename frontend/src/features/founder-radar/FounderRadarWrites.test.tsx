/** The Founder Radar writes: every person, company and review action with its exact old POST body (ported from the old
 *  `founder-radar.spec.ts` body assertions), the refusals, and the unresolved-identity gates. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { ID, KELPWISE, kelpwise, radar } from "./test/fixtures";
import { BRIEF, NO_BOARDY_API, fakeServer, refuse, renderPage } from "./test/server";
import { useFrActions } from "./useFrActions";

const dialog = (name: string) => screen.findByRole("dialog", { name });
const BLOCK = "Resolve identity before promotion";

function card(testId: string, name: string): HTMLElement {
  const c = screen.queryAllByTestId(testId).find((x) => x.querySelector("header > span")?.textContent === name);
  if (!c) throw new Error(`no ${testId} for ${name}`);
  return c;
}

async function opened(path = "/founder-radar") {
  const r = renderPage(path);
  await screen.findByRole("heading", { level: 1, name: "Founder Radar" });
  return r;
}

/** Fill an ask dialog's fields (by label start) and press OK (and, with a confirmation step, Confirm). */
async function answer(title: string, fields: Record<string, string> = {}, { confirm = false, ok = "OK" } = {}) {
  const d = await dialog(title);
  for (const [label, value] of Object.entries(fields)) fireEvent.change(within(d).getByLabelText(new RegExp("^" + label.replace(/[?()]/g, "\\$&"))), { target: { value } });
  fireEvent.click(within(d).getByRole("button", { name: ok }));
  if (confirm) fireEvent.click(within(d).getByRole("button", { name: "Confirm" }));
  return d;
}

const bodies = (server: ReturnType<typeof fakeServer>, endpoint: string) => server.posts(endpoint).map((c) => c.body);

async function oskarDrawer(server = fakeServer()) {
  await opened(`/founder-radar?view=research&seg=insuf&person=${ID.oskar}`);
  const drawer = await dialog("Oskar Lindqvist");
  return { server, drawer, btn: (name: string) => within(drawer).getByRole("button", { name }) };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Founder Radar — cards", () => {
  it("Add to Watchlist and Dismiss on a person card post the old bodies", async () => {
    const server = fakeServer();
    await opened("/founder-radar?view=research&seg=insuf");
    const oskar = card("fr-person-card", "Oskar Lindqvist");
    fireEvent.click(within(oskar).getByRole("button", { name: "Add to Watchlist" }));
    await waitFor(() => expect(bodies(server, "action")).toEqual([{ id: ID.oskar, action: "watch" }]));
    expect(await screen.findByText("Recorded: watch")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Oskar Lindqvist" })).toBeNull(); // the link never opens the drawer

    fireEvent.click(within(oskar).getByRole("button", { name: "Dismiss" }));
    await answer("Dismiss", { "Why dismiss? (kept on record)": "not a founder" });
    await waitFor(() => expect(bodies(server, "action")[1]).toEqual({ id: ID.oskar, action: "dismiss", note: "not a founder" }));
    expect(await screen.findByText("Recorded: dismiss")).toBeInTheDocument();
  });

  it("a cancelled question sends nothing; Investigate founder status on a researcher", async () => {
    const server = fakeServer();
    await opened("/founder-radar?view=research&seg=research");
    const rhea = card("fr-person-card", "Rhea Castell");
    fireEvent.click(within(rhea).getByRole("button", { name: "Dismiss" }));
    fireEvent.click(within(await dialog("Dismiss")).getByRole("button", { name: "Cancel" }));
    fireEvent.click(within(rhea).getByRole("button", { name: "Investigate founder status" }));
    await waitFor(() => expect(bodies(server, "action")).toEqual([{ id: ID.rhea, action: "investigate_founder" }]));
  });

  it("a lead card: Add to Watchlist, Review company facts and Log founder call (with the radar key)", async () => {
    const server = fakeServer();
    await opened();
    const ilka = card("fr-lead-card", "Ilka Moravec");
    fireEvent.click(within(ilka).getByRole("button", { name: "Add to Watchlist" }));
    await waitFor(() => expect(bodies(server, "action")).toEqual([{ id: ID.ilka, action: "watch" }]));
    fireEvent.click(within(ilka).getByRole("button", { name: "Review company facts" }));
    expect(await dialog("Review — Borealis Robotics")).toBeInTheDocument();
    fireEvent.click(within(await dialog("Review — Borealis Robotics")).getByRole("button", { name: "Close" }));
    fireEvent.click(within(card("fr-lead-card", "Mira Talvik")).getByRole("button", { name: "Log founder call" }));
    expect(await screen.findByTestId("elsewhere")).toHaveTextContent(
      "/founder-calls?new=1&person_id=p-mira-talvik-1001&name=Mira+Talvik&company=Kelpwise+GmbH&radar_key=dom%3Akelpwise.example",
    );
  });

  it("a refusal (HTTP 200 {ok:false, error}) is shown, and nothing is recorded", async () => {
    fakeServer({ action: () => refuse("unknown person") });
    await opened("/founder-radar?view=research&seg=insuf");
    fireEvent.click(within(card("fr-person-card", "Oskar Lindqvist")).getByRole("button", { name: "Add to Watchlist" }));
    expect(await screen.findByText("✕ Saving failed — unknown person")).toBeInTheDocument();
    expect(screen.queryByText("Recorded: watch")).toBeNull();
  });
});

describe("Founder Radar — the unresolved identity gates", () => {
  it("block promotion, the pre-company opportunity and Boardy in the evidence drawer, and nothing is written", async () => {
    const server = fakeServer();
    await opened("/founder-radar?view=research");
    fireEvent.click(within(card("fr-company-card", "Kelpwise GmbH")).getByRole("button", { name: "Mira Talvik" }));
    const drawer = await dialog("Mira Talvik");
    expect(drawer.textContent!.match(new RegExp(BLOCK, "g"))!.length).toBeGreaterThanOrEqual(3);
    for (const name of [`Add to Network — ${BLOCK}`, `Create pre-company opportunity — ${BLOCK}`, `Prepare Boardy request — ${BLOCK}`]) {
      const b = within(drawer).getByRole("button", { name });
      expect(b).toBeDisabled();
      expect(b).toHaveAttribute("title", BLOCK);
    }
    expect(drawer.querySelectorAll("button[disabled]").length).toBeGreaterThanOrEqual(3);
    expect(within(drawer).getByRole("combobox", { name: "Boardy status" })).toBeDisabled();
    expect(within(drawer).queryByRole("button", { name: "Add to Network" })).toBeNull();
    expect(drawer).toHaveTextContent("Identityneeds identity resolutionofficial team page names the founder — no stable handle yet");
    expect(server.writes()).toEqual([]);
  });

  it("the promotion guard's refusal from the server is toasted and the dialog stays open", async () => {
    const server = fakeServer({ promote: () => ({ status: 200, body: { ok: false, person: null, error: BLOCK } }) });
    const { btn } = await oskarDrawer(server);
    fireEvent.click(btn("Add to Network"));
    const pm = await dialog("Add to Network — Oskar Lindqvist");
    fireEvent.click(within(pm).getByRole("button", { name: "Add to Network" }));
    expect(await screen.findByText(`✕ Promoting failed — ${BLOCK}`)).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Add to Network — Oskar Lindqvist" })).toBeInTheDocument();
  });
});

describe("Founder Radar — the evidence drawer (?person=)", () => {
  it("shows identity, ordering, relationship, evidence, bands, judgment, connections and history", async () => {
    const { drawer } = await oskarDrawer();
    expect(screen.getByTestId("fr-person")).toBe(within(drawer).getByTestId("fr-person"));
    expect(drawer).toHaveTextContent("IdentityresolvedGitHub identity #88 · corroborated by location");
    expect(drawer).toHaveTextContent("Evidence ordering—no number — identity or evidence gate not met");
    expect(drawer).toHaveTextContent("Relationshipdetectedstrength: not recorded · owner Mohamed");
    expect(drawer).toHaveTextContent("• [trajectory] 2 repos pushed this month — GitHub · source ↗ · 2026-11-10 21:01");
    expect(drawer).toHaveTextContent("Unknown = technical depth, talent magnet, technical theme_overlap. Integrity, coachability, obsession, resilience and trust are never inferred here.");
    expect(drawer).toHaveTextContent("2026-11-10 21:01 researching → detected · detected by founder scan");
    expect(within(drawer).getByRole("link", { name: "Search on LinkedIn ↗" })).toHaveAttribute(
      "href",
      "https://www.linkedin.com/search/results/people/?keywords=Oskar%20Lindqvist%20",
    );
    expect(within(drawer).queryByRole("button", { name: "Ask Scout 00 for identity evidence" })).toBeNull(); // resolved identity
  });

  it("Research, links, the pre-company opportunity, the introduction path and the Boardy status", async () => {
    const { server, drawer, btn } = await oskarDrawer();
    fireEvent.click(btn("Research"));
    await waitFor(() => expect(bodies(server, "action")).toHaveLength(1));
    fireEvent.click(btn("Link to company"));
    await answer("Link to company", { "Company / project name": "Kelpwise GmbH" });
    await waitFor(() => expect(bodies(server, "action")).toHaveLength(2));
    fireEvent.click(btn("Link to event"));
    await answer("Link to event", { "Event name": "Kiel Ocean Hack 2026" });
    await waitFor(() => expect(bodies(server, "action")).toHaveLength(3));
    fireEvent.click(btn("Create pre-company opportunity"));
    await answer("Create pre-company opportunity", { "Pre-company opportunity name": "Stream buoys" });
    await waitFor(() => expect(bodies(server, "action")).toHaveLength(4));
    fireEvent.click(btn("Record introduction path"));
    await answer("Record introduction path", { "Introduction path": "Nils Farrow → Oskar" });
    await waitFor(() => expect(bodies(server, "action")).toHaveLength(5));
    fireEvent.change(within(drawer).getByRole("combobox", { name: "Boardy status" }), { target: { value: "Boardy follow-up due" } });
    await waitFor(() => expect(bodies(server, "action")).toHaveLength(6));
    expect(bodies(server, "action")).toEqual([
      { id: ID.oskar, action: "research" },
      { id: ID.oskar, action: "link_company", company: "Kelpwise GmbH" },
      { id: ID.oskar, action: "link_event", event: "Kiel Ocean Hack 2026" },
      { id: ID.oskar, action: "opportunity", name: "Stream buoys" },
      { id: ID.oskar, action: "intro_path", route: "Nils Farrow → Oskar" },
      { id: ID.oskar, action: "boardy", status: "Boardy follow-up due" },
    ]);
    expect(await screen.findByText("Recorded: boardy")).toBeInTheDocument();
  });

  it("public evidence: the activity date is asked (and sent) only for trajectory", async () => {
    const { server, btn } = await oskarDrawer();
    fireEvent.click(btn("Add public evidence (URL + claim)"));
    const d = await dialog("Add public evidence (URL + claim)");
    expect(within(d).queryByLabelText(/^Activity date/)).toBeNull();
    expect(within(d).getByRole("button", { name: "OK" })).toBeDisabled(); // the URL is required
    fireEvent.change(within(d).getByLabelText(/^Evidence category/), { target: { value: "trajectory" } });
    await answer("Add public evidence (URL + claim)", {
      "Public source URL": "https://github.com/oskarl/streamer",
      "Source label": "GitHub repo",
      "Supported claim": "released v1.0",
      "Activity date": "2026-11-08",
    });
    await waitFor(() => expect(bodies(server, "action")).toHaveLength(1));
    expect(bodies(server, "action")[0]).toEqual({
      id: ID.oskar,
      action: "evidence",
      url: "https://github.com/oskarl/streamer",
      label: "GitHub repo",
      claim: "released v1.0",
      kind: "trajectory",
      activity_date: "2026-11-08",
    });
  });

  it("confirm identity (prefilled, with a confirmation step) and mark identity verified", async () => {
    const server = fakeServer();
    await opened(`/founder-radar?person=${ID.grain}`);
    const drawer = await dialog("grainhacker");
    fireEvent.click(within(drawer).getByRole("button", { name: "Confirm identity with evidence" }));
    const d = await answer("Confirm identity with evidence");
    expect(within(d).getByRole("alert").textContent).toBe(
      "Confirm: Gideon Rask (grainhacker) is co-founder of Grainline Labs\nSource: Grainline Labs about https://grainline.example/about",
    );
    fireEvent.click(within(d).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(bodies(server, "action")).toHaveLength(1));
    expect(bodies(server, "action")[0]).toEqual({
      id: ID.grain,
      action: "confirm_identity",
      name: "Gideon Rask",
      handle: "grainhacker",
      company: "Grainline Labs",
      url: "https://grainline.example/about",
      label: "Grainline Labs about",
      fact: "Gideon Rask (grainhacker) is co-founder of Grainline Labs",
      confirm: true,
    });

    fireEvent.click(within(drawer).getByRole("button", { name: "Mark identity verified (evidence required)" }));
    await answer(
      "Mark identity verified (evidence required)",
      { "Public source URL that verifies this identity": "https://grainline.example/team", "Source label": "team page", "Verified fact": "Gideon Rask (grainhacker) founded Grainline Labs" },
      { confirm: true },
    );
    await waitFor(() => expect(bodies(server, "action")).toHaveLength(2));
    expect(bodies(server, "action")[1]).toEqual({
      id: ID.grain,
      action: "verify_identity",
      url: "https://grainline.example/team",
      label: "team page",
      fact: "Gideon Rask (grainhacker) founded Grainline Labs",
      confirm: true,
    });
  });

  it("LinkedIn: Save URL, and manual verification (URL first, then fact + founder + confirm)", async () => {
    const { server, drawer, btn } = await oskarDrawer();
    fireEvent.click(btn("Mark verified manually (URL + fact + confirm)"));
    expect(await screen.findByText("Enter the canonical profile URL first")).toBeInTheDocument();
    const url = "https://www.linkedin.com/in/oskar-lindqvist";
    fireEvent.change(within(drawer).getByRole("textbox", { name: "LinkedIn profile URL" }), { target: { value: url } });
    fireEvent.click(btn("Save URL"));
    await waitFor(() => expect(bodies(server, "action")).toEqual([{ id: ID.oskar, action: "linkedin", url }]));
    fireEvent.click(btn("Mark verified manually (URL + fact + confirm)"));
    const d = await dialog("Mark verified manually");
    expect(d).toHaveTextContent("Provenance is recorded as operator action; nothing automated.");
    fireEvent.click(within(d).getByRole("checkbox", { name: "The profile confirmed founder / co-founder status" }));
    await answer("Mark verified manually", { "Verified fact from the profile": "Co-founder at Stream Buoys" }, { confirm: true });
    await waitFor(() => expect(bodies(server, "action")).toHaveLength(2));
    expect(bodies(server, "action")[1]).toEqual({
      id: ID.oskar,
      action: "linkedin",
      url,
      verified: true,
      founder: true,
      fact: "Co-founder at Stream Buoys",
      note: "Co-founder at Stream Buoys",
      confirm: true,
    });
  });

  it("Save judgment goes to Network's person_save", async () => {
    const { server, drawer, btn } = await oskarDrawer();
    fireEvent.change(within(drawer).getByRole("textbox", { name: "Your judgment" }), { target: { value: "Strong builder, no founder signal yet" } });
    fireEvent.click(btn("Save judgment"));
    await waitFor(() => expect(server.posts("person_save")).toHaveLength(1));
    expect(server.posts("person_save")[0]).toMatchObject({ path: "/api/network/person_save", body: { id: ID.oskar, human_judgment: "Strong builder, no founder signal yet" } });
    expect(await screen.findByText("Judgment saved")).toBeInTheDocument();
  });

  it("Prepare Boardy request shows the brief (nothing is sent); Add to Network promotes with the relationship facts", async () => {
    const { server, drawer, btn } = await oskarDrawer();
    fireEvent.click(btn("Prepare Boardy request"));
    expect(await within(drawer).findByTestId("fr-brief")).toHaveTextContent(NO_BOARDY_API);
    expect(within(drawer).getByTestId("fr-brief").textContent).toBe(`${BRIEF}\n\n(${NO_BOARDY_API})`);
    expect(bodies(server, "boardy_brief")).toEqual([{ id: ID.oskar }]);
    expect(await screen.findByText("Brief prepared — nothing was sent")).toBeInTheDocument();

    fireEvent.click(btn("Add to Network"));
    const pm = await dialog("Add to Network — Oskar Lindqvist");
    fireEvent.change(within(pm).getByLabelText("How do you know them?"), { target: { value: "met at Kiel Ocean Hack" } });
    fireEvent.change(within(pm).getByLabelText("Follow-up date"), { target: { value: "2026-11-20" } });
    fireEvent.click(within(pm).getByRole("button", { name: "Add to Network" }));
    await waitFor(() => expect(bodies(server, "promote")).toHaveLength(1));
    expect(bodies(server, "promote")[0]).toEqual({
      id: ID.oskar,
      how: "met at Kiel Ocean Hack",
      introduced_by: "",
      stage: "introduction path identified",
      last_interaction: "",
      next_action: "",
      next_action_date: "2026-11-20",
      channel: "",
      notes: "",
    });
    expect(await screen.findByText("Now in Network — history preserved")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Add to Network — Oskar Lindqvist" })).toBeNull());
  });

  it("Merge duplicate… asks again when the server needs confirmation, then merges", async () => {
    const { server, btn } = await oskarDrawer();
    fireEvent.click(btn("Merge duplicate…"));
    await answer("Merge duplicate…", { "ID of the duplicate person record": ID.wren });
    const d = await dialog("Merge duplicate…");
    await waitFor(() => expect(within(d).getByRole("button", { name: "Merge" })).toBeInTheDocument());
    fireEvent.click(within(d).getByRole("button", { name: "Merge" }));
    expect(within(d).getByRole("alert").textContent).toBe("Identity evidence supports a merge. Confirm?");
    fireEvent.click(within(d).getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText("Merged")).toBeInTheDocument();
    expect(bodies(server, "action")).toEqual([
      { id: ID.oskar, action: "merge", other: ID.wren },
      { id: ID.oskar, action: "merge", other: ID.wren, confirm: true },
    ]);
  });

  it("a merge refusal is shown", async () => {
    const server = fakeServer({ action: (b) => (b.action === "merge" ? refuse("merge refused: different strong identifiers") : undefined) });
    const { btn } = await oskarDrawer(server);
    fireEvent.click(btn("Merge duplicate…"));
    await answer("Merge duplicate…", { "ID of the duplicate person record": ID.dana });
    expect(await screen.findByText("merge refused: different strong identifiers")).toBeInTheDocument();
    expect(bodies(server, "action")).toEqual([{ id: ID.oskar, action: "merge", other: ID.dana }]);
  });

  it("Log founder call closes the drawer and opens Founder Calls' new-call form", async () => {
    const { btn } = await oskarDrawer();
    fireEvent.click(btn("Log founder call"));
    expect(await screen.findByTestId("elsewhere")).toHaveTextContent("/founder-calls?new=1&person_id=p-oskar-lindqvist-1007&name=Oskar+Lindqvist&company=&radar_key=");
  });
});

describe("Founder Radar — company actions", () => {
  it("Add sourced company fact (with the confirmation step) and Add public evidence post the old bodies", async () => {
    const server = fakeServer();
    await opened("/founder-radar?view=research");
    const kelp = card("fr-company-card", "Kelpwise GmbH");
    fireEvent.click(within(kelp).getByRole("button", { name: "Add sourced company fact" }));
    const f = await dialog("Add sourced company fact");
    fireEvent.change(within(f).getByLabelText(/^Which fact\?/), { target: { value: "recent_activity" } });
    await answer("Add sourced company fact", {
      Value: "pre-seed round announced",
      "Public source URL that states this fact": "https://kelpwise.example/news",
      "Source label": "Kelpwise news",
      "Exact supported claim as the page states it": "Kelpwise today announced its pre-seed round.",
      "Activity date": "2026-11-04",
    });
    expect(f).toHaveTextContent("Confirm sourced fact:");
    expect(within(f).getByRole("alert").textContent).toBe(
      'Confirm sourced fact:\nrecent_activity = pre-seed round announced · activity date 2026-11-04\n"Kelpwise today announced its pre-seed round."\nKelpwise news · https://kelpwise.example/news',
    );
    fireEvent.click(within(f).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(bodies(server, "company")).toHaveLength(1));
    expect(bodies(server, "company")[0]).toEqual({
      key: KELPWISE,
      fact: {
        field: "recent_activity",
        value: "pre-seed round announced",
        url: "https://kelpwise.example/news",
        label: "Kelpwise news",
        claim: "Kelpwise today announced its pre-seed round.",
        confirm: true,
        activity_date: "2026-11-04",
      },
    });
    expect(await screen.findByText("Sourced company fact recorded (binds only to recent_activity)")).toBeInTheDocument();

    fireEvent.click(within(kelp).getByRole("button", { name: "Add public evidence" }));
    await answer("Add public evidence", { "Public source URL": "https://kelpwise.example/about", "Source label": "About page", "Supported claim": "two marine engineers" });
    await waitFor(() => expect(bodies(server, "company")).toHaveLength(2));
    expect(bodies(server, "company")[1]).toEqual({ key: KELPWISE, evidence: { url: "https://kelpwise.example/about", label: "About page", claim: "two marine engineers" } });
    expect(await screen.findByText("Company evidence saved with provenance")).toBeInTheDocument();
  });

  it("a company refusal is shown", async () => {
    fakeServer({ company: () => refuse("a public source URL is required (not LinkedIn, not a search result)") });
    await opened("/founder-radar?view=research");
    fireEvent.click(within(card("fr-company-card", "Quillstone AI")).getByRole("button", { name: "Add public evidence" }));
    await answer("Add public evidence", { "Public source URL": "https://www.linkedin.com/company/quillstone" });
    expect(await screen.findByText("✕ Saving the company link failed — a public source URL is required (not LinkedIn, not a search result)")).toBeInTheDocument();
    expect(screen.queryByText("Company evidence saved with provenance")).toBeNull();
  });
});

describe("Founder Radar — the review drawer (?review=)", () => {
  it("one row per fact, alternatives collapsed, the summary; the bulk confirm excludes every identity", async () => {
    const server = fakeServer();
    await opened("/founder-radar?view=research");
    const kelp = card("fr-company-card", "Kelpwise GmbH");
    expect(kelp).toHaveTextContent("Priority:");
    expect(kelp).toHaveTextContent("Why:");
    expect(kelp).toHaveTextContent("Next:");
    expect(kelp.textContent).not.toContain("Research priority ");
    fireEvent.click(within(kelp).getByRole("button", { name: /^Review proposals/ }));
    const drawer = await dialog("Review — Kelpwise GmbH");
    await within(drawer).findByTestId("fr-review");
    expect(bodies(server, "proposals")).toEqual([{ key: KELPWISE }]);
    const rows = within(drawer).getAllByTestId("fr-review-row");
    const keys = rows.map((r) => `${r.getAttribute("data-field")} = ${r.getAttribute("data-value")}`);
    expect(keys).toEqual([
      "founded = 2025",
      "funding = pre-seed",
      "status = active",
      "recent_activity = dated item on news page (2026-11-04)",
      "project_a_fit = HIGH",
      "access_route = hello@kelpwise.example",
      "founder = Mira Talvik",
      "founder = Jonas Brekke",
      "operating_signal = customer / deployment wording",
    ]);
    expect(new Set(keys).size).toBe(keys.length);
    expect(drawer.querySelectorAll("details[open]")).toHaveLength(0);
    for (const k of ["Research summary", "Recommended facts", "Missing Gold/Strong requirements", "duplicate passage(s) hidden", "Why it matters"]) expect(drawer).toHaveTextContent(k);
    expect(drawer).toHaveTextContent("4 page(s) retrieved · 1 blocked/skipped · 7 fact(s) · 2 founder candidate(s) · 0 confirmed");
    expect(rows[0]).toHaveTextContent("2 supporting source(s) / duplicate passage(s) hidden");
    expect(rows[0]).toHaveTextContent("quoted public fact");
    expect(within(rows[4]).getByText("machine inference")).toBeInTheDocument();
    expect(rows[4].querySelector("i")?.textContent).toBe("themes: ocean, sensing, industrial IoT");
    expect(within(rows[8]).getByText("template text")).toBeInTheDocument();
    expect(within(rows[8]).getByText("disputed by another source")).toBeInTheDocument();
    expect(within(rows[8]).getByText("evidence kind unknown")).toBeInTheDocument();
    const recFields = rows.filter((r) => r.hasAttribute("data-recommended")).map((r) => r.getAttribute("data-field"));
    expect(recFields).toEqual(["founded", "funding", "status", "recent_activity"]);

    fireEvent.click(within(drawer).getByRole("button", { name: /^Confirm recommended facts \(\d+\)$/ }));
    await waitFor(() => expect(bodies(server, "review")).toHaveLength(1));
    const rv = bodies(server, "review")[0]!;
    expect(rv).toEqual({ key: KELPWISE, confirm: kelpwise().recommended, bindings: {} });
    for (const id of ["pr-k-f-mira", "pr-k-f-jonas"]) expect(rv.confirm).not.toContain(id);
    expect(await screen.findByText("Confirmed 2 recommended fact(s): founded, funding")).toBeInTheDocument();
  });

  it("per-row founder binding, an explicit pairing, per-proposal bindings, and a decided row never replays", async () => {
    const fx = kelpwise();
    const jonas = fx.groups.find((g) => g.field === "founder" && g.value === "Jonas Brekke")!;
    jonas.best.status = "confirmed";
    jonas.status = "confirmed";
    fx.history = [{ on: "2026-11-10 21:05:00", proposal: jonas.best.id, from: "pending", to: "confirmed", person: ID.jonas }];
    const server = fakeServer({ proposals_of: { [KELPWISE]: fx } });
    await opened(`/founder-radar?view=research&review=${encodeURIComponent(KELPWISE)}`);
    const drawer = await dialog("Review — Kelpwise GmbH");
    await within(drawer).findByTestId("fr-review");
    const selects = within(drawer).getAllByTestId("fr-bind");
    expect(selects).toHaveLength(2);
    expect(within(drawer).getByText("Decision history (1, append-only)")).toBeInTheDocument();
    expect(drawer).toHaveTextContent(`2026-11-10 21:05:00 pr-k-f-jonas pending→confirmed · ${ID.jonas}`);

    const mira = drawer.querySelector("[data-testid=fr-review-row][data-field=founder][data-value='Mira Talvik']") as HTMLElement;
    const sel = within(mira).getByTestId("fr-bind");
    const pid = sel.getAttribute("data-prop")!;
    expect(pid).toBe("pr-k-f-mira");
    expect(within(sel).getAllByRole("option").map((o) => o.textContent)).toEqual(["choose…", "Mira Talvik", "Jonas Brekke"]);

    // pairing without a chosen record asks for one first
    fireEvent.click(within(mira).getByRole("button", { name: "Confirm pairing…" }));
    expect(await screen.findByText("Select the founder reference to pair first")).toBeInTheDocument();

    fireEvent.change(sel, { target: { value: ID.mira } });
    fireEvent.click(within(mira).getByRole("button", { name: "Confirm pairing…" }));
    const dlg = await dialog("Confirm pairing");
    fireEvent.click(within(dlg).getByRole("button", { name: "Pair" }));
    expect(dlg).toHaveTextContent("Pair proposed human name");
    expect(within(dlg).getByRole("alert").textContent).toContain(`Mira Talvik (${ID.mira})`);
    fireEvent.click(within(dlg).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(bodies(server, "pair")).toEqual([{ key: KELPWISE, proposal: pid, person: ID.mira }]));
    expect(await screen.findByText("Pairing recorded — now Confirm selected")).toBeInTheDocument();

    // nothing selected yet → no request
    fireEvent.click(within(drawer).getByRole("button", { name: "Confirm selected" }));
    expect(await screen.findByText("Select proposals first")).toBeInTheDocument();
    expect(bodies(server, "review")).toEqual([]);

    fireEvent.click(within(mira).getByRole("checkbox"));
    fireEvent.click(within(drawer).getByRole("button", { name: "Confirm selected" }));
    await waitFor(() => expect(bodies(server, "review")).toEqual([{ key: KELPWISE, bindings: { [pid]: ID.mira }, confirm: [pid] }]));
    expect(await screen.findByText("Confirmed · facts: founded, funding · identity: Mira Talvik ✓")).toBeInTheDocument();

    const jonasRow = drawer.querySelector("[data-testid=fr-review-row][data-field=founder][data-value='Jonas Brekke']") as HTMLElement;
    expect(within(jonasRow).getByRole("checkbox")).toBeDisabled();
    expect(within(jonasRow).getByTestId("fr-bind")).toBeDisabled();
    expect(within(jonasRow).getByRole("button", { name: "Confirm pairing…" })).toBeDisabled();
  });

  it("Reject selected sends the chosen rows; a pairing refusal is shown", async () => {
    const server = fakeServer({ pair: () => refuse("only pending founder proposals can be paired") });
    await opened(`/founder-radar?review=${encodeURIComponent(KELPWISE)}`);
    const drawer = await dialog("Review — Kelpwise GmbH");
    await within(drawer).findByTestId("fr-review");
    fireEvent.click(within(drawer).getByRole("checkbox", { name: "select operating_signal = customer / deployment wording" }));
    fireEvent.click(within(drawer).getByRole("button", { name: "Reject selected" }));
    await waitFor(() => expect(bodies(server, "review")).toEqual([{ key: KELPWISE, bindings: {}, reject: ["pr-k-operating"] }]));
    expect(await screen.findByText("Rejected · facts: founded, funding")).toBeInTheDocument();

    const jonas = drawer.querySelector("[data-testid=fr-review-row][data-value='Jonas Brekke']") as HTMLElement;
    fireEvent.change(within(jonas).getByTestId("fr-bind"), { target: { value: ID.jonas } });
    fireEvent.click(within(jonas).getByRole("button", { name: "Confirm pairing…" }));
    await answer("Confirm pairing", {}, { ok: "Pair", confirm: true });
    expect(await screen.findByText("✕ Pairing failed — only pending founder proposals can be paired")).toBeInTheDocument();
  });

  it("a company without research says so; a decided set has nothing to bulk-confirm", async () => {
    const server = fakeServer();
    await opened(`/founder-radar?review=${encodeURIComponent("dom:quillstone.example")}`);
    const drawer = await dialog("Review — Quillstone AI");
    expect(await within(drawer).findByText("No proposals yet — press Research company.")).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "Confirm recommended facts (0)" }));
    expect(await screen.findByText("No recommended facts to confirm")).toBeInTheDocument();
    expect(bodies(server, "review")).toEqual([]);
  });
});

/* ------------------------------------------------------------------ the 400 for an unknown state */

function StateProbe({ state }: { state: string }) {
  const actions = useFrActions(radar());
  return (
    <button type="button" onClick={() => actions.act(ID.oskar, "state", { state })}>
      set state
    </button>
  );
}

describe("Founder Radar — an unknown state is a 400 (decision f)", () => {
  it("the error is shown and nothing is recorded", async () => {
    const server = fakeServer();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ToastProvider>
          <StateProbe state="sleeping" />
        </ToastProvider>
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "set state" }));
    await waitFor(() => expect(bodies(server, "action")).toEqual([{ id: ID.oskar, action: "state", state: "sleeping" }]));
    expect(await screen.findByText(/^✕ Saving failed — state must be one of: detected, needs identity resolution, watchlisted/)).toBeInTheDocument();
    expect(screen.queryByText("Recorded: state")).toBeNull();
  });

  it("a known state is recorded", async () => {
    const server = fakeServer();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ToastProvider>
          <StateProbe state="dormant" />
        </ToastProvider>
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "set state" }));
    expect(await screen.findByText("Recorded: state")).toBeInTheDocument();
    expect(bodies(server, "action")).toEqual([{ id: ID.oskar, action: "state", state: "dormant" }]);
  });
});

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ALL_ITEMS } from "@/app/nav";
import { NOT_PORTED as CONVICTION } from "@/features/conviction/model/deferred";
import { ID, KELPWISE, radar } from "./test/fixtures";
import { IMPORT_NOTE, fakeServer, renderPage } from "./test/server";

const tab = (name: string) => screen.getByRole("tab", { name: new RegExp("^" + name.replace(/[+()]/g, "\\$&")) });
const leads = () => screen.getByTestId("fr-leads");
const list = () => screen.getByTestId("fr-list");
const companyCard = (name: string) => screen.getAllByTestId("fr-company-card").find((c) => within(c).queryByText(name, { selector: "header > span:first-child" }))!;
function personCard(scope: HTMLElement, name: string): HTMLElement {
  const c = within(scope)
    .queryAllByTestId("fr-person-card")
    .find((x) => x.querySelector("header > span")?.textContent === name);
  if (!c) throw new Error(`no person card for ${name}`);
  return c;
}
const companyNames = () => within(list()).queryAllByTestId("fr-company-card").map((c) => c.querySelector("header > span")?.textContent);
const search = () => screen.getByRole("searchbox", { name: "Search people" });

async function opened(path = "/founder-radar") {
  const r = renderPage(path);
  await screen.findByRole("heading", { level: 1, name: "Founder Radar" });
  return r;
}

/** A deferred control (the Scout 00 job) stays inert for a pointer AND a keyboard (a browser turns Enter / Space into a click). */
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

describe("Founder Radar — the page", () => {
  it("is a ported nav view at /founder-radar", () => {
    expect(ALL_ITEMS.find((i) => i.legacyView === "founders")).toMatchObject({ path: "/founder-radar", label: "Founder Radar", page: expect.anything() });
  });

  it("opens on Top Founder Leads with understandable lead cards, after ONE read", async () => {
    const server = fakeServer();
    await opened();
    expect(screen.getByText(/^Unusually strong builders detected/)).toHaveTextContent(
      "Unusually strong builders detected from permitted public sources — before their companies are obvious. Detected ≠ Watchlist ≠ Network: three states of one person record.",
    );
    expect(tab("Top Founder Leads")).toHaveAttribute("aria-selected", "true");
    expect(tab("Top Founder Leads")).toHaveTextContent("Top Founder Leads3");
    expect(tab("Near Matches")).toHaveTextContent("Near Matches1");
    expect(tab("Research Queue")).toHaveTextContent("Research Queue4");
    expect(screen.getByTestId("fr-counts").textContent).toBe(
      "0 deserve attention first (Gold + Strong) · 6 founder claims unresolved · 1 research & spinout talent · 2 insufficient · 1 watchlisted · 1 in Network",
    );
    const cards = within(leads()).getAllByTestId("fr-lead-card");
    expect(cards).toHaveLength(3);
    expect(screen.queryByTestId("fr-research")).toBeNull();
    expect(screen.queryByTestId("fr-diag")).toBeNull();
    const t = leads().textContent!;
    expect(t).not.toMatch(/rank \d|Research priority|proposal id|hiring_signal|source health/i);
    for (const k of ["Why this founder stands out", "Founder-specific evidence", "Company momentum", "Project A relevance", "LinkedIn", "Public contact", "Access", "Important unknowns", "Next action", "View evidence"])
      expect(t, k).toContain(k);
    expect(within(cards[0]).getByText("Machine-qualified candidate")).toBeInTheDocument();
    expect(within(cards[1]).getByText("Human-confirmed Gold")).toBeInTheDocument();
    expect(cards[0]).toHaveTextContent("Kelpwise GmbH · Co-Founder & CEO · Kiel");
    expect(cards[0]).toHaveTextContent("Access: cold — public e-mail hello@kelpwise.example — cold");
    expect(cards[1]).toHaveTextContent("Access: warm — introduced by Nils Farrow");
    expect(cards[1]).toHaveTextContent("Founder of Borealis Robotics — stated on the company's official site — official page ↗ · confirmed");
    // LinkedIn stays a manual, external search ("never scraped"); a public profile URL is linked as found
    expect(within(cards[0]).getByRole("link", { name: "Search on LinkedIn ↗" })).toHaveAttribute(
      "href",
      "https://www.linkedin.com/search/results/people/?keywords=Mira%20Talvik%20Kelpwise%20GmbH",
    );
    expect(within(cards[1]).getByRole("link", { name: /linkedin\.com\/in\/ilka-moravec-borealis/ })).toHaveAttribute("target", "_blank");
    expect(cards[1]).toHaveTextContent("(found on a public source — never scraped)");
    // an unresolved identity offers no Watchlist; a resolved one does
    expect(within(cards[0]).queryByRole("button", { name: "Add to Watchlist" })).toBeNull();
    expect(within(cards[1]).getByRole("button", { name: "Add to Watchlist" })).toBeInTheDocument();
    expect(server.calls.map((c) => `${c.method} ${c.path}`)).toEqual(["GET /api/founder-radar"]);
  });

  it("the views switch through ?view=: Near Matches, Diagnostics, and the Research Queue on the claim segment", async () => {
    fakeServer();
    const { router } = await opened();
    fireEvent.click(tab("Near Matches"));
    await screen.findByText("Founders with some sourced signal but not enough for a machine-qualified ranking yet.");
    expect(router.state.location.search).toBe("?view=near");
    expect(within(leads()).getAllByTestId("fr-lead-card")).toHaveLength(1);
    expect(within(leads()).getByText("near match")).toBeInTheDocument();
    fireEvent.click(tab("Diagnostics"));
    expect(await screen.findByTestId("fr-diag")).toBeInTheDocument();
    expect(document.getElementById("frHealth")).not.toBeNull();
    expect(document.getElementById("frCoverage")).not.toBeNull();
    fireEvent.click(tab("Research Queue"));
    await screen.findByTestId("fr-research");
    expect(router.state.location.search).toBe("?view=research");
    expect(tab("Founder claims — unverified")).toHaveAttribute("aria-selected", "true");
    expect(list()).toHaveTextContent(/company lead/i);
    fireEvent.click(tab("Top Founder Leads"));
    await screen.findByTestId("fr-leads");
    expect(router.state.location.search).toBe("");
  });

  it("honestly empty: no verified founders yet", async () => {
    const d = radar();
    d.leads = { top: [], near: [], total_candidates: 0 };
    fakeServer({ radar: d });
    await opened();
    expect(within(leads()).getByText(/^No verified founders yet/).textContent).toBe(
      "No verified founders yet — honestly empty. A person appears here only when an official company/team/press page (or your own evidence-backed confirmation) explicitly names them as founder or co-founder of a named company. Run Research company queue in the Research Queue.",
    );
    expect(within(leads()).queryAllByTestId("fr-lead-card")).toHaveLength(0);
  });

  it("a failed read is shown with Retry", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ok: false, error: "Founder Radar data is not imported yet" }), { status: 409 })));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Founder Radar data is not imported yet");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});

describe("Founder Radar — the Research Queue (gates and company grouping)", () => {
  it("the claim segment groups claimed founders by company with the reconciliation counts", async () => {
    fakeServer();
    await opened("/founder-radar?view=research");
    expect(tab("Founder claims — unverified")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("fr-counts").textContent).toBe("Company leads 4 · claimed founders 6 · separately: 6 people currently in Founder claim bucket");
    expect(companyNames()).toEqual(["Kelpwise GmbH", "Borealis Robotics", "Quillstone AI", "Grainline Labs"]);
    for (const c of screen.getAllByTestId("fr-company-card")) expect(c).toHaveTextContent(/claimed founder/i);
    const kelp = companyCard("Kelpwise GmbH");
    expect(kelp).toHaveTextContent("2 claimed founder(s)");
    expect(kelp).toHaveTextContent("Founders (claimed): Mira Talvik (Co-Founder & CEO · needs identity resolution) · Jonas Brekke (Co-Founder & CTO · needs identity resolution)");
    expect(kelp).toHaveTextContent("Unverified claims (never decision-bearing): stage: UNVERIFIED PIPELINE CLAIM: pre_seed");
    expect(kelp).toHaveTextContent("Priority: Medium · Why: recent dated pipeline/public signal; early-stage claim · 8 proposal(s) to review");
    expect(within(kelp).getByRole("button", { name: "Review proposals (8)" })).toBeInTheDocument();
    expect(within(kelp).getByRole("link", { name: "Web search ↗" })).toHaveAttribute("href", "https://duckduckgo.com/?q=Kelpwise%20GmbH%20founders");
    expect(within(kelp).getByRole("link", { name: "LinkedIn search ↗ (not evidence)" })).toHaveAttribute(
      "href",
      "https://www.linkedin.com/search/results/companies/?keywords=Kelpwise%20GmbH",
    );
    expect(within(companyCard("Borealis Robotics")).getByText("candidate domain")).toBeInTheDocument();
    expect(companyCard("Borealis Robotics")).toHaveTextContent("Recent activity (sourced, dated): 2026-11-02 — dated item on the news page: field trial with a forestry co");
    const grain = companyCard("Grainline Labs");
    expect(within(grain).getByText("domain UNKNOWN")).toBeInTheDocument();
    expect(grain).toHaveTextContent("grainhacker (role UNKNOWN · needs identity resolution · login only)");
    expect(grain.textContent).not.toMatch(/order \d+/);
    expect(list()).toHaveTextContent("UNKNOWN");
    expect(screen.getByTestId("fr-metrics")).toHaveTextContent("6 founder claims unresolved");
    expect(screen.getByTestId("fr-metrics")).toHaveTextContent("— watchlist to network conversion");
    expect(screen.getByTestId("fr-metrics")).toHaveTextContent("recorded 2026-11-10 · counts of recorded events, never inferred");
  });

  it("Gold is honestly empty; Insufficient, Research talent, Watchlisted, Network and Dismissed show their people", async () => {
    fakeServer();
    await opened("/founder-radar?view=research");
    fireEvent.click(tab("Gold now + Strong investigation"));
    expect(await screen.findByText(/^Nobody qualifies as Gold or Strong yet/)).toBeInTheDocument();
    expect(within(list()).queryAllByTestId("fr-person-card")).toHaveLength(0);
    expect(screen.getByTestId("fr-counts")).toHaveTextContent("deserve attention first (Gold + Strong)");

    fireEvent.click(tab("Insufficient / out of scope"));
    const oskar = personCard(list(), "Oskar Lindqvist");
    expect(oskar).toHaveTextContent(/Not founder-scorable/);
    expect(oskar).toHaveTextContent("Who: researcher · Zürich CH");
    expect(oskar).toHaveTextContent("Proof: 4 attributed item(s) from GitHub — builders in Zürich · Unknown: no attributed evidence");
    expect(oskar).toHaveTextContent("Next: Collect attributed evidence or dismiss");
    expect(within(oskar).getByRole("button", { name: "Add to Network" })).toBeInTheDocument();
    const petra = personCard(list(), "Petra Lunde");
    expect(petra).toHaveTextContent("Imported: LinkedIn Connections export 2026-10 · connected 17 Sep 2026 · imported 2026-10-02");
    expect(petra).toHaveTextContent("IDENTITY UNRESOLVED — NOT YET VERIFIABLE");
    expect(petra).toHaveTextContent("Add to Network — Resolve identity before promotion");
    expect(within(petra).queryByRole("button", { name: "Add to Network" })).toBeNull();

    fireEvent.click(tab("Research & spinout talent"));
    const rhea = personCard(list(), "Rhea Castell");
    expect(within(rhea).getByRole("button", { name: "Investigate founder status" })).toBeInTheDocument();
    expect(within(rhea).queryByRole("button", { name: "Add to Watchlist" })).toBeNull();
    expect(rhea).toHaveTextContent("Technical theme overlap: MEDIUM");

    fireEvent.click(tab("Watchlisted"));
    expect(personCard(list(), "Wren Adebayo")).toBeTruthy();
    fireEvent.click(tab("Network"));
    expect(within(list()).getAllByTestId("fr-person-card").map((c) => c.querySelector("header > span")?.textContent)).toEqual(["Nils Farrow"]); // not Hana Sato
    fireEvent.click(tab("Dismissed"));
    expect(personCard(list(), "Dana Vale")).toBeTruthy();
  });

  it("?seg= opens a segment; the claim segment's person cards show the Scout Packet link and a proposed identity", async () => {
    fakeServer();
    await opened("/founder-radar?view=research&seg=claim");
    fireEvent.change(search(), { target: { value: "okafor" } });
    const sana = await waitFor(() => personCard(list(), "Sana Okafor"));
    expect(within(sana).getByRole("link", { name: "Review identity evidence (Scout Packet)" })).toHaveAttribute(
      "href",
      "/scout-intake?item=si-quill-7&review=identity&from=founders",
    );
    fireEvent.change(search(), { target: { value: "grainhacker" } });
    const grain = await waitFor(() => personCard(list(), "grainhacker"));
    expect(grain).toHaveTextContent("LOGIN ONLY — NAME NOT ATTRIBUTED");
    expect(within(grain).getByRole("button", { name: "Confirm proposed identity: Gideon Rask" })).toBeInTheDocument();
  });

  it("the filters narrow the people (founder status, identity, region, evidence checks)", async () => {
    fakeServer();
    await opened("/founder-radar?view=research&seg=insuf");
    const names = () => within(list()).queryAllByTestId("fr-person-card").map((c) => c.querySelector("header > span")?.textContent);
    expect(names()).toEqual(["Oskar Lindqvist", "Petra Lunde"]);
    fireEvent.change(screen.getByRole("combobox", { name: "identity" }), { target: { value: "resolved" } });
    expect(names()).toEqual(["Oskar Lindqvist"]);
    fireEvent.change(screen.getByRole("combobox", { name: "region" }), { target: { value: "Nordics" } });
    expect(names()).toEqual([]);
    expect(list()).toHaveTextContent("Nothing here.");
    expect(within(screen.getByRole("combobox", { name: "region" })).getByRole("option", { name: "DACH · 6 people · 1/2 cities ever scanned" })).toBeInTheDocument();
    expect(within(screen.getByRole("combobox", { name: "signal age" })).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "signal age: any",
      "≤ 7 days",
      "≤ 30 days",
      "≤ 90 days",
    ]);
  });
});

describe("Founder Radar — search", () => {
  it("an identity-unresolved founder is found by name everywhere; company search works; nothing is written", async () => {
    const server = fakeServer();
    await opened();
    fireEvent.change(search(), { target: { value: "Sana Okafor" } });
    const block = await screen.findByTestId("fr-search-block");
    expect(block).toHaveTextContent("Search results for “sana okafor” across every Founder Radar bucket — 1 people · 1 company leads (identity states unchanged)");
    expect(within(block).getByTestId("fr-company-card")).toHaveTextContent("Quillstone AI");
    expect(within(block).getByTestId("fr-company-card")).toHaveTextContent(/company lead/i);
    expect(personCard(block, "Sana Okafor")).toHaveTextContent(/needs identity resolution/i);
    expect(tab("Top Founder Leads")).toHaveAttribute("aria-selected", "true");

    fireEvent.click(tab("Research Queue"));
    await screen.findByTestId("fr-research");
    expect(companyNames()).toEqual(["Quillstone AI"]);
    expect(list()).toHaveTextContent("People matching “sana okafor” across every Founder Radar bucket (1)");
    expect(personCard(list(), "Sana Okafor")).toBeTruthy();
    expect(screen.getByTestId("fr-counts").textContent).toBe("Company leads 4 · claimed founders 6 · separately: 6 people currently in Founder claim bucket");

    fireEvent.click(tab("Gold now + Strong investigation"));
    expect(list()).toHaveTextContent("Sana Okafor"); // a search crosses every bucket

    fireEvent.click(tab("Founder claims — unverified"));
    fireEvent.change(search(), { target: { value: "Gideon" } }); // a claimed alias
    await waitFor(() => expect(companyNames()).toEqual(["Grainline Labs"]));
    fireEvent.change(search(), { target: { value: "" } });
    await waitFor(() => expect(companyNames()).toHaveLength(4));
    fireEvent.change(search(), { target: { value: "zzzz-no-such-name" } });
    await waitFor(() => expect(list()).toHaveTextContent("No company lead matches “zzzz-no-such-name” (company name, claimed / scout-reported / linked founder names)."));
    expect(list()).toHaveTextContent("No person matches.");
    fireEvent.change(search(), { target: { value: "" } });
    await waitFor(() => expect(companyNames()).toEqual(["Kelpwise GmbH", "Borealis Robotics", "Quillstone AI", "Grainline Labs"]));
    fireEvent.click(tab("Gold now + Strong investigation"));
    expect(list()).not.toHaveTextContent("Sana Okafor");
    expect(server.calls.filter((c) => c.method !== "GET")).toEqual([]);
  });

  it("no match on Top Founder Leads says so", async () => {
    fakeServer();
    await opened();
    fireEvent.change(search(), { target: { value: "zzzz" } });
    expect(await screen.findByText("No person or company lead matches.")).toBeInTheDocument();
  });
});

describe("Founder Radar — Diagnostics", () => {
  it("source coverage and founder source health", async () => {
    fakeServer();
    await opened("/founder-radar?view=diag");
    const cov = document.getElementById("frCoverage")!;
    const health = document.getElementById("frHealth")!;
    expect(cov).toHaveTextContent("live discovery · enrichment · manual/authorized · configuration required · failed · not attempted");
    expect(cov).toHaveTextContent("live discovery (2)");
    expect(cov).toHaveTextContent("enrichment (0)—");
    expect(cov).toHaveTextContent("LinkedIn — MANUAL / AUTHORIZED — never scanned automatically · config_required · No scraping, automation, cookies or credentials.");
    expect(health).toHaveTextContent("separate from company and event sources · no LinkedIn scraping, no automation, no cookies");
    const h = screen.getByTestId("fr-health");
    expect(h).toHaveTextContent("8 attempted2 successful3 failed3 configuration required12 raw people/signals4 identities resolved8 unresolved1 duplicates merged");
    expect(h).toHaveTextContent("scan 2026-11-10 21:30 · 2.4s");
    expect(h).toHaveTextContent("Europe-wide coverage — rotating batches of 6 cities per scan (registry 51 cities)");
    expect(within(h).getByText("REQUIRES CONFIGURATION")).toBeInTheDocument();
    expect(within(h).getByText("FAILED")).toBeInTheDocument();
    expect(within(h).getByText("OK")).toBeInTheDocument();
    expect(h).toHaveTextContent("Kiel ✓, Zürich ✕, Vienna ·");
    expect(h).toHaveTextContent("✓ retrieved this scan · ✕ failed this scan · unmarked = not attempted this scan (waits for its batch; never reported as covered)");
  });

  it("no scan yet shows the server's note", async () => {
    const d = radar();
    d.health = { scan_time: "", totals: {}, sources: [], note: "No founder scan yet — press Scan founder signals." };
    fakeServer({ radar: d });
    await opened("/founder-radar?view=diag");
    expect(document.getElementById("frHealth")).toHaveTextContent("No founder scan yet — press Scan founder signals.");
    expect(screen.queryByTestId("fr-health")).toBeNull();
  });
});

describe("Founder Radar — authorized import", () => {
  it("the CSV file is read in the browser and posted as {csv, label, include_email}", async () => {
    const server = fakeServer();
    await opened();
    fireEvent.click(screen.getByRole("button", { name: "Authorized import (CSV)" }));
    const dlg = screen.getByRole("dialog", { name: "Authorized import (CSV / TSV)" });
    expect(dlg).toHaveTextContent("official LinkedIn Connections export");
    expect(dlg).toHaveTextContent("Nothing is scanned from LinkedIn — no cookies, no automation.");
    expect(within(dlg).getByRole("button", { name: "Import" })).toBeDisabled();
    fireEvent.change(within(dlg).getByPlaceholderText("label, e.g. 'LinkedIn Connections export 2026-09'"), { target: { value: "LinkedIn Connections export 2026-10" } });
    const csv = "First Name,Last Name,URL,Email Address,Company,Position,Connected On\nPetra,Lunde,https://www.linkedin.com/in/petra-lunde,petra@example.org,Fernhollow,CTO,17 Sep 2026\n";
    fireEvent.change(within(dlg).getByTestId("fr-import-file"), { target: { files: [new File([csv], "sample_Connections.csv", { type: "text/csv" })] } });
    await waitFor(() => expect(dlg).toHaveTextContent("sample_Connections.csv loaded (0 KB) — review, then Import"));
    expect(within(dlg).getByPlaceholderText("paste CSV / TSV here")).toHaveValue(csv);
    fireEvent.click(within(dlg).getByRole("button", { name: "Import" }));
    await waitFor(() => expect(server.posts("import")).toHaveLength(1));
    const b = server.posts("import")[0].body!;
    expect(Object.keys(b).sort()).toEqual(["csv", "include_email", "label"]);
    expect(b).toEqual({ csv, label: "LinkedIn Connections export 2026-10", include_email: false });
    expect(await screen.findByText(`LinkedIn Connections export: 3 new · 0 merged — ${IMPORT_NOTE}`)).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Authorized import (CSV / TSV)" })).toBeNull();
  });

  it("pasted text and the e-mail opt-in", async () => {
    const server = fakeServer();
    await opened();
    fireEvent.click(screen.getByRole("button", { name: "Authorized import (CSV)" }));
    const dlg = screen.getByRole("dialog", { name: "Authorized import (CSV / TSV)" });
    fireEvent.change(within(dlg).getByPlaceholderText("paste CSV / TSV here"), { target: { value: "name,company\nTove Brandt,Grainline Labs" } });
    fireEvent.click(within(dlg).getByRole("checkbox", { name: "also keep e-mail addresses (off by default)" }));
    fireEvent.click(within(dlg).getByRole("button", { name: "Import" }));
    await waitFor(() => expect(server.posts("import")).toHaveLength(1));
    expect(server.posts("import")[0].body).toEqual({ csv: "name,company\nTove Brandt,Grainline Labs", label: "", include_email: true });
  });
});

describe("Founder Radar — the scan and company research (026b)", () => {
  const BUSY = "Another founder scan or research run is in progress — try again when it finishes.";
  const QUEUE = "Research company queue (all leads with an official domain, resumable)";
  const reads = (server: ReturnType<typeof fakeServer>) => server.calls.filter((c) => c.method === "GET" && c.path === "/api/founder-radar").length;

  it("every scan and research control is enabled", async () => {
    fakeServer();
    await opened("/founder-radar?view=research");
    const controls = [
      screen.getByRole("button", { name: "Scan founder signals" }),
      screen.getByRole("button", { name: "Research next 5 leads" }),
      screen.getByRole("button", { name: QUEUE }),
      ...screen.getAllByRole("button", { name: "Research company" }),
    ];
    expect(controls).toHaveLength(7); // the scan, the two queue links and the four company cards
    for (const el of controls) {
      expect(el).toBeEnabled();
      expect(el).not.toHaveAttribute("aria-disabled");
      expect(el).not.toHaveAttribute("title");
    }
    expect(screen.queryByText(/arrive with the founder scan port/)).toBeNull();
    expect(screen.queryByTestId("fr-rq-state")).toBeNull(); // only once the queue runs
  });

  it("Scan founder signals: POST founder-radar/scan {} answers the health report synchronously", async () => {
    const server = fakeServer();
    await opened();
    const before = reads(server);
    fireEvent.click(screen.getByRole("button", { name: "Scan founder signals" }));
    expect(await screen.findByText("Scan done: 2 ok · 3 failed · 5 new · 1 merged")).toBeInTheDocument();
    expect(server.posts("scan").map((c) => c.body)).toEqual([{}]);
    expect(server.calls.filter((c) => c.method === "POST").map((c) => c.path)).toEqual(["/api/founder-radar/scan"]);
    await waitFor(() => expect(reads(server)).toBe(before + 1)); // the radar is re-read once, nothing polls
    expect(screen.getByRole("button", { name: "Scan founder signals" })).toBeEnabled();
  });

  it("Scan founder signals: a started job is polled every 2 s until health.scan_time changes", async () => {
    const after = radar();
    after.health = { ...after.health, scan_time: "2026-11-12 10:00", totals: { ...after.health!.totals, ok: 5 } };
    // the re-read right after the answer still has the old scan time; the first poll sees the new one
    const server = fakeServer({ scan: () => ({ status: 200, body: { started: true } }), radar_after_scan: after, after_scan_reads: 2 });
    await opened();
    const before = reads(server);
    fireEvent.click(screen.getByRole("button", { name: "Scan founder signals" }));
    const busy = await screen.findByRole("button", { name: "Scanning…" });
    expect(busy).toBeDisabled();
    expect(await screen.findByText("Scan done: 5 ok · 3 failed · 5 new · 1 merged", undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(reads(server)).toBe(before + 2);
    expect(server.posts("scan").map((c) => c.body)).toEqual([{}]);
    expect(screen.getByRole("button", { name: "Scan founder signals" })).toBeEnabled();
    await new Promise((r) => setTimeout(r, 2300));
    expect(reads(server)).toBe(before + 2); // the poll stopped
  }, 12_000);

  it("Scan founder signals: a 409 (another run in progress) and a 503 (the deadline) are shown as errors", async () => {
    let status = 409;
    const server = fakeServer({ scan: () => ({ status, body: { ok: false, error: status === 409 ? BUSY : "the scan deadline passed before the write; nothing was written" } }) });
    await opened();
    fireEvent.click(screen.getByRole("button", { name: "Scan founder signals" }));
    expect(await screen.findByText(`✕ Scanning founders failed — ${BUSY}`)).toBeInTheDocument();
    expect(await screen.findByText("Scan failed")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Scan founder signals" })).toBeEnabled());
    status = 503;
    fireEvent.click(screen.getByRole("button", { name: "Scan founder signals" }));
    expect(await screen.findByText(/^✕ Scanning founders failed — .*\(the scan deadline passed before the write; nothing was written\)$/)).toBeInTheDocument();
    expect(server.posts("scan")).toHaveLength(2);
  });

  it("Research company: POST {key}, the toast, then the review opens", async () => {
    const server = fakeServer();
    await opened("/founder-radar?view=research");
    fireEvent.click(within(companyCard("Quillstone AI")).getByRole("button", { name: "Research company" }));
    expect(await screen.findByText("Researching official domain (bounded: homepage + ≤8 pages)…")).toBeInTheDocument();
    expect(await screen.findByText("5 page(s) retrieved · 9 proposal(s) — review before anything counts")).toBeInTheDocument();
    expect(server.posts("research").map((c) => c.body)).toEqual([{ key: "dom:quillstone.example" }]);
    const drawer = await screen.findByRole("dialog", { name: "Review — Quillstone AI" });
    expect(await within(drawer).findByText("No proposals yet — press Research company.")).toBeInTheDocument();
  });

  it("Research company: a failed run is an error toast and the review stays closed", async () => {
    const server = fakeServer({
      research: (b) => ({ status: 200, body: { ok: true, researched: [{ key: b.key, name: "Quillstone AI", ok: false, error: "robots.txt disallows the site" }] } }),
    });
    await opened("/founder-radar?view=research");
    fireEvent.click(within(companyCard("Quillstone AI")).getByRole("button", { name: "Research company" }));
    expect(await screen.findByText("robots.txt disallows the site")).toBeInTheDocument();
    expect(server.posts("research")).toHaveLength(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("Research company: a 409 is the failure toast with the reason", async () => {
    fakeServer({ research: () => ({ status: 409, body: { ok: false, error: BUSY } }) });
    await opened("/founder-radar?view=research");
    fireEvent.click(within(companyCard("Quillstone AI")).getByRole("button", { name: "Research company" }));
    expect(await screen.findByText(`✕ Starting founder research failed — ${BUSY}`)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("Research next 5 leads: POST {} and one part per company", async () => {
    let answer: unknown[] = [
      { key: KELPWISE, name: "Kelpwise GmbH", ok: true, pages: 5, proposals: 9 },
      { key: "dom:quillstone.example", name: "Quillstone AI", ok: false, error: "HTTP 404" },
    ];
    const server = fakeServer({ research: () => ({ status: 200, body: { ok: true, researched: answer } }) });
    await opened("/founder-radar?view=research");
    fireEvent.click(screen.getByRole("button", { name: "Research next 5 leads" }));
    expect(await screen.findByText("Researching next 5 leads…")).toBeInTheDocument();
    expect(await screen.findByText("Kelpwise GmbH: 9 proposals · Quillstone AI: HTTP 404")).toBeInTheDocument();
    answer = [];
    await waitFor(() => expect(screen.getByRole("button", { name: "Research next 5 leads" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Research next 5 leads" }));
    expect(await screen.findByText("nothing left to research")).toBeInTheDocument();
    expect(server.posts("research").map((c) => c.body)).toEqual([{}, {}]);
  });

  it("the review drawer's Refresh research: POST {key, refresh: true}, the toast, the proposals re-read", async () => {
    const server = fakeServer();
    await opened(`/founder-radar?view=research&review=${encodeURIComponent(KELPWISE)}`);
    const drawer = await screen.findByRole("dialog", { name: "Review — Kelpwise GmbH" });
    const refresh = await within(drawer).findByRole("button", { name: "Refresh research" });
    expect(refresh).toBeEnabled();
    expect(server.posts("proposals")).toHaveLength(1);
    fireEvent.click(refresh);
    expect(await screen.findByText("Refreshing research (bounded re-fetch; decisions kept)…")).toBeInTheDocument();
    expect(await screen.findByText("5 page(s) · 0 new proposal(s)")).toBeInTheDocument();
    expect(server.posts("research").map((c) => c.body)).toEqual([{ key: KELPWISE, refresh: true }]);
    await waitFor(() => expect(server.posts("proposals")).toHaveLength(2));
  });

  it("the company research queue: batches of 3 until nothing remains, fr-rq-state once it runs", async () => {
    const server = fakeServer();
    await opened("/founder-radar?view=research");
    expect(screen.queryByTestId("fr-rq-state")).toBeNull();
    const before = reads(server);
    fireEvent.click(screen.getByRole("button", { name: QUEUE }));
    expect(await screen.findByText("Company research queue: 2 done")).toBeInTheDocument();
    expect(screen.getByTestId("fr-rq-state").textContent).toBe(
      "Company research queue: 2 done · 0 remaining · 1 failed · skipped (no official domain): Grainline Labs · completefailures: dom:quillstone.example: HTTP 404",
    );
    expect(server.posts("research_queue").map((c) => c.body)).toEqual([{ batch: 3 }, { batch: 3 }]);
    await waitFor(() => expect(reads(server)).toBe(before + 1));
    expect(screen.getByRole("button", { name: QUEUE })).toBeEnabled();
  });

  it("the company research queue stops after 40 batches and says it can resume", async () => {
    const server = fakeServer({
      research_queue: () => ({ status: 200, body: { ok: true, processed: [], done: 7, remaining: 4, failed: {}, skipped_no_domain: [], in_progress: true, resume: true } }),
    });
    await opened("/founder-radar?view=research");
    fireEvent.click(screen.getByRole("button", { name: QUEUE }));
    expect(await screen.findByText("Company research queue: 7 done")).toBeInTheDocument();
    expect(server.posts("research_queue")).toHaveLength(40);
    expect(screen.getByTestId("fr-rq-state").textContent).toBe("Company research queue: 7 done · 4 remaining · 0 failed · resumable — press again to continue");
  });

  it("the company research queue: a 409 is shown and the queue stops", async () => {
    const server = fakeServer({ research_queue: () => ({ status: 409, body: { ok: false, error: BUSY } }) });
    await opened("/founder-radar?view=research");
    fireEvent.click(screen.getByRole("button", { name: QUEUE }));
    expect(await screen.findByText(BUSY)).toBeInTheDocument();
    expect(server.posts("research_queue")).toHaveLength(1);
    await waitFor(() => expect(screen.queryByTestId("fr-rq-state")).toBeNull());
  });

  it("Ask Scout 00 for identity evidence is disabled with the bridge reason (the Scout Bridge is never ported)", async () => {
    const server = fakeServer();
    await opened(`/founder-radar?person=${ID.mira}`);
    const drawer = await screen.findByRole("dialog", { name: "Mira Talvik" });
    const ask = within(drawer).getByRole("button", { name: "Ask Scout 00 for identity evidence" });
    expect(ask).toHaveAttribute("aria-disabled", "true");
    expect(ask).toHaveAttribute("title", CONVICTION.bridge);
    expect(ask).toHaveAccessibleDescription(CONVICTION.bridge);
    pressEveryWay(ask);
    await new Promise((r) => setTimeout(r, 20));
    expect(server.calls.filter((c) => c.method === "POST")).toEqual([]);
  });
});

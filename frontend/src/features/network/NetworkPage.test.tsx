import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PERSON_FIELDS } from "./model/types";
import { TODAY } from "./test/fixtures";
import { fakeServer, renderNetwork, setWide } from "./test/server";

const rowNames = () => screen.queryAllByTestId("person-row").map((r) => r.querySelector("b")?.textContent);
const profileName = () => within(screen.getByTestId("person-profile")).getByRole("heading", { level: 2 }).textContent;
const search = (router: { state: { location: { search: string } } }) => new URLSearchParams(router.state.location.search);

async function loaded() {
  await waitFor(() => expect(screen.getAllByTestId("person-row").length).toBeGreaterThan(0));
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

function chip(name: RegExp) {
  return screen.getByRole("button", { name });
}

function openMore() {
  fireEvent.click(screen.getByTestId("more-filters"));
  return screen.getByTestId("more-filters-panel");
}

const field = (dlg: HTMLElement, name: string) => dlg.querySelector(`[name="${name}"]`) as HTMLInputElement | HTMLSelectElement;

beforeEach(() => {
  localStorage.clear();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(`${TODAY}T12:00:00Z`));
  setWide(true);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("Network — the list", () => {
  it("shows the header, the counts and the rows in server order; wide opens the first person", async () => {
    fakeServer();
    renderNetwork();
    await loaded();
    expect(screen.getByRole("heading", { level: 1, name: "Network" })).toBeInTheDocument();
    expect(screen.getByText("Relationships — who you know, how warm it is, and what to do next.")).toBeInTheDocument();
    expect(screen.getByTestId("people-counts")).toHaveTextContent("7 relationships · 2 due · 3 from chains");
    expect(rowNames()).toEqual(["Mara Klein", "Felix Ortmann", "Jonas Albrecht", "Tariq Haddad", "Lena Vogt", "Omar Hedeya", "Sofia Brandt"]);
    expect(profileName()).toBe("Mara Klein");
    expect(screen.getAllByTestId("person-row")[0]).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("list", { name: "People" })).toHaveAttribute("data-has-selection", "");
    expect(screen.getByTestId("person-profile")).toHaveTextContent("All facts user-provided · unknown fields left empty · auto-actions labelled SUGGESTED");
    // a row: badges, role · company · city, strength, last contact, linked companies and why
    const jonas = screen.getAllByTestId("person-row")[2];
    expect(jonas).toHaveTextContent("WATCH");
    expect(jonas).toHaveTextContent("CTO · Aereus · Berlin");
    expect(jonas).toHaveTextContent("Strong");
    expect(jonas).toHaveTextContent("last 2026-08-28");
    expect(jonas).toHaveTextContent("Aereus — Built the flight stack at a drone startup");
    expect(screen.getAllByTestId("person-row")[0]).toHaveTextContent("DUE");
    expect(screen.getAllByTestId("person-row")[0]).toHaveTextContent("no contact logged");
    expect(screen.getAllByTestId("person-row")[3]).toHaveTextContent("introduction requested");
  });

  it("the attention segments carry their counts and narrow the list (Due in red)", async () => {
    fakeServer();
    renderNetwork();
    await loaded();
    const attention = within(screen.getByTestId("people-filters")).getByRole("group", { name: "Attention" });
    expect(within(attention).getAllByRole("button").map((b) => b.textContent)).toEqual(["All 7", "Founder potential 4", "Due 2", "Watch 2"]);
    fireEvent.click(chip(/^Due/));
    expect(chip(/^Due/)).toHaveAttribute("aria-pressed", "true");
    expect(rowNames()).toEqual(["Mara Klein", "Felix Ortmann"]);
    fireEvent.click(chip(/^Founder potential/));
    expect(rowNames()).toEqual(["Mara Klein", "Felix Ortmann", "Tariq Haddad", "Lena Vogt"]);
    fireEvent.click(chip(/^Watch/));
    expect(rowNames()).toEqual(["Jonas Albrecht", "Sofia Brandt"]);
    fireEvent.click(chip(/^All/));
    expect(rowNames()).toHaveLength(7);
  });

  it("More filters holds the other segments and the top cities; the active one is named on the closed button", async () => {
    fakeServer();
    renderNetwork();
    await loaded();
    const more = openMore();
    expect(within(more).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Chains 5",
      "Intro requests 1",
      "New this month 1",
      "Dormant high-value 2",
      "With opportunities 1",
      "Via Omar 1",
      "Via Boardy 1",
      "Met at events 1",
      "Berlin 3",
      "Karlsruhe 2",
      "Munich 1",
    ]);
    fireEvent.click(within(more).getByRole("button", { name: /^Dormant high-value/ }));
    expect(rowNames()).toEqual(["Jonas Albrecht", "Tariq Haddad"]);
    expect(screen.getByTestId("more-filters")).toHaveTextContent("More filters · Dormant high-value");
    fireEvent.click(within(more).getByRole("button", { name: /^Berlin/ }));
    expect(rowNames()).toEqual(["Jonas Albrecht", "Omar Hedeya", "Sofia Brandt"]);
    expect(screen.getByTestId("more-filters")).toHaveTextContent("More filters · Berlin");
    fireEvent.click(within(more).getByRole("button", { name: /^New this month/ }));
    expect(rowNames()).toEqual(["Tariq Haddad"]);
  });

  it("search matches any field (debounced); a click selects with history replace and links the company to Conviction", async () => {
    const server = fakeServer();
    const { router } = renderNetwork();
    await loaded();
    fireEvent.change(screen.getByLabelText("Search people"), { target: { value: "aereus" } });
    await waitFor(() => expect(rowNames()).toEqual(["Jonas Albrecht"]));
    fireEvent.click(screen.getByTestId("person-row"));
    await waitFor(() => expect(profileName()).toBe("Jonas Albrecht"));
    expect(search(router).get("person")).toBe("p-jonas-albrecht");
    expect(router.state.historyAction).toBe("REPLACE");
    const link = await within(screen.getByTestId("person-profile")).findByRole("link", { name: /Aereus/ });
    expect(link).toHaveAttribute("href", "/conviction?company=aereus");
    expect(link).toHaveTextContent("Aereus 49");
    fireEvent.change(screen.getByLabelText("Search people"), { target: { value: "zzz-nobody" } });
    await waitFor(() => expect(screen.getByText("No matches.")).toBeInTheDocument());
    expect(server.posts()).toEqual([]);
  });
});

describe("Network — profile and rail", () => {
  it("a chain: the path trace, the introducer, recommendations and the rail's warm path", async () => {
    fakeServer();
    renderNetwork("/network?person=p-mara-klein");
    await loaded();
    const prof = screen.getByTestId("person-profile");
    expect(within(prof).getByRole("img", { name: "Introduction path: Smooth Operator → Lena Vogt → Mara Klein" })).toBeInTheDocument();
    expect(prof).toHaveTextContent("introduced by Lena Vogt → Mara");
    expect(prof).toHaveTextContent('ask: "who are the three most talented people you know?"');
    expect(prof).toHaveTextContent("FOUNDER POT. MAYBE");
    expect(prof).toHaveTextContent("DUE reach out with a warm reference to Lena Vogt SUGGESTED");
    const rail = screen.getByTestId("person-rail");
    expect(rail).toHaveTextContent("Met once");
    expect(rail).toHaveTextContent("via Lena Vogt");
    expect(rail).toHaveTextContent("never logged");
    // the follow-up editor starts from the action without the SUGGESTED prefix
    expect(within(rail).getByLabelText("Next action")).toHaveValue("reach out with a warm reference to Lena Vogt");
  });

  it("an introducer: recommended names, linked companies without a Conviction entry, notes and the timeline", async () => {
    fakeServer();
    renderNetwork("/network?person=p-lena-vogt");
    await loaded();
    const prof = screen.getByTestId("person-profile");
    expect(profileName()).toBe("Lena Vogt");
    expect(within(prof).queryByTestId("intro-path")).toBeNull();
    expect(prof).toHaveTextContent("recommended Mara Klein, Felix Ortmann");
    expect(prof).toHaveTextContent("↳ Mara Klein");
    expect(prof).toHaveTextContent("FOUNDER POT. HIGH");
    expect(prof).toHaveTextContent("Leggo Robotics");
    expect(within(prof).queryByRole("link")).toBeNull();
    expect(prof).toHaveTextContent("Met at ICRA.");
    expect(prof).toHaveTextContent("2026-10-01Last interaction — 41d ago");
    expect(prof).toHaveTextContent("Ask about the spin-out · 2026-11-20");
    const rail = screen.getByTestId("person-rail");
    expect(rail).toHaveTextContent("Warm");
    expect(rail).toHaveTextContent("direct");
    expect(rail).toHaveTextContent("2026-10-01 (41d ago)");
    expect(within(rail).getByRole("link", { name: "LinkedIn ↗" })).toHaveAttribute("href", "https://www.linkedin.com/in/lena-vogt");
    expect(rail.querySelector("i")).toHaveStyle({ width: "60%" });
  });

  it("without an introducer a person met once is cold; nothing on record shows the empty states", async () => {
    fakeServer({ people: [{ id: "p-new", name: "Nadia Cold", relationship_strength: "met_once" }] });
    renderNetwork("/network?person=p-new");
    await loaded();
    const prof = screen.getByTestId("person-profile");
    expect(prof).toHaveTextContent("No chain logged yet.");
    expect(prof).toHaveTextContent("Why interesting — not captured yet.");
    expect(prof).toHaveTextContent("None linked — add in Edit / log (comma-separated).");
    expect(prof).toHaveTextContent("No notes yet.");
    expect(prof).toHaveTextContent("No interaction logged yet.");
    expect(prof).toHaveTextContent("No next action — set one in the rail.");
    expect(within(prof).getByLabelText("Ask Nadia: person 1")).toBeInTheDocument();
    const rail = screen.getByTestId("person-rail");
    expect(rail).toHaveTextContent("cold — find an intro");
    expect(rail).toHaveTextContent("none set");
    expect(rail.querySelector("i")).toHaveStyle({ width: "25%" });
    expect(screen.getByTestId("people-counts")).toHaveTextContent("1 relationships · 0 due · 0 from chains");
  });

  it("Save follow-up posts exactly {id, next_action, next_action_date}", async () => {
    const server = fakeServer();
    renderNetwork("/network?person=p-lena-vogt");
    await loaded();
    const rail = screen.getByTestId("person-rail");
    fireEvent.change(within(rail).getByLabelText("Next action"), { target: { value: "  Coffee at KIT " } });
    fireEvent.change(within(rail).getByLabelText("Next action date"), { target: { value: "2026-10-03" } });
    fireEvent.click(within(rail).getByRole("button", { name: "Save follow-up" }));
    await screen.findByText("Follow-up saved");
    expect(server.posts("person_save").map((c) => c.body)).toEqual([{ id: "p-lena-vogt", next_action: "Coffee at KIT", next_action_date: "2026-10-03" }]);
  });

  it("Log contact today appends 'YYYY-MM-DD — note' to the old notes (the client's UTC date)", async () => {
    const server = fakeServer();
    renderNetwork("/network?person=p-lena-vogt");
    await loaded();
    const rail = screen.getByTestId("person-rail");
    fireEvent.change(within(rail).getByLabelText("Interaction note"), { target: { value: " talked spin-out " } });
    fireEvent.click(within(rail).getByRole("button", { name: "Log contact today" }));
    await screen.findByText("Contact logged");
    expect(server.posts("person_save")[0].body).toEqual({ id: "p-lena-vogt", last_interaction: TODAY, notes: `Met at ICRA.\n${TODAY} — talked spin-out` });
    await waitFor(() => expect(within(screen.getByTestId("person-rail")).getByLabelText("Interaction note")).toHaveValue(""));
  });

  it("Log contact without a note only sets the date; a person without notes gets the note alone", async () => {
    const server = fakeServer();
    renderNetwork("/network?person=p-mara-klein");
    await loaded();
    const rail = () => screen.getByTestId("person-rail");
    fireEvent.click(within(rail()).getByRole("button", { name: "Log contact today" }));
    await waitFor(() => expect(server.posts("person_save")).toHaveLength(1));
    expect(server.posts("person_save")[0].body).toEqual({ id: "p-mara-klein", last_interaction: TODAY });
    fireEvent.change(within(rail()).getByLabelText("Interaction note"), { target: { value: "first call" } });
    fireEvent.click(within(rail()).getByRole("button", { name: "Log contact today" }));
    await waitFor(() => expect(server.posts("person_save")).toHaveLength(2));
    expect(server.posts("person_save")[1].body).toEqual({ id: "p-mara-klein", last_interaction: TODAY, notes: `${TODAY} — first call` });
  });

  it("Log founder call opens Founder Calls with the person prefilled", async () => {
    const server = fakeServer();
    const { router } = renderNetwork("/network?person=p-jonas-albrecht");
    await loaded();
    fireEvent.click(within(screen.getByTestId("person-rail")).getByRole("button", { name: "Log founder call" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/founder-calls"));
    expect(Object.fromEntries(search(router))).toEqual({ log: "1", person_id: "p-jonas-albrecht", name: "Jonas Albrecht", company: "Aereus" });
    expect(server.posts()).toEqual([]);
  });
});

describe("Network — the talented ritual", () => {
  it("inline: no name is refused without a request; the answers post as typed", async () => {
    const server = fakeServer();
    renderNetwork("/network?person=p-tariq-haddad");
    await loaded();
    const inline = screen.getByTestId("talented-inline");
    fireEvent.click(within(inline).getByRole("button", { name: "Create linked people" }));
    await screen.findByText("Enter at least one name");
    expect(server.posts()).toEqual([]);
    fireEvent.change(within(inline).getByLabelText("Ask Tariq: person 1"), { target: { value: "Eva Stein" } });
    fireEvent.change(within(inline).getByLabelText("Ask Tariq: person 1 — why talented"), { target: { value: "vision PhD" } });
    fireEvent.change(within(inline).getByLabelText("person 3 — why"), { target: { value: "a note without a name" } });
    fireEvent.click(within(inline).getByRole("button", { name: "Create linked people" }));
    await screen.findByText("1 people created & linked");
    expect(server.posts("talented").map((c) => c.body)).toEqual([{ id: "p-tariq-haddad", persons: [{ name: "Eva Stein", note: "vision PhD" }] }]);
    await waitFor(() => expect(within(screen.getByTestId("talented-inline")).getByLabelText("Ask Tariq: person 1")).toHaveValue(""));
  });

  it("drawer: the ritual posts every named answer, then closes the drawer on the person", async () => {
    const server = fakeServer({ talented: () => ({ status: 200, body: { ok: true, created: ["p-kai-brenner", "p-lia-voss"] } }) });
    const { router } = renderNetwork("/network?person=p-tariq-haddad");
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Edit full profile" }));
    const dlg = await screen.findByRole("dialog", { name: "Tariq Haddad" });
    expect(dlg).toHaveTextContent("the tool never fills in facts about people");
    const ritual = within(dlg).getByTestId("talented-ritual");
    expect(ritual).toHaveTextContent('The ritual: "Who are the three most talented people you know?"');
    expect(ritual).toHaveTextContent("Log Tariq Haddad's answers - each becomes a linked person with the chain preserved.");
    fireEvent.change(within(ritual).getByLabelText("Person 1 - name"), { target: { value: "Kai Brenner" } });
    fireEvent.change(within(ritual).getByLabelText("Person 2 - name"), { target: { value: "Lia Voss" } });
    fireEvent.change(within(ritual).getByLabelText("Person 2 - name — why talented (optional)"), { target: { value: "robot arms" } });
    fireEvent.click(within(ritual).getByRole("button", { name: "Create the three linked people" }));
    await screen.findByText("2 people created & linked");
    expect(server.posts("talented")[0].body).toEqual({
      id: "p-tariq-haddad",
      persons: [
        { name: "Kai Brenner", note: "" },
        { name: "Lia Voss", note: "robot arms" },
      ],
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(search(router).get("person")).toBe("p-tariq-haddad");
  });
});

describe("Network — the person drawer", () => {
  it("?person=&edit=1 opens the edit drawer once, removes edit, and the save posts every field", async () => {
    const server = fakeServer();
    const { router } = renderNetwork("/network?person=p-sofia-brandt&edit=1");
    const dlg = await screen.findByRole("dialog", { name: "Sofia Brandt" });
    await waitFor(() => expect(router.state.location.search).toBe("?person=p-sofia-brandt"));
    expect(router.state.historyAction).toBe("REPLACE");
    expect(within(dlg).getByLabelText("Watch (signal watchlist — weekly manual sweep)")).toBeChecked();
    expect(field(dlg, "startups")).toHaveValue("Pixel Forge, Helsing");
    expect(field(dlg, "relationship_strength")).toHaveValue("warm");
    fireEvent.change(within(dlg).getByLabelText("Role"), { target: { value: "Staff research engineer" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save person" }));
    await screen.findByText("Saved");
    const b = server.posts("person_save")[0].body!;
    expect(Object.keys(b).sort()).toEqual(["id", ...PERSON_FIELDS, "watch"].sort());
    expect(PERSON_FIELDS).toHaveLength(19);
    expect(b).toEqual({
      id: "p-sofia-brandt",
      name: "Sofia Brandt",
      location: "Berlin, Germany",
      company: "Helsing",
      role: "Staff research engineer",
      university: "TU Munich",
      expertise: "Perception",
      why_interesting: "Ships perception models to hardware",
      discovery: "Boardy",
      founder_potential: "none",
      relationship_strength: "warm",
      last_interaction: "2026-09-12",
      linkedin: "https://www.linkedin.com/in/sofia-brandt",
      x: "https://x.com/sofiab",
      startups: "Pixel Forge, Helsing",
      email: "sofia@example.org",
      next_action: "Coffee in December",
      next_action_date: "2026-12-02",
      notes: "Prefers email.",
      github: "https://github.com/sofiab",
      watch: true,
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(search(router).get("person")).toBe("p-sofia-brandt");
  });

  it("+ Person opens an empty form with the old defaults and posts no id", async () => {
    const server = fakeServer();
    const { router } = renderNetwork();
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "+ Person" }));
    const dlg = await screen.findByRole("dialog", { name: "Add person" });
    expect(within(dlg).getByLabelText("Founder potential")).toHaveValue("maybe");
    expect(within(dlg).getByLabelText("Relationship strength")).toHaveValue("met_once");
    expect(within(dlg).getByLabelText("Last interaction (YYYY-MM-DD)")).toHaveValue(TODAY);
    expect(within(dlg).getByLabelText("Watch (signal watchlist — weekly manual sweep)")).not.toBeChecked();
    expect(within(dlg).queryByTestId("talented-ritual")).toBeNull();
    expect(Array.from(field(dlg, "founder_potential").querySelectorAll("option")).map((o) => o.textContent)).toEqual(["—", "Maybe", "High", "Building now"]);
    fireEvent.change(within(dlg).getByLabelText("Name"), { target: { value: "New Person" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save person" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const b = server.posts("person_save")[0].body!;
    expect(b).not.toHaveProperty("id");
    expect(Object.keys(b).sort()).toEqual([...PERSON_FIELDS, "watch"].sort());
    expect(b).toMatchObject({ name: "New Person", founder_potential: "maybe", relationship_strength: "met_once", last_interaction: TODAY, watch: false });
    expect(search(router).get("person")).toBe("p-new-person");
    await waitFor(() => expect(profileName()).toBe("New Person"));
  });

  it("an add whose person exists (409 duplicate) offers the existing person, which opens on click", async () => {
    const server = fakeServer();
    const { router } = renderNetwork("/network?person=p-jonas-albrecht");
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "+ Person" }));
    const dlg = await screen.findByRole("dialog", { name: "Add person" });
    fireEvent.change(within(dlg).getByLabelText("Name"), { target: { value: "Lena Vogt" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save person" }));
    const alert = await within(dlg).findByTestId("save-duplicate");
    expect(alert).toHaveTextContent("a person with this name is already in your network — open them to edit");
    expect(screen.getByRole("dialog", { name: "Add person" })).toBeInTheDocument();
    expect(within(dlg).getByLabelText("Name")).toHaveValue("Lena Vogt");
    fireEvent.click(within(alert).getByRole("button", { name: "Open existing person" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(router.state.location.pathname).toBe("/network");
    expect(search(router).get("person")).toBe("p-lena-vogt");
    expect(router.state.historyAction).toBe("PUSH");
    await waitFor(() => expect(profileName()).toBe("Lena Vogt"));
    expect(server.posts()).toHaveLength(1);
  });

  it("a duplicate without a message still names the way out", async () => {
    fakeServer({ save: () => ({ status: 409, body: { ok: false, duplicate: true, id: "p-lena-vogt" } }) });
    renderNetwork();
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "+ Person" }));
    const dlg = await screen.findByRole("dialog", { name: "Add person" });
    fireEvent.change(within(dlg).getByLabelText("Name"), { target: { value: "Lena Vogt" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save person" }));
    expect(await within(dlg).findByTestId("save-duplicate")).toHaveTextContent("A person with this name is already in your network.");
  });

  it("an edit of a person the server no longer has (404) keeps the form, without a duplicate offer", async () => {
    const server = fakeServer({ save: (b) => (b.id ? { status: 404, body: { ok: false, error: "unknown person — nothing was changed" } } : undefined) });
    renderNetwork("/network?person=p-sofia-brandt&edit=1");
    const dlg = await screen.findByRole("dialog", { name: "Sofia Brandt" });
    fireEvent.change(within(dlg).getByLabelText("Role"), { target: { value: "Lead" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save person" }));
    await screen.findByText(/unknown person — nothing was changed/);
    expect(screen.getByRole("dialog", { name: "Sofia Brandt" })).toBeInTheDocument();
    expect(within(dlg).getByLabelText("Role")).toHaveValue("Lead");
    expect(within(dlg).queryByTestId("save-duplicate")).toBeNull();
    expect(server.posts("person_save")).toHaveLength(1);
  });

  it("a strong identifier owned by someone else (409 without duplicate) keeps the form, without a duplicate offer", async () => {
    fakeServer({ save: () => ({ status: 409, body: { ok: false, error: "this LinkedIn profile belongs to Lena Vogt — nothing was changed" } }) });
    renderNetwork("/network?person=p-sofia-brandt&edit=1");
    const dlg = await screen.findByRole("dialog", { name: "Sofia Brandt" });
    fireEvent.change(within(dlg).getByLabelText("LinkedIn"), { target: { value: "https://www.linkedin.com/in/lena-vogt" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save person" }));
    await screen.findByText(/this LinkedIn profile belongs to Lena Vogt/);
    expect(screen.getByRole("dialog", { name: "Sofia Brandt" })).toBeInTheDocument();
    expect(within(dlg).queryByTestId("save-duplicate")).toBeNull();
  });
});

describe("Network — deep links", () => {
  it("an unknown ?person= says so (wide); &edit=1 never turns it into an add form", async () => {
    const server = fakeServer();
    const { router } = renderNetwork("/network?person=p-nobody&edit=1");
    await loaded();
    expect(screen.getByText("This person is not in your network records.")).toBeInTheDocument();
    expect(screen.getByText("Select a person.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(router.state.location.search).toBe("?person=p-nobody"));
    expect(server.posts()).toEqual([]);
  });

  it("an unknown ?person= says so in the drawer (narrow)", async () => {
    setWide(false);
    fakeServer();
    renderNetwork("/network?person=p-nobody");
    const dlg = await screen.findByRole("dialog", { name: "Person" });
    expect(dlg).toHaveTextContent("This person is not in your network records.");
  });
});

describe("Network — the talent graph", () => {
  it("Graph shows the forest; a name opens that person's edit drawer; List returns", async () => {
    const server = fakeServer();
    renderNetwork();
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Graph" }));
    expect(screen.getByRole("button", { name: "List" })).toHaveAttribute("aria-pressed", "true");
    const g = screen.getByTestId("talent-graph");
    await within(g).findByRole("button", { name: "Lena Vogt" });
    expect(server.reads("/api/network/graph")).toBe(1);
    expect(g).toHaveTextContent("Lena Vogt high PhD researcher, legged robots · KIT Robotics Lab → Leggo Robotics");
    expect(g).toHaveTextContent("Felix Ortmann maybe watch");
    // "none" is not shown as a founder-potential tag
    expect(g.textContent).not.toContain("none");
    expect(screen.queryAllByTestId("person-row")).toHaveLength(0);
    fireEvent.click(within(g).getByRole("button", { name: "Mara Klein" }));
    const dlg = await screen.findByRole("dialog", { name: "Mara Klein" });
    expect(within(dlg).getByLabelText("Name")).toHaveValue("Mara Klein");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "List" }));
    expect(screen.getAllByTestId("person-row")).toHaveLength(7);
    expect(server.posts()).toEqual([]);
  });

  it("an empty forest names the ritual", async () => {
    fakeServer({ graph: { forest: [] } });
    renderNetwork();
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Graph" }));
    expect(await screen.findByText('No chains yet — the "3 most talented" ritual builds this.')).toBeInTheDocument();
  });
});

describe("Network — narrow screens", () => {
  it("no person opens by itself; a row opens profile + rail in a drawer; closing clears ?person=", async () => {
    setWide(false);
    fakeServer();
    const { router } = renderNetwork();
    await loaded();
    expect(screen.queryByTestId("person-profile")).toBeNull();
    expect(screen.queryByTestId("person-rail")).toBeNull();
    expect(screen.getByRole("list", { name: "People" })).not.toHaveAttribute("data-has-selection");
    fireEvent.click(screen.getAllByTestId("person-row")[4]);
    const dlg = await screen.findByRole("dialog", { name: "Lena Vogt" });
    expect(within(dlg).getByTestId("person-profile")).toBeInTheDocument();
    expect(within(dlg).getByTestId("person-rail")).toBeInTheDocument();
    expect(search(router).get("person")).toBe("p-lena-vogt");
    // Edit full profile swaps the person drawer for the edit drawer
    fireEvent.click(within(dlg).getByRole("button", { name: "Edit full profile" }));
    await screen.findByRole("dialog", { name: "Lena Vogt" });
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(within(screen.getByRole("dialog")).getByRole("form", { name: "Person form" })).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Close" }));
    const back = await screen.findByRole("dialog", { name: "Lena Vogt" });
    expect(within(back).getByTestId("person-rail")).toBeInTheDocument();
    fireEvent.click(within(back).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(search(router).get("person")).toBeNull();
  });
});

describe("Network — not ported yet", () => {
  it("the identity review keeps its row, says why, and neither reads nor writes identity", async () => {
    const server = fakeServer();
    renderNetwork();
    await loaded();
    const idr = screen.getByTestId("identity-review");
    expect(idr.closest("[data-deferred]")).not.toBeNull();
    expect(idr).toHaveTextContent("Identity review");
    expect(idr).toHaveTextContent("Identity review arrives with the identity port");
    // opening it only shows the explanation (no answers to give, nothing loaded)
    fireEvent.click(within(idr).getByText("Identity review"));
    await waitFor(() => expect(within(idr).getByTestId("identity-deferred")).toBeInTheDocument());
    expect(within(idr).queryAllByRole("button")).toHaveLength(0);
    // every disabled control on the page says why and sends nothing when pressed
    for (const el of Array.from(document.querySelectorAll('[aria-disabled="true"]'))) {
      expect(el.getAttribute("title")).toBeTruthy();
      expect(document.getElementById(el.getAttribute("aria-describedby") ?? "")?.textContent).toBeTruthy();
      pressEveryWay(el);
    }
    expect(server.calls.some((c) => c.path.includes("identity"))).toBe(false);
    expect(server.posts()).toEqual([]);
  });
});

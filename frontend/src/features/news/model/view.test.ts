import { describe, expect, it } from "vitest";

import { emptyNews, news } from "../test/fixtures";
import { NOT_PORTED } from "./deferred";
import type { Story } from "./types";
import {
  analysisLabel,
  canAudit,
  checkText,
  companiesLine,
  disagreementLine,
  EMPTY,
  fmt,
  footerLine,
  independence,
  isStoryTab,
  metaLine,
  NO_BACKCAST,
  proposalText,
  provenance,
  showsProposal,
  signalBadge,
  stateBadge,
  storiesFor,
  TABS,
  takesSignals,
  whatHappened,
} from "./view";

const story = (company: string): Story => news().stories.find((s) => s.company === company)!;

describe("the sections", () => {
  it("are the nine old tabs, in order", () => {
    expect(TABS.map((t) => t.label)).toEqual([
      "Today",
      "All stories",
      "Caught early",
      "Misses",
      "Historical cases",
      "What's moving",
      "My companies",
      "Weekly review",
      "News sources",
    ]);
    expect(TABS.filter((t) => isStoryTab(t.value)).map((t) => t.value)).toEqual(Object.keys(EMPTY));
  });
  it("list the payload's own lists, unchanged", () => {
    const d = news();
    const names = (t: Parameters<typeof storiesFor>[0]) => storiesFor(t, d).map((s) => s.company);
    expect(names("today")).toEqual(["Vantor Kinetics", "Quillon Labs", "Lumora Grid"]);
    expect(names("all")).toEqual(["Vantor Kinetics", "Quillon Labs", "Brightwell Bio", "Halvard Robotics", "Lumora Grid", "Ostra Systems", "Pinecrest Capital"]);
    expect(names("caught")).toEqual(["Vantor Kinetics"]);
    expect(names("misses")).toEqual(["Quillon Labs", "Brightwell Bio"]);
    expect(names("historical")).toEqual(["Halvard Robotics"]);
    expect(names("mine")).toEqual(["Vantor Kinetics", "Lumora Grid"]);
    for (const t of Object.keys(EMPTY) as Array<keyof typeof EMPTY>) expect(storiesFor(t, emptyNews())).toEqual([]);
  });
});

describe("dates", () => {
  it("keep a year, shorten a month, spell a day and pass anything else through", () => {
    expect(fmt("2020")).toBe("2020");
    expect(fmt("2021-06")).toBe("Jun 2021");
    expect(fmt("2026-10-05")).toBe("5 Oct 2026");
    expect(fmt("soon")).toBe("soon");
    expect(fmt("")).toBe("");
  });
});

describe("the footer", () => {
  it("says when the last refresh ran, how many feeds failed and when Project Zero started", () => {
    expect(footerLine(news())).toBe(
      "Last refresh: 2026-11-12 07:00 · 5 feeds · 3 new events · 1 feed(s) failed (retried tomorrow). Project Zero started on 27 Sept 2026.",
    );
    expect(footerLine(emptyNews())).toBe("Last refresh: not yet. Project Zero started on 27 Sept 2026.");
  });
});

describe("a story card", () => {
  it("badges, the meta line and what happened (card, summary, or the headline only)", () => {
    expect(stateBadge("CAUGHT_EARLY")).toEqual({ label: "EARLY CATCH", tone: "green" });
    expect(stateBadge("SOMETHING")).toEqual({ label: "NOT SEEN BY PZ", tone: "neutral" });
    expect(metaLine(story("Vantor Kinetics"))).toBe("Funding round · 10 Nov 2026 · 3 sources");
    expect(metaLine(story("Brightwell Bio"))).toBe("Acquisition · 3 Nov 2026 · 1 source");
    expect(whatHappened(story("Lumora Grid"))).toBe(story("Lumora Grid").summary);
    expect(whatHappened(story("Ostra Systems"))).toBe("Only the headline is available — open the source.");
  });
  it("disagreements: settled and open, never a silent winner", () => {
    expect(disagreementLine(story("Vantor Kinetics").disagreements!)).toBe("amount: Isar Startup Post 18M vs Alpine Wire 18.4M (settled by primary source)");
    expect(disagreementLine(story("Quillon Labs").disagreements!)).toBe("round: Alpine Wire series b vs Harbour Post series c (not settled yet)");
  });
  it("the outcome proposal shows until a decision is recorded", () => {
    const v = story("Vantor Kinetics");
    expect(showsProposal(v)).toBe(true);
    expect(proposalText(v)).toBe(
      " this looks like a real-world institutional round for Vantor Kinetics. Project Zero first saw Vantor Kinetics 61 day(s) before this event. Only your confirmation records it in Validation.",
    );
    expect(showsProposal(story("Lumora Grid"))).toBe(false); // rejected before
    expect(showsProposal({ ...v, outcome_decision: "confirm" })).toBe(false);
  });
  it("the analysis toggle, the miss audit and the early-signal actions", () => {
    expect(analysisLabel(story("Brightwell Bio"), false)).toBe("Backcast & sources");
    expect(analysisLabel(story("Vantor Kinetics"), false)).toBe("Sources & learning");
    expect(analysisLabel(story("Vantor Kinetics"), true)).toBe("Hide analysis");
    expect(canAudit(story("Brightwell Bio"))).toBe(true); // missed, no audit
    expect(canAudit(story("Quillon Labs"))).toBe(false); // possible miss, but audited
    expect(canAudit({ ...story("Quillon Labs"), audit_id: null })).toBe(true);
    expect(canAudit({ ...story("Brightwell Bio"), company: "" })).toBe(false);
    expect(canAudit(story("Vantor Kinetics"))).toBe(false);
    expect(takesSignals(story("Vantor Kinetics"))).toBe(true);
    expect(takesSignals(story("Lumora Grid"))).toBe(false); // MEDIUM
    expect(NO_BACKCAST).not.toMatch(/research/);
  });
  it("sources: independence and the card's provenance", () => {
    expect(independence("syndicated")).toEqual({ label: "copy of another article", tone: "neutral" });
    expect(independence("primary")).toEqual({ label: "primary source", tone: "blue" });
    expect(independence("independent")).toEqual({ label: "independent media", tone: "green" });
    expect(provenance("rules")).toBe("Summary built by rules (no model) from the article text.");
    expect(provenance("curated from the linked sources")).toBe("Curated from the linked sources.");
    expect(provenance("gemma-mini")).toBe("Summary written by gemma-mini from the article text only.");
    expect(signalBadge("known_early_signal").label).toBe("known early signal");
    expect(signalBadge("in_retrospect").label).toBe("only clear in retrospect");
  });
});

describe("the Project Zero check, per state", () => {
  const pz = "2026-09-27";
  it("an early catch leads with the edge", () => {
    expect(checkText(story("Vantor Kinetics"), pz)).toEqual({
      strong: "Project Zero edge: detected 61 days before this event.",
      text: "First seen 10 Sept 2026 via northgate-spinouts (pre-company), capital stage then: pre seed. Machine said STRONG, you decided PURSUE.",
    });
    const bare = { ...story("Vantor Kinetics"), check: { known: true, lead_days: 20, pz_first_seen: "2026-10-01", state: "CAUGHT_EARLY" as const } };
    expect(checkText(bare, pz).text).toBe("First seen 1 Oct 2026 via a scan. Machine said —.");
  });
  it("late, historical, missed, not relevant and unseen", () => {
    expect(checkText(story("Lumora Grid"), pz).text).toBe(
      "Project Zero knew Lumora Grid, but only at the time of this news — it was found through funding news itself. No sourcing edge claimed.",
    );
    const late = story("Lumora Grid");
    expect(checkText({ ...late, check: { ...late.check, lead_days: 5, first_tier: "pre_company" } }, pz).text).toBe(
      "Project Zero knew Lumora Grid, but only 5 days this news. No sourcing edge claimed.",
    );
    expect(checkText(story("Halvard Robotics"), pz).text).toBe("Its early signals predate Project Zero (started 27 Sept 2026) — a learning case, not a miss.");
    expect(checkText(story("Brightwell Bio"), pz).text).toBe("A public signal existed while Project Zero was running, and Project Zero did not detect it.");
    expect(checkText(story("Pinecrest Capital"), pz).text).toBe("Outside Project Zero's geography or themes — context only.");
    expect(checkText(story("Quillon Labs"), pz).text).toBe(
      "Project Zero has not seen Quillon Labs. Not yet reviewed — it may be a miss, or the early signals may predate Project Zero. Add a backcast or audit it.",
    );
    expect(checkText({ ...story("Ostra Systems"), company: "" }, pz).text).toBe("Project Zero has not seen this company. ");
  });
});

describe("What's moving and the deferrals", () => {
  it("counts the companies Project Zero holds", () => {
    expect(companiesLine(1)).toBe("Project Zero already holds 1 company with this theme.");
    expect(companiesLine(7)).toBe("Project Zero already holds 7 companies with this theme.");
  });
  it("say which port brings each control (the 028b decisions are enabled)", () => {
    expect(NOT_PORTED).toEqual({
      refresh: "Refreshing News arrives with the News refresh port (028c)",
      health: "System health arrives with its port",
    });
  });
});

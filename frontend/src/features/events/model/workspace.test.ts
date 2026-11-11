import { describe, expect, it } from "vitest";

import type { EventRecord, ScoutReport } from "./types";
import { DEFAULT_FILTERS, counts, dayGroups, dayMarks, inView, isPriority, isRich, itemsOf, monthGrid, priorityWhy, shiftMonth, visible, type WsFilters } from "./workspace";

let n = 0;
function ev(p: Partial<EventRecord> & { days?: number | null; tier?: string; order?: number | null; area?: string }): EventRecord {
  const d = p.days === undefined ? 5 : p.days;
  const start = d == null ? "" : new Date(Date.UTC(2026, 10, 10 + d)).toISOString().slice(0, 10);
  n += 1;
  return {
    id: p.id ?? `e${n}`,
    name: p.name ?? `Event ${n}`,
    status: p.status ?? "new",
    type: p.type ?? "founder_meetup",
    days_until: d,
    past: d != null && d < 0,
    when: { start_date: start, start_time: p.when?.start_time ?? "", days_until: d },
    eligibility: { tier: p.tier ?? "HIGH-SIGNAL" },
    sc: { total: p.order === undefined ? 39 : p.order, band: "", evidence: [] },
    place: { city: "", area: "", country: "", country_name: "", label: p.area ?? "Berlin, Germany", area_label: p.area ?? "Berlin, Germany" },
    themes: p.themes ?? [],
    scout: p.scout ?? null,
    assessment: p.assessment,
    human_verified: p.human_verified,
  };
}
const report = (p: Partial<ScoutReport> = {}): ScoutReport => ({
  key: "scout-1", name: "Northlight Summit 2026", date: "2026-11-17", days_until: 7, city: "Helsinki",
  place: { city: "Helsinki", area: "Helsinki", country: "FI", country_name: "Finland", label: "Helsinki, Finland", area_label: "Helsinki, Finland" },
  p_class: "P2", ev_class: "EV-A", why: "Nordic founder density", action: "", cycles: ["008"], url: "https://example.org/northlight",
  report_ids: ["se-008-1"], statuses: ["NEW"], themes: ["Robotics"], tracked_event_id: "", ...p,
});
const scoutP = (p: string) => ({ p_class: p, ev_class: "EV-A", why: "", action: "", cycles: ["008"] });
const F = (p: Partial<WsFilters> = {}) => ({ ...DEFAULT_FILTERS, ...p });
const names = (xs: Array<{ name: string }>) => xs.map((x) => x.name);

describe("items: events and Scout 00 suggestions", () => {
  it("an untracked report becomes a suggestion item; a tracked one does not appear twice", () => {
    const its = itemsOf([ev({ name: "Lakeside Investor Day" })], [report(), report({ key: "scout-2", name: "Lakeside Investor Day", tracked_event_id: "ev-lakeside" })]);
    expect(its.map((i) => [i.kind, i.name])).toEqual([["event", "Lakeside Investor Day"], ["suggestion", "Northlight Summit 2026"]]);
  });

  it("priority: planned, Scout 00 P1/P2, strong evidence — never skipped or past", () => {
    const p = (e: EventRecord) => isPriority(itemsOf([e], [])[0]);
    expect(p(ev({ status: "planned", tier: "NEEDS REVIEW" }))).toBe(true);
    expect(p(ev({ tier: "NEEDS REVIEW", scout: scoutP("P1") }))).toBe(true);
    expect(p(ev({ tier: "NEEDS REVIEW", scout: scoutP("P3") }))).toBe(false);
    expect(p(ev({ order: 69 }))).toBe(true);
    expect(p(ev({ order: 39 }))).toBe(false);
    expect(p(ev({ order: 69, status: "skipped" }))).toBe(false);
    expect(p(ev({ order: 69, days: -2 }))).toBe(false);
    expect(isPriority(itemsOf([], [report({ p_class: "P3" })])[0])).toBe(false);
    expect(priorityWhy(itemsOf([], [report()])[0])).toBe("Scout 00 P2");
  });

  it("rich card vs one quiet line: title-only listings stay a line", () => {
    const [hs, rv, sc, ver, sug] = itemsOf([ev({}), ev({ tier: "NEEDS REVIEW" }), ev({ tier: "NEEDS REVIEW", scout: scoutP("P3") }), ev({ tier: "NEEDS REVIEW", human_verified: true })], [report()]);
    expect([hs, rv, sc, ver, sug].map(isRich)).toEqual([true, false, true, true, true]);
  });
});

describe("views", () => {
  const its = itemsOf(
    [ev({ name: "hs" }), ev({ name: "rv", tier: "NEEDS REVIEW" }), ev({ name: "rej", tier: "REJECTED" }), ev({ name: "go", status: "planned" }), ev({ name: "scoutRv", tier: "NEEDS REVIEW", scout: scoutP("P2") }), ev({ name: "old", days: -3 })],
    [report()],
  );
  it("upcoming hides general/rejected unless asked; past events never show", () => {
    expect(names(visible(its, "upcoming", F()))).not.toContain("rej");
    expect(names(visible(its, "upcoming", F()))).not.toContain("old");
    expect(names(visible(its, "upcoming", F({ general: true })))).toContain("rej");
    expect(names(visible(its, "upcoming", F()))).toContain("Northlight Summit 2026");
  });
  it("planned, priority and Scout suggestions are real views over the records", () => {
    expect(names(visible(its, "planned", F()))).toEqual(["go"]);
    expect(names(visible(its, "priority", F())).sort()).toEqual(["Northlight Summit 2026", "go", "scoutRv"]);
    expect(names(visible(its, "suggestions", F())).sort()).toEqual(["Northlight Summit 2026", "scoutRv"]);
    expect(inView(its[0], "suggestions", F())).toBe(false);
  });
  it("attended events show only in the Attended toggle", () => {
    const a = itemsOf([ev({ name: "went", status: "attended", days: -4 })], []);
    expect(visible(a, "upcoming", F())).toEqual([]);
    expect(names(visible(a, "upcoming", F({ past: true })))).toEqual(["went"]);
  });
});

describe("filters, counts, day groups, calendar", () => {
  const its = itemsOf(
    [
      ev({ name: "ai", themes: ["AI"], days: 3, area: "Zürich, Switzerland", assessment: { founder: "HIGH" } }),
      ev({ name: "rob", themes: ["Robotics"], days: 20, type: "demo_day", area: "Paris, France" }),
    ],
    [report()],
  );
  it("date window, area (metro), theme, type, founders, investors", () => {
    expect(names(visible(its, "upcoming", F({ days: "7" })))).toEqual(["ai", "Northlight Summit 2026"]); // the summit is 7 days out
    expect(names(visible(its, "upcoming", F({ area: "Paris, France" })))).toEqual(["rob"]);
    expect(names(visible(its, "upcoming", F({ theme: "Robotics" })))).toEqual(["Northlight Summit 2026", "rob"]);
    expect(names(visible(its, "upcoming", F({ type: "demo_day" })))).toEqual(["rob"]);
    expect(names(visible(its, "upcoming", F({ founders: "high" })))).toEqual(["ai"]);
    expect(names(visible(its, "upcoming", F({ investors: "yes" })))).toEqual(["rob"]);
  });
  it("a calendar day filters the list; option counts ignore their own filter", () => {
    expect(names(visible(its, "upcoming", F({ date: "2026-11-17" })))).toEqual(["Northlight Summit 2026"]);
    expect(counts(visible(its, "upcoming", F({ area: "Paris, France" }), "area"), "area")).toEqual([["Helsinki, Finland", 1], ["Paris, France", 1], ["Zürich, Switzerland", 1]]);
  });
  it("groups by day, splits cards from quiet lines, and counts what is beyond the cutoff", () => {
    const g = dayGroups(visible(its, "upcoming", F()), "2026-11-20");
    expect(g.groups.map((x) => x.day)).toEqual(["2026-11-13", "2026-11-17"]);
    expect(g.rest).toBe(1);
  });
  it("month grid is Monday-first; marks carry priority and planned", () => {
    const grid = monthGrid("2026-11");
    expect(grid).toHaveLength(42);
    expect(grid[0]).toBe("2026-10-26");
    expect(grid.indexOf("2026-11-01")).toBe(6);
    const marks = dayMarks(itemsOf([ev({ days: 7, status: "planned" })], [report()]));
    expect(marks.get("2026-11-17")).toEqual({ n: 2, priority: true, planned: true });
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
  });
});

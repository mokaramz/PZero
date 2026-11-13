import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { home, homeQuiet, inbox, NOW, pipeline, sources, today } from "../test/fixtures";
import { att, attWhy } from "./attention";
import {
  activityOf,
  candidateLink,
  companyLink,
  deskView,
  eventDate,
  gatedOf,
  lastScanLine,
  machineLine,
  missionRows,
  NOTHING,
  promising,
  rec,
  sourceWarnings,
  summaryOf,
  tierL,
  timeOf,
} from "./desk";
import { flowLabel, flowPath, flowSince, flowStages, flowXs } from "./flow";
import type { Candidate, ReviewRow, Signal } from "./types";

const full = () => deskView({ h: home(), ib: inbox(), pipe: pipeline(), today: today(), rows: [], sources: sources() });
const live = () => pipeline().signals.filter((s) => s.status !== "dropped");
const review = (x: Partial<ReviewRow> & { id: string }): ReviewRow => ({ name: `Review ${x.id}`, decision: "new", ...x });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});
afterEach(() => vi.useRealTimers());

describe("Investment Desk — the rows of Priority missions", () => {
  it("Today's company and signal missions in Today's order, then the due follow-ups; Manager and event missions are not rows", () => {
    const rows = missionRows(today(), live(), [], home().due);
    expect(rows.map((r) => [r.key, r.state, r.action, r.to])).toEqual([
      ["t-CONTACT_FOUNDER-Halvorsen Robotics", "Your move", "Open", "/conviction?company=halvorsen-robotics"],
      ["t-PREPARE_FOUNDER_CALL-Ilse Marquardt", "Founder call", "Open", "/founder-calls"],
      ["t-CASE_READY-Tessaro Grid", "Case prepared", "Open", "/conviction?company=tessaro-grid"],
      ["t-REVIEW_VERIFICATION-Nordvik Materials", "Verification", "Open", "/conviction?company=nordvik-materials"],
      ["t-TRIAGE_REVIEW-Review 10", "Signal review", "Open", "/deal-flow?filter=triage&route=NEEDS_MOHAMED"],
      ["f-p-ilse-marquardt", "Follow-up", "Open", "/network?person=p-ilse-marquardt"],
      ["f-p-jonas-feld", "Follow-up", "Open", "/network?person=p-jonas-feld"],
    ]);
  });

  it("a mission row: the why-now (else the line), the biggest unknown and the field's tone", () => {
    const [contact, , kase] = missionRows(today(), live(), [], []);
    expect(contact).toMatchObject({ name: "Halvorsen Robotics", unknown: "Core facts verified", tone: "neutral" });
    expect(contact.reason).toBe("Two plant pilots converted to paid contracts in October; the seed…");
    expect(kase.unknown).toBe("Unverified: traction");
    // without the pipeline the mission keeps its own line and has no unknown
    const bare = missionRows(today(), [], [], [])[0];
    expect(bare.unknown).toBe("");
    expect(bare.reason).toBeTruthy();
  });

  it("a follow-up row: the action as the reason, its due date or 'no date set'", () => {
    const [, , , , , dated, undated] = missionRows(today(), live(), [], home().due);
    expect(dated).toMatchObject({ name: "Ilse Marquardt", reason: "Send the pilot data you promised", unknown: "due 2026-11-12", tone: "neutral" });
    expect(undated.unknown).toBe("no date set");
  });

  it("a review row (the deferred queue, decision d): only new reviews, the lowered recommendation, or not yet scorable", () => {
    const rows = missionRows(undefined, [], [
      review({ id: "r1", thesis: "Grid-edge storage for municipal utilities. Second sentence.", proposed: 54, recommendation: "STRONG_MAYBE" }),
      review({ id: "r2", proposed: null }),
      review({ id: "r3", decision: "kept", proposed: 70 }),
    ], undefined);
    expect(rows.map((r) => [r.key, r.reason, r.unknown, r.state, r.tone, r.action])).toEqual([
      ["r-r1", "Grid-edge storage for municipal utilities", "Analyst: strong maybe · proposed 54/100", "Review", "attention", "Open review"],
      ["r-r2", "", "Not yet scorable — entity unverified", "Review", "attention", "Open review"],
    ]);
    expect(rec("PASS_FOR_NOW")).toBe("pass for now");
    expect(rec(undefined)).toBe("");
  });

  it("no Today read, no follow-ups: no rows", () => {
    expect(missionRows(undefined, [], [], undefined)).toEqual([]);
  });
});

describe("Investment Desk — the view", () => {
  it("the counts behind the tiles and the flow: rows, Manager decisions, founders holding the ball, candidates to decide", () => {
    const v = full();
    expect(v.human).toHaveLength(7);
    expect(v.shownMissions).toHaveLength(5);
    expect(v.gated.map((e) => e.slug)).toEqual(["brightwell-analytics", "corvane-systems", "lumora-health", "pellucid-optics"]);
    expect(v.awaiting.map((e) => e.slug)).toEqual(["mirava-labs", "oskarberg-bio"]);
    expect(v.sig).toHaveLength(10); // the dropped company is neither gated nor awaiting nor counted
    expect(v.news).toHaveLength(8);
    expect(v.done).toBe(3);
    expect(v.warn).toBe(2);
    expect(v.summary).toBe("Deal flow is active: 7 missions need judgment, 4 Manager decisions are blocked and 2 founders hold the ball.");
  });

  it("the desk's own gate: a possible conflict OR CONFLICT GATED — never Conviction's narrower rule", () => {
    const s = (x: Partial<Signal>) => ({ slug: "x", company: "X", sc: { verified: 0, missing: [] }, ...x }) as Signal;
    expect(gatedOf(s({ conflict: "potential_conflict" }))).toBe(true);
    expect(gatedOf(s({ conflict: "unclear", op: { status: "CONFLICT GATED" } as Signal["op"] }))).toBe(true);
    expect(gatedOf(s({ conflict: "unclear" }))).toBe(false);
    expect(gatedOf(s({ conflict: "none", op: { status: "BLOCKED BY CONFLICT" } as Signal["op"] }))).toBe(false);
  });

  it("the best opportunity is the server's pick, joined with its Conviction record (or absent)", () => {
    const v = full();
    expect(v.pr?.slug).toBe("halvorsen-robotics");
    expect(v.prSig?.one_liner).toMatch(/^Autonomous palletising/);
    const none = deskView({ h: homeQuiet(), rows: [] });
    expect([none.pr, none.prSig]).toEqual([null, undefined]);
    const unknown = home();
    unknown.priority!.slug = "not-in-conviction";
    expect(deskView({ h: unknown, pipe: pipeline(), rows: [] }).prSig).toBeUndefined();
  });

  it("before the other reads arrive: empty counts, the quiet sentence", () => {
    const v = deskView({ h: homeQuiet(), rows: [] });
    expect([v.C, v.news, v.sig, v.human, v.gated, v.awaiting, v.att6, v.activity, v.done, v.warn]).toEqual([[], [], [], [], [], [], [], [], 0, 0]);
    expect(v.summary).toBe(NOTHING);
  });
});

describe("Investment Desk — the situational sentence", () => {
  it.each([
    [[1, 0, 0], "Deal flow is active: 1 mission needs judgment."],
    [[2, 0, 0], "Deal flow is active: 2 missions need judgment."],
    [[0, 1, 0], "Deal flow is active: 1 Manager decision is blocked."],
    [[0, 0, 1], "Deal flow is active: 1 founder holds the ball."],
    [[3, 1, 0], "Deal flow is active: 3 missions need judgment and 1 Manager decision is blocked."],
    [[0, 2, 2], "Deal flow is active: 2 Manager decisions are blocked and 2 founders hold the ball."],
    [[1, 1, 1], "Deal flow is active: 1 mission needs judgment, 1 Manager decision is blocked and 1 founder holds the ball."],
    [[0, 0, 0], NOTHING],
  ])("%j → %s", ([m, g, a], want) => {
    expect(summaryOf(m, g, a)).toBe(want);
  });
});

describe("Investment Desk — promising signals and recent activity", () => {
  it("the new candidates the queue does not gate, by final score then priority, six at most", () => {
    const att6 = promising(full().news);
    expect(att6.map((c) => c.name)).toEqual(["Quillon Robotics", "Tarnhelm Bio", "Marlowe Grid", "Ilvara Systems", "Corrib Health", "Sorrel Optics"]);
    const more = [...full().news, { ...full().news[0], id: "c-0199", name: "Seventh", attention_v2: { final: 99 } } as Candidate];
    expect(promising(more)).toHaveLength(6);
    expect(promising(more)[0].name).toBe("Seventh");
  });

  it("the tier label, the client attention fallback and its explanation", () => {
    const [q, , m, , , sorrel] = promising(full().news);
    expect([tierL(q), tierL(m), tierL(full().news[2])]).toEqual(["Pre-company", "Grant", "Announcement"]);
    expect(att(sorrel)).toBe(8); // freshness 4 (26 days) + earliness 3 + quality 1
    expect(attWhy(sorrel)).toBe(
      "attention 8 = freshness 4 (source date 2026-10-18) + earliness 3 + Project A fit 0 + source quality 1 + cross-source confirmation 0 + Feedback-adjusted sourcing priority 0",
    );
  });

  it("the activity: the last scan's top three, the reviews and the Manager list, newest first", () => {
    const a = full().activity;
    expect(a.map((x) => [x.t, x.title, x.sub, x.to])).toEqual([
      ["2026-11-12 22:18", "Tarnhelm Bio surfaced", "via Northfield Startup Press", candidateLink("c-0103")],
      ["2026-11-12 22:17", "Marlowe Grid surfaced", "via Copper Valley Awards", candidateLink("c-0102")],
      ["2026-11-12 22:16", "Quillon Robotics surfaced", "via Isarwerk Venture Lab (official)", candidateLink("c-0101")],
      ["2026-11-11", "Lumora Health sent to Manager", "feedback logged", "/conviction"],
      ["2026-11-09", "Brightwell Analytics sent to Manager", "awaiting feedback", "/conviction"],
    ]);
  });

  it("an analysed review joins the activity (the deferred queue), a source-less candidate says 'a source'", () => {
    const c = { id: "c-x", name: "Nameless", decision: "new", run_id: "R", first_seen: "2026-11-01" } as Candidate;
    const a = activityOf([c], "R", [review({ id: "r1", created: "2026-11-05 10:00", recommendation: "PASS", thesis: "One two three four five six seven eight nine." })], []);
    expect(a.map((x) => [x.title, x.sub])).toEqual([
      ["Review r1 analysed — pass", "One two three four five six seven eight…"],
      ["Nameless surfaced", "via a source"],
    ]);
    expect(activityOf([c], null, [], undefined)).toEqual([]);
  });
});

describe("Investment Desk — the machine work", () => {
  it("the source warnings: enabled sources with failures; never-scanned (null) is not a warning, the old `=== false` stays", () => {
    expect(sourceWarnings(sources())).toBe(2);
    expect(sourceWarnings(undefined)).toBe(0);
    const s = sources();
    s.sources = [{ ...s.sources[0], last_ok: false as unknown as string }];
    expect(sourceWarnings(s)).toBe(1);
  });

  it("the folded line and the last scan line", () => {
    expect(machineLine(inbox(), home().progress, 3, 2)).toBe("5 new in the last scan · 3 analyses · 2 source warnings");
    expect(machineLine(undefined, { found: 4 }, 1, 1)).toBe("4 new in the last scan · 1 analyses · 1 source warning");
    expect(machineLine(undefined, {}, 0, 0)).toBe("0 new in the last scan · 0 analyses · 0 source warnings");
    expect(lastScanLine(inbox())).toBe("Last scan 2026-11-12 22:15: 5 genuinely new (2 from pre-company channels) · 3 noise set aside.");
    expect(lastScanLine({ ...inbox(), last_summary: { new: 1 } })).toBe("Last scan 2026-11-12 22:15: 1 genuinely new.");
    expect(lastScanLine({ ...inbox(), last_summary: undefined })).toBe("Last scan 2026-11-12 22:15: 0 genuinely new.");
    expect(lastScanLine({ ...inbox(), last_run: null })).toBeNull();
    expect(lastScanLine(undefined)).toBeNull();
  });
});

describe("Investment Desk — the parsed dates (the old regexes)", () => {
  it("timeOf: a time when there is one, else '2 Nov', else the text as it is", () => {
    expect(timeOf("2026-11-02 18:57")).toBe("18:57");
    expect(timeOf("2026-11-02T08:05:00")).toBe("08:05");
    expect(timeOf("2026-11-02")).toBe("2 Nov");
    expect(timeOf("yesterday")).toBe("yesterday");
    expect(timeOf("")).toBe("");
  });

  it("eventDate: a YYYY-MM-DD start as a local date, else null", () => {
    expect(eventDate("2026-11-14")?.toDateString()).toBe(new Date(2026, 10, 14).toDateString());
    expect(eventDate("2026-11-14 18:00")?.getDate()).toBe(14);
    expect(eventDate("TBA")).toBeNull();
    expect(eventDate(undefined)).toBeNull();
  });

  it("the links", () => {
    expect(candidateLink("c 1/2")).toBe("/deal-flow?candidate=c%201%2F2");
    expect(companyLink("tessaro-grid")).toBe("/conviction?company=tessaro-grid");
  });
});

describe("Investment Desk — the flow graphic", () => {
  it("four stages: candidates first seen in the last 14 days (first_seen, else detected_on), then the desk's counts", () => {
    expect(flowSince(NOW)).toBe("2026-10-31");
    const stages = flowStages(inbox().candidates, 7, 4, 10, NOW);
    expect(stages.map((s) => [s.key, s.n, s.hint])).toEqual([
      ["signals", 8, "new · 14 days"],
      ["review", 7, "need you"],
      ["manager", 4, "blocked"],
      ["decision", 10, "in Conviction"],
    ]);
    expect(flowLabel(stages)).toBe(
      "Today's operating flow: Signals 8 (new · 14 days) → Review 7 (need you) → Manager 4 (blocked) → Decision 10 (in Conviction)",
    );
  });

  it("the nodes on their column centres, joined by one S-curved path", () => {
    expect(flowXs(4)).toEqual([40, 120, 200, 280]);
    expect(flowPath(flowXs(4))).toBe("M 40 22 C 80 13, 80 31, 120 22 C 160 31, 160 13, 200 22 C 240 13, 240 31, 280 22");
  });
});

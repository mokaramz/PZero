import { describe, expect, it } from "vitest";

import { type Action, clip, type Company, companyOf, firstSentence, headline, kind, KIND, mission, plural, sentence, short } from "./missions";
import { actionOf, pipeline, today, variants } from "./test/fixtures";

const signals = (): Company[] => pipeline().signals.filter((e) => e.status !== "dropped");
const act = (type: string, over: Partial<Action> = {}): Action => ({
  type,
  title: "",
  why: "",
  next_step: "",
  link: "/conviction",
  urgency: "medium",
  evidence: [],
  subject: "",
  conflict: "unknown",
  contact_appropriate: false,
  ...over,
});

describe("missions — the kinds", () => {
  it("knows the ten old action types, with the old labels, groups and moves", () => {
    expect(Object.keys(KIND)).toEqual([
      "CASE_READY",
      "CONTACT_FOUNDER",
      "PREPARE_FOUNDER_CALL",
      "REVIEW_VERIFICATION",
      "WATCH_TRIGGER",
      "NATIVE_INTEL",
      "SCOUT00_CYCLE",
      "EVENT_ACTION",
      "ASK_OMAR_CONFLICT",
      "TRIAGE_REVIEW",
    ]);
    const groups = Object.fromEntries(Object.entries(KIND).map(([t, k]) => [t, k.group]));
    expect(groups).toEqual({
      CASE_READY: "company",
      CONTACT_FOUNDER: "company",
      PREPARE_FOUNDER_CALL: "company",
      REVIEW_VERIFICATION: "company",
      WATCH_TRIGGER: "company",
      NATIVE_INTEL: "signal",
      SCOUT00_CYCLE: "signal",
      EVENT_ACTION: "event",
      ASK_OMAR_CONFLICT: "manager",
      TRIAGE_REVIEW: "signal",
    });
    const a = act("X");
    expect(Object.values(KIND).map((k) => [k.label, k.field(a)])).toEqual([
      ["Case ready", "neutral"],
      ["Your move", "neutral"],
      ["Founder call", "neutral"],
      ["Verification", "neutral"],
      ["New intel", "progress"],
      ["New intel", "progress"],
      ["Scout 00", "attention"],
      ["Event", "neutral"],
      ["Manager decision", "risk"],
      ["Signal review", "attention"],
    ]);
    expect(
      ["CONTACT_FOUNDER", "PREPARE_FOUNDER_CALL", "REVIEW_VERIFICATION", "WATCH_TRIGGER", "EVENT_ACTION", "ASK_OMAR_CONFLICT", "TRIAGE_REVIEW"].map((t) =>
        KIND[t].move(a),
      ),
    ).toEqual(["Contact the founder", "Prepare the call", "Verify the evidence", "Review the change", "Decide: go or skip", "Message Manager", "Review the queue"]);
  });

  it("a prepared case: attention only when urgent; its move is the backend's recommended action, up to a dash or a full stop", () => {
    const fresh = actionOf(today(), "CASE_READY");
    expect(KIND.CASE_READY.field(fresh)).toBe("attention");
    expect(KIND.CASE_READY.move(fresh)).toBe("Prepare a founder call");
    const [, , waiting, , , , weak] = variants().actions;
    expect(KIND.CASE_READY.field(waiting)).toBe("neutral");
    expect(KIND.CASE_READY.move(waiting)).toBe("Await the founder's response");
    expect(KIND.CASE_READY.move(weak)).toBe("Decide: watch or drop");
    expect(KIND.CASE_READY.move(act("CASE_READY", { why: "Nothing recommended" }))).toBe("Open the case");
  });

  it("an unknown type keeps its name as the label, groups with companies and moves by its own next step", () => {
    const k = kind("SOMETHING_NEW");
    expect([k.label, k.group, k.field(act("SOMETHING_NEW"))]).toEqual(["SOMETHING_NEW", "company", "neutral"]);
    expect(k.move(act("SOMETHING_NEW", { next_step: "Read the new memo before Friday and decide. Then tell the Manager." }))).toBe(
      "Read the new memo before…",
    );
    expect(kind("EVENT_ACTION")).toBe(KIND.EVENT_ACTION);
  });
});

describe("missions — the text helpers", () => {
  it("firstSentence, clip, plural, short and sentence", () => {
    expect(firstSentence("One. Two.")).toBe("One.");
    expect(firstSentence("No full stop")).toBe("No full stop");
    expect(clip("Verify the founders — then call")).toBe("Verify the founders");
    expect(clip("a b c d e f g h", 6)).toBe("a b c d e f…");
    expect(clip("Done; next", 6)).toBe("Done");
    expect(plural(1, "mission")).toBe("1 mission");
    expect(plural(2, "mission")).toBe("2 missions");
    expect(plural(3, "company", "companies")).toBe("3 companies");
    expect(short("Omar decides. Then the rest.")).toBe("Manager decides");
    expect(short(undefined)).toBe("");
    expect(short("one two three four five", 3)).toBe("one two three…");
    expect(sentence("READY_FOR_OUTREACH")).toBe("Ready for outreach");
    expect(sentence("  ")).toBe("");
  });
});

describe("missions — headline (the regex parsing of the old titles, unchanged)", () => {
  it("an event: the name, the date and the city from 'Decide on X (YYYY-MM-DD, City)'", () => {
    const h = headline(actionOf(today(), "EVENT_ACTION"));
    const day = new Date(2026, 10, 15).toLocaleDateString(undefined, { day: "numeric", month: "short" });
    expect(h).toEqual({ name: "Alpine Deep Tech Summit", reason: `${day} · Zurich` });
    const noCity = headline(variants().actions[4]);
    expect(noCity.name).toBe("Hardware Founders Breakfast");
    expect(noCity.reason).toMatch(/ · —$/);
    // a title that does not match the pattern is not an event headline
    expect(headline(act("EVENT_ACTION", { title: "Decide on Something", subject: "Something", why: "Soon. Really." }))).toEqual({
      name: "Something",
      reason: "Soon",
    });
  });

  it("a prepared case: the company and its human decisions ('(\\d+) human decision')", () => {
    expect(headline(actionOf(today(), "CASE_READY"))).toEqual({ name: "Tessaro Grid", reason: "2 decisions for you" });
    const v = variants().actions;
    expect(headline(v[6])).toEqual({ name: "Ravelin Soil", reason: "1 decision for you" });
    expect(headline(v[2])).toEqual({ name: "Oskarberg Bio", reason: "Case prepared" });
    expect(headline(act("CASE_READY", { title: "Nubis Air — case prepared. Next: open the case." })).name).toBe("Nubis Air");
  });

  it("a Manager decision: 'Ask Manager about' is cut after the role wording; the triage variant is clipped", () => {
    expect(headline(actionOf(today(), "ASK_OMAR_CONFLICT"))).toEqual({
      name: "3 possible portfolio conflict(s)",
      reason: "Manager confirms if investable",
    });
    expect(headline(variants().actions[3])).toEqual({
      name: "1 new candidate(s) touch the Project…",
      reason: "Manager confirms if investable",
    });
  });

  it("the triage review: 'Triage:' is cut and the title clipped at its dash", () => {
    expect(headline(actionOf(today(), "TRIAGE_REVIEW"))).toEqual({ name: "review 10", reason: "Your judgment, not the machine's" });
  });

  it("the retired Scout kinds still read (the Desk shares this file)", () => {
    expect(headline(act("NATIVE_INTEL", { title: "Quillon Bio — new early venture in Germany" }))).toEqual({
      name: "Quillon Bio",
      reason: "new early venture in Germany",
    });
    expect(headline(act("SCOUT00_CYCLE", { title: "Scout 00 · Cycle 007 — 4 signals · 1 update ready" }))).toEqual({
      name: "Scout 00 · Cycle 007",
      reason: "4 signals · 1 update ready",
    });
    expect(headline(act("NATIVE_INTEL", { title: "Bare" })).reason).toBe("New early venture");
  });

  it("everything else: the subject and the first words of why", () => {
    expect(headline(actionOf(today(), "CONTACT_FOUNDER"))).toEqual({
      name: "Halvorsen Robotics",
      reason: "On Radar (high, verified 78), conflict…",
    });
    expect(headline(actionOf(today(), "PREPARE_FOUNDER_CALL")).name).toBe("Ilse Marquardt");
    expect(headline(act("WATCH_TRIGGER", { title: "A very long title with many words in it" })).name).toBe("A very long title with many…");
  });
});

describe("missions — companyOf and mission (the join with the cached pipeline)", () => {
  it("joins by the ?company= slug of the link, else by the subject; nothing for an event or a Manager decision", () => {
    const s = signals();
    expect(companyOf(actionOf(today(), "REVIEW_VERIFICATION"), s)?.slug).toBe("nordvik-materials");
    expect(companyOf(act("WATCH_TRIGGER", { link: "/watchlist", subject: "Mirava Labs" }), s)?.slug).toBe("mirava-labs");
    expect(companyOf(act("X", { link: "/conviction?company=halvorsen%2Drobotics" }), s)?.slug).toBe("halvorsen-robotics");
    expect(companyOf(actionOf(today(), "EVENT_ACTION"), s)).toBeUndefined();
    expect(companyOf(actionOf(today(), "ASK_OMAR_CONFLICT"), s)).toBeUndefined();
  });

  it("a company mission: the one-liner, the why-now, the biggest unknown, the operator state and the verified score", () => {
    const m = mission(actionOf(today(), "CONTACT_FOUNDER"), signals());
    expect({ name: m.name, line: m.line, whyNow: m.whyNow, unknown: m.unknown, state: m.state, score: m.score }).toEqual({
      name: "Halvorsen Robotics",
      line: "Autonomous palletising cells for mid-sized food plants",
      whyNow: "Two plant pilots converted to paid contracts in October; the seed…",
      unknown: "Core facts verified",
      state: "Your move", // a score-band state is not an operator state: the kind's label
      score: 78,
    });
    const c = mission(actionOf(today(), "CASE_READY"), signals());
    expect([c.whyNow, c.unknown, c.state, c.score]).toEqual(["Grid flexibility is a core Project A energy thesis", "Unverified: traction", "Case prepared", 61]);
    const v = mission(actionOf(today(), "REVIEW_VERIFICATION"), signals());
    expect([v.line, v.whyNow, v.unknown, v.state]).toEqual([
      "Low-carbon cement additive from mining tailings",
      "Provisional 71 ≥ 65 — it enters Radar only once verified…",
      "Unverified: founders, traction",
      "Verification",
    ]);
    expect(mission(variants().actions[2], signals()).state).toBe("Awaiting founder");
  });

  it("without a company: the reason is the line, why-now comes from the action, no unknown and no score", () => {
    const t = mission(actionOf(today(), "TRIAGE_REVIEW"), signals());
    expect({ name: t.name, line: t.line, whyNow: t.whyNow, unknown: t.unknown, state: t.state, score: t.score }).toEqual({
      name: "Review 10",
      line: "Your judgment, not the machine's",
      whyNow: "487 machine proposals handled: 3 queued for case preparation, 129 in…",
      unknown: "",
      state: "Signal review",
      score: undefined,
    });
    const o = mission(actionOf(today(), "ASK_OMAR_CONFLICT"), signals());
    expect([o.name, o.line, o.whyNow]).toEqual([
      "3 possible portfolio conflict(s)",
      "Manager confirms if investable",
      "These companies cannot move until Manager / Project A confirms whether…",
    ]);
    // a prepared case the pipeline does not hold says what changed (never the "Recommended next action" move)
    expect(mission(actionOf(today(), "CASE_READY"), []).whyNow).toBe("Case prepared — 2 decisions for you");
    expect(mission(actionOf(today(), "PREPARE_FOUNDER_CALL"), signals()).whyNow).toBe(
      "Founder-call next action is overdue: Send the pilot pricing sheet and…",
    );
  });
});

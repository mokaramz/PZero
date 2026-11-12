import { describe, expect, it } from "vitest";

import { panel, sessionRow, sessions } from "../test/server";
import {
  askedQuestions,
  awaitingStaged,
  claimActions,
  countsLine,
  existingEvidence,
  groupOf,
  isUnknownAnswer,
  movementLine,
  openContradictions,
  questionTone,
  rowLine,
  startFromParams,
  startSubject,
  stateTone,
  withoutStart,
} from "./view";

const [linked, ended, external] = sessions();

describe("Active Evaluator — the ?start=1 entry", () => {
  it("reads the prefill only with start=1; a slug links it to Conviction", () => {
    expect(startFromParams(new URLSearchParams("slug=kestrel-labs"))).toBeNull();
    expect(startFromParams(new URLSearchParams("start=1&slug=kestrel-labs&name=Kestrel%20Labs&founder=Ada%20Quill"))).toEqual({
      slug: "kestrel-labs",
      name: "Kestrel Labs",
      founder: "Ada Quill",
    });
    expect(startFromParams(new URLSearchParams("start=1&name=Otter"))).toEqual({ name: "Otter", founder: "" });
  });

  it("drops the entry keys and keeps the rest", () => {
    expect(withoutStart(new URLSearchParams("start=1&slug=a&name=b&founder=c&session=ev-1")).toString()).toBe("session=ev-1");
  });

  it("builds the old start subject: company with a slug, external without", () => {
    expect(startSubject({ slug: "kestrel-labs" }, { name: "Kestrel Labs", founder: "Ada Quill" })).toEqual({
      kind: "company",
      slug: "kestrel-labs",
      name: "Kestrel Labs",
      founder: "Ada Quill",
    });
    expect(startSubject({}, { name: "Otter", founder: "" })).toEqual({ kind: "external", name: "Otter", founder: "" });
  });
});

describe("Active Evaluator — view rules", () => {
  it("tones: sourced / verified green, contradiction red, UNKNOWN grey, the rest amber; challenge amber, unknown grey, else blue", () => {
    expect(["PUBLIC SOURCED FACT", "OPERATOR VERIFIED", "CONTRADICTION", "UNKNOWN", "DECK CLAIM", "FOUNDER-REPORTED"].map(stateTone)).toEqual([
      "green",
      "green",
      "red",
      "neutral",
      "amber",
      "amber",
    ]);
    expect(["challenge", "unknown", "opening", "followup"].map(questionTone)).toEqual(["amber", "neutral", "blue", "blue"]);
  });

  it("the counts line and a strip row", () => {
    const rows = sessions().map(sessionRow);
    expect(countsLine(rows)).toBe("3 evaluations · 2 live · 1 ended");
    expect(countsLine(rows.slice(0, 1))).toBe("1 evaluation · 1 live · 0 ended");
    expect(rowLine(sessionRow(linked))).toBe("Ada Quill · 1 answers · 5 ledger items (1 founder-reported · 1 deck)");
    expect(rowLine({ ...sessionRow(external), unknowns: 2 })).toBe(" · 0 answers · 0 ledger items (0 founder-reported · 0 deck · 2 UNKNOWN)");
  });

  it("an UNKNOWN answer is 'unknown' or 'don't know' at the start", () => {
    expect(["unknown", "  Unknown yet", "don't know", "dont know", "I don't know", "", null].map(isUnknownAnswer)).toEqual([
      true,
      true,
      true,
      true,
      false,
      false,
      false,
    ]);
  });

  it("the existing-evidence line of a linked and an unlinked session", () => {
    expect(existingEvidence(linked.context)).toBe("Provisional 66 · Verified 40 · verified flags: founders true, traction false, funding false · conflict: none");
    expect(existingEvidence({ slug: "x" })).toBe("Provisional — · Verified — · verified flags: founders false, traction false, funding false · conflict: none");
    expect(existingEvidence(external.context)).toBe("not linked to a Conviction company");
  });

  it("claim actions: verify for deck and founder claims, resolve for an open contradiction of a live session, the note once resolved", () => {
    expect(linked.ledger.map((c) => claimActions(c, false))).toEqual(["verify", "verify", "resolve", "resolved", null]);
    expect(claimActions(linked.ledger[2], true)).toBeNull();
  });

  it("the derived lists: asked questions, open contradictions, staged evidence awaiting the operator", () => {
    expect(askedQuestions(linked).map((q) => q.id)).toEqual(["q-1"]);
    expect(openContradictions(linked.ledger).map((c) => c.id)).toEqual(["c-3"]);
    expect(awaitingStaged(linked).map((x) => x.job_id)).toEqual(["job-9"]);
    expect(awaitingStaged(ended)).toEqual([]);
  });

  it("a movement line and a group with its non-zero states", () => {
    expect(movementLine({ dimension: "Founder", current: 15, verified_flag: true, provisional_direction: "up" })).toBe("Founder (15 ✓): up");
    expect(movementLine({ dimension: "Why now", current: null, verified_flag: false, provisional_direction: "→" })).toBe("Why now (— unverified): →");
    expect(movementLine({ dimension: "Taste", current: 10, verified_flag: null, provisional_direction: "→" })).toBe("Taste (10): →");
    const p = panel(linked);
    expect(groupOf(p, "traction")).toMatchObject({ claims: 2, states: [["DECK CLAIM", 1], ["CONTRADICTION", 1]] });
    expect(groupOf({ ...p, groups: {} }, "founder")).toEqual({ claims: 0, states: [], covered: false });
  });
});

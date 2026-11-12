import { describe, expect, it } from "vitest";

import { packet } from "../test/fixtures";
import {
  asksDatabase,
  AUDIT_FORM,
  auditBody,
  auditReady,
  auditTitle,
  benchmarkReady,
  importedMessage,
  importLabel,
  markBody,
  needsEvidence,
  OUTCOME_FORM,
  outcomeReady,
  packetGenerated,
  previewLine,
  REAL_WORLD,
  retractReason,
  toggleCause,
  type BenchmarkSummary,
} from "./writes";

describe("Validation writes — the outcome form", () => {
  it("starts on an institutional round, with the old fields only", () => {
    expect(OUTCOME_FORM).toEqual({ company: "", kind: "institutional_round", event_date: "", evidence_url: "", benchmark_system: "", note: "" });
    for (const k of ["candidate_id", "supersedes", "outcome_date"]) expect(OUTCOME_FORM).not.toHaveProperty(k);
  });

  it("real-world outcomes need evidence; the rest do not", () => {
    expect(REAL_WORLD).toEqual(["institutional_round", "commercial_milestone", "acquisition", "project_a_invested"]);
    for (const k of REAL_WORLD) expect(needsEvidence(k)).toBe(true);
    for (const k of ["external_db_listing", "accelerator", "shutdown", ""]) expect(needsEvidence(k)).toBe(false);
  });

  it("Save needs a company, a date and, for a real-world outcome, an http(s) URL", () => {
    const f = { ...OUTCOME_FORM, company: "Kestrel Labs", event_date: "2026-09-01" };
    expect(outcomeReady(OUTCOME_FORM)).toBe(false);
    expect(outcomeReady(f)).toBe(false); // institutional round without evidence
    expect(outcomeReady({ ...f, evidence_url: "news.example/round" })).toBe(false);
    expect(outcomeReady({ ...f, evidence_url: "ftp://news.example/round" })).toBe(false);
    expect(outcomeReady({ ...f, evidence_url: "https://news.example/round" })).toBe(true);
    expect(outcomeReady({ ...f, evidence_url: "http://news.example/round" })).toBe(true);
    expect(outcomeReady({ ...f, kind: "external_db_listing" })).toBe(true);
    expect(outcomeReady({ ...f, kind: "external_db_listing", company: "" })).toBe(false);
    expect(outcomeReady({ ...f, kind: "external_db_listing", event_date: "" })).toBe(false);
  });

  it("'Which database' is asked only for an external-database listing", () => {
    expect(asksDatabase("external_db_listing")).toBe(true);
    expect(asksDatabase("institutional_round")).toBe(false);
  });
});

describe("Validation writes — the audits", () => {
  it("the form starts with the old defaults", () => {
    expect(AUDIT_FORM).toMatchObject({ why_missed: "source_not_covered", preventable: "unclear", causes: [] });
  });

  it("a miss needs a company; a false positive also needs a cause", () => {
    expect(auditReady("miss", AUDIT_FORM)).toBe(false);
    expect(auditReady("miss", { ...AUDIT_FORM, company: "Orbelle Health" })).toBe(true);
    expect(auditReady("false_positive", { ...AUDIT_FORM, company: "Graniteleaf Labs" })).toBe(false);
    expect(auditReady("false_positive", { ...AUDIT_FORM, company: "Graniteleaf Labs", causes: ["weak_source"] })).toBe(true);
  });

  it("the body is the whole form plus its type", () => {
    expect(auditBody("miss", { ...AUDIT_FORM, company: "Orbelle Health" })).toEqual({ ...AUDIT_FORM, company: "Orbelle Health", type: "miss" });
  });

  it("causes are ticked in order and unticked", () => {
    expect(toggleCause(["a"], "b", true)).toEqual(["a", "b"]);
    expect(toggleCause(["a", "b"], "a", false)).toEqual(["b"]);
  });

  it("titles", () => {
    expect(auditTitle("miss")).toBe("Miss audit — a strong company we did not catch early");
    expect(auditTitle("false_positive")).toBe("False-positive audit — prioritised but proved weak");
  });
});

describe("Validation writes — the retraction", () => {
  it("posts only a reason of 8+ characters (trimmed), sent as typed", () => {
    expect(retractReason(null)).toBeNull();
    expect(retractReason("")).toBeNull();
    expect(retractReason("too shrt")).toBe("too shrt");
    expect(retractReason("  short  ")).toBeNull();
    expect(retractReason("  wrong company  ")).toBe("  wrong company  ");
  });
});

describe("Validation writes — the benchmark import", () => {
  const p: BenchmarkSummary = { system: "Dealroom", rows: 2, usable: 1, skipped: 1, matched_to_pz: 0, name_column: "Name", date_column: "Date added", imported: false };

  it("Preview needs a system and 10+ characters of CSV", () => {
    expect(benchmarkReady({ system: "", csv: "Name,Date added\n" })).toBe(false);
    expect(benchmarkReady({ system: "Dealroom", csv: "Name,Date" })).toBe(false);
    expect(benchmarkReady({ system: "Dealroom", csv: "Name,Dates" })).toBe(true);
  });

  it("the old preview line, button and toast", () => {
    expect(previewLine(p)).toBe("2 rows · 1 usable · 1 skipped (no / future date) · 0 known to Project Zero · columns “Name” / “Date added”");
    expect(importLabel(p)).toBe("Import 1 dates");
    expect(importedMessage({ ...p, imported: true })).toBe("1 benchmark date(s) imported");
  });
});

describe("Validation writes — the packet mark (decision f)", () => {
  it("reads the Generated time from the packet text", () => {
    expect(packetGenerated(packet().text)).toBe("2026-11-12T09:15:00");
    expect(packetGenerated("PROJECT ZERO\nGenerated 2026-11-12 09:15 · cycle all")).toBeNull();
    expect(packetGenerated("no header")).toBeNull();
  });

  it("marks the packet shown: its cycle ('' for all), Generated time and sha", () => {
    expect(markBody(packet())).toEqual({ cycle: "c-2026-10-16", generated: "2026-11-12T09:15:00", sha: "5d1c0e9a7b3f2468" });
    expect(markBody({ ...packet(), cycle: "all" })).toEqual({ cycle: "", generated: "2026-11-12T09:15:00", sha: "5d1c0e9a7b3f2468" });
    expect(markBody({ ...packet(), text: "PROJECT ZERO → CHIEF SCOUT 00\n" })).toBeNull();
  });
});

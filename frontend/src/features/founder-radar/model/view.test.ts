import { describe, expect, it } from "vitest";

import { ID, KELPWISE, kelpwise, radar } from "../test/fixtures";
import { initialValues, missingRequired, sv, visibleFields } from "./ask";
import {
  COMPANY_FACT,
  NOTE_ASKS,
  PERSON_EVIDENCE,
  companyEvidenceBody,
  companyFactBody,
  confirmIdentityExtra,
  confirmIdentitySpec,
  linkedinVerifiedExtra,
  noteExtra,
  pairSpec,
  personEvidenceExtra,
  verifyIdentityExtra,
} from "./dialogs";
import { NO_FILTERS } from "./logic";
import {
  callLink,
  chosenBindings,
  countsLine,
  domainTag,
  importToast,
  initialSeg,
  leadAccessText,
  metricRows,
  priorityFactorsLine,
  recommendedPending,
  researchList,
  reviewToast,
  scoutReviewLink,
  storedBindings,
  viewOf,
  withView,
} from "./view";

const d = radar();
const qs = (s: string) => new URLSearchParams(s);

describe("the URL", () => {
  it("?view= falls back to Top Founder Leads; ?seg= else claim for the Research Queue, gold elsewhere", () => {
    expect(viewOf(qs(""))).toBe("top");
    expect(viewOf(qs("view=diag"))).toBe("diag");
    expect(viewOf(qs("view=nope"))).toBe("top");
    expect(initialSeg(qs("view=research"), "research")).toBe("claim");
    expect(initialSeg(qs(""), "top")).toBe("gold");
    expect(initialSeg(qs("seg=insuf"), "research")).toBe("insuf");
  });

  it("switching views keeps the other keys; Top drops `view`", () => {
    expect(withView(qs("view=diag&review=k"), "top").toString()).toBe("review=k");
    expect(withView(qs("seg=insuf"), "research").toString()).toBe("seg=insuf&view=research");
  });
});

describe("counts and lists", () => {
  it("the bucket counts line, and the company-queue line in the claim segment", () => {
    expect(countsLine(d, "gold", "")).toBe(
      "0 deserve attention first (Gold + Strong) · 6 founder claims unresolved · 1 research & spinout talent · 2 insufficient · 1 watchlisted · 1 in Network",
    );
    expect(countsLine(d, "claim", "")).toBe("Company leads 4 · claimed founders 6 · separately: 6 people currently in Founder claim bucket");
  });

  it("without server counts the claim line counts the matching companies", () => {
    const x = { ...d, queue_counts: {} };
    expect(countsLine(x, "claim", "borealis")).toBe("Company leads 1 · claimed founders 2 · separately: — people currently in Founder claim bucket");
  });

  it("researchList: the segment, or every bucket while searching, ordered and capped", () => {
    expect(researchList(d, "insuf", NO_FILTERS, "").list.map((p) => p.id)).toEqual([ID.oskar, ID.petra]);
    expect(researchList(d, "gold", NO_FILTERS, "sana okafor").list.map((p) => p.id)).toEqual([ID.sana]);
    expect(researchList(d, "gold", NO_FILTERS, "hana sato").list).toEqual([]); // kept out of the radar
    const many = { ...d, people: Array.from({ length: 25 }, (_, i) => ({ id: `g${i}`, name: `G${i}`, signal: { bucket: "Gold now" } })) };
    expect(researchList(many, "gold", NO_FILTERS, "")).toMatchObject({ hidden: 5 });
    expect(researchList(many, "gold", NO_FILTERS, "").list).toHaveLength(20);
  });

  it("metricRows: every metric but the date, null as —", () => {
    const rows = metricRows(d.metrics);
    expect(rows[0]).toEqual({ key: "gold_now", value: "0", label: "gold now" });
    expect(rows.at(-1)).toEqual({ key: "watchlist_to_network_conversion", value: "—", label: "watchlist to network conversion" });
    expect(rows.some((r) => r.key === "date")).toBe(false);
  });
});

describe("links and card text", () => {
  it("Log founder call → Founder Calls' new-call form with the person, company and radar key", () => {
    expect(callLink({ person_id: ID.mira, name: "Mira Talvik", company: "Kelpwise GmbH", radar_key: KELPWISE })).toBe(
      "/founder-calls?new=1&person_id=p-mira-talvik-1001&name=Mira+Talvik&company=Kelpwise+GmbH&radar_key=dom%3Akelpwise.example",
    );
    expect(callLink({ person_id: ID.oskar, name: "Oskar Lindqvist" })).toBe("/founder-calls?new=1&person_id=p-oskar-lindqvist-1007&name=Oskar+Lindqvist&company=&radar_key=");
  });

  it("the Scout Packet link keeps the old Scout Intake address (the app redirects it)", () => {
    expect(scoutReviewLink("si quill/7")).toBe("/scout-intake?item=si%20quill%2F7&review=identity&from=founders");
  });

  it("access text, domain badge and priority factors", () => {
    expect(leadAccessText({ access: "none", access_label: "x" })).toBe("no access path recorded");
    expect(leadAccessText({ access: "warm", access_label: "Warm path: introduced by Nils Farrow" })).toBe("warm — introduced by Nils Farrow");
    expect(leadAccessText({ access: "cold" })).toBe("cold");
    expect(domainTag({ domain: "a.example", domain_source: "pipeline website" })).toBeNull();
    expect(domainTag({ domain: "UNKNOWN", domain_source: "no official domain found" })).toBe("domain UNKNOWN");
    expect(domainTag({ domain: "a.example", domain_source: "candidate domain (search)" })).toBe("candidate domain");
    expect(domainTag({ domain: "a.example", domain_source: "operator" })).toBe("confirmed domain");
    expect(priorityFactorsLine(d.companies![3])).toBe("no official domain -1 · founder identity completeness 0/1 +0 · total 1");
  });
});

describe("the review drawer", () => {
  const k = kelpwise();
  it("the bulk confirm sends the recommended rows still pending, never a founder", () => {
    expect(recommendedPending(k.groups, k.recommended)).toEqual(["pr-k-founded", "pr-k-funding", "pr-k-status", "pr-k-recent"]);
    const decided = k.groups.map((g) => (g.best.id === "pr-k-funding" ? { ...g, best: { ...g.best, status: "confirmed" } } : g));
    expect(recommendedPending(decided, k.recommended)).toEqual(["pr-k-founded", "pr-k-status", "pr-k-recent"]);
    expect(recommendedPending(k.groups, [...k.recommended, "pr-k-f-mira"])).toContain("pr-k-f-mira"); // only what the server recommends
  });

  it("bindings start from the stored ones; only chosen ones are sent", () => {
    const bound = k.groups.map((g) => (g.best.id === "pr-k-f-mira" ? { ...g, best: { ...g.best, bound_person: ID.mira } } : g));
    expect(storedBindings(bound)).toEqual({ "pr-k-f-mira": ID.mira });
    expect(chosenBindings({ a: "", b: ID.jonas })).toEqual({ b: ID.jonas });
  });

  it("the review toast lists facts, bound identities, pending, conflicts and refusals", () => {
    expect(reviewToast("confirm", { ok: true, facts: ["founded"], identity_bound: [{ name: "Mira Talvik" }], still_pending: ["x"], conflicts: [1, 2], refused: ["y"] })).toBe(
      "Confirmed · facts: founded · identity: Mira Talvik ✓ · still pending: 1 · conflicts: 2 · refused: y",
    );
    expect(reviewToast("reject", { ok: true })).toBe("Rejected · facts: none");
  });

  it("the pairing confirmation names the proposal and the record with its aliases", () => {
    const s = pairSpec("Jonas Brekke", ID.jonas, { name: "Jonas Brekke", aliases: ["jbrekke"] });
    expect(s.confirm!({})).toBe(
      "Pair proposed human name\n  Jonas Brekke\nwith record\n  Jonas Brekke (p-jonas-brekke-1002 · aliases: jbrekke)\n\nThis records the pairing with your provenance; identity is confirmed only when you then press Confirm selected.",
    );
    expect(pairSpec("X", "p-gone", undefined).confirm!({})).toContain("\n  p-gone (p-gone)\n");
  });
});

describe("the old POST bodies", () => {
  it("one-line notes go to their own key", () => {
    expect(noteExtra(NOTE_ASKS.dismiss, { x: "not a founder" })).toEqual({ note: "not a founder" });
    expect(noteExtra(NOTE_ASKS.introPath, { x: "Nils → Ilka" })).toEqual({ route: "Nils → Ilka" });
    expect(noteExtra(NOTE_ASKS.opportunity, { x: "Kelp buoys" })).toEqual({ name: "Kelp buoys" });
  });

  it("LinkedIn manual verification", () => {
    expect(linkedinVerifiedExtra("https://www.linkedin.com/in/x", { fact: "Co-founder at Y", founder: true })).toEqual({
      url: "https://www.linkedin.com/in/x",
      verified: true,
      founder: true,
      fact: "Co-founder at Y",
      note: "Co-founder at Y",
      confirm: true,
    });
  });

  it("person evidence: the activity date only for trajectory", () => {
    expect(personEvidenceExtra({ url: "https://u", label: "L", claim: "C", kind: "builder", activity_date: "2026-11-01" })).toEqual({
      url: "https://u",
      label: "L",
      claim: "C",
      kind: "builder",
      activity_date: undefined,
    });
    expect(personEvidenceExtra({ url: "https://u", label: "", claim: "", kind: "trajectory", activity_date: "2026-11-01" })).toMatchObject({ activity_date: "2026-11-01" });
    expect(personEvidenceExtra({ url: "https://u", kind: "" })).toMatchObject({ kind: "operator" });
    expect(visibleFields(PERSON_EVIDENCE.fields, initialValues(PERSON_EVIDENCE.fields)).map((x) => x.name)).toEqual(["url", "label", "claim", "kind"]);
  });

  it("confirm identity: prefilled from the proposed identity, a default fact", () => {
    const grain = d.people.find((p) => p.id === ID.grain)!;
    const spec = confirmIdentitySpec(grain);
    const v = initialValues(spec.fields);
    expect(v).toEqual({ name: "Gideon Rask", handle: "grainhacker", company: "Grainline Labs", url: "https://grainline.example/about", label: "Grainline Labs about", fact: "" });
    expect(spec.confirm!(v)).toBe("Confirm: Gideon Rask (grainhacker) is co-founder of Grainline Labs\nSource: Grainline Labs about https://grainline.example/about");
    expect(confirmIdentityExtra(v)).toEqual({
      name: "Gideon Rask",
      handle: "grainhacker",
      company: "Grainline Labs",
      url: "https://grainline.example/about",
      label: "Grainline Labs about",
      fact: "Gideon Rask (grainhacker) is co-founder of Grainline Labs",
      confirm: true,
    });
    expect(verifyIdentityExtra({ url: "https://u", label: "L", fact: "F" })).toEqual({ url: "https://u", label: "L", fact: "F", confirm: true });
  });

  it("company evidence and a sourced fact (the activity date only for recent_activity)", () => {
    expect(companyEvidenceBody(KELPWISE, { url: "https://u", label: "L", claim: "C" })).toEqual({ key: KELPWISE, evidence: { url: "https://u", label: "L", claim: "C" } });
    const v = { field: "recent_activity", value: "pre-seed round", url: "https://kelpwise.example/news", label: "news", claim: "announced", activity_date: "2026-11-04" };
    expect(companyFactBody(KELPWISE, v)).toEqual({ key: KELPWISE, fact: { ...v, confirm: true } });
    expect(companyFactBody(KELPWISE, { ...v, field: "founded" }).fact.activity_date).toBeUndefined();
    expect(COMPANY_FACT.confirm!(v)).toBe('Confirm sourced fact:\nrecent_activity = pre-seed round · activity date 2026-11-04\n"announced"\nnews · https://kelpwise.example/news');
  });

  it("the dialog's required fields and string values", () => {
    expect(missingRequired(COMPANY_FACT.fields, { field: "founded", value: "2025", url: " " })).toBe(true);
    expect(missingRequired(COMPANY_FACT.fields, { field: "founded", value: "2025", url: "https://u" })).toBe(false);
    expect(sv({ a: true }, "a")).toBe("");
  });

  it("the import toast", () => {
    expect(importToast({ ok: true, format: "linkedin_connections", new: 3, merged: 0, skipped: [], note: "nothing verified" })).toBe(
      "LinkedIn Connections export: 3 new · 0 merged — nothing verified",
    );
    expect(importToast({ ok: true, format: "custom", new: 1, merged: 2, skipped: [{}, {}] })).toBe("custom CSV: 1 new · 2 merged · 2 skipped — ");
  });
});

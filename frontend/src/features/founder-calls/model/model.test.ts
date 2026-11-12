import { describe, expect, it } from "vitest";

import { companies, workspace } from "../test/server";
import {
  briefingFile,
  ctxFromParams,
  dueRows,
  filterRows,
  initialAnswers,
  initialFields,
  memoFile,
  personRows,
  pipelineRows,
  saveBody,
  slugName,
  withoutCtx,
} from "./calls";

describe("Founder Calls — the context keys", () => {
  it("?log=1 or ?new=1 opens the form with the known keys only; anything else does not", () => {
    expect(ctxFromParams(new URLSearchParams("log=1&name=Eve&company=Wren&person_id=p-1&other=x&radar_key="))).toEqual({ name: "Eve", company: "Wren", person_id: "p-1" });
    expect(ctxFromParams(new URLSearchParams("new=1&pipeline_slug=wren&discovery_origin=scan&call_type=followup"))).toEqual({
      pipeline_slug: "wren",
      discovery_origin: "scan",
      call_type: "followup",
    });
    expect(ctxFromParams(new URLSearchParams("log=0&name=Eve"))).toBeNull();
    expect(ctxFromParams(new URLSearchParams("call=call-1"))).toBeNull();
  });

  it("drops the entry keys and keeps the rest", () => {
    expect(withoutCtx(new URLSearchParams("log=1&new=1&name=Eve&founder_id=f&company_id=c&call=call-1&x=y")).toString()).toBe("call=call-1&x=y");
  });
});

describe("Founder Calls — the due box and the files", () => {
  it("shows overdue, due and upcoming only", () => {
    expect(dueRows(workspace(companies())).map((c) => [c.id, c.due_state])).toEqual([
      ["call-1", "overdue"],
      ["call-4", "due"],
      ["call-3", "upcoming"],
    ]);
  });

  it("names the memo and briefing files like before", () => {
    expect(slugName("Zoë O'Neil", "founder")).toBe("zo-o-neil");
    expect(slugName("", "founder")).toBe("founder");
    const c = workspace(companies()).calls[0];
    expect(memoFile(c)).toBe("call-memo-ada-quill-2026-11-02.md");
    expect(memoFile(undefined)).toBe("call-memo-founder-.md");
    expect(briefingFile("Ada Quill")).toBe("omar-briefing-ada-quill.md");
  });
});

describe("Founder Calls — the form", () => {
  it("a new call from a context: names from the context, today's date, Mohamed and the founder as participants", () => {
    const fc = workspace(companies());
    const f = initialFields(fc, { name: "Eve", company: "Wren", call_type: "followup" });
    expect(f).toMatchObject({ founder: "Eve", company: "Wren", call_type: "followup", date: "2026-11-12", channel: "video", participants: "Mohamed, Eve", na_owner: "Mohamed" });
    expect(initialFields({ ...fc, today: "" }, {}, "2030-01-01")).toMatchObject({ founder: "", date: "2030-01-01", participants: "Mohamed", call_type: "first" });
  });

  it("an edit round-trips: the body of an untouched call carries its stored values", () => {
    const fc = workspace(companies());
    const ctx = { call_id: "call-1" };
    const c = fc.calls[0];
    const body = saveBody(fc, ctx, initialFields(fc, ctx), initialAnswers(c), { ...c.assessment });
    expect(body).toMatchObject({
      id: "call-1",
      founder_id: "f-ada",
      company_id: "co-kestrel",
      time: "10:30",
      claims: "Three paid pilots",
      answers: c.answers,
      assessment: c.assessment,
      next_action: { text: "Send the deck to Robin", owner: "Mohamed", due: "2026-11-10" },
    });
  });

  it("only the current template's answers go out; an answered section is never UNKNOWN on load", () => {
    const fc = workspace(companies());
    const ctx = { founder_id: "f-cleo", company_id: "co-otter" };
    const f = { ...initialFields(fc, ctx), call_type: "followup" };
    const body = saveBody(fc, ctx, f, { why: { a: "stale", unknown: false, followups: {} }, metrics: { a: " 10k MRR ", unknown: false, followups: { 0: " ", 1: "x" } } }, {});
    expect(body.answers).toEqual({ metrics: { a: "10k MRR", unknown: false, followups: {} } });
    expect(body).toMatchObject({ founder_id: "f-cleo", company_id: "co-otter", founder: "Cleo Marsh", company: "Otter Mill" });
    expect(initialAnswers({ ...fc.calls[0], answers: { why: { a: "yes", unknown: true, followups: {} } } })).toEqual({ why: { a: "yes", unknown: false, followups: {} } });
  });
});

describe("Founder Calls — the pickers", () => {
  it("people and Conviction rows, filtered on label and sub-line", () => {
    const fc = workspace(companies());
    expect(personRows(fc)).toEqual([
      { id: "p-ben", label: "Benjamin Rook", sub: "Otter Mill · CEO" },
      { id: "p-gus", label: "Gus Fernley", sub: "Fernley Tools" },
    ]);
    expect(pipelineRows(fc)[0]).toEqual({ id: "otter-mill", label: "Otter Mill GmbH", sub: "Benjamin Rook, Cleo Marsh" });
    expect(filterRows(personRows(fc), "CEO").map((r) => r.id)).toEqual(["p-ben"]);
  });
});

import { describe, expect, it } from "vitest";

import {
  auditMissBody,
  CONFIRM_TEXT,
  familyLabel,
  LABEL,
  outcomeBody,
  SIGNAL_FORM,
  SIGNAL_HELP,
  SIGNAL_KINDS,
  signalBody,
  signalReady,
  SUCCESS,
  writesValidation,
} from "./writes";

describe("the outcome proposal", () => {
  it("posts the event and the decision, nothing else", () => {
    expect(outcomeBody("nw-3f9a1c0b7d2e", "confirm")).toEqual({
      event_id: "nw-3f9a1c0b7d2e",
      decision: "confirm",
    });
    expect(Object.keys(outcomeBody("nw-3f9a1c0b7d2e", "not_enough"))).toEqual(["event_id", "decision"]);
  });
  it("only a confirm writes a Validation row", () => {
    expect(writesValidation("confirm")).toBe(true);
    expect(writesValidation("reject")).toBe(false);
    expect(writesValidation("not_enough")).toBe(false);
  });
  it("asks before confirming, in the old words", () => {
    expect(CONFIRM_TEXT).toBe("records a verified outcome in Validation");
  });
});

describe("the miss audit", () => {
  it("posts the event alone (the server prefills the rest)", () => {
    expect(auditMissBody("nw-1e8b5a6c4d90")).toEqual({
      event_id: "nw-1e8b5a6c4d90",
    });
  });
});

describe("the early signal", () => {
  it("starts with the old defaults", () => {
    expect(SIGNAL_FORM).toEqual({
      date: "",
      text: "",
      url: "",
      family: "university_lab",
      kind: "known_early_signal",
    });
  });
  it("needs a date and a URL starting with http (the server checks the rest)", () => {
    const f = { ...SIGNAL_FORM };
    expect(signalReady(f)).toBe(false);
    expect(signalReady({ ...f, date: "2021-06" })).toBe(false);
    expect(signalReady({ ...f, url: "https://lab.example/spinout" })).toBe(false);
    expect(signalReady({ ...f, date: "2021-06", url: "lab.example/spinout" })).toBe(false);
    expect(signalReady({ ...f, date: "2021-06", url: "ftp://lab.example" })).toBe(false);
    expect(
      signalReady({
        ...f,
        date: "2021-06",
        url: "https://lab.example/spinout",
      }),
    ).toBe(true);
    expect(signalReady({ ...f, date: "2021", url: "http://lab.example" })).toBe(true);
    expect(signalReady({ ...f, date: "June 2021", url: "httpx" })).toBe(true); // as before: the server refuses it with its own text
  });
  it("posts the form as typed, then the event, in the old key order", () => {
    const body = signalBody(
      {
        date: "2021-06",
        text: "Lab page",
        url: "https://lab.example",
        family: "github",
        kind: "in_retrospect",
      },
      "nw-case-halvard-unicorn-2026-10",
    );
    expect(body).toEqual({
      date: "2021-06",
      text: "Lab page",
      url: "https://lab.example",
      family: "github",
      kind: "in_retrospect",
      event_id: "nw-case-halvard-unicorn-2026-10",
    });
    expect(Object.keys(body)).toEqual(["date", "text", "url", "family", "kind", "event_id"]);
  });
  it("labels the families and the two kinds as before", () => {
    expect(familyLabel("university_lab")).toBe("university lab");
    expect(familyLabel("early_funding")).toBe("early funding");
    expect(familyLabel("grant")).toBe("grant");
    expect(SIGNAL_KINDS).toEqual([
      { value: "known_early_signal", label: "Yes — a known early signal" },
      { value: "in_retrospect", label: "No — only clear in retrospect" },
    ]);
    expect(SIGNAL_HELP).toMatch(/^A public signal that existed BEFORE the story, with its source\./);
  });
});

describe("the old toasts and activity labels", () => {
  it("are unchanged", () => {
    expect(SUCCESS).toEqual({
      outcome: "Recorded",
      audit: "Miss audit created in Validation (prefilled)",
      signal: "Signal added to the backcast",
    });
    expect(LABEL).toEqual({
      outcome: "Recording the outcome",
      audit: "Creating the miss audit",
      signal: "Adding the early signal",
    });
  });
});

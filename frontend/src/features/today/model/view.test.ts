import { describe, expect, it } from "vitest";

import { board, exceptionsLine, flowLabel, footerLine, HANDLED, heroDate, machineLine, NOTHING, reviewCount, snapshotLine, stamp } from "./view";
import { emptyDay, pipeline, today, variants } from "../test/fixtures";

const NOTE = "Triage routes and prepared cases are the imported snapshot until their runs are ported";

describe("Today — the page logic", () => {
  it("the hero date: weekday, day, month and time, en-GB", () => {
    expect(heroDate(new Date(2026, 10, 13, 9, 5))).toBe("Friday, 13 Nov · 09:05");
  });

  it("the board: missions (companies and signals), Manager decisions and events, in the server's order", () => {
    const b = board(today(), pipeline().signals, "all");
    expect(b.signals).toHaveLength(9); // the dropped company is not counted
    expect(b.missions.map((m) => m.a.type)).toEqual(["CONTACT_FOUNDER", "PREPARE_FOUNDER_CALL", "CASE_READY", "REVIEW_VERIFICATION", "TRIAGE_REVIEW"]);
    expect(b.manager.map((m) => m.a.type)).toEqual(["ASK_OMAR_CONFLICT"]);
    expect(b.events.map((m) => m.a.type)).toEqual(["EVENT_ACTION"]);
    expect(b.nCompany).toBe(4);
    expect(b.shown).toHaveLength(5);
    expect(b.brief).toBe("5 priority missions · 1 Manager decision due · 1 event decision");
    expect(b.top?.name).toBe("Halvorsen Robotics");
    expect(board(today(), pipeline().signals, "signal").shown.map((m) => m.a.type)).toEqual(["TRIAGE_REVIEW"]);
    expect(board(today(), pipeline().signals, "company").shown).toHaveLength(4);
  });

  it("the board before the pipeline arrives, and on a quiet day", () => {
    const b = board(today(), undefined, "all");
    expect(b.signals).toEqual([]);
    expect(b.missions[0].score).toBeUndefined();
    const quiet = board(emptyDay(), pipeline().signals, "all");
    expect([quiet.missions, quiet.events, quiet.manager, quiet.top, quiet.brief]).toEqual([[], [], [], undefined, NOTHING]);
    const onlyEvents = emptyDay();
    onlyEvents.actions = [today().actions[5]];
    expect(board(onlyEvents, [], "all")).toMatchObject({ brief: "1 event decision", top: { name: "Alpine Deep Tech Summit" } });
  });

  it("the flow graphic's name", () => {
    expect(flowLabel(5, 2, 487)).toBe("Today's flow: 487 signals handled by the machine → 5 missions for review → 2 decisions due");
    expect(flowLabel(0, 0)).toBe("Today's flow: 0 missions for review → 0 decisions due");
  });

  it("the Machine line and the review count, with and without a compression run", () => {
    const t = today().triage;
    expect(machineLine(t)).toBe("487 handled · 129 researching · 331 watching");
    expect(machineLine(null)).toBe("working");
    expect(machineLine({ ...t!, counts: {} })).toBe("487 handled · 0 researching · 0 watching");
    expect(reviewCount(t)).toBe(10); // 14 + 5, capped by the budget of 10
    expect(reviewCount({ ...t!, needs_mohamed: 0, calibration: 5 })).toBe(5);
    expect(reviewCount(null)).toBe(0);
  });

  it("the exceptions in role wording — and the old '… for Omars' as it stands (decision h)", () => {
    expect(exceptionsLine(today())).toBe(
      "1 company needs your judgment · 2 founder calls worth preparing · 5 possible portfolio conflicts for Manager · 2 events worth deciding on · 10 machine proposals need your judgment",
    );
    expect(exceptionsLine(variants())).toBe(
      "1 company needs your judgment · 1 founder call worth preparing · 1 possible portfolio conflict for Omars · 1 Watch trigger materially changed · 1 event worth deciding on",
    );
    expect(exceptionsLine(emptyDay())).toBe(HANDLED);
    const none = emptyDay();
    delete none.exceptions;
    expect(exceptionsLine(none)).toBe(HANDLED);
  });

  it("the footer lists only the sections the server considered, a failed one included", () => {
    expect(footerLine(today())).toBe(
      "3 lower-priority action(s) not shown. Deterministic ranking over existing state; nothing is sent, registered, scored or forwarded. Sources considered: pipeline 4 · calls 1 · events 2 · triage 2 · watch 1 · cases 1.",
    );
    expect(footerLine(variants())).toBe(
      "Deterministic ranking over existing state; nothing is sent, registered, scored or forwarded. Sources considered: pipeline 1 · calls temporarily unavailable — the rest of Today is complete · events 1 · triage 1 · watch 2 · cases 2.",
    );
    expect(footerLine(variants())).not.toMatch(/native|scout00/);
  });

  it("the snapshot note with the original run timestamps, or nothing (decision f)", () => {
    expect(stamp("2026-11-12T23:05:10")).toBe("2026-11-12 23:05");
    expect(stamp("2026-11-12 23:05:10.123")).toBe("2026-11-12 23:05");
    expect(stamp("unknown")).toBe("unknown");
    expect(snapshotLine(today().snapshot)).toBe(`${NOTE} (triage run 2026-11-12 23:05 · newest prepared case 2026-11-01 19:36).`);
    expect(snapshotLine(emptyDay().snapshot)).toBe(`${NOTE} (newest prepared case 2026-11-01 19:36).`);
    expect(snapshotLine({ note: NOTE, triage_at: null, cases_prepared_at: null })).toBe(`${NOTE}.`);
    expect(snapshotLine(variants().snapshot)).toBeNull();
    expect(snapshotLine(null)).toBeNull();
    expect(snapshotLine({ note: "", triage_at: "2026-11-12T23:05:10", cases_prepared_at: null })).toBeNull();
  });
});

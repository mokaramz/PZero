import { describe, expect, it } from "vitest";

import { isDeferred, JOBS_SNAPSHOT, NOT_PORTED, ported, reasonOf, type Maybe } from "./deferred";

describe("the deferred shape", () => {
  it("is an object whose only key is a non-empty `deferred` string", () => {
    expect(isDeferred({ deferred: "Backups arrive with the hardening port." })).toBe(true);
    for (const x of [
      null,
      undefined,
      0,
      "deferred",
      [],
      [{ deferred: "x" }],
      {},
      { deferred: "" },
      { deferred: "   " },
      { deferred: 3 },
      { deferred: "x", count: 1 },
      { count: 0, latest: null },
    ])
      expect(isDeferred(x), JSON.stringify(x)).toBe(false);
  });

  it("reasonOf gives the reason or null; ported gives the data or undefined", () => {
    const off: Maybe<{ count: number }> = { deferred: "Not ported." };
    const on: Maybe<{ count: number }> = { count: 2 };
    expect(reasonOf(off)).toBe("Not ported.");
    expect(reasonOf(on)).toBeNull();
    expect(reasonOf(undefined)).toBeNull();
    expect(ported(off)).toBeUndefined();
    expect(ported(on)).toEqual({ count: 2 });
    expect(ported<number>(0)).toBe(0);
    expect(ported<number[]>([])).toEqual([]);
    expect(ported(null)).toBeUndefined();
  });

  it("one reason per deferred action, each a sentence", () => {
    expect(NOT_PORTED.runner).toBe("The background-job runner is not ported yet.");
    expect(JOBS_SNAPSHOT).toBe("Background jobs are not ported yet: job state and history are the imported snapshot.");
    expect(new Set(Object.values(NOT_PORTED)).size).toBe(Object.keys(NOT_PORTED).length);
    for (const r of Object.values(NOT_PORTED)) expect(r).toMatch(/^[A-Z].*\.$/);
  });
});

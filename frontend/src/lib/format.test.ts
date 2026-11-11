import { describe, expect, it } from "vitest";

import { cx, daysSince, fmtDate, host, plural, truncate } from "./format";

describe("format helpers", () => {
  it("plural", () => {
    expect(plural(1, "company", "companies")).toBe("1 company");
    expect(plural(3, "lead")).toBe("3 leads");
  });
  it("fmtDate keeps unparseable input and formats ISO dates", () => {
    expect(fmtDate("2026-09-27")).toBe("27 Sept 2026".replace("Sept", new Date("2026-09-27T00:00:00").toLocaleDateString("en-GB", { month: "short" })));
    expect(fmtDate("not a date")).toBe("not a date");
    expect(fmtDate(undefined)).toBe("");
  });
  it("daysSince", () => {
    const d = new Date(); // the LOCAL date — daysSince counts from local midnight (UTC differs around midnight)
    const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    expect(daysSince(today)).toBe(0);
    expect(daysSince("garbage")).toBeNull();
  });
  it("truncate, cx, host", () => {
    expect(truncate("abcdef", 4)).toBe("abc…");
    expect(cx("a", false, null, "b")).toBe("a b");
    expect(host("https://www.a68.io/about")).toBe("a68.io");
    expect(host("nope")).toBe("");
  });
});

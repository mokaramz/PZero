import { describe, expect, it } from "vitest";

import { edges, PIECE, piecePath, pieceViewBox } from "./piecePath";

const nums = (p: string) => (p.match(/-?\d+(\.\d+)?/g) ?? []).map(Number);

describe("piecePath", () => {
  it("a flat piece is a rounded rectangle that closes", () => {
    const p = piecePath(100, 50, edges({}), { n: 5, d: 10, c: 4, r: 8 });
    expect(p.startsWith("M8,0")).toBe(true);
    expect(p.endsWith("Z")).toBe(true);
    expect((p.match(/A8,8/g) ?? []).length).toBe(4);
    expect(p).not.toContain("C");
  });
  it("a right tab bulges outward by d; a right blank cuts inward by d", () => {
    const { W, H, o } = PIECE.card;
    const xsTab = nums(piecePath(W, H, edges({ right: "tab" }), o));
    expect(Math.max(...xsTab)).toBe(W + o.d);
    const blank = piecePath(W, H, edges({ right: "blank" }), o);
    expect(blank).toContain(`${W - o.d},${H / 2}`);
  });
  it("a top tab rises above the piece; a left blank cuts in", () => {
    const { W, H, o } = PIECE.evidence;
    expect(piecePath(W, H, edges({ top: "tab" }), o)).toContain(`${W / 2},${-o.d}`);
    expect(piecePath(W, H, edges({ left: "blank" }), o)).toContain(`${o.d},${H / 2}`);
  });
  it("the viewBox is padded by d on every side", () => {
    const { W, H, o } = PIECE.mark;
    expect(pieceViewBox(W, H, o)).toBe(`-12 -12 74 74`);
  });
});

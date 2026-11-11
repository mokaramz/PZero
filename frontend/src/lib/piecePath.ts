/**
 * Jigsaw piece geometry — the ONE generator for every piece in the Deal Flow identity (candidate cards, the header
 * pipeline chain, the evidence strip, the mark). Edges: "tab" = evidence attached (bulges out), "blank" = an open
 * question (cut in), "flat" = not applicable. Pure string geometry; render it as an SVG <path> whose viewBox is padded
 * by `d` on every side (see pieceViewBox) with overflow visible, so tabs are never clipped.
 */
export type Edge = "tab" | "blank" | "flat";
export type Edges = { top: Edge; right: Edge; bottom: Edge; left: Edge };
/** n neck half-width, d bump depth, c curve, r corner radius */
export type PieceOpts = { n: number; d: number; c: number; r: number };

export function piecePath(W: number, H: number, e: Edges, o: PieceOpts): string {
  const { n, d, c, r } = o;
  // one edge from (ax,ay) to (bx,by); (ux,uy) = edge direction, (ox,oy) = outward normal
  const seg = (ax: number, ay: number, bx: number, by: number, ux: number, uy: number, ox: number, oy: number, k: Edge): string => {
    if (k === "flat") return `L${bx},${by}`;
    const s = k === "tab" ? 1 : -1;
    const dx = ox * s * d;
    const dy = oy * s * d;
    const mx = (ax + bx) / 2;
    const my = (ay + by) / 2;
    const p1x = mx - ux * n;
    const p1y = my - uy * n;
    const p2x = mx + ux * n;
    const p2y = my + uy * n;
    return (
      `L${p1x},${p1y} C${p1x - ux * c},${p1y - uy * c} ${p1x - ux * c + dx},${p1y - uy * c + dy} ${mx + dx},${my + dy}` +
      ` C${mx + dx + ux * (n + c)},${my + dy + uy * (n + c)} ${p2x + ux * c},${p2y + uy * c} ${p2x},${p2y} L${bx},${by}`
    );
  };
  return (
    `M${r},0 ${seg(r, 0, W - r, 0, 1, 0, 0, -1, e.top)} A${r},${r} 0 0 1 ${W},${r} ${seg(W, r, W, H - r, 0, 1, 1, 0, e.right)}` +
    ` A${r},${r} 0 0 1 ${W - r},${H} ${seg(W - r, H, r, H, -1, 0, 0, 1, e.bottom)} A${r},${r} 0 0 1 0,${H - r}` +
    ` ${seg(0, H - r, 0, r, 0, -1, -1, 0, e.left)} A${r},${r} 0 0 1 ${r},0 Z`
  );
}

/** viewBox for a W×H piece, padded by the bump depth on all sides so tabs stay inside the drawing area. */
export function pieceViewBox(W: number, H: number, o: PieceOpts): string {
  return `${-o.d} ${-o.d} ${W + 2 * o.d} ${H + 2 * o.d}`;
}

const flat: Edges = { top: "flat", right: "flat", bottom: "flat", left: "flat" };
export const edges = (e: Partial<Edges>): Edges => ({ ...flat, ...e });

/** The four sizes of the identity (W, H, geometry). */
export const PIECE = {
  card: { W: 380, H: 104, o: { n: 7, d: 22, c: 9, r: 10 } },
  chain: { W: 200, H: 120, o: { n: 9, d: 26, c: 11, r: 12 } },
  evidence: { W: 148, H: 88, o: { n: 6, d: 14, c: 7, r: 8 } },
  mark: { W: 50, H: 50, o: { n: 5, d: 12, c: 6, r: 9 } },
} as const;

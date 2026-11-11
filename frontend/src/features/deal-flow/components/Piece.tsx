/**
 * Deal Flow's jigsaw identity for company cards: every candidate is a piece; its right edge is a tab that plugs into
 * the detail panel ("the board"). Geometry from the shared generator (lib/piecePath). Decorative only (aria-hidden):
 * the card itself is the <button>; this paints its outline behind the content.
 */
import { edges, PIECE, piecePath, pieceViewBox, type Edges, type PieceOpts } from "@/lib/piecePath";
import styles from "../DealFlow.module.css";

function PieceSvg({ w, h, e, o, className }: { w: number; h: number; e: Edges; o: PieceOpts; className?: string }) {
  if (!w || !h) return null;
  return (
    <svg
      className={className}
      width={w + 2 * o.d}
      height={h + 2 * o.d}
      viewBox={pieceViewBox(w, h, o)}
      style={{ left: -o.d, top: -o.d }}
      aria-hidden="true"
      focusable="false"
    >
      <path className={styles.pieceShape} d={piecePath(w, h, e, o)} />
    </svg>
  );
}

/** The card's outline: a right-edge tab, other edges flat. */
export function CardPiece({ w, h }: { w: number; h: number }) {
  return <PieceSvg w={w} h={h} e={edges({ right: "tab" })} o={PIECE.card.o} className={styles.pieceSvg} />;
}

/** The card mark keeps its own legal-form list ("Limited" too), so its initials stay exactly as before. */
const SKIP = /^(gmbh|ag|sa|se|ug|ltd|limited|inc|bv|ab|oy|sas|srl|plc|the)$/i;
function initials(name: string): string {
  const words = String(name || "?")
    .replace(/[^\p{L}\p{N} ]/gu, " ")
    .split(/\s+/)
    .filter((w) => w && !SKIP.test(w));
  return (words.length > 1 ? words[0][0] + words[1][0] : (words[0] ?? "?").slice(0, 2)).toUpperCase();
}

/** The company's mark: a small piece with a left blank (the slot the company still has to fill) and its initials. */
export function PieceMark({ name, size = 40 }: { name: string; size?: number }) {
  const { W, H, o } = PIECE.mark;
  return (
    <span className={styles.pieceMark} style={{ width: size, height: size }} aria-hidden="true">
      <svg width={size} height={size} viewBox={`0 0 ${W} ${H}`} overflow="visible" focusable="false">
        <path className={styles.pieceMarkShape} d={piecePath(W, H, edges({ left: "blank" }), o)} />
        <text x={W / 2 + o.d / 2} y={H / 2 + 1} dominantBaseline="central" textAnchor="middle" className={styles.pieceMarkText}>
          {initials(name)}
        </text>
      </svg>
    </span>
  );
}

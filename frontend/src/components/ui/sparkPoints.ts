/** The drawing box of a Sparkline (viewBox `0 0 W H`). */
export const SPARK_W = 120;
export const SPARK_H = 30;

/** The points of a sparkline over the finite numbers in `values` (others are dropped), or null below 3 of them.
 *  x spans 2 … W-2; y spans H-3 (the lowest value) … 3 (the highest); a flat series sits on the bottom line. */
export function sparkPoints(values: Array<number | null | undefined>): { values: number[]; points: Array<readonly [number, number]> } | null {
  const v = values.filter((x): x is number => typeof x === "number" && Number.isFinite(x));
  if (v.length < 3) return null;
  const lo = Math.min(...v);
  const hi = Math.max(...v);
  const span = hi - lo || 1;
  const points = v.map((x, i) => [2 + (i * (SPARK_W - 4)) / (v.length - 1), SPARK_H - 3 - ((x - lo) / span) * (SPARK_H - 6)] as const);
  return { values: v, points };
}

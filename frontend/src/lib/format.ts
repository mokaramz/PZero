/** Small, pure formatting helpers shared by all features. */

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** "2026-09-27" -> "27 Sep 2026" (keeps unparseable input as-is). */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function daysSince(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const d = new Date(iso.slice(0, 10) + "T00:00:00");
  if (Number.isNaN(d.getTime())) return null;
  return Math.floor((Date.now() - d.getTime()) / 86_400_000);
}

export function truncate(s: string | null | undefined, n: number): string {
  const t = s ?? "";
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
}

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

/** Hostname of a URL without "www." ("" when not a URL). */
export function host(u: string | null | undefined): string {
  try {
    return new URL(u ?? "").hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

/** Quiet freshness: "today", "yesterday", "6d ago", "3 wk ago", "4 mo ago" — "" when the date is unknown. */
export function ago(iso: string | null | undefined, now = Date.now()): string {
  const t = iso ? Date.parse(String(iso).slice(0, 10)) : NaN;
  if (Number.isNaN(t)) return "";
  const d = Math.floor((now - t) / 86_400_000);
  if (d <= 0) return "today";
  if (d === 1) return "yesterday";
  if (d < 21) return `${d}d ago`;
  if (d < 90) return `${Math.round(d / 7)} wk ago`;
  return `${Math.round(d / 30)} mo ago`;
}

/** Small shared formatting for the Events page. */
export const travelLine = (h: number | null | undefined) => (h == null ? "" : h === 0 ? "in Karlsruhe" : `${h} h from Karlsruhe`);

/** "16:00" -> "4:00 PM" (Luma-style); empty -> "Time not stated". */
export function timeLabel(t: string | undefined): string {
  if (!t) return "Time not stated";
  const [h, m] = t.split(":").map(Number);
  if (Number.isNaN(h)) return t;
  return `${((h + 11) % 12) + 1}:${String(m || 0).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
}

export const dayLabel = (iso: string, today: string): [string, string] => {
  if (!iso) return ["Date not stated", ""];
  const d = new Date(`${iso}T12:00:00`);
  const wd = d.toLocaleDateString("en-GB", { weekday: "long" });
  const t = new Date(`${today}T12:00:00`);
  const diff = Math.round((d.getTime() - t.getTime()) / 86_400_000);
  if (diff === 0) return ["Today", wd];
  if (diff === 1) return ["Tomorrow", wd];
  const main = d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }) + (iso.slice(0, 4) !== today.slice(0, 4) ? ` ${iso.slice(0, 4)}` : "");
  return [main, wd];
};

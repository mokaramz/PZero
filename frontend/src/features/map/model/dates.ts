/** The Berlin calendar day (YYYY-MM-DD) of an instant — the server's request day (review 025, decision g). */
export function berlinDay(now: Date): string {
  // en-CA formats as YYYY-MM-DD
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Berlin", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

/** The Berlin calendar day plus `days` calendar days: the sourcing-day default is `berlinDayPlus(new Date(), 7)`. */
export function berlinDayPlus(now: Date, days: number): string {
  const [y, m, d] = berlinDay(now).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

/**
 * Time-aware greeting for the Investment Desk. Uses the PZ machine's local time zone (Project Zero is local-first: the
 * browser and the server run on the same computer) unless a zone is passed — tests pass one, so they never depend on
 * the developer's clock or location.
 */
import { ROLE } from "@/lib/roles";

/** Local hour (0–23) of `at` in `timeZone` (default: this machine's zone). */
export function localHour(at: Date, timeZone?: string): number {
  const h = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", hourCycle: "h23", timeZone }).format(at);
  return Number(h) % 24;
}

/** 05:00–11:59 morning · 12:00–16:59 afternoon · 17:00–22:59 evening · 23:00–04:59 welcome back. */
export function greeting(at: Date, timeZone?: string, who: string = ROLE.operator): string {
  const h = localHour(at, timeZone);
  if (h >= 5 && h < 12) return `Good morning, ${who}.`;
  if (h >= 12 && h < 17) return `Good afternoon, ${who}.`;
  if (h >= 17 && h < 23) return `Good evening, ${who}.`;
  return `Welcome back, ${who}.`;
}

/** "Monday, 2 Nov · 17:43" in the same zone — a quiet context line under the greeting. */
export function contextLine(at: Date, timeZone?: string): string {
  const day = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "short", timeZone }).format(at);
  const time = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone }).format(at);
  return `${day.replace(/^(\w+) /, "$1, ")} · ${time}`;
}

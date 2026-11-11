import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Badge, Button, Callout, Field } from "@/components/ui";
import { friendlyError } from "@/lib/activity";
import { WEEKEND, fetchWeekend } from "../api";
import type { WeekendMission, WeekendStep } from "../model/types";
import styles from "../Events.module.css";

function isoLocal(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** Default window: the Friday before the weekend window through its Sunday (v1 openWeekend). */
function defaultWindow(ww: [string, string] | undefined): [string, string] {
  const sat = ww?.[0] ? new Date(`${ww[0]}T12:00:00`) : new Date();
  const fri = new Date(sat);
  fri.setDate(sat.getDate() - 1);
  const sun = ww?.[1] ? new Date(`${ww[1]}T12:00:00`) : new Date(sat.getTime() + 86_400_000);
  return [isoLocal(fri), isoLocal(sun)];
}

function stepPrice(s: WeekendStep): string {
  if (s.price_state === "free") return "FREE";
  if (s.price_state === "paid") return `${s.price?.amount ?? ""} ${s.price?.currency ?? ""}`.trim();
  if (s.price_state === "sold out") return "SOLD OUT";
  return "PRICE UNKNOWN";
}

/** Sourcing weekend: one city, the best compatible events in the window + open Talent-Graph follow-ups there.
 *  "Build missions" reads them for the typed window (GET events/weekend — the old POST never wrote). */
export function WeekendPlan({ weekendWindow }: { weekendWindow?: [string, string] }) {
  const [d0, d1] = defaultWindow(weekendWindow);
  const [from, setFrom] = useState(d0);
  const [to, setTo] = useState(d1);
  const [missions, setMissions] = useState<WeekendMission[] | null>(null);
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const toast = useToast();

  const run = async () => {
    setBusy(true);
    try {
      const r = await qc.fetchQuery({ queryKey: [WEEKEND, { start: from, end: to }], queryFn: ({ signal }) => fetchWeekend(from, to, signal), staleTime: 0 });
      setMissions(r.missions ?? []);
    } catch (e) {
      // the old action's failure toast; a read has no success toast and no Background activity row
      toast.show(`✕ Building weekend plan failed — ${friendlyError(e instanceof Error ? e.message : String(e), (e as { status?: number }).status)}`, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack" data-testid="weekend-plan">
      <Callout tone="blue">
        Network-density optimization, not tourism: one city, the best compatible events in your window, plus open Talent-Graph follow-ups there.
      </Callout>
      <div className={styles.weekendBar}>
        <Field label="From">
          <input value={from} onChange={(e) => setFrom(e.target.value)} />
        </Field>
        <Field label="To">
          <input value={to} onChange={(e) => setTo(e.target.value)} />
        </Field>
        <Button variant="primary" busy={busy} onClick={() => void run()}>
          Build missions
        </Button>
      </div>
      {missions && !missions.length && (
        <Callout tone="amber">
          No dated events in this window — no mission can be built from empty data. Check <b>Event source health</b> on the Events page, scan
          sources or add an event you know about.
        </Callout>
      )}
      {missions?.map((m, i) => (
        <section key={m.city + i} className={styles.mission}>
          <div className="row">
            <b className={styles.missionTitle}>
              #{i + 1} {m.city}
            </b>
            {m.strength && <Badge tone={m.strength === "Strong evidence" ? "green" : m.strength === "Consider" ? "amber" : "neutral"}>{m.strength}</Badge>}
            <span className="muted small">{m.travel_hours != null ? `travel ~${m.travel_hours}h from Karlsruhe (approximation)` : "travel time unknown"}</span>
          </div>
          {!!m.unknowns?.length && <div className="muted small">Missing: {m.unknowns.join(", ")}</div>}
          <ul className={styles.plan}>
            {m.plan.map((s, j) => (
              <li key={j}>
                <b>
                  {(s.when || "").slice(0, 10)} {s.time || ""}
                  {s.end_time ? `–${s.end_time}` : ""}
                </b>{" "}
                {s.what}
                {s.venue !== undefined && (
                  <div className="muted small">
                    {s.venue || ""}
                    {s.city ? `, ${s.city}` : ""} · {s.format || "UNKNOWN"} · {stepPrice(s)} · organizer {s.organizer || "UNKNOWN"}
                  </div>
                )}
                <div className="muted small">Why: {s.why}</div>
                {s.venue !== undefined && (
                  <div className="muted small">
                    Objective: {s.objective || ""} · confidence {s.confidence || "UNRESOLVED"}
                    {s.unknowns?.length ? ` · unknown: ${s.unknowns.join(", ")}` : ""}
                    {s.research_first?.length ? ` · research first: ${s.research_first.join(", ")}` : ""}
                  </div>
                )}
                {s.action?.state === "sold_out" ? (
                  <div className="muted small">Sold out — not actionable</div>
                ) : s.action?.state === "waitlist" ? (
                  <a className="small" href={s.action.url} target="_blank" rel="noreferrer">
                    Sold out — check waitlist ↗
                  </a>
                ) : s.registration_url ? (
                  <a className="small" href={s.registration_url} target="_blank" rel="noreferrer">
                    Register / details ↗
                  </a>
                ) : null}
              </li>
            ))}
          </ul>
          <div className={styles.expected}>
            <b>Expected:</b> {m.expected}
          </div>
        </section>
      ))}
    </div>
  );
}

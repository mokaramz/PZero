import { cx } from "@/lib/format";
import type { EventRecord, ScoutReport } from "../model/types";
import { travelLine, timeLabel } from "./bits";
import { isPriorityEvent, priorityWhy, type Item } from "../model/workspace";
import styles from "../Events.module.css";

type Common = { selected: boolean; onOpen: (id: string) => void };

/** The evidence words a source listing actually contains, as one plain sentence (never a score). */
function evidenceLine(e: EventRecord): string {
  const words = [...new Set((e.assessment?.factors ?? []).flatMap((f) => f.evidence.map((w) => w.toLowerCase())))].slice(0, 5);
  return words.length ? `The listing mentions ${words.join(", ")}.` : "";
}

function Label({ e }: { e: EventRecord }) {
  if (e.status === "planned") return <span className={cx(styles.lab, styles.labGo)}>Planned</span>;
  if (e.status === "attended") return <span className={cx(styles.lab, styles.labGo)}>Attended</span>;
  if (isPriorityEvent(e)) return <span className={cx(styles.lab, styles.labPrio)}>Priority · {priorityWhy({ kind: "event", e } as Item)}</span>;
  if (e.scout) return <span className={cx(styles.lab, styles.labScout)}>Scout 00 {e.scout.p_class}</span>;
  return null;
}

/** An event with real signal: time · title · organizer · place · why it matters · type/themes · verification · actions. */
export function EventCard({ e, types, selected, onOpen, onPlan }: Common & { e: EventRecord; types: Record<string, string>; onPlan: (id: string) => void }) {
  const tier = e.eligibility?.tier;
  const why = e.scout?.why || (tier === "HIGH-SIGNAL" ? evidenceLine(e) : "");
  const org = e.organizer && e.organizer !== "UNKNOWN" ? e.organizer.split(",").slice(0, 2).join(",") : "";
  const sold = e.action?.state === "sold_out" || e.action?.state === "waitlist";
  return (
    <article
      className={cx(styles.card, selected && styles.cardSel, isPriorityEvent(e) && styles.cardPrio, e.status === "planned" && styles.cardGo)}
      data-testid="event-card"
      data-event-id={e.id}
      onClick={(x) => {
        if (!(x.target as HTMLElement).closest("a,button")) onOpen(e.id); // the whole card opens the details
      }}
    >
      <div className={styles.cardTl}>
        <span>{timeLabel(e.when?.start_time)}</span>
        {e.when?.weekend && <span className={styles.wk}>WEEKEND</span>}
        {sold && <span className={styles.sold}>{e.action?.state === "waitlist" ? "SOLD OUT — WAITLIST" : "SOLD OUT"}</span>}
        <span className="grow" />
        <Label e={e} />
      </div>
      <button type="button" className={styles.cardTitle} onClick={() => onOpen(e.id)}>
        {e.name}
      </button>
      <div className={styles.cardMeta}>
        {org && (
          <span>
            <i aria-hidden>◦</i>By {org}
          </span>
        )}
        <span>
          <i aria-hidden>⌖</i>
          <span data-testid="event-place">{e.place?.label || e.city || "Location not stated"}</span>
          {travelLine(e.travel_hours) && <span className={styles.faint}> · {travelLine(e.travel_hours)}</span>}
        </span>
      </div>
      {why && <p className={styles.cardWhy}>{why}</p>}
      <div className={styles.cardFoot}>
        {e.type && e.type !== "UNKNOWN" && <span className={styles.typeTag}>{types[e.type] || e.type}</span>}
        {(e.themes ?? []).slice(0, 3).map((t) => (
          <span key={t} className={styles.theme}>
            {t}
          </span>
        ))}
        {e.human_verified ? (
          <span className={styles.verOk}>Verified by you</span>
        ) : tier === "NEEDS REVIEW" ? (
          <span className={styles.verNo}>Needs your verification</span>
        ) : null}
        <span className="grow" />
        {e.status !== "planned" && e.status !== "attended" && tier !== "REJECTED" && (
          <button type="button" className={styles.act} onClick={() => onPlan(e.id)}>
            Plan
          </button>
        )}
        <button type="button" className={styles.actQ} onClick={() => onOpen(e.id)}>
          Details
        </button>
        {(e.registration_url || e.url) && (
          <a className={styles.actQ} href={e.registration_url || e.url} target="_blank" rel="noreferrer">
            Source ↗
          </a>
        )}
      </div>
    </article>
  );
}

/** A Scout 00 recommendation that is NOT an Events record yet — explicitly labelled; Add / Monitor / Ignore only. */
export function SuggestionCard({ r, selected, onOpen, onAct, busy }: Common & { r: ScoutReport; onAct: (r: ScoutReport, a: "add" | "monitor" | "ignore") => void; busy: boolean }) {
  return (
    <article
      className={cx(styles.card, styles.cardSug, selected && styles.cardSel)}
      data-testid="suggestion-card"
      data-key={r.key}
      onClick={(x) => {
        if (!(x.target as HTMLElement).closest("a,button")) onOpen(r.key);
      }}
    >
      <div className={styles.cardTl}>
        <span>Time not stated</span>
        <span className="grow" />
        <span className={cx(styles.lab, styles.labSug)}>Scout 00 suggestion · not on Events yet</span>
      </div>
      <button type="button" className={styles.cardTitle} onClick={() => onOpen(r.key)}>
        {r.name}
      </button>
      <div className={styles.cardMeta}>
        <span>
          <i aria-hidden>⌖</i>
          {r.place?.label || r.city}
          {travelLine(r.travel_hours) && <span className={styles.faint}> · {travelLine(r.travel_hours)}</span>}
        </span>
      </div>
      {r.why && <p className={styles.cardWhy}>{r.why}</p>}
      <div className={styles.cardFoot}>
        <span className={styles.typeTag}>
          Scout 00 · {[r.p_class, r.ev_class].filter(Boolean).join(" · ")}
          {r.cycles.length > 1 ? ` · ${r.cycles.length} cycles` : ""}
        </span>
        {r.themes.slice(0, 2).map((t) => (
          <span key={t} className={styles.theme}>
            {t}
          </span>
        ))}
        <span className="grow" />
        <button type="button" className={styles.actPri} disabled={busy} onClick={() => onAct(r, "add")}>
          {busy ? "Adding…" : "Add to Events"}
        </button>
        {!r.statuses.includes("MONITOR") && (
          <button type="button" className={styles.actQ} onClick={() => onAct(r, "monitor")}>
            Monitor
          </button>
        )}
        <button type="button" className={styles.actQ} onClick={() => onAct(r, "ignore")}>
          Ignore
        </button>
      </div>
    </article>
  );
}

/** A listing whose source gives only a title (or a general event when included): one quiet line, opens the details. */
export function QuietRow({ e, selected, onOpen }: Common & { e: EventRecord }) {
  const rejected = e.eligibility?.tier === "REJECTED";
  return (
    <button type="button" className={cx(styles.quietRow, selected && styles.quietSel)} data-testid="event-card" data-event-id={e.id} onClick={() => onOpen(e.id)}>
      <span className={styles.qTime}>{e.when?.start_time ? timeLabel(e.when.start_time) : "—"}</span>
      <span className={styles.qName}>{e.name}</span>
      <span className={styles.qPlace}>{rejected ? `Not recommended: ${(e.eligibility?.reasons ?? [])[0] ?? "general event"}` : e.place?.area_label || e.city || "Location not stated"}</span>
    </button>
  );
}

/** The two small components of the old `eventUtil.tsx`, verbatim: an explicit unknown, and an event's date and time. */
import type { ReactNode } from "react";

import type { EventRecord } from "../model/types";
import styles from "../Events.module.css";

export const Unk = ({ children }: { children: ReactNode }) => <span className={styles.unk}>{children}</span>;

const dayFmt = (iso: string) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });

/** "Sat 27 Sep → Sun 28 Sep · 18:00–21:00" with explicit unknowns (v1 evWhen). */
export function When({ e }: { e: EventRecord }) {
  const w = e.when ?? {};
  if (!w.start_date) return <Unk>Date unknown</Unk>;
  return (
    <>
      <b>{dayFmt(w.start_date)}</b>
      {w.multi_day && w.end_date && <> → {dayFmt(w.end_date)}</>}
      {w.start_time ? (
        <>
          {" "}· {w.start_time}
          {w.end_time ? `–${w.end_time}` : ""}
          {w.tz === "converted to Europe/Berlin" && <span className="muted"> (Berlin time)</span>}
        </>
      ) : (
        <>
          {" "}· <Unk>Time unknown</Unk>
        </>
      )}
    </>
  );
}

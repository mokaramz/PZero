import { Badge, Button } from "@/components/ui";
import { cx } from "@/lib/format";
import { useAckTrigger } from "../api";
import type { Trigger } from "../model/types";
import { evidenceText, triggerSource, triggerTone } from "../model/watch";
import styles from "../Watchlist.module.css";

/**
 * What the WATCH sensors fired for one company (the old `TriggerList`), on the Watchlist and in the Deal Flow WATCH
 * section. An open trigger has Reviewed / Dismiss (a status line is appended; the trigger stays on record); a decided
 * one shows its status.
 */
export function TriggerList({ triggers }: { triggers: Trigger[] }) {
  const ack = useAckTrigger();
  if (!triggers.length) return <div className="small faint">No triggers yet.</div>;
  return (
    <ul className={cx("small", styles.triggers)}>
      {triggers.map((t) => (
        <li key={t.id} className={styles.trigger} data-testid="watch-trigger" data-status={t.status}>
          <Badge tone={triggerTone(t)}>{t.label}</Badge> {evidenceText(t)}{" "}
          <span className="faint">
            · {triggerSource(t)} · first seen {t.first_observed.slice(0, 10)}
            {t.source_date && ` · dated ${t.source_date}`}
          </span>{" "}
          {t.url && (
            <a href={t.url} target="_blank" rel="noreferrer">
              source
            </a>
          )}
          {t.status === "new" ? (
            <>
              {" "}
              <Button size="sm" variant="ghost" onClick={() => ack.mutate({ id: t.id, status: "reviewed" })}>
                Reviewed
              </Button>
              <Button size="sm" variant="ghost" onClick={() => ack.mutate({ id: t.id, status: "dismissed" })}>
                Dismiss
              </Button>
            </>
          ) : (
            <span className="faint"> · {t.status}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

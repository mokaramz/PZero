import { DeferredButton } from "@/components/Deferred";
import { Badge, Button, Panel } from "@/components/ui";
import { NOT_PORTED } from "../model/deferred";
import type { Packet, ValidationPayload } from "../model/types";
import { label, latestCycle, missType, scoutLine } from "../model/view";
import styles from "../Validation.module.css";

type PacketState = { packet: Packet | null; loading: boolean; prepare: (cycle: string) => void };

/** "Where do we miss?" — audited misses and false positives, and the Scout 00 feedback packet. */
export function MissTab({ d, scout }: { d: ValidationPayload; scout: PacketState }) {
  return (
    <div className={styles.two}>
      <Misses d={d} />
      <ScoutFeedback d={d} {...scout} />
    </div>
  );
}

/** "Record false positive" is a write (review 027b): visible, disabled with its reason. */
function Misses({ d }: { d: ValidationPayload }) {
  return (
    <Panel
      title="Misses & false positives"
      aside={
        <DeferredButton size="sm" reason={NOT_PORTED.writes} data-testid="record-fp">
          Record false positive
        </DeferredButton>
      }
      data-testid="val-misses"
    >
      {!d.misses.length && !d.false_positive_audits.length && (
        <div className="small faint">
          Nothing recorded yet. When you learn about a strong company Project Zero missed (or caught late), record a miss: what was the earliest public
          signal, and who should have found it?
        </div>
      )}
      {[...d.misses, ...d.false_positive_audits].map((a) => (
        <div key={a.id} className={styles.audit} data-testid="val-audit">
          <Badge tone={a.type === "miss" ? "red" : "amber"}>{a.type === "miss" ? "MISS" : "FALSE POSITIVE"}</Badge> <b>{a.company}</b>
          {a.miss_type && <span className="small faint"> · {missType(a.miss_type)}</span>}
          {a.type === "miss" ? (
            <div className="small">
              earliest signal: {a.earliest_signal || "—"} {a.earliest_signal_date ? `(${a.earliest_signal_date})` : ""} · should have been found by{" "}
              {a.should_have_found || "—"} · why: {label(a.why_missed || "")} · preventable: {a.preventable}
              {a.improvement && <div>→ {a.improvement}</div>}
            </div>
          ) : (
            <div className="small">
              {(a.causes || []).map(label).join(", ")}
              {a.lesson && ` — ${a.lesson}`}
            </div>
          )}
        </div>
      ))}
      {!!d.false_positive_watch.length && (
        <div className={`small ${styles.mt}`}>
          <b>Prioritised but now negative</b> (worth a false-positive audit): {d.false_positive_watch.map((x) => x.name).join(", ")}
        </div>
      )}
    </Panel>
  );
}

/** Preparing the packet is a read. "Copy & log handover" marks it as sent, a write (review 027b): visible, disabled
 *  with its reason — the packet text can still be selected and copied by hand. Its News and source-network sections
 *  arrive with News & Learning. */
function ScoutFeedback({ d, packet, loading, prepare }: { d: ValidationPayload } & PacketState) {
  return (
    <Panel title="Scout 00 feedback" data-testid="val-scout">
      <div className="small">
        {scoutLine(d.scout)}
        {d.scout.last_packet && (
          <span className="faint">
            {" "}
            Last packet handed over {d.scout.last_packet.at} (cycle {d.scout.last_packet.cycle}).
          </span>
        )}
      </div>
      <div className={`row ${styles.mt}`}>
        <Button size="sm" busy={loading} onClick={() => prepare(latestCycle(d.scout.cycles))} data-testid="scout-packet">
          Prepare feedback packet (latest cycle)
        </Button>
        {packet && (
          <DeferredButton size="sm" variant="primary" reason={NOT_PORTED.writes} data-testid="scout-packet-copy">
            Copy &amp; log handover
          </DeferredButton>
        )}
      </div>
      {packet && (
        <>
          <pre className={styles.packet} data-testid="scout-packet-text">
            {packet.text}
          </pre>
          <div className="small faint" data-testid="scout-packet-deferred">
            News and source-network learnings: {NOT_PORTED.news}.
          </div>
        </>
      )}
      <div className="small faint">Manual copy/paste into grok.com — nothing is sent automatically.</div>
    </Panel>
  );
}

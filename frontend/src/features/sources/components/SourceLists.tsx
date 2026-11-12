import { Badge, Panel } from "@/components/ui";
import type { Feed, ManualSource, WatchedPage } from "../model/types";
import styles from "../Sources.module.css";

/** The manual / relationship sources, then the watched pages and feeds the scan button checks. */
export function SourceLists({ manual, pages, feeds }: { manual: ManualSource[]; pages: WatchedPage[]; feeds: Feed[] }) {
  return (
    <>
      <Panel
        title={
          <>
            Manual &amp; relationship sources <small className="faint">— the real edge lives here; no tool can do these</small>
          </>
        }
        data-testid="manual-sources"
      >
        <div className={styles.srcGrid}>
          {manual.map((m) => (
            <div key={m.name} className={styles.srcItem}>
              <b>{m.name}</b>
              <a href={m.url} target="_blank" rel="noreferrer">
                open ↗
              </a>
              <div className={styles.how}>{m.how}</div>
            </div>
          ))}
        </div>
      </Panel>
      <Panel title="What the button checks" data-testid="checked-sources">
        <div className={styles.srcGrid}>
          {pages.map((p) => (
            <div key={p.name} className={styles.srcItem}>
              <b>{p.name}</b>
              <span>
                <Badge tone="green">PRE-COMPANY · the edge</Badge>
              </span>
              <div className={styles.how}>
                Page watcher: we detect new text, you read it. Archetypes {p.archetypes.join(", ")}.{" "}
                <a href={p.url} target="_blank" rel="noreferrer">
                  open ↗
                </a>
              </div>
            </div>
          ))}
          {feeds.map((f) => (
            <div key={f.name} className={styles.srcItem}>
              <b>{f.name}</b>
              <span>
                <Badge>ANNOUNCEMENT · discovery only</Badge>
              </span>
              <div className={styles.how}>RSS feed of funding/spinout news. Usually recently funded → low urgency, relationship value.</div>
            </div>
          ))}
        </div>
      </Panel>
    </>
  );
}

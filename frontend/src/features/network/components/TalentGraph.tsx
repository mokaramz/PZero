import { Async, Badge } from "@/components/ui";
import { useGraph } from "../api";
import type { GraphNode } from "../model/types";
import styles from "../Network.module.css";

/** Talent Graph: introduction / recommendation chains as a forest (GET network/graph). A name opens that person. */
export function TalentGraph({ onOpen }: { onOpen: (id: string) => void }) {
  const q = useGraph();
  const node = (n: GraphNode, depth: number) => (
    <div key={n.id} className={depth ? styles.gChild : styles.gRoot}>
      <button type="button" className={styles.linkBtn} onClick={() => onOpen(n.id)}>
        {n.name}
      </button>
      {n.founder_potential && n.founder_potential !== "none" && (
        <>
          {" "}
          <Badge tone="green">{n.founder_potential}</Badge>
        </>
      )}
      {n.watch && (
        <>
          {" "}
          <Badge tone="red">watch</Badge>
        </>
      )}
      <span className="muted small">
        {" "}
        {n.role || ""}
        {n.company ? ` · ${n.company}` : ""}
      </span>
      {!!n.startups?.length && (
        <span className="muted small">
          {" "}
          → <b className={styles.navy}>{n.startups.join(", ")}</b>
        </span>
      )}
      {n.children.map((c) => node(c, depth + 1))}
    </div>
  );
  return (
    <div className={styles.graph} data-testid="talent-graph">
      <Async q={q} label="Loading talent graph…">
        {(g) =>
          g.forest.length ? (
            <div className="stack">{g.forest.map((r) => node(r, 0))}</div>
          ) : (
            <span className="muted">No chains yet — the "3 most talented" ritual builds this.</span>
          )
        }
      </Async>
    </div>
  );
}

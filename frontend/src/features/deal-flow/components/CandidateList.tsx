import { memo } from "react";

import { Badge, Button } from "@/components/ui";
import { cx } from "@/lib/format";
import { useChanged } from "@/lib/motion";
import { useBoxSize } from "../hooks/useBoxSize";
import { attWhy, scoreTxt, thesis, tierLbl } from "../model/attention";
import { PROPOSAL_LABEL, proposalTone, type TriageSummary } from "../model/triage";
import type { Candidate } from "../model/types";
import { CardPiece, PieceMark } from "./Piece";
import styles from "../DealFlow.module.css";

const MORE = 50;

/** The row's name: the triage entity repair names the real company when the stored name is not one. */
const rowName = (c: Candidate, tri?: TriageSummary) => (tri?.entity.broken && tri.entity.entities.length ? tri.entity.display_name : c.name);

/** The one-line signal: the description first; the attention breakdown (scoring artefacts) only as a fallback. */
const signal = (c: Candidate) => (c.description ? (c.description.length > 130 ? `${c.description.slice(0, 127)}…` : c.description) : thesis(c));

type RowProps = {
  c: Candidate;
  tri?: TriageSummary;
  selected: boolean;
  im: boolean;
  themes: Record<string, string>;
  onSelect: (id: string) => void;
};

const Row = memo(function Row({ c, tri, selected, im, themes, onSelect }: RowProps) {
  const th = (c.themes || []).map((t) => themes[t] || t);
  const decided = useChanged(c.decision || "new");
  const [ref, size] = useBoxSize<HTMLButtonElement>();
  return (
    <button
      ref={ref}
      type="button"
      className={cx(styles.cand, selected && styles.candSel, c.decision !== "new" && styles.candDecided)}
      onClick={() => onSelect(c.id)}
      aria-pressed={selected}
      data-testid="cand-row"
      data-id={c.id}
    >
      <CardPiece w={size.w} h={size.h} />
      <PieceMark name={c.name} size={40} />
      <span className={styles.candBody}>
        <span className={styles.candL1}>
          <span className={styles.candName}>{rowName(c, tri)}</span>
          {c.opportunistic && <Badge tone="red">OPP</Badge>}
          {tri && (
            <Badge
              tone={proposalTone(tri.display_proposal)}
              title={`Machine triage proposal${tri.reject_basis ? ` (${tri.reject_basis})` : ""}`}
              data-testid="row-triage"
            >
              {PROPOSAL_LABEL[tri.display_proposal]}
            </Badge>
          )}
          <span className="grow" />
          <span className={styles.score} title={attWhy(c)}>
            {scoreTxt(c, im)}
          </span>
        </span>
        <span className={styles.candL3}>{signal(c)}</span>
        <span className={styles.candL2}>
          <span className={cx(styles.tier, c.discovery_tier === "pre_company" && styles.tierPre)}>{tierLbl(c)}</span>
          {" · "}
          {c.source}
          {th.length ? ` · ${th.join(" · ")}` : ""}
          {c.also_seen?.length ? ` · ${c.also_seen.length + 1} sources` : ""}
          {c.decision !== "new" && (
            <>
              {" · "}
              <b key={c.decision} className={decided ? "pz-enter" : undefined}>
                {c.decision}
              </b>
            </>
          )}
        </span>
      </span>
    </button>
  );
});

type ListProps = {
  list: Candidate[];
  tri?: Record<string, TriageSummary>;
  selId: string | null;
  im: boolean;
  themes: Record<string, string>;
  onSelect: (id: string) => void;
  limit: number;
  onMore: () => void;
  /** undecided candidates below the Attention queue's cut */
  hidden: number;
};

/** Paginated candidate list: the inbox can hold ~1,000 rows, so only `limit` are mounted at once. */
export function CandidateList({ list, tri, selId, im, themes, onSelect, limit, onMore, hidden }: ListProps) {
  return (
    <div className={styles.list} role="list" aria-label="Candidates">
      {list.slice(0, limit).map((c) => (
        <Row key={c.id} c={c} selected={c.id === selId} im={im} themes={themes} onSelect={onSelect} tri={tri?.[c.id]} />
      ))}
      {list.length > limit && (
        <div className={styles.more}>
          <span className="faint small">
            Showing {limit} of {list.length}
          </span>
          <Button size="sm" onClick={onMore}>
            Show {Math.min(MORE, list.length - limit)} more
          </Button>
        </div>
      )}
      {hidden > 0 && (
        <div className={styles.listNote}>
          Attention queue shows the top 15 by signal — <b>{hidden} more undecided</b> under <b>All to decide</b>.
        </div>
      )}
    </div>
  );
}

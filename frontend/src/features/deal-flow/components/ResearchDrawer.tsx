import { useState } from "react";

import { Button, Callout, Drawer } from "@/components/ui";
import type { Candidate } from "../model/types";
import styles from "../DealFlow.module.css";

const searchLinks = (name: string): Array<[string, string]> => {
  const q = encodeURIComponent(name);
  return [
    ["Google", `https://www.google.com/search?q=${q}`],
    ["Who founded it?", `https://www.google.com/search?q=${q}+founder+OR+gründer+OR+CEO`],
    ["LinkedIn", `https://www.linkedin.com/search/results/all/?keywords=${q}`],
    ["Crunchbase (funding?)", `https://www.crunchbase.com/textsearch?q=${q}`],
    ["Google News", `https://news.google.com/search?q=${q}`],
    ["Project A portfolio", "https://www.project-a.vc/companies"],
  ];
};

/** v1 research(): the manual 10-minute research panel — links out, notes, decide. The only place notes are written. */
export function ResearchDrawer({
  c,
  onClose,
  onDecide,
  onKeep,
  busy,
}: {
  c: Candidate;
  onClose: () => void;
  onDecide: (decision: "research" | "rejected", notes: string) => Promise<boolean>;
  /** opens Keep & score; the notes are saved first (as researching), as before */
  onKeep: () => void;
  busy: boolean;
}) {
  const [notes, setNotes] = useState(c.notes || "");
  return (
    <Drawer open onClose={onClose} title={`Research: ${c.name}`} width={720}>
      <Callout tone="blue">
        <b>10 minutes, three questions:</b> WHO is behind it (founder strength)? WHEN are they raising (timing)? Does Project A already own this market
        (conflict)? The tool cannot answer these — you click, read, decide.
      </Callout>
      <b>Search links</b>
      <div className={styles.links}>
        {searchLinks(c.name).map(([l, u]) => (
          <a key={l} href={u} target="_blank" rel="noreferrer">
            {l}
          </a>
        ))}
      </div>
      {!!c.twins?.length && (
        <Callout tone="amber">
          <b>Possible portfolio twin(s): {c.twins.join(", ")}.</b> Decide: similar-taste / complementary / potential conflict / unclear. If unsure → "potential
          conflict" and ask Manager.
        </Callout>
      )}
      <label htmlFor="rnotes">
        <b>Notes</b> (founders, timing evidence, conflict thoughts):
      </label>
      <textarea id="rnotes" rows={5} value={notes} onChange={(e) => setNotes(e.target.value)} className={styles.mt8} />
      <div className={`row ${styles.mt8}`}>
        <Button
          variant="success"
          disabled={busy}
          onClick={async () => {
            if (await onDecide("research", notes)) onKeep();
          }}
        >
          Keep — go to scoring
        </Button>
        <Button
          variant="primary"
          disabled={busy}
          onClick={async () => {
            if (await onDecide("research", notes)) onClose();
          }}
        >
          Save &amp; decide later
        </Button>
        <Button
          variant="danger"
          disabled={busy}
          onClick={async () => {
            if (await onDecide("rejected", notes)) onClose();
          }}
        >
          Reject
        </Button>
      </div>
    </Drawer>
  );
}

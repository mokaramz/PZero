import { useState } from "react";
import { Link } from "react-router-dom";

import { DeferredButton } from "@/components/Deferred";
import { Badge, Button } from "@/components/ui";
import { useSavePages } from "../api";
import type { WatchedCompany } from "../model/types";
import { checkLine, PAGE_CHECKS_DEFERRED, splitUrls } from "../model/watch";
import { TriggerList } from "./TriggerList";
import styles from "../Watchlist.module.css";

/**
 * One watched company (the old `CompanyRow`): its name (to its Deal Flow candidate), the open-trigger and stale-triage
 * badges, its triggers, and the official pages to watch with Save pages. "Check now" keeps its place, deferred until
 * the sensors (review 037b).
 */
export function CompanyRow({ c }: { c: WatchedCompany }) {
  const [urls, setUrls] = useState(c.urls.join("\n"));
  const save = useSavePages();
  return (
    <div className={styles.company} data-testid="watched-company" data-key={c.key}>
      <div className="row">
        <b className={styles.companyName}>{c.candidate_id ? <Link to={`/deal-flow?candidate=${encodeURIComponent(c.candidate_id)}`}>{c.name}</Link> : c.name}</b>
        {c.open > 0 && <Badge tone="red">{c.open} new</Badge>}
        {c.triage_predates_evidence && (
          <Badge tone="amber" title="The machine triage judged the company before this evidence existed">
            machine triage predates new evidence
          </Badge>
        )}
        <span className="grow" />
        <DeferredButton size="sm" reason={PAGE_CHECKS_DEFERRED} data-testid="watch-check">
          Check now
        </DeferredButton>
      </div>
      <TriggerList triggers={c.triggers} />
      <details className={styles.pages}>
        <summary className="small">Official pages to watch ({c.urls.length})</summary>
        <textarea
          rows={3}
          className={styles.pagesBox}
          placeholder="One public URL per line: company news page, careers page, product page…"
          value={urls}
          onChange={(e) => setUrls(e.target.value)}
          aria-label={`Pages to watch for ${c.name}`}
        />
        <Button size="sm" busy={save.isPending} onClick={() => save.mutate({ name: c.name, urls: splitUrls(urls), candidate_id: c.candidate_id })}>
          Save pages
        </Button>
        {Object.entries(c.checks).map(([u, k]) => (
          <div key={u} className={`small faint ${styles.check}`} data-testid="watch-page-check">
            {checkLine(u, k)}
          </div>
        ))}
      </details>
    </div>
  );
}

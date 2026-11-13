/**
 * Signal watchlist (v1 view `watch`, review 013). Manual-first and ToS-safe: the operator opens public links and logs
 * what changed via POST network/watch_log {id, note} (an empty note just marks the person checked). Above the people,
 * the watched companies panel (review 037a): pages are saved and triggers acknowledged; the page checks are 037b.
 */
import { useState } from "react";
import { Link } from "react-router-dom";

import { useToast } from "@/components/Toast";
import { Async, Button, Callout, EmptyState, PageHeader, Panel } from "@/components/ui";
import { personLink, PEOPLE, useWatchlist, WATCH_LOG, WATCHLIST } from "@/features/network/api";
import type { WatchPerson } from "@/features/network/model/types";
import { useAction } from "@/lib/hooks";
import { WatchedCompanies } from "./components/WatchedCompanies";
import styles from "./Watchlist.module.css";

export default function WatchlistPage() {
  const q = useWatchlist();
  return (
    <>
      <PageHeader
        title="Signal watchlist"
        subtitle={
          <>
            Founders, researchers and investors worth tracking. <b>Manual-first and ToS-safe:</b> no LinkedIn scraping, ever. The weekly sweep is you
            opening the links below for 15 minutes and logging what changed (left company, title → founder, new repo, hiring post). Reliable public
            signals only.
          </>
        }
      />
      <WatchedCompanies />
      <Callout tone="blue">Add someone to the watchlist via Network → open person → tick "Watch". Suggested weekly rhythm: Friday, after the Radar.</Callout>
      <Panel>
        <Async q={q}>
          {(d) =>
            d.people.length ? (
              <div className={styles.scroll}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Person</th>
                      <th>Why watching</th>
                      <th>Public signal links</th>
                      <th className={styles.wChecked}>Last checked</th>
                      <th className={styles.wLog}>Log a signal</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.people.map((p) => (
                      <Row key={p.id} p={p} />
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState>
                Watchlist empty. People → open a person → tick Watch. Start with: strong engineers at Helsing/Quantum/ARX-class companies you actually
                know, and researchers whose work you follow.
              </EmptyState>
            )
          }
        </Async>
      </Panel>
    </>
  );
}

/** The public places to look a person up (no scraping): web, news, GitHub users, Scholar, then their own profiles. */
function signalLinks(p: WatchPerson): Array<[string, string]> {
  const q = encodeURIComponent(p.name);
  const links: Array<[string, string]> = [
    ["Google", `https://www.google.com/search?q=${q}`],
    ["News", `https://news.google.com/search?q=${q}`],
    ["GitHub", `https://github.com/search?q=${q}&type=users`],
    ["Scholar", `https://scholar.google.com/scholar?q=${q}`],
  ];
  if (p.linkedin) links.push(["LinkedIn", p.linkedin]);
  if (p.x) links.push(["X", p.x]);
  return links;
}

function Row({ p }: { p: WatchPerson }) {
  const [note, setNote] = useState("");
  const toast = useToast();
  const log = useAction<{ id: string; note: string }>(WATCH_LOG, { invalidates: [WATCHLIST, PEOPLE], label: "Logging the signal", quiet: true });
  return (
    <tr data-testid="watch-row">
      <td>
        <Link to={personLink(p.id)} className={styles.name}>
          {p.name}
        </Link>
        <div className={styles.sub}>
          {p.role ?? ""}
          {p.company && ` · ${p.company}`}
        </div>
      </td>
      <td className={styles.sub}>{p.why_interesting ?? ""}</td>
      <td className={styles.sub}>
        {signalLinks(p).map(([l, u], i) => (
          <span key={l}>
            {i > 0 && " · "}
            <a href={u} target="_blank" rel="noreferrer">
              {l}
            </a>
          </span>
        ))}
      </td>
      <td className={styles.sub}>{p.last_checked || "never"}</td>
      <td>
        <input className={styles.input} placeholder="what changed?" aria-label={`Signal for ${p.name}`} value={note} onChange={(e) => setNote(e.target.value)} />
        <Button
          size="sm"
          className={styles.logBtn}
          busy={log.isPending}
          onClick={() =>
            log.mutate(
              { id: p.id, note },
              {
                onSuccess: () => {
                  toast.show(note ? "Signal logged" : "Marked checked", "ok");
                  setNote("");
                },
              },
            )
          }
        >
          Log &amp; mark checked
        </Button>
      </td>
    </tr>
  );
}

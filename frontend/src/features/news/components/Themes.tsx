import { Badge } from "@/components/ui";
import type { Theme } from "../model/types";
import { companiesLine, THEMES_EMPTY } from "../model/view";
import styles from "../News.module.css";
import { Section } from "./Section";

/** "What's moving": only patterns with ≥ 3 distinct companies in 30 days (two articles are not a trend). */
export function Themes({ themes }: { themes: Theme[] }) {
  if (!themes.length) return <div className={styles.empty}>{THEMES_EMPTY}</div>;
  return (
    <div className={styles.list}>
      {themes.map((t) => (
        <article key={`${t.theme}-${t.geo}`} className={styles.card} data-testid="news-theme">
          <div className={styles.chips}>
            <Badge tone="blue">MARKET SIGNAL</Badge>
            <span className={styles.meta}>confidence: {t.confidence}</span>
          </div>
          <h3 className={styles.headline}>{t.observation}</h3>
          <Section title="Why it could matter">{t.why_it_matters}</Section>
          <Section title="Supporting stories">
            <ul>
              {t.stories.map((x) => (
                <li key={x.event_id}>{x.headline}</li>
              ))}
            </ul>
          </Section>
          <div className={styles.faint}>{companiesLine(t.pz_related)}</div>
        </article>
      ))}
    </div>
  );
}

import { Async } from "@/components/ui";
import { useNewsWeekly } from "../api";
import { fmt } from "../model/view";
import styles from "../News.module.css";
import { Section } from "./Section";

/** The weekly learning review (`GET news/weekly`, read only: nothing is recorded). */
export function WeeklyReview() {
  const q = useNewsWeekly();
  return (
    <Async q={q}>
      {(w) => (
        <article className={styles.card} data-testid="news-weekly">
          <div className={styles.kicker}>Week ending {fmt(w.week_ending)}</div>
          <h3 className={styles.headline}>Weekly learning review</h3>
          <Section title="Biggest relevant developments">
            {w.top.length ? (
              <ol>
                {w.top.map((x) => (
                  <li key={x.event_id}>
                    {x.headline} <span className={styles.faint}>— {x.state}</span>
                  </li>
                ))}
              </ol>
            ) : (
              "A quiet week."
            )}
          </Section>
          <Section title="Caught early">{w.caught_early.join(", ") || "None this week."}</Section>
          <Section title="Missed">{w.missed.join(", ") || "None confirmed this week."}</Section>
          <Section title="Strongest pattern">{w.pattern}</Section>
          <Section title="One sourcing lesson">{w.sourcing_lesson}</Section>
          <Section title="One VC lesson">
            <b>{w.vc_lesson.title}</b> {w.vc_lesson.text}
          </Section>
        </article>
      )}
    </Async>
  );
}

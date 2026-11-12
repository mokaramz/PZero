import type { Meta, Signal } from "@/features/conviction/model/types";
import { cx } from "@/lib/format";
import { emptySlotsLabel } from "../model/slots";
import { RadarCard, type CardPick } from "./RadarCard";
import styles from "../Radar.module.css";

/** One Radar list. A slotted list (`slots` > 0) ends with its empty slots as ONE quiet line — the count stays exact,
 *  the page stays about real companies. */
export function RadarSection({
  title,
  list,
  slots = 0,
  gated,
  meta,
  pick,
}: {
  title: string;
  list: Signal[];
  slots?: number;
  gated?: boolean;
  meta?: Meta;
  pick: CardPick;
}) {
  const empty = Math.max(0, slots - list.length);
  return (
    <section className={styles.section} aria-label={title}>
      <h3 className={styles.sectionTitle}>{title}</h3>
      {list.map((e) => (
        <RadarCard key={e.slug} e={e} gated={gated} meta={meta} pick={pick} />
      ))}
      {empty > 0 && (
        <div className={cx(styles.card, styles.empty)} data-testid="radar-empty" data-empty={empty}>
          {emptySlotsLabel(list.length, slots)}: empty — no candidate met the bar (left empty on purpose)
        </div>
      )}
    </section>
  );
}

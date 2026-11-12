import { cx } from "@/lib/format";
import { chipDots, chipTitle, splitRegistry } from "../model/registry";
import type { CityRegistry as Registry, RegistryCity } from "../model/types";
import styles from "../Ecosystems.module.css";

/** The city chips: curated cities, then the cities detected in the startup, event and people data. Each chip carries four
 *  dots (startups · events · people · verified institutions); a click opens that city. */
export function CityRegistry({ r, q, city, onPick }: { r: Registry; q: string; city: string; onPick: (c: string) => void }) {
  const { curated, detected } = splitRegistry(r, q);
  const chip = (x: RegistryCity) => (
    <button
      key={x.name}
      type="button"
      aria-pressed={x.name === city}
      className={cx(styles.cityChip, x.name === city && styles.cityOn)}
      onClick={() => onPick(x.name)}
      title={chipTitle(x)}
    >
      {x.name}
      {!x.curated && <small className="muted"> detected</small>}
      <span className={styles.dots} aria-hidden>
        {chipDots(x).map((on, i) => (
          <i key={i} className={cx(on && styles.dotOn)} />
        ))}
      </span>
    </button>
  );
  return (
    <div className={styles.registry} data-testid="city-registry">
      <div className={styles.grp} data-testid="registry-curated">
        <div className={styles.grpHd}>
          Curated ecosystem intelligence <span className="muted">— {r.curated_count} cities with verified institutions and deeper pages</span>
        </div>
        <div className={styles.chips}>{curated.length ? curated.map(chip) : <span className="muted small">no match</span>}</div>
      </div>
      <div className={styles.grp} data-testid="registry-detected">
        <div className={styles.grpHd}>
          Detected sourcing coverage{" "}
          <span className="muted">— {r.detected_count} more cities/regions appearing in your startup, event and people data (no curated intelligence yet)</span>
        </div>
        <div className={styles.chips}>
          {detected.length ? detected.map(chip) : <span className="muted small">none detected yet — run scans, add events and people</span>}
        </div>
      </div>
      <p className="muted small">
        {r.note} Dots: startups · events · people · verified institutions. Add curated cities or institutions in <code>ecosystems.json</code> — no code change
        needed.
      </p>
    </div>
  );
}

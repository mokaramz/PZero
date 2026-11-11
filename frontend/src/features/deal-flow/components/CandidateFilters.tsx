import { GroupedFilters } from "@/components/attention";
import { Chip } from "@/components/ui";
import { NOT_PORTED } from "../model/deferred";
import type { NaFilter, Workspace } from "../model/geo";
import { FILTERS, type Filter } from "../model/list";
import { DEFERRED_FILTERS } from "../model/view";
import { useDeferred } from "./Deferred";
import styles from "../DealFlow.module.css";

/** The same filters, grouped by purpose: ATTENTION (the everyday four, always visible); pipeline states and machine /
 *  admin views live under "More filters" — one click away, and the active one is named on the closed button. */
const ATTENTION_FILTERS: Filter[] = ["top", "new", "thisrun", "pre"];
const MORE_GROUPS: Array<{ label: string; values: Filter[] }> = [
  { label: "Pipeline", values: ["research", "watch", "kept", "rejected"] },
  { label: "Machine", values: ["triage", "review", "baseline"] },
];
const NA_SUB: ReadonlyArray<readonly [NaFilter, string]> = [
  ["both", "USA + Canada"],
  ["us", "USA"],
  ["ca", "Canada"],
];

type Props = {
  ws: Workspace;
  naf: NaFilter;
  setNaf: (v: NaFilter) => void;
  filter: Filter;
  setFilter: (f: Filter) => void;
  theme: string;
  setTheme: (t: string) => void;
  themes: Record<string, string>;
  im: boolean;
  setIm: (v: boolean) => void;
};

function FilterChip({ value, label, on, onPick }: { value: Filter; label: string; on: boolean; onPick: (f: Filter) => void }) {
  return (
    <Chip on={on} onClick={() => onPick(value)} data-filter={value}>
      {label}
    </Chip>
  );
}

/** The Agent Review Queue lists machine analyses — not ported yet, so its chip stays in place, disabled. */
function DeferredFilterChip({ value, label }: { value: Filter; label: string }) {
  const d = useDeferred(NOT_PORTED.reviewQueue);
  return (
    <>
      <Chip on={false} data-filter={value} {...d.props}>
        {label}
      </Chip>
      {d.note}
    </>
  );
}

export function CandidateFilters({ ws, naf, setNaf, filter, setFilter, theme, setTheme, themes, im, setIm }: Props) {
  const chip = (f: { value: Filter; label: string }) =>
    DEFERRED_FILTERS.has(f.value) ? (
      <DeferredFilterChip key={f.value} value={f.value} label={f.label} />
    ) : (
      <FilterChip key={f.value} value={f.value} label={f.label} on={filter === f.value} onPick={setFilter} />
    );
  const activeMore =
    [!ATTENTION_FILTERS.includes(filter) ? FILTERS.find((f) => f.value === filter)?.label : "", theme ? (themes[theme] ?? theme) : "", im ? "IM lens" : ""]
      .filter(Boolean)
      .join(" · ") || undefined;
  return (
    <GroupedFilters
      testId="df-filters"
      view={
        ws === "na" ? (
          <span className={styles.naSub}>
            {NA_SUB.map(([v, l]) => (
              <Chip key={v} on={naf === v} onClick={() => setNaf(v)}>
                {l}
              </Chip>
            ))}
          </span>
        ) : undefined
      }
      attention={FILTERS.filter((f) => ATTENTION_FILTERS.includes(f.value)).map(chip)}
      activeMore={activeMore}
      more={
        <>
          <select value={theme} onChange={(e) => setTheme(e.target.value)} aria-label="Project A theme">
            <option value="">All Project A themes</option>
            {Object.entries(themes).map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
          {MORE_GROUPS.map((g) => (
            <span key={g.label} className={styles.fGroup} role="group" aria-label={g.label}>
              <span className={styles.fLabel}>{g.label}</span>
              {FILTERS.filter((f) => g.values.includes(f.value)).map(chip)}
              {g.label === "Machine" && (
                <Chip on={im} onClick={() => setIm(!im)} title="Investment lens — ranking only, nothing is rejected">
                  Investment manager lens
                </Chip>
              )}
            </span>
          ))}
        </>
      }
    />
  );
}

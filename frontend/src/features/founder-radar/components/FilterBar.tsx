import { useFr } from "../context";
import { sourceOptions, themeOptions, type Filters } from "../model/logic";
import styles from "../FounderRadar.module.css";

type Opt = { v: string; t: string };
const plain = (xs: string[]): Opt[] => xs.map((v) => ({ v, t: v }));

const STATUSES = ["explicit founder", "building now", "pre-company", "founder claim (unverified)", "researcher", "unknown"];
const IDENTITIES = ["resolved", "verified by operator", "needs identity resolution"];
/** Signal age keeps the browser clock (review 026a decision g). */
const AGES: Opt[] = [
  { v: "7", t: "≤ 7 days" },
  { v: "30", t: "≤ 30 days" },
  { v: "90", t: "≤ 90 days" },
];

/** The Research Queue filters: founder status, theme, identity, region / country / city, source, signal age and four
 *  evidence checks. Each select is named by its "any" option ("founder status", "region", …). */
export function FilterBar({ filters: f, setFilters }: { filters: Filters; setFilters: (f: Filters) => void }) {
  const { data } = useFr();
  const G = data.geo ?? { regions: [], countries: [], cities: [] };
  const set = (k: keyof Filters, v: string | boolean) => setFilters({ ...f, [k]: v });
  const sel = (k: keyof Filters, label: string, opts: Opt[]) => (
    <select aria-label={label.split(":")[0]} value={String(f[k])} onChange={(e) => set(k, e.target.value)}>
      <option value="">{label}</option>
      {opts.map((o, i) => (
        <option key={o.v + ":" + i} value={o.v}>
          {o.t}
        </option>
      ))}
    </select>
  );
  const chk = (k: keyof Filters, label: string) => (
    <label className={styles.check}>
      <input type="checkbox" checked={!!f[k]} onChange={(e) => set(k, e.target.checked)} /> {label}
    </label>
  );
  return (
    <div className={styles.filters} data-testid="fr-filters">
      {sel("status", "founder status: any", plain(STATUSES))}
      {sel("theme", "Project A theme: any", plain(themeOptions(data.people)))}
      {sel("identity", "identity: any", plain(IDENTITIES))}
      {sel(
        "region",
        "region: all",
        G.regions.map((r) => ({ v: r.region, t: `${r.region} · ${r.people} people · ${r.cities.filter((c) => c.last_ok).length}/${r.cities.length} cities ever scanned` })),
      )}
      {sel(
        "country",
        "country: all",
        G.countries.map((c) => ({ v: c.country, t: `${c.country} · ${c.people} people · ${c.attempted}/${c.cities} cities scanned` })),
      )}
      {sel(
        "city",
        "city: all",
        G.cities.map((c) => ({ v: c.city, t: `${c.city} (${c.country}) · ${c.people} · ${c.last_ok ? "scanned " + c.last_ok : c.status}` })),
      )}
      {sel("source", "source: any", plain(sourceOptions(data.people)))}
      {sel("age", "signal age: any", AGES)}
      {chk("ent", "entrepreneurial evidence")}
      {chk("tech", "technical evidence")}
      {chk("recent", "recent activity / transition")}
      {chk("warm", "warm path available")}
    </div>
  );
}

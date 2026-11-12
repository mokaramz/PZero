/** The city registry's pure rules (the old page kept them inline). */
import type { CityRegistry, RegistryCity } from "./types";

/** The city the page opens on without a `?city=` deep link; travel hours are counted from here. */
export const HOME_CITY = "Karlsruhe";

/** The city search: a case-insensitive substring of the name, split into curated then detected, registry order kept. */
export function splitRegistry(r: CityRegistry, q: string): { curated: RegistryCity[]; detected: RegistryCity[] } {
  const f = (x: RegistryCity) => !q || x.name.toLowerCase().includes(q.toLowerCase());
  return { curated: r.cities.filter((x) => x.curated && f(x)), detected: r.cities.filter((x) => !x.curated && f(x)) };
}

/** A chip's four dots: startups · events · people (each "yes") · verified institutions. */
export function chipDots(x: RegistryCity): [boolean, boolean, boolean, boolean] {
  const s = x.status;
  return [s.startups === "yes", s.events === "yes", s.people === "yes", s.institutions === "verified"];
}

/** A chip's tooltip: the four counts and the last refresh when there is one. */
export function chipTitle(x: RegistryCity): string {
  const c = x.coverage;
  return `startups ${c.startups} · events ${c.events} · people ${c.people} · institutions ${c.institutions}${c.last_refresh ? ` · last refresh ${c.last_refresh}` : ""}`;
}

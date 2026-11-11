/**
 * A small network (shaped like the old e2e capture, kept as data in `network.json`): every segment rule hit at least
 * once, three cities, a chain with an introducer and recommendations, a person with every field (the edit drawer), and
 * the talent forest. The derived fields (`due`, `days_since_touch`, `introduced_by_name`, `recommended_names`) are as
 * the server lists them on 2026-11-11.
 */
import type { GraphPayload, PeoplePayload, Person } from "../model/types";
import data from "./network.json";

export const TODAY = "2026-11-11";

export const STRENGTHS = { met_once: "Met once", warm: "Warm", strong: "Strong", close: "Close" };
export const POTENTIAL = { none: "—", maybe: "Maybe", high: "High", building: "Building now" };

export const people = (): Person[] => structuredClone(data.people) as Person[];

export function peoplePayload(): PeoplePayload {
  return { people: people(), strengths: { ...STRENGTHS }, potential: { ...POTENTIAL } };
}

export const graph = (): GraphPayload => structuredClone(data.graph) as GraphPayload;

export const PIPE = { signals: [{ slug: "aereus", company: "Aereus", sc: { provisional: 49 } }] };

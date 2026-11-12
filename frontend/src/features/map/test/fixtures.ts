/** Invented Map payloads (adapted from the old `e2e/tests/fixtures/map/data.json` and `map.spec.ts`): every company,
 *  person, event and institution name is made up; the cities and their coordinates are real places, and the home base
 *  is the app's own default (Karlsruhe). The browser clock for these is 2026-09-26 10:00 Berlin (`PINS_NOW`), the
 *  weekend of 26-27 Sep, as the old spec froze it. */
import type { GeoDetail, GeoEco, GeoIntel, MapData, MapEvent, MapStartup, SourcingDay } from "../model/types";

export const PINS_NOW = new Date("2026-09-26T10:00:00+02:00");
export const INTEL_NOW = new Date("2026-10-12T10:00:00+02:00");

const KA = { lat: 49.0069, lng: 8.4037 };
const HD = { lat: 49.3988, lng: 8.6724 };
const MUC = { lat: 48.1351, lng: 11.582 };
const BER = { lat: 52.52, lng: 13.405 };
const HEL = { lat: 60.1699, lng: 24.9384 };
const ZRH = { lat: 47.3769, lng: 8.5417 };
const CPH = { lat: 55.6761, lng: 12.5683 };
const STR = { lat: 48.7758, lng: 9.1829 };
const FRA = { lat: 50.1109, lng: 8.6821 };

const startup = (slug: string, company: string, at: { lat: number; lng: number }, extra: Partial<MapStartup>): MapStartup => ({
  slug,
  company,
  ...at,
  stage: "pre_seed",
  stage_label: "Pre-seed closed",
  score: 50,
  verified: false,
  archetype: "",
  one_liner: `${company} one-liner`,
  location: "",
  funding: "",
  timing: "Raising in the next six months",
  sent_to_omar: "",
  conflict: "none",
  why: "",
  founders: "",
  ...extra,
});

const event = (id: string, name: string, city: string, at: { lat: number; lng: number }, start: string, extra: Partial<MapEvent>): MapEvent => ({
  id,
  name,
  ...at,
  city,
  start,
  type: "UNKNOWN",
  type_label: "Type not evidenced",
  when: { weekend: false },
  score: 50,
  band: "WORTH A LOOK",
  why: `${name} gathers early founders`,
  url: "",
  deadline: "",
  organizer: "",
  audience: "",
  status: "candidate",
  past: false,
  ...extra,
});

/** 8 startups, 8 events (one past, one more than 30 days out), 4 people (none carries a `city`, as on the real
 *  answer), 4 universities & labs and 2 hubs; one company has no coordinates. */
export function pins(): MapData {
  return {
    startups: [
      startup("kestrel-robotics", "Kestrel Robotics", MUC, {
        stage: "grant_angel",
        stage_label: "Grant or angel money only",
        score: 49,
        archetype: "#5 Defence software layer",
        location: "Munich, Germany",
        funding: "€300k angel",
      }),
      startup("lumen-ledger", "Lumen Ledger", BER, { score: 68, archetype: "#1 Vertical AI agent", location: "Berlin" }),
      startup("northwind-assure", "Northwind Assure", HEL, { score: 71, location: "Helsinki", conflict: "potential_conflict" }),
      startup("quillmark", "Quillmark", ZRH, {
        stage: "grant_angel",
        stage_label: "Grant or angel money only",
        score: 45,
        archetype: "#3 Regulated-by-design financial infrastructure",
        location: "Zürich",
      }),
      startup("skylark-freight", "Skylark Freight", CPH, {
        score: 65,
        verified: true,
        archetype: "#6 Dual-use autonomous platforms",
        location: "Copenhagen",
        sent_to_omar: "2026-09-20",
      }),
      startup("otterfield-analytics", "Otterfield Analytics", HD, {
        stage: "pre_company",
        stage_label: "Pre-company / no round",
        score: 64,
        archetype: "#4 Insurance infrastructure",
        location: "Heidelberg",
      }),
      startup("brightforge-ai", "Brightforge AI", KA, { score: 45, archetype: "#1 Vertical AI agent", location: "Karlsruhe, Germany", founders: "Robin Example" }),
      startup("fernhollow-materials", "Fernhollow Materials", MUC, {
        score: 69,
        archetype: "#14 Sovereignty-framed bio-manufacturing / materials",
        location: "Munich",
        why: "Materials discovery with its own synthesis lab",
      }),
    ],
    events: [
      event("forge-demo-day", "Forge Demo Day & Pitch Night", "Karlsruhe", KA, "2026-09-27T18:00:00+02:00", {
        type: "demo_day",
        type_label: "Demo day",
        when: { weekend: true },
        score: 82,
        band: "HIGH-SIGNAL",
        organizer: "Forge Hub",
        deadline: "2026-09-26",
        url: "https://forge.example.org/demo-day",
      }),
      event("spree-founder-dinner", "Spree Founder Dinner", "Berlin", BER, "2026-10-01T19:30:00", { type: "accelerator", type_label: "Accelerator event", score: 70 }),
      event("alpine-robotics-hackathon", "Alpine Robotics Hackathon", "Zürich", ZRH, "2026-10-02", { type: "hackathon", type_label: "Hackathon", score: 76 }),
      event("main-wine-evening", "Main Wine Evening", "Frankfurt", FRA, "2026-10-03", { score: 12 }),
      event("neckar-builders-night", "Neckar Builders Night", "Stuttgart", STR, "2026-10-06", { score: 40 }),
      event("isar-defence-meetup", "Isar Defence Founders Meetup", "Munich", MUC, "2026-10-15T19:00:00", { type: "accelerator", type_label: "Accelerator event", score: 74 }),
      event("alder-energy-day", "Alder Energy Innovation Day", "Karlsruhe", KA, "2026-10-30", { type: "university", type_label: "University entrepreneurship", score: 58 }),
      event("summer-founder-meetup", "Summer Founder Meetup", "Karlsruhe", KA, "2026-09-10", {
        type: "founder_meetup",
        type_label: "Founder meetup / pitch night",
        score: 50,
        past: true,
      }),
    ],
    people: [
      {
        id: "p-mara-lindqvist",
        name: "Mara Lindqvist",
        ...KA,
        role: "PhD researcher, legged robots",
        company: "Alder Robotics Lab",
        why: "Built the lab's quadruped controller; talks about spinning out.",
        strength: "warm",
        potential: "high",
        next_action: "Coffee to hear the spin-out plan",
        watch: false,
      },
      {
        id: "p-ines-halvorsen",
        name: "Ines Halvorsen",
        ...ZRH,
        role: "Research engineer",
        company: "Limmat AI Centre",
        why: "Runs an agents reading group.",
        strength: "met_once",
        potential: "maybe",
        next_action: "SUGGESTED: follow up within 48h while the conversation is warm",
        watch: true,
      },
      {
        id: "p-teo-marchetti",
        name: "Teo Marchetti",
        ...STR,
        role: "Senior engineer, industrial vision",
        company: "Neckar Werke",
        why: "Quietly building a factory-inspection side project.",
        strength: "close",
        potential: "maybe",
        next_action: "Ask about the side project",
        watch: false,
      },
      {
        id: "p-jonah-weller",
        name: "Jonah Weller",
        ...MUC,
        role: "CTO",
        company: "Kestrel Robotics",
        why: "Second-time founder.",
        strength: "strong",
        potential: "building",
        next_action: "",
        watch: false,
      },
    ],
    orgs: [
      { name: "Alder Institute of Technology", kind: "university", city: "Karlsruhe", lat: 49.0119, lng: 8.4158, why: "Robotics faculty", url: "https://ait.example.edu" },
      { name: "Rheinfeld Research Lab", kind: "lab", city: "Karlsruhe", lat: 49.0128, lng: 8.4244, why: "Applied AI and robotics", url: "https://rrl.example.org" },
      { name: "Forge Hub", kind: "hub", city: "Karlsruhe", lat: 49.0094, lng: 8.4108, why: "Student founder community", url: "https://forge.example.org" },
      { name: "Isar Polytechnic", kind: "university", city: "Munich", lat: 48.1497, lng: 11.5679, why: "Deep-tech spinouts", url: "https://isar.example.edu" },
      { name: "Limmat Polytechnic", kind: "university", city: "Zürich", lat: 47.3763, lng: 8.5476, why: "Robotics and AI", url: "https://limmat.example.edu" },
      { name: "Isar Founder Works", kind: "hub", city: "Munich", lat: 48.2656, lng: 11.6681, why: "Venture programme", url: "https://works.example.org" },
    ],
    home: { city: "Karlsruhe", ...KA },
    no_geo: ["Quiet Harbor Systems"],
    new_signals: 241,
  };
}

const ECO = (city: string, state: GeoEco["state"], at: { lat: number; lng: number }, extra: Partial<GeoEco> = {}): GeoEco => ({
  city,
  ...at,
  country: "DE",
  state,
  early: 0,
  late: 0,
  companies: 0,
  events: 0,
  high_signal_events: 0,
  scout: 0,
  conviction: 0,
  convergence: { converging: false, families: [], family_labels: [], signals: 0, entities: 0 },
  coverage: { assessed: true, families: {}, strong: 6, weak: [], visibility: "GOOD" },
  reasons: [],
  travel: { bucket: "DAY TRIP", km: 253, text: "~3 h from Karlsruhe (approximate city table)" },
  ...extra,
});

export const NOTE = "This shows Project Zero activity / opportunity signals and visibility — not company investment scores.";

/** Munich (VERY ACTIVE, converging, founder formation NOT COVERED), Berlin (NORMAL, coverage not assessed) and Tallinn
 *  (UNDER-COVERED, POOR visibility); 12 Deal Flow candidates could not be placed. */
export function intel(): GeoIntel {
  return {
    ecosystems: [
      ECO("Munich", "VERY ACTIVE", MUC, {
        early: 5,
        companies: 6,
        events: 2,
        high_signal_events: 1,
        scout: 1,
        convergence: {
          converging: true,
          families: ["event", "research", "scout00"],
          family_labels: ["Event", "University / research spinout", "Scout 00 discovery"],
          signals: 6,
          entities: 6,
        },
        coverage: { assessed: true, families: { "Founder formation": "NOT COVERED", Events: "STRONG" }, strong: 6, weak: ["Founder formation"], visibility: "GOOD" },
        reasons: ["5 early signal(s) from 3 source(s)", "1 Scout 00 discovery", "1 high-signal event(s) in the next 45 days", "Weak visibility: founder formation"],
      }),
      ECO("Berlin", "NORMAL", BER, {
        companies: 3,
        events: 1,
        coverage: { assessed: false, families: {}, strong: 0, weak: [], visibility: "NOT ASSESSED" },
        reasons: ["3 companies, none early"],
        travel: { bucket: "OVERNIGHT", km: 520, text: "~6 h from Karlsruhe (approximate city table)" },
      }),
      ECO("Tallinn", "UNDER-COVERED", { lat: 59.437, lng: 24.754 }, {
        country: "EE",
        coverage: { assessed: true, families: {}, strong: 0, weak: ["Universities / research"], visibility: "POOR" },
        travel: { bucket: "OVERNIGHT", km: 1700, text: "1700 km — travel time not calculated" },
      }),
    ],
    counts: { "VERY ACTIVE": 1, NORMAL: 1, "UNDER-COVERED": 1 },
    where_to_go: {
      ranked: [
        {
          city: "Munich",
          state: "VERY ACTIVE",
          why: ["5 early signal(s) from 3 source(s)", "1 high-signal event"],
          travel: { bucket: "DAY TRIP", km: 253, text: "~3 h from Karlsruhe (approximate city table)" },
        },
      ],
      note: "Ranked by early signals — not by volume.",
    },
    cards: [
      { id: "go", title: "Where to go", text: "Munich — 5 early signal(s)", city: "Munich" },
      { id: "gap", title: "Coverage gap", text: "Munich: founder formation weak", city: "Munich" },
    ],
    unplaced: { deal_flow: 12 },
    home: { city: "Karlsruhe" },
    built_at: "2026-10-12T10:00:00",
    note: NOTE,
    legend: {
      "VERY ACTIVE": "early signals from several independent families",
      NORMAL: "activity, but little that is early",
      "UNDER-COVERED": "little detected AND weak visibility — we do not know, it is not 'cold'",
    },
  };
}

/** Munich's "Why here?": a Scout 00 card without a candidate, an absorbed Deal Flow candidate, a Conviction company
 *  (linked by name), one person, one HIGH-SIGNAL event at 18:00, one news story, a source candidate, two institutions. */
export function munich(): GeoDetail {
  const e = intel().ecosystems[0];
  const d: GeoDetail = {
    ...e,
    scout: [],
    why_here: e.reasons,
    companies: [
      {
        name: "Pallas Grip",
        kind: "scout",
        pz_state: "Scout Intake · NEW INTAKE",
        first_seen: "2026-10-12",
        stage: "pre-company",
        why: "Robotics spin-off from Isar Polytechnic",
        early: true,
        late: false,
        score: "",
        machine: "",
        scout: "009",
        watch: false,
        news: [],
        families: ["Scout 00 discovery"],
        link: "/scout-intake",
        next_action: "Review the Scout 00 card",
      },
      {
        name: "Torvane Systems",
        kind: "company",
        pz_state: "Deal Flow · new",
        first_seen: "2026-10-01",
        stage: "pre-seed",
        why: "Drone swarm autonomy",
        early: true,
        late: false,
        score: "",
        machine: "machine triage: advance",
        scout: "",
        watch: true,
        news: ["Torvane Systems joins a regional accelerator"],
        families: ["Accelerator"],
        link: "/deal-flow?candidate=cand-torvane",
        next_action: "Open the record and decide",
      },
      {
        name: "Kestrel Robotics",
        kind: "company",
        pz_state: "Conviction · active",
        first_seen: "2026-08-14",
        stage: "grant / angel",
        why: "",
        early: false,
        late: true,
        score: "provisional 49",
        machine: "",
        scout: "",
        watch: false,
        news: [],
        families: ["Conviction"],
        link: "/conviction?company=Kestrel Robotics",
        next_action: "See the workspace",
      },
    ],
    people: [
      {
        label: "Jonah Weller",
        role: "CTO",
        org: "Kestrel Robotics",
        why: "second-time founder",
        relationship: "strong",
        next_action: "",
        link: "/network?person=p-jonah-weller",
      },
    ],
    events: [
      {
        label: "Isar Pitch Night",
        date: "2026-10-20",
        time: "18:00",
        band: "HIGH-SIGNAL",
        why: "founder: HIGH",
        audience: "",
        registration: "open",
        price: "free",
        url: "",
        link: "/events?event=isar-pitch-night",
      },
    ],
    news: [{ headline: "Torvane Systems joins a regional accelerator", date: "2026-10-05", source: "Example Wire" }],
    institutions: [
      { name: "Isar Polytechnic", kind: "university", why: "", url: "" },
      { name: "Isar Founder Works", kind: "hub", why: "", url: "" },
    ],
    source_candidates: [{ name: "Isar Founder Directory", state: "DISCOVERED", family: "founder_move", url: "https://directory.example.de/founders" }],
    next_best_action: "Decide on Isar Pitch Night (2026-10-20) — registration is yours to do.",
    note: `${NOTE} Machine proposals and provisional scores are labelled as such; only verified scores are official.`,
  };
  d.scout = d.companies.filter((c) => c.kind === "scout");
  return d;
}

export function plan(date: string): SourcingDay {
  return {
    city: "Munich",
    date,
    weekday: "Tuesday",
    objective: "University / research spinout",
    travel: intel().ecosystems[0].travel,
    before_you_go: [
      { name: "Pallas Grip", why: "Robotics spin-off from Isar Polytechnic", link: "/scout-intake" },
      { name: "Torvane Systems", why: "Drone swarm autonomy", link: "/deal-flow?candidate=cand-torvane" },
    ],
    people: [{ name: "Jonah Weller", role: "CTO", org: "Kestrel Robotics", relationship: "strong", why: "" }],
    stops: [
      { time: "you choose (opening hours not checked)", what: "Isar Polytechnic (university)", why: "", kind: "institution" },
      { time: "18:00", what: "Isar Pitch Night", why: "", kind: "event" },
    ],
    events_other_days: [],
    bring_back: ["new companies (add them to Deal Flow)", "source candidates (System health → New sources)"],
    coverage_caveat: ["Founder formation"],
    note: "PLAN ONLY — Project Zero does not message anyone, register you or book travel.",
    empty: false,
  };
}

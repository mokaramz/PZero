/**
 * A small synthetic Events payload (every name invented), as the server lists it on 2026-11-11 (a Wednesday, Berlin):
 * a priority high-signal event and a title-only listing on the same day, a planned event that needs verification, a
 * general / rejected event, an attended past event, an open lead and one Scout 00 suggestion not on Events yet.
 */
import type { EventHealthPayload, EventRecord, EventsPayload, ScoutReport, WeekendMission, WsigItem } from "../model/types";

export const TODAY = "2026-11-11";

const place = (city: string, country: string, country_name: string) => ({ city, area: city, country, country_name, label: `${city}, ${country_name}`, area_label: `${city}, ${country_name}` });

function ev(p: Partial<EventRecord> & { id: string; name: string; date: string; days: number }): EventRecord {
  const { date, days, ...rest } = p;
  return {
    status: "new",
    type: "founder_meetup",
    city: "Berlin",
    place: place("Berlin", "DE", "Germany"),
    start: `${date}T18:00:00`,
    when: { start_date: date, start_time: "18:00", days_until: days },
    days_until: days,
    past: days < 0,
    eligibility: { tier: "HIGH-SIGNAL", label: "High-signal", reasons: [] },
    sc: { total: 39, band: "", evidence: [] },
    themes: [],
    scout: null,
    sources: [],
    ...rest,
  };
}

export function events(): EventRecord[] {
  return [
    ev({
      id: "ev-alpha",
      name: "Founders Breakfast Alpha",
      date: "2026-11-13",
      days: 2,
      organizer: "Alpha Collective",
      sc: { total: 69, band: "", evidence: [] },
      themes: ["AI"],
      registration_url: "https://example.org/alpha",
      url: "https://example.org/alpha",
      assessment: { founder: "HIGH", networking: "MEDIUM", confidence: "STRUCTURED (JSON-LD)", factors: [{ dimension: "founder", band: "HIGH", evidence: ["founders"] }] },
    }),
    ev({ id: "ev-quiet", name: "Open Builders Night", date: "2026-11-13", days: 2, eligibility: { tier: "NEEDS REVIEW", reasons: ["title only"] }, when: { start_date: "2026-11-13", start_time: "", days_until: 2 } }),
    ev({
      id: "ev-gamma",
      name: "Gamma Demo Day",
      date: "2026-11-20",
      days: 9,
      type: "demo_day",
      status: "planned",
      city: "Munich",
      place: place("Munich", "DE", "Germany"),
      eligibility: { tier: "NEEDS REVIEW", label: "Needs review", reasons: ["price not stated", "organizer not stated"] },
      action: { state: "sold_out" },
    }),
    ev({ id: "ev-mixer", name: "General Business Mixer", date: "2026-11-18", days: 7, eligibility: { tier: "REJECTED", label: "General", reasons: ["general networking event"] } }),
    ev({ id: "ev-went", name: "Past Robotics Meetup", date: "2026-11-01", days: -10, status: "attended" }),
  ];
}

export function reports(): ScoutReport[] {
  return [
    {
      key: "scout-harbor",
      name: "Harbor Summit 2026",
      date: "2026-11-24",
      days_until: 13,
      city: "Hamburg",
      place: place("Hamburg", "DE", "Germany"),
      p_class: "P2",
      ev_class: "EV-A",
      why: "Dense founder audience",
      action: "",
      cycles: ["008"],
      url: "https://example.org/harbor",
      report_ids: ["se-008-1"],
      statuses: ["NEW"],
      themes: ["Climate"],
      tracked_event_id: "",
    },
  ];
}

export function eventsPayload(): EventsPayload {
  return {
    events: events(),
    leads: [{ id: "lead-1", title: "Spring Hack Weekend", date: "2026-12-05", city: "Berlin", url: "https://example.org/lead", source: "watcher", confidence: "LIKELY", detected_on: "2026-11-10" }],
    weekend_window: ["2026-11-14", "2026-11-15"],
    today: TODAY,
    types: { founder_meetup: "Founder meetup", demo_day: "Demo day" },
    dims: { founder_density: { label: "Founder density", max: 25, ladder: [[16, "some founders"]] } },
    dim_order: ["founder_density"],
    manual_sources: [{ name: "Community calendar", url: "https://example.org/cal", how: "Scan the list" }],
    pages: ["https://example.org/page"],
    ics_count: 1,
    scout_reports: reports(),
    source_count: { luma: 2, jsonld: 1 },
  };
}

export const health = (): EventHealthPayload => ({
  scan_time: "2026-11-10 08:00",
  totals: { attempted: 5, ok: 4, productive: 3, failed: 1 },
  sources: [{ name: "Example calendar", status: "ok", raw: 4, future: 3, ingested: 3 }],
});

export const wsig = (days: string): { ranked: WsigItem[] } => ({
  ranked:
    days === "30"
      ? []
      : [{ id: "ev-alpha", name: "Founders Breakfast Alpha", city: "Berlin", start: "2026-11-13", event_score: 69, rank: 80, reason: "strong founder evidence", priority: "P1", url: "https://example.org/alpha" }],
});

export const missions = (): { missions: WeekendMission[] } => ({
  missions: [{ city: "Berlin", travel_hours: 3, strength: "Consider", plan: [{ when: "2026-11-13", time: "18:00", what: "Founders Breakfast Alpha", why: "founder evidence" }], expected: "Two warm intros" }],
});

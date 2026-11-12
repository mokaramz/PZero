/**
 * The Founder Radar test data (invented names only), kept as JSON so the mocked Playwright spec reads the same shapes
 * (`e2e/tests/fixtures/founder-radar/`):
 * - 13 people: two Kelpwise GmbH founders with unresolved identities (promotion blocked), two resolved Borealis Robotics
 *   founders, a Quillstone AI founder with a ready Scout Packet, a login-only GitHub handle with a proposed identity, an
 *   insufficient-evidence builder, a researcher, one watchlisted, one in the Network, one user-provided Network contact
 *   without evidence (kept out of the radar), one dismissed and one LinkedIn-export import;
 * - 4 company leads (one researched with 9 proposal rows, one with confirmed facts, one unresearched, one without an
 *   official domain), 3 top leads and 1 near match;
 * - a scan health report, the source coverage, the geo options and the metrics snapshot.
 */
import type { FounderRadar, Proposals } from "../model/types";
import borealisJson from "./proposals_borealis.json";
import radarJson from "./founder_radar.json";
import kelpwiseJson from "./proposals_kelpwise.json";

export const KELPWISE = "dom:kelpwise.example";
export const BOREALIS = "dom:borealis.example";

export const radar = (): FounderRadar => structuredClone(radarJson) as unknown as FounderRadar;
export const kelpwise = (): Proposals => structuredClone(kelpwiseJson) as unknown as Proposals;
export const borealis = (): Proposals => structuredClone(borealisJson) as unknown as Proposals;

export const ID = {
  mira: "p-mira-talvik-1001",
  jonas: "p-jonas-brekke-1002",
  ilka: "p-ilka-moravec-1003",
  teo: "p-teo-haarberg-1004",
  sana: "p-sana-okafor-1005",
  grain: "p-grainhacker-1006",
  oskar: "p-oskar-lindqvist-1007",
  rhea: "p-rhea-castell-1008",
  wren: "p-wren-adebayo-1009",
  nils: "p-nils-farrow-1010",
  hana: "p-hana-sato-1011",
  dana: "p-dana-vale-1012",
  petra: "p-petra-lunde-1013",
} as const;

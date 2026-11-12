/**
 * The Validation test data (invented names only), kept as JSON so the mocked Playwright spec reads the same shapes
 * (`e2e/tests/fixtures/validation/`). The shapes and key order are the old `GET /api/validation` and
 * `GET /api/validation_scout_packet` answers:
 * - `validation.json`: a working month — 13 sources (12 shown), conversion for five groupings (no Scout lanes),
 *   human-vs-machine calibration with two disagreements, two misses and one false-positive audit, two outcomes, two
 *   Scout intake cycles, five daily snapshots (three series with 3+ numbers, pre-funding share with only 2), one data
 *   warning, two benchmark systems; News and the native bridge `{available: false, reason}`;
 * - `validation_empty.json`: an empty data folder (every metric NOT YET MEASURABLE, nothing recorded, one snapshot);
 * - `scout_packet.json`: the packet for the latest cycle, its News and source-network sections deferred.
 */
import type { Packet, ValidationPayload } from "../model/types";
import packetJson from "./scout_packet.json";
import emptyJson from "./validation_empty.json";
import fullJson from "./validation.json";

export const validation = (): ValidationPayload => structuredClone(fullJson) as unknown as ValidationPayload;
export const emptyValidation = (): ValidationPayload => structuredClone(emptyJson) as unknown as ValidationPayload;
export const packet = (): Packet => structuredClone(packetJson) as Packet;

/** The old write endpoints and their 027b paths: no test may ever see a request to one of them. */
export const WRITE_PATHS = /\/api\/(validation_(outcome|audit|retract|benchmark_import|scout_packet)|validation\/(outcome|audit|retract|benchmark_import))\b/;

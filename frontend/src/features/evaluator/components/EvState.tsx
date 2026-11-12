import { Badge } from "@/components/ui";
import { stateTone } from "../model/view";

/** A claim state as its badge (green sourced / verified, red contradiction, grey UNKNOWN, amber unverified). */
export function EvState({ st }: { st: string }) {
  return <Badge tone={stateTone(st)}>{st}</Badge>;
}

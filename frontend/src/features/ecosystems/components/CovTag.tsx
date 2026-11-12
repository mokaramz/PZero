import { Badge } from "@/components/ui";
import { stateTone } from "../model/coverage";
import type { CovState } from "../model/types";

/** A coverage state as a toned badge (the state is also its title). */
export function CovTag({ st }: { st: CovState | undefined }) {
  return (
    <Badge tone={stateTone(st)} title={st}>
      {st}
    </Badge>
  );
}

import { useState } from "react";

import { useToast } from "@/components/Toast";
import { fetchScoutPacket } from "./api";
import type { Packet } from "./model/types";

/** The prepared Scout 00 packet, kept by the page so it survives a visit to another question. Preparing it is a read
 *  (`GET validation/scout_packet`); a failure is a toast, the last packet stays. */
export function useScoutPacket() {
  const toast = useToast();
  const [packet, setPacket] = useState<Packet | null>(null);
  const [loading, setLoading] = useState(false);
  const prepare = (cycle: string) => {
    setLoading(true);
    fetchScoutPacket(cycle)
      .then(setPacket)
      .catch((e: unknown) => toast.show(`✕ Preparing the Scout 00 packet failed — ${e instanceof Error ? e.message : String(e)}`, "error"))
      .finally(() => setLoading(false));
  };
  return { packet, loading, prepare };
}

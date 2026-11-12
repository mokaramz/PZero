import { useState } from "react";

import { useToast } from "@/components/Toast";
import { fetchScoutPacket, LABEL, useMarkPacket } from "./api";
import type { Packet } from "./model/types";
import { CLIPBOARD_BLOCKED, markBody, NO_GENERATED, PACKET_COPIED } from "./model/writes";

/** The prepared Scout 00 packet, kept by the page so it survives a visit to another question.
 * - Preparing it is a read (`GET validation/scout_packet`); a failure is a toast, the last packet stays.
 * - "Copy & log handover" copies the text shown, and only once the copy succeeded logs the handover with that packet's
 *   `Generated` time and sha (decision f). A blocked clipboard is the old error toast and logs nothing; a packet that
 *   changed since it was prepared is refused by the server (409, the failure toast). */
export function useScoutPacket() {
  const toast = useToast();
  const mark = useMarkPacket();
  const [packet, setPacket] = useState<Packet | null>(null);
  const [loading, setLoading] = useState(false);
  const prepare = (cycle: string) => {
    setLoading(true);
    fetchScoutPacket(cycle)
      .then(setPacket)
      .catch((e: unknown) => toast.show(`✕ ${LABEL.packet} failed — ${e instanceof Error ? e.message : String(e)}`, "error"))
      .finally(() => setLoading(false));
  };
  const copyAndLog = async () => {
    if (!packet) return;
    try {
      await navigator.clipboard.writeText(packet.text);
    } catch {
      toast.show(CLIPBOARD_BLOCKED, "error");
      return;
    }
    toast.show(PACKET_COPIED, "ok");
    const body = markBody(packet);
    if (body) mark.mutate(body);
    else toast.show(`✕ ${LABEL.packet} failed — ${NO_GENERATED}`, "error");
  };
  return { packet, loading, prepare, copyAndLog };
}

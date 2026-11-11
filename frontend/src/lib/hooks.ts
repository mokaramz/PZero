import { useMutation, useQuery, useQueryClient, type UseQueryOptions } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "@/components/Toast";
import { actions, friendlyError, labelFor } from "./activity";
import { get, post, type Query } from "./api";

/** Cached GET. The query key is the endpoint + params, so `invalidate("people")` refreshes every people view. */
export function useApi<T>(path: string, query?: Query, options?: Partial<UseQueryOptions<T>>) {
  return useQuery<T>({
    queryKey: [path, query ?? {}],
    queryFn: ({ signal }) => get<T>(path, query, { signal }),
    ...options,
  });
}

/* ------------------------------------------------------------------ useAction */

export type ActionOptions<TRes> = {
  /** Endpoint names whose cached GETs become stale after success ([] for none, "*" for all — the default). */
  invalidates?: string[] | "*";
  success?: string | ((r: TRes) => string | undefined);
  /** Resolve (instead of throw) when a 2xx body carries an `error` field — for endpoints that answer
   *  "needs confirmation" style outcomes as `{ error, needs_confirmation }` with HTTP 200. */
  allowErrorField?: boolean;
  /** What the operator sees the instant they click ("Creating backup"); defaults to the action's standard verb. */
  label?: string;
  /** Inline-only feedback (the component renders its own result): no toast, still in Background activity. */
  quiet?: boolean;
};

/** A body of `{ started: false }` means the server (or the in-flight guard) did not run the action: PARTIAL. */
type StartedBody = { started?: boolean; reason?: string };

/** The activity state and the message for a successful POST (pure — shared by the toast and the activity dock). */
export function describeOutcome<TRes>(
  result: TRes,
  name: string,
  success?: string | ((r: TRes) => string | undefined),
): { state: "COMPLETE" | "PARTIAL"; message: string } {
  const res = (result ?? {}) as StartedBody;
  const custom = typeof success === "function" ? success(result) : success;
  if (res.started === false) return { state: "PARTIAL", message: custom || res.reason || `${name}: already running` };
  if (custom) return { state: "COMPLETE", message: custom };
  return {
    state: "COMPLETE",
    message: res.started ? `${name} — started; it runs in the background (see Background activity)` : `✓ ${name} — done`,
  };
}

/** The same action with the same input already in flight (a double click) never runs twice. */
const INFLIGHT = new Set<string>();

/** POST with toast feedback, a Background activity row and cache invalidation. */
export function useAction<TBody extends object, TRes = unknown>(
  path: string,
  { invalidates = "*", success, allowErrorField = false, label, quiet = false }: ActionOptions<TRes> = {},
) {
  const qc = useQueryClient();
  const toast = useToast();
  const name = label ?? labelFor(path);
  return useMutation<TRes, Error, TBody, { act: number }>({
    mutationFn: async (body) => {
      const key = `${path}|${JSON.stringify(body ?? {})}`;
      if (INFLIGHT.has(key)) return { started: false, reason: `${name} is already running.` } as TRes;
      INFLIGHT.add(key);
      try {
        return await post<TRes>(path, body, { allowErrorField });
      } finally {
        INFLIGHT.delete(key);
      }
    },
    // CLICK → immediate acknowledgement on every page (Background activity), before any network round trip
    onMutate: () => ({ act: actions.start(name) }),
    onSuccess: async (result, _body, ctx) => {
      if (invalidates === "*") await qc.invalidateQueries();
      else await Promise.all(invalidates.map((k) => qc.invalidateQueries({ queryKey: [k] })));
      void qc.invalidateQueries({ queryKey: ["activity"] });
      const { state, message } = describeOutcome(result, name, success);
      if (ctx) actions.finish(ctx.act, state, message);
      if (!quiet && message) toast.show(message, state === "COMPLETE" ? "ok" : "info");
    },
    onError: (e, _body, ctx) => {
      const message = friendlyError(e.message, (e as { status?: number }).status);
      if (ctx) actions.finish(ctx.act, "FAILED", message);
      toast.show(`✕ ${name} failed — ${message}`, "error");
    },
  });
}

/* ------------------------------------------------------------------ small hooks */

/** Polls `path` every `ms` while `active` — for background jobs (scans, batches, research). */
export function usePoll<T>(path: string, active: boolean, ms = 1200, query?: Query) {
  return useApi<T>(path, query, { refetchInterval: active ? ms : false });
}

/** Debounced value — for search boxes over large lists. */
export function useDebounced<T>(value: T, ms = 200): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** Copy text to the clipboard with a toast. */
export function useCopy() {
  const toast = useToast();
  return useCallback(
    async (text: string, label = "Copied") => {
      try {
        await navigator.clipboard.writeText(text);
        toast.show(label, "ok");
      } catch {
        toast.show("Clipboard blocked — select the text and copy manually", "error");
      }
    },
    [toast],
  );
}

/** Persist a small per-viewer UI preference (tab, filter) in localStorage under `pz:<key>`; never app state.
 *  The initial value is not written back — only a change is. */
export function usePref<T>(key: string, initial: T): [T, (v: T) => void] {
  const k = `pz:${key}`;
  const [v, setV] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(k);
      return raw === null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    try {
      localStorage.setItem(k, JSON.stringify(v));
    } catch {
      /* storage unavailable: preference just isn't remembered */
    }
  }, [k, v]);
  return [v, setV];
}

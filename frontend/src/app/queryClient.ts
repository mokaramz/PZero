import { QueryClient } from "@tanstack/react-query";

/** The app's query defaults: data counts as fresh for 15 s, no refetch on window focus, one retry. */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { staleTime: 15_000, refetchOnWindowFocus: false, retry: 1 },
    },
  });
}

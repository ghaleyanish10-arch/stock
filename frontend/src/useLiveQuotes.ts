/* Live price polling for any set of symbols.
 *
 * Reads the backend's shared NEPSE poller cache (GET /api/realtime/prices) -
 * one upstream NEPSE request per interval regardless of how many tabs poll
 * this. Returns a symbol -> quote map plus a `live` flag: false when the
 * poller has no fresh pass yet (pre-open, closed market, or backend restart),
 * in which case callers keep showing the archived/EOD values.
 */

import { useQuery } from "@tanstack/react-query";
import { realtime, type LiveQuote } from "./api";

const LIVE_STALE_MS = 90_000; // poller interval (30s) + slack

export function useLiveQuotes(symbols: string[], refetchMs = 30_000) {
  const key = [...symbols].sort().join(",");
  const query = useQuery({
    queryKey: ["live-quotes", key],
    queryFn: ({ signal }) => realtime.prices(symbols, signal),
    enabled: symbols.length > 0,
    refetchInterval: refetchMs,
    staleTime: 15_000,
    retry: 1,
  });

  const map = new Map<string, LiveQuote>();
  let live = false;
  for (const q of query.data?.quotes ?? []) {
    map.set(q.symbol, q);
    const age = Date.now() - new Date(q.timestamp + "Z").getTime();
    if (age <= LIVE_STALE_MS) live = true;
  }
  return { quotes: map, live, asOf: query.data?.as_of ?? null, isLoading: query.isLoading };
}

/* Live index bar and highlights ticker.
 *
 * The index bar is a flat, always-visible strip of the headline numbers, so
 * they are readable on every page instead of only the overview. The ticker
 * carries the session's extremes; it pauses on hover so a value can actually
 * be read, and it respects `prefers-reduced-motion` by not animating at all.
 */

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { market } from "../api";
import { fmtInt, fmtNum, fmtPct, fmtRs, trendClass } from "../format";

export function IndexBar() {
  const { data, isError } = useQuery({
    queryKey: ["index-bar"],
    queryFn: ({ signal }) => market.overview(signal),
    refetchInterval: 30_000,
    staleTime: 20_000,
  });

  if (isError) {
    return (
      <div className="index-bar" role="status">
        <span className="index-bar-item index-bar-stale">
          Index unavailable -- NEPSE did not answer
        </span>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="index-bar" aria-busy="true">
        <span className="index-bar-item index-bar-stale">Loading index...</span>
      </div>
    );
  }

  const idx = data.nepse_index;
  const summary = data.summary;
  const indexValue = idx?.value ?? null;
  const trend = trendClass(idx?.change);

  return (
    <div className="index-bar" role="region" aria-label="Live market index">
      <span className="index-bar-item index-bar-primary">
        <span className="index-bar-key">NEPSE</span>
        <strong className={trend}>{indexValue != null ? fmtNum(indexValue) : "—"}</strong>
        {!idx?.is_closed && indexValue != null && idx?.change != null && (
          <span className={trend}>
            {idx.change > 0 ? "+" : ""}
            {fmtNum(idx.change)} ({fmtPct(idx.change_percentage)})
          </span>
        )}
        {idx?.is_closed && <span className="index-bar-tag">closed</span>}
      </span>

      <span className="index-bar-item">
        <span className="index-bar-key">Turnover</span>
        {fmtRs(summary?.total_turnover)}
      </span>
      <span className="index-bar-item">
        <span className="index-bar-key">Shares</span>
        {fmtInt(summary?.total_traded_shares)}
      </span>
      <span className="index-bar-item">
        <span className="index-bar-key">Trades</span>
        {fmtInt(summary?.total_transactions)}
      </span>
      <span className="index-bar-item">
        <span className="index-bar-key">Scrips</span>
        {fmtInt(summary?.traded_scrips)}
      </span>
    </div>
  );
}

export function HighlightsTicker() {
  const { data } = useQuery({
    queryKey: ["ticker"],
    queryFn: async ({ signal }) => {
      const [gainers, losers] = await Promise.all([
        market.topGainers(6, signal),
        market.topLosers(6, signal),
      ]);
      return { gainers, losers };
    },
    refetchInterval: 60_000,
    staleTime: 45_000,
  });

  const items = [
    ...(data?.gainers ?? []).map((r) => ({ ...r, kind: "gainer" as const })),
    ...(data?.losers ?? []).map((r) => ({ ...r, kind: "loser" as const })),
  ];

  const reduced = usePrefersReducedMotion();
  const [paused, hoverHandlers] = useHoverPause();

  if (items.length === 0) return null;

  return (
    <div
      className={`ticker${paused ? " paused" : ""}${reduced ? " static" : ""}`}
      role="region"
      aria-label="Session highlights"
      {...hoverHandlers}
    >
      <span className="ticker-label">Highlights</span>
      <div className="ticker-viewport">
        {/* Duplicated so the CSS marquee can loop seamlessly; the copy is
            hidden from assistive tech to avoid reading everything twice. */}
        <div className="ticker-track">
          {[0, 1].map((copy) => (
            <span className="ticker-run" key={copy} aria-hidden={copy === 1}>
              {items.map((r) => (
                <Link
                  key={`${copy}-${r.symbol}`}
                  to={`/analytics?symbol=${encodeURIComponent(r.symbol)}`}
                  className={`ticker-item ${r.kind}`}
                >
                  <strong>{r.symbol}</strong>
                  <span className="ticker-ltp">{fmtNum(r.ltp)}</span>
                  <span className="ticker-chg">{fmtPct(r.percentage_change)}</span>
                </Link>
              ))}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

/** Pauses CSS animation while hovered or focused, for keyboard users too. */
export function useHoverPause(): [boolean, { onMouseEnter: () => void; onMouseLeave: () => void; onFocusCapture: () => void; onBlurCapture: () => void }] {
  const [paused, setPaused] = useState(false);
  const handlers = {
    onMouseEnter: () => setPaused(true),
    onMouseLeave: () => setPaused(false),
    onFocusCapture: () => setPaused(true),
    onBlurCapture: () => setPaused(false),
  };
  return [paused, handlers];
}

/** Tracks a media query; used to disable the marquee for reduced motion. */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    if (!window.matchMedia) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduced;
}
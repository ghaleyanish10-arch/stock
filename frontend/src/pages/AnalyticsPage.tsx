/* Technical analytics over archived bars.
 *
 * Phase 5 layout: the technical chart sits at the top for the loaded symbol,
 * the indicator value cards below it. Every indicator is computed server-side
 * (see app/analytics/indicators.py) so the numbers are reproducible and
 * testable rather than re-derived in the browser. Warm-up windows are `null`
 * and are labelled as such - RSI genuinely does not exist until the 15th close.
 *
 * Staleness contract (Phase 5g): each card shows the latest NON-null value with
 * the date it belongs to, so an indicator whose last computed day is older than
 * the price as-of is never presented as current. If the newest archived bar has
 * no close (ingest still running), the page says so once.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { analytics, reference } from "../api";
import { MeasuredValue, ProvenanceLegend } from "../provenance";
import { Card, ErrorState, Loading, Stat } from "../components/ui";
import { fmtDate, fmtInt, fmtNum, isMissing } from "../format";
import type { IndicatorsResponse, Measured, SeriesPoint } from "../types";
import { TechnicalChartCard } from "../components/TechnicalChart";
import { INDICATORS } from "../indicators";

/** Label -> plain-language definition from the registry (Trading Indicators notes). */
const DESC_BY_KEY: Record<string, string> = Object.fromEntries(
  INDICATORS.flatMap((d) => d.series.map((k) => [k, d.desc ?? ""])),
);

interface TypeaheadRow {
  symbol: string;
  name: string | null;
}

/** Rank matches the way the NEPSE site does: exact symbol, then symbol
 * prefix, then symbol contains, then name-word matches. */
function rankMatches(rows: TypeaheadRow[], needle: string): TypeaheadRow[] {
  const words = needle.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const scored: { row: TypeaheadRow; score: number }[] = [];
  for (const row of rows) {
    const sym = row.symbol.toLowerCase();
    const name = (row.name ?? "").toLowerCase().replace(/\s+/g, " ");
    let score = -1;
    if (sym === words.join("") || words.length === 1 && sym === words[0]) score = 0;
    else if (words.length === 1 && sym.startsWith(words[0])) score = 1;
    else if (words.every((w) => sym.includes(w))) score = 2;
    else if (words.every((w) => name.includes(w))) score = 3;
    else if (words.every((w) => sym.includes(w) || name.includes(w))) score = 4;
    if (score >= 0) scored.push({ row, score });
  }
  return scored
    .sort((a, b) => a.score - b.score || a.row.symbol.localeCompare(b.row.symbol))
    .slice(0, 8)
    .map((s) => s.row);
}

/** NEPSE-site-style typeahead: `(SYMBOL) Company Name` dropdown under the
 * input, keyboard navigable, click or Enter to load. */
function SymbolTypeahead({
  value,
  onValueChange,
  onPick,
  onSubmit,
}: {
  value: string;
  onValueChange: (v: string) => void;
  /** A concrete security was chosen from the dropdown. */
  onPick: (symbol: string) => void;
  /** Enter/Load pressed without picking - free-text resolution. */
  onSubmit: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Shares the app-wide "securities" cache (same key as the command palette),
  // so typing never triggers its own network storm.
  const { data } = useQuery({
    queryKey: ["securities"],
    queryFn: ({ signal }) => reference.securities(undefined, true, signal),
    staleTime: 5 * 60_000,
    enabled: open,
  });

  const matches = useMemo(
    () => rankMatches(data?.securities ?? [], value),
    [data, value],
  );

  // Close when clicking anywhere outside the combobox.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  useEffect(() => setHighlight(0), [value]);

  const pick = (sym: string) => {
    setOpen(false);
    onValueChange(sym);
    onPick(sym);
  };

  return (
    <div className="typeahead" ref={wrapRef}>
      <div className="typeahead-box">
        <input
          className="input"
          value={value}
          onChange={(e) => {
            onValueChange(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (!open || !matches.length) {
              if (e.key === "Enter") {
                e.preventDefault();
                onSubmit();
              }
              return;
            }
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setHighlight((h) => (h + 1) % matches.length);
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setHighlight((h) => (h - 1 + matches.length) % matches.length);
            } else if (e.key === "Enter") {
              e.preventDefault();
              pick(matches[highlight].symbol);
            } else if (e.key === "Escape") {
              setOpen(false);
            }
          }}
          placeholder="Symbol or name e.g. NABIL, prabhu"
          aria-label="Symbol"
          role="combobox"
          aria-expanded={open && matches.length > 0}
          aria-controls="symbol-typeahead-menu"
          autoComplete="off"
          maxLength={60}
        />
        <svg className="typeahead-icon" viewBox="0 0 20 20" aria-hidden="true">
          <circle cx="8.5" cy="8.5" r="5.5" fill="none" stroke="currentColor" strokeWidth="2" />
          <line x1="13" y1="13" x2="18" y2="18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </div>
      {open && matches.length > 0 && (
        <ul className="typeahead-menu" id="symbol-typeahead-menu" role="listbox">
          {matches.map((m, i) => (
            <li key={m.symbol} role="option" aria-selected={i === highlight}>
              <button
                type="button"
                className={`typeahead-item${i === highlight ? " on" : ""}`}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(m.symbol)}
                onMouseEnter={() => setHighlight(i)}
              >
                <strong>({m.symbol})</strong> {m.name ?? "Security"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const LAST_SYMBOL_KEY = "analytics.symbol";

/** Indicator groups, with the unit each one is displayed in. */
const GROUPS: {
  title: string;
  keys: { key: string; label: string; unit: "number" | "percent" }[];
}[] = [
  {
    title: "Trend",
    keys: [
      { key: "sma_20", label: "SMA 20", unit: "number" },
      { key: "ema_20", label: "EMA 20", unit: "number" },
      { key: "macd", label: "MACD", unit: "number" },
      { key: "macd_signal", label: "MACD signal", unit: "number" },
      { key: "macd_histogram", label: "MACD histogram", unit: "number" },
      { key: "roc_1", label: "ROC (1d)", unit: "percent" },
    ],
  },
  {
    title: "Volatility",
    keys: [
      { key: "bb_upper", label: "Bollinger upper", unit: "number" },
      { key: "bb_middle", label: "Bollinger mid", unit: "number" },
      { key: "bb_lower", label: "Bollinger lower", unit: "number" },
      { key: "bb_bandwidth_pct", label: "Bandwidth", unit: "percent" },
      { key: "bb_percent_b", label: "%B", unit: "percent" },
      { key: "atr_14", label: "ATR 14", unit: "number" },
    ],
  },
  {
    title: "Volume & flow",
    keys: [
      { key: "obv", label: "OBV", unit: "number" },
      { key: "accumulation_distribution", label: "A&D line", unit: "number" },
      { key: "chaikin_money_flow_20", label: "CMF 20", unit: "number" },
      { key: "money_flow_index_14", label: "MFI 14", unit: "number" },
      { key: "vwap", label: "VWAP", unit: "number" },
      { key: "volume_vs_20d_pct", label: "Volume vs 20d", unit: "percent" },
    ],
  },
  {
    title: "Momentum",
    keys: [
      { key: "rsi_14", label: "RSI 14", unit: "number" },
      { key: "stoch_k", label: "Stoch %K", unit: "number" },
      { key: "stoch_d", label: "Stoch %D", unit: "number" },
      { key: "stoch_rsi", label: "Stoch RSI", unit: "number" },
      { key: "cci_20", label: "CCI 20", unit: "number" },
      { key: "williams_r_14", label: "Williams %R", unit: "number" },
      { key: "momentum_10", label: "Momentum 10", unit: "number" },
      { key: "ultimate_osc", label: "Ultimate Osc", unit: "number" },
      { key: "awesome_osc", label: "Awesome Osc", unit: "number" },
      { key: "tsi", label: "TSI", unit: "number" },
      { key: "rvi", label: "RVI", unit: "number" },
    ],
  },
  {
    title: "Volatility & bands",
    keys: [
      { key: "stdev_20", label: "Std Dev 20", unit: "number" },
      { key: "keltner_upper", label: "Keltner upper", unit: "number" },
      { key: "keltner_middle", label: "Keltner mid", unit: "number" },
      { key: "keltner_lower", label: "Keltner lower", unit: "number" },
      { key: "donchian_upper", label: "Donchian upper", unit: "number" },
      { key: "donchian_lower", label: "Donchian lower", unit: "number" },
      { key: "historical_vol_20", label: "Hist Vol 20", unit: "number" },
      { key: "chaikin_volatility", label: "Chaikin Vol", unit: "number" },
      { key: "supertrend", label: "Supertrend", unit: "number" },
    ],
  },
  {
    title: "Pivots & Fibonacci",
    keys: [
      { key: "pivot_pp", label: "Pivot P", unit: "number" },
      { key: "pivot_r1", label: "Pivot R1", unit: "number" },
      { key: "pivot_s1", label: "Pivot S1", unit: "number" },
      { key: "pivot_r2", label: "Pivot R2", unit: "number" },
      { key: "pivot_s2", label: "Pivot S2", unit: "number" },
      { key: "cam_r3", label: "Camarilla R3", unit: "number" },
      { key: "cam_s3", label: "Camarilla S3", unit: "number" },
      { key: "cam_r4", label: "Camarilla R4", unit: "number" },
      { key: "cam_s4", label: "Camarilla S4", unit: "number" },
      { key: "fib_618", label: "Fib 61.8%", unit: "number" },
      { key: "fibe_1618", label: "Fib ext 161.8%", unit: "number" },
      { key: "fibf_500", label: "Fib fan 50%", unit: "number" },
    ],
  },
  {
    title: "Volume indicators",
    keys: [
      { key: "vpt", label: "VPT", unit: "number" },
      { key: "emv_14", label: "EMV 14", unit: "number" },
      { key: "force_index_13", label: "Force Index", unit: "number" },
      { key: "volume_osc", label: "Volume Osc", unit: "percent" },
      { key: "klinger", label: "Klinger", unit: "number" },
      { key: "chaikin_osc", label: "Chaikin Osc", unit: "number" },
      { key: "vwma_20", label: "VWMA 20", unit: "number" },
    ],
  },
];

export function AnalyticsPage({ initialSymbol }: { initialSymbol?: string }) {
  // No hardcoded symbol: start from the deep link, then the last viewed
  // symbol, then nothing (search-box empty state).
  const [symbol, setSymbol] = useState(() => {
    if (initialSymbol) return initialSymbol;
    try {
      return window.localStorage.getItem(LAST_SYMBOL_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [active, setActive] = useState(symbol);

  // A deep link to a different symbol should reload the page content.
  useEffect(() => {
    if (initialSymbol) {
      setSymbol(initialSymbol);
      setActive(initialSymbol);
    }
  }, [initialSymbol]);

  const query = useQuery({
    queryKey: ["indicators", active],
    queryFn: ({ signal }) => analytics.indicators(active, signal),
    enabled: !!active,
    retry: 1,
  });

  const data = query.data;

  const rememberSymbol = (sym: string) => {
    try {
      window.localStorage.setItem(LAST_SYMBOL_KEY, sym);
    } catch {
      /* non-fatal */
    }
  };

  /** Chosen from the typeahead dropdown - always a concrete symbol. */
  const pickSymbol = (sym: string) => {
    setResolveError(null);
    setActive(sym);
    rememberSymbol(sym);
  };

  /** Enter/Load on free text: everything is validated against the security
   * master - an exact symbol loads as-is, a name resolves to its symbol, and
   * unknown input (e.g. a company name typed as one word) gets a clear error
   * instead of a confusing "no archived bars" 404. */
  const [resolveError, setResolveError] = useState<string | null>(null);
  const [resolving, setResolving] = useState(false);
  const loadSymbol = async () => {
    const raw = symbol.trim().toUpperCase();
    if (!raw) return;
    setResolveError(null);
    setResolving(true);
    try {
      const found = await reference.securities(raw, true);
      const exact = found.securities.find((s) => s.symbol === raw);
      const pick = exact ?? found.securities[0];
      if (!pick) {
        setResolveError(`No security matches "${symbol.trim()}". Try the dropdown suggestions.`);
        return;
      }
      setActive(pick.symbol);
      setSymbol(pick.symbol);
      rememberSymbol(pick.symbol);
    } catch {
      setResolveError(`Could not resolve "${symbol.trim()}". Try the symbol, e.g. PRVU.`);
    } finally {
      setResolving(false);
    }
  };

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Technical</h1>
          <p className="page-sub">
            Chart and indicators computed server-side from archived bars. A blank cell means the
            indicator is undefined yet, not zero.
          </p>
        </div>
        <form
          className="symbol-form"
          onSubmit={(e) => {
            e.preventDefault();
            void loadSymbol();
          }}
        >
          <SymbolTypeahead
            value={symbol}
            onValueChange={setSymbol}
            onPick={pickSymbol}
            onSubmit={() => void loadSymbol()}
          />
          <button type="submit" className="btn btn-primary" disabled={resolving}>
            {resolving ? "Searching…" : "Load"}
          </button>
        </form>
      </header>

      {resolveError && (
        <Card>
          <div className="state state-empty">
            <span>{resolveError}</span>
          </div>
        </Card>
      )}

      {!active && (
        <Card>
          <div className="state state-empty">
            <span>
              Enter a trading symbol or company name above (for example <strong>NABIL</strong> or{" "}
              <strong>prabhu</strong>) and press Load to see its chart and indicators.
            </span>
          </div>
        </Card>
      )}

      {active && query.isLoading && <Loading label={`Computing indicators for ${active}`} />}
      {active && query.error && (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      )}

      {active && data && (
        <>
          {/* Phase 5a: chart on top, same symbol input/Load button above. */}
          <TechnicalChartCard symbol={active} />
          <IndicatorBody data={data} />
        </>
      )}

      {data?.notes && (
        <Card title="About these numbers">
          <ul className="notes-list">
            {Object.entries(data.notes).map(([key, text]) => (
              <li key={key}>
                <strong>{key.replace(/_/g, " ")}:</strong> {text}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function IndicatorBody({ data }: { data: IndicatorsResponse }) {
  /** Latest non-null point of a series, so a null newest bar never hides the
   * value that is still current. Returns null when nothing is computable. */
  const latestNonNull = (key: string): SeriesPoint | null => {
    const series = data.indicators[key];
    if (!series) return null;
    for (let i = series.length - 1; i >= 0; i--) {
      if (!isMissing(series[i].value)) return series[i];
    }
    return null;
  };

  const close = data.price.close;
  const lastClose = close[close.length - 1];
  const newestBarMissing = isMissing(lastClose);
  const firstClose = close.find((c) => !isMissing(c)) ?? null;

  return (
    <>
      {newestBarMissing && (
        <Card>
          <div className="state state-empty">
            <span>
              The newest archived bar ({fmtDate(data.as_of)}) has no close yet — values below are
              the latest computed ones, which may be one session older.
            </span>
          </div>
        </Card>
      )}

      <div className="stat-row">
        <Stat label="Symbol" hint={`Price as of ${fmtDate(data.as_of)}`}>
          <strong>{data.symbol}</strong>
        </Stat>
        <Stat label="Last close" hint={`${fmtInt(data.sessions)} sessions archived`}>
          {fmtNum(lastClose, 2)}
        </Stat>
        <Stat
          label="Change over window"
          hint={`${fmtDate(data.first)} to ${fmtDate(data.as_of)}`}
        >
          {firstClose !== null && !isMissing(lastClose)
            ? `${(((lastClose! - firstClose) / firstClose) * 100).toFixed(2)}%`
            : "–"}
        </Stat>
      </div>

      {GROUPS.map((group) => (
        <Card key={group.title} title={group.title} actions={<ProvenanceLegend />}>
          <div className="indicator-grid">
            {group.keys.map(({ key, label, unit }) => {
              const point = latestNonNull(key);
              const measured: Measured = {
                value: point?.value ?? null,
                status: point?.value == null ? "not_reported" : "ok",
                as_of: point?.date ?? null,
                source: "derived",
                note:
                  point?.value == null
                    ? "Not enough archived history for this indicator yet, or the day had no volume."
                    : point.date !== data.as_of
                      ? `Latest computable value; its day (${fmtDate(point.date)}) is older than the newest price bar.`
                      : null,
              };
              const desc = DESC_BY_KEY[key];
              return (
                <div className="indicator" key={key} title={desc || undefined}>
                  <div className="indicator-label">{label}</div>
                  <div className="indicator-value">
                    <MeasuredValue
                      measured={measured}
                      format={unit === "percent" ? "number" : "number"}
                    />
                  </div>
                  {point && (
                    <div className="indicator-asof">as of {fmtDate(point.date)}</div>
                  )}
                </div>
              );
            })}
          </div>
        </Card>
      ))}

      <Card title="Recent closes">
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th className="align-right">Open</th>
                <th className="align-right">High</th>
                <th className="align-right">Low</th>
                <th className="align-right">Close</th>
                <th className="align-right">Volume</th>
                <th className="align-right">RSI 14</th>
                <th className="align-right">A&D</th>
              </tr>
            </thead>
            <tbody>
              {data.price.dates
                .map((date, i) => ({ date, i }))
                .reverse()
                .slice(0, 40)
                .map(({ date, i }) => {
                  const ad = data.indicators.accumulation_distribution?.[i]?.value ?? null;
                  const rsiValue = data.indicators.rsi_14?.[i]?.value ?? null;
                  return (
                    <tr key={date}>
                      <td>{fmtDate(date)}</td>
                      <td className="align-right">{fmtNum(data.price.open[i])}</td>
                      <td className="align-right">{fmtNum(data.price.high[i])}</td>
                      <td className="align-right">{fmtNum(data.price.low[i])}</td>
                      <td className="align-right">{fmtNum(data.price.close[i])}</td>
                      <td className="align-right">{fmtInt(data.price.volume[i])}</td>
                      <td className="align-right">
                        <MeasuredValue
                          measured={{
                            value: rsiValue,
                            status: rsiValue == null ? "not_reported" : "ok",
                            as_of: date,
                            source: "derived",
                            note: rsiValue == null ? "RSI needs 15 closes." : null,
                          }}
                        />
                      </td>
                      <td className="align-right">
                        {ad == null ? (
                          <span className="mv-chip st-missing">Not declared yet</span>
                        ) : (
                          fmtNum(ad, 0)
                        )}
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}

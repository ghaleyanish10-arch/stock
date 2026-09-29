/* Technical analytics over archived bars.
 *
 * Every indicator is computed server-side (see app/analytics/indicators.py) so
 * the numbers are reproducible and testable rather than re-derived in the
 * browser. Warm-up windows are `null` and are labelled as such - RSI genuinely
 * does not exist until the 15th close.
 */

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { analytics } from "../api";
import { MeasuredValue, ProvenanceLegend } from "../provenance";
import { Card, ErrorState, Loading, Stat } from "../components/ui";
import { fmtDate, fmtInt, fmtNum, isMissing } from "../format";
import type { IndicatorsResponse, Measured, SeriesPoint } from "../types";

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
    keys: [{ key: "rsi_14", label: "RSI 14", unit: "number" }],
  },
];

export function AnalyticsPage({ initialSymbol }: { initialSymbol?: string }) {
  const [symbol, setSymbol] = useState(initialSymbol ?? "NABIL");
  const [active, setActive] = useState(initialSymbol ?? "NABIL");

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
    retry: 1,
  });

  const data = query.data;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Technical</h1>
          <p className="page-sub">
            Indicators computed server-side from archived bars. A blank cell means the
            indicator is undefined yet, not zero.
          </p>
        </div>
        <form
          className="symbol-form"
          onSubmit={(e) => {
            e.preventDefault();
            const sym = symbol.trim().toUpperCase();
            if (sym) setActive(sym);
          }}
        >
          <input
            className="input"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="Symbol"
            aria-label="Symbol"
            maxLength={12}
          />
          <button type="submit" className="btn btn-primary">
            Load
          </button>
        </form>
      </header>

      {query.isLoading && <Loading label={`Computing indicators for ${active}`} />}
      {query.error && <ErrorState error={query.error} onRetry={() => void query.refetch()} />}

      {data && <IndicatorBody data={data} />}

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
  const latest = (key: string): SeriesPoint | undefined => {
    const series = data.indicators[key];
    return series?.[series.length - 1];
  };

  const close = data.price.close;
  const lastClose = close[close.length - 1];
  const firstClose = close.find((c) => !isMissing(c)) ?? null;

  return (
    <>
      <div className="stat-row">
        <Stat label="Symbol" hint={data.as_of}>
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
              const point = latest(key);
              const measured: Measured = {
                value: point?.value ?? null,
                status: point?.value == null ? "not_reported" : "ok",
                as_of: point ? data.as_of : null,
                source: "derived",
                note:
                  point?.value == null
                    ? "Not enough archived history for this indicator yet, or the day had no volume."
                    : null,
              };
              return (
                <div className="indicator" key={key}>
                  <div className="indicator-label">{label}</div>
                  <div className="indicator-value">
                    <MeasuredValue
                      measured={measured}
                      format={unit === "percent" ? "number" : "number"}
                    />
                  </div>
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

/* Company page: profile, price, valuation, dividends, promoter split, news, depth.
 *
 * Uses the company endpoint which returns everything in one request so the page
 * needs no client-side joins. Every section that NEPSE does not publish is
 * returned as an explicit unavailable block with a reason, never a bare null.
 */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { analytics, reference } from "../api";
import { INDICATORS, DEFAULT_SELECTION, selectedToParam } from "../indicators";
import type { IndicatorId } from "../indicators";
import type { CompanyResponse, Measured, DividendRow } from "../types";
import { fmtNum, fmtPct, fmtRs, fmtInt, trendClass } from "../format";
import {
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Missing,
  ProvenanceChip,
  Stat,
} from "../components/ui";
import { TechnicalChart } from "../components/TechnicalChart";

interface SimpleMeasured {
  value: number | null;
  reason?: string;
  as_of?: string;
}

function renderMeasuredValue(
  measured: SimpleMeasured | Measured,
  formatter?: (v: number) => string,
) {
  if (measured.value != null) {
    return formatter ? formatter(measured.value) : String(measured.value);
  }
  return <Missing reason={("note" in measured ? measured.note : measured.reason) ?? "Unknown"} />;
}

function renderSimpleValue(value: number | null, reason: string | undefined, formatter?: (v: number) => string) {
  if (value != null) {
    return formatter ? formatter(value) : String(value);
  }
  return <Missing reason={reason ?? "Unknown"} />;
}

function renderUnavailable(section: { available: false; reason: string; status?: string }) {
  return (
    <div className="state state-empty">
      <ProvenanceChip
        measured={{
          value: null,
          status: (section.status as Measured["status"]) ?? "not_reported",
          as_of: null,
          source: null,
          note: section.reason,
        }}
      />
    </div>
  );
}

function renderNoticeFact(fact: { available: true; value: string; from_headline: string | null; published_at: string | null; note: string } | { available: false; reason: string; status?: string }) {
  if (!fact.available) {
    return renderUnavailable(fact);
  }
  return (
    <div className="stat-row">
      <div className="stat">
        <span className="stat-label">Date</span>
        <span className="stat-value">{fact.value}</span>
      </div>
      <div className="stat">
        <span className="stat-label">From</span>
        <span className="stat-value">{fact.from_headline}</span>
      </div>
      <div className="stat">
        <span className="stat-label">Published</span>
        <span className="stat-value">{fact.published_at ? new Date(fact.published_at).toLocaleString() : "N/A"}</span>
      </div>
    </div>
  );
}

function renderMarketDepth(depth: { available: true; source: string; payload: any; note: string } | { available: false; reason: string; status?: string; checked_at?: string }) {
  if (!depth.available) {
    return (
      <div className="state state-empty">
        <ProvenanceChip
          measured={{
            value: null,
            status: (depth.status as Measured["status"]) ?? "upstream_unavailable",
            as_of: null,
            source: null,
            note: depth.reason,
          }}
        />
        {depth.checked_at && (
          <span className="stat-hint">Checked at {new Date(depth.checked_at).toLocaleString()}</span>
        )}
      </div>
    );
  }
  return (
    <div className="muted">
      {depth.note}
    </div>
  );
}

function renderSplitSection(split: { available: true; promoter_shares: number | null; public_shares: number | null; promoter_pct: number | null; public_pct: number | null; source: string; as_of: string | null } | { available: false; reason: string; status?: string }) {
  if (!split.available) {
    return renderUnavailable(split);
  }
  return (
    <div className="stat-row">
      <div className="stat">
        <span className="stat-label">Promoter shares</span>
        <span className="stat-value">{split.promoter_shares != null ? fmtInt(split.promoter_shares) : <Missing reason="Not reported" />}</span>
      </div>
      <div className="stat">
        <span className="stat-label">Promoter %</span>
        <span className="stat-value">{split.promoter_pct != null ? fmtPct(split.promoter_pct) + "%" : <Missing reason="Not reported" />}</span>
      </div>
      <div className="stat">
        <span className="stat-label">Public shares</span>
        <span className="stat-value">{split.public_shares != null ? fmtInt(split.public_shares) : <Missing reason="Not reported" />}</span>
      </div>
      <div className="stat">
        <span className="stat-label">Public %</span>
        <span className="stat-value">{split.public_pct != null ? fmtPct(split.public_pct) + "%" : <Missing reason="Not reported" />}</span>
      </div>
    </div>
  );
}

interface DividendRowWithRight extends DividendRow {
  right_pct?: Measured;
}

export function CompanyPage() {
  const { symbol } = useParams<{ symbol: string }>();
  const [enriching, setEnriching] = useState(false);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["company", symbol],
    queryFn: ({ signal }) => reference.company(symbol!, signal),
    enabled: !!symbol,
    staleTime: 60_000,
  });

  // Selected chart indicators, persisted per browser so the page keeps the
  // user's mix across navigation.
  const [selected, setSelected] = useState<IndicatorId[]>(
    () => {
      try {
        const raw = window.localStorage.getItem("chart-indicators");
        const parsed: unknown = raw ? JSON.parse(raw) : null;
        if (Array.isArray(parsed)) {
          const valid = parsed.filter(
            (k): k is IndicatorId =>
              typeof k === "string" && INDICATORS.some((d) => d.key === k),
          );
          if (valid.length) return valid;
        }
      } catch {
        /* fall through to the default mix */
      }
      return DEFAULT_SELECTION;
    },
  );
  useEffect(() => {
    window.localStorage.setItem("chart-indicators", JSON.stringify(selected));
  }, [selected]);

  // Chart data for technical analysis - default to the last available archived range
  const { data: chartData, isLoading: chartLoading } = useQuery({
    queryKey: ["chart", symbol, selected],
    queryFn: ({ signal }) =>
      analytics.chart(
        symbol!,
        // The endpoint accepts ADJUSTED | UNADJUSTED (case-sensitive); the
        // lowercase value here made every chart request 400 so the chart and
        // its picker never rendered.
        { range: "ALL", mode: "UNADJUSTED", indicators: selectedToParam(selected) },
        signal,
      ),
    enabled: !!symbol,
    staleTime: 60_000,
  });

  const handleEnrich = useCallback(async () => {
    if (!symbol) return;
    setEnriching(true);
    try {
      await reference.enrich(symbol);
      await refetch();
    } finally {
      setEnriching(false);
    }
  }, [symbol, refetch]);

  if (isLoading) {
    return (
      <div className="page">
        <Loading label={`${symbol}…`} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="page">
        <ErrorState error={error} />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="page">
        <EmptyState message="No data" />
      </div>
    );
  }

  const company = data as CompanyResponse;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>
            {company.profile.name} ({company.symbol})
          </h1>
          <p className="page-sub">
            {company.profile.sector && <span>{company.profile.sector} • </span>}
            {company.profile.security_type && <span>{company.profile.security_type} • </span>}
            {company.profile.isin && <span>ISIN: {company.profile.isin}</span>}
          </p>
        </div>
        <div className="page-head-actions">
          {company.profile.needs_enrichment?.length && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleEnrich}
              disabled={enriching}
            >
              {enriching ? "Enriching…" : "Enrich metadata"}
            </button>
          )}
        </div>
      </header>

      {/* Price snapshot */}
      <Card padded={false}>
        <div className="card-head">
          <span className="card-title">Price snapshot</span>
        </div>
        <div className="stat-row">
          <div className="stat">
            <span className="stat-label">LTP</span>
            <span className="stat-value big-num">
              {renderMeasuredValue(company.valuation.ltp, fmtNum)}
            </span>
            {company.valuation.ltp.as_of && (
              <span className="stat-hint">as of {company.valuation.ltp.as_of}</span>
            )}
          </div>
          <div className="stat">
            <span className="stat-label">Change</span>
            <span className={`stat-value ${company.price.change_pct != null && company.price.change_pct > 0 ? "up" : company.price.change_pct != null && company.price.change_pct < 0 ? "down" : ""}`}>
              {renderSimpleValue(company.price.change, company.price.reasons?.change, (v) => `${v > 0 ? "+" : ""}${fmtNum(v)} (${fmtPct(company.price.change_pct ?? 0)})`)}
            </span>
          </div>
          <div className="stat">
            <span className="stat-label">Day range</span>
            <span className="stat-value">
              {company.price.day_low != null && company.price.day_high != null
                ? `${fmtNum(company.price.day_low)} – ${fmtNum(company.price.day_high)}`
                : <Missing reason={company.price.reasons?.range ?? "Unknown"} />}
            </span>
          </div>
          <div className="stat">
            <span className="stat-label">52-week range</span>
            <span className="stat-value">
              {company.price.low_52w != null && company.price.high_52w != null
                ? `${fmtNum(company.price.low_52w)} – ${fmtNum(company.price.high_52w)}`
                : <Missing reason={company.price.reasons?.range_52w ?? "Unknown"} />}
            </span>
          </div>
          <div className="stat">
            <span className="stat-label">Volume</span>
            <span className="stat-value">
              {company.price.volume != null ? fmtInt(company.price.volume) : <Missing reason={company.price.reasons?.volume ?? "Unknown"} />}
            </span>
          </div>
          <div className="stat">
            <span className="stat-label">Turnover</span>
            <span className="stat-value">
              {company.price.turnover != null ? fmtRs(company.price.turnover) : <Missing reason={company.price.reasons?.turnover ?? "Unknown"} />}
            </span>
          </div>
        </div>
      </Card>

{/* Technical chart */}
      {chartData && !chartLoading && (
        <Card title={`Technical chart (${chartData.range?.requested || "ALL"}, adjusted)`}>
          <TechnicalChart
            data={{ series: chartData.series, indicators: chartData.indicators }}
            selected={selected}
          />
          {chartData.range && !chartData.range.complete && (
            <div className="notice notice-warn" style={{ marginTop: "var(--space-4)" }}>
              <strong>Range not fully covered:</strong> Archive starts {chartData.range.first_shown}, inside the {chartData.range.requested} window, so this period is only covered from {chartData.range.first_shown}.
            </div>
          )}
          <div className="legend">
            <span className="legend-title">Indicators</span>
            <div className="picker" role="group" aria-label="Chart indicators">
              {INDICATORS.map((def) => {
                const on = selected.includes(def.key);
                return (
                  <label
                    key={def.key}
                    className={`picker-chip${on ? " on" : ""}`}
                    style={on ? { borderColor: def.color, color: def.color } : undefined}
                  >
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={(e) =>
                        setSelected((prev) =>
                          e.target.checked ? [...prev, def.key] : prev.filter((k) => k !== def.key),
                        )
                      }
                    />
                    {def.label}
                  </label>
                );
              })}
            </div>
          </div>
          <div className="legend">
            <span className="legend-title">Adjusted close</span>
            <span>
              Adjusted for bonus/right actions at book-close dates within archive coverage.
              {company.dividends.actions.some((a) => (a as any).right_pct || (a as any).bonus_pct)
                ? ""
                : " No corporate actions with right/bonus found in archive; adjusted = raw close."}
            </span>
          </div>
        </Card>
      )}

      {/* Performance panel from chart data */}
      {chartData?.panel && !chartLoading && (
        <Card title="Performance snapshot">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "var(--space-4)" }}>
            {/* Day stats */}
            <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)", padding: "var(--space-3)", background: "var(--surface-2)", borderRadius: "var(--radius-md)" }}>
              <span style={{ fontSize: "var(--text-xs)", fontWeight: "var(--weight-semibold)", color: "var(--text-subtle)", textTransform: "uppercase" }}>Today</span>
              <div className="stat-row" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
                {chartData.panel.day.ltp != null && (
                  <Stat label="LTP">
                    <span className={`big-num ${trendClass(chartData.panel.day.change_pct)}`}>{fmtNum(chartData.panel.day.ltp)}</span>
                    {chartData.panel.day.change_pct != null && (
                      <span className={`stat-delta ${trendClass(chartData.panel.day.change_pct)}`}>{fmtPct(chartData.panel.day.change_pct)}</span>
                    )}
                  </Stat>
                )}
                {chartData.panel.day.prev_close != null && (
                  <Stat label="Prev Close">{fmtNum(chartData.panel.day.prev_close)}</Stat>
                )}
                {chartData.panel.day.open != null && (
                  <Stat label="Open">{fmtNum(chartData.panel.day.open)}</Stat>
                )}
                {chartData.panel.day.high != null && chartData.panel.day.low != null && (
                  <Stat label="Day Range">{fmtNum(chartData.panel.day.low)} – {fmtNum(chartData.panel.day.high)}</Stat>
                )}
              </div>
              {chartData.panel.day.as_of && (
                <span className="stat-hint">as of {chartData.panel.day.as_of}</span>
              )}
              {chartData.panel.day.incomplete_note && (
                <span className="stat-hint" style={{ color: "var(--warn)" }}>{chartData.panel.day.incomplete_note}</span>
              )}
            </div>

            {/* 52-week range */}
            <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)", padding: "var(--space-3)", background: "var(--surface-2)", borderRadius: "var(--radius-md)" }}>
              <span style={{ fontSize: "var(--text-xs)", fontWeight: "var(--weight-semibold)", color: "var(--text-subtle)", textTransform: "uppercase" }}>52-Week Range</span>
              <div className="stat-row" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
                <Stat label="High">{chartData.panel.week_52.high != null ? fmtNum(chartData.panel.week_52.high) : <Missing reason={chartData.panel.week_52.reason ?? "Unknown"} />}</Stat>
                <Stat label="Low">{chartData.panel.week_52.low != null ? fmtNum(chartData.panel.week_52.low) : <Missing reason={chartData.panel.week_52.reason ?? "Unknown"} />}</Stat>
              </div>
              {chartData.panel.week_52.sessions && (
                <span className="stat-hint">Based on {chartData.panel.week_52.sessions} sessions</span>
              )}
            </div>

            {/* Recent 5 days */}
            {chartData.panel.recent_5_days && chartData.panel.recent_5_days.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)", padding: "var(--space-3)", background: "var(--surface-2)", borderRadius: "var(--radius-md)" }}>
                <span style={{ fontSize: "var(--text-xs)", fontWeight: "var(--weight-semibold)", color: "var(--text-subtle)", textTransform: "uppercase" }}>Recent 5 Sessions</span>
                <div style={{ display: "flex", gap: "var(--space-2)", overflowX: "auto" }}>
                  {chartData.panel.recent_5_days.map((d, i) => (
                    <div key={i} style={{ flex: "0 0 auto", minWidth: "80px", textAlign: "center", padding: "var(--space-2)", background: "var(--surface)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}>
                      <div style={{ fontSize: "var(--text-xs)", color: "var(--text-subtle)" }}>{d.date}</div>
                      <div style={{ fontSize: "var(--text-sm)", fontWeight: "var(--weight-medium)", fontVariantNumeric: "tabular-nums" }}>
                        {d.close != null ? fmtNum(d.close) : <Missing reason="N/A" />}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Performance periods */}
            {chartData.panel.performance && chartData.panel.performance.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)", padding: "var(--space-3)", background: "var(--surface-2)", borderRadius: "var(--radius-md)" }}>
                <span style={{ fontSize: "var(--text-xs)", fontWeight: "var(--weight-semibold)", color: "var(--text-subtle)", textTransform: "uppercase" }}>Performance</span>
                <div className="stat-row" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(100px, 1fr))" }}>
                  {chartData.panel.performance.map((p) => (
                    <Stat key={p.label} label={p.label}>
                      {p.available && p.pct != null ? (
                        <span className={trendClass(p.pct)}>{fmtPct(p.pct)}</span>
                      ) : (
                        <Missing reason="N/A" />
                      )}
                    </Stat>
                  ))}
                </div>
              </div>
            )}
          </div>
        </Card>
      )}

      {chartLoading && <Loading label="Loading chart…" />}

      {/* Valuation */}
      <Card>
        <div className="card-head">
          <span className="card-title">Valuation</span>
        </div>
        <div className="card-body">
          <div className="stat-row">
            <div className="stat">
              <span className="stat-label">Market cap</span>
              <span className="stat-value big-num">
                {renderMeasuredValue(company.valuation.market_cap, fmtRs)}
              </span>
              {company.valuation.market_cap.formula && (
                <span className="stat-hint">{company.valuation.market_cap.formula}</span>
              )}
              {company.valuation.market_cap.as_of && (
                <span className="stat-hint">as of {company.valuation.market_cap.as_of}</span>
              )}
            </div>
            <div className="stat">
              <span className="stat-label">Dividend yield</span>
              <span className="stat-value">
                {renderMeasuredValue(company.valuation.dividend_yield_pct, (v) => fmtPct(v) + "%")}
              </span>
              {company.valuation.dividend_yield_pct.basis && (
                <span className="stat-hint">{company.valuation.dividend_yield_pct.basis}</span>
              )}
              {company.valuation.dividend_yield_pct.cash_dividend_pct != null && (
                <span className="stat-hint">
                  Cash dividend: {fmtPct(company.valuation.dividend_yield_pct.cash_dividend_pct)}%
                </span>
              )}
              {company.valuation.dividend_yield_pct.face_value != null && (
                <span className="stat-hint">
                  Face value: {fmtNum(company.valuation.dividend_yield_pct.face_value)}
                </span>
              )}
              {company.valuation.dividend_yield_pct.fiscal_year && (
                <span className="stat-hint">FY {company.valuation.dividend_yield_pct.fiscal_year}</span>
              )}
            </div>
          </div>
          {Object.keys(company.valuation.ratios).length > 0 && (
            <div className="legend">
              <span className="legend-title">Ratios unavailable</span>
              <ul className="legend-list">
                {Object.entries(company.valuation.ratios).map(([key, val]) => (
                  <li key={key}>
                    <strong>{key.toUpperCase()}</strong>: {val.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </Card>

      {/* Dividends & corporate actions */}
      <Card>
        <div className="card-head">
          <span className="card-title">Dividends & corporate actions</span>
        </div>
        <div className="card-body">
          {company.dividends.count === 0 ? (
            <div className="state state-empty">
              <Missing reason={company.dividends.coverage_note} />
            </div>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Fiscal year</th>
                    <th className="align-right">Cash div %</th>
                    <th className="align-right">Bonus %</th>
                    <th className="align-right">Right %</th>
                    <th>Book close</th>
                    <th>AGM date</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {company.dividends.actions.map((a) => {
                    const action = a as DividendRowWithRight;
                    return (
                      <tr key={a.fiscal_year}>
                        <td>{a.fiscal_year}</td>
                        <td className="align-right">
                          <ProvenanceChip measured={a.cash_dividend_pct} formatter={(v) => fmtPct(v) + "%"} />
                        </td>
                        <td className="align-right">
                          <ProvenanceChip measured={a.bonus_pct} formatter={(v) => fmtPct(v) + "%"} />
                        </td>
                        <td className="align-right">
                          {action.right_pct ? (
                            <ProvenanceChip measured={action.right_pct} formatter={(v) => fmtPct(v) + "%"} />
                          ) : (
                            <Missing reason="Not reported" />
                          )}
                        </td>
                        <td>{a.book_close ?? <Missing reason="Not reported" />}</td>
                        <td>{a.agm_date ?? <Missing reason="Not reported" />}</td>
                        <td><span className="muted">{a.source}</span></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <div className="legend">
            <span className="legend-title">Note</span>
            <ul className="legend-list">
              <li>{company.dividends.coverage_note}</li>
            </ul>
          </div>
        </div>
      </Card>

      {/* Promoter / public split */}
      <Card>
        <div className="card-head">
          <span className="card-title">Promoter / public shareholding</span>
        </div>
        <div className="card-body">
          {renderSplitSection(company.promoter_public_split)}
          <div className="legend">
            <span className="legend-title">Source</span>
            {company.promoter_public_split.available && company.promoter_public_split.source && (
              <span>{company.promoter_public_split.source}</span>
            )}
            {company.promoter_public_split.available && company.promoter_public_split.as_of && (
              <>
                <span className="legend-title">As of</span>
                <span>{company.promoter_public_split.as_of}</span>
              </>
            )}
          </div>
        </div>
      </Card>

      {/* Company news / announcements */}
      <Card>
        <div className="card-head">
          <span className="card-title">Announcements</span>
        </div>
        <div className="card-body">
          {company.news.available === false ? (
            renderUnavailable(company.news)
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
              {company.news.items.map((item) => (
                <div key={item.id} style={{ border: "1px solid var(--border)", borderRadius: "8px", padding: "12px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", marginBottom: "8px" }}>
                    <strong>{item.headline}</strong>
                    <span className="muted">{item.published_at ? new Date(item.published_at).toLocaleString() : ""}</span>
                  </div>
                  {item.type && <span className="badge badge-info">{item.type}</span>}
                  {item.parsed && Object.keys(item.parsed).length > 0 && (
                    <details style={{ marginTop: "8px" }}>
                      <summary className="linkish">Parsed fields</summary>
                      <ul style={{ marginTop: "8px", fontSize: "var(--text-xs)" }}>
                        {Object.entries(item.parsed).map(([k, v]) => (
                          <li key={k}><strong>{k}:</strong> {v}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                  {item.body && (
                    <details style={{ marginTop: "8px" }}>
                      <summary className="linkish">Full text</summary>
                      <div style={{ marginTop: "8px", fontSize: "var(--text-xs)", whiteSpace: "pre-wrap" }}>
                        {item.body}
                      </div>
                    </details>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>

      {/* Book closure */}
      <Card>
        <div className="card-head">
          <span className="card-title">Book closure date</span>
        </div>
        <div className="card-body">
          {renderNoticeFact(company.book_closure)}
          {company.book_closure.available && (
            <div className="legend">
              <span className="legend-title">Note</span>
              <span>{company.book_closure.note}</span>
            </div>
          )}
        </div>
      </Card>

      {/* AGM */}
      <Card>
        <div className="card-head">
          <span className="card-title">AGM date</span>
        </div>
        <div className="card-body">
          {renderNoticeFact(company.agm)}
          {company.agm.available && (
            <div className="legend">
              <span className="legend-title">Note</span>
              <span>{company.agm.note}</span>
            </div>
          )}
        </div>
      </Card>

      {/* Market depth */}
      <Card>
        <div className="card-head">
          <span className="card-title">Market depth (order book)</span>
        </div>
        <div className="card-body">
          {renderMarketDepth(company.market_depth)}
        </div>
      </Card>

      {/* Notes */}
      {company.notes.length > 0 && (
        <Card>
          <div className="card-head">
            <span className="card-title">Notes</span>
          </div>
          <div className="card-body">
            <ul className="notes-list">
              {company.notes.map((note, i) => (
                <li key={i}>{note}</li>
              ))}
            </ul>
          </div>
        </Card>
      )}
    </div>
  );
}

interface DividendRowWithRight extends DividendRow {
  right_pct?: Measured;
}
/* Quarterly Analysis page: view quarterly metrics and fundamental data. */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { quarterly } from "../api";
import { Card, EmptyState, ErrorState, Loading, Missing, Table } from "../components/ui";
import { fmtInt, fmtPct, fmtRs } from "../format";

interface QuarterlyItem {
  symbol: string;
  fiscal_year: string;
  quarter: number;
  quarterly_return: number | null;
  high: number | null;
  low: number | null;
  avg_volume: number | null;
  volatility: number | null;
  revenue: number | null;
  net_profit: number | null;
  eps: number | null;
  book_value_per_share: number | null;
  created_at: string | null;
}

interface QuarterlyResponse {
  symbol: string;
  fiscal_year?: string;
  quarter?: number;
  history?: QuarterlyItem[];
  quarters?: QuarterlyItem[];
}

export function QuarterlyPage() {
  const [symbol, setSymbol] = useState("NABIL");
  const [fiscalYear, setFiscalYear] = useState("");
  const [quarter, setQuarter] = useState<number | "">(1);

  // Available periods
  const { data: periodsData } = useQuery({
    queryKey: ["quarterly-periods"],
    queryFn: () => quarterly.getPeriods(),
    staleTime: 60_000 * 60,
  });

  // Quarterly analysis
  const { data: analysisData, isLoading: analysisLoading, error: analysisError } = useQuery({
    queryKey: ["quarterly", symbol, fiscalYear, quarter],
    queryFn: () => quarterly.getAnalysis(symbol, fiscalYear || undefined, quarter as number | undefined),
    enabled: !!symbol,
  });

  // History
  const { data: historyData } = useQuery({
    queryKey: ["quarterly-history", symbol],
    queryFn: () => quarterly.getHistory(symbol, 20),
    enabled: !!symbol,
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (symbol.trim()) {
      setSymbol(symbol.trim().toUpperCase());
    }
  };

  const renderAnalysis = (data: QuarterlyResponse) => {
    if (!data || (data.quarters && data.quarters.length === 0) && (data.history && data.history.length === 0)) {
      return <EmptyState message="No quarterly data available for this symbol/period." />;
    }

    // Single quarter result
    if (data.fiscal_year && data.quarter) {
      const q = data as QuarterlyItem;
      return (
        <Card title={`Quarterly Analysis: ${q.symbol} FY${q.fiscal_year} Q${q.quarter}`}>
          <div className="stat-row">
            <div className="stat"><span className="stat-label">Quarterly Return</span><span className="stat-value">{q.quarterly_return != null ? fmtPct(q.quarterly_return) + "%" : <Missing reason="Insufficient price data" />}</span></div>
            <div className="stat"><span className="stat-label">High</span><span className="stat-value">{q.high != null ? fmtRs(q.high) : <Missing reason="No price data" />}</span></div>
            <div className="stat"><span className="stat-label">Low</span><span className="stat-value">{q.low != null ? fmtRs(q.low) : <Missing reason="No price data" />}</span></div>
            <div className="stat"><span className="stat-label">Avg Volume</span><span className="stat-value">{q.avg_volume != null ? fmtInt(q.avg_volume) : <Missing reason="No volume data" />}</span></div>
            <div className="stat"><span className="stat-label">Volatility</span><span className="stat-value">{q.volatility != null ? fmtPct(q.volatility * 100, 2) + "%" : <Missing reason="Insufficient data" />}</span></div>
          </div>
          {q.revenue != null && (
            <div className="stat-row" style={{ marginTop: "var(--space-4)", paddingTop: "var(--space-4)", borderTop: "1px solid var(--border)" }}>
              <div className="stat"><span className="stat-label">Revenue</span><span className="stat-value">{fmtRs(q.revenue)}</span></div>
              <div className="stat"><span className="stat-label">Net Profit</span><span className="stat-value">{fmtRs(q.net_profit)}</span></div>
              <div className="stat"><span className="stat-label">EPS</span><span className="stat-value">{q.eps != null ? fmtRs(q.eps) : <Missing reason="Not reported" />}</span></div>
              <div className="stat"><span className="stat-label">Book Value/Share</span><span className="stat-value">{q.book_value_per_share != null ? fmtRs(q.book_value_per_share) : <Missing reason="Not reported" />}</span></div>
            </div>
          )}
          <div className="muted" style={{ marginTop: "var(--space-2)" }}>
            Computed at {q.created_at ? new Date(q.created_at).toLocaleString() : "recently"}
            {q.revenue != null && <span> • Fundamentals from admin import</span>}
          </div>
        </Card>
      );
    }

    // Fiscal year summary
    if (data.quarters) {
      return (
        <Card title={`Quarterly Analysis: ${data.symbol} FY${data.fiscal_year}`}>
          <Table
            rows={data.quarters}
            rowKey={(q) => String(q.quarter)}
            columns={[
              { key: "quarter", header: "Quarter", align: "center", render: (q) => `Q${q.quarter}` },
              { key: "quarterly_return", header: "Return %", align: "right", render: (q) => q.quarterly_return != null ? (q.quarterly_return >= 0 ? <span className="up">{fmtPct(q.quarterly_return)}%</span> : <span className="down">{fmtPct(q.quarterly_return)}%</span>) : <Missing reason="No data" /> },
              { key: "high", header: "High", align: "right", render: (q) => q.high != null ? fmtRs(q.high) : <Missing reason="No data" /> },
              { key: "low", header: "Low", align: "right", render: (q) => q.low != null ? fmtRs(q.low) : <Missing reason="No data" /> },
              { key: "avg_volume", header: "Avg Vol", align: "right", render: (q) => q.avg_volume != null ? fmtInt(q.avg_volume) : <Missing reason="No data" /> },
              { key: "volatility", header: "Volatility", align: "right", render: (q) => q.volatility != null ? fmtPct(q.volatility * 100, 2) + "%" : <Missing reason="No data" /> },
              { key: "revenue", header: "Revenue", align: "right", render: (q) => q.revenue != null ? fmtRs(q.revenue) : <Missing reason="Not imported" /> },
              { key: "net_profit", header: "Net Profit", align: "right", render: (q) => q.net_profit != null ? fmtRs(q.net_profit) : <Missing reason="Not imported" /> },
              { key: "eps", header: "EPS", align: "right", render: (q) => q.eps != null ? fmtRs(q.eps) : <Missing reason="Not imported" /> },
            ]}
            empty="No quarters"
          />
        </Card>
      );
    }

    // History
    if (data.history) {
      return (
        <Card title={`Quarterly History: ${data.symbol} (${data.history.length} quarters)`}>
          <Table
            rows={data.history}
            rowKey={(q) => `${q.fiscal_year}-Q${q.quarter}`}
            columns={[
              { key: "fiscal_year", header: "FY", render: (q) => q.fiscal_year },
              { key: "quarter", header: "Q", align: "center", render: (q) => String(q.quarter) },
              { key: "quarterly_return", header: "Return %", align: "right", render: (q) => q.quarterly_return != null ? (q.quarterly_return >= 0 ? <span className="up">{fmtPct(q.quarterly_return)}%</span> : <span className="down">{fmtPct(q.quarterly_return)}%</span>) : <Missing reason="No data" /> },
              { key: "high", header: "High", align: "right", render: (q) => q.high != null ? fmtRs(q.high) : <Missing reason="No data" /> },
              { key: "low", header: "Low", align: "right", render: (q) => q.low != null ? fmtRs(q.low) : <Missing reason="No data" /> },
              { key: "avg_volume", header: "Avg Vol", align: "right", render: (q) => q.avg_volume != null ? fmtInt(q.avg_volume) : <Missing reason="No data" /> },
              { key: "volatility", header: "Volatility", align: "right", render: (q) => q.volatility != null ? fmtPct(q.volatility * 100, 2) + "%" : <Missing reason="No data" /> },
              { key: "revenue", header: "Revenue", align: "right", render: (q) => q.revenue != null ? fmtRs(q.revenue) : <Missing reason="Not imported" /> },
              { key: "net_profit", header: "Net Profit", align: "right", render: (q) => q.net_profit != null ? fmtRs(q.net_profit) : <Missing reason="Not imported" /> },
            ]}
            empty="No history"
          />
        </Card>
      );
    }

    return null;
  };

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Quarterly Analysis</h1>
          <p className="page-sub">Price-based quarterly metrics and imported fundamentals.</p>
        </div>
      </header>

      <Card title="Query">
        <form onSubmit={handleSearch} style={{ display: "flex", gap: "var(--space-4)", flexWrap: "wrap", alignItems: "flex-end" }}>
          <label className="field">
            <span className="field-label">Symbol</span>
            <input className="input" placeholder="e.g., NABIL" value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} required />
          </label>
          <label className="field">
            <span className="field-label">Fiscal Year (optional)</span>
            <select className="select" value={fiscalYear} onChange={e => setFiscalYear(e.target.value)}>
              <option value="">All years</option>
              {periodsData?.fiscal_years.map((fy: string) => (
                <option key={fy} value={fy}>{fy}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">Quarter (optional)</span>
            <select className="select" value={quarter} onChange={e => setQuarter(e.target.value ? Number(e.target.value) : "")}>
              <option value="">All quarters</option>
              {periodsData?.quarters.map((q: number) => (
                <option key={q} value={q}>Q{q}</option>
              ))}
            </select>
          </label>
          <button type="submit" className="btn btn-primary">Analyze</button>
        </form>
        <div className="muted" style={{ marginTop: "var(--space-2)" }}>
          {periodsData?.note}
        </div>
      </Card>

      {analysisError && <ErrorState error={analysisError} />}
      {analysisLoading && <Loading label="Computing quarterly analysis" />}
      {!analysisLoading && !analysisError && analysisData && renderAnalysis(analysisData)}

      {!analysisLoading && !analysisError && !analysisData && (
        <EmptyState message="No data found. Try a different symbol or period." />
      )}

      {historyData && historyData.history && historyData.history.length > 0 && (
        <Card title="Full History">
          <Table
            rows={historyData.history}
            rowKey={(q) => `${q.fiscal_year}-Q${q.quarter}`}
            columns={[
              { key: "fiscal_year", header: "FY", render: (q) => q.fiscal_year },
              { key: "quarter", header: "Q", align: "center", render: (q) => String(q.quarter) },
              { key: "quarterly_return", header: "Return %", align: "right", render: (q) => q.quarterly_return != null ? (q.quarterly_return >= 0 ? <span className="up">{fmtPct(q.quarterly_return)}%</span> : <span className="down">{fmtPct(q.quarterly_return)}%</span>) : <Missing reason="No data" /> },
              { key: "high", header: "High", align: "right", render: (q) => q.high != null ? fmtRs(q.high) : <Missing reason="No data" /> },
              { key: "low", header: "Low", align: "right", render: (q) => q.low != null ? fmtRs(q.low) : <Missing reason="No data" /> },
              { key: "avg_volume", header: "Avg Vol", align: "right", render: (q) => q.avg_volume != null ? fmtInt(q.avg_volume) : <Missing reason="No data" /> },
              { key: "volatility", header: "Volatility", align: "right", render: (q) => q.volatility != null ? fmtPct(q.volatility * 100, 2) + "%" : <Missing reason="No data" /> },
              { key: "revenue", header: "Revenue", align: "right", render: (q) => q.revenue != null ? fmtRs(q.revenue) : <Missing reason="Not imported" /> },
              { key: "net_profit", header: "Net Profit", align: "right", render: (q) => q.net_profit != null ? fmtRs(q.net_profit) : <Missing reason="Not imported" /> },
            ]}
            empty="No history"
          />
        </Card>
      )}

      <Card title="How It Works">
        <ul style={{ fontSize: "var(--text-sm)", lineHeight: 1.7 }}>
          <li><strong>Price metrics</strong> (return, high, low, avg volume, volatility) are computed from the local price archive for the Nepali fiscal quarter date ranges.</li>
          <li><strong>Fundamentals</strong> (revenue, net profit, EPS, book value/share) come from admin CSV imports via <code>POST /api/reference/fundamentals/import</code>.</li>
          <li><strong>Nepali fiscal year</strong>: Shrawan (mid-Jul) to Ashadh (mid-Jul next year). Q1=Shrawan-Bhadra, Q2=Ashwin-Kartik, Q3=Mangsir-Poush, Q4=Chaitra-Baishakh.</li>
          <li>Results are cached in the <code>quarterly_analysis</code> table for fast subsequent loads.</li>
        </ul>
      </Card>
    </div>
  );
}
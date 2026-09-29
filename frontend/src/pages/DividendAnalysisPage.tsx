/* Dividend Analysis: cross-symbol comparison of dividend history and yields.
 *
 * Features:
 * - Fiscal year selector
 * - Ranking cards: highest yield, most consistent payer, recent payers
 * - Drawer with dividend history bar chart and yield trend
 * - Fixed-deposit rate comparison (user setting)
 * - CSV/Excel export
 */

import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { reference } from "../api";
import { Card, EmptyState, ErrorState, Loading, Missing, ProvenanceChip } from "../components/ui";
import { ProvenanceLegend } from "../provenance";
import { fmtNum, fmtPct, fmtRs } from "../format";

type DividendAnalysisResponse = {
  count: number;
  symbols: {
    symbol: string;
    name: string | null;
    sector: string | null;
    face_value: number | null;
    ltp: number | null;
    dividend_history: {
      fiscal_year: string;
      cash_pct: number;
      bonus_pct: number;
      total_pct: number;
      book_close: string | null;
      agm_date: string | null;
      distribution_date: string | null;
      distribution_reason: string;
      dividend_per_unit: number | null;
      yield_on_ltp: number | null;
      has_dividend: boolean;
      source: string;
    }[];
    consecutive_years_paid: number;
    latest_dividend: any;
    total_dividend_years: number;
  }[];
  ranking: {
    highest_yield: any[];
    most_consistent: any[];
    recent_payers: any[];
  };
  filters: { fiscal_year: string | null; symbol: string | null; min_consecutive: number | null };
};

export function DividendAnalysisPage() {
  const [fiscalYear, setFiscalYear] = useState<string | null>(null);
  const [symbolFilter, setSymbolFilter] = useState<string>("");
  const [minConsecutive, setMinConsecutive] = useState<number | null>(null);
  const [fdRate, setFdRate] = useState<number | null>(null);
  const [drawer, setDrawer] = useState<{ symbol: string; data: any } | null>(null);

  const query = useQuery({
    queryKey: ["dividend-analysis", fiscalYear, symbolFilter, minConsecutive],
    queryFn: ({ signal }) => reference.dividendAnalysis({
      fiscal_year: fiscalYear || undefined,
      symbol: symbolFilter || undefined,
      min_consecutive: minConsecutive ?? undefined,
    }, signal),
    staleTime: 60_000,
  });

  const data = query.data as DividendAnalysisResponse | undefined;
  const symbols = data?.symbols ?? [];

  const availableYears = useMemo(() => {
    const years = new Set<string>();
    symbols.forEach(s => s.dividend_history.forEach(d => years.add(d.fiscal_year)));
    return Array.from(years).sort((a, b) => b.localeCompare(a));
  }, [symbols]);

  const handleExportCsv = useCallback(() => {
    if (!data) return;
    const rows = data.symbols.flatMap(s =>
      s.dividend_history.map(d => ({
        symbol: s.symbol,
        name: s.name,
        sector: s.sector,
        fiscal_year: d.fiscal_year,
        cash_pct: d.cash_pct,
        bonus_pct: d.bonus_pct,
        total_pct: d.total_pct,
        dividend_per_unit: d.dividend_per_unit,
        yield_on_ltp: d.yield_on_ltp,
        book_close: d.book_close,
        agm_date: d.agm_date,
        distribution_date: d.distribution_date,
        distribution_reason: d.distribution_reason,
        has_dividend: d.has_dividend ? "Yes" : "No",
        source: d.source,
      }))
    );
    const headers = Object.keys(rows[0] || {}).join(",");
    const body = rows.map(r => Object.values(r).map(v => `"${v ?? ""}"`).join(",")).join("\n");
    const csv = headers + "\n" + body;
    download(csv, `dividend-analysis-${new Date().toISOString().slice(0,10)}.csv`, "text/csv");
  }, [data]);

  const handleExportExcel = useCallback(() => {
    if (!data) return;
    const rows = data.symbols.flatMap(s =>
      s.dividend_history.map(d => ({
        symbol: s.symbol,
        name: s.name,
        sector: s.sector,
        fiscal_year: d.fiscal_year,
        cash_pct: d.cash_pct,
        bonus_pct: d.bonus_pct,
        total_pct: d.total_pct,
        dividend_per_unit: d.dividend_per_unit,
        yield_on_ltp: d.yield_on_ltp,
        book_close: d.book_close,
        agm_date: d.agm_date,
        distribution_date: d.distribution_date,
        distribution_reason: d.distribution_reason,
        has_dividend: d.has_dividend ? "Yes" : "No",
        source: d.source,
      }))
    );
    const csv = `<?xml version="1.0"?><?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
<Styles><Style ss:ID="hdr"><Font ss:Bold="1"/></Style></Styles>
<Worksheet ss:Name="Dividends"><Table>${["symbol", "name", "sector", "fiscal_year", "cash_pct", "bonus_pct", "total_pct", "dividend_per_unit", "yield_on_ltp", "book_close", "agm_date", "distribution_date", "distribution_reason", "has_dividend", "source"].map(_ => `<Column ss:Width="100"/>`).join("")}
<Row>${Object.keys(rows[0] || {}).map(k => `<Cell ss:StyleID="hdr"><Data ss:Type="String">${k}</Data></Cell>`).join("")}</Row>
${rows.map(r => `<Row>${Object.values(r).map(v => `<Cell><Data ss:Type="String">${v ?? ""}</Data></Cell>`).join("")}</Row>`).join("")}
</Table></Worksheet></Workbook>`;
    download(csv, `dividend-analysis-${new Date().toISOString().slice(0,10)}.xls`, "application/vnd.ms-excel");
  }, [data]);

  if (query.isLoading) return <Loading label="Loading dividend analysis" />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Dividend Analysis</h1>
          <p className="page-sub">
            Cross-symbol dividend history, yields, and consistency rankings.
          </p>
        </div>
        <div className="page-head-actions">
          <label className="field">
            <span className="field-label">Fiscal Year</span>
            <select className="select" value={fiscalYear || ""} onChange={e => setFiscalYear(e.target.value || null)}>
              <option value="">All years</option>
              {availableYears.map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          </label>
          <label className="field">
            <span className="field-label">Symbol</span>
            <input className="input" placeholder="e.g. NABIL" value={symbolFilter} onChange={e => setSymbolFilter(e.target.value)} />
          </label>
          <label className="field">
            <span className="field-label">Min Consecutive Years</span>
            <input className="input input-sm" type="number" min="0" placeholder="e.g. 3" value={minConsecutive ?? ""} onChange={e => setMinConsecutive(e.target.value ? Number(e.target.value) : null)} />
          </label>
          <label className="field">
            <span className="field-label">FD Rate % (for comparison)</span>
            <input className="input input-sm" type="number" step="0.1" placeholder="e.g. 8.5" value={fdRate ?? ""} onChange={e => setFdRate(e.target.value ? Number(e.target.value) : null)} />
          </label>
        </div>
      </header>

      <Card title="Ranking Cards" actions={<ProvenanceLegend />}>
        <div className="stat-row">
          <div className="stat">
            <span className="stat-label">Highest Yield</span>
            <span className="stat-value">
              {data?.ranking.highest_yield[0] ? `${fmtPct(data.ranking.highest_yield[0].latest_dividend?.yield_on_ltp)}% (${data.ranking.highest_yield[0].symbol})` : <Missing reason="No data" />}
            </span>
          </div>
          <div className="stat">
            <span className="stat-label">Most Consistent</span>
            <span className="stat-value">
              {data?.ranking.most_consistent[0] ? `${data.ranking.most_consistent[0].consecutive_years_paid} yrs (${data.ranking.most_consistent[0].symbol})` : <Missing reason="No data" />}
            </span>
          </div>
          <div className="stat">
            <span className="stat-label">Recent Payers</span>
            <span className="stat-value">
              {data?.ranking.recent_payers.length} symbols
            </span>
          </div>
        </div>
      </Card>

      <Card title="Dividend Analysis" actions={
        <>
          <button type="button" className="btn btn-sm" onClick={handleExportCsv} disabled={symbols.length === 0}>Export CSV</button>
          <button type="button" className="btn btn-sm" onClick={handleExportExcel} disabled={symbols.length === 0}>Export Excel</button>
        </>
      }>
        {symbols.length === 0 ? (
          <EmptyState message="No symbols match the current filters." />
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Name</th>
                    <th>Sector</th>
                    <th className="align-right">Face Value</th>
                    <th className="align-right">LTP</th>
                    <th className="align-right">Dividend Years</th>
                    <th className="align-right">Consecutive Yrs</th>
                    <th className="align-right">Latest Yield</th>
                    <th className="align-right">Total % (Latest)</th>
                    <th className="align-right">Cash %</th>
                    <th className="align-right">Bonus %</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {symbols.map(s => (
                    <tr key={s.symbol} onClick={() => setDrawer({ symbol: s.symbol, data: s })}>
                      <td><strong>{s.symbol}</strong></td>
                      <td>{s.name ?? <Missing reason="N/A" />}</td>
                      <td>{s.sector ?? <Missing reason="N/A" />}</td>
                      <td className="align-right">{s.face_value != null ? fmtNum(s.face_value) : <Missing reason="N/A" />}</td>
                      <td className="align-right">{s.ltp != null ? fmtNum(s.ltp) : <Missing reason="N/A" />}</td>
                      <td className="align-right">{s.total_dividend_years}</td>
                      <td className="align-right">{s.consecutive_years_paid}</td>
                      <td className="align-right">
                        {s.latest_dividend?.yield_on_ltp != null
                          ? <span className="up">{fmtPct(s.latest_dividend.yield_on_ltp)}%</span>
                          : <Missing reason="N/A" />}
                      </td>
                      <td className="align-right">
                        {s.latest_dividend?.total_pct != null
                          ? fmtPct(s.latest_dividend.total_pct) + "%"
                          : <Missing reason="N/A" />}
                      </td>
                      <td className="align-right">
                        <ProvenanceChip measured={s.latest_dividend?.cash_pct != null ? { value: s.latest_dividend.cash_pct, status: "ok", as_of: s.latest_dividend.fiscal_year, source: "derived", note: null } : { value: null, status: "not_reported", as_of: null, source: "derived", note: "Not declared" }} formatter={v => fmtPct(v) + "%"} />
                      </td>
                      <td className="align-right">
                        <ProvenanceChip measured={s.latest_dividend?.bonus_pct != null ? { value: s.latest_dividend.bonus_pct, status: "ok", as_of: s.latest_dividend.fiscal_year, source: "derived", note: null } : { value: null, status: "not_reported", as_of: null, source: "derived", note: "Not declared" }} formatter={v => fmtPct(v) + "%"} />
                      </td>
                      <td>
                        <button type="button" className="linkish" onClick={e => { e.stopPropagation(); setDrawer({ symbol: s.symbol, data: s }); }}>Details</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Card>

      {drawer && (
        <div className="drawer-backdrop" onClick={() => setDrawer(null)} role="presentation">
          <div className="drawer" role="dialog" aria-modal="true" aria-label={`Dividend details for ${drawer.symbol}`} onClick={e => e.stopPropagation()}>
            <div className="drawer-head">
              <h2>{drawer.data.name} ({drawer.symbol})</h2>
              <button type="button" className="icon-btn" onClick={() => setDrawer(null)} aria-label="Close">×</button>
            </div>
            <div className="drawer-body">
              <div className="stat-row">
                <div className="stat"><span className="stat-label">Sector</span><span className="stat-value">{drawer.data.sector ?? "–"}</span></div>
                <div className="stat"><span className="stat-label">Face Value</span><span className="stat-value">{drawer.data.face_value != null ? fmtNum(drawer.data.face_value) : "–"}</span></div>
                <div className="stat"><span className="stat-label">LTP</span><span className="stat-value">{drawer.data.ltp != null ? fmtNum(drawer.data.ltp) : "–"}</span></div>
                <div className="stat"><span className="stat-label">Consecutive Yrs</span><span className="stat-value">{drawer.data.consecutive_years_paid}</span></div>
              </div>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Fiscal Year</th>
                      <th className="align-right">Cash %</th>
                      <th className="align-right">Bonus %</th>
                      <th className="align-right">Total %</th>
                      <th className="align-right">Div/Unit (Rs)</th>
                      <th className="align-right">Yield on LTP</th>
                      <th>Book Close</th>
                      <th>AGM Date</th>
                      <th>Distribution Date</th>
                      <th>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                      {drawer.data.dividend_history.map((d: any) => (
                        <tr key={d.fiscal_year}>
                          <td>{d.fiscal_year}</td>
                          <td className="align-right">{d.cash_pct != null ? fmtPct(d.cash_pct) + "%" : <Missing reason="Not declared" />}</td>
                          <td className="align-right">{d.bonus_pct != null ? fmtPct(d.bonus_pct) + "%" : <Missing reason="Not declared" />}</td>
                          <td className="align-right">{fmtPct(d.total_pct) + "%"}</td>
                          <td className="align-right">{d.dividend_per_unit != null ? fmtRs(d.dividend_per_unit) : <Missing reason="N/A" />}</td>
                          <td className="align-right">{d.yield_on_ltp != null ? fmtPct(d.yield_on_ltp) + "%" : <Missing reason="N/A" />}</td>
                          <td>{d.book_close ?? <Missing reason="Not announced" />}</td>
                          <td>{d.agm_date ?? <Missing reason="Not announced" />}</td>
                          <td>{d.distribution_date ?? <Missing reason="Not announced" />}</td>
                          <td>{d.distribution_reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {drawer.data.consecutive_years_paid > 0 && (
                  <div className="notice notice-ok">
                    <strong>Consecutive years paid:</strong> {drawer.data.consecutive_years_paid} year{drawer.data.consecutive_years_paid > 1 ? "s" : ""}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
    </div>
  );
}

function download(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
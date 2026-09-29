/* Corporate Actions: market-wide feed of dividends, bonuses, rights, book closures, AGMs, IPOs, FPOs.
 *
 * Data sourced from:
 * - Corporate actions endpoint (dividends, bonus, rights)
 * - Company announcements (book closures, AGMs, IPO/FPO notices)
 * - Market-wide news feed
 *
 * All dates verbatim as published by NEPSE (DD/MM/YYYY).
 */

import { useCallback, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { reference } from "../api";
import { Badge, Card, EmptyState, ErrorState, Loading, Missing, Table, Toolbar } from "../components/ui";
import { ProvenanceLegend } from "../provenance";
import { fmtPct } from "../format";

export function CorporateActionsPage() {
  const [sector, setSector] = useState<string>("");
  const [actionType, setActionType] = useState<string>("");
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const [upcomingOnly, setUpcomingOnly] = useState(false);
  const [showUpcoming, setShowUpcoming] = useState(false);

  const query = useQuery({
    queryKey: ["corporate-actions", sector, actionType, dateFrom, dateTo, upcomingOnly],
    queryFn: async ({ signal }) => {
      const result = await reference.corporateActionsFeed({
        sector: sector || undefined,
        action_type: actionType || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        upcoming_only: upcomingOnly,
      }, signal);
      return result as { results: any[]; sectors: string[]; action_types: string[]; filters: any };
    },
    staleTime: 60_000,
  });

  const upcomingQuery = useQuery({
    queryKey: ["upcoming-corporate-actions", 30],
    queryFn: async ({ signal }) => {
      const result = await reference.upcomingCorporateActions({ days: 30 }, signal);
      return result as { count: number; period: string; upcoming: any[] };
    },
    staleTime: 60_000,
    enabled: showUpcoming,
  });

  // Type assertions to satisfy TypeScript
  const queryWithTypes = query as {
    data: { results: any[]; sectors: string[]; action_types: string[]; filters: any } | undefined;
    error: Error | null;
    refetch: () => Promise<any>;
    isLoading: boolean;
    isError: boolean;
  };
  const upcomingQueryWithTypes = upcomingQuery as {
    data: { count: number; period: string; upcoming: any[] } | undefined;
    error: Error | null;
    refetch: () => Promise<any>;
    isLoading: boolean;
    isError: boolean;
  };

  const data = queryWithTypes.data;
  const upcomingData = upcomingQueryWithTypes.data;

  const handleExportCsv = useCallback(() => {
    if (!data) return;
    const rows = data.results.map((r: any) => ({
      symbol: r.symbol,
      name: r.name,
      sector: r.sector,
      fiscal_year: r.fiscal_year,
      cash_dividend_pct: r.cash_dividend_pct,
      bonus_pct: r.bonus_pct,
      right_pct: r.right_pct,
      book_close: r.book_close,
      agm_date: r.agm_date,
      action_types: r.action_types.join(";"),
      source: r.source,
      headline: r.headline,
      published_at: r.published_at,
    }));
    const headers = Object.keys(rows[0] || {}).join(",");
    const body = rows.map(r => Object.values(r).map(v => `"${v ?? ""}"`).join(",")).join("\n");
    const csv = headers + "\n" + body;
    download(csv, `corporate-actions-${new Date().toISOString().slice(0,10)}.csv`, "text/csv");
  }, [data]);

  const handleExportExcel = useCallback(() => {
    if (!data) return;
    const rows = data.results.map((r: any) => ({
      symbol: r.symbol,
      name: r.name,
      sector: r.sector,
      fiscal_year: r.fiscal_year,
      cash_dividend_pct: r.cash_dividend_pct,
      bonus_pct: r.bonus_pct,
      right_pct: r.right_pct,
      book_close: r.book_close,
      agm_date: r.agm_date,
      action_types: r.action_types.join(";"),
      source: r.source,
      headline: r.headline,
      published_at: r.published_at,
    }));
    const csv = `<?xml version="1.0"?><?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
<Styles><Style ss:ID="hdr"><Font ss:Bold="1"/></Style></Styles>
<Worksheet ss:Name="CorporateActions"><Table>${["symbol", "name", "sector", "fiscal_year", "cash_dividend_pct", "bonus_pct", "right_pct", "book_close", "agm_date", "action_types", "source", "headline", "published_at"].map(_ => `<Column ss:Width="100"/>`).join("")}
<Row>${Object.keys(rows[0] || {}).map(k => `<Cell ss:StyleID="hdr"><Data ss:Type="String">${k}</Data></Cell>`).join("")}</Row>
${rows.map(r => `<Row>${Object.values(r).map(v => `<Cell><Data ss:Type="String">${v ?? ""}</Data></Cell>`).join("")}</Row>`).join("")}
</Table></Worksheet></Workbook>`;
    download(csv, `corporate-actions-${new Date().toISOString().slice(0,10)}.xls`, "application/vnd.ms-excel");
  }, [data]);

  if (query.isLoading) return <Loading label="Loading corporate actions" />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Corporate Actions</h1>
          <p className="page-sub">
            Market-wide feed of dividends, bonuses, rights, book closures, AGMs, and IPO/FPO notices.
            All dates verbatim as published by NEPSE (DD/MM/YYYY).
          </p>
        </div>
      </header>

      <Card title="Filters" actions={
        <>
          <button type="button" className="btn btn-sm" onClick={() => { setSector(""); setActionType(""); setDateFrom(""); setDateTo(""); setUpcomingOnly(false); }}>Clear</button>
          <button type="button" className="btn btn-sm" onClick={handleExportCsv} disabled={!data || data.results.length === 0}>Export CSV</button>
          <button type="button" className="btn btn-sm" onClick={handleExportExcel} disabled={!data || data.results.length === 0}>Export Excel</button>
        </>
      }>
        <Toolbar>
          <label className="field">
            <span className="field-label">Sector</span>
            <select className="select" value={sector} onChange={e => setSector(e.target.value)}>
              <option value="">All sectors</option>
              {data?.sectors.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>

          <label className="field">
            <span className="field-label">Action Type</span>
            <select className="select" value={actionType} onChange={e => setActionType(e.target.value)}>
              <option value="">All types</option>
              {data?.action_types.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>

          <label className="field">
            <span className="field-label">From Date</span>
            <input className="input input-sm" type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
          </label>
          <label className="field">
            <span className="field-label">To Date</span>
            <input className="input input-sm" type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} />
          </label>

          <label className="check">
            <input type="checkbox" checked={upcomingOnly} onChange={e => setUpcomingOnly(e.target.checked)} />
            <span>Upcoming only</span>
          </label>
        </Toolbar>
      </Card>

      <Toolbar>
        <button
          type="button"
          className={`btn btn-sm ${showUpcoming ? "btn-primary" : ""}`}
          onClick={() => setShowUpcoming(s => !s)}
        >
          Upcoming Book Closures & AGMs (30 days)
        </button>
      </Toolbar>

      {showUpcoming && (
        <Card title={`Upcoming Book Closures & AGMs (next 30 days)`} actions={<ProvenanceLegend />}>
          {upcomingQuery.isLoading ? (
            <Loading label="Loading upcoming events" />
          ) : upcomingQuery.error ? (
            <ErrorState error={upcomingQuery.error} onRetry={() => void upcomingQuery.refetch()} />
          ) : upcomingData && upcomingData.upcoming.length === 0 ? (
            <EmptyState message="No upcoming book closures or AGMs in the next 30 days." />
          ) : (
            <Table
              rows={upcomingData?.upcoming ?? []}
              rowKey={(u: any) => `${u.symbol}-${u.event_type}-${u.date}`}
              columns={[
                { key: "symbol", header: "Symbol", render: (u: any) => <strong>{u.symbol}</strong> },
                { key: "name", header: "Name", render: (u: any) => u.name ?? <Missing reason="N/A" /> },
                { key: "sector", header: "Sector", render: (u: any) => u.sector ?? <Missing reason="N/A" /> },
                { key: "event_type", header: "Event", render: (u: any) => <Badge tone={u.event_type === "agm" ? "info" : "warn"}>{u.event_type.toUpperCase()}</Badge> },
                { key: "date", header: "Date", align: "center", render: (u: any) => u.date },
                { key: "fiscal_year", header: "Fiscal Year", render: (u: any) => u.fiscal_year ?? <Missing reason="N/A" /> },
                { key: "headline", header: "Notice", render: (u: any) => u.headline ? <span title={u.headline}>{u.headline.slice(0, 60)}…</span> : <Missing reason="N/A" /> },
                { key: "source", header: "Source", render: (u: any) => u.source },
              ]}
              empty="No upcoming events."
            />
          )}
        </Card>
      )}

      <Card title={`Corporate Actions Feed${data ? ` (${data.results.length} records)` : ""}`} actions={<ProvenanceLegend />}>
        {queryWithTypes.isLoading ? (
          <Loading label="Loading corporate actions" />
        ) : queryWithTypes.error ? (
          <ErrorState error={queryWithTypes.error} onRetry={() => void queryWithTypes.refetch()} />
        ) : data && data.results.length === 0 ? (
          <EmptyState message="No corporate actions match the current filters." />
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Name</th>
                    <th>Sector</th>
                    <th>Fiscal Year</th>
                    <th className="align-right">Cash %</th>
                    <th className="align-right">Bonus %</th>
                    <th className="align-right">Right %</th>
                    <th>Book Close</th>
                    <th>AGM Date</th>
                    <th>Types</th>
                    <th>Source</th>
                    <th>Notice</th>
                  </tr>
                </thead>
                <tbody>
                  {data?.results.map(r => (
                    <tr key={`${r.symbol}-${r.fiscal_year}-${r.action_types.join(",")}`}>
                      <td><strong>{r.symbol}</strong></td>
                      <td>{r.name ?? <Missing reason="N/A" />}</td>
                      <td>{r.sector ?? <Missing reason="N/A" />}</td>
                      <td>{r.fiscal_year ?? <Missing reason="N/A" />}</td>
                      <td className="align-right">{r.cash_dividend_pct != null ? fmtPct(r.cash_dividend_pct) + "%" : <Missing reason="Not declared" />}</td>
                      <td className="align-right">{r.bonus_pct != null ? fmtPct(r.bonus_pct) + "%" : <Missing reason="Not declared" />}</td>
                      <td className="align-right">{r.right_pct != null ? fmtPct(r.right_pct) + "%" : <Missing reason="Not reported" />}</td>
                      <td>{r.book_close ?? <Missing reason="Not announced" />}</td>
                      <td>{r.agm_date ?? <Missing reason="Not announced" />}</td>
                      <td>
                        {r.action_types.map((t: string) => (
                          <Badge key={t} tone={t === "dividend" ? "ok" : t === "bonus" ? "info" : t === "right" ? "warn" : "neutral"}>{t}</Badge>
                        ))}
                      </td>
                      <td>{r.source}</td>
                      <td>
                        {r.headline && (
                          <span className="linkish" title={r.headline}>{r.headline.slice(0, 40)}…</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data && data.results.length > 0 && (
              <div className="toolbar" style={{ marginTop: "var(--space-4)" }}>
                <button type="button" className="btn btn-sm" onClick={handleExportCsv}>Export CSV</button>
                <button type="button" className="btn btn-sm" onClick={handleExportExcel}>Export Excel</button>
              </div>
            )}
          </>
        )}
      </Card>
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
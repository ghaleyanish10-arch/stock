/* Mutual funds and NAV status.
 *
 * NEPSE does not publish mutual fund NAV - the fund manager declares it. So
 * every NAV here reads "Not published by source" with the reason attached,
 * which is the honest state. Premium/discount stays inactive until a NAV is
 * supplied by CSV import or manual entry.
 *
 * Tabs: Close-Ended / Open-Ended / Matured (derived from scheme_description)
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { reference } from "../api";
import { Badge, Card, ErrorState, Loading, Missing, ProvenanceChip, Table } from "../components/ui";
import { ProvenanceLegend } from "../provenance";
import { fmtInt, fmtNum, fmtPct, fmtRs } from "../format";

const TABS = [
  { value: "all", label: "All" },
  { value: "close_ended", label: "Close-Ended" },
  { value: "open_ended", label: "Open-Ended" },
  { value: "matured", label: "Matured" },
] as const;

export function FundsPage() {
  const [tab, setTab] = useState<typeof TABS[number]["value"]>("all");

  const { data, isLoading, error } = useQuery({
    queryKey: ["funds", tab],
    queryFn: ({ signal }) => reference.funds(tab === "all" ? undefined : tab, signal),
    staleTime: 5 * 60_000,
  });

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Funds</h1>
          <p className="page-sub">
            Mutual funds NEPSE lists as tradable instruments, with NAV status stated
            explicitly.
          </p>
        </div>
        <div className="page-head-actions">
          <div className="seg-group" role="group" aria-label="Fund type">
            {TABS.map((t) => (
              <button
                key={t.value}
                type="button"
                className={`seg-btn ${tab === t.value ? "is-active" : ""}`}
                aria-pressed={tab === t.value}
                onClick={() => setTab(t.value)}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      {data?.nav_note && <div className="notice notice-warn">{data.nav_note}</div>}

      <Card padded={false} actions={<ProvenanceLegend />}>
        {isLoading && <Loading label="Loading funds" />}
        {error && <ErrorState error={error} />}
        {!isLoading && !error && data && (
          <>
            <div className="stat-row" style={{ marginBottom: "var(--space-4)" }}>
              <div className="stat">
                <span className="stat-label">Showing</span>
                <span className="stat-value">{data.count} of {data.total} funds</span>
              </div>
            </div>

            <Table
              rows={data.funds}
              rowKey={(f) => f.code}
              columns={[
                {
                  key: "code",
                  header: "Code",
                  render: (f) => (
                    <strong>
                      <a href={`/chart/${f.code}`} style={{ textDecoration: "none", color: "inherit" }}>
                        {f.code}
                      </a>
                    </strong>
                  ),
                },
                {
                  key: "name",
                  header: "Name",
                  render: (f) => f.name ?? <Missing reason="Not provided" />,
                },
                {
                  key: "scheme_name",
                  header: "Scheme",
                  render: (f) => f.scheme_name ?? <Missing reason="Not provided" />,
                },
                {
                  key: "scheme_description",
                  header: "Description",
                  render: (f) => {
                    if (!f.scheme_description) return <Missing reason="Not provided" />;
                    // Truncate long descriptions
                    const desc = f.scheme_description;
                    return desc.length > 60 ? <span title={desc}>{desc.slice(0, 60)}…</span> : desc;
                  },
                },
                {
                  key: "close_ended",
                  header: "Type",
                  align: "center",
                  render: (f) => {
                    if (f.close_ended === null) return <Missing reason="Not classified" />;
                    if (f.maturity_date && new Date(f.maturity_date) < new Date()) {
                      return <Badge tone="warn">Matured</Badge>;
                    }
                    return f.close_ended ? <Badge tone="info">Close-Ended</Badge> : <Badge tone="ok">Open-Ended</Badge>;
                  },
                },
                {
                  key: "maturity_date",
                  header: "Maturity",
                  align: "center",
                  render: (f) => f.maturity_date ?? <Missing reason="Not available" />,
                },
                {
                  key: "face_value",
                  header: "Face Value",
                  align: "right",
                  render: (f) => f.face_value != null ? fmtNum(f.face_value) : <Missing reason="Not provided" />,
                },
                {
                  key: "units",
                  header: "Units",
                  align: "right",
                  render: (f) => f.units != null ? fmtInt(f.units) : <Missing reason="Not provided" />,
                },
                {
                  key: "fund_size",
                  header: "Fund Size",
                  align: "right",
                  render: (f) => f.fund_size != null ? fmtRs(f.fund_size) : <Missing reason="Not computable" />,
                },
                {
                  key: "listing_date",
                  header: "Listed",
                  align: "center",
                  render: (f) => f.listing_date ?? <Missing reason="Not provided" />,
                },
                {
                  key: "nav",
                  header: "NAV",
                  align: "right",
                  render: (f) => <ProvenanceChip measured={f.nav} formatter={(v) => fmtNum(v)} />,
                },
                {
                  key: "premium_discount",
                  header: "Premium / Discount",
                  align: "right",
                  render: (f) => {
                    if (f.premium_discount == null) {
                      return <span className="mv-chip st-missing" title={f.premium_discount_reason ?? undefined}>Requires NAV</span>;
                    }
                    const color = f.premium_discount >= 0 ? "var(--up)" : "var(--down)";
                    return <span style={{ color }}>{f.premium_discount >= 0 ? "+" : ""}{fmtPct(f.premium_discount)}</span>;
                  },
                },
                {
                  key: "dividend_count",
                  header: "Dividends",
                  align: "right",
                  render: (f) => f.dividend_count > 0 ? f.dividend_count : <Missing reason="None declared" />,
                },
              ]}
              empty="No funds yet. Funds appear here once a mutual fund symbol is enriched."
            />
          </>
        )}
      </Card>

      {data && data.count > 0 && (
        <p className="muted">
          {data.total} fund{data.total === 1 ? "" : "s"} identified from NEPSE's
          instrument type (<Badge tone="info">CDS</Badge>). Laghubitta cooperatives are{" "}
          <Badge tone="info">EQ</Badge> with sector Microfinance and are deliberately excluded.
        </p>
      )}

      {data?.unsynced && data.unsynced.length > 0 && (
        <div style={{ marginTop: "var(--space-4)" }}>
          <Card title="Unsynced CDS Securities">
            <p className="muted" style={{ marginBottom: "var(--space-4)" }}>
              {data.unsynced_count} CDS securit{data.unsynced_count === 1 ? "y" : "ies"} in NEPSE master have no local fund row.
              Run <code>POST /api/reference/sync</code> to create them.
            </p>
            <Table
              rows={data.unsynced}
              rowKey={(u) => u.symbol}
              columns={[
                { key: "symbol", header: "Symbol", render: (u) => <strong>{u.symbol}</strong> },
                { key: "name", header: "Name", render: (u) => u.name ?? <Missing reason="Not provided" /> },
                {
                  key: "reason",
                  header: "Reason",
                  render: (u) => <span className="mv-chip st-missing" title={u.reason}>{u.reason}</span>,
                },
                { key: "nepse_security_id", header: "NEPSE ID", align: "center", render: (u) => u.nepse_security_id ?? <Missing reason="Unknown" /> },
                { key: "listed_shares", header: "Listed Shares", align: "right", render: (u) => u.listed_shares != null ? fmtInt(u.listed_shares) : <Missing reason="Unknown" /> },
                { key: "promoter_pct", header: "Promoter %", align: "right", render: (u) => u.promoter_pct != null ? fmtPct(u.promoter_pct) + "%" : <Missing reason="Unknown" /> },
                { key: "public_pct", header: "Public %", align: "right", render: (u) => u.public_pct != null ? fmtPct(u.public_pct) + "%" : <Missing reason="Unknown" /> },
              ]}
              empty="All CDS securities are synced"
            />
          </Card>
        </div>
      )}
    </div>
  );
}
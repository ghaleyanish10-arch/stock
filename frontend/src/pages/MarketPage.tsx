/* Market overview: index, session totals, sub-indices, movers, and index chart. */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { market } from "../api";
import { Card, ErrorState, Loading, Stat } from "../components/ui";
import { fmtDate, fmtInt, fmtNum, fmtPct, fmtRs, trendClass } from "../format";

const RANGES = [
  { label: "1M", days: 30 },
  { label: "3M", days: 90 },
  { label: "6M", days: 182 },
  { label: "1Y", days: 365 },
];

export function MarketPage() {
  const [indexName, setIndexName] = useState("nepse");
  const [days, setDays] = useState(90);

  const overview = useQuery({
    queryKey: ["market-overview"],
    queryFn: ({ signal }) => market.overview(signal),
    refetchInterval: 30_000,
  });

  const indices = useQuery({
    queryKey: ["indices"],
    queryFn: ({ signal }) => market.indices(signal),
    refetchInterval: 60_000,
  });

  const gainers = useQuery({
    queryKey: ["top-gainers"],
    queryFn: ({ signal }) => market.topGainers(10, signal),
    refetchInterval: 60_000,
  });

  const losers = useQuery({
    queryKey: ["top-losers"],
    queryFn: ({ signal }) => market.topLosers(10, signal),
    refetchInterval: 60_000,
  });

  const range = useMemo(() => {
    const end = new Date();
    const start = new Date(end.getTime() - days * 86_400_000);
    return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
  }, [days]);

  const history = useQuery({
    queryKey: ["index-history", indexName, range.start, range.end],
    queryFn: ({ signal }) => market.indexHistory(indexName, range.start, range.end, signal),
  });

  if (overview.isLoading) return <Loading label="Loading market" />;
  if (overview.error) {
    return <ErrorState error={overview.error} onRetry={() => void overview.refetch()} />;
  }

  const data = overview.data;
  if (!data) return <Loading label="Loading market" />;

  const idx = data.nepse_index;
  const summary = data.summary;
  const isClosed = idx?.is_closed === true;
  const trend = trendClass(idx?.change);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Market</h1>
          <p className="page-sub">
            {data.status.is_open ? "Live session" : "Market closed"} · as of{" "}
            {fmtDate(data.status.as_of)}
          </p>
        </div>
      </header>

      {/* Key stats */}
      <div className="stat-row">
        <Stat
          label="NEPSE Index"
          hint={isClosed ? "Last known close" : "Live"}
        >
          <span className={`big-num ${trend}`}>{fmtNum(idx?.value)}</span>
          {!isClosed && (
            <span className={`stat-delta ${trend}`}>
              {fmtPct(idx?.change_percentage)}
            </span>
          )}
        </Stat>
        <Stat label="Turnover" hint={fmtDate(summary?.business_date)}>
          {fmtRs(summary?.total_turnover)}
        </Stat>
        <Stat label="Shares traded">
          {fmtInt(summary?.total_traded_shares)}
        </Stat>
        <Stat label="Transactions">
          {fmtInt(summary?.total_transactions)}
        </Stat>
        <Stat label="Scrips traded">
          {fmtInt(summary?.traded_scrips)}
        </Stat>
      </div>

      {/* Sub-indices strip */}
      {indices.data?.sub_indices && indices.data.sub_indices.length > 0 && (
        <Card title="Sub-indices" padded={false}>
          <div className="sub-indices-strip" style={{
            display: "flex",
            gap: "var(--space-3)",
            overflowX: "auto",
            padding: "var(--space-3) var(--space-4)",
            flexWrap: "nowrap"
          }}>
            {indices.data.sub_indices.map((si) => {
              const siTrend = trendClass(si.change);
              return (
                <div key={si.name} className="sub-index-item" style={{
                  flex: "0 0 auto",
                  minWidth: "180px",
                  padding: "var(--space-2) var(--space-3)",
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius-md)",
                  display: "flex",
                  flexDirection: "column",
                  gap: "var(--space-1)"
                }}>
                  <span style={{
                    fontSize: "var(--text-xs)",
                    fontWeight: "var(--weight-semibold)",
                    color: "var(--text-subtle)",
                    textTransform: "uppercase",
                    letterSpacing: "0.06em"
                  }}>
                    {si.name}
                  </span>
                  <div style={{ display: "flex", alignItems: "baseline", gap: "var(--space-2)" }}>
                    <span className={`big-num ${siTrend}`} style={{ fontSize: "var(--text-lg)" }}>
                      {fmtNum(si.value)}
                    </span>
                    {si.change_percentage != null && (
                      <span className={`stat-delta ${siTrend}`}>
                        {fmtPct(si.change_percentage)}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {/* Top movers */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)" }}>
        <Card title="Top Gainers" padded={false}>
          {gainers.isLoading ? (
            <div style={{ padding: "var(--space-4)" }}><Loading label="Loading gainers" /></div>
          ) : gainers.data?.length ? (
            <div className="movers-list" style={{ padding: "var(--space-3) var(--space-4)" }}>
              {gainers.data.map((g, i) => (
                <div key={g.symbol} className="mover-item" style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "var(--space-2) 0",
                  borderBottom: i < gainers.data.length - 1 ? "1px solid var(--border)" : "none"
                }}>
                  <div>
                    <span style={{ fontWeight: "var(--weight-medium)" }}>{g.symbol}</span>
                    {g.security_name && (
                      <span className="muted" style={{ marginLeft: "var(--space-2)", fontSize: "var(--text-xs)" }}>
                        {g.security_name}
                      </span>
                    )}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", textAlign: "right" }}>
                    {g.ltp != null && <span className="muted" style={{ fontSize: "var(--text-sm)" }}>{fmtNum(g.ltp)}</span>}
                    <span className={`badge badge-up`} style={{ fontSize: "var(--text-xs)" }}>
                      {g.percentage_change != null ? `+${fmtPct(g.percentage_change)}%` : "+"}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="state state-empty" style={{ padding: "var(--space-4)" }}>
              <span>No gainers data</span>
            </div>
          )}
        </Card>

        <Card title="Top Losers" padded={false}>
          {losers.isLoading ? (
            <div style={{ padding: "var(--space-4)" }}><Loading label="Loading losers" /></div>
          ) : losers.data?.length ? (
            <div className="movers-list" style={{ padding: "var(--space-3) var(--space-4)" }}>
              {losers.data.map((l, i) => (
                <div key={l.symbol} className="mover-item" style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "var(--space-2) 0",
                  borderBottom: i < losers.data.length - 1 ? "1px solid var(--border)" : "none"
                }}>
                  <div>
                    <span style={{ fontWeight: "var(--weight-medium)" }}>{l.symbol}</span>
                    {l.security_name && (
                      <span className="muted" style={{ marginLeft: "var(--space-2)", fontSize: "var(--text-xs)" }}>
                        {l.security_name}
                      </span>
                    )}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", textAlign: "right" }}>
                    {l.ltp != null && <span className="muted" style={{ fontSize: "var(--text-sm)" }}>{fmtNum(l.ltp)}</span>}
                    <span className={`badge badge-down`} style={{ fontSize: "var(--text-xs)" }}>
                      {l.percentage_change != null ? `${fmtPct(l.percentage_change)}%` : "-"}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="state state-empty" style={{ padding: "var(--space-4)" }}>
              <span>No losers data</span>
            </div>
          )}
        </Card>
      </div>

      {/* Index history chart */}
      <Card
        title="Index history"
        actions={
          <div className="seg">
            <select
              className="input input-sm"
              value={indexName}
              onChange={(e) => setIndexName(e.target.value)}
              aria-label="Index"
            >
              <option value="nepse">NEPSE</option>
              {(indices.data?.sub_indices ?? []).map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name}
                </option>
              ))}
            </select>
            <div className="seg-group" role="group" aria-label="Range">
              {RANGES.map((r) => (
                <button
                  key={r.label}
                  type="button"
                  className={`seg-btn ${days === r.days ? "active" : ""}`}
                  onClick={() => setDays(r.days)}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>
        }
      >
        {history.isLoading ? (
          <Loading label="Loading history" />
        ) : history.error ? (
          <ErrorState error={history.error} onRetry={() => void history.refetch()} />
        ) : (
          <Sparkline points={(history.data?.history ?? []).map((p) => p.close)} />
        )}
        {history.data && (
          <p className="muted">
            {history.data.count} points, {fmtDate(history.data.start)} to{" "}
            {fmtDate(history.data.end)}
          </p>
        )}
      </Card>
    </div>
  );
}

function Sparkline({ points }: { points: (number | null)[] }) {
  const values = points.filter((p): p is number => p != null);
  if (values.length < 2) {
    return <p className="prose">Not enough points in this range to draw a line.</p>;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const w = 1000;
  const h = 220;
  const step = w / (values.length - 1);

  const path = values
    .map((v, i) => {
      const x = i * step;
      const y = h - ((v - min) / span) * (h - 20) - 10;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const rising = values[values.length - 1] >= values[0];
  const stroke = rising ? "var(--up)" : "var(--down)";

  // Generate SVG circle elements for hover tooltips
  const pointsData = values.map((v, i) => ({
    x: i * step,
    y: h - ((v - min) / span) * (h - 20) - 10,
    value: v,
    index: i,
  }));

  return (
    <div className="spark">
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" aria-label="Index close over time">
        <path d={path} fill="none" stroke={stroke} strokeWidth="2" vectorEffect="non-scaling-stroke" />
        {/* Hover points with tooltips */}
        {pointsData.map((p) => (
          <g key={p.index}>
            <circle
              cx={p.x}
              cy={p.y}
              r="6"
              fill="transparent"
              stroke="transparent"
              strokeWidth="10"
              onMouseEnter={() => {
                const tooltip = document.getElementById(`spark-tooltip-${p.index}`);
                if (tooltip) tooltip.style.display = "block";
              }}
              onMouseLeave={() => {
                const tooltip = document.getElementById(`spark-tooltip-${p.index}`);
                if (tooltip) tooltip.style.display = "none";
              }}
            />
            <title id={`spark-tooltip-${p.index}`} style={{ display: "none" }}>
              Value: {fmtNum(p.value)}
            </title>
          </g>
        ))}
      </svg>
      <div className="spark-axis">
        <span>{fmtNum(min)}</span>
        <span>{fmtNum(max)}</span>
      </div>
    </div>
  );
}
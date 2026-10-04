/* Market overview: index, session totals, sub-indices, movers, and index chart. */

import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { market } from "../api";
import { Card, ErrorState, Loading, Stat } from "../components/ui";
import { fmtDate, fmtInt, fmtNum, fmtPct, fmtRs, fmtSigned, trendClass } from "../format";
import type { IndexPoint } from "../types";

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
                      {/* fmtPct already emits the sign and %: manual +/% around it made "++2.00%%". */}
                      {g.percentage_change != null ? fmtPct(g.percentage_change) : "+"}
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
                      {l.percentage_change != null ? fmtPct(l.percentage_change) : "-"}
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
          <Sparkline data={history.data?.history ?? []} />
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
}/**
 * Index history sparkline with a crosshair hover: the nearest session's date,
 * close, change vs the previous session, turnover, volume and trades show in
 * a tooltip while a vertical guide + dot track the line. The old per-point
 * invisible circles + hidden <title> approach never actually displayed.
 */
function Sparkline({ data }: { data: IndexPoint[] }) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [hover, setHover] = useState<number | null>(null);

  // Only sessions with a close can sit on the line; keep the rest of the
  // payload for the tooltip. The API returns newest-first, so sort ascending -
  // otherwise the line (and its up/down colour) is drawn time-reversed and the
  // hover "change vs previous session" compares the wrong neighbours.
  const pts = useMemo(
    () =>
      data
        .filter((p): p is IndexPoint & { close: number } => p.close != null)
        .slice()
        .sort((a, b) => (a.business_date ?? "").localeCompare(b.business_date ?? "")),
    [data],
  );

  if (pts.length < 2) {
    return <p className="prose">Not enough points in this range to draw a line.</p>;
  }

  const values = pts.map((p) => p.close);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const w = 1000;
  const h = 220;
  const step = w / (values.length - 1);
  const xAt = (i: number) => i * step;
  const yAt = (v: number) => h - ((v - min) / span) * (h - 20) - 10;

  const path = values
    .map((v, i) => `${i === 0 ? "M" : "L"}${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`)
    .join(" ");

  const rising = values[values.length - 1] >= values[0];
  const stroke = rising ? "var(--up)" : "var(--down)";

  // Map mouse x through the viewBox; preserveAspectRatio="none" keeps the
  // mapping linear between container pixels and chart coordinates.
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return;
    const xView = ((e.clientX - rect.left) / rect.width) * w;
    const i = Math.min(values.length - 1, Math.max(0, Math.round(xView / step)));
    setHover(i);
  };

  const hp = hover != null ? pts[hover] : null;
  const prev = hover != null && hover > 0 ? pts[hover - 1] : null;
  const chg = hp && prev ? hp.close - prev.close : null;
  const chgPct = hp && prev && prev.close !== 0 ? (chg! / prev.close) * 100 : null;

  const tipLeft = hover != null ? (xAt(hover) / w) * 100 : 0;
  const tipTop = hp ? (yAt(hp.close) / h) * 100 : 0;
  // Flip the box before it runs off the right edge.
  const flip = tipLeft > 70;

  return (
    <div className="spark" style={{ position: "relative" }}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${w} ${h}`}
        preserveAspectRatio="none"
        role="img"
        aria-label="Index close over time"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        <path d={path} fill="none" stroke={stroke} strokeWidth="2" vectorEffect="non-scaling-stroke" />
        {hover != null && hp && (
          <g>
            <line
              x1={xAt(hover)}
              x2={xAt(hover)}
              y1={0}
              y2={h}
              stroke="var(--border-strong)"
              strokeDasharray="4 4"
              vectorEffect="non-scaling-stroke"
            />
            <circle
              cx={xAt(hover)}
              cy={yAt(hp.close)}
              r="4"
              fill={stroke}
              stroke="var(--surface)"
              strokeWidth="1.5"
            />
          </g>
        )}
      </svg>
      {hover != null && hp && (
        <div
          className="spark-tip"
          style={{
            left: `${tipLeft}%`,
            top: `${tipTop}%`,
            transform: `translate(${flip ? "calc(-100% - 8px)" : "8px"}, -50%)`,
          }}
        >
          <div className="spark-tip-date">{fmtDate(hp.business_date)}</div>
          <div className="spark-tip-grid">
            <span>Close</span>
            <strong>{fmtNum(hp.close)}</strong>
            {chg != null && (
              <>
                <span>Change</span>
                <span className={trendClass(chg)}>
                  {fmtSigned(chg)} ({fmtPct(chgPct)})
                </span>
              </>
            )}
            {hp.turnover != null && (
              <>
                <span>Turnover</span>
                <span>{fmtRs(hp.turnover)}</span>
              </>
            )}
            {hp.volume != null && (
              <>
                <span>Volume</span>
                <span>{fmtInt(hp.volume)}</span>
              </>
            )}
            {hp.total_transactions != null && (
              <>
                <span>Trades</span>
                <span>{fmtInt(hp.total_transactions)}</span>
              </>
            )}
          </div>
        </div>
      )}
      <div className="spark-axis">
        <span>{fmtNum(min)}</span>
        <span>{fmtNum(max)}</span>
      </div>
    </div>
  );
}
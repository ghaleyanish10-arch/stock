/* Market map: treemap and sector pie.
 *
 * Two views over the same data. The treemap nests tiles inside sector groups so
 * a sector's weight is readable at a glance; the pie shows the same figures as
 * proportional arcs. Both are sized by one selected metric and coloured by one
 * selected period, with a fixed +/-6% legend so a colour means the same thing in
 * every configuration.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { analytics } from "../api";
import type { PeriodKey, SizeMetric, TreemapTile } from "../types";
import { changeColor, groupBy, isTooSmall, type LaidOutTile } from "../treemap";
import { fmtNum, fmtPct, fmtRs } from "../format";
import { Card, EmptyState, ErrorState, Loading } from "../components/ui";

/** A null cell that always shows *why* it is null, never a bare dash. */
function Missing({ reason }: { reason: string }) {
  return (
    <span className="mv mv-missing" title={reason}>
      {reason}
    </span>
  );
}

const PERIODS: { value: PeriodKey; label: string }[] = [
  { value: "1D", label: "1D" },
  { value: "1W", label: "1W" },
  { value: "1M", label: "1M" },
  { value: "3M", label: "3M" },
  { value: "6M", label: "6M" },
  { value: "1Y", label: "1Y" },
  { value: "YTD", label: "YTD" },
];

const SIZES: { value: SizeMetric; label: string; hint: string }[] = [
  { value: "market_cap", label: "Market cap", hint: "listed shares x LTP" },
  { value: "volume", label: "Volume", hint: "shares traded in period" },
  { value: "turnover", label: "Turnover", hint: "NPR traded in period" },
];

type View = "treemap" | "pie";

interface Tile extends TreemapTile {
  sector: string | null;
  // Alias `size` as `value` to satisfy `groupBy` constraint T extends { value: number }
  value: number;
}

export function MarketMapPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [view, setView] = useState<View>("treemap");
  const [fullscreen, setFullscreen] = useState(false);
  const [find, setFind] = useState("");
  const [size, setSize] = useState<{ w: number; h: number }>({ w: 900, h: 560 });
  const frameRef = useRef<HTMLDivElement>(null);

  const period = (params.get("period") as PeriodKey) || "1M";
  const metric = (params.get("size") as SizeMetric) || "market_cap";

  const setParam = useCallback(
    (key: string, value: string) => {
      const next = new URLSearchParams(params);
      next.set(key, value);
      setParams(next, { replace: true });
    },
    [params, setParams],
  );

  const { data, isLoading, error } = useQuery({
    queryKey: ["heatmap", period, metric],
    queryFn: ({ signal }) => analytics.heatmap({ period, size: metric }, signal),
  });

  // Track the frame so the treemap fills whatever space it is given, and
  // recompute on resize. Without this the layout would be computed once at a
  // guessed size and be wrong on every other viewport.
  useEffect(() => {
    const el = frameRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect;
      if (box && box.width > 0 && box.height > 0) {
        setSize({ w: Math.floor(box.width), h: Math.floor(box.height) });
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [fullscreen, view]);

  // Escape leaves fullscreen, matching every other modal overlay.
  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFullscreen(false);
    };
    window.addEventListener("keydown", onKey);
    document.body.classList.add("map-fullscreen");
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.classList.remove("map-fullscreen");
    };
  }, [fullscreen]);

  const tiles = useMemo<Tile[]>(
    () => (data?.tiles ?? []).map((t) => ({ ...t, sector: t.sector, value: t.size })),
    [data],
  );

  const groups = useMemo(
    () => groupBy(tiles, { x: 0, y: 0, width: size.w, height: size.h }, (t) => t.size),
    [tiles, size],
  );

  const legendMax = data?.legend.max_pct ?? 6;
  const coverage = data?.coverage;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Market map</h1>
          <p className="page-sub">
            {SIZES.find((s) => s.value === metric)?.hint}, coloured by{" "}
            {PERIODS.find((p) => p.value === period)?.label} return.
          </p>
        </div>
        <div className="page-head-actions">
          <div className="seg-group" role="group" aria-label="View">
            {(["treemap", "pie"] as View[]).map((v) => (
              <button
                key={v}
                type="button"
                className={`seg-btn ${view === v ? "is-active" : ""}`}
                aria-pressed={view === v}
                onClick={() => setView(v)}
              >
                {v === "treemap" ? "Treemap" : "Pie"}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => setFullscreen((f) => !f)}
            aria-pressed={fullscreen}
          >
            {fullscreen ? "Exit full screen" : "Full screen"}
          </button>
        </div>
      </header>

      <div className="map-toolbar">
        <fieldset className="map-filter">
          <legend>Period</legend>
          <div className="seg-group">
            {PERIODS.map((p) => (
              <button
                key={p.value}
                type="button"
                className={`seg-btn ${period === p.value ? "is-active" : ""}`}
                aria-pressed={period === p.value}
                onClick={() => setParam("period", p.value)}
              >
                {p.label}
              </button>
            ))}
          </div>
        </fieldset>

        <fieldset className="map-filter">
          <legend>Size by</legend>
          <div className="seg-group">
            {SIZES.map((s) => (
              <button
                key={s.value}
                type="button"
                className={`seg-btn ${metric === s.value ? "is-active" : ""}`}
                aria-pressed={metric === s.value}
                onClick={() => setParam("size", s.value)}
              >
                {s.label}
              </button>
            ))}
          </div>
        </fieldset>

        <div className="map-find">
          <label className="field-label" htmlFor="map-find">
            Find symbol
          </label>
          <input
            id="map-find"
            className="input"
            list="map-find-symbols"
            placeholder="e.g. NABIL"
            value={find}
            onChange={(e) => setFind(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== "Enter") return;
              const hit = tiles.find(
                (t) => t.symbol.toLowerCase() === find.trim().toLowerCase(),
              );
              if (hit) navigate(`/chart/${hit.symbol}`);
            }}
          />
          <datalist id="map-find-symbols">
            {tiles.slice(0, 250).map((t) => (
              <option key={t.symbol} value={t.symbol}>
                {t.name ?? ""}
              </option>
            ))}
          </datalist>
        </div>
      </div>

      <div className="map-legend" aria-hidden="true">
        <span className="map-legend-label">
          {PERIODS.find((p) => p.value === period)?.label} return
        </span>
        <span className="map-legend-scale">
          <span className="map-legend-cap">-{legendMax.toFixed(0)}%</span>
          {Array.from({ length: 13 }, (_, i) => {
            const t = i / 12;
            const pct = -legendMax + t * legendMax * 2;
            return (
              <span
                key={i}
                className="map-legend-swatch"
                style={{ background: changeColor(pct, legendMax) }}
              />
            );
          })}
          <span className="map-legend-cap">+{legendMax.toFixed(0)}%</span>
        </span>
        <span className="map-legend-note">
          Colour clamps at the ends; every tile prints its true percentage.
        </span>
      </div>

      {isLoading && <Loading label="Building the market map" />}
      {error && <ErrorState error={error} />}

      {!isLoading && !error && data && (
        <>
          {data.counts.skipped > 0 && (
            <div className="map-skipped">
              <p className="map-warn">
                <strong>
                  {data.counts.skipped} of {data.counts.scanned} securities could not be
                  drawn
                </strong>{" "}
                for this combination.{" "}
                {data.skipped[0]?.reason ? <>Example: {data.skipped[0].reason}</> : null}{" "}
                Promoter shares and debentures have no published listed shares, so they
                have no market cap.
              </p>
            </div>
          )}

          {data.counts.truncated > 0 && (
            <p className="hint">
              Showing the {data.counts.drawn} largest of {data.counts.drawn + data.counts.truncated}{" "}
              matching securities. Small tiles would be unreadable below that.
            </p>
          )}

          <div className={`map-frame ${fullscreen ? "is-fullscreen" : ""}`} ref={frameRef}>
            {view === "treemap" ? (
              <TreemapView
                groups={groups}
                period={period}
                legendMax={legendMax}
                onPick={(symbol) => navigate(`/chart/${symbol}`)}
              />
            ) : (
              <PieView
                sectors={data.sectors}
                total={data.sectors.reduce((a, s) => a + s.size, 0)}
                period={period}
                legendMax={legendMax}
                metric={metric}
                onPick={(sector) => {
                  const first = tiles.find((t) => t.sector === sector);
                  if (first) navigate(`/screener?sector=${encodeURIComponent(sector)}`);
                }}
              />
            )}
          </div>

          {coverage && (
            <p className="hint">
              Archive covers {fmtNum(coverage.sessions, 0)} sessions,{" "}
              {coverage.first} to {coverage.last}. {coverage.note}
            </p>
          )}

          {view === "pie" && (
            <Card title="Sectors">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Sector</th>
                    <th scope="col" className="num">
                      Securities
                    </th>
                    <th scope="col" className="num">
                      {SIZES.find((s) => s.value === metric)?.label}
                    </th>
                    <th scope="col" className="num">
                      {PERIODS.find((p) => p.value === period)?.label} return
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.sectors.map((s) => (
                    <tr key={s.sector}>
                      <th scope="row">{s.sector}</th>
                      <td className="num">{s.symbols}</td>
                      <td className="num">
                        {metric === "turnover" ? fmtRs(s.size) : fmtNum(s.size, 0)}
                      </td>
                      <td className={`num ${(s.change_pct ?? 0) >= 0 ? "up" : "down"}`}>
                        {s.change_pct === null ? (
                          <Missing reason="Not computable for this period" />
                        ) : (
                          fmtPct(s.change_pct)
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

interface Group {
  sector: string;
  rect: { x: number; y: number; width: number; height: number };
  tiles: LaidOutTile<Tile>[];
  value: number;
}

function TreemapView({
  groups,
  period,
  legendMax,
  onPick,
}: {
  groups: Group[];
  period: PeriodKey;
  legendMax: number;
  onPick: (symbol: string) => void;
}) {
  if (groups.length === 0) {
    return (
      <EmptyState message="No security has both a value for this sizing metric and a computable return for this period. Try a shorter period, or size by volume instead of market cap." />
    );
  }

  return (
    <svg
      className="treemap"
      role="img"
      aria-label={`Treemap of securities by ${period} return`}
    >
      {groups.map((group) => (
        <g key={group.sector}>
          <rect
            x={group.rect.x}
            y={group.rect.y}
            width={group.rect.width}
            height={group.rect.height}
            className="treemap-group-bg"
          />
          <text
            x={group.rect.x + 5}
            y={group.rect.y + 13}
            className="treemap-group-label"
          >
            {group.sector}
          </text>
          {group.tiles.map((tile) => {
            const tiny = isTooSmall(tile);
            return (
              <g
                key={tile.item.symbol}
                className="treemap-tile"
                tabIndex={0}
                role="button"
                aria-label={`${tile.item.symbol}, ${tile.item.name ?? "no name"}, ${fmtPct(
                  tile.item.change_pct,
                )}`}
                onClick={() => onPick(tile.item.symbol)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onPick(tile.item.symbol);
                  }
                }}
              >
                <title>
                  {`${tile.item.symbol} - ${tile.item.name ?? ""}\n${fmtPct(
                    tile.item.change_pct,
                  )} (${period})\nLTP ${fmtNum(tile.item.ltp)}`}
                </title>
                <rect
                  x={tile.x}
                  y={tile.y + (tiny ? 0 : 14)}
                  width={Math.max(0, tile.width - 1)}
                  height={Math.max(0, tile.height - 1)}
                  fill={changeColor(tile.item.change_pct, legendMax)}
                />
                {!tiny && (
                  <>
                    <text x={tile.x + 5} y={tile.y + 24} className="treemap-symbol">
                      {tile.item.symbol}
                    </text>
                    {tile.height > 44 && (
                      <text x={tile.x + 5} y={tile.y + 36} className="treemap-change">
                        {fmtPct(tile.item.change_pct, 1)}
                      </text>
                    )}
                  </>
                )}
              </g>
            );
          })}
        </g>
      ))}
    </svg>
  );
}

function PieView({
  sectors,
  total,
  period,
  legendMax,
  metric,
  onPick,
}: {
  sectors: { sector: string; size: number; symbols: number; change_pct: number | null }[];
  total: number;
  period: PeriodKey;
  legendMax: number;
  metric: SizeMetric;
  onPick: (sector: string) => void;
}) {
  if (total <= 0) {
    return (
      <EmptyState message="No sector has a computable value for this metric and period." />
    );
  }

  const size = 340;
  const radius = size / 2 - 6;
  const cx = size / 2;
  const cy = size / 2;
  let angle = -Math.PI / 2; // start at 12 o'clock

  const arcs = sectors.map((s) => {
    const sweep = (s.size / total) * Math.PI * 2;
    const start = angle;
    const end = angle + sweep;
    angle = end;
    const large = sweep > Math.PI ? 1 : 0;
    // A full-circle single sector would collapse to a zero-length arc, so it is
    // drawn as a ring instead.
    const d =
      sectors.length === 1
        ? `M ${cx} ${cy - radius} A ${radius} ${radius} 0 1 1 ${cx - 0.01} ${cy - radius} L ${cx} ${cy} Z`
        : `M ${cx} ${cy} L ${cx + radius * Math.cos(start)} ${cy + radius * Math.sin(start)} A ${radius} ${radius} 0 ${large} 1 ${
            cx + radius * Math.cos(end)
          } ${cy + radius * Math.sin(end)} Z`;
    return { sector: s.sector, d, change: s.change_pct ?? 0, size: s.size };
  });

  return (
    <div className="pie-wrap">
      <svg className="pie" viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Sector shares">
        {arcs.map((a) => (
          <path
            key={a.sector}
            d={a.d}
            fill={changeColor(a.change, legendMax)}
            className="pie-slice"
            tabIndex={0}
            role="button"
            aria-label={`${a.sector}, ${(a.size / total * 100).toFixed(1)} percent`}
            onClick={() => onPick(a.sector)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onPick(a.sector);
              }
            }}
          >
            <title>
              {`${a.sector}\n${metric === "turnover" ? fmtRs(a.size) : fmtNum(a.size, 0)}\n${fmtPct(a.change)} (${period})`}
            </title>
          </path>
        ))}
      </svg>
      <ul className="pie-legend">
        {sectors.map((s) => (
          <li key={s.sector}>
            <span
              className="pie-legend-chip"
              style={{ background: changeColor(s.change_pct ?? 0, legendMax) }}
            />
            <span className="pie-legend-name">{s.sector}</span>
            <span className="pie-legend-val">
              {((s.size / total) * 100).toFixed(1)}%
            </span>
            <span className={`pie-legend-chg ${(s.change_pct ?? 0) >= 0 ? "up" : "down"}`}>
              {fmtPct(s.change_pct)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* Technical chart: Lightweight Charts (v5) wrapper + the Technical page card.
 *
 * Two exports:
 *   TechnicalChart       - the pure chart (candles, volume, overlays, indicator
 *                          panes, tooltip, legend). CompanyPage also uses this.
 *   TechnicalChartCard   - the card the Technical page embeds: owns the chart
 *                          query, the header, the sticky toolbar (ranges +
 *                          dates + basis + picker), skeleton/error states.
 *
 * Axis rule (fixes the "candles clipped / squashed" bug): ONLY the candle
 * series participates in the price scale's autoscale. Every overlay line is
 * created with `autoscaleInfoProvider: () => null`, so a 52-week pivot at
 * 8,520 or a band around a broken series can never stretch the y-axis away
 * from the visible candles. The y-domain is therefore always min(low)..max(high)
 * of the visible candles (plus the library's small padding) and refits on zoom,
 * pan, range and basis changes automatically. Nothing is clipped.
 *
 * Colour rule (green up / red down): one source of truth, the CSS variables
 * --up/--down/--flat (see theme.css + the trend-palette setting), resolved for
 * canvas at draw time. `changeColor()` derives up/down/flat from the sign of
 * close - ref where ref is chosen by the documented rule:
 *   "prev_close" (default) - close vs previous session close, matching the
 *     +/- change shown in tables and the header;
 *   "open"                 - close vs open (intrabar direction).
 * Candle body, wick and volume bar all use the same value. No other input.
 *
 * Indicators plot immediately: the picker toggles registry ids, the selection
 * drives series creation locally (no page reload), each family gets its own
 * pane, and a missing series shows its reason in the legend chip instead of
 * leaving the user with a click that does nothing.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  createChart,
  IChartApi,
  ISeriesApi,
  LineStyle,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  UTCTimestamp,
  Time,
  CandlestickData,
  LineData,
  HistogramData,
  DeepPartial,
  ChartOptions,
  MouseEventParams,
  LineSeriesOptions,
} from "lightweight-charts";
import type { ChartResponse, ChartSeries, IndicatorKey } from "../types";
import { INDICATORS, INDICATOR_COLORS, DEFAULT_SELECTION, selectedToParam } from "../indicators";
import type { IndicatorId } from "../indicators";
import { analytics, market } from "../api";
import { fmtNum, fmtPct, fmtSigned, fmtDate, fmtInt, isMissing } from "../format";
import { ErrorState } from "./ui";
import { useLiveQuotes } from "../useLiveQuotes";
import type { LiveQuote } from "../api";
import { COLOR_RULE_LABELS, COLOR_RULE_EVENT, loadColorRule, storeColorRule } from "../colorRule";
import type { ColorRule } from "../colorRule";

// Colour logic lives in ../chartColors so the colour contract is testable
// without a DOM; imported here and re-exported for the chart's importers.
import { trendPalette, changeColor, changeRef, alpha } from "../chartColors";
export { trendPalette, changeColor, changeRef, alpha };

/* -- live candle ------------------------------------------------------------ */

/** A synthetic in-session candle built from the live poller quote. */
export interface LiveCandle {
  time: string; // YYYY-MM-DD session date
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/* -- hex -> rgba ------------------------------------------------------------ */

/* -- theme tokens ------------------------------------------------------------ */

function chartTheme() {
  const cs = getComputedStyle(document.documentElement);
  const get = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback;
  const border = get("--border", "#dfe3e9");
  const borderStrong = get("--border-strong", "#c4cad3");
  return {
    text: get("--text-muted", "#5b6472"),
    grid: alpha(border, 0.1),
    crosshair: alpha(borderStrong, 0.55),
    scaleBorder: alpha(border, 0.6),
    labelBg: get("--surface-2", "#f0f2f5"),
  };
}
type ThemeColors = ReturnType<typeof chartTheme>;

function crosshairOptions(t: ThemeColors) {
  return {
    mode: 1,
    vertLines: { color: t.crosshair, style: LineStyle.Dashed, width: 1 },
    horzLines: { color: t.crosshair, style: LineStyle.Dashed, width: 1 },
    labelBackgroundColor: t.labelBg,
  };
}

function baseOptions(t: ThemeColors): DeepPartial<ChartOptions> {
  return {
    autoSize: true,
    layout: {
      background: { type: "solid", color: "transparent" },
      textColor: t.text,
      fontSize: 11,
      fontFamily: "var(--font-mono)",
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: t.grid },
      horzLines: { color: t.grid },
    },
    crosshair: crosshairOptions(t),
    rightPriceScale: {
      borderColor: t.scaleBorder,
      // The candle domain always contains every visible high/low; padding is
      // the library's default 10% margin around the autoscale range.
      scaleMargins: { top: 0.08, bottom: 0.08 },
    },
    timeScale: {
      borderColor: t.scaleBorder,
      timeVisible: false,
      secondsVisible: false,
      rightOffset: 1,
      barSpacing: 7,
      tickMarkFormatter: (time: number) =>
        new Date(time * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
    },
  } as DeepPartial<ChartOptions>;
}

/* -- payload helpers --------------------------------------------------------- */

/** Zip a payload value array with the shared time axis, skipping nulls. */
function toLineData(
  times: UTCTimestamp[],
  vals: (number | null)[],
): LineData<UTCTimestamp>[] {
  const out: LineData<UTCTimestamp>[] = [];
  for (let i = 0; i < vals.length && i < times.length; i++) {
    if (!isMissing(vals[i])) out.push({ time: times[i], value: vals[i]! });
  }
  return out;
}

/** Last non-null value of a payload series. */
function lastNonNull(vals?: (number | null)[]): number | null {
  if (!vals) return null;
  for (let i = vals.length - 1; i >= 0; i--) {
    if (!isMissing(vals[i])) return vals[i]!;
  }
  return null;
}

interface ChartData {
  series: ChartSeries;
  indicators: Partial<Record<IndicatorKey, (number | null)[]>>;
}

/** Why a requested indicator has nothing to draw (legend chip shows it). */
export type IndicatorStatus =
  | { kind: "ok" }
  | { kind: "empty"; reason: string }
  | { kind: "loading" }
  | { kind: "error"; reason: string };

/* -- the pure chart ----------------------------------------------------------- */

/** Registry-driven renderer: every series comes from `INDICATORS` + `selected`. */
export function TechnicalChart({
  data,
  selected,
  symbol,
  onToggleIndicator,
  liveCandle,
  marketClosed,
  statusByKey,
  showVolume = true,
  timeframe,
  warmUp,
}: {
  data: ChartData;
  /** Selected registry ids; defaults to the classic mix. */
  selected?: IndicatorId[];
  /** Symbol for the price-pane corner label. */
  symbol?: string;
  /** Called when a legend chip's remove (x) is clicked. */
  onToggleIndicator?: (id: IndicatorId) => void;
  /** Live in-session tick appended after the last archived bar. */
  liveCandle?: LiveCandle | null;
  /** True when the session is over: the header says so instead of LIVE. */
  marketClosed?: boolean;
  /** Backend-provided reasons for tokens that cannot render (D3). */
  statusByKey?: Record<string, string>;
  /** Show the volume pane (default true). */
  showVolume?: boolean;
  /** Timeframe info from backend (applied tf, week_start, bar_label_mode). */
  timeframe?: {
    requested: string;
    applied: string;
    auto: boolean;
    week_start: string;
    bar_label_mode: string;
    note: string;
  };
  /** Warm-up info from backend per indicator. */
  warmUp?: Record<string, { first_available: string | null; reason: string }>;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const labelRefs = useRef<(HTMLDivElement | null)[]>([]);
  const valueSpans = useRef(new Map<string, HTMLSpanElement>());
  const ohlcRef = useRef<ChartSeries | null>(null);
  const [colorRule, setColorRuleState] = useState<ColorRule>(() => loadColorRule());
  // Bumped whenever the theme (or palette) changes so memoised colours rebuild.
  const [themeTick, setThemeTick] = useState(0);
  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    row: {
      date: string;
      open: number | null;
      high: number | null;
      low: number | null;
      close: number | null;
      chg: number | null;
      chgPct: number | null;
      volume: number | null;
    } | null;
  } | null>(null);

  // Re-render with the new palette when the up/down colour rule or theme changes.
  useEffect(() => {
    const onRule = () => {
      setColorRuleState(loadColorRule());
      setThemeTick((t) => t + 1);
    };
    window.addEventListener(COLOR_RULE_EVENT, onRule);
    const obs = new MutationObserver(onRule);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "data-trend"] });
    return () => {
      window.removeEventListener(COLOR_RULE_EVENT, onRule);
      obs.disconnect();
    };
  }, []);

  // One selection drives everything: default keeps the classic mix for callers
  // that do not pass a picker state.
  const selection = useMemo(() => new Set<IndicatorId>(selected ?? DEFAULT_SELECTION), [selected]);
  const activeDefs = useMemo(
    () => INDICATORS.filter((d) => selection.has(d.key)),
    [selection],
  );
  const overlayDefs = activeDefs.filter((d) => d.pane === "overlay" || d.pane === "cloud");
  const flowDefs = activeDefs.filter((d) => d.pane === "flow");
  const trendDefs = activeDefs.filter((d) => d.pane === "trend");
  const rsiOn = selection.has("rsi_14");
  const macdOn = selection.has("macd");
  const trixOn = selection.has("trix_15");
  // Bounded 0-100 oscillators (Stochastic, StochRSI, Williams %R, Ultimate Osc,
  // and every other `osc` registry row) share one pane with 20/80 guides, per
  // family its own price scale so units never fight.
  const oscDefs = activeDefs.filter((d) => d.pane === "osc");

  const pal = useMemo(() => trendPalette(), [colorRule, themeTick]);

  // Pane layout: price, volume, then a slice per sub-pane. Expressed as
  // stretch factors; the container height grows with each active pane.
  const extraPanes =
    (trixOn ? 1 : 0) + (trendDefs.length ? 1 : 0) + (flowDefs.length ? 1 : 0) + (oscDefs.length ? 1 : 0);
  const subPanes = 1 + (rsiOn ? 1 : 0) + (macdOn ? 1 : 0);
  const chartHeight = 320 + subPanes * 100 + extraPanes * 110;

  // Legend rows: one chip per active registry entry, in picker order.
  const legendRows = activeDefs.map((def) => {
    const seriesValues = def.series.map((k) => data.indicators[k]);
    const hasAnyData = seriesValues.some((v) => (v ?? []).some((x) => !isMissing(x)));
    const keysMissing = def.series.filter((k) => !data.indicators[k]);
    // The backend keys `disabled` by token name, not payload series key.
    const backendReason =
      statusByKey?.[def.key] ?? def.series.map((k) => statusByKey?.[k]).find(Boolean);
    // Use backend warm-up reason if available (for this timeframe)
    const warmUpReason = warmUp?.[def.key]?.reason ?? warmUp?.[def.token]?.reason;
    let status: IndicatorStatus = { kind: "ok" };
    if (!hasAnyData) {
      if (backendReason) status = { kind: "error", reason: backendReason };
      else if (def.disabledByDesign) status = { kind: "error", reason: def.disabledByDesign };
      else if (def.minHistory && (data.series.dates.length < def.minHistory))
        status = { kind: "error", reason: `needs ${def.minHistory} bars, window has ${data.series.dates.length}` };
      else if (keysMissing.length)
        status = { kind: "empty", reason: "not in this response (token missing server-side)" };
      else if (warmUpReason) status = { kind: "empty", reason: warmUpReason };
      else status = { kind: "empty", reason: "no value in this window yet (warm-up)" };
    }
    return { def, latest: seriesValues.map((v) => lastNonNull(v ?? [])), status };
  });

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const t = chartTheme();
    const chart = createChart(container, baseOptions(t));
    chartRef.current = chart;
    // Dev-only handle for the parity page and manual verification.
    if (import.meta.env.DEV) {
      (window as unknown as Record<string, unknown>).__tcChart = chart;
    }

    /** Overlays must never stretch the candle axis (the clipping bug). */
    const NO_AUTOSCALE = () => null;
    const overlayLineOpts = (color: string): DeepPartial<LineSeriesOptions> => ({
      color,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      autoscaleInfoProvider: NO_AUTOSCALE,
    });

    // Pane 0: price candles (the only autoscale participant) + overlay lines.
    const candleSeries = chart.addSeries(CandlestickSeries, {}, 0);

    const overlays: { key: IndicatorKey; api: ISeriesApi<"Line"> }[] = [];
    for (const def of overlayDefs) {
      for (const key of def.series) {
        const values = data.indicators[key];
        if (!values || !values.some((v) => !isMissing(v))) continue; // draw nothing; legend explains
        overlays.push({
          key,
          api: chart.addSeries(
            LineSeries,
            overlayLineOpts(def.colors?.[key] ?? def.color),
            0,
          ),
        });
      }
    }

    // Pane 1: volume, coloured by the same rule as the candles. Optional:
    // the card's Volume checkbox hides the pane entirely when unchecked.
    let paneIndex = 1;
    const volumePane = showVolume ? chart.addPane() : null;
    if (volumePane) volumePane.setStretchFactor(1.1);
    const volumeSeries = volumePane
      ? chart.addSeries(
          HistogramSeries,
          { priceScaleId: "volume", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false },
          paneIndex,
        )
      : null;
    if (!volumePane) paneIndex = 0; // oscillator panes shift up one slot

    // RSI pane with 30/70 guides.
    let rsiSeries: ISeriesApi<"Line"> | null = null;
    if (rsiOn) {
      paneIndex += 1;
      const pane = chart.addPane();
      pane.setStretchFactor(1.4);
      rsiSeries = chart.addSeries(
        LineSeries,
        {
          color: INDICATOR_COLORS.rsi_14,
          lineWidth: 1,
          priceScaleId: "rsi",
          priceLineVisible: false,
        },
        paneIndex,
      );
      for (const level of [30, 70]) {
        rsiSeries.createPriceLine({
          price: level,
          color: t.crosshair,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: false,
          title: "",
        });
      }
    }

    // MACD pane: line + signal + sign-coloured histogram.
    let macdSeries: ISeriesApi<"Line"> | null = null;
    let macdSignalSeries: ISeriesApi<"Line"> | null = null;
    let macdHistSeries: ISeriesApi<"Histogram"> | null = null;
    if (macdOn) {
      paneIndex += 1;
      const pane = chart.addPane();
      pane.setStretchFactor(1.4);
      macdSeries = chart.addSeries(
        LineSeries,
        { color: INDICATOR_COLORS.macd, lineWidth: 1, priceScaleId: "macd", priceLineVisible: false },
        paneIndex,
      );
      macdSignalSeries = chart.addSeries(
        LineSeries,
        { color: INDICATOR_COLORS.macd_signal, lineWidth: 1, priceScaleId: "macd", priceLineVisible: false, lastValueVisible: false },
        paneIndex,
      );
      macdHistSeries = chart.addSeries(
        HistogramSeries,
        { priceScaleId: "macd", lastValueVisible: false, priceLineVisible: false },
        paneIndex,
      );
    }

    // TRIX pane.
    let trixSeries: ISeriesApi<"Line"> | null = null;
    if (trixOn) {
      paneIndex += 1;
      const pane = chart.addPane();
      pane.setStretchFactor(1.4);
      trixSeries = chart.addSeries(
        LineSeries,
        { color: INDICATOR_COLORS.trix_15, lineWidth: 1, priceScaleId: "trix", priceLineVisible: false },
        paneIndex,
      );
    }

    // Bounded-oscillator pane (0-100 family) with 20/80 guides.
    const oscSeriesMap: Record<string, ISeriesApi<"Line">> = {};
    if (oscDefs.length) {
      paneIndex += 1;
      const pane = chart.addPane();
      pane.setStretchFactor(1.4);
      let firstOscSeries: ISeriesApi<"Line"> | null = null;
      for (const def of oscDefs) {
        for (const key of def.series) {
          const values = data.indicators[key];
          if (!values || !values.some((v) => !isMissing(v))) continue;
          const s = chart.addSeries(
            LineSeries,
            {
              color: def.colors?.[key] ?? def.color,
              lineWidth: 1,
              priceScaleId: `osc-${def.key}`,
              priceLineVisible: false,
              lastValueVisible: false,
            },
            paneIndex,
          );
          oscSeriesMap[key] = s;
          firstOscSeries = firstOscSeries ?? s;
        }
      }
      for (const level of [20, 80]) {
        firstOscSeries?.createPriceLine({
          price: level,
          color: t.crosshair,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: false,
          title: "",
        });
      }
    }

    // Trend-strength pane: ADX/DMI, Aroon, Vortex and friends share one pane,
    // each family with its own price scale (percents vs ratios).
    const trendSeriesMap: Record<string, ISeriesApi<"Line">> = {};
    if (trendDefs.length) {
      paneIndex += 1;
      const pane = chart.addPane();
      pane.setStretchFactor(1.4);
      for (const def of trendDefs) {
        for (const key of def.series) {
          const values = data.indicators[key];
          if (!values || !values.some((v) => !isMissing(v))) continue;
          trendSeriesMap[key] = chart.addSeries(
            LineSeries,
            {
              color: def.colors?.[key] ?? def.color,
              lineWidth: 1,
              priceScaleId: `trend-${def.key}`,
              priceLineVisible: false,
              lastValueVisible: false,
            },
            paneIndex,
          );
        }
      }
    }

    // Volume-flow pane: one shared pane, one price scale per series so units
    // (shares, money, percent, price-range) never fight each other.
    const flowSeriesMap: Record<string, ISeriesApi<"Line">> = {};
    if (flowDefs.length) {
      paneIndex += 1;
      const pane = chart.addPane();
      pane.setStretchFactor(1.4);
      for (const def of flowDefs) {
        for (const key of def.series) {
          const values = data.indicators[key];
          if (!values || !values.some((v) => !isMissing(v))) continue;
          flowSeriesMap[key] = chart.addSeries(
            LineSeries,
            {
              color: def.colors?.[key] ?? def.color,
              lineWidth: 1,
              priceScaleId: `flow-${key}`,
              priceLineVisible: false,
              lastValueVisible: false,
            },
            paneIndex,
          );
        }
      }
    }

    // -- populate data ------------------------------------------------------
    const { series, indicators } = data;
    ohlcRef.current = series;
    const n = series.dates.length;
    const times: UTCTimestamp[] = series.dates.map(
      (d) => (Math.floor(new Date(d).getTime() / 1000) as UTCTimestamp),
    );

    const candleData: CandlestickData<UTCTimestamp>[] = [];
    const volumeData: HistogramData<UTCTimestamp>[] = [];
    let prevClose: number | null = null;
    for (let i = 0; i < n; i++) {
      const o = series.open[i];
      const h = series.high[i];
      const l = series.low[i];
      const c = series.close[i];
      const v = series.volume[i];

      if (!isMissing(o) && !isMissing(h) && !isMissing(l) && !isMissing(c)) {
        // The colour rule: one delta decides body, wick AND the volume bar.
        const ref = changeRef(colorRule, o!, prevClose);
        const col = changeColor(c! - ref, pal);
        candleData.push({
          time: times[i],
          open: o!,
          high: h!,
          low: l!,
          close: c!,
          color: col,
          borderColor: col,
          wickColor: col,
        });
        if (!isMissing(v)) {
          volumeData.push({ time: times[i], value: v!, color: alpha(col, 0.5) });
        }
        prevClose = c!;
      }
    }
    candleSeries.setData(candleData);
    volumeSeries?.setData(volumeData);

    // Live in-session candle: appended only when its session date is not
    // already archived (the nightly ingest adds the real bar; no duplicates).
    // For W/M timeframes, update the current period's bar instead of appending.
    const appliedTf = timeframe?.applied ?? "D";
    const isAggregated = appliedTf === "W" || appliedTf === "M";
    if (liveCandle && n > 0) {
      const lt = Math.floor(new Date(liveCandle.time).getTime() / 1000) as UTCTimestamp;
      const lastT = times[n - 1];
      const liveRef = changeRef(colorRule, liveCandle.open, prevClose);
      const liveCol = changeColor(liveCandle.close - liveRef, pal);
      if (lt > lastT) {
        if (!isAggregated) {
          // Daily: append new candle
          candleData.push({
            time: lt,
            open: liveCandle.open,
            high: liveCandle.high,
            low: liveCandle.low,
            close: liveCandle.close,
            color: liveCol,
            borderColor: liveCol,
            wickColor: liveCol,
          });
          candleSeries.setData(candleData);
          if (liveCandle.volume > 0) {
            volumeData.push({
              time: lt,
              value: liveCandle.volume,
              color: alpha(liveCol, 0.5),
            });
            volumeSeries?.setData(volumeData);
          }
        } else {
          // W/M: update the last (current period) bar
          const i = candleData.length - 1;
          if (i >= 0) {
            const merged = {
              ...candleData[i],
              close: liveCandle.close,
              high: Math.max(candleData[i].high, liveCandle.high),
              low: Math.min(candleData[i].low, liveCandle.low),
            };
            const mRef = changeRef(colorRule, merged.open, i > 0 ? candleData[i - 1].close : null);
            merged.color = merged.borderColor = merged.wickColor = changeColor(merged.close - mRef, pal);
            candleData[i] = merged;
            candleSeries.setData(candleData);
            if (liveCandle.volume > 0) {
              volumeData[i] = { ...volumeData[i], value: liveCandle.volume, color: alpha(merged.color, 0.5) };
              volumeSeries?.setData(volumeData);
            }
          }
        }
      } else if (lt === lastT) {
        // Same session already archived: overlay the live close onto that bar.
        const i = candleData.findIndex((c) => c.time === lt);
        if (i >= 0) {
          const merged = {
            ...candleData[i],
            close: liveCandle.close,
            high: Math.max(candleData[i].high, liveCandle.high),
            low: Math.min(candleData[i].low, liveCandle.low),
          };
          const mRef = changeRef(colorRule, merged.open, i > 0 ? candleData[i - 1].close : null);
          merged.color = merged.borderColor = merged.wickColor = changeColor(merged.close - mRef, pal);
          candleData[i] = merged;
          candleSeries.setData(candleData);
        }
      }
    }

    for (const { key, api } of overlays) {
      api.setData(toLineData(times, indicators[key] ?? []));
    }
    if (rsiSeries) rsiSeries.setData(toLineData(times, indicators.rsi_14 ?? []));
    if (macdSeries && macdSignalSeries && macdHistSeries) {
      macdSeries.setData(toLineData(times, indicators.macd ?? []));
      macdSignalSeries.setData(toLineData(times, indicators.macd_signal ?? []));
      const macdHistData: HistogramData<UTCTimestamp>[] = [];
      const macdHistVals = indicators.macd_histogram ?? [];
      for (let i = 0; i < macdHistVals.length && i < n; i++) {
        if (!isMissing(macdHistVals[i])) {
          macdHistData.push({
            time: times[i],
            value: macdHistVals[i]!,
            // Histogram sign colour: positive bars up, negative bars down.
            color: alpha(changeColor(macdHistVals[i]!, pal), 0.8),
          });
        }
      }
      macdHistSeries.setData(macdHistData);
    }
    if (trixSeries) trixSeries.setData(toLineData(times, indicators.trix_15 ?? []));
    for (const def of oscDefs) {
      for (const key of def.series) {
        oscSeriesMap[key]?.setData(toLineData(times, indicators[key] ?? []));
      }
    }
    for (const def of trendDefs) {
      for (const key of def.series) {
        trendSeriesMap[key]?.setData(toLineData(times, indicators[key] ?? []));
      }
    }
    for (const def of flowDefs) {
      for (const key of def.series) {
        flowSeriesMap[key]?.setData(toLineData(times, indicators[key] ?? []));
      }
    }

    // Default view: the whole window visible, nothing clipped. The library
    // refits the (candle-only) autoscale domain to the visible bars on zoom,
    // pan and range changes, so this is the only explicit fit needed.
    chart.timeScale().fitContent();

    // -- corner labels: price and volume values follow the crosshair --------

    const cornerItems: {
      pi: number;
      ii: number;
      api: ISeriesApi<"Line"> | ISeriesApi<"Histogram"> | ISeriesApi<"Candlestick">;
      fmt: (v: number) => string;
      latest: number | null;
    }[] = [
      {
        pi: 0,
        ii: 0,
        api: candleSeries,
        fmt: (v) => fmtNum(v, 2),
        latest: liveCandle ? liveCandle.close : lastNonNull(series.close),
      },
      ...(volumeSeries
        ? [
            {
              pi: 1,
              ii: 0,
              api: volumeSeries,
              fmt: (v: number) => fmtInt(v),
              latest: liveCandle && liveCandle.volume > 0 ? liveCandle.volume : lastNonNull(series.volume),
            },
          ]
        : []),
    ];
    const showLatest = () => {
      for (const it of cornerItems) {
        const el = valueSpans.current.get(`${it.pi}:${it.ii}`);
        if (el && it.latest != null) el.textContent = it.fmt(it.latest);
      }
    };
    showLatest();

    chart.subscribeCrosshairMove((param: MouseEventParams<Time>) => {
      // Corner values.
      for (const it of cornerItems) {
        const el = valueSpans.current.get(`${it.pi}:${it.ii}`);
        if (!el) continue;
        if (!param.time) {
          if (it.latest != null) el.textContent = it.fmt(it.latest);
          continue;
        }
        const d = param.seriesData.get(it.api) as { value?: number; close?: number } | undefined;
        const v = d ? (d.close ?? d.value ?? null) : null;
        el.textContent = v == null ? (it.latest != null ? it.fmt(it.latest) : "–") : it.fmt(v);
      }
      // Tooltip row for the hovered session.
      if (!param.time || !param.point || !ohlcRef.current) {
        setTooltip(null);
        return;
      }
      const s = ohlcRef.current;
      const t0 = param.time as number;
      let idx = -1;
      for (let i = 0; i < s.dates.length; i++) {
        if (times[i] === t0) {
          idx = i;
          break;
        }
      }
      if (idx < 0) {
        setTooltip(null);
        return;
      }
      const o = s.open[idx];
      const h = s.high[idx];
      const l = s.low[idx];
      const c = s.close[idx];
      // Change vs the previous session with a close (matches the header rule).
      let p = idx - 1;
      while (p >= 0 && isMissing(s.close[p])) p--;
      const prevC = p >= 0 ? s.close[p] : null;
      const chg = c != null && prevC != null ? c - prevC : null;
      const chgPct = chg != null && prevC ? (chg / prevC) * 100 : null;
      const row = {
        date: s.dates[idx],
        open: o,
        high: h,
        low: l,
        close: c,
        chg,
        chgPct,
        volume: s.volume[idx],
      };
      const wrap = container.getBoundingClientRect();
      const x = Math.min(Math.max(param.point.x + 14, 8), Math.max(wrap.width - 190, 8));
      const y = Math.min(Math.max(param.point.y + 12, 8), Math.max(wrap.height - 120, 8));
      setTooltip({ x, y, row });
    });

    // Pane label tops follow the real pane geometry (stretch factors), so
    // recompute on every container resize.
    const paneApis = chart.panes().slice(1);
    const layoutLabels = () => {
      const total = container.clientHeight;
      const others = paneApis.reduce((s, p) => s + p.getHeight(), 0);
      const priceH = Math.max(total - others - paneApis.length, 0);
      const heights = [priceH, ...paneApis.map((p) => p.getHeight())];
      let acc = 0;
      for (let i = 0; i < heights.length; i++) {
        const el = labelRefs.current[i];
        if (el) el.style.top = `${acc + 6}px`;
        acc += heights[i] + 1;
      }
    };
    layoutLabels();
    const ro = new ResizeObserver(() => layoutLabels());
    ro.observe(container);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      if (import.meta.env.DEV) delete (window as unknown as Record<string, unknown>).__tcChart;
    };
    // `selected` drives every def list above; `data`, the live tick, the
    // colour rule and the palette rebuild the chart.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, selection, liveCandle, colorRule, pal]);

  // Re-apply theme-dependent colours when the app switches light/dark/system:
  // the document attribute is the single source of truth (see theme.ts).
  useEffect(() => {
    const apply = () => {
      const chart = chartRef.current;
      if (!chart) return;
      const t = chartTheme();
      chart.applyOptions({
        layout: { textColor: t.text },
        grid: { vertLines: { color: t.grid }, horzLines: { color: t.grid } },
        crosshair: crosshairOptions(t),
        rightPriceScale: { borderColor: t.scaleBorder },
        timeScale: { borderColor: t.scaleBorder },
      });
    };
    apply();
    const obs = new MutationObserver(apply);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);

  return (
    <div className="tc-chart-wrap">
      <div ref={containerRef} className="tc-chart" style={{ height: chartHeight }} />

      {/* Corner labels: price and volume values follow the crosshair. */}
      <div
        className="tc-pane-label"
        ref={(el) => {
          labelRefs.current[0] = el;
        }}
      >
        <span className="tc-pl-item">
          <span className="tc-pl-name">{symbol || "Price"}</span>
          <span
            ref={(el) => {
              const k = "0:0";
              if (el) valueSpans.current.set(k, el);
              else valueSpans.current.delete(k);
            }}
          >
            –
          </span>
        </span>
      </div>
      <div
        className="tc-pane-label"
        ref={(el) => {
          labelRefs.current[1] = el;
        }}
      >
        <span className="tc-pl-item">
          <span className="tc-pl-name">VOL</span>
          <span
            ref={(el) => {
              const k = "1:0";
              if (el) valueSpans.current.set(k, el);
              else valueSpans.current.delete(k);
            }}
          >
            –
          </span>
        </span>
      </div>

      {/* Active-indicator legend: dot, label, latest value(s), status, x. */}
      {legendRows.length > 0 && (
        <div className="tc-legend">
          {legendRows.map(({ def, latest, status }) => (
            <span
              key={def.key}
              className={`tc-legend-chip${status.kind !== "ok" ? " warn" : ""}`}
              style={{ borderColor: def.color }}
              title={def.desc}
            >
              {def.series.map((k) => (
                <span key={k} className="dot" style={{ background: def.colors?.[k] ?? def.color }} />
              ))}
              <span className="tc-legend-name">{def.label}</span>
              {latest.map((v, i) => (
                <span key={i}>{v == null ? "–" : fmtNum(v, 2)}</span>
              ))}
              {status.kind !== "ok" && (
                <span className="tc-legend-status" title={status.reason}>
                  ⚠ {status.reason}
                </span>
              )}
              {onToggleIndicator && (
                <button
                  type="button"
                  className="tc-legend-x"
                  aria-label={`Remove ${def.label}`}
                  onClick={() => onToggleIndicator(def.key)}
                >
                  ×
                </button>
              )}
            </span>
          ))}
          {liveCandle ? (
            <span className="tc-live-note">last point provisional (live session)</span>
          ) : (
            marketClosed && <span className="tc-live-note">market closed - final session values</span>
          )}
        </div>
      )}

      {/* OHLCV tooltip; rendered by the crosshair handler. */}
      {tooltip?.row && (
        <div className="tc-tooltip" style={{ left: tooltip.x, top: tooltip.y }}>
          <div className="tc-tooltip-date">{tooltip.row.date}</div>
          <div className="tc-tooltip-grid">
            <span>O</span>
            <span>{fmtNum(tooltip.row.open)}</span>
            <span>H</span>
            <span>{fmtNum(tooltip.row.high)}</span>
            <span>L</span>
            <span>{fmtNum(tooltip.row.low)}</span>
            <span>C</span>
            <span className={tooltip.row.chg == null ? "" : tooltip.row.chg > 0 ? "up" : tooltip.row.chg < 0 ? "down" : "flat"}>
              {fmtNum(tooltip.row.close)}
            </span>
            <span>Chg</span>
            <span className={tooltip.row.chg == null ? "" : tooltip.row.chg > 0 ? "up" : tooltip.row.chg < 0 ? "down" : "flat"}>
              {fmtSigned(tooltip.row.chg)} ({fmtPct(tooltip.row.chgPct)})
            </span>
            <span>Vol</span>
            <span>{tooltip.row.volume == null ? "–" : fmtInt(tooltip.row.volume)}</span>
          </div>
        </div>
      )}
    </div>
  );
}

/* -- the Technical page card ------------------------------------------------ */

function loadSelected(symbol: string): IndicatorId[] {
  const keys = [`chart-indicators:${symbol}`, "chart-indicators"];
  for (const key of keys) {
    try {
      const raw = window.localStorage.getItem(key);
      const parsed: unknown = raw ? JSON.parse(raw) : null;
      if (Array.isArray(parsed)) {
        const valid = parsed.filter(
          (k): k is IndicatorId => typeof k === "string" && INDICATORS.some((d) => d.key === k),
        );
        if (valid.length) return valid;
      }
    } catch {
      /* fall through */
    }
  }
  return DEFAULT_SELECTION;
}

const MAX_ACTIVE = 12;

const RANGES = ["1W", "1M", "3M", "6M", "YTD", "1Y", "ALL"] as const;
const DEFAULT_RANGE = "3M";

/** Chart header: symbol, name, last close, change and %, as-of date.
 * When a fresh live quote exists, LTP/change come from it and the header says
 * LIVE; otherwise the last archived close is shown with a "market closed" tag.
 * Never presents a stale quote as live. Colours come from the up/down CSS
 * variables (green up / red down, or the user's chosen alternative). */
function ChartHeader({
  data,
  live,
}: {
  data: ChartResponse;
  live?: LiveQuote | null;
}) {
  const closes = data.series.close;
  let li = closes.length - 1;
  while (li >= 0 && isMissing(closes[li])) li--;
  let pi = li - 1;
  while (pi >= 0 && isMissing(closes[pi])) pi--;
  const last = li >= 0 ? closes[li]! : null;
  const prev = pi >= 0 ? closes[pi]! : null;

  // Live quote wins when fresh; archived close is the fallback.
  const LIVE_TTL_MS = 90_000;
  const liveFresh =
    !!live && Date.now() - new Date(live.timestamp + "Z").getTime() <= LIVE_TTL_MS;
  const price = liveFresh ? live!.ltp : last;
  const ref =
    liveFresh && (live!.change !== 0 || live!.change_pct !== 0)
      ? live!.ltp - live!.change
      : prev;
  const chg = price != null && ref != null ? price - ref : null;
  const pct = chg != null && ref ? (chg / ref) * 100 : null;
  // Class-based tone so the app-wide --up/--down variables decide the colour.
  const cls = chg == null || chg === 0 ? "flat" : chg > 0 ? "up" : "down";

  return (
    <div className="tc-header">
      <span className="tc-symbol">{data.symbol}</span>
      {data.name && <span className="tc-name">{data.name}</span>}
      <span className={`tc-price ${cls}`}>
        {fmtNum(price)}
      </span>
      <span className={`tc-chg ${cls}`}>
        {fmtSigned(chg)} ({fmtPct(pct)})
      </span>
      {liveFresh && <span className="tc-live-badge">LIVE</span>}
      {!liveFresh && (
        <span className="tc-closed-badge">market closed</span>
      )}
      <span className="tc-asof">
        {liveFresh
          ? `live at ${new Date(live!.timestamp + "Z").toLocaleTimeString()}`
          : `as of ${fmtDate(data.as_of)}`}
      </span>
    </div>
  );
}

/** Phase 5/6: the card embedded at the top of the Technical page. */
export function TechnicalChartCard({ symbol }: { symbol: string }) {
  const [colorRule, setColorRuleState] = useState<ColorRule>(loadColorRule());
  const [selected, setSelected] = useState<IndicatorId[]>(() => loadSelected(symbol));
  const [range, setRange] = useState<string>(() => {
    try {
      return window.localStorage.getItem("chart-range") ?? DEFAULT_RANGE;
    } catch {
      return DEFAULT_RANGE;
    }
  });
  const [fromDate, setFromDate] = useState<string>("");
  const [toDate, setToDate] = useState<string>("");
  const [basis, setBasis] = useState<"as_traded" | "adjusted">("as_traded");
  const [tf, setTf] = useState<"auto" | "D" | "W" | "M">(() => {
    try {
      return (window.localStorage.getItem(`chart-tf:${symbol}`) as "auto" | "D" | "W" | "M") ?? "auto";
    } catch {
      return "auto";
    }
  });
  const [weekStart, setWeekStart] = useState<"sunday" | "monday">(() => {
    try {
      return (window.localStorage.getItem(`chart-week-start:${symbol}`) as "sunday" | "monday") ?? "monday";
    } catch {
      return "monday";
    }
  });
  const [barLabelMode, setBarLabelMode] = useState<"last_session" | "period_start">(() => {
    try {
      return (window.localStorage.getItem(`chart-bar-label:${symbol}`) as "last_session" | "period_start") ?? "period_start";
    } catch {
      return "period_start";
    }
  });
  const [showVolume, setShowVolume] = useState(true);
  // Re-read when another surface (topbar, another chart) changes the rule.
  useEffect(() => {
    const onRule = () => setColorRuleState(loadColorRule());
    window.addEventListener(COLOR_RULE_EVENT, onRule);
    return () => window.removeEventListener(COLOR_RULE_EVENT, onRule);
  }, []);
  const [chipHidden, setChipHidden] = useState(false);
  const [capNotice, setCapNotice] = useState<string | null>(null);

  // Selection is per symbol (D2): each ticker remembers its own mix.
  useEffect(() => {
    try {
      window.localStorage.setItem(`chart-indicators:${symbol}`, JSON.stringify(selected));
    } catch {
      /* non-fatal */
    }
  }, [selected, symbol]);
  useEffect(() => {
    try {
      window.localStorage.setItem("chart-range", range);
    } catch {
      /* non-fatal */
    }
  }, [range]);
  // Persist timeframe per symbol
  useEffect(() => {
    try {
      window.localStorage.setItem(`chart-tf:${symbol}`, tf);
    } catch {
      /* non-fatal */
    }
  }, [tf, symbol]);
  useEffect(() => {
    try {
      window.localStorage.setItem(`chart-week-start:${symbol}`, weekStart);
    } catch {
      /* non-fatal */
    }
  }, [weekStart, symbol]);
  useEffect(() => {
    try {
      window.localStorage.setItem(`chart-bar-label:${symbol}`, barLabelMode);
    } catch {
      /* non-fatal */
    }
  }, [barLabelMode, symbol]);
  useEffect(() => setChipHidden(false), [symbol, range]);

  const toggle = (id: IndicatorId) => {
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((k) => k !== id);
      if (prev.length >= MAX_ACTIVE) {
        setCapNotice(`At most ${MAX_ACTIVE} indicators at once - remove one first.`);
        return prev;
      }
      setCapNotice(null);
      return [...prev, id];
    });
  };

  const customDates = !!(fromDate || toDate);
  const effRange = customDates ? "ALL" : range;

  const query = useQuery({
    queryKey: ["chart", symbol, effRange, fromDate, toDate, basis, tf, weekStart, barLabelMode, selected],
    queryFn: ({ signal }) =>
      analytics.chart(
        symbol,
        {
          range: effRange,
          mode: "UNADJUSTED",
          basis,
          indicators: selectedToParam(selected),
          start: fromDate || undefined,
          end: toDate || undefined,
          tf,
          week_start: weekStart,
          bar_label_mode: barLabelMode,
        },
        signal,
      ),
    enabled: !!symbol,
    staleTime: 60_000,
  });
  const data = query.data;

  // Live tick for this symbol from the backend's shared poller (30s refresh;
  // one NEPSE call per interval server-side no matter how many tabs poll).
  const { quotes } = useLiveQuotes(symbol ? [symbol] : []);
  // Market-hours gate: the poller keeps serving its cached quote after hours,
  // so the header would claim LIVE at 10pm. The app's market overview (same
  // query key as the topbar's, so one fetch serves both) decides.
  const { data: marketStatus } = useQuery({
    queryKey: ["market-status"],
    queryFn: ({ signal }) => market.overview(signal),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
  const marketOpen = marketStatus?.status.is_open;
  const live = marketOpen === false ? null : (quotes.get(symbol) ?? null);

  // Synthetic in-session candle from the live quote, anchored on the previous
  // close so open/high/low are honest within what we know. Only shown when
  // its session (today) is NOT already archived.
  let liveCandle: LiveCandle | null = null;
  if (data && live) {
    const today = new Date().toISOString().slice(0, 10);
    const dates = data.series.dates;
    const lastDate = dates[dates.length - 1];
    if (today > lastDate) {
      const closes = data.series.close;
      let li = closes.length - 1;
      while (li >= 0 && isMissing(closes[li])) li--;
      const prevClose = li >= 0 ? closes[li]! : live.ltp;
      const refClose =
        live.change !== 0 || live.change_pct !== 0 ? live.ltp - live.change : prevClose;
      liveCandle = {
        time: today,
        open: refClose,
        high: Math.max(live.high, live.ltp, refClose),
        low: Math.min(live.low > 0 ? live.low : live.ltp, live.ltp, refClose),
        close: live.ltp,
        volume: live.volume ?? 0,
      };
    }
  }

  return (
    <section className="chart-card">
      {data && <ChartHeader data={data} live={live} />}

      <div className="tc-toolbar">
        <div className="tc-ranges" role="group" aria-label="Chart range">
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              className={`tc-range-btn${!customDates && range === r ? " on" : ""}`}
              onClick={() => {
                setRange(r);
                setFromDate("");
                setToDate("");
              }}
            >
              {r}
            </button>
          ))}
        </div>
        <div className="tc-dates" role="group" aria-label="Custom date range">
          <input
            type="date"
            className="input tc-date-input"
            aria-label="From date"
            value={fromDate}
            max={toDate || undefined}
            onChange={(e) => setFromDate(e.target.value)}
          />
          <span className="tc-date-dash">–</span>
          <input
            type="date"
            className="input tc-date-input"
            aria-label="To date"
            value={toDate}
            min={fromDate || undefined}
            onChange={(e) => setToDate(e.target.value)}
          />
          {customDates && (
            <button
              type="button"
              className="tc-range-btn"
              aria-label="Clear custom dates"
              onClick={() => {
                setFromDate("");
                setToDate("");
              }}
            >
              ×
            </button>
          )}
        </div>
        <label className="tc-ctl">
          <span>Timeframe</span>
          <select
            className="input"
            value={tf}
            onChange={(e) => setTf(e.target.value as "auto" | "D" | "W" | "M")}
            aria-label="Bar timeframe"
          >
            <option value="auto">Auto</option>
            <option value="D">Daily</option>
            <option value="W">Weekly</option>
            <option value="M">Monthly</option>
          </select>
        </label>
        {tf === "W" && (
          <label className="tc-ctl">
            <span>Week start</span>
            <select
              className="input"
              value={weekStart}
              onChange={(e) => setWeekStart(e.target.value as "sunday" | "monday")}
              aria-label="Week start day"
            >
              <option value="sunday">Sunday</option>
              <option value="monday">Monday</option>
            </select>
          </label>
        )}
        <label className="tc-ctl">
          <span>Bar label</span>
          <select
            className="input"
            value={barLabelMode}
            onChange={(e) => setBarLabelMode(e.target.value as "last_session" | "period_start")}
            aria-label="Bar date label mode"
          >
            <option value="last_session">Last session</option>
            <option value="period_start">Period start</option>
          </select>
        </label>
        <label className="tc-ctl">
          <span>Prices</span>
          <select
            className="input"
            value={basis}
            onChange={(e) => setBasis(e.target.value === "adjusted" ? "adjusted" : "as_traded")}
            aria-label="Price basis"
          >
            <option value="as_traded">As traded</option>
            <option value="adjusted">Adjusted</option>
          </select>
        </label>
        <label className="tc-ctl" title={COLOR_RULE_LABELS[colorRule]}>
          <span>Colours</span>
          <select
            className="input"
            value={colorRule}
            onChange={(e) => {
              const next = e.target.value === "open" ? "open" : "prev_close";
              setColorRuleState(next);
              storeColorRule(next);
            }}
            aria-label="Candle colour rule"
          >
            <option value="prev_close">vs prev close</option>
            <option value="open">close vs open</option>
          </select>
        </label>
        <label className="tc-ctl">
          <span>Volume</span>
          <input
            type="checkbox"
            checked={showVolume}
            onChange={(e) => setShowVolume(e.target.checked)}
          />
        </label>
        <div className="picker tc-picker" role="group" aria-label="Chart indicators">
          {INDICATORS.map((def) => {
            const on = selected.includes(def.key);
            return (
              <label
                key={def.key}
                className={`picker-chip${on ? " on" : ""}`}
                style={on ? { borderColor: def.color, color: def.color } : undefined}
                title={def.desc}
              >
                <input type="checkbox" checked={on} onChange={() => toggle(def.key)} />
                {def.label}
              </label>
            );
          })}
        </div>
      </div>

      {capNotice && (
        <div className="tc-cap-notice" role="status">
          {capNotice}
          <button type="button" aria-label="Dismiss" onClick={() => setCapNotice(null)}>
            ×
          </button>
        </div>
      )}

      {query.isLoading && <div className="tc-skeleton" aria-hidden="true" />}
      {query.error && (
        <div className="tc-error">
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        </div>
      )}

      {data && (
        <>
          {data.range && !data.range.complete && !chipHidden && (
            <div className="tc-range-chip">
              <span>
                Archive for {effRange} starts {fmtDate(data.range.first_shown)}.
              </span>
              <button type="button" aria-label="Dismiss" onClick={() => setChipHidden(true)}>
                ×
              </button>
            </div>
          )}
          {basis === "adjusted" && data.price_mode?.differs_from_requested && (
            <div className="tc-range-chip">
              <span>{data.price_mode.reason}</span>
            </div>
          )}
          <TechnicalChart
            data={{ series: data.series, indicators: data.indicators }}
            selected={selected}
            symbol={symbol}
            onToggleIndicator={toggle}
            liveCandle={liveCandle}
            statusByKey={data.disabled}
            showVolume={showVolume}
            marketClosed={live ? false : marketOpen === false}
            timeframe={data.timeframe}
            warmUp={data.warm_up}
          />
        </>
      )}
    </section>
  );
}

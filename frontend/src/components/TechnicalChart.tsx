/* Technical chart: Lightweight Charts wrapper + the Technical page chart card.
 *
 * Two exports:
 *   TechnicalChart       - the pure chart (candles, overlays, indicator panes,
 *                          corner labels, overlay legend). CompanyPage also
 *                          uses this directly.
 *   TechnicalChartCard   - the Phase 5/6 card the Technical page embeds: owns
 *                          the chart query, the header, the sticky toolbar
 *                          (range + picker), the range chip and the
 *                          skeleton/error states.
 *
 * Canvas colours: the chart paints onto <canvas>, which cannot resolve CSS
 * variables - the old build passed `var(--up)` straight to the library, every
 * fill silently failed, and all candles rendered black. Theme-dependent
 * colours are therefore resolved with getComputedStyle at draw time and
 * re-applied whenever the document's `data-theme` attribute changes.
 * Candle/indicator colours are literals from the registry palette family.
 *
 * Candle convention (Phase 6a): up = green, down = red. Note the app's ticker
 * elsewhere uses the NEPSE convention (up = red); flip CHART_UP/CHART_DOWN if
 * the app-wide convention should win here too.
 */

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  createChart,
  IChartApi,
  ISeriesApi,
  IPaneApi,
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
} from "lightweight-charts";
import type { ChartResponse, ChartSeries, IndicatorKey } from "../types";
import { INDICATORS, INDICATOR_COLORS, DEFAULT_SELECTION, selectedToParam } from "../indicators";
import type { IndicatorId } from "../indicators";
import { analytics } from "../api";
import { fmtNum, fmtPct, fmtSigned, fmtDate, isMissing } from "../format";
import { ErrorState } from "./ui";
import { useLiveQuotes } from "../useLiveQuotes";
import type { LiveQuote } from "../api";

/** Explicit Phase 6a convention: up = green, down = red. */
const CHART_UP = "#26a69a";
const CHART_DOWN = "#ef5350";

const RANGES = ["1M", "3M", "6M", "1Y", "ALL"] as const;
const CHART_RANGE_KEY = "chart-range";
const CHART_INDICATORS_KEY = "chart-indicators";

const compactFmt = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
});

/** Hex (#rgb/#rrggbb) -> rgba with the given alpha; other formats pass through. */
function alpha(color: string, a: number): string {
  const c = color.trim();
  if (c.startsWith("#")) {
    if (c.length === 4) {
      return `rgba(${parseInt(c[1] + c[1], 16)},${parseInt(c[2] + c[2], 16)},${parseInt(c[3] + c[3], 16)},${a})`;
    }
    if (c.length === 7) {
      return `rgba(${parseInt(c.slice(1, 3), 16)},${parseInt(c.slice(3, 5), 16)},${parseInt(c.slice(5, 7), 16)},${a})`;
    }
  }
  return c;
}

/** Theme tokens resolved for the canvas (they cannot stay as CSS vars). */
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
    rightPriceScale: { borderColor: t.scaleBorder },
    timeScale: {
      borderColor: t.scaleBorder,
      timeVisible: false,
      secondsVisible: false,
      tickMarkFormatter: (time: number) =>
        new Date(time * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
    },
  } as DeepPartial<ChartOptions>;
}

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

/** A synthetic in-session candle built from the live poller quote. */
export interface LiveCandle {
  time: string; // YYYY-MM-DD session date
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/* -- the pure chart -------------------------------------------------------- */

/** Registry-driven renderer: every series comes from `INDICATORS` + `selected`. */
export function TechnicalChart({
  data,
  selected,
  symbol,
  onToggleOverlay,
  liveCandle,
}: {
  data: ChartData;
  /** Selected registry ids; defaults to the classic mix. */
  selected?: IndicatorId[];
  /** Symbol for the price-pane corner label. */
  symbol?: string;
  /** Called when a legend chip's remove (x) is clicked. */
  onToggleOverlay?: (id: IndicatorId) => void;
  /** Live in-session tick appended after the last archived bar. */
  liveCandle?: LiveCandle | null;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const labelRefs = useRef<(HTMLDivElement | null)[]>([]);
  const valueSpans = useRef(new Map<string, HTMLSpanElement>());

  // One selection drives everything: default keeps the classic mix for callers
  // that do not pass a picker state.
  const selection = new Set<IndicatorId>(selected ?? DEFAULT_SELECTION);
  const overlayDefs = INDICATORS.filter(
    (d) => (d.pane === "overlay" || d.pane === "cloud") && selection.has(d.key),
  );
  const flowDefs = INDICATORS.filter((d) => d.pane === "flow" && selection.has(d.key));
  const trendDefs = INDICATORS.filter((d) => d.pane === "trend" && selection.has(d.key));
  const rsiOn = selection.has("rsi_14");
  const macdOn = selection.has("macd");
  const trixOn = selection.has("trix_15");
  // Bounded 0-100 oscillators (Stochastic, StochRSI, Williams %R, Ultimate
  // Osc) share one pane with RSI-style 20/80 guides, per family its own
  // price scale so units never fight.
  const oscDefs = INDICATORS.filter((d) => d.pane === "osc" && selection.has(d.key));

  // Pane layout: price ~60%, volume ~10%, RSI/MACD ~15% each (Phase 6f);
  // optional TRIX/trend/flow panes get a smaller slice each. Expressed as a
  // fixed pixel height for the container plus relative stretch factors.
  const extraPanes =
    (trixOn ? 1 : 0) + (trendDefs.length ? 1 : 0) + (flowDefs.length ? 1 : 0) + (oscDefs.length ? 1 : 0);
  const subPanes = 1 + (rsiOn ? 1 : 0) + (macdOn ? 1 : 0);
  const chartHeight = 320 + subPanes * 100 + extraPanes * 110;

  // Corner-label rows, one per pane, in the exact order the effect creates
  // panes; values are filled in by the crosshair handler.
  const paneLabels: { id: string; items: { key: string; name: string; color?: string }[] }[] = [
    { id: "price", items: [{ key: "close", name: symbol || "Price" }] },
    { id: "volume", items: [{ key: "vol", name: "VOL" }] },
  ];
  if (rsiOn) {
    paneLabels.push({ id: "rsi", items: [{ key: "rsi_14", name: "RSI 14", color: INDICATOR_COLORS.rsi_14 }] });
  }
  if (macdOn) {
    paneLabels.push({
      id: "macd",
      items: [
        { key: "macd", name: "MACD", color: INDICATOR_COLORS.macd },
        { key: "macd_signal", name: "SIG", color: INDICATOR_COLORS.macd_signal },
        { key: "macd_histogram", name: "HIST", color: INDICATOR_COLORS.macd_histogram },
      ],
    });
  }
  if (trixOn) {
    paneLabels.push({ id: "trix", items: [{ key: "trix_15", name: "TRIX 15", color: INDICATOR_COLORS.trix_15 }] });
  }
  if (oscDefs.length) {
    paneLabels.push({
      id: "osc",
      items: oscDefs.map((d) => ({
        key: d.series[0],
        name: d.series.length > 1 ? `${d.label} K` : d.label,
        color: d.color,
      })),
    });
  }
  if (trendDefs.length) {
    paneLabels.push({
      id: "trend",
      items: trendDefs.map((d) => ({ key: d.series[0], name: d.label, color: d.color })),
    });
  }
  if (flowDefs.length) {
    paneLabels.push({
      id: "flow",
      items: flowDefs.map((d) => ({ key: d.series[0], name: d.label, color: d.color })),
    });
  }

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const t = chartTheme();
    const chart = createChart(container, baseOptions(t));
    chartRef.current = chart;

    const paneApis: IPaneApi<Time>[] = [];
    let paneIndex = 0;

    // Pane 0: price candles + overlay lines (price ~60% via default stretch 1).
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: CHART_UP,
      downColor: CHART_DOWN,
      borderUpColor: CHART_UP,
      borderDownColor: CHART_DOWN,
      wickUpColor: CHART_UP,
      wickDownColor: CHART_DOWN,
    });

    const overlays: { key: IndicatorKey; api: ISeriesApi<"Line"> }[] = [];
    for (const def of overlayDefs) {
      for (const key of def.series) {
        overlays.push({
          key,
          api: chart.addSeries(
            LineSeries,
            {
              color: def.colors?.[key] ?? def.color,
              lineWidth: 1,
              priceScaleId: "right",
              priceLineVisible: false,
            },
            0,
          ),
        });
      }
    }

    // Pane 1: volume (~10%), semi-transparent up/down coloured bars.
    paneIndex += 1;
    const volumePane = chart.addPane();
    paneApis.push(volumePane);
    volumePane.setStretchFactor(0.3125);
    const volumeSeries = chart.addSeries(
      HistogramSeries,
      { priceScaleId: "volume", priceFormat: { type: "volume" } },
      paneIndex,
    );

    // RSI pane (~15%) with 30/70 guide lines.
    let rsiSeries: ISeriesApi<"Line"> | null = null;
    if (rsiOn) {
      paneIndex += 1;
      const pane = chart.addPane();
      paneApis.push(pane);
      pane.setStretchFactor(0.3125);
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

    // MACD pane (~15%): line + signal + sign-coloured histogram.
    let macdSeries: ISeriesApi<"Line"> | null = null;
    let macdSignalSeries: ISeriesApi<"Line"> | null = null;
    let macdHistSeries: ISeriesApi<"Histogram"> | null = null;
    if (macdOn) {
      paneIndex += 1;
      const pane = chart.addPane();
      paneApis.push(pane);
      pane.setStretchFactor(0.3125);
      macdSeries = chart.addSeries(
        LineSeries,
        { color: INDICATOR_COLORS.macd, lineWidth: 1, priceScaleId: "macd" },
        paneIndex,
      );
      macdSignalSeries = chart.addSeries(
        LineSeries,
        { color: INDICATOR_COLORS.macd_signal, lineWidth: 1, priceScaleId: "macd" },
        paneIndex,
      );
      macdHistSeries = chart.addSeries(
        HistogramSeries,
        { priceScaleId: "macd" },
        paneIndex,
      );
    }

    // TRIX pane.
    let trixSeries: ISeriesApi<"Line"> | null = null;
    if (trixOn) {
      paneIndex += 1;
      const pane = chart.addPane();
      paneApis.push(pane);
      pane.setStretchFactor(0.34);
      trixSeries = chart.addSeries(
        LineSeries,
        { color: INDICATOR_COLORS.trix_15, lineWidth: 1, priceScaleId: "trix" },
        paneIndex,
      );
    }

    // Bounded-oscillator pane (0-100 family) with 20/80 guides: every family
    // gets its own price scale, like the trend pane.
    const oscSeriesMap: Record<string, ISeriesApi<"Line">> = {};
    if (oscDefs.length) {
      paneIndex += 1;
      const pane = chart.addPane();
      paneApis.push(pane);
      pane.setStretchFactor(0.34);
      let firstOscSeries: ISeriesApi<"Line"> | null = null;
      for (const def of oscDefs) {
        for (const key of def.series) {
          const s = chart.addSeries(
            LineSeries,
            {
              color: def.colors?.[key] ?? def.color,
              lineWidth: 1,
              priceScaleId: `osc-${def.key}`,
              priceLineVisible: false,
            },
            paneIndex,
          );
          oscSeriesMap[key] = s;
          firstOscSeries = firstOscSeries ?? s;
        }
      }
      for (const level of [20, 80]) {
        firstOscSeries!.createPriceLine({
          price: level,
          color: t.crosshair,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: false,
          title: "",
        });
      }
    }

    // Trend-strength pane: ADX/DMI, Aroon and Vortex share one pane, each
    // family with its own price scale (percent 0-100 vs ratios around 1.0).
    const trendSeriesMap: Record<string, ISeriesApi<"Line">> = {};
    if (trendDefs.length) {
      paneIndex += 1;
      const pane = chart.addPane();
      paneApis.push(pane);
      pane.setStretchFactor(0.34);
      for (const def of trendDefs) {
        for (const key of def.series) {
          trendSeriesMap[key] = chart.addSeries(
            LineSeries,
            {
              color: def.colors?.[key] ?? def.color,
              lineWidth: 1,
              priceScaleId: `trend-${def.key}`,
              priceLineVisible: false,
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
      paneApis.push(pane);
      pane.setStretchFactor(0.34);
      for (const def of flowDefs) {
        for (const key of def.series) {
          flowSeriesMap[key] = chart.addSeries(
            LineSeries,
            {
              color: def.colors?.[key] ?? def.color,
              lineWidth: 1,
              priceScaleId: `flow-${key}`,
              priceLineVisible: false,
            },
            paneIndex,
          );
        }
      }
    }

    // -- populate data ------------------------------------------------------
    const { series, indicators } = data;
    const n = series.dates.length;
    const times: UTCTimestamp[] = series.dates.map(
      (d) => Math.floor(new Date(d).getTime() / 1000) as UTCTimestamp,
    );

    const candleData: CandlestickData<UTCTimestamp>[] = [];
    const volumeData: HistogramData<UTCTimestamp>[] = [];
    for (let i = 0; i < n; i++) {
      const o = series.open[i];
      const h = series.high[i];
      const l = series.low[i];
      const c = series.close[i];
      const v = series.volume[i];

      if (!isMissing(o) && !isMissing(h) && !isMissing(l) && !isMissing(c)) {
        candleData.push({ time: times[i], open: o!, high: h!, low: l!, close: c! });
      }
      if (!isMissing(v)) {
        const up = !isMissing(c) && !isMissing(o) && c! >= o!;
        volumeData.push({
          time: times[i],
          value: v!,
          color: up ? alpha(CHART_UP, 0.45) : alpha(CHART_DOWN, 0.45),
        });
      }
    }
    candleSeries.setData(candleData);
    volumeSeries.setData(volumeData);

    // Live in-session candle: appended only when its session date is not
    // already archived (the nightly ingest adds the real bar; no duplicates).
    if (liveCandle && n > 0) {
      const t = Math.floor(new Date(liveCandle.time).getTime() / 1000) as UTCTimestamp;
      const lastT = times[n - 1];
      if (t > lastT) {
        candleData.push({
          time: t,
          open: liveCandle.open,
          high: liveCandle.high,
          low: liveCandle.low,
          close: liveCandle.close,
        });
        candleSeries.setData(candleData);
        if (liveCandle.volume > 0) {
          volumeData.push({
            time: t,
            value: liveCandle.volume,
            color: alpha(liveCandle.close >= liveCandle.open ? CHART_UP : CHART_DOWN, 0.45),
          });
          volumeSeries.setData(volumeData);
        }
      } else if (t === lastT) {
        // Same session already archived: overlay the live close onto that bar.
        const i = candleData.findIndex((c) => c.time === t);
        if (i >= 0) {
          candleData[i] = {
            ...candleData[i],
            close: liveCandle.close,
            high: Math.max(candleData[i].high, liveCandle.high),
            low: Math.min(candleData[i].low, liveCandle.low),
          };
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
            color: alpha(macdHistVals[i]! >= 0 ? CHART_UP : CHART_DOWN, 0.8),
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

    // -- corner labels: registry of (pane, item) -> series + formatter -------
    type Item = {
      pi: number;
      ii: number;
      api: ISeriesApi<"Line"> | ISeriesApi<"Histogram"> | ISeriesApi<"Candlestick">;
      fmt: (v: number) => string;
      latest: number | null;
    };
    const items: Item[] = [];
    // The live candle's close, when present, is the most current known price
    // (it may also overlay an already-archived same-day bar).
    items.push({ pi: 0, ii: 0, api: candleSeries, fmt: (v) => fmtNum(v, 2), latest: liveCandle ? liveCandle.close : lastNonNull(series.close) });
    items.push({ pi: 1, ii: 0, api: volumeSeries, fmt: (v) => compactFmt.format(v), latest: liveCandle && liveCandle.volume > 0 ? liveCandle.volume : lastNonNull(series.volume) });

    let nextPane = 2;
    if (rsiOn) {
      items.push({ pi: nextPane, ii: 0, api: rsiSeries!, fmt: (v) => fmtNum(v, 2), latest: lastNonNull(indicators.rsi_14) });
      nextPane += 1;
    }
    if (macdOn) {
      items.push({ pi: nextPane, ii: 0, api: macdSeries!, fmt: (v) => fmtNum(v, 2), latest: lastNonNull(indicators.macd) });
      items.push({ pi: nextPane, ii: 1, api: macdSignalSeries!, fmt: (v) => fmtNum(v, 2), latest: lastNonNull(indicators.macd_signal) });
      items.push({ pi: nextPane, ii: 2, api: macdHistSeries!, fmt: (v) => fmtNum(v, 2), latest: lastNonNull(indicators.macd_histogram) });
      nextPane += 1;
    }
    if (trixOn) {
      items.push({ pi: nextPane, ii: 0, api: trixSeries!, fmt: (v) => fmtNum(v, 2), latest: lastNonNull(indicators.trix_15) });
      nextPane += 1;
    }
    if (oscDefs.length) {
      oscDefs.forEach((def, ii) => {
        items.push({
          pi: nextPane,
          ii,
          api: oscSeriesMap[def.series[0]],
          fmt: (v) => fmtNum(v, 2),
          latest: lastNonNull(indicators[def.series[0]]),
        });
      });
      nextPane += 1;
    }
    if (trendDefs.length) {
      trendDefs.forEach((def, ii) => {
        items.push({
          pi: nextPane,
          ii,
          api: trendSeriesMap[def.series[0]],
          fmt: (v) => fmtNum(v, 2),
          latest: lastNonNull(indicators[def.series[0]]),
        });
      });
      nextPane += 1;
    }
    if (flowDefs.length) {
      flowDefs.forEach((def, ii) => {
        items.push({
          pi: nextPane,
          ii,
          api: flowSeriesMap[def.series[0]],
          fmt: (v) => compactFmt.format(v),
          latest: lastNonNull(indicators[def.series[0]]),
        });
      });
    }

    const showLatest = () => {
      for (const it of items) {
        const el = valueSpans.current.get(`${it.pi}:${it.ii}`);
        if (el && it.latest != null) el.textContent = it.fmt(it.latest);
      }
    };
    showLatest();

    chart.subscribeCrosshairMove((param) => {
      for (const it of items) {
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
    });

    // Pane label tops follow the real pane geometry (stretch factors), so
    // recompute on every container resize.
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
    };
    // `selected` drives every def list above; `data` and the live tick rebuild
    // the chart.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, selected, liveCandle]);

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

  const legendLatest = (key: IndicatorKey) => lastNonNull(data.indicators[key]);

  return (
    <div className="tc-chart-wrap">
      <div ref={containerRef} className="tc-chart" style={{ height: chartHeight }} />

      {/* Corner labels, one row per pane, values follow the crosshair. */}
      {paneLabels.map((pane, pi) => (
        <div
          key={pane.id}
          className="tc-pane-label"
          ref={(el) => {
            labelRefs.current[pi] = el;
          }}
        >
          {pane.items.map((it, ii) => (
            <span key={it.key} className="tc-pl-item">
              {it.color && <span className="dot" style={{ background: it.color }} />}
              <span className="tc-pl-name">{it.name}</span>
              <span
                ref={(el) => {
                  const k = `${pi}:${ii}`;
                  if (el) valueSpans.current.set(k, el);
                  else valueSpans.current.delete(k);
                }}
              >
                –
              </span>
            </span>
          ))}
        </div>
      ))}

      {/* Price-pane legend for active overlays: dot, label, latest value, x. */}
      {overlayDefs.length > 0 && (
        <div className="tc-legend">
          {overlayDefs.map((def) => (
            <span key={def.key} className="tc-legend-chip" style={{ borderColor: def.color }}>
              <span className="dot" style={{ background: def.color }} />
              <span>{def.label}</span>
              {def.series.map((k) => {
                const v = legendLatest(k);
                return <span key={k}>{v == null ? "–" : fmtNum(v, 2)}</span>;
              })}
              {onToggleOverlay && (
                <button
                  type="button"
                  className="tc-legend-x"
                  aria-label={`Remove ${def.label}`}
                  onClick={() => onToggleOverlay(def.key)}
                >
                  ×
                </button>
              )}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/* -- the Technical page card ------------------------------------------------ */

function loadSelected(): IndicatorId[] {
  try {
    const raw = window.localStorage.getItem(CHART_INDICATORS_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    if (Array.isArray(parsed)) {
      const valid = parsed.filter(
        (k): k is IndicatorId => typeof k === "string" && INDICATORS.some((d) => d.key === k),
      );
      if (valid.length) return valid;
    }
  } catch {
    /* fall through to the default mix */
  }
  return DEFAULT_SELECTION;
}

/** Chart header: symbol, name, last close, change and %, as-of date.
 * When a fresh live quote exists, LTP/change come from it and the header says
 * LIVE; otherwise the last archived close is shown. Never presents a stale
 * quote as live. */
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
  const ref = liveFresh ? live!.change !== 0 || live!.change_pct !== 0
    ? live!.ltp - live!.change
    : prev : prev;
  const chg = price != null && ref != null ? price - ref : null;
  const pct = chg != null && ref ? (chg / ref) * 100 : null;
  const up = (chg ?? 0) >= 0;
  const tone = { color: up ? CHART_UP : CHART_DOWN };

  return (
    <div className="tc-header">
      <span className="tc-symbol">{data.symbol}</span>
      {data.name && <span className="tc-name">{data.name}</span>}
      <span className="tc-price" style={tone}>
        {fmtNum(price)}
      </span>
      <span className="tc-chg" style={tone}>
        {fmtSigned(chg)} ({fmtPct(pct)})
      </span>
      {liveFresh && <span className="tc-live-badge">LIVE</span>}
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
  const [selected, setSelected] = useState<IndicatorId[]>(loadSelected);
  const [range, setRange] = useState<string>(() => {
    try {
      return window.localStorage.getItem(CHART_RANGE_KEY) ?? "6M";
    } catch {
      return "6M";
    }
  });
  const [chipHidden, setChipHidden] = useState(false);

  useEffect(() => {
    try {
      window.localStorage.setItem(CHART_INDICATORS_KEY, JSON.stringify(selected));
    } catch {
      /* non-fatal */
    }
  }, [selected]);
  useEffect(() => {
    try {
      window.localStorage.setItem(CHART_RANGE_KEY, range);
    } catch {
      /* non-fatal */
    }
  }, [range]);
  useEffect(() => setChipHidden(false), [symbol, range]);

  const toggle = (id: IndicatorId) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((k) => k !== id) : [...prev, id]));

  const query = useQuery({
    queryKey: ["chart", symbol, range, selected],
    queryFn: ({ signal }) =>
      analytics.chart(symbol, { range, mode: "UNADJUSTED", indicators: selectedToParam(selected) }, signal),
    enabled: !!symbol,
    staleTime: 60_000,
  });
  const data = query.data;

  // Live tick for this symbol from the backend's shared poller (30s refresh;
  // one NEPSE call per interval server-side no matter how many tabs poll).
  const { quotes } = useLiveQuotes(symbol ? [symbol] : []);
  const live = quotes.get(symbol) ?? null;

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
              className={`tc-range-btn${range === r ? " on" : ""}`}
              onClick={() => setRange(r)}
            >
              {r}
            </button>
          ))}
        </div>
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
                Archive for {range} starts {fmtDate(data.range.first_shown)}.
              </span>
              <button type="button" aria-label="Dismiss" onClick={() => setChipHidden(true)}>
                ×
              </button>
            </div>
          )}
          <TechnicalChart
            data={{ series: data.series, indicators: data.indicators }}
            selected={selected}
            symbol={symbol}
            onToggleOverlay={toggle}
            liveCandle={liveCandle}
          />
        </>
      )}
    </section>
  );
}

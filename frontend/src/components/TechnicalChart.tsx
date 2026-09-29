/* Lightweight Charts wrapper for the company page.
 *
 * Renders price candles with overlays (SMA/EMA/WMA/HMA/DEMA/TEMA, VWAP,
 * Bollinger Bands) and indicator panes below (RSI, MACD, TRIX, ADX/DMI,
 * Aroon, OBV/A&D, CMF/MFI). Adjusted close is derived from bonus/right
 * actions when available.
 */

import { useEffect, useRef } from "react";
import {
  createChart,
  IChartApi,
  ISeriesApi,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  UTCTimestamp,
  CandlestickData,
  LineData,
  HistogramData,
  DeepPartial,
  ChartOptions,
} from "lightweight-charts";
import type { ChartSeries, IndicatorKey } from "../types";
import { INDICATORS, INDICATOR_COLORS, DEFAULT_SELECTION } from "../indicators";
import type { IndicatorId } from "../indicators";
import { isMissing } from "../format";

interface ChartData {
  series: ChartSeries;
  indicators: Partial<Record<IndicatorKey, (number | null)[]>>;
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

/** Registry-driven renderer: every series comes from `INDICATORS` + `selected`. */
export function TechnicalChart({
  data,
  selected,
}: {
  data: ChartData;
  /** Selected registry ids; defaults to the classic mix. */
  selected?: IndicatorId[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  // One selection drives everything: default keeps the classic mix for callers
  // that do not pass a picker state.
  // One selection drives everything: default keeps the classic mix for callers
  // that do not pass a picker state.
  const selection = new Set<IndicatorId>(selected ?? DEFAULT_SELECTION);
  const overlayDefs = INDICATORS.filter(
    (d) => (d.pane === "overlay" || d.pane === "cloud") && selection.has(d.key),
  );
  const flowDefs = INDICATORS.filter(
    (d) => d.pane === "flow" && selection.has(d.key),
  );
  const trendDefs = INDICATORS.filter(
    (d) => d.pane === "trend" && selection.has(d.key),
  );
  const trixWanted = selection.has("trix_15");

  // The chart is rebuilt whenever the payload changes: the cleanup removes
  // the previous instance, so a stale `initialized` guard must NOT sit in
  // front of creation - it used to let the cleanup destroy the fresh chart
  // and then exit early, leaving an empty container.
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: "solid", color: "transparent" },
        textColor: "var(--text)",
        fontSize: 11,
        fontFamily: "var(--font-mono)",
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: "var(--border)" },
        horzLines: { color: "var(--border)" },
      },
      crosshair: {
        mode: 1,
      },
      rightPriceScale: {
        borderColor: "var(--border)",
      },
      timeScale: {
        borderColor: "var(--border)",
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (time: number) => {
          const date = new Date((time as UTCTimestamp) * 1000);
          return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
        },
      },
      handleScale: {
        axisPressedMouseMove: true,
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
      },
    } as DeepPartial<ChartOptions>);

    chartRef.current = chart;

    // Main price pane (index 0)
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "var(--up)",
      downColor: "var(--down)",
      borderUpColor: "var(--up)",
      borderDownColor: "var(--down)",
      wickUpColor: "var(--up)",
      wickDownColor: "var(--down)",
    });

    // Panes are created on demand, in order: price (0), volume (1), then one
    // pane per selected indicator family. Indexes must stay sequential.
    let paneIndex = 0;

    // Overlay lines on the main price pane (index 0). A definition may carry
    // several series (Bollinger emits three bands for one selection).
    const overlays: { key: IndicatorKey; api: ISeriesApi<"Line"> }[] = [];
    for (const def of overlayDefs) {
      for (const key of def.series) {
        overlays.push({
          key,
          api: chart.addSeries(LineSeries, {
            color: def.colors?.[key] ?? def.color,
            lineWidth: 1,
            priceScaleId: "right",
            priceLineVisible: false,
          }, 0),
        });
      }
    }

    // Volume pane.
    paneIndex += 1;
    const volumePane = chart.addPane();
    volumePane.setHeight(100);
    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: "rgba(138, 146, 159, 0.5)",
      priceScaleId: "volume",
      priceFormat: { type: "volume" },
    }, paneIndex);

    // RSI pane.
    const rsiWanted = selection.has("rsi_14");
    let rsiSeries: ISeriesApi<"Line"> | null = null;
    if (rsiWanted) {
      paneIndex += 1;
      const rsiPane = chart.addPane();
      rsiPane.setHeight(100);
      rsiSeries = chart.addSeries(LineSeries, {
        color: INDICATOR_COLORS.rsi_14,
        lineWidth: 1,
        priceScaleId: "rsi",
        priceLineVisible: false,
      }, paneIndex);
    }

    // MACD pane (line + signal + histogram whenever MACD is selected).
    const macdWanted = selection.has("macd");
    let macdSeries: ISeriesApi<"Line"> | null = null;
    let macdSignalSeries: ISeriesApi<"Line"> | null = null;
    let macdHistSeries: ISeriesApi<"Histogram"> | null = null;
    if (macdWanted) {
      paneIndex += 1;
      const macdPane = chart.addPane();
      macdPane.setHeight(90);
      macdSeries = chart.addSeries(LineSeries, {
        color: INDICATOR_COLORS.macd,
        lineWidth: 1,
        priceScaleId: "macd",
      }, paneIndex);
      macdSignalSeries = chart.addSeries(LineSeries, {
        color: INDICATOR_COLORS.macd_signal,
        lineWidth: 1,
        priceScaleId: "macd",
      }, paneIndex);
      macdHistSeries = chart.addSeries(HistogramSeries, {
        color: INDICATOR_COLORS.macd_histogram,
        priceScaleId: "macd",
      }, paneIndex);
    }

    // TRIX pane.
    let trixSeries: ISeriesApi<"Line"> | null = null;
    if (trixWanted) {
      paneIndex += 1;
      const trixPane = chart.addPane();
      trixPane.setHeight(90);
      trixSeries = chart.addSeries(LineSeries, {
        color: INDICATOR_COLORS.trix_15,
        lineWidth: 1,
        priceScaleId: "trix",
      }, paneIndex);
    }

    // Trend-strength pane: ADX/DMI, Aroon and Vortex share one pane, but each
    // family gets its own price scale (they measure different things: percent
    // 0-100 versus ratios around 1.0), mirroring the flow pane's approach.
    const trendSeriesMap: Record<string, ISeriesApi<"Line">> = {};
    if (trendDefs.length) {
      paneIndex += 1;
      const trendPane = chart.addPane();
      trendPane.setHeight(110);
      for (const def of trendDefs) {
        for (const key of def.series) {
          trendSeriesMap[key] = chart.addSeries(LineSeries, {
            color: def.colors?.[key] ?? def.color,
            lineWidth: 1,
            priceScaleId: `trend-${def.key}`,
            priceLineVisible: false,
          }, paneIndex);
        }
      }
    }

    // Volume-flow pane: one shared pane, one price scale per series so units
    // (shares, money, percent) never fight each other.
    const flowSeriesMap: Record<string, ISeriesApi<"Line">> = {};
    if (flowDefs.length) {
      paneIndex += 1;
      const flowPane = chart.addPane();
      flowPane.setHeight(110);
      for (const def of flowDefs) {
        for (const key of def.series) {
          flowSeriesMap[key] = chart.addSeries(LineSeries, {
            color: def.colors?.[key] ?? def.color,
            lineWidth: 1,
            priceScaleId: `flow-${key}`,
            priceLineVisible: false,
          }, paneIndex);
        }
      }
    }

    // Populate data
    const { series, indicators } = data;
    const n = series.dates.length;

    // Convert dates to UTC timestamps
    const times: UTCTimestamp[] = series.dates.map((d) => Math.floor(new Date(d).getTime() / 1000)) as UTCTimestamp[];

    // Candlestick data
    const candleData: CandlestickData<UTCTimestamp>[] = [];
    const volumeData: HistogramData<UTCTimestamp>[] = [];

    for (let i = 0; i < n; i++) {
      const o = series.open[i];
      const h = series.high[i];
      const l = series.low[i];
      const c = series.close[i];
      const v = series.volume[i];

      if (!isMissing(o) && !isMissing(h) && !isMissing(l) && !isMissing(c)) {
        candleData.push({
          time: times[i],
          open: o!,
          high: h!,
          low: l!,
          close: c!,
        });
      }

      if (!isMissing(v)) {
        volumeData.push({
          time: times[i],
          value: v!,
          color: !isMissing(c) && !isMissing(series.open[i]) && c! >= series.open[i]!
            ? "var(--up)"
            : "var(--down)",
        });
      }
    }

    candleSeries.setData(candleData);
    volumeSeries.setData(volumeData);

    // Overlay indicators
    for (const { key, api } of overlays) {
      api.setData(toLineData(times, indicators[key] ?? []));
    }

    // RSI
    if (rsiSeries) {
      rsiSeries.setData(toLineData(times, indicators.rsi_14 ?? []));
    }

    // MACD
    if (macdSeries && macdSignalSeries && macdHistSeries) {
      macdSeries.setData(toLineData(times, indicators.macd ?? []));
      macdSignalSeries.setData(toLineData(times, indicators.macd_signal ?? []));
      const macdHistVals = indicators.macd_histogram ?? [];
      const macdHistData: HistogramData<UTCTimestamp>[] = [];
      for (let i = 0; i < macdHistVals.length && i < n; i++) {
        if (!isMissing(macdHistVals[i])) {
          macdHistData.push({
            time: times[i],
            value: macdHistVals[i]!,
            color: macdHistVals[i]! >= 0 ? "var(--up)" : "var(--down)",
          });
        }
      }
      macdHistSeries.setData(macdHistData);
    }

    // TRIX
    if (trixSeries) {
      trixSeries.setData(toLineData(times, indicators.trix_15 ?? []));
    }

    // Trend-strength family (ADX/DMI, Aroon)
    for (const def of trendDefs) {
      for (const key of def.series) {
        trendSeriesMap[key]?.setData(toLineData(times, indicators[key] ?? []));
      }
    }

    // Volume-flow family
    for (const def of flowDefs) {
      for (const key of def.series) {
        flowSeriesMap[key]?.setData(toLineData(times, indicators[key] ?? []));
      }
    }

    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [data]);

  return <div ref={containerRef} style={{ width: "100%", height: "600px" }} />;
}
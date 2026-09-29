/* The one registry of technical indicators.
 *
 * Two name spaces live here, deliberately distinct:
 *
 *   IndicatorToken - what the /api/analytics/chart `indicators=` param accepts
 *                    (e.g. `bb`, one token that makes the backend emit three
 *                    band series; `ad` for the accumulation/distribution line).
 *   IndicatorKey   - the payload keys the response carries (types.ts), i.e.
 *                    what TechnicalChart actually draws.
 *
 * A registry entry maps one picker row to its token and to every payload key
 * the selection produces, so the chart, the picker and the request builder all
 * read from this single list. Adding an indicator later means: one entry here,
 * one `if key in wanted` block in app/analytics/chart.py, and the payload keys
 * appended to the IndicatorKey union in types.ts. There is no second list.
 */

import type { IndicatorKey } from "./types";

/** Tokens accepted by GET /api/analytics/chart?indicators=... */
export type IndicatorToken =
  | "sma_20"
  | "ema_20"
  | "wma_20"
  | "hma_16"
  | "dema_20"
  | "tema_20"
  | "trix_15"
  | "adx"
  | "aroon"
  | "psar"
  | "supertrend"
  | "vortex"
  | "ichimoku"
  | "rsi_14"
  | "macd"
  | "bb"
  | "vwap"
  | "obv"
  | "ad"
  | "cmf"
  | "mfi"
  | "roc";

/** Picker rows (== registry keys). Multi-series families have one id. */
export type IndicatorId = Exclude<IndicatorToken, "roc">;

export type IndicatorPane = "overlay" | "cloud" | "rsi" | "macd" | "trix" | "trend" | "flow";

export interface IndicatorDef {
  /** Picker state id. */
  key: IndicatorId;
  /** Token sent to the chart endpoint. */
  token: IndicatorToken;
  label: string;
  color: string;
  pane: IndicatorPane;
  /** Payload keys this selection draws, in draw order. */
  series: IndicatorKey[];
  /** Per-payload-key color overrides (e.g. Bollinger's lighter middle band). */
  colors?: Partial<Record<IndicatorKey, string>>;
}

/** Selectable indicators, in picker order. */
export const INDICATORS: IndicatorDef[] = [
  // Trend / overlays
  { key: "sma_20", token: "sma_20", label: "SMA 20", color: "#2962ff", pane: "overlay", series: ["sma_20"] },
  { key: "ema_20", token: "ema_20", label: "EMA 20", color: "#ff6d00", pane: "overlay", series: ["ema_20"] },
  { key: "wma_20", token: "wma_20", label: "WMA 20", color: "#00b0ff", pane: "overlay", series: ["wma_20"] },
  { key: "hma_16", token: "hma_16", label: "HMA 16", color: "#76ff03", pane: "overlay", series: ["hma_16"] },
  { key: "dema_20", token: "dema_20", label: "DEMA 20", color: "#ffab00", pane: "overlay", series: ["dema_20"] },
  { key: "tema_20", token: "tema_20", label: "TEMA 20", color: "#f06292", pane: "overlay", series: ["tema_20"] },
  { key: "vwap", token: "vwap", label: "VWAP", color: "#00c853", pane: "overlay", series: ["vwap"] },
  {
    key: "bb",
    token: "bb",
    label: "Bollinger Bands",
    color: "#aa00ff",
    pane: "overlay",
    series: ["bb_upper", "bb_middle", "bb_lower"],
    colors: { bb_middle: "#7b1fa2" },
  },
  { key: "psar", token: "psar", label: "Parabolic SAR", color: "#ffd600", pane: "overlay", series: ["psar"] },
  { key: "supertrend", token: "supertrend", label: "Supertrend", color: "#00e676", pane: "overlay", series: ["supertrend"] },
  {
    key: "ichimoku",
    token: "ichimoku",
    label: "Ichimoku Cloud",
    color: "#18a0fb",
    pane: "cloud",
    series: [
      "ichimoku_tenkan",
      "ichimoku_kijun",
      "ichimoku_senkou_a",
      "ichimoku_senkou_b",
      "ichimoku_chikou",
    ],
    colors: {
      ichimoku_tenkan: "#18a0fb",
      ichimoku_kijun: "#b25000",
      ichimoku_senkou_a: "#26a69a",
      ichimoku_senkou_b: "#ef5350",
      ichimoku_chikou: "#9c27b0",
    },
  },
  // Sub-panes
  { key: "rsi_14", token: "rsi_14", label: "RSI 14", color: "#2962ff", pane: "rsi", series: ["rsi_14"] },
  {
    key: "macd",
    token: "macd",
    label: "MACD",
    color: "#2962ff",
    pane: "macd",
    series: ["macd", "macd_signal", "macd_histogram"],
    colors: { macd_signal: "#ff6d00", macd_histogram: "#4caf50" },
  },
  { key: "trix_15", token: "trix_15", label: "TRIX 15", color: "#e040fb", pane: "trix", series: ["trix_15"] },
  // Trend-strength pane
  {
    key: "adx",
    token: "adx",
    label: "ADX / DMI",
    color: "#2962ff",
    pane: "trend",
    series: ["adx", "plus_di", "minus_di", "dx"],
    colors: { plus_di: "#00c853", minus_di: "#ff5252", dx: "#9e9e9e" },
  },
  {
    key: "aroon",
    token: "aroon",
    label: "Aroon",
    color: "#00b0ff",
    pane: "trend",
    series: ["aroon_up", "aroon_down"],
    colors: { aroon_down: "#ff6d00" },
  },
  // Vortex is a ratio around 1.0, not a 0-100 percent, so it keeps its own
  // price scale inside the shared trend pane (scales are per family).
  {
    key: "vortex",
    token: "vortex",
    label: "Vortex",
    color: "#00c853",
    pane: "trend",
    series: ["vortex_plus", "vortex_minus"],
    colors: { vortex_minus: "#ff5252" },
  },
  // Volume-flow pane
  { key: "obv", token: "obv", label: "OBV", color: "#00c853", pane: "flow", series: ["obv"] },
  { key: "ad", token: "ad", label: "Acc/Dist", color: "#ff6d00", pane: "flow", series: ["accumulation_distribution"] },
  { key: "cmf", token: "cmf", label: "CMF 20", color: "#aa00ff", pane: "flow", series: ["chaikin_money_flow_20"] },
  { key: "mfi", token: "mfi", label: "MFI 14", color: "#7b1fa2", pane: "flow", series: ["money_flow_index_14"] },
];

/** Default picker mix when nothing is stored. */
export const DEFAULT_SELECTION: IndicatorId[] = ["sma_20", "ema_20", "rsi_14", "macd"];

/** Color for every payload key, derived from the registry (never hand-listed). */
export const INDICATOR_COLORS: Record<string, string> = Object.fromEntries(
  INDICATORS.flatMap((d) => d.series.map((k) => [k, d.colors?.[k] ?? d.color])),
);

/** Picker selection -> the `indicators=` request parameter (deduplicated). */
export function selectedToParam(selected: IndicatorId[]): string {
  const tokens = selected
    .filter((k) => INDICATORS.some((d) => d.key === k))
    .map((k) => INDICATORS.find((d) => d.key === k)!.token);
  return [...new Set(tokens)].join(",");
}

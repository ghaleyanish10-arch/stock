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
  | "roc"
  | "atr"
  /* Trading Indicators notes additions */
  | "stoch"
  | "stoch_rsi"
  | "cci"
  | "williams_r"
  | "momentum"
  | "ultimate_osc"
  | "awesome_osc"
  | "tsi"
  | "rvi"
  | "stdev"
  | "keltner"
  | "donchian"
  | "historical_vol"
  | "chaikin_vol"
  | "vpt"
  | "emv"
  | "force_index"
  | "volume_osc"
  | "klinger"
  | "chaikin_osc"
  | "vwma"
  | "cvd"
  | "pivots"
  | "camarilla"
  | "woodie"
  | "demark"
  | "fib_retrace"
  | "fib_extension"
  | "fib_fan"
  | "volume_profile";

/** Picker rows (== registry keys). Multi-series families have one id. */
export type IndicatorId = IndicatorToken;

export type IndicatorPane =
  | "overlay"
  | "cloud"
  | "rsi"
  | "macd"
  | "trix"
  | "trend"
  | "flow"
  /** Bounded oscillator (0-100 family): Stochastic, StochRSI, Williams %R, UO. */
  | "osc";

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
  /** One-line plain-language definition (from the Trading Indicators notes). */
  desc?: string;
}

/** Selectable indicators, in picker order. */
export const INDICATORS: IndicatorDef[] = [
  // Trend / overlays
  { key: "sma_20", token: "sma_20", label: "SMA 20", color: "#2962ff", pane: "overlay", series: ["sma_20"], desc: "Arithmetic mean of the last 20 closes. Smooths daily noise to show trend direction; often acts as dynamic support/resistance." },
  { key: "ema_20", token: "ema_20", label: "EMA 20", color: "#ff6d00", pane: "overlay", series: ["ema_20"], desc: "Moving average that weights recent prices more (k = 2/(n+1)), so it reacts faster to reversals than the SMA." },
  { key: "wma_20", token: "wma_20", label: "WMA 20", color: "#00b0ff", pane: "overlay", series: ["wma_20"], desc: "Linearly weighted average - the newest close gets the highest weight - making it more responsive than the SMA." },
  { key: "hma_16", token: "hma_16", label: "HMA 16", color: "#76ff03", pane: "overlay", series: ["hma_16"], desc: "Alan Hull (2005): nearly zero-lag moving average that stays smooth while hugging price action." },
  { key: "dema_20", token: "dema_20", label: "DEMA 20", color: "#ffab00", pane: "overlay", series: ["dema_20"], desc: "Patrick Mulloy (1994): 2xEMA - EMA(EMA), removing much of the ordinary EMA's lag." },
  { key: "tema_20", token: "tema_20", label: "TEMA 20", color: "#f06292", pane: "overlay", series: ["tema_20"], desc: "Mulloy's triple-EMA combo (3EMA - 3EMA(EMA) + EMA(EMA(EMA))); even less lag than DEMA." },
  { key: "vwap", token: "vwap", label: "VWAP", color: "#00c853", pane: "overlay", series: ["vwap"], desc: "Average price weighted by volume - the session's 'fair value'. Prices above it read as bullish, below as bearish." },
  {
    key: "bb",
    token: "bb",
    label: "Bollinger Bands",
    color: "#aa00ff",
    pane: "overlay",
    series: ["bb_upper", "bb_middle", "bb_lower"],
    colors: { bb_middle: "#7b1fa2" },
    desc: "SMA 20 plus/minus two standard deviations. Squeezes mark quiet markets, expansions mark volatile ones; %B locates price inside the bands.",
  },
  { key: "psar", token: "psar", label: "Parabolic SAR", color: "#ffd600", pane: "overlay", series: ["psar"], desc: "Trailing stop-and-reverse dots below price in uptrends and above in downtrends; a flip signals a potential reversal." },
  { key: "supertrend", token: "supertrend", label: "Supertrend", color: "#00e676", pane: "overlay", series: ["supertrend"], desc: "Olivier Seban (2009): ATR-based trailing line (default 10, x3) that flips side on reversals - green below price in uptrends, red above in downtrends." },
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
    desc: "Conversion/base lines plus a forward-projected cloud (senkou spans). Price above the cloud reads bullish, below bearish, inside undecided.",
  },
  // Sub-panes
  { key: "rsi_14", token: "rsi_14", label: "RSI 14", color: "#2962ff", pane: "rsi", series: ["rsi_14"], desc: "Momentum oscillator 0-100. Above 70 = overbought, below 30 = oversold; divergences against price hint at reversals." },
  {
    key: "macd",
    token: "macd",
    label: "MACD",
    color: "#2962ff",
    pane: "macd",
    series: ["macd", "macd_signal", "macd_histogram"],
    colors: { macd_signal: "#ff6d00", macd_histogram: "#4caf50" },
    desc: "12-26 EMA spread (MACD line) vs its 9-EMA (signal). Crossovers time entries; the histogram shows momentum strength.",
  },
  { key: "trix_15", token: "trix_15", label: "TRIX 15", color: "#e040fb", pane: "trix", series: ["trix_15"], desc: "Percent rate of change of a triple-smoothed EMA; filters noise and its sign tracks the underlying trend." },
  // Trend-strength pane
  {
    key: "adx",
    token: "adx",
    label: "ADX / DMI",
    color: "#2962ff",
    pane: "trend",
    series: ["adx", "plus_di", "minus_di", "dx"],
    colors: { plus_di: "#00c853", minus_di: "#ff5252", dx: "#9e9e9e" },
    desc: "ADX (0-100) measures trend STRENGTH (>25 trending), +DI/-DI its direction. A +DI cross above -DI favours longs.",
  },
  {
    key: "aroon",
    token: "aroon",
    label: "Aroon",
    color: "#00b0ff",
    pane: "trend",
    series: ["aroon_up", "aroon_down"],
    colors: { aroon_down: "#ff6d00" },
    desc: "Days since the latest 25-day high (up) / low (down), scaled 0-100. Readings above 70 mark fresh extremes; crossovers flag trend shifts.",
  },
  {
    key: "vortex",
    token: "vortex",
    label: "Vortex",
    color: "#00c853",
    pane: "trend",
    series: ["vortex_plus", "vortex_minus"],
    colors: { vortex_minus: "#ff5252" },
    desc: "VI+ (upward movement) vs VI- (downward) as ratios around 1.0. VI+ crossing above VI- signals a new uptrend, and vice versa.",
  },
  // Volume-flow pane
  { key: "obv", token: "obv", label: "OBV", color: "#00c853", pane: "flow", series: ["obv"], desc: "Running total that adds volume on up-days and subtracts it on down-days; rising OBV with rising price confirms the trend." },
  { key: "ad", token: "ad", label: "Acc/Dist", color: "#ff6d00", pane: "flow", series: ["accumulation_distribution"], desc: "Cumulative line weighting volume by where the close sits in the day's range (Close Location Value); shows accumulation vs distribution." },
  { key: "cmf", token: "cmf", label: "CMF 20", color: "#aa00ff", pane: "flow", series: ["chaikin_money_flow_20"], desc: "20-day sum of money-flow volume over volume. Positive = buying pressure, negative = selling pressure." },
  { key: "mfi", token: "mfi", label: "MFI 14", color: "#7b1fa2", pane: "flow", series: ["money_flow_index_14"], desc: "Volume-weighted RSI: positive vs negative money flow over 14 days. Above 80 overbought, below 20 oversold." },
  { key: "roc", token: "roc", label: "ROC (1d)", color: "#26a69a", pane: "flow", series: ["roc_1"], desc: "Pure momentum: percent change of price versus n periods ago (here 1 day)." },
  { key: "atr", token: "atr", label: "ATR 14", color: "#ff5252", pane: "flow", series: ["atr_14"], desc: "Average True Range: the average daily range (true range accounts for gaps). A volatility yardstick for stops and position sizing." },

  // -- Trading Indicators notes additions ---------------------------------
  // Momentum
  {
    key: "stoch",
    token: "stoch",
    label: "Stochastic",
    color: "#2962ff",
    pane: "osc",
    series: ["stoch_k", "stoch_d"],
    colors: { stoch_d: "#ff6d00" },
    desc: "George Lane: %K places the close inside the 14-day high-low range, %D smooths it. Above 80 overbought, below 20 oversold; %K/%D crossovers time the turn.",
  },
  { key: "stoch_rsi", token: "stoch_rsi", label: "Stoch RSI", color: "#00bfa5", pane: "osc", series: ["stoch_rsi"], desc: "The Stochastic formula applied to RSI instead of price: where the current RSI sits in its own 14-day range. The most overbought/oversold-sensitive RSI variant." },
  { key: "cci", token: "cci", label: "CCI 20", color: "#7c4dff", pane: "osc", series: ["cci_20"], desc: "Distance of the typical price from its average, scaled by 0.015 x mean absolute deviation. Beyond +/-100 marks cyclical extremes." },
  { key: "williams_r", token: "williams_r", label: "Williams %R", color: "#f06292", pane: "osc", series: ["williams_r_14"], desc: "Close vs the 14-day range on a 0 to -100 scale: 0 = closing at the very high, -100 at the very low. Below -80 oversold, above -20 overbought." },
  { key: "momentum", token: "momentum", label: "Momentum 10", color: "#ffa000", pane: "osc", series: ["momentum_10"], desc: "Close minus the close 10 sessions ago, in price units. The plainest speed gauge - above zero the trend is up, below zero down." },
  { key: "ultimate_osc", token: "ultimate_osc", label: "Ultimate Osc", color: "#3949ab", pane: "osc", series: ["ultimate_osc"], desc: "Larry Williams: buying pressure averaged over 7, 14 and 28 days (short window weighted 4x) to cut single-timeframe false divergences. Above 70 overbought, below 30 oversold." },
  { key: "awesome_osc", token: "awesome_osc", label: "Awesome Osc", color: "#00897b", pane: "osc", series: ["awesome_osc"], desc: "Bill Williams: SMA5 minus SMA34 of the median price. Crossing above zero = momentum shifting up; saucers and twin peaks fine-tune entries." },
  { key: "tsi", token: "tsi", label: "TSI", color: "#5e35b1", pane: "osc", series: ["tsi"], desc: "True Strength Index: double-smoothed (25,13) momentum of price change relative to absolute price change. Zero-line crosses carry the trend; divergences flag reversals." },
  {
    key: "rvi",
    token: "rvi",
    label: "RVI",
    color: "#d81b60",
    pane: "osc",
    series: ["rvi", "rvi_signal"],
    colors: { rvi_signal: "#ffa726" },
    desc: "Relative Vigor Index: where the close sits in the bar's range vs its open, symmetric-smoothed (1,2,2,1). Closes above opens in uptrends give positive vigor; RVI/signal crossovers time entries.",
  },
  // Volatility
  { key: "stdev", token: "stdev", label: "Std Dev 20", color: "#9575cd", pane: "flow", series: ["stdev_20"], desc: "Rolling 20-day standard deviation of price: the dispersion measure behind Bollinger Bands, shown on its own. Rising = volatile market, falling = quiet." },
  {
    key: "keltner",
    token: "keltner",
    label: "Keltner Channels",
    color: "#26a69a",
    pane: "overlay",
    series: ["keltner_upper", "keltner_middle", "keltner_lower"],
    colors: { keltner_middle: "#00897b" },
    desc: "EMA 20 with bands 2 ATRs (10-period) above and below. A close outside the channel often precedes a move back to the middle line; riding the band marks a strong trend.",
  },
  {
    key: "donchian",
    token: "donchian",
    label: "Donchian Channels",
    color: "#42a5f5",
    pane: "overlay",
    series: ["donchian_upper", "donchian_middle", "donchian_lower"],
    colors: { donchian_middle: "#1565c0" },
    desc: "Highest high and lowest low of the last 20 days with their midpoint - the original turtle-trading breakout channel. A close outside the channel is the trend-entry signal.",
  },
  { key: "historical_vol", token: "historical_vol", label: "Hist Vol 20", color: "#ef6c00", pane: "flow", series: ["historical_vol_20"], desc: "Annualized standard deviation of daily log returns (sqrt-252 scaled). The realized-risk yardstick - compare symbols by ranking this number." },
  { key: "chaikin_vol", token: "chaikin_vol", label: "Chaikin Vol", color: "#8d6e63", pane: "flow", series: ["chaikin_volatility"], desc: "Marc Chaikin: percent change of the 10-day EMA of the high-low range over 10 days. Rising = ranges expanding, falling = quiet that often precedes a move." },
  // Volume
  { key: "vpt", token: "vpt", label: "VPT", color: "#2e7d32", pane: "flow", series: ["vpt"], desc: "Volume Price Trend: adds volume scaled by the percent price change, so a big move on thin volume can outweigh a small move on heavy volume. Rising VPT confirms uptrends." },
  { key: "emv", token: "emv", label: "EMV 14", color: "#00695c", pane: "flow", series: ["emv_14"], desc: "Ease of Movement: midpoint price change divided by the volume box ratio. High readings = price travelling far on little volume (easy), near zero = heavy going." },
  { key: "force_index", token: "force_index", label: "Force Index", color: "#ad1457", pane: "flow", series: ["force_index_13"], desc: "Alexander Elder: close-to-close change x volume, 13-day EMA smoothed. Direction, magnitude and participation in one line; zero-line crosses mark shifts in power." },
  { key: "volume_osc", token: "volume_osc", label: "Volume Osc", color: "#558b2f", pane: "flow", series: ["volume_osc"], desc: "5-day volume MA minus 20-day volume MA as a percent of the long MA. Positive = volume expanding behind the move, negative = participation drying up." },
  { key: "klinger", token: "klinger", label: "Klinger", color: "#6a1b9a", pane: "flow", series: ["klinger"], desc: "Klinger Volume Oscillator: volume force (direction x range positioning x volume), EMA34 minus EMA55. Its long-term money-flow divergences against price are the signal." },
  { key: "chaikin_osc", token: "chaikin_osc", label: "Chaikin Osc", color: "#fbc02d", pane: "flow", series: ["chaikin_osc"], desc: "MACD construction (EMA3 - EMA10) applied to the Accumulation/Distribution line. Rising = money flowing in, falling = distribution." },
  { key: "vwma", token: "vwma", label: "VWMA 20", color: "#00acc1", pane: "overlay", series: ["vwma_20"], desc: "Volume-Weighted Moving Average: sum(close x volume) / sum(volume). High-volume sessions steer the average, unlike the flat SMA." },
  { key: "cvd", token: "cvd", label: "CVD (proxy)", color: "#c62828", pane: "flow", series: ["cvd"], desc: "Cumulative Volume Delta - daily close-to-close PROXY (ask/bid tick data is not published for NEPSE). Shows sustained one-sided participation, not tick-grade order flow." },
  // Support / resistance
  {
    key: "pivots",
    token: "pivots",
    label: "Pivot Points",
    color: "#5d4037",
    pane: "overlay",
    series: ["pivot_pp", "pivot_r1", "pivot_r2", "pivot_s1", "pivot_s2"],
    colors: { pivot_pp: "#5d4037", pivot_r1: "#c62828", pivot_r2: "#e57373", pivot_s1: "#2e7d32", pivot_s2: "#81c784" },
    desc: "Floor-trader pivots: P=(H+L+C)/3 of the previous session with R1-R3 / S1-S3 radiating outward. P is the balance level; breaks of R/S levels are traded as continuations.",
  },
  {
    key: "camarilla",
    token: "camarilla",
    label: "Camarilla Pivots",
    color: "#4527a0",
    pane: "overlay",
    series: ["cam_pp", "cam_r3", "cam_r4", "cam_s3", "cam_s4"],
    colors: { cam_pp: "#4527a0", cam_r3: "#e57373", cam_r4: "#c62828", cam_s3: "#81c784", cam_s4: "#2e7d32" },
    desc: "Eight bands at 1.1 x range/{12,6,4,2} around the close. R3/S3 are range-trade reversal zones, R4/S4 breakout levels - the 3rd/4th levels carry the system.",
  },
  {
    key: "woodie",
    token: "woodie",
    label: "Woodie's Pivots",
    color: "#0277bd",
    pane: "overlay",
    series: ["wpiv_pp", "wpiv_r1", "wpiv_s1"],
    colors: { wpiv_pp: "#0277bd", wpiv_r1: "#c62828", wpiv_s1: "#2e7d32" },
    desc: "Woodie's pivot weights the previous close double: P=(H+L+2C)/4. Same R/S geometry as the standard set, but momentum-weighted.",
  },
  {
    key: "demark",
    token: "demark",
    label: "DeMark Pivots",
    color: "#6d4c41",
    pane: "overlay",
    series: ["dpiv_pp", "dpiv_r1", "dpiv_s1"],
    colors: { dpiv_pp: "#6d4c41", dpiv_r1: "#c62828", dpiv_s1: "#2e7d32" },
    desc: "DeMark's projected expected high/low: X depends on whether the previous session closed above or below its open, then P=X/4, R1=X/2-L, S1=X/2-H.",
  },
  {
    key: "fib_retrace",
    token: "fib_retrace",
    label: "Fib Retracement",
    color: "#bf360c",
    pane: "overlay",
    series: ["fib_236", "fib_382", "fib_500", "fib_618", "fib_786"],
    colors: { fib_236: "#ffcc80", fib_382: "#ffb74d", fib_500: "#ffa726", fib_618: "#fb8c00", fib_786: "#f57c00" },
    desc: "Retracement levels of the visible swing at 23.6/38.2/50/61.8/78.6%. Pullbacks often stall at these ratios of the prior move before the trend resumes.",
  },
  {
    key: "fib_extension",
    token: "fib_extension",
    label: "Fib Extension",
    color: "#33691e",
    pane: "overlay",
    series: ["fibe_618", "fibe_1000", "fibe_1272", "fibe_1618", "fibe_2618"],
    colors: { fibe_618: "#aed581", fibe_1000: "#9ccc65", fibe_1272: "#8bc34a", fibe_1618: "#66bb6a", fibe_2618: "#43a047" },
    desc: "Extension targets at 61.8/100/127.2/161.8/261.8% of the swing, projected from the pullback point - where the trend may travel after the retracement ends.",
  },
  {
    key: "fib_fan",
    token: "fib_fan",
    label: "Fib Fan",
    color: "#795548",
    pane: "overlay",
    series: ["fibf_382", "fibf_500", "fibf_618"],
    colors: { fibf_382: "#bcaaa4", fibf_500: "#a1887f", fibf_618: "#8d6e63" },
    desc: "Diagonal fan lines from the swing start through 38.2/50/61.8% of the vertical move - sloped support/resistance that travels with time.",
  },
  // Advanced
  {
    key: "volume_profile",
    token: "volume_profile",
    label: "Volume Profile",
    color: "#00838f",
    pane: "overlay",
    series: ["vp_poc", "vp_va_high", "vp_va_low"],
    colors: { vp_poc: "#00838f", vp_va_high: "#4dd0e1", vp_va_low: "#4dd0e1" },
    desc: "Volume at each price level over the range (VPFR/VPVR share the computation): POC = the heaviest-traded price; value area = the 70% band around it. magnet in ranges, breakout zone outside.",
  },
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

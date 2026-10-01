/* Pure candle-colour logic, split out of TechnicalChart.tsx so the colour
 * contract has one testable home (see scripts/check-color-rule.mjs).
 *
 * The rule is a setting, not a guess:
 *   prev_close (default) - a candle is green when it closed above the
 *     previous session's close, matching the +/- change in the header and
 *     every table.
 *   open - green when it closed above its own open (intrabar direction).
 *
 * The two rules disagree on gap days, which is exactly what the tests pin
 * down. Colours come from the app's CSS variables so the chart follows the
 * topbar's green-up / red-up switch.
 */

import type { ColorRule } from "./colorRule";

export type { ColorRule };

export interface TrendPalette {
  up: string;
  down: string;
  flat: string;
}

/** Resolve the palette from the CSS variables (browser only). */
export function trendPalette(): TrendPalette {
  const cs = getComputedStyle(document.documentElement);
  const get = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback;
  return {
    up: get("--up", "#26a69a"),
    down: get("--down", "#ef5350"),
    flat: get("--flat", "#787b86"),
  };
}

/**
 * Sign -> colour. The only colour decision in the chart; body, wick and
 * volume bars all call this with the same value.
 */
export function changeColor(
  delta: number | null | undefined,
  pal: TrendPalette,
): string {
  if (delta == null || !Number.isFinite(delta) || delta === 0) return pal.flat;
  return delta > 0 ? pal.up : pal.down;
}

/** The comparison value a candle's close is judged against, per the rule. */
export function changeRef(
  rule: ColorRule,
  open: number,
  prevClose: number | null,
): number {
  // First visible bar has no previous session inside the window: fall back to
  // the intrabar rule for that one bar rather than inventing a close.
  return rule === "open" || prevClose == null ? open : prevClose;
}

/** #rgb / #rrggbb -> rgba() with alpha, used for volume bars. */
export function alpha(color: string, a: number): string {
  const c = color.trim();
  if (c.startsWith("#")) {
    if (c.length === 4) {
      return `rgba(${parseInt(c[1] + c[1], 16)},${parseInt(c[2] + c[2], 16)},${parseInt(c[3] + c[3], 16)},${a})`;
    }
    if (c.length === 7) {
      return `rgba(${parseInt(c.slice(1, 3), 16)},${parseInt(c.slice(3, 5), 16)},${parseInt(c.slice(5, 7), 16)},${a})`;
    }
  }
  return color;
}

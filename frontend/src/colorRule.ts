/* Candle colour rule (C2 of the chart fix).
 *
 * One rule decides every candle body, wick and volume bar on the chart, and
 * it is the same rule the header and tables use for their +/- change:
 *
 *   prev_close (default) - close vs the previous session's close. A candle is
 *     green when it closed above yesterday, red when below, grey when equal.
 *   open                 - close vs the same bar's open. Green when the day's
 *     trading ended above where it started, regardless of yesterday.
 *
 * The two rules disagree on gap days: open lower but recover above the open
 * yet still below yesterday's close is "open"-green and "prev_close"-red.
 * Store the choice per browser; the chart re-colours instantly on change.
 */

export type ColorRule = "prev_close" | "open";

export const COLOR_RULE_KEY = "chart-color-rule";
export const COLOR_RULE_EVENT = "tc-color-rule-change";

export const COLOR_RULE_LABELS: Record<ColorRule, string> = {
  prev_close:
    "Green when the close is above the previous session's close (matches the +/- change everywhere in the app).",
  open: "Green when the close is above the same candle's open (intrabar direction).",
};

/** Read the stored rule; anything unexpected falls back to prev_close. */
export function loadColorRule(): ColorRule {
  try {
    const raw = window.localStorage.getItem(COLOR_RULE_KEY);
    return raw === "open" ? "open" : "prev_close";
  } catch {
    return "prev_close";
  }
}

/** Persist the rule and announce it; the chart re-colours on the event. */
export function storeColorRule(rule: ColorRule): void {
  try {
    window.localStorage.setItem(COLOR_RULE_KEY, rule);
  } catch {
    // Storage optional: the event still updates the running chart.
  }
  window.dispatchEvent(new CustomEvent(COLOR_RULE_EVENT, { detail: rule }));
}

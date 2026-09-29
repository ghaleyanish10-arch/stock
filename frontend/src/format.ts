/* Number and date formatting.
 *
 * These only format values that are *known*. Anything unknown is handled by the
 * provenance renderer in `provenance.tsx`, which shows the reason instead of a
 * dash - so a bare "-" never appears from these helpers.
 */

const NBSP = "–"; // en dash, used for "not applicable to this row"

export function isMissing(value: number | null | undefined): boolean {
  return value === null || value === undefined || Number.isNaN(value);
}

export function fmtNum(value: number | null | undefined, digits = 2): string {
  if (isMissing(value)) return NBSP;
  return value!.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtInt(value: number | null | undefined): string {
  if (isMissing(value)) return NBSP;
  return value!.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

/** Compact NPR, e.g. `Rs 3.22B`. */
export function fmtRs(value: number | null | undefined): string {
  if (isMissing(value)) return NBSP;
  const v = value!;
  const abs = Math.abs(v);
  if (abs >= 1e9) return `Rs ${(v / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `Rs ${(v / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `Rs ${(v / 1e3).toFixed(1)}K`;
  return `Rs ${v.toFixed(2)}`;
}

export function fmtPct(value: number | null | undefined, digits = 2): string {
  if (isMissing(value)) return NBSP;
  const v = value!;
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

/** Signed value with an explicit + for gains, used for point change. */
export function fmtSigned(value: number | null | undefined, digits = 2): string {
  if (isMissing(value)) return NBSP;
  const v = value!;
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}`;
}

export function fmtDate(value: string | null | undefined): string {
  if (!value) return NBSP;
  return value.slice(0, 10);
}

/** "2026-09-24 15:00" -> "2026-09-24 15:00", trimmed to minutes. */
export function fmtDateTime(value: string | null | undefined): string {
  if (!value) return NBSP;
  return value.replace("T", " ").slice(0, 16);
}

export function fmtVolume(value: number | null | undefined): string {
  if (isMissing(value)) return NBSP;
  return value!.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

/** Trend class for a change value, using the NEPSE red-up / green-down rule. */
export function trendClass(value: number | null | undefined): string {
  if (isMissing(value) || value === 0) return "flat";
  return (value as number) > 0 ? "up" : "down";
}

/* -- Indian/Nepali number units ------------------------------------------- */

export type UnitScale = "default" | "thousands" | "lakhs" | "crore" | "arba";

export interface UnitOption {
  value: UnitScale;
  label: string;
  suffix: string;
  /** How much to divide by. 1 for `default`. */
  divisor: number;
}

/**
 * South Asian number units, which Nepali finance uses natively.
 *
 * Arba (1e9) = 100 crore, crore (1e7) = 100 lakh, lakh (1e5) = 100 thousand.
 * "Default" leaves the number untouched with thousands separators, which is
 * what a spreadsheet comparison needs.
 */
export const UNIT_OPTIONS: UnitOption[] = [
  { value: "default", label: "Default", suffix: "", divisor: 1 },
  { value: "thousands", label: "Thousands", suffix: "K", divisor: 1e3 },
  { value: "lakhs", label: "Lakhs", suffix: "L", divisor: 1e5 },
  { value: "crore", label: "Crore", suffix: "Cr", divisor: 1e7 },
  { value: "arba", label: "Arba", suffix: "Ar", divisor: 1e9 },
];

/**
 * Format a value in the chosen unit. Missing stays missing - the switch never
 * turns an unknown into a 0.00.
 */
export function fmtUnit(
  value: number | null | undefined,
  unit: UnitScale,
  digits = 2,
): string {
  if (isMissing(value)) return NBSP;
  const opt = UNIT_OPTIONS.find((o) => o.value === unit) ?? UNIT_OPTIONS[0];
  const scaled = (value as number) / opt.divisor;
  const num = scaled.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return opt.suffix ? `${num} ${opt.suffix}` : num;
}

/* Provenance rendering.
 *
 * This is where the None-versus-zero contract becomes visible. The old UI
 * printed a bare dash for every `null`, which made "NEPSE does not publish
 * mutual fund NAV" look identical to "we failed to fetch it" and identical to
 * "not enough history yet".
 *
 * `<MeasuredValue>` renders a `Measured` as:
 *   - the formatted number, when there is one
 *   - the backend's own wording for the status, when there is not
 *   - a tooltip explaining the reason, the as-of time and the source
 *
 * The wording comes from the backend (`ValueStatus` -> label) rather than being
 * invented here, so every screen says the same thing.
 */

import type { ReactNode } from "react";
import type { Measured, ValueStatus } from "./types";
import { fmtNum, fmtPct, fmtRs, isMissing } from "./format";

/** Mirrors `STATUS_LABEL` in app/core/provenance.py. */
const STATUS_LABEL: Record<ValueStatus, string> = {
  ok: "",
  declared_zero: "Declared as zero",
  not_reported: "Not declared yet",
  not_published: "Not published by source",
  upstream_unavailable: "Data unavailable",
  not_applicable: "Not applicable",
  pending: "Not declared yet",
};

/** Mirrors `STATUS_EXPLANATION` in app/core/provenance.py. */
const STATUS_EXPLANATION: Record<ValueStatus, string> = {
  ok: "",
  declared_zero:
    "The source reported an explicit zero. This is a real declared value, not missing data.",
  not_reported: "The source has this field but has not filled it in for this entity.",
  not_published: "The source does not publish this field at all, so it cannot be known.",
  upstream_unavailable: "The upstream source could not be reached. This is usually temporary.",
  not_applicable: "The value does not apply to this entity.",
  pending: "This has not been announced yet.",
};

/** Chip colour class per status. */
const STATUS_TONE: Record<ValueStatus, string> = {
  ok: "st-ok",
  declared_zero: "st-zero",
  not_reported: "st-missing",
  not_published: "st-missing",
  upstream_unavailable: "st-warn",
  not_applicable: "st-missing",
  pending: "st-missing",
};

export type MeasuredFormat = "number" | "percent" | "currency" | "integer" | "raw";

function format(value: number | null, format: MeasuredFormat): string {
  switch (format) {
    case "percent":
      return fmtPct(value);
    case "currency":
      return fmtRs(value);
    case "integer":
      return fmtNum(value, 0);
    case "raw":
      return value === null ? "–" : String(value);
    default:
      return fmtNum(value, 2);
  }
}

export function explain(measured: Measured): string {
  const parts: string[] = [];
  const expl = STATUS_EXPLANATION[measured.status];
  if (expl) parts.push(expl);
  if (measured.note) parts.push(measured.note);
  if (measured.as_of) parts.push(`Source timestamp: ${measured.as_of}.`);
  if (measured.source) parts.push(`Via ${measured.source}.`);
  return parts.join(" ") || "No provenance information available.";
}

export interface MeasuredValueProps {
  measured: Measured | null | undefined;
  format?: MeasuredFormat;
  /** Show the status chip even when a number is present (e.g. a declared zero). */
  alwaysShowStatus?: boolean;
  className?: string;
}

/**
 * Render a `Measured` value.
 *
 * A `declared_zero` still shows `0.00`, but is tagged, so a real zero is never
 * mistaken for missing data.
 */
export function MeasuredValue({
  measured,
  format: fmt = "number",
  alwaysShowStatus = false,
  className,
}: MeasuredValueProps) {
  if (!measured) {
    return <span className={`mv mv-missing ${className ?? ""}`}>Not loaded</span>;
  }

  const { value, status } = measured;

  if (isMissing(value)) {
    const label = STATUS_LABEL[status] ?? "Unavailable";
    return (
      <span className={`mv mv-chip ${STATUS_TONE[status]}`} title={explain(measured)}>
        {label}
      </span>
    );
  }

  return (
    <span className={`mv ${className ?? ""}`} title={explain(measured)}>
      {format(value, fmt)}
      {(alwaysShowStatus || status === "declared_zero") && (
        <span className={`mv-chip mv-chip-inline ${STATUS_TONE[status]}`}>
          {STATUS_LABEL[status]}
        </span>
      )}
    </span>
  );
}

/**
 * Render a raw nullable number that has no `Measured` wrapper, using a neutral
 * placeholder. Used for fields the API returns as bare nulls (e.g. a bar's
 * `market_cap` when listed shares are unknown).
 */
export function Nullable({
  value,
  format: fmt = "number",
  reason,
  className,
}: {
  value: number | null | undefined;
  format?: MeasuredFormat;
  reason?: string;
  className?: string;
}) {
  if (isMissing(value)) {
    return (
      <span className={`mv mv-chip st-missing ${className ?? ""}`} title={reason}>
        {reason ?? "Not available"}
      </span>
    );
  }
  return <span className={className}>{format(value!, fmt)}</span>;
}

/** A small legend explaining the provenance chips, shown on data-heavy pages. */
export function ProvenanceLegend() {
  return (
    <div className="legend">
      <span className="legend-title">Value meanings</span>
      <span className="mv-chip st-ok">Measured</span>
      <span className="mv-chip st-zero">Declared as zero</span>
      <span className="mv-chip st-missing">Not declared yet</span>
      <span className="mv-chip st-missing">Not published by source</span>
      <span className="mv-chip st-warn">Data unavailable</span>
    </div>
  );
}

/** Card wrapper with an optional explanation line. */
export function Stat({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{children}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

/* Screener: price, volume and technical filters over the local archive.
 *
 * Two rules shape the whole page:
 *
 * 1. A null is never a zero and never a bare dash. Rows carry a `reasons` map
 *    from the API explaining every missing cell, and the page surfaces that. A
 *    filter that needs a value a row lacks excludes the row and *says how many*
 *    were excluded, because otherwise a thin result set looks like a quiet
 *    market rather than a coverage gap.
 * 2. Fundamentals and earnings controls are visible but disabled, with the
 *    reason on the control itself. Hiding them would imply they do not exist;
 *    showing them as active would be a lie, since NEPSE publishes neither.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { analytics, reference } from "../api";
import type { ScreenerRow } from "../types";
import {
  UNIT_OPTIONS,
  fmtInt,
  fmtNum,
  fmtPct,
  fmtUnit,
  isMissing,
  type UnitScale,
} from "../format";
import { Card, EmptyState, ErrorState, Loading } from "../components/ui";

/* -- filter state --------------------------------------------------------- */

/** One configurable numeric filter. `null` means "not applied". */
interface Bound {
  min: number | null;
  max: number | null;
}

const emptyBound = (): Bound => ({ min: null, max: null });

type FilterState = {
  sector: string;
  ltp: Bound;
  market_cap: Bound;
  change_pct: Bound;
  volume: Bound;
  turnover: Bound;
  ret_5d: Bound;
  ret_1m: Bound;
  ret_3m: Bound;
  ret_6m: Bound;
  ret_1y: Bound;
  ret_ytd: Bound;
  rsi_14: Bound;
  day_low: Bound;
  day_high: Bound;
  above_vwap: "any" | "above" | "below";
};

const initialFilters = (): FilterState => ({
  sector: "",
  ltp: emptyBound(),
  market_cap: emptyBound(),
  change_pct: emptyBound(),
  volume: emptyBound(),
  turnover: emptyBound(),
  ret_5d: emptyBound(),
  ret_1m: emptyBound(),
  ret_3m: emptyBound(),
  ret_6m: emptyBound(),
  ret_1y: emptyBound(),
  ret_ytd: emptyBound(),
  rsi_14: emptyBound(),
  day_low: emptyBound(),
  day_high: emptyBound(),
  above_vwap: "any",
});

/* -- column model --------------------------------------------------------- */

type Align = "num" | "text";

interface Column {
  field: keyof ScreenerRow | "symbol";
  label: string;
  align: Align;
  unit?: UnitScale;
  /** Render function; a null result renders the reason. */
  render: (row: ScreenerRow, unit: UnitScale) => string | null;
  defaultVisible: boolean;
}

const COLUMNS: Column[] = [
  {
    field: "symbol",
    label: "Symbol",
    align: "text",
    defaultVisible: true,
    render: (r) => r.symbol,
  },
  {
    field: "name",
    label: "Name",
    align: "text",
    defaultVisible: true,
    render: (r) => r.name,
  },
  {
    field: "sector",
    label: "Sector",
    align: "text",
    defaultVisible: true,
    render: (r) => r.sector,
  },
  {
    field: "ltp",
    label: "LTP",
    align: "num",
    defaultVisible: true,
    render: (r) => (isMissing(r.ltp) ? null : fmtNum(r.ltp)),
  },
  {
    field: "change_pct",
    label: "Change %",
    align: "num",
    defaultVisible: true,
    render: (r) => (isMissing(r.change_pct) ? null : fmtPct(r.change_pct)),
  },
  {
    field: "market_cap",
    label: "Market cap",
    align: "num",
    unit: "default",
    defaultVisible: true,
    render: (r, u) => (isMissing(r.market_cap) ? null : fmtUnit(r.market_cap, u, 2)),
  },
  {
    field: "volume",
    label: "Volume",
    align: "num",
    unit: "default",
    defaultVisible: true,
    render: (r, u) => (isMissing(r.volume) ? null : fmtUnit(r.volume, u, 0)),
  },
  {
    field: "turnover",
    label: "Turnover",
    align: "num",
    unit: "default",
    defaultVisible: true,
    render: (r, u) => (isMissing(r.turnover) ? null : fmtUnit(r.turnover, u, 2)),
  },
  { field: "ret_5d", label: "5D", align: "num", defaultVisible: true, render: (r) => pct(r.ret_5d) },
  { field: "ret_1m", label: "1M", align: "num", defaultVisible: true, render: (r) => pct(r.ret_1m) },
  { field: "ret_3m", label: "3M", align: "num", defaultVisible: false, render: (r) => pct(r.ret_3m) },
  { field: "ret_6m", label: "6M", align: "num", defaultVisible: false, render: (r) => pct(r.ret_6m) },
  { field: "ret_1y", label: "1Y", align: "num", defaultVisible: false, render: (r) => pct(r.ret_1y) },
  { field: "ret_ytd", label: "YTD", align: "num", defaultVisible: false, render: (r) => pct(r.ret_ytd) },
  {
    field: "vwap_180d",
    label: "180D VWAP",
    align: "num",
    defaultVisible: true,
    render: (r) => (isMissing(r.vwap_180d) ? null : fmtNum(r.vwap_180d)),
  },
  {
    field: "rsi_14",
    label: "RSI (14)",
    align: "num",
    defaultVisible: true,
    render: (r) => (isMissing(r.rsi_14) ? null : fmtNum(r.rsi_14, 1)),
  },
  {
    field: "day_high",
    label: "Day high",
    align: "num",
    defaultVisible: false,
    render: (r) => (isMissing(r.day_high) ? null : fmtNum(r.day_high)),
  },
  {
    field: "day_low",
    label: "Day low",
    align: "num",
    defaultVisible: false,
    render: (r) => (isMissing(r.day_low) ? null : fmtNum(r.day_low)),
  },
];

function pct(value: number | null): string | null {
  return isMissing(value) ? null : fmtPct(value);
}

const DEFAULT_VISIBLE = COLUMNS.filter((c) => c.defaultVisible).map((c) => String(c.field));

/* -- saved parameter sets ------------------------------------------------- */

const SAVED_KEY = "sa.screener.sets";

interface SavedSet {
  name: string;
  filters: FilterState;
  columns: string[];
  unit: UnitScale;
  savedAt: string;
}

function loadSaved(): SavedSet[] {
  try {
    const raw = window.localStorage.getItem(SAVED_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as SavedSet[]) : [];
  } catch {
    return [];
  }
}

function persistSaved(sets: SavedSet[]): void {
  try {
    window.localStorage.setItem(SAVED_KEY, JSON.stringify(sets));
  } catch {
    /* storage blocked: saved sets are a convenience, not a requirement */
  }
}

/* -- CSV / Excel export --------------------------------------------------- */

function toCsv(rows: ScreenerRow[], columns: Column[], unit: UnitScale): string {
  const head = columns.map((c) => `"${c.label}"`).join(",");
  const body = rows
    .map((row) =>
      columns
        .map((c) => {
          const v = c.render(row, unit);
          // A missing cell exports as empty, and the reason is not smuggled into
          // the file as if it were data.
          return v === null ? "" : `"${v.replace(/"/g, '""')}"`;
        })
        .join(","),
    )
    .join("\n");
  return `${head}\n${body}\n`;
}

/**
 * SpreadsheetML 2003 (.xls). Chosen over .xlsx deliberately: a real .xlsx is a
 * ZIP of XML parts, which would need a writer dependency for a single export
 * button. Excel, LibreOffice and Sheets all open this format natively, and the
 * MIME type is what makes the browser offer "Download".
 */
function toExcelXml(rows: ScreenerRow[], columns: Column[], unit: UnitScale): string {
  const cell = (v: string | number | null) => {
    if (v === null) return '<Cell ss:StyleID="missing"/>';
    if (typeof v === "number") return `<Cell><Data ss:Type="Number">${v}</Data></Cell>`;
    return `<Cell><Data ss:Type="String">${v
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")}</Data></Cell>`;
  };
  const header = `<Row>${columns
    .map((c) => `<Cell ss:StyleID="hdr"><Data ss:Type="String">${c.label}</Data></Cell>`)
    .join("")}</Row>`;
  const body = rows
    .map(
      (r) =>
        `<Row>${columns
          .map((c) => {
            const rendered = c.render(r, unit);
            return cell(rendered === null ? null : Number.isNaN(Number(rendered)) ? rendered : Number(rendered));
          })
          .join("")}</Row>`,
    )
    .join("");
  return `<?xml version="1.0"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
<Styles><Style ss:ID="hdr"><Font ss:Bold="1"/></Style>
<Style ss:ID="missing"><Font ss:Color="#888888"/></Style></Styles>
<Worksheet ss:Name="Screener"><Table>${header}${body}</Table></Worksheet>
</Workbook>`;
}

function download(filename: string, mime: string, content: string): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Revoke on the next tick: revoking synchronously can cancel the download in
  // some browsers before it has read the blob.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/* -- page ----------------------------------------------------------------- */

export function ScreenerPage() {
  const [params, setParams] = useSearchParams();
  const [filters, setFilters] = useState<FilterState>(initialFilters);
  const [sort, setSort] = useState("market_cap");
  const [descending, setDescending] = useState(true);
  const [unit, setUnit] = useState<UnitScale>("default");
  const [visible, setVisible] = useState<string[]>(DEFAULT_VISIBLE);
  const [saved, setSaved] = useState<SavedSet[]>(loadSaved);
  const [setName, setSetName] = useState("");
  const [showColumns, setShowColumns] = useState(false);

  // A sector chosen on the market map deep-links in.
  useEffect(() => {
    const sector = params.get("sector");
    if (sector) setFilters((f) => ({ ...f, sector }));
  }, [params]);

  const query = useMemo(() => {
    const q: Record<string, string | number | boolean> = {
      sort,
      descending,
      limit: 250,
    };
    const put = (key: string, b: Bound) => {
      if (b.min !== null) q[`min_${key}`] = b.min;
      if (b.max !== null) q[`max_${key}`] = b.max;
    };
    if (filters.sector) q.sector = filters.sector;
    put("ltp", filters.ltp);
    put("market_cap", filters.market_cap);
    put("change_pct", filters.change_pct);
    put("volume", filters.volume);
    put("turnover", filters.turnover);
    put("ret_5d", filters.ret_5d);
    put("ret_1m", filters.ret_1m);
    put("ret_3m", filters.ret_3m);
    put("ret_6m", filters.ret_6m);
    put("ret_1y", filters.ret_1y);
    put("ret_ytd", filters.ret_ytd);
    put("rsi_14", filters.rsi_14);
    put("day_low", filters.day_low);
    put("day_high", filters.day_high);
    if (filters.above_vwap !== "any") q.above_vwap_180d = filters.above_vwap === "above";
    return q;
  }, [filters, sort, descending]);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["screener", query],
    queryFn: ({ signal }) => analytics.screener(query, signal),
  });

  const { data: sectorData } = useQuery({
    queryKey: ["sectors"],
    queryFn: ({ signal }) => reference.sectors(signal),
  });

  const columns = useMemo(
    () => COLUMNS.filter((c) => visible.includes(String(c.field))),
    [visible],
  );

  const activeCount = useMemo(() => {
    let n = 0;
    if (filters.sector) n += 1;
    if (filters.above_vwap !== "any") n += 1;
    (Object.keys(filters) as (keyof FilterState)[]).forEach((k) => {
      const v = filters[k];
      if (v && typeof v === "object" && "min" in v && (v.min !== null || v.max !== null)) n += 1;
    });
    return n;
  }, [filters]);

  const setBound = useCallback(
    (key: keyof FilterState, side: "min" | "max", raw: string) => {
      const text = raw.trim();
      const value = text === "" ? null : Number(text);
      setFilters((f) => {
        const current = f[key] as Bound;
        return { ...f, [key]: { ...current, [side]: value } };
      });
    },
    [],
  );

  const clearAll = useCallback(() => {
    setFilters(initialFilters());
    const next = new URLSearchParams(params);
    next.delete("sector");
    setParams(next, { replace: true });
  }, [params, setParams]);

  const saveSet = useCallback(() => {
    const name = setName.trim();
    if (!name) return;
    const next = [...saved.filter((s) => s.name !== name), {
      name,
      filters,
      columns: visible,
      unit,
      savedAt: new Date().toISOString(),
    }];
    setSaved(next);
    persistSaved(next);
    setSetName("");
  }, [setName, saved, filters, visible, unit]);

  const loadSet = useCallback((set: SavedSet) => {
    setFilters(set.filters);
    setVisible(set.columns);
    setUnit(set.unit);
  }, []);

  const deleteSet = useCallback((name: string) => {
    const next = saved.filter((s) => s.name !== name);
    setSaved(next);
    persistSaved(next);
  }, [saved]);

  const toggleColumn = (field: string) => {
    setVisible((v) =>
      v.includes(field) ? v.filter((f) => f !== field) : [...v, field],
    );
  };

  const stamp = new Date().toISOString().slice(0, 10);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Screener</h1>
          <p className="page-sub">
            Price, volume and technical filters over the local archive. No
            fundamentals: NEPSE publishes none.
          </p>
        </div>
        <div className="page-head-actions">
          <label className="field">
            <span className="field-label">Units</span>
            <select
              className="select"
              value={unit}
              onChange={(e) => setUnit(e.target.value as UnitScale)}
            >
              {UNIT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => setShowColumns((s) => !s)}
            aria-expanded={showColumns}
          >
            Columns ({visible.length}/{COLUMNS.length})
          </button>
        </div>
      </header>

      {/* -- filter bar -- */}
      <Card
        title={`Filters${activeCount ? ` (${activeCount} active)` : ""}`}
        actions={
          <>
            <button type="button" className="btn btn-sm btn-primary" onClick={() => {}} disabled>
              Apply filters
            </button>
            <button type="button" className="btn btn-sm" onClick={clearAll} disabled={activeCount === 0}>
              Clear all
            </button>
          </>
        }
      >
        <div className="filters">
          <label className="field">
            <span className="field-label">Sector</span>
            <select
              className="select"
              value={filters.sector}
              onChange={(e) => setFilters((f) => ({ ...f, sector: e.target.value }))}
            >
              <option value="">All sectors</option>
              {sectorData?.sectors.map((s) => (
                <option key={s.code} value={s.name}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>

          <RangeFilter
            label="LTP"
            unit="Rs"
            value={filters.ltp}
            onChange={(side, v) => setBound("ltp", side, v)}
          />
          <RangeFilter
            label="Market cap"
            unit={unit === "default" ? "Rs" : unit}
            value={filters.market_cap}
            onChange={(side, v) => setBound("market_cap", side, v)}
          />
          <RangeFilter
            label="Change %"
            unit="%"
            value={filters.change_pct}
            onChange={(side, v) => setBound("change_pct", side, v)}
          />
          <RangeFilter
            label="Volume"
            unit={unit === "default" ? "shares" : unit}
            value={filters.volume}
            onChange={(side, v) => setBound("volume", side, v)}
          />
          <RangeFilter
            label="Turnover"
            unit={unit === "default" ? "Rs" : unit}
            value={filters.turnover}
            onChange={(side, v) => setBound("turnover", side, v)}
          />
          <RangeFilter label="5D %" unit="%" value={filters.ret_5d} onChange={(s, v) => setBound("ret_5d", s, v)} />
          <RangeFilter label="1M %" unit="%" value={filters.ret_1m} onChange={(s, v) => setBound("ret_1m", s, v)} />
          <RangeFilter label="3M %" unit="%" value={filters.ret_3m} onChange={(s, v) => setBound("ret_3m", s, v)} />
          <RangeFilter label="6M %" unit="%" value={filters.ret_6m} onChange={(s, v) => setBound("ret_6m", s, v)} />
          <RangeFilter label="1Y %" unit="%" value={filters.ret_1y} onChange={(s, v) => setBound("ret_1y", s, v)} />
          <RangeFilter label="YTD %" unit="%" value={filters.ret_ytd} onChange={(s, v) => setBound("ret_ytd", s, v)} />
          <RangeFilter
            label="RSI (14)"
            unit=""
            value={filters.rsi_14}
            onChange={(s, v) => setBound("rsi_14", s, v)}
          />
          <RangeFilter
            label="Day low"
            unit="Rs"
            value={filters.day_low}
            onChange={(s, v) => setBound("day_low", s, v)}
          />
          <RangeFilter
            label="Day high"
            unit="Rs"
            value={filters.day_high}
            onChange={(s, v) => setBound("day_high", s, v)}
          />

          <label className="field">
            <span className="field-label">vs 180D VWAP</span>
            <select
              className="select"
              value={filters.above_vwap}
              onChange={(e) =>
                setFilters((f) => ({
                  ...f,
                  above_vwap: e.target.value as FilterState["above_vwap"],
                }))
              }
            >
              <option value="any">Any</option>
              <option value="above">LTP above VWAP</option>
              <option value="below">LTP below VWAP</option>
            </select>
          </label>
        </div>

        {/* -- the disabled fundamentals group -- */}
        <fieldset className="filters-disabled" disabled>
          <legend>Fundamentals (not available)</legend>
          <p className="hint">
            {data?.fundamentals.reason ??
              "No fundamentals provider is configured. NEPSE publishes no reliable fundamentals API, so these filters are not offered rather than being filled with guesses."}
          </p>
          <div className="filters">
            <label className="field">
              <span className="field-label">P/E</span>
              <input className="input" type="number" placeholder="disabled" disabled />
            </label>
            <label className="field">
              <span className="field-label">EPS</span>
              <input className="input" type="number" placeholder="disabled" disabled />
            </label>
            <label className="field">
              <span className="field-label">ROE %</span>
              <input className="input" type="number" placeholder="disabled" disabled />
            </label>
            <label className="field">
              <span className="field-label">Book value</span>
              <input className="input" type="number" placeholder="disabled" disabled />
            </label>
          </div>
        </fieldset>

        <fieldset className="filters-disabled" disabled>
          <legend>Earnings (not available)</legend>
          <p className="hint">
            {data?.earnings.reason ??
              "NEPSE publishes no earnings calendar or results feed, so quarterly earnings filters are disabled."}
          </p>
          <div className="filters">
            <label className="field">
              <span className="field-label">Next results within</span>
              <select className="select" disabled>
                <option>disabled</option>
              </select>
            </label>
          </div>
        </fieldset>
      </Card>

      {/* -- saved parameter sets -- */}
      <Card title="Saved parameter sets">
        <div className="saved-row">
          <label className="field">
            <span className="field-label">Save current filters as</span>
            <input
              className="input"
              value={setName}
              placeholder="e.g. Big banks, RSI 40-60"
              onChange={(e) => setSetName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") saveSet();
              }}
            />
          </label>
          <button type="button" className="btn" onClick={saveSet} disabled={!setName.trim()}>
            Save
          </button>
        </div>
        {saved.length > 0 && (
          <ul className="saved-list">
            {saved.map((s) => (
              <li key={s.name}>
                <button type="button" className="btn btn-sm" onClick={() => loadSet(s)}>
                  {s.name}
                </button>
                <span className="hint">{s.savedAt.slice(0, 10)}</span>
                <button
                  type="button"
                  className="btn btn-sm btn-danger"
                  onClick={() => deleteSet(s.name)}
                  aria-label={`Delete saved set ${s.name}`}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {showColumns && (
        <Card title="Visible columns">
          <div className="column-toggles">
            {COLUMNS.map((c) => (
              <label key={String(c.field)} className="checkbox">
                <input
                  type="checkbox"
                  checked={visible.includes(String(c.field))}
                  onChange={() => toggleColumn(String(c.field))}
                />
                <span>{c.label}</span>
              </label>
            ))}
          </div>
        </Card>
      )}

      {isLoading && <Loading label="Screening the archive" />}
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}

      {data && !isLoading && (
        <>
          <div className="result-bar">
            <span>
              <strong>{fmtInt(data.total)}</strong> of {fmtInt(data.coverage.sessions)} sessions
              {data.total !== data.rows.length && ` (showing ${data.rows.length})`}
            </span>
            {data.rejected_by.length > 0 && (
              <span className="hint">
                Filtered out:{" "}
                {data.rejected_by.map((r) => `${r.count} by ${r.field}`).join(", ")}.
              </span>
            )}
            {data.undecidable.map((u) => (
              <span key={u.field} className="hint warn-text">
                {u.reason}
              </span>
            ))}
            <span className="spacer" />
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() =>
                download(
                  `nepse-screener-${stamp}.csv`,
                  "text/csv;charset=utf-8",
                  toCsv(data.rows, columns, unit),
                )
              }
              disabled={data.rows.length === 0}
            >
              Export CSV
            </button>
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() =>
                download(
                  `nepse-screener-${stamp}.xls`,
                  "application/vnd.ms-excel",
                  toExcelXml(data.rows, columns, unit),
                )
              }
              disabled={data.rows.length === 0}
            >
              Export Excel
            </button>
          </div>

          {data.rows.length === 0 ? (
            <EmptyState message="No security matches these filters. Loosen a bound, or clear the filters and start again." />
          ) : (
            <Card padded={false}>
              <div className="table-scroll">
                <table className="table table-dense">
                  <thead>
                    <tr>
                      {columns.map((c) => (
                        <th
                          key={String(c.field)}
                          scope="col"
                          className={c.align === "num" ? "num sortable" : "sortable"}
                          onClick={() => {
                            if (sort === c.field) setDescending((d) => !d);
                            else {
                              setSort(String(c.field));
                              setDescending(c.align === "num");
                            }
                          }}
                          aria-sort={
                            sort === c.field
                              ? descending
                                ? "descending"
                                : "ascending"
                              : "none"
                          }
                        >
                          {c.label}
                          {sort === c.field ? (descending ? " v" : " ^") : ""}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.map((row) => (
                      <tr key={row.symbol}>
                        {columns.map((c) => {
                          const raw = c.render(row, unit);
                          const isChange = c.field === "change_pct" || String(c.field).startsWith("ret_");
                          return (
                            <td
                              key={String(c.field)}
                              className={
                                c.align === "num"
                                  ? `num ${isChange && raw ? (Number(String(raw).replace(/[+%]/g, "")) >= 0 ? "up" : "down") : ""}`
                                  : ""
                              }
                            >
                              {raw === null ? (
                                <span
                                  className="mv mv-missing"
                                  title={row.reasons[String(c.field)] ?? "Not available"}
                                >
                                  {row.reasons[String(c.field)] ?? "Not available"}
                                </span>
                              ) : c.field === "symbol" ? (
                                <a href={`/chart/${row.symbol}`}>{raw}</a>
                              ) : (
                                raw
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

function RangeFilter({
  label,
  unit,
  value,
  onChange,
}: {
  label: string;
  unit: string;
  value: Bound;
  onChange: (side: "min" | "max", value: string) => void;
}) {
  const id = `f-${label.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`;
  return (
    <fieldset className="range-filter">
      <legend className="field-label">
        {label}
        {unit ? <span className="field-unit"> {unit}</span> : null}
      </legend>
      <div className="range-inputs">
        <input
          id={`${id}-min`}
          className="input"
          type="number"
          inputMode="decimal"
          placeholder="min"
          aria-label={`${label} minimum`}
          value={value.min ?? ""}
          onChange={(e) => onChange("min", e.target.value)}
        />
        <span className="range-dash" aria-hidden="true">
          -
        </span>
        <input
          id={`${id}-max`}
          className="input"
          type="number"
          inputMode="decimal"
          placeholder="max"
          aria-label={`${label} maximum`}
          value={value.max ?? ""}
          onChange={(e) => onChange("max", e.target.value)}
        />
      </div>
    </fieldset>
  );
}

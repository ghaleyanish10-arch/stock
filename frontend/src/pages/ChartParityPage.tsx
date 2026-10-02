/* Chart parity helper (B5): compare our chart payload against NEPSE's own
 * daily table, row by row.
 *
 * How to use: pick a symbol and the same date window you are looking at on
 * NEPSE, paste NEPSE's daily table (Date Open High Low Close Volume — the
 * parser tolerates commas, pipes and dd/mm/yyyy), and every row is diffed
 * against the exact payload the chart above renders. A green cell means the
 * value matches to the paisa; red means it does not; grey means that field is
 * missing on one side. Prices are compared on the as_traded basis by default
 * because that is what NEPSE's table quotes.
 *
 * This is a dev page: it is not linked from the nav. `window.__tcChart` (set
 * by the chart component in dev builds) allows console-level poking too.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { analytics } from "../api";
import { Card, ErrorState, Loading } from "../components/ui";
import { TechnicalChart } from "../components/TechnicalChart";
import { fmtInt, fmtNum } from "../format";
import type { ChartSeries } from "../types";

const RANGES = ["1W", "1M", "3M", "6M", "YTD", "1Y", "ALL"] as const;

interface NepseRow {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
}

/** ok: true = matches, false = mismatch, null = cannot compare (missing side). */
interface DiffCell {
  nepse: number | null;
  ours: number | null;
  ok: boolean | null;
}

interface DiffRow {
  nepse: NepseRow;
  cells: [DiffCell, DiffCell, DiffCell, DiffCell, DiffCell];
  /** All comparable cells match (null when nothing was comparable). */
  ok: boolean | null;
  /** "not-in-window" when the date is absent from our fetched payload. */
  missing: boolean;
}

/** "2026/09/30", "2026.09.30" -> ISO; "30/09/2026" -> ISO, day-first. */
function normDate(token: string): string | null {
  let m = /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/.exec(token);
  if (m) {
    return `${m[1]}-${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}`;
  }
  m = /^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$/.exec(token);
  if (m) {
    const a = Number(m[1]);
    const b = Number(m[2]);
    // NEPSE writes dd/mm/yyyy; disambiguate only when one side proves it.
    const day = a > 12 ? a : b > 12 ? b : a;
    const month = a > 12 ? b : b > 12 ? a : b;
    return `${m[3]}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  }
  return null;
}

function parseNumber(token: string): number | null {
  if (/^-?\d+(\.\d+)?$/.test(token)) return Number(token);
  return null; // "-", "—", headers, anything else
}

/** Parse one pasted line. Returns [row, null] or [null, skipReason]. */
function parseLine(raw: string): [NepseRow, null] | [null, string] {
  // Kill thousand separators first: "4,919.70" and "1,234,567" -> plain digits.
  const line = raw.replace(/(\d),(\d)/g, "$1$2");
  const tokens = line.split(/[\s|;]+/).filter(Boolean);
  if (!tokens.length) return [null, "empty"];

  let date: string | null = null;
  const numbers: number[] = [];
  for (const tok of tokens) {
    const d = normDate(tok);
    if (d && !date) {
      date = d;
      continue;
    }
    const n = parseNumber(tok);
    if (n !== null) numbers.push(n);
  }
  if (!date) return [null, numbers.length ? "no date" : "header or prose"];
  if (numbers.length < 4) return [null, "fewer than 4 numbers"];

  const [open, high, low, close, volume = null] = numbers;
  return [
    { date, open, high, low, close, volume },
    null,
  ];
}

export function parseNepseTable(text: string): { rows: NepseRow[]; skipped: number } {
  const rows: NepseRow[] = [];
  let skipped = 0;
  for (const raw of text.split(/\r?\n/)) {
    if (!raw.trim()) continue;
    const [row, why] = parseLine(raw);
    if (row) rows.push(row);
    else if (why !== "empty" && why !== "header or prose") skipped += 1;
  }
  return { rows, skipped };
}

/** Price tolerance: one paisa covers 1dp-vs-2dp rounding; volume is relative. */
function cell(nepse: number | null, ours: number | null, isVolume = false): DiffCell {
  if (nepse === null || ours === null) return { nepse, ours, ok: null };
  const tol = isVolume ? Math.max(1, Math.abs(nepse) * 0.005) : 0.011;
  return { nepse, ours, ok: Math.abs(nepse - ours) <= tol };
}

export function buildDiffs(rows: NepseRow[], series: ChartSeries): DiffRow[] {
  const byDate = new Map<string, { o: number | null; h: number | null; l: number | null; c: number | null; v: number | null }>();
  series.dates.forEach((d, i) => {
    byDate.set(d, {
      o: series.open[i] ?? null,
      h: series.high[i] ?? null,
      l: series.low[i] ?? null,
      c: series.close[i] ?? null,
      v: series.volume[i] ?? null,
    });
  });

  return rows.map((n) => {
    const bar = byDate.get(n.date);
    if (!bar) {
      return {
        nepse: n,
        cells: [null, null, null, null, null] as unknown as [DiffCell, DiffCell, DiffCell, DiffCell, DiffCell],
        ok: null,
        missing: true,
      };
    }
    const cells: [DiffCell, DiffCell, DiffCell, DiffCell, DiffCell] = [
      cell(n.open, bar.o),
      cell(n.high, bar.h),
      cell(n.low, bar.l),
      cell(n.close, bar.c),
      cell(n.volume, bar.v, true),
    ];
    const comparable = cells.filter((c) => c.ok !== null);
    const ok = comparable.length === 0 ? null : comparable.every((c) => c.ok === true);
    return { nepse: n, cells, ok, missing: false };
  });
}

export function ChartParityPage() {
  const [params, setParams] = useSearchParams();
  const symbol = (params.get("symbol") ?? "ANLB").toUpperCase();
  const range = params.get("range") ?? "3M";
  const basis = params.get("basis") ?? "as_traded";

  const [paste, setPaste] = useState("");
  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    setParams(next, { replace: true });
  };

  const query = useQuery({
    queryKey: ["chart-parity", symbol, range, basis],
    queryFn: ({ signal }) => analytics.chart(symbol, { range, basis, indicators: "none" }, signal),
  });

  const series = query.data?.series;
  const { rows, skipped } = useMemo(() => parseNepseTable(paste), [paste]);
  const diffs = useMemo(() => (series && rows.length ? buildDiffs(rows, series) : []), [rows, series]);

  const matched = diffs.filter((d) => d.ok === true).length;
  const mismatched = diffs.filter((d) => d.ok === false).length;
  const notInWindow = diffs.filter((d) => d.missing).length;
  const incomparable = diffs.filter((d) => d.ok === null && !d.missing).length;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Chart parity</h1>
          <p className="page-sub">
            Dev page — paste NEPSE's daily table and diff it against the exact payload the chart
            renders. Basis defaults to as_traded because that is what NEPSE's table quotes.
          </p>
        </div>
        <form className="symbol-form" onSubmit={(e) => e.preventDefault()}>
          <input
            className="input"
            value={symbol}
            onChange={(e) => setParam("symbol", e.target.value.toUpperCase())}
            aria-label="Symbol"
            style={{ width: 110, textTransform: "uppercase" }}
          />
          <select className="input" value={range} onChange={(e) => setParam("range", e.target.value)} aria-label="Range">
            {RANGES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <select className="input" value={basis} onChange={(e) => setParam("basis", e.target.value)} aria-label="Basis">
            <option value="as_traded">as_traded</option>
            <option value="adjusted">adjusted</option>
          </select>
        </form>
      </header>

      {query.isLoading && <Loading label={`Loading ${symbol} ${range}`} />}
      {query.error && <ErrorState error={query.error} onRetry={() => void query.refetch()} />}

      {query.data && series && (
        <>
          {query.data.price_mode.differs_from_requested && (
            <Card title="Price mode">
              <p className="state state-empty">{query.data.price_mode.reason}</p>
            </Card>
          )}

          <TechnicalChart data={{ series, indicators: {} }} selected={[]} symbol={symbol} />

          <Card title={`Our payload — ${series.dates.length} sessions (${range})`}>
            <div className="parity-table-wrap">
              <table className="table parity-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Open</th>
                    <th>High</th>
                    <th>Low</th>
                    <th>Close</th>
                    <th>Volume</th>
                  </tr>
                </thead>
                <tbody>
                  {[...series.dates.keys()].reverse().map((i) => (
                    <tr key={series.dates[i]}>
                      <td>{series.dates[i]}</td>
                      <td>{fmtNum(series.open[i])}</td>
                      <td>{fmtNum(series.high[i])}</td>
                      <td>{fmtNum(series.low[i])}</td>
                      <td>{fmtNum(series.close[i])}</td>
                      <td>{fmtInt(series.volume[i])}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="parity-meta">
              as_of {query.data.as_of} · sessions shown {query.data.range.sessions_shown} · first
              shown {query.data.range.first_shown} · price mode {query.data.price_mode.applied}
            </p>
          </Card>

          <Card title="NEPSE table paste — per-row diff">
            <textarea
              className="input parity-paste"
              value={paste}
              onChange={(e) => setPaste(e.target.value)}
              placeholder={`Paste NEPSE's daily table here, e.g.\n2026-09-30  4,935.00  4,935.00  4,821.00  4,919.70  3,204\nor dd/mm/yyyy 4935 4935 4821 4919.7 3204`}
              rows={8}
            />
            {rows.length > 0 && (
              <>
                <p className="parity-summary">
                  <strong className={mismatched ? "p-bad" : matched ? "p-ok" : undefined}>
                    {matched} match
                  </strong>
                  {" · "}
                  <strong className={mismatched ? "p-bad" : undefined}>{mismatched} mismatch</strong>
                  {" · "}
                  {notInWindow} not in window{" · "}
                  {incomparable} incomparable (missing field)
                  {skipped > 0 && <> · {skipped} unparseable line(s) ignored</>}
                </p>
                <div className="parity-table-wrap">
                  <table className="table parity-table">
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>O (NEPSE / ours)</th>
                        <th>H (NEPSE / ours)</th>
                        <th>L (NEPSE / ours)</th>
                        <th>C (NEPSE / ours)</th>
                        <th>Volume (NEPSE / ours)</th>
                        <th>Verdict</th>
                      </tr>
                    </thead>
                    <tbody>
                      {diffs.map((d) => (
                        <tr key={d.nepse.date} className={d.missing ? "p-miss" : undefined}>
                          <td>{d.nepse.date}</td>
                          {d.missing ? (
                            <td colSpan={5}>not in the fetched window — widen the range above</td>
                          ) : (
                            d.cells.map((c, j) => (
                              <td key={j} className={c.ok === true ? "p-ok" : c.ok === false ? "p-bad" : "p-miss"}>
                                {fmtNum(c.nepse, j === 4 ? 0 : 2)} / {fmtNum(c.ours, j === 4 ? 0 : 2)}
                                {c.ok === false && (
                                  <span className="p-delta"> ({c.nepse !== null && c.ours !== null ? fmtNum(c.nepse - c.ours) : "?"})</span>
                                )}
                              </td>
                            ))
                          )}
                          <td>
                            {d.missing ? "—" : d.ok === true ? "match" : d.ok === false ? "MISMATCH" : "incomparable"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="parity-meta">
                  Price cells match to ±0.011 (one paisa of rounding); volume to 0.5%. A red cell
                  with a parenthesised number shows NEPSE − ours.
                </p>
              </>
            )}
            <details className="parity-meta">
              <summary>What belongs in the paste</summary>
              <ul>
                <li>One row per session: date, open, high, low, close, volume (volume optional).</li>
                <li>Commas, pipes, tabs and dd/mm/yyyy all tolerated; header rows are ignored.</li>
                <li>Paste the same date window the range selector above shows — rows outside it are flagged, not guessed.</li>
              </ul>
            </details>
          </Card>
        </>
      )}
    </div>
  );
}

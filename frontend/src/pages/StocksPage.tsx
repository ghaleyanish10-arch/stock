/* Top movers and the full stock table. */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { market } from "../api";
import { Badge, Card, ErrorState, Loading, Stat, Table, Toolbar } from "../components/ui";
import { fmtInt, fmtNum, fmtPct, fmtRs, isMissing, trendClass } from "../format";
import type { MoverRow, Stock } from "../types";

const REFRESH_MS = 30_000;

export function MoversPage() {
  const gainers = useQuery({
    queryKey: ["top-gainers"],
    queryFn: ({ signal }) => market.topGainers(10, signal),
    refetchInterval: REFRESH_MS,
  });
  const losers = useQuery({
    queryKey: ["top-losers"],
    queryFn: ({ signal }) => market.topLosers(10, signal),
    refetchInterval: REFRESH_MS,
  });

  if (gainers.isLoading || losers.isLoading) return <Loading label="Loading movers" />;
  if (gainers.error) return <ErrorState error={gainers.error} onRetry={() => void gainers.refetch()} />;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Movers</h1>
          <p className="page-sub">Largest percentage moves in the latest session.</p>
        </div>
      </header>

      <div className="two-col">
        <MoverCard title="Gainers" rows={gainers.data ?? []} />
        <MoverCard title="Losers" rows={losers.data ?? []} />
      </div>
    </div>
  );
}

function MoverCard({ title, rows }: { title: string; rows: MoverRow[] }) {
  return (
    <Card title={title}>
      <Table
        rows={rows}
        rowKey={(r) => r.symbol}
        empty="No data."
        columns={[
          {
            key: "symbol",
            header: "Symbol",
            render: (r) => <Link to={`/analytics?symbol=${r.symbol}`}>{r.symbol}</Link>,
          },
          { key: "name", header: "Name", render: (r) => r.security_name ?? "–" },
          { key: "ltp", header: "LTP", align: "right", render: (r) => fmtNum(r.ltp) },
          {
            key: "chg",
            header: "Change",
            align: "right",
            render: (r) => (
              <span className={trendClass(r.percentage_change)}>{fmtPct(r.percentage_change)}</span>
            ),
          },
        ]}
      />
    </Card>
  );
}

export function StocksPage() {
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<{ key: keyof Stock; dir: 1 | -1 }>({
    key: "total_traded_value",
    dir: -1,
  });

  const query = useQuery({
    queryKey: ["stocks"],
    queryFn: ({ signal }) => market.stocks(signal),
    refetchInterval: REFRESH_MS,
  });

  const rows = useMemo(() => {
    const all = query.data?.stocks ?? [];
    const needle = search.trim().toLowerCase();
    const filtered = needle
      ? all.filter(
          (s) =>
            s.symbol.toLowerCase().includes(needle) ||
            (s.security_name ?? "").toLowerCase().includes(needle),
        )
      : all;
    return [...filtered].sort((a, b) => {
      const av = a[sort.key] ?? -Infinity;
      const bv = b[sort.key] ?? -Infinity;
      return (av < bv ? -1 : av > bv ? 1 : 0) * sort.dir;
    });
  }, [query.data, search, sort]);

  if (query.isLoading) return <Loading label="Loading stocks" />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;

  const totalTurnover = rows.reduce(
    (sum, s) => sum + (isMissing(s.total_traded_value) ? 0 : s.total_traded_value!),
    0,
  );

  const sortBy = (key: keyof Stock) =>
    setSort((prev) => ({ key, dir: prev.key === key && prev.dir === -1 ? 1 : -1 }));

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Stocks</h1>
          <p className="page-sub">{fmtInt(rows.length)} instruments in the latest snapshot.</p>
        </div>
      </header>

      <div className="stat-row">
        <Stat label="Turnover in view">{fmtRs(totalTurnover)}</Stat>
        <Stat label="Instruments">{fmtInt(rows.length)}</Stat>
      </div>

      <Toolbar>
        <input
          className="input"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search symbol or name"
          aria-label="Search stocks"
        />
      </Toolbar>

      <Card padded={false}>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>
                  <button type="button" className="th-sort" onClick={() => sortBy("symbol")}>
                    Symbol
                  </button>
                </th>
                <th>Name</th>
                <th className="align-right">
                  <button type="button" className="th-sort" onClick={() => sortBy("close_price")}>
                    Close
                  </button>
                </th>
                <th className="align-right">Change</th>
                <th className="align-right">
                  <button type="button" className="th-sort" onClick={() => sortBy("total_traded_value")}>
                    Turnover
                  </button>
                </th>
                <th className="align-right">
                  <button type="button" className="th-sort" onClick={() => sortBy("total_traded_quantity")}>
                    Volume
                  </button>
                </th>
                <th className="align-right">
                  <button type="button" className="th-sort" onClick={() => sortBy("fifty_two_week_high")}>
                    52w high
                  </button>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 250).map((s) => (
                <tr key={s.symbol}>
                  <td>
                    <Link to={`/analytics?symbol=${s.symbol}`}>
                      <strong>{s.symbol}</strong>
                    </Link>
                  </td>
                  <td className="truncate" title={s.security_name ?? undefined}>
                    {s.security_name ?? "–"}
                  </td>
                  <td className="align-right">{fmtNum(s.close_price)}</td>
                  <td className={`align-right ${trendClass(s.change_percentage)}`}>
                    {fmtPct(s.change_percentage)}
                    {s.change_percentage != null && s.change_percentage === 0 && (
                      <>
                        {" "}
                        <Badge tone="neutral">flat</Badge>
                      </>
                    )}
                  </td>
                  <td className="align-right">{fmtRs(s.total_traded_value)}</td>
                  <td className="align-right">{fmtInt(s.total_traded_quantity)}</td>
                  <td className="align-right">{fmtNum(s.fifty_two_week_high)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {rows.length > 250 && (
          <p className="muted pad">Showing the first 250 of {fmtInt(rows.length)}.</p>
        )}
      </Card>
    </div>
  );
}

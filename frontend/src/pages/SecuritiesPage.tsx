/* Security master.
 *
 * Most fields are `null` until a symbol is enriched, because NEPSE only carries
 * sector, ISIN and listed shares one symbol at a time
 * (`POST /api/reference/enrich/{symbol}`). Those nulls are shown with their
 * reason rather than as dashes.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { reference } from "../api";
import { useAuth } from "../auth";
import { ProvenanceLegend } from "../provenance";
import { Badge, Card, ErrorState, Loading, Table, Toolbar } from "../components/ui";
import { fmtDate, fmtInt, fmtNum } from "../format";
import type { SecurityRow } from "../types";

const PAGE_SIZE = 100;

export function SecuritiesPage() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const [search, setSearch] = useState("");
  const [activeOnly, setActiveOnly] = useState(true);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [enrichError, setEnrichError] = useState<unknown>(null);

  const query = useQuery({
    queryKey: ["securities", search, activeOnly],
    queryFn: ({ signal }) => reference.securities(search || undefined, activeOnly, signal),
    staleTime: 60_000,
  });

  const enrich = useMutation({
    mutationFn: (symbol: string) => reference.enrich(symbol),
    onSuccess: () => {
      setEnrichError(null);
      void qc.invalidateQueries({ queryKey: ["securities"] });
    },
    onError: (err) => setEnrichError(err),
  });

  const rows = query.data?.securities ?? [];
  const visible = rows.slice(0, limit);
  const unlisted = rows.filter((r) => r.listed_shares == null).length;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Securities</h1>
          <p className="page-sub">
            {fmtInt(query.data?.count)} symbols in the master.
            {unlisted > 0 && (
              <>
                {" "}
                {fmtInt(unlisted)} have no listed-share count yet - NEPSE publishes that one
                symbol at a time.
              </>
            )}
          </p>
        </div>
        {user?.is_admin && (
          <button
            type="button"
            className="btn btn-sm btn-primary"
            onClick={() => reference.sync().then(() => query.refetch())}
          >
            Sync from NEPSE
          </button>
        )}
      </header>

      <Toolbar>
        <input
          className="input"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search symbol or name"
          aria-label="Search securities"
        />
        <label className="check">
          <input
            type="checkbox"
            checked={activeOnly}
            onChange={(e) => setActiveOnly(e.target.checked)}
          />
          Active only
        </label>
      </Toolbar>

      {enrichError != null && <ErrorState error={enrichError} />}

      <Card padded={false} actions={<ProvenanceLegend />}>
        {query.isLoading ? (
          <Loading label="Loading securities" />
        ) : query.error ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : (
          <Table
            rows={visible}
            rowKey={(r) => r.symbol}
            columns={[
              { key: "symbol", header: "Symbol", render: (r) => <strong>{r.symbol}</strong> },
              { key: "name", header: "Name", render: (r) => r.name ?? "–" },
              {
                key: "sector",
                header: "Sector",
                render: (r) =>
                  r.sector ? (
                    r.sector
                  ) : (
                    <span
                      className="mv-chip st-missing"
                      title="NEPSE only carries sector in the per-symbol detail endpoint. Use Enrich."
                    >
                      Not fetched
                    </span>
                  ),
              },
              {
                key: "type",
                header: "Type",
                render: (r) => (r.type ? <Badge tone="info">{r.type}</Badge> : "–"),
              },
              {
                key: "shares",
                header: "Listed shares",
                align: "right",
                render: (r) =>
                  r.listed_shares == null ? (
                    <span className="mv-chip st-missing">Not fetched</span>
                  ) : (
                    fmtInt(r.listed_shares)
                  ),
              },
              { key: "isin", header: "ISIN", render: (r) => r.isin ?? "–" },
              { key: "rating", header: "Rating", render: (r) => r.credit_rating ?? "–" },
              { key: "listed", header: "Listed", render: (r) => fmtDate(r.listing_date) },
              {
                key: "actions",
                header: "",
                align: "right",
                render: (r) => (
                  <button
                    type="button"
                    className="btn btn-xs"
                    disabled={enrich.isPending}
                    onClick={() => enrich.mutate(r.symbol)}
                    title={
                      r.listed_shares == null
                        ? "Fetch sector, ISIN and listed shares from NEPSE"
                        : "Refresh metadata from NEPSE"
                    }
                  >
                    Enrich
                  </button>
                ),
              },
            ]}
            empty="No securities match. Run a sync first."
          />
        )}
      </Card>

      {rows.length > visible.length && (
        <div className="more-row">
          <button type="button" className="btn btn-sm" onClick={() => setLimit((l) => l + 100)}>
            Show {Math.min(100, rows.length - visible.length)} more
          </button>
          <span className="muted">
            Showing {visible.length} of {rows.length}
          </span>
        </div>
      )}

      <Card title="Tick size and face value">
        <p className="prose">
          Reported by NEPSE per symbol: {fmtNum(rows[0]?.tick_size)} tick size for{" "}
          {rows[0]?.symbol ?? "the first row"}. These are only present after enrichment, like
          the columns above.
        </p>
      </Card>
    </div>
  );
}

export type { SecurityRow };

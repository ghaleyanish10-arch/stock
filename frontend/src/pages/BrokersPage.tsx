/* Official broker/member directory.
 *
 * This is real reference data: 92 members with names, dealer flags, contact
 * details and provinces. It is *not* trade attribution - NEPSE leaves the
 * broker fields in its floorsheet null and ignores its own broker filter, so
 * per-broker flow cannot be derived. That limitation is stated on the page
 * rather than hidden.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { reference } from "../api";
import { Badge, Card, ErrorState, Loading, Table, Toolbar } from "../components/ui";
import { fmtInt } from "../format";
import type { BrokerRow } from "../types";

export function BrokersPage() {
  const [search, setSearch] = useState("");
  const [province, setProvince] = useState("");

  const query = useQuery({
    queryKey: ["brokers", search, province],
    queryFn: ({ signal }) =>
      reference.brokers(
        { search: search || undefined, province: province || undefined },
        signal,
      ),
    staleTime: 5 * 60_000,
  });

  const data = query.data;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Brokers</h1>
          <p className="page-sub">
            The NEPSE member registry - {fmtInt(data?.count)} members.
          </p>
        </div>
      </header>

      {data && !data.attribution.available && (
        <div className="notice notice-warn">
          <strong>Trade attribution is not available.</strong> {data.attribution.reason}
        </div>
      )}

      <Toolbar>
        <input
          className="input"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search broker name"
          aria-label="Search brokers"
        />
        <select
          className="input input-sm"
          value={province}
          onChange={(e) => setProvince(e.target.value)}
          aria-label="Filter by province"
        >
          <option value="">All provinces</option>
          {(data?.provinces ?? []).map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </Toolbar>

      <Card padded={false}>
        {query.isLoading ? (
          <Loading label="Loading brokers" />
        ) : query.error ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : (
          <Table
            rows={data?.brokers ?? []}
            rowKey={(b) => b.member_code}
            columns={[
              { key: "code", header: "#", align: "right", render: (b) => b.member_code },
              {
                key: "name",
                header: "Member",
                render: (b) => (
                  <>
                    <strong>{b.member_name}</strong>
                    {b.is_dealer === true && (
                      <>
                        {" "}
                        <Badge tone="info">dealer</Badge>
                      </>
                    )}
                  </>
                ),
              },
              { key: "province", header: "Province", render: (b) => b.province ?? "–" },
              { key: "district", header: "District", render: (b) => b.district ?? "–" },
              { key: "phone", header: "Phone", render: (b) => b.phone ?? "–" },
              { key: "email", header: "Email", render: (b) => b.email ?? "–" },
              {
                key: "status",
                header: "Status",
                render: (b) =>
                  b.is_active === null ? (
                    <span className="mv-chip st-missing">Not reported</span>
                  ) : b.is_active ? (
                    <Badge tone="ok">active</Badge>
                  ) : (
                    <Badge tone="neutral">inactive</Badge>
                  ),
              },
            ]}
            empty="No brokers match."
          />
        )}
      </Card>
    </div>
  );
}

export type { BrokerRow };

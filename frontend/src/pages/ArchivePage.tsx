/* Archive: what history we hold, and why each day looks the way it does.
 *
 * The three-way calendar split is the point of this page. A weekend/holiday, a
 * date older than NEPSE publishes, and a date whose fetch failed are all
 * different facts, and the UI keeps them apart.
 */

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { archive } from "../api";
import { ProvenanceLegend } from "../provenance";
import { Badge, Card, ErrorState, Loading, Stat, Table, Toolbar } from "../components/ui";
import { fmtDate, fmtDateTime, fmtInt } from "../format";
import type { SessionRow } from "../types";

export function ArchivePage() {
  const qc = useQueryClient();
  const [probeDate, setProbeDate] = useState("");
  const [startBack, setStartBack] = useState("");

  const coverage = useQuery({
    queryKey: ["coverage"],
    queryFn: ({ signal }) => archive.coverage(signal),
  });

  const sessions = useQuery({
    queryKey: ["sessions"],
    queryFn: ({ signal }) => archive.sessions(undefined, undefined, 400, signal),
  });

  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: ({ signal }) => archive.runs(20, signal),
  });

  const asOf = useQuery({
    queryKey: ["as-of", probeDate],
    queryFn: ({ signal }) => archive.asOf(probeDate || undefined, signal),
    enabled: probeDate.length > 0,
  });

  const [backfillError, setBackfillError] = useState<unknown>(null);
  const [backfillNote, setBackfillNote] = useState<string | null>(null);

  async function runBackfill() {
    setBackfillError(null);
    setBackfillNote(null);
    try {
      const res = await archive.backfill({ start: startBack || undefined });
      setBackfillNote(res.detail);
      // A backfill runs in the background; poll coverage while it works.
      setTimeout(() => {
        void qc.invalidateQueries({ queryKey: ["coverage"] });
        void qc.invalidateQueries({ queryKey: ["runs"] });
        void qc.invalidateQueries({ queryKey: ["sessions"] });
      }, 3000);
    } catch (err) {
      setBackfillError(err);
    }
  }

  if (coverage.isLoading) return <Loading label="Reading archive" />;
  if (coverage.error) return <ErrorState error={coverage.error} onRetry={() => void coverage.refetch()} />;

  const cov = coverage.data;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Archive</h1>
          <p className="page-sub">
            History this app has stored locally, with every date's status kept
            distinct.
          </p>
        </div>
      </header>

      {cov && (
        <div className="stat-row">
          <Stat label="Sessions stored" hint={`${cov.known_days} calendar days known`}>
            {fmtInt(cov.sessions)}
          </Stat>
          <Stat label="Bars" hint={`${fmtInt(cov.symbols)} distinct symbols`}>
            {fmtInt(cov.bars)}
          </Stat>
          <Stat
            label="Range"
            hint={cov.first_session ? `From ${fmtDate(cov.first_session)}` : "No sessions yet"}
          >
            {cov.first_session ? fmtDate(cov.first_session) : "–"}
            <span className="stat-sep">→</span>
            {fmtDate(cov.last_session)}
          </Stat>
          <Stat
            label="Non-sessions"
            hint="Weekends and holidays NEPSE confirmed"
          >
            {fmtInt(cov.non_sessions)}
          </Stat>
          <Stat
            label="Unknown"
            hint="Never fetched, or the last fetch failed. Retried, not assumed."
          >
            {fmtInt(cov.unknown_days)}
          </Stat>
        </div>
      )}

      {cov && (
        <Card title="Source limits">
          <p className="prose">{cov.note}</p>
          <p className="prose">
            NEPSE's own floor is <strong>{fmtDate(cov.nepse_published_floor)}</strong>. Dates
            before it are permanently unavailable from the source, so they are recorded as
            out-of-range rather than as holidays.
          </p>
          <ProvenanceLegend />
        </Card>
      )}

      <Card
        title="Backfill"
        actions={
          <Toolbar>
            <select
              className="input input-sm"
              value={startBack}
              onChange={(e) => setStartBack(e.target.value)}
              aria-label="Backfill start"
            >
              <option value="">From the archive floor</option>
              <option value="2026-09-01">From 2026-09-01</option>
              <option value="2026-08-01">From 2026-08-01</option>
            </select>
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() => void runBackfill()}
            >
              Start backfill
            </button>
          </Toolbar>
        }
      >
        <p className="prose">
          Backfill fetches each date from NEPSE, resuming from what is already stored.
          This issues hundreds of upstream requests, so it needs an admin account.
        </p>
        {backfillNote && <p className="notice notice-ok">{backfillNote}</p>}
        {backfillError != null && <ErrorState error={backfillError} onRetry={() => void runBackfill()} />}
      </Card>

      <Card title="Date resolver">
        <p className="prose">
          Ask for any date and see which session the API would return, with the reason it
          substituted.
        </p>
        <Toolbar>
          <input
            className="input input-sm"
            type="date"
            value={probeDate}
            onChange={(e) => setProbeDate(e.target.value)}
            aria-label="Date to resolve"
          />
          {probeDate && (
            <button type="button" className="btn btn-sm" onClick={() => setProbeDate("")}>
              Clear
            </button>
          )}
        </Toolbar>
        {asOf.isFetching && <Loading label="Resolving" />}
        {asOf.data && (
          <div className="resolve-result">
            <div>
              <span className="resolve-label">Requested</span>
              <strong>{fmtDate(asOf.data.requested)}</strong>
            </div>
            <div>
              <span className="resolve-label">Resolves to</span>
              <strong>{fmtDate(asOf.data.resolved)}</strong>
            </div>
            {asOf.data.walked_back ? (
              <Badge tone="warn">walked back</Badge>
            ) : (
              <Badge tone="ok">exact</Badge>
            )}
            {asOf.data.reason && <p className="prose">{asOf.data.reason}</p>}
          </div>
        )}
      </Card>

      <Card title="Calendar" actions={<ProvenanceLegend />}>
        {sessions.isLoading ? (
          <Loading label="Reading calendar" />
        ) : sessions.error ? (
          <ErrorState error={sessions.error} onRetry={() => void sessions.refetch()} />
        ) : (
          <SessionTable days={sessions.data?.days ?? []} />
        )}
        {sessions.data?.legend && (
          <ul className="legend-list">
            {Object.entries(sessions.data.legend).map(([key, text]) => (
              <li key={key}>
                <code>{key}</code> {text}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Backfill runs">
        {runs.isLoading ? (
          <Loading label="Reading runs" />
        ) : runs.error ? (
          <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />
        ) : (runs.data?.runs.length ?? 0) === 0 ? (
          <p className="prose">No backfill has been run yet.</p>
        ) : (
          <Table
            rows={runs.data?.runs ?? []}
            rowKey={(r) => String(r.id)}
            columns={[
              { key: "id", header: "#", align: "right" },
              { key: "started_at", header: "Started", render: (r) => fmtDateTime(r.started_at) },
              { key: "finished_at", header: "Finished", render: (r) => fmtDateTime(r.finished_at) },
              {
                key: "status",
                header: "Status",
                render: (r) => (
                  <Badge tone={r.status === "ok" ? "ok" : r.status === "running" ? "info" : "warn"}>
                    {r.status}
                  </Badge>
                ),
              },
              { key: "sessions", header: "Sessions", align: "right", render: (r) => fmtInt(r.sessions) },
              { key: "non_sessions", header: "Non", align: "right", render: (r) => fmtInt(r.non_sessions) },
              { key: "failed", header: "Failed", align: "right", render: (r) => fmtInt(r.failed) },
              { key: "rows_written", header: "Rows", align: "right", render: (r) => fmtInt(r.rows_written) },
            ]}
            empty="No runs yet."
          />
        )}
      </Card>
    </div>
  );
}

function SessionTable({ days }: { days: SessionRow[] }) {
  return (
    <Table
      rows={days}
      rowKey={(d) => d.business_date}
      empty="No dates fetched yet. Run a backfill."
      columns={[
        { key: "date", header: "Date", render: (d) => fmtDate(d.business_date) },
        {
          key: "status",
          header: "Status",
          render: (d) => {
            if (d.is_session === true) return <Badge tone="ok">session</Badge>;
            if (d.is_session === false) return <Badge tone="neutral">non-session</Badge>;
            return <Badge tone="warn">unknown</Badge>;
          },
        },
        {
          key: "rows",
          header: "Rows",
          align: "right",
          render: (d) => (d.is_session ? fmtInt(d.row_count) : "–"),
        },
        { key: "fetched", header: "Fetched", render: (d) => fmtDateTime(d.fetched_at) },
        { key: "note", header: "Note", render: (d) => d.note ?? "–" },
      ]}
    />
  );
}

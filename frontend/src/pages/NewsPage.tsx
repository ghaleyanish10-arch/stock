/* News page: browse and search NEPSE announcements. */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { news } from "../api";
import { Card, EmptyState, ErrorState, Loading, Missing, Table, Badge } from "../components/ui";
import { fmtInt } from "../format";

export function NewsPage() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<"list" | "search">("list");
  const [filters, setFilters] = useState({
    symbol: "",
    news_type: "",
    date_from: "",
    date_to: "",
    limit: 50,
    offset: 0,
  });
  const [searchQuery, setSearchQuery] = useState("");
  const [searchLimit, setSearchLimit] = useState(20);
  const [showSync, setShowSync] = useState(false);
  const [syncSymbol, setSyncSymbol] = useState("");
  const [syncLimit, setSyncLimit] = useState(100);

  // List news
  const { data: newsData, isLoading: newsLoading, error: newsError } = useQuery({
    queryKey: ["news", filters],
    queryFn: () => news.list(filters),
  });

  // Search news
  const searchMut = useMutation({
    mutationFn: () => news.search(searchQuery, searchLimit),
  });

  // Sync news (admin)
  const syncMut = useMutation({
    mutationFn: () => news.sync(syncSymbol || undefined, syncLimit),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["news"] });
      setShowSync(false);
    },
  });

  const handleSearch = () => {
    if (searchQuery.trim()) {
      searchMut.mutate();
    }
  };

  const handleSync = () => {
    if (confirm("Sync news from NEPSE? This may take a while.")) {
      syncMut.mutate();
    }
  };

  const handlePageChange = (newOffset: number) => {
    setFilters(prev => ({ ...prev, offset: newOffset }));
  };

  const hasNextPage = newsData && filters.offset + filters.limit < newsData.total;
  const hasPrevPage = filters.offset > 0;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>News & Announcements</h1>
          <p className="page-sub">Browse NEPSE company announcements and market news.</p>
        </div>
        <div className="page-head-actions">
          <button type="button" className="btn" onClick={() => setShowSync(true)}>
            Sync from NEPSE (Admin)
          </button>
        </div>
      </header>

      <div className="seg-group" role="group" aria-label="News sections" style={{ marginBottom: "var(--space-4)" }}>
        <button
          type="button"
          className={`seg-btn ${activeTab === "list" ? "is-active" : ""}`}
          aria-pressed={activeTab === "list"}
          onClick={() => setActiveTab("list")}
        >
          Browse
        </button>
        <button
          type="button"
          className={`seg-btn ${activeTab === "search" ? "is-active" : ""}`}
          aria-pressed={activeTab === "search"}
          onClick={() => setActiveTab("search")}
        >
          Search
        </button>
      </div>

      {activeTab === "list" && (
        <>
          {/* Filters */}
          <Card title="Filters">
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "var(--space-4)", marginBottom: "var(--space-4)" }}>
              <label className="field">
                <span className="field-label">Symbol</span>
                <input className="input" placeholder="e.g., NABIL" value={filters.symbol} onChange={e => setFilters(prev => ({ ...prev, symbol: e.target.value.toUpperCase(), offset: 0 }))} />
              </label>
              <label className="field">
                <span className="field-label">News Type</span>
                <input className="input" placeholder="e.g., dividend, bonus, agm" value={filters.news_type} onChange={e => setFilters(prev => ({ ...prev, news_type: e.target.value, offset: 0 }))} />
              </label>
              <label className="field">
                <span className="field-label">Date From</span>
                <input className="input" type="date" value={filters.date_from} onChange={e => setFilters(prev => ({ ...prev, date_from: e.target.value, offset: 0 }))} />
              </label>
              <label className="field">
                <span className="field-label">Date To</span>
                <input className="input" type="date" value={filters.date_to} onChange={e => setFilters(prev => ({ ...prev, date_to: e.target.value, offset: 0 }))} />
              </label>
              <label className="field">
                <span className="field-label">Limit</span>
                <input className="input" type="number" min={1} max={200} value={filters.limit} onChange={e => setFilters(prev => ({ ...prev, limit: Number(e.target.value), offset: 0 }))} />
              </label>
            </div>
            <button type="button" className="btn btn-sm" onClick={() => setFilters({ symbol: "", news_type: "", date_from: "", date_to: "", limit: 50, offset: 0 })}>Clear Filters</button>
          </Card>

          {/* Results */}
          <Card title="Announcements">
            {newsLoading && <Loading label="Loading news" />}
            {newsError && <ErrorState error={newsError} />}
            {!newsLoading && !newsError && newsData?.items.length === 0 && (
              <EmptyState message="No announcements match these filters." />
            )}
            {!newsLoading && !newsError && newsData?.items.length && (
              <>
                <Table
                  rows={newsData.items}
                  rowKey={(n) => n.id}
                  columns={[
                    { key: "published_at", header: "Published", render: (n) => n.published_at ? new Date(n.published_at).toLocaleString() : <Missing reason="Unknown" /> },
                    { key: "symbol", header: "Symbol", render: (n) => n.symbol ? <strong>{n.symbol}</strong> : <Missing reason="Market-wide" /> },
                    { key: "news_type", header: "Type", render: (n) => n.news_type ? <Badge tone="info">{n.news_type}</Badge> : <Missing reason="Unknown" /> },
                    { key: "headline", header: "Headline", render: (n) => n.headline ?? <Missing reason="No headline" /> },
                    {
                      key: "actions",
                      header: "",
                      render: (n) => (
                        <button
                          type="button"
                          className="btn btn-sm"
                          onClick={() => alert(n.body || "No full text available")}
                        >
                          View
                        </button>
                      ),
                    },
                  ]}
                  empty="No announcements"
                />
                {/* Pagination */}
                <div style={{ display: "flex", justifyContent: "center", gap: "var(--space-2)", marginTop: "var(--space-4)" }}>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => handlePageChange(Math.max(0, filters.offset - filters.limit))}
                    disabled={!hasPrevPage || newsLoading}
                  >
                    Previous
                  </button>
                  <span style={{ display: "flex", alignItems: "center", padding: "0 var(--space-4)" }}>
                    Showing {filters.offset + 1}–{Math.min(filters.offset + filters.limit, newsData.total)} of {newsData.total}
                  </span>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => handlePageChange(filters.offset + filters.limit)}
                    disabled={!hasNextPage || newsLoading}
                  >
                    Next
                  </button>
                </div>
              </>
            )}
          </Card>
        </>
      )}

      {activeTab === "search" && (
        <Card title="Search Announcements">
          <div style={{ display: "flex", gap: "var(--space-2)", marginBottom: "var(--space-4)" }}>
            <input
              className="input"
              placeholder="Search keyword (e.g., dividend, bonus, AGM, book closure)"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleSearch()}
              style={{ flex: 1 }}
            />
            <label className="field" style={{ marginBottom: 0 }}>
              <span className="field-label">Limit</span>
              <input className="input" type="number" min={1} max={100} value={searchLimit} onChange={e => setSearchLimit(Number(e.target.value))} style={{ width: "80px" }} />
            </label>
            <button type="button" className="btn btn-primary" onClick={handleSearch} disabled={searchMut.isPending || !searchQuery.trim()}>
              {searchMut.isPending ? "Searching…" : "Search"}
            </button>
          </div>

          {searchMut.isSuccess && searchMut.data && (
            <div style={{ marginBottom: "var(--space-4)" }}>
              <p><strong>{searchMut.data.count}</strong> results for "<strong>{searchMut.data.query}</strong>"</p>
              <Table
                rows={searchMut.data.results}
                rowKey={(n) => n.id}
                columns={[
                  { key: "published_at", header: "Published", render: (n) => n.published_at ? new Date(n.published_at).toLocaleString() : <Missing reason="Unknown" /> },
                  { key: "symbol", header: "Symbol", render: (n) => n.symbol ? <strong>{n.symbol}</strong> : <Missing reason="Market-wide" /> },
                  { key: "news_type", header: "Type", render: (n) => n.news_type ? <Badge tone="info">{n.news_type}</Badge> : <Missing reason="Unknown" /> },
                  { key: "headline", header: "Headline", render: (n) => n.headline ?? <Missing reason="No headline" /> },
                  {
                    key: "actions",
                    header: "",
                    render: (n) => (
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => alert(n.body || "No full text available")}
                      >
                        View
                      </button>
                    ),
                  },
                ]}
                empty="No results"
              />
            </div>
          )}

          {searchMut.isError && <ErrorState error={searchMut.error} />}
        </Card>
      )}

      {/* Sync Modal */}
      {showSync && (
        <div className="modal-overlay" onClick={() => setShowSync(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>Sync News from NEPSE (Admin)</h3>
            <p className="muted">Fetches latest announcements from NEPSE endpoints. Requires admin role.</p>
            <label className="field">
              <span className="field-label">Symbol (optional)</span>
              <input className="input" placeholder="e.g., NABIL (empty = all symbols)" value={syncSymbol} onChange={e => setSyncSymbol(e.target.value.toUpperCase())} />
            </label>
            <label className="field">
              <span className="field-label">Limit</span>
              <input className="input" type="number" min={1} max={500} value={syncLimit} onChange={e => setSyncLimit(Number(e.target.value))} />
            </label>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "var(--space-2)", marginTop: "var(--space-4)" }}>
              <button type="button" className="btn" onClick={() => setShowSync(false)}>Cancel</button>
              <button type="button" className="btn btn-primary" onClick={handleSync} disabled={syncMut.isPending}>
                {syncMut.isPending ? "Syncing…" : "Sync Now"}
              </button>
            </div>
            {syncMut.isSuccess && syncMut.data && (
              <div className="stat-row" style={{ marginTop: "var(--space-4)" }}>
                <div className="stat"><span className="stat-label">Synced</span><span className="stat-value">{fmtInt((syncMut.data as any).synced)}</span></div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
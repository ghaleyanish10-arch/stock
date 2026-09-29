/* Watchlist page: manage watchlists and symbols with live prices. */

import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { watchlist } from "../api";
import { Card, EmptyState, ErrorState, Loading, Missing, Table } from "../components/ui";
import { fmtPct, fmtRs } from "../format";

export function WatchlistPage() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newWatchlistName, setNewWatchlistName] = useState("");
  const [newSymbol, setNewSymbol] = useState("");
  const [newNote, setNewNote] = useState("");

  // List watchlists
  const { data: watchlistsData, isLoading: watchlistsLoading, error: watchlistsError } = useQuery({
    queryKey: ["watchlists"],
    queryFn: () => watchlist.list(),
  });

  // Selected watchlist items
  const { data: itemsData, isLoading: itemsLoading, refetch: refetchItems } = useQuery({
    queryKey: ["watchlist-items", selectedId],
    queryFn: () => watchlist.getItems(selectedId!),
    enabled: !!selectedId,
    refetchInterval: 30_000,
  });

  // Mutations
  const createWatchlistMut = useMutation({
    mutationFn: (name: string) => watchlist.create(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["watchlists"] });
      setShowCreate(false);
      setNewWatchlistName("");
    },
  });

  const addItemMut = useMutation({
    mutationFn: ({ symbol, note }: { symbol: string; note?: string }) =>
      watchlist.addItem(selectedId!, symbol.toUpperCase(), note),
    onSuccess: () => {
      refetchItems();
      setNewSymbol("");
      setNewNote("");
    },
  });

  const removeItemMut = useMutation({
    mutationFn: (symbol: string) => watchlist.removeItem(selectedId!, symbol),
    onSuccess: () => refetchItems(),
  });

  // Auto-select first watchlist
  useEffect(() => {
    if (!selectedId && watchlistsData?.watchlists.length) {
      setSelectedId(watchlistsData.watchlists[0].id);
    }
  }, [watchlistsData, selectedId]);

  const handleCreateWatchlist = () => {
    if (newWatchlistName.trim()) {
      createWatchlistMut.mutate(newWatchlistName.trim());
    }
  };

  const handleAddItem = () => {
    if (!selectedId || !newSymbol.trim()) return;
    addItemMut.mutate({ symbol: newSymbol.trim().toUpperCase(), note: newNote.trim() || undefined });
  };

  const handleRemoveItem = (symbol: string) => {
    if (!selectedId) return;
    if (confirm(`Remove ${symbol} from watchlist?`)) {
      removeItemMut.mutate(symbol);
    }
  };

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Watchlists</h1>
          <p className="page-sub">Track symbols with live prices and notes.</p>
        </div>
        <div className="page-head-actions">
          <button type="button" className="btn btn-primary" onClick={() => setShowCreate(true)}>
            New Watchlist
          </button>
        </div>
      </header>

      {watchlistsError && <ErrorState error={watchlistsError} />}
      {watchlistsLoading && <Loading label="Loading watchlists" />}

      {!watchlistsLoading && !watchlistsError && (
        <>
          {/* Create watchlist modal */}
          {showCreate && (
            <div className="modal-overlay" onClick={() => setShowCreate(false)}>
              <div className="modal" onClick={(e) => e.stopPropagation()}>
                <h3>Create Watchlist</h3>
                <label className="field">
                  <span className="field-label">Name</span>
                  <input
                    className="input"
                    value={newWatchlistName}
                    onChange={(e) => setNewWatchlistName(e.target.value)}
                    placeholder="e.g. My Tech Stocks"
                    autoFocus
                    onKeyDown={(e) => e.key === "Enter" && handleCreateWatchlist()}
                  />
                </label>
                <div style={{ display: "flex", justifyContent: "flex-end", gap: "var(--space-2)", marginTop: "var(--space-4)" }}>
                  <button type="button" className="btn" onClick={() => setShowCreate(false)}>Cancel</button>
                  <button type="button" className="btn btn-primary" onClick={handleCreateWatchlist} disabled={createWatchlistMut.isPending}>
                    {createWatchlistMut.isPending ? "Creating…" : "Create"}
                  </button>
                </div>
              </div>
            </div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: "var(--space-4)" }}>
            <Card title="Watchlists" padded={false}>
              {watchlistsData?.watchlists.length === 0 ? (
                <EmptyState message="No watchlists yet. Create one to start tracking." />
              ) : (
                <div style={{ maxHeight: "400px", overflow: "auto" }}>
                  {watchlistsData?.watchlists.map((w) => (
                    <div
                      key={w.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        padding: "var(--space-2) var(--space-3)",
                        borderBottom: "1px solid var(--border)",
                      }}
                    >
                      <button
                        type="button"
                        className={`nav-link${selectedId === w.id ? " active" : ""}`}
                        style={{ width: "100%", textAlign: "left", padding: 0 }}
                        onClick={() => setSelectedId(w.id)}
                      >
                        <strong>{w.name}</strong>
                        <br />
                        <span className="muted">{w.created_at ? new Date(w.created_at).toLocaleDateString() : ""}</span>
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            {selectedId && (
              <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
                <header className="page-head" style={{ marginTop: 0 }}>
                  <div>
                    <h2>{watchlistsData?.watchlists.find(w => w.id === selectedId)?.name}</h2>
                  </div>
                  <div className="page-head-actions">
                    <div style={{ display: "flex", gap: "var(--space-2)" }}>
                      <input
                        className="input"
                        placeholder="Symbol (e.g., NABIL)"
                        value={newSymbol}
                        onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
                        style={{ width: "120px" }}
                        onKeyDown={(e) => e.key === "Enter" && handleAddItem()}
                      />
                      <input
                        className="input"
                        placeholder="Note (optional)"
                        value={newNote}
                        onChange={(e) => setNewNote(e.target.value)}
                        style={{ width: "200px" }}
                        onKeyDown={(e) => e.key === "Enter" && handleAddItem()}
                      />
                      <button
                        type="button"
                        className="btn btn-primary"
                        onClick={handleAddItem}
                        disabled={addItemMut.isPending || !newSymbol.trim()}
                      >
                        Add
                      </button>
                    </div>
                  </div>
                </header>

                <Card title="Symbols">
                  {itemsLoading && <Loading label="Loading symbols" />}
                  {!itemsLoading && itemsData?.items.length === 0 && (
                    <EmptyState message="No symbols in this watchlist. Add one above." />
                  )}
                  {!itemsLoading && itemsData?.items.length && (
                    <Table
                      rows={itemsData.items}
                      rowKey={(item) => item.symbol}
                      columns={[
                        { key: "symbol", header: "Symbol", render: (i) => <strong>{i.symbol}</strong> },
                        {
                          key: "ltp",
                          header: "LTP",
                          align: "right",
                          render: (i) => i.ltp != null ? fmtRs(i.ltp) : <Missing reason={i.ltp_reason ?? "Unknown"} />,
                        },
                        {
                          key: "change_pct",
                          header: "Change %",
                          align: "right",
                          render: (i) => i.change_pct != null ? (
                            <span className={i.change_pct >= 0 ? "up" : "down"}>{fmtPct(i.change_pct)}%</span>
                          ) : <Missing reason={i.ltp_reason ?? "Unknown"} />,
                        },
                        { key: "note", header: "Note", render: (i) => i.note ?? <Missing reason="None" /> },
                        {
                          key: "actions",
                          header: "",
                          render: (i) => (
                            <button
                              type="button"
                              className="btn btn-sm btn-danger"
                              onClick={() => handleRemoveItem(i.symbol)}
                              disabled={removeItemMut.isPending}
                            >
                              Remove
                            </button>
                          ),
                        },
                      ]}
                      empty="No symbols"
                    />
                  )}
                </Card>
              </div>
            )}

            {!selectedId && watchlistsData?.watchlists.length === 0 && (
              <EmptyState message="Create a watchlist to get started." />
            )}
          </div>
        </>
      )}
    </div>
  );
}
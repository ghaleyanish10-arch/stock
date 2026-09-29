/* Portfolio page: create portfolios, add transactions, view holdings & P/L. */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { portfolio } from "../api";
import type { Transaction, ValuationHolding } from "../types";
import { fmtRs, fmtNum, fmtPct, fmtInt, trendClass } from "../format";
import {
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Stat,
  Missing,
} from "../components/ui";

interface NewTransaction {
  symbol: string;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  trade_date: string;
  fees?: number;
  note: string;
}

const NEW_PORTFOLIO_DEFAULTS = { name: "", base_currency: "NPR" };
const NEW_TRANSACTION_DEFAULTS: NewTransaction = {
  symbol: "",
  side: "buy",
  quantity: 1,
  price: 0,
  trade_date: new Date().toISOString().slice(0, 10),
  fees: undefined,
  note: "",
};

export function PortfolioPage() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreatePortfolio, setShowCreatePortfolio] = useState(false);
  const [newPortfolio, setNewPortfolio] = useState(NEW_PORTFOLIO_DEFAULTS);
  const [showAddTransaction, setShowAddTransaction] = useState(false);
  const [newTransaction, setNewTransaction] = useState<NewTransaction>(NEW_TRANSACTION_DEFAULTS);

  const portfoliosData = useQuery({
    queryKey: ["portfolios"],
    queryFn: () => portfolio.list(),
  });

  const holdings = useQuery({
    queryKey: ["holdings", selectedId],
    queryFn: () => portfolio.getHoldings(selectedId!),
    enabled: !!selectedId,
    staleTime: 30_000,
  });

  const transactions = useQuery({
    queryKey: ["transactions", selectedId],
    queryFn: () => portfolio.listTransactions(selectedId!),
    enabled: !!selectedId,
    staleTime: 30_000,
  });

  const valuation = useQuery({
    queryKey: ["valuation", selectedId],
    queryFn: () => portfolio.getValuation(selectedId!),
    enabled: !!selectedId,
    staleTime: 30_000,
  });

  const createPortfolioMut = useMutation({
    mutationFn: (data: { name: string; base_currency: string }) =>
      portfolio.create(data.name, data.base_currency),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      setShowCreatePortfolio(false);
      setNewPortfolio(NEW_PORTFOLIO_DEFAULTS);
    },
  });

  const addTransactionMut = useMutation({
    mutationFn: (tx: {
      symbol: string;
      side: "buy" | "sell";
      quantity: number;
      price: number;
      trade_date: string;
      fees?: number;
      note?: string;
    }) => portfolio.addTransaction(selectedId!, tx),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["holdings", selectedId] });
      queryClient.invalidateQueries({ queryKey: ["transactions", selectedId] });
      queryClient.invalidateQueries({ queryKey: ["valuation", selectedId] });
      setShowAddTransaction(false);
      setNewTransaction(NEW_TRANSACTION_DEFAULTS);
    },
  });

  const handleCreatePortfolio = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPortfolio.name.trim()) return;
    createPortfolioMut.mutate(newPortfolio);
  };

  const handleAddTransaction = (tx: typeof newTransaction) => {
    if (!tx.symbol.trim() || !tx.quantity || !tx.price || !tx.trade_date) return;
    addTransactionMut.mutate(tx);
  };

  if (portfoliosData.isLoading) return <Loading label="Loading portfolios" />;
  if (portfoliosData.error) return <ErrorState error={portfoliosData.error} onRetry={() => portfoliosData.refetch()} />;

  const portfolios = portfoliosData.data?.portfolios ?? [];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Portfolio</h1>
          <p className="page-sub">Track holdings, transactions, and performance.</p>
        </div>
        <div className="page-head-actions">
          <button type="button" className="btn btn-primary" onClick={() => setShowCreatePortfolio(true)}>
            New Portfolio
          </button>
        </div>
      </header>

      <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: "var(--space-4)" }}>
        {/* Portfolio list sidebar */}
        <Card title="Your Portfolios">
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
            {portfolios.length === 0 ? (
              <div className="state state-empty" style={{ padding: "var(--space-6)", textAlign: "center" }}>
                <p style={{ marginBottom: "var(--space-4)", color: "var(--text-muted)" }}>
                  You don&apos;t have any portfolios yet.
                </p>
                <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
                  <button type="button" className="btn btn-primary" onClick={() => setShowCreatePortfolio(true)}>
                    Create Portfolio
                  </button>
                  <button type="button" className="btn" onClick={() => setShowCreatePortfolio(true)}>
                    Transaction Import (CSV)
                  </button>
                </div>
              </div>
            ) : (
              portfolios.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className={`portfolio-item ${selectedId === p.id ? "active" : ""}`}
                  onClick={() => setSelectedId(p.id)}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "var(--space-3) var(--space-4)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-md)",
                    background: selectedId === p.id ? "var(--accent-soft)" : "var(--surface)",
                    color: selectedId === p.id ? "var(--accent)" : "var(--text)",
                    textAlign: "left",
                    width: "100%",
                    cursor: "pointer",
                    transition: "all var(--dur-fast) var(--ease)",
                  }}
                >
                  <span style={{ fontWeight: "var(--weight-medium)" }}>{p.name}</span>
                  <span className="badge badge-info" style={{ fontSize: "var(--text-xs)" }}>
                    {p.base_currency}
                  </span>
                </button>
              ))
            )}
          </div>
        </Card>

        {/* Main content area */}
        <div style={{ minWidth: 0 }}>
          {selectedId && (
            <>
              {holdings.isLoading || transactions.isLoading || valuation.isLoading ? (
                <Loading label="Loading portfolio data" />
              ) : holdings.error ? (
                <ErrorState error={holdings.error} onRetry={() => holdings.refetch()} />
              ) : (
                <>
                  {/* Valuation summary */}
                  {valuation.data && (
                    <Card title="Portfolio Valuation">
                      <div className="stat-row">
                        <Stat label="Total Value">
                          {valuation.data.total_market_value != null
                            ? fmtRs(valuation.data.total_market_value)
                            : <Missing reason="No prices available" />}
                        </Stat>
                        <Stat label="Total Cost">
                          {fmtRs(valuation.data.total_cost)}
                        </Stat>
                        <Stat
                          label="Unrealized P/L"
                          hint={valuation.data.as_of ? `as of ${valuation.data.as_of}` : undefined}
                        >
                          <span className={trendClass(valuation.data.total_unrealized_pl)}>
                            {valuation.data.total_unrealized_pl != null
                              ? fmtRs(valuation.data.total_unrealized_pl)
                              : <Missing reason="No prices available" />}
                          </span>
                          {valuation.data.total_unrealized_pl_pct != null && (
                            <span className={`stat-delta ${trendClass(valuation.data.total_unrealized_pl_pct)}`}>
                              {fmtPct(valuation.data.total_unrealized_pl_pct)}
                            </span>
                          )}
                        </Stat>
                      </div>
                    </Card>
                  )}

                  {/* Holdings table */}
                  {holdings.data?.holdings.length ? (
                    <Card title="Holdings">
                      <div className="table-wrap">
                        <table className="table">
                          <thead>
                            <tr>
                              <th>Symbol</th>
                              <th className="align-right">Qty</th>
                              <th className="align-right">Avg Cost</th>
                              <th className="align-right">Total Cost</th>
                              <th className="align-right">LTP</th>
                              <th className="align-right">Market Value</th>
                              <th className="align-right">Unrealized P/L</th>
                              <th className="align-right">P/L %</th>
                            </tr>
                          </thead>
                          <tbody>
                            {valuation.data?.holdings.map((h: ValuationHolding) => (
                              <tr key={h.symbol}>
                                <td style={{ fontWeight: "var(--weight-medium)" }}>{h.symbol}</td>
                                <td className="align-right">{fmtInt(h.quantity)}</td>
                                <td className="align-right">{fmtNum(h.avg_cost)}</td>
                                <td className="align-right">{fmtRs(h.total_cost)}</td>
                                <td className="align-right">
                                  {h.ltp != null ? fmtNum(h.ltp) : <Missing reason={h.ltp_reason ?? "N/A"} />}
                                </td>
                                <td className="align-right">
                                  {h.market_value != null ? fmtRs(h.market_value) : <Missing reason="N/A" />}
                                </td>
                                <td className="align-right">
                                  <span className={trendClass(h.unrealized_pl)}>
                                    {h.unrealized_pl != null ? fmtRs(h.unrealized_pl) : <Missing reason="N/A" />}
                                  </span>
                                </td>
                                <td className="align-right">
                                  <span className={trendClass(h.unrealized_pl_pct)}>
                                    {h.unrealized_pl_pct != null ? fmtPct(h.unrealized_pl_pct) + "%" : <Missing reason="N/A" />}
                                  </span>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </Card>
                  ) : (
                    <Card title="Holdings">
                      <EmptyState message="No holdings in this portfolio. Add a transaction to get started." />
                    </Card>
                  )}

                  {/* Transactions */}
                  <Card title="Transactions" actions={
                    <button type="button" className="btn btn-primary btn-sm" onClick={() => setShowAddTransaction(true)}>
                      Add Transaction
                    </button>
                  }>
                    {transactions.data?.transactions.length ? (
                      <div className="table-wrap">
                        <table className="table">
                          <thead>
                            <tr>
                              <th>Date</th>
                              <th>Symbol</th>
                              <th>Side</th>
                              <th className="align-right">Qty</th>
                              <th className="align-right">Price</th>
                              <th className="align-right">Fees</th>
                              <th>Note</th>
                            </tr>
                          </thead>
                          <tbody>
                            {transactions.data.transactions.map((tx: Transaction) => (
                              <tr key={tx.id}>
                                <td>{tx.trade_date}</td>
                                <td style={{ fontWeight: "var(--weight-medium)" }}>{tx.symbol}</td>
                                <td>
                                  <span className={`badge badge-${tx.side === "buy" ? "ok" : "warn"}`}>
                                    {tx.side.toUpperCase()}
                                  </span>
                                </td>
                                <td className="align-right">{fmtInt(tx.quantity)}</td>
                                <td className="align-right">{fmtNum(tx.price)}</td>
                                <td className="align-right">{tx.fees != null ? fmtNum(tx.fees) : "-"}</td>
                                <td>{tx.note ?? "-"}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <EmptyState message='No transactions yet. Click "Add Transaction" to start.' />
                    )}
                  </Card>
                </>
              )}
            </>
          )}

          {!selectedId && portfolios.length > 0 && (
            <Card>
              <div className="state state-empty" style={{ padding: "var(--space-10)", textAlign: "center" }}>
                <p style={{ color: "var(--text-muted)" }}>Select a portfolio from the sidebar to view details.</p>
              </div>
            </Card>
          )}
        </div>
      </div>

      {/* Create Portfolio Modal */}
      {showCreatePortfolio && (
        <div className="modal-overlay" onClick={() => setShowCreatePortfolio(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Create Portfolio</h3>
            <form onSubmit={handleCreatePortfolio}>
              <label className="field" style={{ marginBottom: "var(--space-4)" }}>
                <span className="field-label">Name</span>
                <input
                  className="input"
                  type="text"
                  value={newPortfolio.name}
                  onChange={(e) => setNewPortfolio({ ...newPortfolio, name: e.target.value })}
                  placeholder="e.g., My NEPSE Portfolio"
                  required
                  autoFocus
                />
              </label>
              <label className="field" style={{ marginBottom: "var(--space-4)" }}>
                <span className="field-label">Base Currency</span>
                <select
                  className="select"
                  value={newPortfolio.base_currency}
                  onChange={(e) => setNewPortfolio({ ...newPortfolio, base_currency: e.target.value })}
                >
                  <option value="NPR">NPR</option>
                  <option value="USD">USD</option>
                </select>
              </label>
              <div style={{ display: "flex", justifyContent: "flex-end", gap: "var(--space-2)" }}>
                <button type="button" className="btn" onClick={() => setShowCreatePortfolio(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={createPortfolioMut.isPending}>
                  {createPortfolioMut.isPending ? "Creating…" : "Create Portfolio"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Add Transaction Modal */}
      {showAddTransaction && (
        <div className="modal-overlay" onClick={() => setShowAddTransaction(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Add Transaction</h3>
            <form onSubmit={(e) => { e.preventDefault(); handleAddTransaction(newTransaction); }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "var(--space-4)" }}>
                <label className="field">
                  <span className="field-label">Symbol</span>
                  <input
                    className="input"
                    type="text"
                    value={newTransaction.symbol}
                    onChange={(e) => setNewTransaction({ ...newTransaction, symbol: e.target.value.toUpperCase() })}
                    placeholder="e.g., NABIL"
                    required
                  />
                </label>
                <label className="field">
                  <span className="field-label">Side</span>
                  <select
                    className="select"
                    value={newTransaction.side}
                    onChange={(e) => setNewTransaction({ ...newTransaction, side: e.target.value as "buy" | "sell" })}
                    required
                  >
                    <option value="buy">Buy</option>
                    <option value="sell">Sell</option>
                  </select>
                </label>
                <label className="field">
                  <span className="field-label">Quantity</span>
                  <input
                    className="input"
                    type="number"
                    min="1"
                    step="1"
                    value={newTransaction.quantity}
                    onChange={(e) => setNewTransaction({ ...newTransaction, quantity: Number(e.target.value) })}
                    required
                  />
                </label>
                <label className="field">
                  <span className="field-label">Price</span>
                  <input
                    className="input"
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={newTransaction.price}
                    onChange={(e) => setNewTransaction({ ...newTransaction, price: Number(e.target.value) })}
                    required
                  />
                </label>
                <label className="field">
                  <span className="field-label">Trade Date</span>
                  <input
                    className="input"
                    type="date"
                    value={newTransaction.trade_date}
                    onChange={(e) => setNewTransaction({ ...newTransaction, trade_date: e.target.value })}
                    required
                  />
                </label>
                <label className="field">
                  <span className="field-label">Fees (optional)</span>
                  <input
                    className="input"
                    type="number"
                    min="0"
                    step="0.01"
                    value={newTransaction.fees != null ? String(newTransaction.fees) : ""}
                    onChange={(e) => setNewTransaction({ ...newTransaction, fees: e.target.value ? Number(e.target.value) : undefined })}
                  />
                </label>
                <label className="field" style={{ gridColumn: "1 / -1" }}>
                  <span className="field-label">Note (optional)</span>
                  <input
                    className="input"
                    type="text"
                    value={newTransaction.note}
                    onChange={(e) => setNewTransaction({ ...newTransaction, note: e.target.value })}
                  />
                </label>
              </div>
              <div style={{ display: "flex", justifyContent: "flex-end", gap: "var(--space-2)", marginTop: "var(--space-4)" }}>
                <button type="button" className="btn" onClick={() => setShowAddTransaction(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={addTransactionMut.isPending}>
                  {addTransactionMut.isPending ? "Adding…" : "Add Transaction"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
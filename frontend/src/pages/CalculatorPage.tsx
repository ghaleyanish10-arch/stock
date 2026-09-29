/* Calculator page: buy/sell cost, bonus/right, WACC, break-even, dividend yield, XIRR, price adjustment. */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { calculator } from "../api";
import { Card, ErrorState, Missing, Table } from "../components/ui";
import { fmtInt, fmtNum, fmtPct, fmtRs } from "../format";

type CalcType = "buy-sell" | "bonus-right" | "wacc" | "break-even" | "dividend-yield" | "xirr" | "adjust-price";

const CALCULATORS: { value: CalcType; label: string; description: string }[] = [
  { value: "buy-sell", label: "Buy/Sell Cost", description: "Calculate total cost including broker, SEBON, DP, STT" },
  { value: "bonus-right", label: "Bonus/Right Impact", description: "Calculate new quantity and cost after bonus/right issue" },
  { value: "wacc", label: "WACC (Weighted Avg Cost)", description: "Calculate FIFO weighted average cost per share" },
  { value: "break-even", label: "Break-Even Price", description: "Calculate break-even price and % from current price" },
  { value: "dividend-yield", label: "Dividend Yield", description: "Calculate yield on LTP and cost basis" },
  { value: "xirr", label: "XIRR", description: "Calculate Extended IRR from cashflows" },
  { value: "adjust-price", label: "Price Adjustment", description: "Adjust price for bonus/right issues" },
];

export function CalculatorPage() {
  const [calcType, setCalcType] = useState<CalcType>("buy-sell");
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  // Form state
  const [form, setForm] = useState<Record<string, any>>({});

  const mutate = useMutation({
    mutationFn: async () => {
      setIsLoading(true);
      setError(null);
      try {
        let res;
        switch (calcType) {
          case "buy-sell":
            res = await calculator.buySell(form.quantity, form.price, form.side);
            break;
          case "bonus-right":
            res = await calculator.bonusRight(form.original_quantity, form.bonus_ratio, form.right_ratio, form.right_price);
            break;
          case "wacc":
            res = await calculator.wacc(form.transactions);
            break;
          case "break-even":
            res = await calculator.breakEven(form.avg_cost, form.current_price);
            break;
          case "dividend-yield":
            res = await calculator.dividendYield(form.face_value, form.cash_dividend_pct, form.ltp, form.avg_cost);
            break;
          case "xirr":
            res = await calculator.xirr(form.cashflows);
            break;
          case "adjust-price":
            res = await calculator.adjustPrice(form.symbol, form.original_price, form.bonus_events, form.right_events);
            break;
        }
        setResult(res);
        return res;
      } catch (e: any) {
        setError(e.message || "Calculation failed");
        throw e;
      } finally {
        setIsLoading(false);
      }
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    mutate.mutate();
  };

  const handleChange = (key: string, value: any) => {
    setForm(prev => ({ ...prev, [key]: value }));
  };

  const renderForm = () => {
    const c = CALCULATORS.find(c => c.value === calcType);
    if (!c) return null;

    switch (calcType) {
      case "buy-sell":
        return (
          <form onSubmit={handleSubmit}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "var(--space-4)" }}>
              <label className="field">
                <span className="field-label">Quantity</span>
                <input className="input" type="number" value={form.quantity || ""} onChange={e => handleChange("quantity", Number(e.target.value))} required min={1} />
              </label>
              <label className="field">
                <span className="field-label">Price (Rs)</span>
                <input className="input" type="number" step="0.01" value={form.price || ""} onChange={e => handleChange("price", Number(e.target.value))} required min={0.01} />
              </label>
              <label className="field">
                <span className="field-label">Side</span>
                <select className="select" value={form.side || "buy"} onChange={e => handleChange("side", e.target.value)}>
                  <option value="buy">Buy</option>
                  <option value="sell">Sell</option>
                </select>
              </label>
            </div>
            <button type="submit" className="btn btn-primary" disabled={isLoading} style={{ marginTop: "var(--space-4)" }}>
              {isLoading ? "Calculating…" : "Calculate"}
            </button>
          </form>
        );

      case "bonus-right":
        return (
          <form onSubmit={handleSubmit}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "var(--space-4)" }}>
              <label className="field">
                <span className="field-label">Original Quantity</span>
                <input className="input" type="number" value={form.original_quantity || ""} onChange={e => handleChange("original_quantity", Number(e.target.value))} required min={1} />
              </label>
              <label className="field">
                <span className="field-label">Bonus Ratio (e.g., 0.1 for 1:10)</span>
                <input className="input" type="number" step="0.01" value={form.bonus_ratio || 0} onChange={e => handleChange("bonus_ratio", Number(e.target.value))} min={0} />
              </label>
              <label className="field">
                <span className="field-label">Right Ratio (e.g., 0.5 for 1:2)</span>
                <input className="input" type="number" step="0.01" value={form.right_ratio || 0} onChange={e => handleChange("right_ratio", Number(e.target.value))} min={0} />
              </label>
              <label className="field">
                <span className="field-label">Right Price (Rs, optional)</span>
                <input className="input" type="number" step="0.01" value={form.right_price || ""} onChange={e => handleChange("right_price", e.target.value ? Number(e.target.value) : undefined)} min={0} />
              </label>
            </div>
            <button type="submit" className="btn btn-primary" disabled={isLoading} style={{ marginTop: "var(--space-4)" }}>
              {isLoading ? "Calculating…" : "Calculate"}
            </button>
          </form>
        );

      case "wacc":
        return (
          <form onSubmit={handleSubmit}>
            <label className="field">
              <span className="field-label">Transactions (JSON array)</span>
              <textarea
                className="input"
                value={JSON.stringify(form.transactions || [], null, 2)}
                onChange={e => {
                  try {
                    handleChange("transactions", JSON.parse(e.target.value));
                  } catch { /* ignore */ }
                }}
                rows={8}
                style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-sm)" }}
                placeholder='[{"date": "2026-01-01", "side": "buy", "quantity": 100, "price": 500, "fees": 100}, {"date": "2026-06-01", "side": "buy", "quantity": 50, "price": 550}]'
              />
            </label>
            <p className="hint">Each transaction: date (YYYY-MM-DD), side (buy/sell), quantity, price, fees (optional)</p>
            <button type="submit" className="btn btn-primary" disabled={isLoading} style={{ marginTop: "var(--space-4)" }}>
              {isLoading ? "Calculating…" : "Calculate"}
            </button>
          </form>
        );

      case "break-even":
        return (
          <form onSubmit={handleSubmit}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "var(--space-4)" }}>
              <label className="field">
                <span className="field-label">Average Cost (Rs)</span>
                <input className="input" type="number" step="0.01" value={form.avg_cost || ""} onChange={e => handleChange("avg_cost", Number(e.target.value))} required min={0.01} />
              </label>
              <label className="field">
                <span className="field-label">Current Price (Rs, optional)</span>
                <input className="input" type="number" step="0.01" value={form.current_price || ""} onChange={e => handleChange("current_price", e.target.value ? Number(e.target.value) : undefined)} min={0} />
              </label>
            </div>
            <button type="submit" className="btn btn-primary" disabled={isLoading} style={{ marginTop: "var(--space-4)" }}>
              {isLoading ? "Calculating…" : "Calculate"}
            </button>
          </form>
        );

      case "dividend-yield":
        return (
          <form onSubmit={handleSubmit}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "var(--space-4)" }}>
              <label className="field">
                <span className="field-label">Face Value (Rs)</span>
                <input className="input" type="number" step="0.01" value={form.face_value || ""} onChange={e => handleChange("face_value", Number(e.target.value))} required min={0.01} />
              </label>
              <label className="field">
                <span className="field-label">Cash Dividend %</span>
                <input className="input" type="number" step="0.01" value={form.cash_dividend_pct || ""} onChange={e => handleChange("cash_dividend_pct", Number(e.target.value))} required min={0} />
              </label>
              <label className="field">
                <span className="field-label">LTP (Rs, optional)</span>
                <input className="input" type="number" step="0.01" value={form.ltp || ""} onChange={e => handleChange("ltp", e.target.value ? Number(e.target.value) : undefined)} min={0} />
              </label>
              <label className="field">
                <span className="field-label">Avg Cost (Rs, optional)</span>
                <input className="input" type="number" step="0.01" value={form.avg_cost || ""} onChange={e => handleChange("avg_cost", e.target.value ? Number(e.target.value) : undefined)} min={0} />
              </label>
            </div>
            <button type="submit" className="btn btn-primary" disabled={isLoading} style={{ marginTop: "var(--space-4)" }}>
              {isLoading ? "Calculating…" : "Calculate"}
            </button>
          </form>
        );

      case "xirr":
        return (
          <form onSubmit={handleSubmit}>
            <label className="field">
              <span className="field-label">Cashflows (JSON array)</span>
              <textarea
                className="input"
                value={JSON.stringify(form.cashflows || [], null, 2)}
                onChange={e => {
                  try {
                    handleChange("cashflows", JSON.parse(e.target.value));
                  } catch { /* ignore */ }
                }}
                rows={8}
                style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-sm)" }}
                placeholder='[{"date": "2026-01-01", "amount": -10000}, {"date": "2026-06-01", "amount": 500}, {"date": "2026-12-31", "amount": 11000}]'
              />
            </label>
            <p className="hint">Negative = investment (buy), Positive = return (sell/dividend). Need at least one negative and one positive.</p>
            <button type="submit" className="btn btn-primary" disabled={isLoading} style={{ marginTop: "var(--space-4)" }}>
              {isLoading ? "Calculating…" : "Calculate"}
            </button>
          </form>
        );

      case "adjust-price":
        return (
          <form onSubmit={handleSubmit}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "var(--space-4)" }}>
              <label className="field">
                <span className="field-label">Symbol</span>
                <input className="input" type="text" value={form.symbol || ""} onChange={e => handleChange("symbol", e.target.value.toUpperCase())} required placeholder="NABIL" />
              </label>
              <label className="field">
                <span className="field-label">Original Price (Rs)</span>
                <input className="input" type="number" step="0.01" value={form.original_price || ""} onChange={e => handleChange("original_price", Number(e.target.value))} required min={0.01} />
              </label>
            </div>
            <label className="field">
              <span className="field-label">Bonus Events (JSON array)</span>
              <textarea
                className="input"
                value={JSON.stringify(form.bonus_events || [], null, 2)}
                onChange={e => {
                  try {
                    handleChange("bonus_events", JSON.parse(e.target.value));
                  } catch { /* ignore */ }
                }}
                rows={4}
                style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-sm)" }}
                placeholder='[{"date": "2026-01-01", "ratio": 0.1}]'
              />
            </label>
            <label className="field">
              <span className="field-label">Right Events (JSON array)</span>
              <textarea
                className="input"
                value={JSON.stringify(form.right_events || [], null, 2)}
                onChange={e => {
                  try {
                    handleChange("right_events", JSON.parse(e.target.value));
                  } catch { /* ignore */ }
                }}
                rows={4}
                style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-sm)" }}
                placeholder='[{"date": "2026-01-01", "ratio": 0.5, "price": 100}]'
              />
            </label>
            <button type="submit" className="btn btn-primary" disabled={isLoading} style={{ marginTop: "var(--space-4)" }}>
              {isLoading ? "Calculating…" : "Calculate"}
            </button>
          </form>
        );
    }
  };

  const renderResult = () => {
    if (!result) return null;

    switch (calcType) {
      case "buy-sell":
        return (
          <Card title="Buy/Sell Cost Result">
            <div className="stat-row">
              <div className="stat"><span className="stat-label">Gross Amount</span><span className="stat-value">{fmtRs(result.gross_amount)}</span></div>
              <div className="stat"><span className="stat-label">Broker Commission (0.275%)</span><span className="stat-value">{fmtRs(result.broker_commission)}</span></div>
              <div className="stat"><span className="stat-label">SEBON Fee (0.015%)</span><span className="stat-value">{fmtRs(result.sebon_fee)}</span></div>
              <div className="stat"><span className="stat-label">DP Charge (Rs 25)</span><span className="stat-value">{fmtRs(result.dp_charge)}</span></div>
              <div className="stat"><span className="stat-label">STT (0.15%, sell only)</span><span className="stat-value">{fmtRs(result.stt)}</span></div>
              <div className="stat"><span className="stat-label">Total Fees</span><span className="stat-value">{fmtRs(result.total_fees)}</span></div>
              <div className="stat"><span className="stat-label">Net Amount</span><span className="stat-value big-num">{fmtRs(result.net_amount)}</span></div>
            </div>
          </Card>
        );
      case "bonus-right":
        return (
          <Card title="Bonus/Right Impact Result">
            <div className="stat-row">
              <div className="stat"><span className="stat-label">Original Quantity</span><span className="stat-value">{fmtInt(result.original_quantity)}</span></div>
              <div className="stat"><span className="stat-label">Bonus Shares</span><span className="stat-value">{fmtInt(result.bonus_shares)}</span></div>
              <div className="stat"><span className="stat-label">Right Shares</span><span className="stat-value">{fmtInt(result.right_shares)}</span></div>
              <div className="stat"><span className="stat-label">New Quantity</span><span className="stat-value big-num">{fmtInt(result.new_quantity)}</span></div>
              <div className="stat"><span className="stat-label">Additional Cost</span><span className="stat-value">{fmtRs(result.additional_cost)}</span></div>
            </div>
          </Card>
        );
      case "wacc":
        return (
          <Card title="WACC Result">
            <div className="stat-row">
              <div className="stat"><span className="stat-label">Total Quantity</span><span className="stat-value">{fmtInt(result.total_quantity)}</span></div>
              <div className="stat"><span className="stat-label">Total Cost</span><span className="stat-value">{fmtRs(result.total_cost)}</span></div>
              <div className="stat"><span className="stat-label">WACC (per share)</span><span className="stat-value big-num">{fmtRs(result.wacc)}</span></div>
            </div>
          </Card>
        );
      case "break-even":
        return (
          <Card title="Break-Even Result">
            <div className="stat-row">
              <div className="stat"><span className="stat-label">Average Cost</span><span className="stat-value">{fmtRs(result.avg_cost)}</span></div>
              <div className="stat"><span className="stat-label">Break-Even Price</span><span className="stat-value big-num">{fmtRs(result.break_even_price)}</span></div>
              <div className="stat"><span className="stat-label">Break-Even %</span><span className={`stat-value ${result.break_even_pct >= 0 ? "up" : "down"}`}>{result.break_even_pct >= 0 ? "+" : ""}{fmtPct(result.break_even_pct)}%</span></div>
            </div>
          </Card>
        );
      case "dividend-yield":
        return (
          <Card title="Dividend Yield Result">
            <div className="stat-row">
              <div className="stat"><span className="stat-label">Dividend per Share</span><span className="stat-value">{fmtRs(result.dividend_per_share)}</span></div>
              <div className="stat"><span className="stat-label">Yield on LTP</span><span className="stat-value">{result.yield_on_ltp != null ? fmtPct(result.yield_on_ltp) + "%" : <Missing reason="LTP not provided" />}</span></div>
              <div className="stat"><span className="stat-label">Yield on Cost</span><span className="stat-value">{result.yield_on_cost != null ? fmtPct(result.yield_on_cost) + "%" : <Missing reason="Avg cost not provided" />}</span></div>
            </div>
          </Card>
        );
      case "xirr":
        return (
          <Card title="XIRR Result">
            <div className="stat-row">
              <div className="stat"><span className="stat-label">XIRR</span><span className={`stat-value big-num ${result.xirr_pct != null && result.xirr_pct >= 0 ? "up" : result.xirr_pct != null ? "down" : ""}`}>{result.xirr_pct != null ? fmtPct(result.xirr_pct / 100) + "%" : <Missing reason="Could not compute" />}</span></div>
              <div className="stat"><span className="stat-label">Iterations</span><span className="stat-value">{fmtInt(result.iterations)}</span></div>
            </div>
            {result.cashflows && result.cashflows.length > 0 && (
              <Table<{ date: string; amount: number }>
                rows={result.cashflows}
                rowKey={(row) => row.date}
                columns={[
                  { key: "date", header: "Date", render: (row) => row.date },
                  { key: "amount", header: "Amount", align: "right", render: (row) => fmtRs(row.amount) },
                ]}
                empty="No cashflows"
              />
            )}
          </Card>
        );
      case "adjust-price":
        return (
          <Card title="Price Adjustment Result">
            <div className="stat-row">
              <div className="stat"><span className="stat-label">Original Price</span><span className="stat-value">{fmtRs(result.original_price)}</span></div>
              <div className="stat"><span className="stat-label">Adjusted Price</span><span className="stat-value big-num">{fmtRs(result.adjusted_price)}</span></div>
              <div className="stat"><span className="stat-label">Adjustment Factor</span><span className="stat-value">{fmtNum(result.adjustment_factor, 4)}</span></div>
            </div>
          </Card>
        );
    }
  };

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Calculators</h1>
          <p className="page-sub">Trading cost, corporate action impact, returns and valuation helpers.</p>
        </div>
      </header>

      <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: "var(--space-4)" }}>
        <Card title="Calculators">
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
            {CALCULATORS.map((c) => (
              <button
                key={c.value}
                type="button"
                className={`calc-tab${calcType === c.value ? " active" : ""}`}
                style={{ textAlign: "left", padding: "var(--space-3) var(--space-4)", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", background: calcType === c.value ? "var(--accent-soft)" : "var(--surface)", color: calcType === c.value ? "var(--accent)" : "var(--text)", cursor: "pointer", transition: "all var(--dur-fast) var(--ease)" }}
                onClick={() => { setCalcType(c.value); setResult(null); setForm({}); }}
              >
                <strong>{c.label}</strong>
                <br />
                <span className="muted" style={{ fontSize: "var(--text-xs)" }}>{c.description}</span>
              </button>
            ))}
          </div>
        </Card>

        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
          <Card title={CALCULATORS.find(c => c.value === calcType)?.label}>
            {error && <ErrorState error={new Error(error)} />}
            {renderForm()}
          </Card>
          {renderResult()}
        </div>
      </div>
    </div>
  );
}
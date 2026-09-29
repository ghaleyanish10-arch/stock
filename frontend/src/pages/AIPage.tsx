/* AI Assistant page: grounded Q&A with NEPSE data. */

import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { ai, reference } from "../api";
import { Card, ErrorState, Loading } from "../components/ui";
import { fmtInt } from "../format";

export function AIPage() {
  const [question, setQuestion] = useState("");
  const [symbols, setSymbols] = useState<string[]>([]);
  const [dataSources, setDataSources] = useState<string[]>([]);
  const [privacyConsent, setPrivacyConsent] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [answer, setAnswer] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const availableSources = [
    "live_market",
    "archive",
    "corporate_actions",
    "news",
    "reference",
    "calculator",
    "quarterly",
  ] as const;

  // AI status
  const { data: status, isLoading: statusLoading } = useQuery({
    queryKey: ["ai-status"],
    queryFn: () => ai.statusPublic(),
    staleTime: 60_000,
  });

  // Symbol suggestions
  const { data: securities } = useQuery({
    queryKey: ["securities-for-ai"],
    queryFn: () => reference.securities(undefined, true),
    staleTime: 5 * 60_000,
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    setError(null);
    setAnswer(null);

    try {
      if (streaming) {
        await handleStream();
      } else {
        await handleAsk();
      }
    } catch (e: any) {
      setError(e.message || "Failed to get answer");
    }
  };

  const handleAsk = async () => {
    setIsLoading(true);
    try {
      const res = await ai.ask({
        question: question.trim(),
        symbols,
        data_sources: dataSources,
        privacy_consent: privacyConsent,
      });
      setAnswer(res.answer);
    } finally {
      setIsLoading(false);
    }
  };

  const handleStream = async () => {
    setIsLoading(true);
    setAnswer("");
    try {
      const stream = await ai.stream({
        question: question.trim(),
        symbols,
        data_sources: dataSources,
        privacy_consent: privacyConsent,
      });

      if (!stream) throw new Error("No stream returned");

      const reader = stream.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const data = line.slice(6);
            if (data === "[DONE]") return;
            try {
              const parsed = JSON.parse(data);
              setAnswer((prev) => (prev || "") + parsed.chunk);
            } catch { /* ignore parse errors */ }
          }
        }
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleSymbolAdd = (symbol: string) => {
    const upper = symbol.toUpperCase();
    if (!symbols.includes(upper)) {
      setSymbols([...symbols, upper]);
    }
  };

  const handleSymbolRemove = (symbol: string) => {
    setSymbols(symbols.filter((s) => s !== symbol));
  };

  const handleSourceToggle = (source: string) => {
    setDataSources((prev) =>
      prev.includes(source) ? prev.filter((s) => s !== source) : [...prev, source]
    );
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  // Auto-scroll when answer changes
  if (answer) scrollToBottom();

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>AI Assistant</h1>
          <p className="page-sub">
            Ask questions grounded in NEPSE data. No buy/sell recommendations.
            {status?.privacy_consent_required && <span className="badge badge-warn"> Privacy consent required </span>}
            {!status?.configured && <span className="badge badge-info"> Demo mode (no LLM configured) </span>}
          </p>
        </div>
        <div className="page-head-actions">
          <label className="checkbox" style={{ marginLeft: "var(--space-4)" }}>
            <input
              type="checkbox"
              checked={streaming}
              onChange={(e) => setStreaming(e.target.checked)}
            />
            <span>Stream response</span>
          </label>
        </div>
      </header>

      {statusLoading && <Loading label="Checking AI status" />}
      {!statusLoading && status && !status.configured && (
        <div className="notice notice-info" style={{ marginBottom: "var(--space-4)" }}>
          <strong>AI not configured.</strong> Set <code>LLM_PROVIDER</code>, <code>LLM_MODEL</code>, and <code>LLM_API_KEY</code>
          environment variables to enable a real LLM. Currently running in demo mode with fake responses.
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: "var(--space-4)" }}>
        <Card title="Ask a Question">
          <form onSubmit={handleSubmit}>
            <label className="field" style={{ marginBottom: "var(--space-4)" }}>
              <span className="field-label">Your Question</span>
              <textarea
                className="input"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                rows={4}
                placeholder="e.g., What was NABIL's dividend yield in FY 2083/84? How does banking sector P/E compare to market?"
                disabled={isLoading}
              />
            </label>

            <div style={{ marginBottom: "var(--space-4)" }}>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={privacyConsent}
                  onChange={(e) => setPrivacyConsent(e.target.checked)}
                />
                <span>
                  I consent to sending my question to the AI provider for processing.
                  <a href="/settings#privacy" target="_blank" rel="noopener"> Privacy policy</a>
                </span>
              </label>
            </div>

            <div style={{ display: "flex", gap: "var(--space-2)", marginBottom: "var(--space-4)" }}>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={isLoading || !question.trim() || !privacyConsent}
              >
                {isLoading ? "Thinking…" : "Ask"}
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => { setQuestion(""); setAnswer(null); setError(null); }}
                disabled={isLoading}
              >
                Clear
              </button>
            </div>

            {error && <ErrorState error={new Error(error)} />}
          </form>

          {answer && (
            <div className="answer" style={{ marginTop: "var(--space-4)", padding: "var(--space-4)", background: "var(--bg-elevated)", borderRadius: "var(--radius)", whiteSpace: "pre-wrap" }}>
              {answer}
            </div>
          )}
          <div ref={messagesEndRef} />
        </Card>

        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
          <Card title="Context">
            <div style={{ marginBottom: "var(--space-4)" }}>
              <label className="field">
                <span className="field-label">Symbols (optional)</span>
                <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                  <input
                    className="input"
                    placeholder="e.g., NABIL"
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && e.currentTarget.value.trim()) {
                        handleSymbolAdd(e.currentTarget.value);
                        e.currentTarget.value = "";
                      }
                    }}
                  />
{symbols.map((s) => (
                    <button
                      key={s}
                      type="button"
                      className="badge badge-info"
                      style={{ cursor: "pointer", padding: "2px 8px", border: "none", background: "var(--info)", color: "white", borderRadius: "var(--radius-sm)", fontSize: "var(--text-xs)" }}
                      onClick={() => handleSymbolRemove(s)}
                    >
                      {s}
                    </button>
                  ))}
                </div>
                {securities?.securities && (
                  <datalist id="symbol-suggestions">
                    {securities.securities.slice(0, 50).map((sec) => (
                      <option key={sec.symbol} value={sec.symbol} />
                    ))}
                  </datalist>
                )}
              </label>
            </div>

            <div style={{ marginBottom: "var(--space-4)" }}>
              <label className="field">
                <span className="field-label">Data Sources</span>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-2)" }}>
                  {availableSources.map((src) => (
                    <label key={src} className="checkbox" style={{ marginRight: "var(--space-4)" }}>
                      <input
                        type="checkbox"
                        checked={dataSources.includes(src)}
                        onChange={() => handleSourceToggle(src)}
                      />
                      <span>{src}</span>
                    </label>
                  ))}
                </div>
              </label>
            </div>
          </Card>

          <Card title="AI Status">
            <div className="stat-row">
              <div className="stat"><span className="stat-label">Provider</span><span className="stat-value">{status?.provider || "unknown"}</span></div>
              <div className="stat"><span className="stat-label">Model</span><span className="stat-value">{status?.model || "unknown"}</span></div>
              <div className="stat"><span className="stat-label">Configured</span><span className="stat-value">{status?.configured ? "Yes" : "No (demo mode)"}</span></div>
            </div>
            <div className="stat-row">
              <div className="stat"><span className="stat-label">Rate Limit</span><span className="stat-value">{fmtInt(status?.rate_limit_per_minute || 20)}/min</span></div>
              <div className="stat"><span className="stat-label">Daily Limit</span><span className="stat-value">{fmtInt(status?.daily_limit || 50)}/day</span></div>
            </div>
          </Card>

          <Card title="Example Questions">
            <ul style={{ fontSize: "var(--text-sm)", lineHeight: 1.8 }}>
              <li><code>What is NABIL's current dividend yield?</code></li>
              <li><code>Show me banking sector P/E ratios</code></li>
              <li><code>Which stocks announced bonus shares this quarter?</code></li>
              <li><code>Calculate break-even for 100 shares bought at Rs 500</code></li>
              <li><code>Compare NABIL vs NTC valuation metrics</code></li>
              <li><code>What are the upcoming book closure dates?</code></li>
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}
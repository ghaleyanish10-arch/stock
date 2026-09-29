/* Alerts page: manage notification channels and alert rules. */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { alerts } from "../api";
import { Card, EmptyState, ErrorState, Loading, Missing, Table, Badge } from "../components/ui";
import { fmtInt } from "../format";

interface RuleKindParam {
  key: string;
  label: string;
  type: "number" | "text";
  default?: number | string;
}

interface RuleKind {
  value: string;
  label: string;
  params: RuleKindParam[];
}

const RULE_KINDS: RuleKind[] = [
  { value: "price_above", label: "Price Above", params: [{ key: "threshold", label: "Threshold", type: "number" }] },
  { value: "price_below", label: "Price Below", params: [{ key: "threshold", label: "Threshold", type: "number" }] },
  { value: "volume_spike", label: "Volume Spike", params: [{ key: "threshold", label: "Multiplier (e.g., 2 for 2x)", type: "number", default: 2 }] },
  { value: "announcement", label: "New Announcement", params: [{ key: "types", label: "Types (comma-separated)", type: "text", default: "dividend,bonus,rights,agm,book_closure" }] },
  { value: "book_closure", label: "Book Closure Approaching", params: [{ key: "days_ahead", label: "Days Ahead", type: "number", default: 7 }] },
  { value: "agm_approaching", label: "AGM Approaching", params: [{ key: "days_ahead", label: "Days Ahead", type: "number", default: 7 }] },
];

export function AlertsPage() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<"channels" | "rules">("channels");
  const [showCreateChannel, setShowCreateChannel] = useState(false);
  const [showCreateRule, setShowCreateRule] = useState(false);
  const [newChannelType, setNewChannelType] = useState<"email" | "telegram" | "in_app">("email");
  const [newChannelConfig, setNewChannelConfig] = useState<Record<string, any>>({});
  const [newRuleKind, setNewRuleKind] = useState(RULE_KINDS[0].value);
  const [newRuleSymbol, setNewRuleSymbol] = useState("");
  const [newRuleParams, setNewRuleParams] = useState<Record<string, any>>({});
  const [newRuleChannelId, setNewRuleChannelId] = useState<string | undefined>();
  const [newRuleCooldown, setNewRuleCooldown] = useState(300);
  const [newRuleOneShot, setNewRuleOneShot] = useState(false);

  // Channels
  const { data: channelsData, isLoading: channelsLoading, error: channelsError } = useQuery({
    queryKey: ["alert-channels"],
    queryFn: () => alerts.listChannels(),
  });

  // Rules
  const { data: rulesData, isLoading: rulesLoading, error: rulesError } = useQuery({
    queryKey: ["alert-rules"],
    queryFn: () => alerts.listRules(),
  });

  // Mutations
  const createChannelMut = useMutation({
    mutationFn: ({ channel_type, config }: { channel_type: "email" | "telegram" | "in_app"; config: Record<string, any> }) =>
      alerts.createChannel(channel_type, config),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alert-channels"] });
      setShowCreateChannel(false);
      setNewChannelType("email");
      setNewChannelConfig({});
    },
  });

  const deleteChannelMut = useMutation({
    mutationFn: (id: string) => alerts.deleteChannel(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alert-channels"] }),
  });

  const createRuleMut = useMutation({
    mutationFn: () => alerts.createRule({
      kind: newRuleKind,
      symbol: newRuleSymbol.toUpperCase() || undefined,
      params: newRuleParams,
      channel_id: newRuleChannelId,
      cooldown_seconds: newRuleCooldown,
      is_one_shot: newRuleOneShot,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alert-rules"] });
      setShowCreateRule(false);
      setNewRuleSymbol("");
      setNewRuleParams({});
      setNewRuleChannelId(undefined);
      setNewRuleCooldown(300);
      setNewRuleOneShot(false);
    },
  });

  const deleteRuleMut = useMutation({
    mutationFn: (id: string) => alerts.deleteRule(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alert-rules"] }),
  });

  const evaluateRuleMut = useMutation({
    mutationFn: ({ kind, symbol, params }: { kind: string; symbol: string; params: Record<string, any> }) =>
      alerts.evaluateRule(kind, symbol, params),
  });

  const handleCreateChannel = () => {
    // Validate based on channel type
    if (newChannelType === "email") {
      if (!newChannelConfig.email || !newChannelConfig.email.includes("@")) {
        alert("Please enter a valid email address");
        return;
      }
    } else if (newChannelType === "telegram") {
      if (!newChannelConfig.chat_id || !newChannelConfig.bot_token) {
        alert("Please enter both Chat ID and Bot Token for Telegram");
        return;
      }
    }
    // in_app requires no config
    
    createChannelMut.mutate({
      channel_type: newChannelType,
      config: newChannelConfig,
    });
  };

  const handleCreateRule = () => {
    createRuleMut.mutate();
  };

  const handleDeleteChannel = (id: string) => {
    if (confirm("Delete this notification channel?")) {
      deleteChannelMut.mutate(id);
    }
  };

  const handleDeleteRule = (id: string) => {
    if (confirm("Delete this alert rule?")) {
      deleteRuleMut.mutate(id);
    }
  };

  const handleTestRule = (rule: any) => {
    evaluateRuleMut.mutate({
      kind: rule.kind,
      symbol: rule.symbol || "",
      params: rule.params,
    });
  };

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Alerts</h1>
          <p className="page-sub">Configure notification channels and price/event rules.</p>
        </div>
      </header>

      <div className="seg-group" role="group" aria-label="Alert sections" style={{ marginBottom: "var(--space-4)" }}>
        <button
          type="button"
          className={`seg-btn ${activeTab === "channels" ? "is-active" : ""}`}
          aria-pressed={activeTab === "channels"}
          onClick={() => setActiveTab("channels")}
        >
          Channels
        </button>
        <button
          type="button"
          className={`seg-btn ${activeTab === "rules" ? "is-active" : ""}`}
          aria-pressed={activeTab === "rules"}
          onClick={() => setActiveTab("rules")}
        >
          Rules
        </button>
      </div>

      {activeTab === "channels" && (
        <>
          {channelsError && <ErrorState error={channelsError} />}
          {channelsLoading && <Loading label="Loading channels" />}

          {!channelsLoading && !channelsError && (
            <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
              <Card title="Notification Channels">
                <div className="page-head-actions" style={{ marginBottom: "var(--space-4)" }}>
                  <button type="button" className="btn btn-primary" onClick={() => setShowCreateChannel(true)}>
                    Add Channel
                  </button>
                </div>

                {channelsData?.channels.length === 0 ? (
                  <EmptyState message="No notification channels. Add one to receive alerts." />
                ) : (
                  <Table
                    rows={channelsData?.channels || []}
                    rowKey={(c) => c.id}
                    columns={[
                      { key: "type", header: "Type", render: (c) => <Badge tone={c.type === "email" ? "info" : c.type === "telegram" ? "warn" : "ok"}>{c.type}</Badge> },
                      {
                        key: "config",
                        header: "Config",
                        render: (c) => (
                          <pre style={{ fontSize: "var(--text-xs)", maxWidth: "300px", overflow: "auto" }}>
                            {JSON.stringify(c.config, null, 2)}
                          </pre>
                        ),
                      },
                      { key: "is_active", header: "Active", align: "center", render: (c) => c.is_active ? "✓" : "✗" },
                      { key: "is_verified", header: "Verified", align: "center", render: (c) => c.is_verified ? "✓" : "✗" },
                      {
                        key: "verified_at",
                        header: "Verified At",
                        render: (c) => c.verified_at ? new Date(c.verified_at).toLocaleString() : <Missing reason="Not verified" />,
                      },
                      {
                        key: "actions",
                        header: "",
                        render: (c) => (
                          <button
                            type="button"
                            className="btn btn-sm btn-danger"
                            onClick={() => handleDeleteChannel(c.id)}
                            disabled={deleteChannelMut.isPending}
                          >
                            Delete
                          </button>
                        ),
                      },
                    ]}
                    empty="No channels"
                  />
                )}
              </Card>

              {showCreateChannel && (
                <Card title="Add Notification Channel">
                  <label className="field">
                    <span className="field-label">Type</span>
                    <select
                      className="select"
                      value={newChannelType}
                      onChange={(e) => {
                        setNewChannelType(e.target.value as "email" | "telegram" | "in_app");
                        // Set default config template
                        const defaults: Record<string, any> = {
                          email: { email: "" },
                          telegram: { chat_id: "", bot_token: "" },
                          in_app: {},
                        };
                        setNewChannelConfig(defaults[e.target.value] || {});
                      }}
                    >
                      <option value="email">Email</option>
                      <option value="telegram">Telegram</option>
                      <option value="in_app">In-App</option>
                    </select>
                  </label>
                  
                  {newChannelType === "email" && (
                    <label className="field">
                      <span className="field-label">Email address</span>
                      <input
                        className="input"
                        type="email"
                        placeholder="user@example.com"
                        value={newChannelConfig.email || ""}
                        onChange={(e) => setNewChannelConfig({ ...newChannelConfig, email: e.target.value })}
                        required
                      />
                    </label>
                  )}
                  
{newChannelType === "telegram" && (
                    <div>
                      <label className="field">
                        <span className="field-label">Chat ID</span>
                        <input
                          className="input"
                          type="text"
                          placeholder="123456789 (from @userinfobot)"
                          value={newChannelConfig.chat_id || ""}
                          onChange={(e) => setNewChannelConfig({ ...newChannelConfig, chat_id: e.target.value })}
                          required
                        />
                      </label>
                      <label className="field">
                        <span className="field-label">Bot Token</span>
                        <input
                          className="input"
                          type="password"
                          placeholder="bot123456:ABC-DEF..."
                          value={newChannelConfig.bot_token || ""}
                          onChange={(e) => setNewChannelConfig({ ...newChannelConfig, bot_token: e.target.value })}
                          required
                        />
                      </label>
                      <p className="hint">Get Chat ID from <a href="https://t.me/userinfobot" target="_blank" rel="noopener">@userinfobot</a>. Create bot via <a href="https://t.me/BotFather" target="_blank" rel="noopener">@BotFather</a>.</p>
                    </div>
                  )}
                  
                  <div style={{ display: "flex", justifyContent: "flex-end", gap: "var(--space-2)", marginTop: "var(--space-4)" }}>
                    <button type="button" className="btn" onClick={() => setShowCreateChannel(false)}>Cancel</button>
                    <button type="button" className="btn btn-primary" onClick={handleCreateChannel} disabled={createChannelMut.isPending}>
                      {createChannelMut.isPending ? "Creating…" : "Create Channel"}
                    </button>
                  </div>
                </Card>
              )}

              <Card title="Channel Setup Notes">
                <ul style={{ fontSize: "var(--text-sm)", lineHeight: 1.6 }}>
                  <li><strong>Email:</strong> Requires SMTP configured in backend (<code>SMTP_HOST</code>, <code>SMTP_PORT</code>, <code>SMTP_USER</code>, <code>SMTP_PASS</code>). Shows "Not configured" if missing.</li>
                  <li><strong>Telegram:</strong> Requires <code>TELEGRAM_BOT_TOKEN</code> in backend. Bot must be added to chat; use <code>chat_id</code> from <code>@userinfobot</code>.</li>
                  <li><strong>In-App:</strong> Always works; notifications appear in the app (no external config needed).</li>
                  <li>Credentials are stored encrypted and never logged. Test messages are sent on channel creation if credentials exist.</li>
                </ul>
              </Card>
            </div>
          )}
        </>
      )}

      {activeTab === "rules" && (
        <>
          {rulesError && <ErrorState error={rulesError} />}
          {rulesLoading && <Loading label="Loading rules" />}

          {!rulesLoading && !rulesError && (
            <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
              <Card title="Alert Rules">
                <div className="page-head-actions" style={{ marginBottom: "var(--space-4)" }}>
                  <button type="button" className="btn btn-primary" onClick={() => setShowCreateRule(true)}>
                    Create Rule
                  </button>
                </div>

                {rulesData?.rules.length === 0 ? (
                  <EmptyState message="No alert rules. Create one to get notified." />
                ) : (
                  <Table
                    rows={rulesData?.rules || []}
                    rowKey={(r) => r.id}
                    columns={[
                      { key: "kind", header: "Type", render: (r) => <code>{r.kind}</code> },
                      { key: "symbol", header: "Symbol", render: (r) => r.symbol ? <strong>{r.symbol}</strong> : <Missing reason="All symbols" /> },
                      {
                        key: "params",
                        header: "Params",
                        render: (r) => (
                          <pre style={{ fontSize: "var(--text-xs)", maxWidth: "200px", overflow: "auto" }}>
                            {JSON.stringify(r.params, null, 2)}
                          </pre>
                        ),
                      },
                      { key: "channel_id", header: "Channel", render: (r) => r.channel_id ? <code>{r.channel_id.slice(0, 8)}…</code> : <Missing reason="None (in-app only)" /> },
                      { key: "cooldown_seconds", header: "Cooldown", align: "right", render: (r) => `${r.cooldown_seconds}s` },
                      { key: "is_one_shot", header: "One-shot", align: "center", render: (r) => r.is_one_shot ? "✓" : "✗" },
                      { key: "is_active", header: "Active", align: "center", render: (r) => r.is_active ? "✓" : "✗" },
                      { key: "trigger_count", header: "Triggers", align: "right", render: (r) => fmtInt(r.trigger_count) },
                      {
                        key: "actions",
                        header: "",
                        render: (r) => (
                          <div style={{ display: "flex", gap: "var(--space-2)" }}>
                            <button
                              type="button"
                              className="btn btn-sm"
                              onClick={() => handleTestRule(r)}
                              disabled={evaluateRuleMut.isPending}
                            >
                              Test
                            </button>
                            <button
                              type="button"
                              className="btn btn-sm btn-danger"
                              onClick={() => handleDeleteRule(r.id)}
                              disabled={deleteRuleMut.isPending}
                            >
                              Delete
                            </button>
                          </div>
                        ),
                      },
                    ]}
                    empty="No rules"
                  />
                )}
              </Card>

              {showCreateRule && (
                <Card title="Create Alert Rule">
                  <label className="field">
                    <span className="field-label">Rule Type</span>
                    <select
                      className="select"
                      value={newRuleKind}
                      onChange={(e) => {
                        setNewRuleKind(e.target.value);
                        const kind = RULE_KINDS.find(k => k.value === e.target.value);
                        if (kind) {
                          const defaults = kind.params.reduce((acc, p) => ({ ...acc, [p.key]: p.default }), {});
                          setNewRuleParams(defaults);
                        }
                      }}
                    >
                      {RULE_KINDS.map((k) => (
                        <option key={k.value} value={k.value}>{k.label}</option>
                      ))}
                    </select>
                  </label>

                  <label className="field">
                    <span className="field-label">Symbol (optional)</span>
                    <input
                      className="input"
                      placeholder="e.g., NABIL (empty = all symbols)"
                      value={newRuleSymbol}
                      onChange={(e) => setNewRuleSymbol(e.target.value.toUpperCase())}
                    />
                  </label>

                  <label className="field">
                    <span className="field-label">Parameters (JSON)</span>
                    <textarea
                      className="input"
                      value={JSON.stringify(newRuleParams, null, 2)}
                      onChange={(e) => {
                        try {
                          setNewRuleParams(JSON.parse(e.target.value));
                        } catch { /* ignore invalid JSON while typing */ }
                      }}
                      rows={4}
                      style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-sm)" }}
                    />
                  </label>

                  <label className="field">
                    <span className="field-label">Notification Channel (optional)</span>
                    <select
                      className="select"
                      value={newRuleChannelId || ""}
                      onChange={(e) => setNewRuleChannelId(e.target.value || undefined)}
                    >
                      <option value="">In-App only</option>
                      {(channelsData?.channels || []).map((c) => (
                        <option key={c.id} value={c.id}>{c.type} ({c.id.slice(0, 8)}…)</option>
                      ))}
                    </select>
                  </label>

                  <label className="field">
                    <span className="field-label">Cooldown (seconds)</span>
                    <input
                      className="input"
                      type="number"
                      value={newRuleCooldown}
                      onChange={(e) => setNewRuleCooldown(Number(e.target.value))}
                      min={60}
                    />
                  </label>

                  <label className="checkbox">
                    <input
                      type="checkbox"
                      checked={newRuleOneShot}
                      onChange={(e) => setNewRuleOneShot(e.target.checked)}
                    />
                    <span>One-shot (disable after first trigger)</span>
                  </label>

                  <div style={{ display: "flex", justifyContent: "flex-end", gap: "var(--space-2)", marginTop: "var(--space-4)" }}>
                    <button type="button" className="btn" onClick={() => setShowCreateRule(false)}>Cancel</button>
                    <button type="button" className="btn btn-primary" onClick={handleCreateRule} disabled={createRuleMut.isPending}>
                      {createRuleMut.isPending ? "Creating…" : "Create Rule"}
                    </button>
                  </div>
                </Card>
              )}

              {evaluateRuleMut.isSuccess && evaluateRuleMut.data && (
                <Card title="Test Result">
                  <div className="stat-row">
                    <div className="stat">
                      <span className="stat-label">Triggered</span>
                      <span className={`stat-value ${evaluateRuleMut.data.triggered ? "up" : "down"}`}>
                        {evaluateRuleMut.data.triggered ? "YES" : "NO"}
                      </span>
                    </div>
                  </div>
                  {evaluateRuleMut.data.result && (
                    <pre style={{ marginTop: "var(--space-2)", fontSize: "var(--text-xs)" }}>
                      {JSON.stringify(evaluateRuleMut.data.result, null, 2)}
                    </pre>
                  )}
                </Card>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
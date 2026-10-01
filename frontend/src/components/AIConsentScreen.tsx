/* AI Consent Screen: shows exact data fields sent, provider name, consent version,
 * grant and revoke buttons. Linked from AI page and Portfolio "AI review" when
 * consent is missing.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { auth, ai } from "../api";
import { Card, ErrorState, Loading, Stat } from "../components/ui";

// Current disclosure version - changing this MUST bump DISCLOSURE_VERSION
// The actual disclosure text is fetched from /api/ai/status/public
export const DISCLOSURE_VERSION = "1.0";

export function AIConsentScreen() {
  const queryClient = useQueryClient();
  const [disclosureOpen, setDisclosureOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: meData, isLoading } = useQuery({
    queryKey: ["me"],
    queryFn: ({ signal }) => auth.me(signal),
    staleTime: 30_000,
  });

  const { data: status } = useQuery({
    queryKey: ["ai-status"],
    queryFn: () => ai.statusPublic(),
    staleTime: 60_000,
  });

  // Fetch disclosure text from public endpoint
  const { data: disclosure } = useQuery({
    queryKey: ["ai-disclosure"],
    queryFn: () => ai.disclosurePublic(),
    staleTime: 60_000,
  });

  const grantMutation = useMutation({
    mutationFn: () => auth.setAIConsent(true, "1.0"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["me"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const revokeMutation = useMutation({
    mutationFn: () => auth.setAIConsent(false, "1.0"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["me"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  if (isLoading) return <Loading label="Loading consent status…" />;

  const me = meData as any;
  const hasConsent = me?.ai_consent === true;
  const consentVersion = me?.ai_consent_version ?? "none";
  const consentUpdated = me?.ai_consent_updated_at
    ? new Date(me.ai_consent_updated_at).toLocaleString()
    : "never";

  const disclosureText = disclosure?.disclosure_text ?? "";
  const disclosureVersion = disclosure?.disclosure_version ?? DISCLOSURE_VERSION;

  const [saving, setSaving] = useState(false);

  const handleGrant = () => {
    setSaving(true);
    grantMutation.mutate(undefined, {
      onSuccess: () => setSaving(false),
      onError: () => setSaving(false),
    });
  };

  const handleRevoke = () => {
    if (window.confirm("Revoke AI consent? All AI features will be disabled until you grant it again.")) {
      revokeMutation.mutate();
    }
  };

  return (
    <div className="page" style={{ maxWidth: "720px", margin: "0 auto" }}>
      <header className="page-head">
        <h1>AI Data Consent</h1>
        <p className="page-sub">
          Control what portfolio data is sent to the AI provider for analysis.
        </p>
      </header>

      <Card title="Current Status">
        <div className="stat-row">
          <Stat label="Consent">
            <span className={hasConsent ? "up" : "down"}>
              {hasConsent ? "Granted" : "Not granted"}
            </span>
          </Stat>
          <Stat label="Disclosure Version">{consentVersion || "not granted"}</Stat>
          <Stat label="Last Updated">{consentUpdated}</Stat>
        </div>
        <div style={{ marginTop: "var(--space-4)" }}>
          <Stat label="Provider">
            <span>{status?.provider || "unknown"}</span>
          </Stat>
          <Stat label="Model">
            <span>{status?.model || "unknown"}</span>
          </Stat>
          <Stat label="Configured">
            <span>{status?.configured ? "Yes" : "No (demo mode)"}</span>
          </Stat>
        </div>
        <div style={{ marginTop: "var(--space-4)", display: "flex", gap: "var(--space-3)", flexWrap: "wrap" }}>
          {hasConsent ? (
            <button className="btn btn-warn" onClick={handleRevoke} disabled={saving}>
              Revoke Consent
            </button>
          ) : (
            <button className="btn btn-primary" onClick={handleGrant} disabled={saving}>
              Grant Consent
            </button>
          )}
          <button className="btn" type="button" onClick={() => setDisclosureOpen(!disclosureOpen)}>
            {disclosureOpen ? "Hide Disclosure" : "View Full Disclosure"}
          </button>
        </div>
      </Card>

      <Card title="Full Disclosure">
        <div style={{ display: disclosureOpen ? "block" : "none" }}>
          <pre style={{ whiteSpace: "pre-wrap", fontSize: "var(--text-xs)", lineHeight: 1.6, fontFamily: "inherit" }}>
            {disclosureText}
          </pre>
          <div className="legend" style={{ marginTop: "var(--space-4)" }}>
            <span className="legend-title">Current Version:</span>
            <code>{disclosureVersion}</code>
          </div>
        </div>
      </Card>

      <Card title="What This Controls">
        <ul style={{ lineHeight: 1.8, fontSize: "var(--text-sm)" }}>
          <li><strong>AI Chat (/ask):</strong> Your question + selected symbols/sources → AI provider</li>
          <li><strong>Streaming Chat (/stream):</strong> Same data, streamed response</li>
          <li><strong>Portfolio AI Review:</strong> Your full portfolio data + question → AI provider</li>
          <li><strong>Without consent:</strong> All three endpoints return <code>403 Privacy consent required</code></li>
          <li><strong>Revoking:</strong> Takes effect on the very next request; no data is sent</li>
        </ul>
      </Card>

      {error && <ErrorState error={new Error(error)} />}
    </div>
  );
}

export function AIConsentBanner({ onGrant }: { onGrant: () => void }) {
  return (
    <div className="ai-consent-banner" style={{ borderColor: "var(--warn)", background: "rgba(255, 193, 7, 0.1)", border: "1px solid var(--warn)", borderRadius: "var(--radius)", padding: "var(--space-4)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "spaceBetween", gap: "var(--space-4)", flexWrap: "wrap" }}>
        <div>
          <strong>AI features require consent</strong>
          <p className="muted" style={{ marginTop: "var(--space-1)" }}>
            Your portfolio data will be sent to the AI provider. <a href="/settings/ai-consent">Grant or manage consent</a>.
          </p>
        </div>
        <button className="btn btn-primary" onClick={onGrant}>Grant Consent</button>
      </div>
    </div>
  );
}
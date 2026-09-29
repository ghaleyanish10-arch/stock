/* Sign in / register.
 *
 * Both actions return a JWT which `api.ts` attaches to later requests, so
 * signing in is all that is needed to unlock watchlists and profile settings.
 */

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { Card, ErrorState, Field } from "../components/ui";

export function SignInPage() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "in") await login(email, password);
      else await register(email, password, displayName || undefined);
      navigate("/");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page page-narrow">
      <Card title={mode === "in" ? "Sign in" : "Create an account"}>
        <form onSubmit={submit} className="form">
          <Field label="Email" hint={mode === "up" ? "Used to sign in. Not sent anywhere yet." : undefined}>
            <input
              className="input"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
            />
          </Field>

          {mode === "up" && (
            <Field label="Display name" hint="Optional. Shown in the header instead of your email.">
              <input
                className="input"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                autoComplete="name"
                maxLength={120}
              />
            </Field>
          )}

          <Field
            label="Password"
            hint={mode === "up" ? "At least 1 character. No complexity rules enforced." : undefined}
          >
            <input
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "in" ? "current-password" : "new-password"}
              required
            />
          </Field>

          {error != null && <ErrorState error={error} />}

          <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
            {busy ? "Working…" : mode === "in" ? "Sign in" : "Create account"}
          </button>
        </form>

        <p className="muted">
          {mode === "in" ? (
            <>
              No account?{" "}
              <button type="button" className="linkish" onClick={() => setMode("up")}>
                Create one
              </button>
            </>
          ) : (
            <>
              Already registered?{" "}
              <button type="button" className="linkish" onClick={() => setMode("in")}>
                Sign in
              </button>
            </>
          )}
        </p>
        <p className="muted">
          <Link to="/">Back to the market overview</Link>
        </p>
      </Card>
    </div>
  );
}

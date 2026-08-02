import { useState, type FormEvent } from "react";

import { BrandMark } from "../components/Shell";
import { useAction, useBranding, useSession, useTheme } from "../lib/hooks";

export function SignIn() {
  const { signIn } = useSession();
  const { branding } = useBranding();
  const { theme, setTheme } = useTheme();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const { run, running, error } = useAction((id: string, secret: string) => signIn(id, secret));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void run(identifier, password);
  };

  return (
    <div className="auth">
      <div className="auth-shell">
        {/* The mark sits above the card, not inside it. The card is the task;
            the wordmark is where you are. */}
        <div className="auth-brand">
          <span className="brand-mark">
            {branding.logo_url ? (
              <img className="brand-logo brand-logo-lg" src={branding.logo_url} alt="" />
            ) : (
              <BrandMark size={26} />
            )}
          </span>
          <span className="wordmark">{branding.display_name}</span>
        </div>

        <form className="auth-card" onSubmit={submit}>
          <h1 style={{ fontSize: 21, marginBottom: 4 }}>Sign in</h1>
          <p className="small muted" style={{ marginBottom: 22 }}>
            {branding.tagline ?? "Research and collections platform."}
          </p>

          <div className="col">
            {error && (
              <div className="alert alert-danger" role="alert">
                {error}
              </div>
            )}

            <div className="field">
              <label className="field-label" htmlFor="identifier">
                E-mail or username
              </label>
              <input
                id="identifier"
                className="input"
                value={identifier}
                autoComplete="username"
                autoFocus
                required
                onChange={(event) => setIdentifier(event.target.value)}
              />
            </div>

            <div className="field">
              <label className="field-label" htmlFor="password">
                Password
              </label>
              <input
                id="password"
                className="input"
                type="password"
                value={password}
                autoComplete="current-password"
                placeholder="••••••••"
                required
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>

            <button
              type="submit"
              className="btn btn-primary btn-lg"
              disabled={running}
              style={{ width: "100%" }}
            >
              {running && <span className="spinner" />}
              {running ? "Signing in…" : "Sign in"}
            </button>

            <div className="row-between small">
              <span className="muted">Forgotten password? Ask an administrator.</span>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() =>
                  setTheme(theme === "dark" ? "light" : theme === "light" ? "system" : "dark")
                }
              >
                {theme === "system" ? "Auto" : theme === "dark" ? "Dark" : "Light"}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}

import { useState, type FormEvent } from "react";

import { useAction, useSession } from "../lib/hooks";

export function SignIn() {
  const { signIn } = useSession();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const { run, running, error } = useAction((id: string, secret: string) => signIn(id, secret));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void run(identifier, password);
  };

  return (
    <div className="auth">
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-brand">
          <span className="brand-mark" aria-hidden="true" />
          <div>
            <h2 style={{ fontSize: "var(--text-lg)" }}>Archeo</h2>
            <div className="small muted">Archaeological research &amp; heritage management</div>
          </div>
        </div>

        <div className="col" style={{ gap: "var(--space-4)" }}>
          {error && <div className="alert alert-danger">{error}</div>}

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
              required
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>

          <button type="submit" className="btn btn-primary btn-lg" disabled={running}>
            {running ? <span className="spinner" /> : null}
            {running ? "Signing in…" : "Sign in"}
          </button>
        </div>
      </form>
    </div>
  );
}

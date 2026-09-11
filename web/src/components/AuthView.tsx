import { useState, type FormEvent } from "react";
import { ApiError, api, errorText } from "../api";

export function AuthView({ onAuthed }: { onAuthed: () => void }) {
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "signup") await api.register(email, password);
      await api.login(email, password);
      onAuthed();
    } catch (err) {
      // Registration answers the same way for new and existing emails, so a
      // failed login right after it usually means the account already existed.
      if (mode === "signup" && err instanceof ApiError && err.status === 401) {
        setError("If this email already has an account, sign in with that account's password.");
      } else {
        setError(errorText(err));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <section className="intro">
        <h1>See where your personal data is exposed.</h1>
        <p className="lead">
          Footprint searches the public web for your own details, checks your email against known breaches, and
          turns what it finds into a plan: opt-out links, removal letters ready to send, and steps to lock down your
          accounts.
        </p>
        <ul className="facts">
          <li>It only searches for details you have proven, or confirmed, are yours.</li>
          <li>It never deletes anything or sends requests on your behalf. You stay in control of every step.</li>
          <li>Your personal details are stored encrypted, and you can erase your account at any time.</li>
        </ul>
      </section>

      <form className="card auth-card" onSubmit={submit}>
        <div className="segmented" role="tablist">
          <button type="button" role="tab" aria-selected={mode === "signin"} onClick={() => setMode("signin")}>
            Sign in
          </button>
          <button type="button" role="tab" aria-selected={mode === "signup"} onClick={() => setMode("signup")}>
            Create account
          </button>
        </div>
        <label>
          Email
          <input
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label>
          Password
          <input
            type="password"
            autoComplete={mode === "signup" ? "new-password" : "current-password"}
            minLength={mode === "signup" ? 12 : undefined}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {mode === "signup" && <p className="hint">At least 12 characters.</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button className="primary" disabled={busy}>
          {busy ? "Please wait…" : mode === "signin" ? "Sign in" : "Create account"}
        </button>
      </form>
    </div>
  );
}

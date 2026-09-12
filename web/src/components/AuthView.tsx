import { useState, type FormEvent } from "react";
import { ApiError, api, errorText } from "../api";
import { useI18n } from "../i18n";

export function AuthView({ onAuthed }: { onAuthed: () => void }) {
  const { t } = useI18n();
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
        setError(t("auth.accountExists"));
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
        <h1>{t("auth.title")}</h1>
        <p className="lead">{t("auth.lead")}</p>
        <ul className="facts">
          <li>{t("auth.fact1")}</li>
          <li>{t("auth.fact2")}</li>
          <li>{t("auth.fact3")}</li>
        </ul>
      </section>

      <form className="card auth-card" onSubmit={submit}>
        <div className="segmented" role="tablist">
          <button type="button" role="tab" aria-selected={mode === "signin"} onClick={() => setMode("signin")}>
            {t("auth.signIn")}
          </button>
          <button type="button" role="tab" aria-selected={mode === "signup"} onClick={() => setMode("signup")}>
            {t("auth.createAccount")}
          </button>
        </div>
        <label>
          {t("auth.email")}
          <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label>
          {t("auth.password")}
          <input
            type="password"
            autoComplete={mode === "signup" ? "new-password" : "current-password"}
            minLength={mode === "signup" ? 12 : undefined}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {mode === "signup" && <p className="hint">{t("auth.passwordHint")}</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button className="primary" disabled={busy}>
          {busy ? t("auth.wait") : mode === "signin" ? t("auth.signIn") : t("auth.createAccount")}
        </button>
      </form>
    </div>
  );
}

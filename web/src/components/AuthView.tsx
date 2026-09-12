import { useState, type FormEvent } from "react";
import { ApiError, api, errorText } from "../api";
import { useI18n } from "../i18n";

export function AuthView({ onAuthed }: { onAuthed: () => void }) {
  const { t } = useI18n();
  const [mode, setMode] = useState<"signin" | "signup" | "reset">("signin");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function show(next: "signin" | "signup" | "reset") {
    setMode(next);
    setError(null);
    setNotice(null);
    setSent(false);
    setCode("");
    setPassword("");
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "reset") {
        if (!sent) {
          await api.requestPasswordReset(email);
          setSent(true);
          setNotice(t("reset.sent"));
        } else {
          await api.confirmPasswordReset(email, code, password);
          await api.login(email, password);
          onAuthed();
        }
        return;
      }
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
          <button type="button" role="tab" aria-selected={mode === "signin"} onClick={() => show("signin")}>
            {t("auth.signIn")}
          </button>
          <button type="button" role="tab" aria-selected={mode === "signup"} onClick={() => show("signup")}>
            {t("auth.createAccount")}
          </button>
        </div>
        <label>
          {t("auth.email")}
          <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        {mode === "reset" && sent && (
          <label>
            {t("reset.code")}
            <input
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              required
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </label>
        )}
        {(mode !== "reset" || sent) && (
          <label>
            {mode === "reset" ? t("reset.newPassword") : t("auth.password")}
            <input
              type="password"
              autoComplete={mode === "signin" ? "current-password" : "new-password"}
              minLength={mode === "signin" ? undefined : 12}
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
        )}
        {mode !== "signin" && <p className="hint">{t("auth.passwordHint")}</p>}
        {mode === "reset" && !sent && <p className="hint">{t("reset.intro")}</p>}
        {notice && <p className="note">{notice}</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button className="primary" disabled={busy}>
          {busy
            ? t("auth.wait")
            : mode === "signin"
              ? t("auth.signIn")
              : mode === "signup"
                ? t("auth.createAccount")
                : sent
                  ? t("reset.setPassword")
                  : t("reset.sendCode")}
        </button>
        {mode !== "reset" ? (
          <button type="button" className="link" onClick={() => show("reset")}>
            {t("reset.forgot")}
          </button>
        ) : (
          <button type="button" className="link" onClick={() => show("signin")}>
            {t("reset.backToSignIn")}
          </button>
        )}
      </form>
    </div>
  );
}

import { useEffect, useState } from "react";
import { api, hasToken, refreshIfStale, setToken, setUnauthorizedHandler } from "./api";
import { AuthView } from "./components/AuthView";
import { Dashboard } from "./components/Dashboard";
import { useI18n } from "./i18n";
import type { Meta } from "./types";

export default function App() {
  const { lang, setLang, t } = useI18n();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [authed, setAuthed] = useState(hasToken());

  useEffect(() => {
    api.meta().then(setMeta).catch(() => setMeta(null));
    setUnauthorizedHandler(() => setAuthed(false));
  }, []);

  // Tokens last 30 minutes. Renew them while the user is actually doing
  // something, so an active session doesn't lapse mid-task but an idle tab
  // still expires.
  useEffect(() => {
    if (!authed) return;
    let lastActivity = Date.now();
    const markActive = () => {
      lastActivity = Date.now();
    };
    const tick = () => {
      if (Date.now() - lastActivity < 5 * 60 * 1000) void refreshIfStale();
    };
    const timer = window.setInterval(tick, 60_000);
    window.addEventListener("pointerdown", markActive);
    window.addEventListener("keydown", markActive);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("pointerdown", markActive);
      window.removeEventListener("keydown", markActive);
    };
  }, [authed]);

  function signOut() {
    setToken(null);
    setAuthed(false);
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          Footprint
        </div>
        <div className="topbar-actions">
          <button
            className="ghost"
            lang={lang === "en" ? "fi" : "en"}
            aria-label={t("app.languageLabel")}
            onClick={() => setLang(lang === "en" ? "fi" : "en")}
          >
            {t("app.otherLanguage")}
          </button>
          {meta?.donate_url && (
            // A plain link rather than PayPal's embedded button: that needs
            // PayPal's script, and the CSP only allows our own.
            <a className="button donate" href={meta.donate_url} target="_blank" rel="noopener noreferrer">
              {t("app.donate")}
            </a>
          )}
          {authed && (
            <button className="ghost" onClick={signOut}>
              {t("app.signOut")}
            </button>
          )}
        </div>
      </header>
      {meta?.demo_scans && (
        <div className="banner demo" role="note">
          <strong>{t("app.demoTitle")}</strong> {t("app.demoBody")}
        </div>
      )}
      <main className="content">
        {authed ? <Dashboard meta={meta} onSignedOut={signOut} /> : <AuthView meta={meta} onAuthed={() => setAuthed(true)} />}
      </main>
    </div>
  );
}

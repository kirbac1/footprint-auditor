import { useEffect, useState } from "react";
import { api, hasToken, setToken, setUnauthorizedHandler } from "./api";
import { AuthView } from "./components/AuthView";
import { Dashboard } from "./components/Dashboard";
import type { Meta } from "./types";

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [authed, setAuthed] = useState(hasToken());

  useEffect(() => {
    api.meta().then(setMeta).catch(() => setMeta(null));
    setUnauthorizedHandler(() => setAuthed(false));
  }, []);

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
          {meta?.donate_url && (
            // A plain link rather than PayPal's embedded button: that needs
            // PayPal's script, and the CSP only allows our own.
            <a className="button donate" href={meta.donate_url} target="_blank" rel="noopener noreferrer">
              Donate via PayPal
            </a>
          )}
          {authed && (
            <button className="ghost" onClick={signOut}>
              Sign out
            </button>
          )}
        </div>
      </header>
      {meta?.demo_scans && (
        <div className="banner demo" role="note">
          <strong>Demo mode.</strong> Scans run the real pipeline against a scripted model and synthetic search
          results. Scan findings on this server are not real.
        </div>
      )}
      <main className="content">
        {authed ? <Dashboard meta={meta} onSignedOut={signOut} /> : <AuthView onAuthed={() => setAuthed(true)} />}
      </main>
    </div>
  );
}

import { useEffect, useState, type FormEvent } from "react";
import { api, errorText, setToken } from "../api";
import type { Me } from "../types";

export function AccountTab({ onErased }: { onErased: () => void }) {
  const [me, setMe] = useState<Me | null>(null);
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.me().then(setMe).catch((err) => setError(errorText(err)));
  }, []);

  async function erase(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.deleteAccount();
      setToken(null);
      onErased();
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <section className="card">
        <h2>Account</h2>
        {me && (
          <dl className="facts-list">
            <dt>Signed in as</dt>
            <dd>{me.email}</dd>
            <dt>Member since</dt>
            <dd>{new Date(me.created_at).toLocaleDateString()}</dd>
          </dl>
        )}
      </section>
      <form className="card danger" onSubmit={erase}>
        <h2>Erase my account</h2>
        <p>
          Deletes your account, every detail you added, all scans and findings, breach results and your action plan.
          This can't be undone. A log of actions, holding ids only and none of your details, is kept for security.
        </p>
        <label>
          Type <strong>erase</strong> to confirm
          <input value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="danger" disabled={busy || confirm !== "erase"}>
          Erase everything
        </button>
      </form>
    </div>
  );
}

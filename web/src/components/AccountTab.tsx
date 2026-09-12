import { useEffect, useState, type FormEvent } from "react";
import { api, errorText, setToken } from "../api";
import { useI18n } from "../i18n";
import type { Me } from "../types";

export function AccountTab({ onErased }: { onErased: () => void }) {
  const { lang, t } = useI18n();
  const [me, setMe] = useState<Me | null>(null);
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const word = t("account.confirmWord");

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
        <h2>{t("account.title")}</h2>
        {me && (
          <dl className="facts-list">
            <dt>{t("account.signedInAs")}</dt>
            <dd>{me.email}</dd>
            <dt>{t("account.since")}</dt>
            <dd>{new Date(me.created_at).toLocaleDateString(lang === "fi" ? "fi-FI" : undefined)}</dd>
          </dl>
        )}
      </section>
      <form className="card danger" onSubmit={erase}>
        <h2>{t("account.eraseTitle")}</h2>
        <p>{t("account.eraseBody")}</p>
        <label>
          {t("account.typeToConfirm", { word })}
          <input value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="danger" disabled={busy || confirm.trim().toLowerCase() !== word}>
          {t("account.eraseButton")}
        </button>
      </form>
    </div>
  );
}

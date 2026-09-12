import { useEffect, useState } from "react";
import { api, errorText } from "../api";
import { useI18n, type MessageKey } from "../i18n";
import type { ItemStatus, Jurisdiction, PlanItem } from "../types";

const JURISDICTIONS: Jurisdiction[] = ["FI", "EU", "US-CA", "US", "OTHER"];
const STATUSES: ItemStatus[] = ["open", "sent", "done", "dismissed"];

export function PlanTab() {
  const { lang, t } = useI18n();
  const [jurisdiction, setJurisdiction] = useState<Jurisdiction>("FI");
  const [items, setItems] = useState<PlanItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api
      .plan(jurisdiction, lang)
      .then((plan) => !cancelled && setItems(plan.items))
      .catch((err) => !cancelled && setError(errorText(err)));
    return () => {
      cancelled = true;
    };
  }, [jurisdiction, lang]);

  async function setStatus(item: PlanItem, status: ItemStatus) {
    try {
      const updated = await api.updateItem(item.id, status);
      setItems((prev) => prev?.map((i) => (i.id === updated.id ? updated : i)) ?? null);
    } catch (err) {
      setError(errorText(err));
    }
  }

  const finished = items?.filter((i) => i.status === "done" || i.status === "dismissed").length ?? 0;

  return (
    <div className="stack">
      <section className="card">
        <div className="card-head">
          <h2>{t("plan.title")}</h2>
          <label className="compact">
            {t("plan.liveIn")}
            <select value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value as Jurisdiction)}>
              {JURISDICTIONS.map((id) => (
                <option key={id} value={id}>
                  {t(`jur.${id}` as MessageKey)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="muted">{t("plan.intro")}</p>
        {items && items.length > 0 && (
          <div className="meter" aria-label={t("plan.progress", { done: finished, total: items.length })}>
            <div className="meter-bar">
              <div className="meter-fill" style={{ width: `${(finished / items.length) * 100}%` }} />
            </div>
            <span>{t("plan.progress", { done: finished, total: items.length })}</span>
          </div>
        )}
        {error && <p className="error">{error}</p>}
      </section>

      {items === null && !error && <p className="muted">{t("plan.building")}</p>}
      {[0, 1, 2, 3].map((priority) => {
        const group = items?.filter((i) => i.priority === priority) ?? [];
        if (group.length === 0) return null;
        return (
          <section key={priority} className="plan-group">
            <h3 className={`priority p${priority}`}>{t(`prio.${priority}` as MessageKey)}</h3>
            {group.map((item) => (
              <PlanCard key={item.id} item={item} onStatus={(s) => void setStatus(item, s)} />
            ))}
          </section>
        );
      })}
    </div>
  );
}

function PlanCard({ item, onStatus }: { item: PlanItem; onStatus: (s: ItemStatus) => void }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const closed = item.status === "done" || item.status === "dismissed";

  async function copy() {
    if (!item.draft) return;
    await navigator.clipboard.writeText(item.draft);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }

  return (
    <article className={closed ? "card plan-item closed" : "card plan-item"}>
      <div className="card-head">
        <h4>{item.title}</h4>
        <select
          value={item.status}
          onChange={(e) => onStatus(e.target.value as ItemStatus)}
          aria-label={t("plan.statusLabel", { title: item.title })}
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {t(`item.${s}` as MessageKey)}
            </option>
          ))}
        </select>
      </div>
      <p>{item.detail}</p>
      <div className="plan-actions">
        {item.url && (
          <a className="button" href={item.url} target="_blank" rel="noopener noreferrer">
            {item.action_type === "opt_out" ? t("plan.openOptOut") : t("plan.openPage")}
          </a>
        )}
      </div>
      {item.draft && (
        <details className="draft">
          <summary>{t("plan.letter")}</summary>
          <pre>{item.draft}</pre>
          <button className="small" onClick={() => void copy()}>
            {copied ? t("plan.copied") : t("plan.copyLetter")}
          </button>
        </details>
      )}
    </article>
  );
}

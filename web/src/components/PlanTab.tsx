import { useEffect, useState } from "react";
import { api, errorText } from "../api";
import type { ItemStatus, Jurisdiction, PlanItem } from "../types";

const JURISDICTIONS: [Jurisdiction, string][] = [
  ["FI", "Finland"],
  ["EU", "EU / EEA"],
  ["US-CA", "California"],
  ["US", "Elsewhere in the US"],
  ["OTHER", "Somewhere else"],
];

const PRIORITY = ["Do this first", "High priority", "Worth doing", "When you have time"];
const STATUS_LABEL: Record<ItemStatus, string> = { open: "To do", sent: "Request sent", done: "Done", dismissed: "Not relevant" };

export function PlanTab() {
  const [jurisdiction, setJurisdiction] = useState<Jurisdiction>("FI");
  const [items, setItems] = useState<PlanItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api
      .plan(jurisdiction)
      .then((plan) => !cancelled && setItems(plan.items))
      .catch((err) => !cancelled && setError(errorText(err)));
    return () => {
      cancelled = true;
    };
  }, [jurisdiction]);

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
          <h2>Your action plan</h2>
          <label className="compact">
            I live in
            <select value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value as Jurisdiction)}>
              {JURISDICTIONS.map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="muted">
          Built from your scans and breach checks. Where you live decides which removal law the letters cite. Nothing
          here is sent for you. Removal requests are yours to send, and some sites will ask you to prove who you are.
        </p>
        {items && items.length > 0 && (
          <div className="meter" aria-label={`${finished} of ${items.length} done`}>
            <div className="meter-bar">
              <div className="meter-fill" style={{ width: `${(finished / items.length) * 100}%` }} />
            </div>
            <span>
              {finished} of {items.length} done
            </span>
          </div>
        )}
        {error && <p className="error">{error}</p>}
      </section>

      {items === null && !error && <p className="muted">Building your plan…</p>}
      {PRIORITY.map((label, priority) => {
        const group = items?.filter((i) => i.priority === priority) ?? [];
        if (group.length === 0) return null;
        return (
          <section key={priority} className="plan-group">
            <h3 className={`priority p${priority}`}>{label}</h3>
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
          aria-label={`Status of ${item.title}`}
        >
          {(Object.keys(STATUS_LABEL) as ItemStatus[]).map((s) => (
            <option key={s} value={s}>
              {STATUS_LABEL[s]}
            </option>
          ))}
        </select>
      </div>
      <p>{item.detail}</p>
      <div className="plan-actions">
        {item.url && (
          <a className="button" href={item.url} target="_blank" rel="noopener noreferrer">
            {item.action_type === "opt_out" ? "Open the opt-out page" : "Open page"}
          </a>
        )}
      </div>
      {item.draft && (
        <details className="draft">
          <summary>Removal request letter</summary>
          <pre>{item.draft}</pre>
          <button className="small" onClick={() => void copy()}>
            {copied ? "Copied" : "Copy letter"}
          </button>
        </details>
      )}
    </article>
  );
}

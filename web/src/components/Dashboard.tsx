import { useCallback, useEffect, useState } from "react";
import { api, errorText } from "../api";
import type { Identifier, Meta } from "../types";
import { AccountTab } from "./AccountTab";
import { BreachTab } from "./BreachTab";
import { DetailsTab } from "./DetailsTab";
import { PlanTab } from "./PlanTab";
import { ScanTab } from "./ScanTab";

const TABS = [
  ["details", "Your details"],
  ["scan", "Footprint scan"],
  ["breaches", "Breaches"],
  ["plan", "Action plan"],
  ["account", "Account"],
] as const;
type Tab = (typeof TABS)[number][0];

export function Dashboard({ meta, onSignedOut }: { meta: Meta | null; onSignedOut: () => void }) {
  const [tab, setTab] = useState<Tab>("details");
  const [identifiers, setIdentifiers] = useState<Identifier[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setIdentifiers(await api.identifiers());
      setLoadError(null);
    } catch (err) {
      setLoadError(errorText(err));
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const hasVerified = identifiers.some((i) => i.status === "verified");

  return (
    <div className="dashboard">
      <nav className="tabs" role="tablist">
        {TABS.map(([id, label]) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            className={tab === id ? "tab active" : "tab"}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </nav>

      {loadError && <p className="error">{loadError}</p>}
      {!hasVerified && (tab === "scan" || tab === "breaches") && (
        <div className="banner">
          Verify an email address or phone number under{" "}
          <button className="inline-link" onClick={() => setTab("details")}>
            Your details
          </button>{" "}
          first. Scans and breach lookups only cover details you have proven are yours.
        </div>
      )}

      {tab === "details" && <DetailsTab identifiers={identifiers} meta={meta} onChange={reload} />}
      {tab === "scan" && <ScanTab identifiers={identifiers} meta={meta} onOpenPlan={() => setTab("plan")} />}
      {tab === "breaches" && <BreachTab hasVerified={hasVerified} meta={meta} />}
      {tab === "plan" && <PlanTab />}
      {tab === "account" && <AccountTab onErased={onSignedOut} />}
    </div>
  );
}

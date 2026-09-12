import { useCallback, useEffect, useState } from "react";
import { api, errorText } from "../api";
import { useI18n, type MessageKey } from "../i18n";
import type { Identifier, Meta } from "../types";
import { AccountTab } from "./AccountTab";
import { BreachTab } from "./BreachTab";
import { DetailsTab } from "./DetailsTab";
import { PlanTab } from "./PlanTab";
import { ScanTab } from "./ScanTab";

type Tab = "details" | "scan" | "breaches" | "plan" | "account";

const TABS: [Tab, MessageKey][] = [
  ["details", "tab.details"],
  ["scan", "tab.scan"],
  ["breaches", "tab.breaches"],
  ["plan", "tab.plan"],
  ["account", "tab.account"],
];

export function Dashboard({ meta, onSignedOut }: { meta: Meta | null; onSignedOut: () => void }) {
  const { t } = useI18n();
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

  // Only a verified email or phone opens the gate; a proven username doesn't.
  const hasVerified = identifiers.some((i) => i.status === "verified" && (i.kind === "email" || i.kind === "phone"));
  const after = t("dash.verifyAfter");

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
            {t(label)}
          </button>
        ))}
      </nav>

      {loadError && <p className="error">{loadError}</p>}
      {!hasVerified && (tab === "scan" || tab === "breaches") && (
        <div className="banner">
          {t("dash.verifyBefore")}{" "}
          <button className="inline-link" onClick={() => setTab("details")}>
            {t("tab.details")}
          </button>
          {/^[.,]/.test(after) ? after : ` ${after}`}
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

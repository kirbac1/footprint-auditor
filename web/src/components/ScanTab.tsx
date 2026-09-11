import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api, errorText } from "../api";
import type { Finding, Identifier, Meta, Scan, ScanKind } from "../types";

const CATEGORY: Record<string, string> = {
  data_broker: "Data broker",
  people_search: "People-search site",
  social_profile: "Social profile",
  possible_impersonation: "Possible impersonation",
  paste_or_leak: "Paste or leak site",
  news_or_public_record: "News or public record",
  other: "Other",
};

const KIND_TITLE: Record<ScanKind, string> = {
  exposure: "Footprint scan",
  impersonation: "Impersonation check",
};

const isActive = (s: Scan | null) => s !== null && (s.status === "queued" || s.status === "running");

interface Props {
  identifiers: Identifier[];
  meta: Meta | null;
  onOpenPlan: () => void;
}

export function ScanTab({ identifiers, meta, onOpenPlan }: Props) {
  const [scans, setScans] = useState<Scan[]>([]);
  const [selected, setSelected] = useState<Scan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const hasVerified = identifiers.some((i) => i.status === "verified");
  const hasProfile = identifiers.some((i) => ["name", "username", "image"].includes(i.kind));
  const hasContext = identifiers.some((i) => ["city", "birth_year", "workplace"].includes(i.kind));

  const refreshList = useCallback(async () => {
    try {
      const list = await api.scans();
      setScans(list);
      return list;
    } catch (err) {
      setError(errorText(err));
      return [];
    }
  }, []);

  // Open the most recent scan on arrival, so a scan started earlier is visible.
  useEffect(() => {
    void refreshList().then(async (list) => {
      if (list.length > 0) setSelected(await api.scan(list[0].id));
    });
  }, [refreshList]);

  // Poll the selected scan while it is still running.
  const selectedId = selected?.id;
  const selectedActive = isActive(selected);
  useEffect(() => {
    if (!selectedId || !selectedActive) return;
    let stopped = false;
    const timer = window.setInterval(async () => {
      try {
        const scan = await api.scan(selectedId);
        if (stopped) return;
        setSelected(scan);
        if (!isActive(scan)) void refreshList();
      } catch (err) {
        setError(errorText(err));
      }
    }, 2000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [selectedId, selectedActive, refreshList]);

  async function start(kind: ScanKind) {
    setStarting(true);
    setError(null);
    try {
      const { scan_id } = await api.startScan(kind);
      setSelected(await api.scan(scan_id));
      await refreshList();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setStarting(false);
    }
  }

  const unavailable = meta !== null && !meta.scans_available;
  const busy = starting || scans.some((s) => s.status === "queued" || s.status === "running");
  const exposureReason = !hasVerified
    ? "Verify an email or phone first."
    : unavailable
      ? "Scanning is not configured on this server (model or web search missing)."
      : null;
  const impersonationReason = exposureReason ?? (!hasProfile ? "Add your name, a username or a photo first." : null);

  return (
    <div className="stack">
      <section className="card">
        <h2>Check your digital footprint</h2>
        <p className="muted">
          The scan searches the public web, data brokers and people-search sites for the details you've added. It can
          take a few minutes. You can leave this page; results are saved to your account.
        </p>
        {hasVerified && !hasContext && (
          <p className="hint">
            Tip: add a city, birth year or workplace under Your details. The scan uses them to leave out people who
            only share your name.
          </p>
        )}
        <div className="actions">
          <div className="action">
            <button className="primary" disabled={busy || exposureReason !== null} onClick={() => void start("exposure")}>
              Scan my footprint
            </button>
            {exposureReason && <span className="hint">{exposureReason}</span>}
          </div>
          <div className="action">
            <button disabled={busy || impersonationReason !== null} onClick={() => void start("impersonation")}>
              Check for impersonation
            </button>
            {impersonationReason && <span className="hint">{impersonationReason}</span>}
          </div>
        </div>
        {meta && <p className="hint">Up to {meta.limits.scans_per_day} scans per day, one at a time.</p>}
        {error && <p className="error">{error}</p>}
      </section>

      {selected && <ScanDetail scan={selected} onOpenPlan={onOpenPlan} onChanged={setSelected} />}

      {scans.length > 1 && (
        <section className="card">
          <h3>Earlier scans</h3>
          <ul className="rows">
            {scans.map((s) => (
              <li key={s.id} className="row">
                <div className="row-main">
                  <span className="value">{KIND_TITLE[s.kind]}</span>
                  <span className="muted">{new Date(s.created_at).toLocaleString()}</span>
                  <span className={`pill ${s.status}`}>{s.status}</span>
                  <button className="ghost small" onClick={() => void api.scan(s.id).then(setSelected)}>
                    View
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function ScanDetail({ scan, onOpenPlan, onChanged }: { scan: Scan; onOpenPlan: () => void; onChanged: (s: Scan) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const active = isActive(scan);
  const aboutYou = scan.findings.filter((f) => f.match_status !== "unclear");
  const review = scan.findings.filter((f) => f.match_status === "unclear");
  const n = scan.namesakes_excluded;

  async function judge(finding: Finding, verdict: "me" | "not_me") {
    setBusy(finding.id);
    setError(null);
    try {
      if (verdict === "me") await api.confirmFinding(finding.id);
      else await api.notMe(finding.id);
      onChanged(await api.scan(scan.id));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="card" aria-live="polite">
      <div className="card-head">
        <h3>{KIND_TITLE[scan.kind]}</h3>
        <span className={`pill ${scan.status}`}>{active ? "Scanning…" : scan.status}</span>
      </div>
      {active && (
        <div className="progress" role="status">
          <span className="spinner" aria-hidden="true" /> Searching. This page updates by itself.
        </div>
      )}
      {scan.error && <p className="error">{scan.error}</p>}
      {scan.summary && <p className="summary">{scan.summary}</p>}
      {n > 0 && (
        <p className="note">
          Left out {n} result{n === 1 ? "" : "s"} about {n === 1 ? "someone" : "other people"} with your name. They
          contradicted your details and were not saved.
        </p>
      )}
      {!active && scan.status === "completed" && scan.findings.length === 0 && (
        <p className="empty">Nothing found for your details in this scan.</p>
      )}
      {error && <p className="error">{error}</p>}

      {aboutYou.length > 0 && (
        <>
          <h4 className="section-label">About you</h4>
          <ul className="findings">
            {aboutYou.map((f) => (
              <FindingItem key={f.id} finding={f}>
                <button className="ghost small" disabled={busy === f.id} onClick={() => void judge(f, "not_me")}>
                  Not me
                </button>
              </FindingItem>
            ))}
          </ul>
        </>
      )}

      {review.length > 0 && (
        <>
          <h4 className="section-label">Might be someone with your name</h4>
          <p className="hint">
            Only your name links these to you. The ones you confirm get removal steps. The others are deleted and
            left out of future scans.
          </p>
          <ul className="findings review">
            {review.map((f) => (
              <FindingItem key={f.id} finding={f}>
                <button className="primary small" disabled={busy === f.id} onClick={() => void judge(f, "me")}>
                  This is me
                </button>
                <button className="small" disabled={busy === f.id} onClick={() => void judge(f, "not_me")}>
                  Not me
                </button>
              </FindingItem>
            ))}
          </ul>
        </>
      )}

      {aboutYou.length > 0 && (
        <button className="primary" onClick={onOpenPlan}>
          See what to do about these
        </button>
      )}
    </section>
  );
}

function FindingItem({ finding: f, children }: { finding: Finding; children: ReactNode }) {
  return (
    <li className="finding">
      <div className="finding-head">
        <span className="kind">{CATEGORY[f.category] ?? f.category}</span>
        {f.match_status === "confirmed" ? (
          <span className="pill attested">Confirmed by you</span>
        ) : (
          <span className={`pill conf-${f.confidence}`}>{f.confidence} confidence</span>
        )}
      </div>
      <a href={f.url} target="_blank" rel="noopener noreferrer" className="finding-title">
        {f.title || f.url}
      </a>
      <div className="url">{f.url}</div>
      <p className="muted">{f.rationale}</p>
      <div className="finding-actions">{children}</div>
    </li>
  );
}

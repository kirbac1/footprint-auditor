import { useCallback, useEffect, useRef, useState, type ReactNode, type SyntheticEvent } from "react";
import { api, errorText } from "../api";
import { useI18n, type MessageKey } from "../i18n";
import type { Finding, Identifier, Meta, Scan, ScanKind, TraceEvent } from "../types";

const isActive = (s: Scan | null) => s !== null && (s.status === "queued" || s.status === "running");

interface Props {
  identifiers: Identifier[];
  meta: Meta | null;
  onOpenPlan: () => void;
}

export function ScanTab({ identifiers, meta, onOpenPlan }: Props) {
  const { lang, t } = useI18n();
  const [scans, setScans] = useState<Scan[]>([]);
  const [selected, setSelected] = useState<Scan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const detailRef = useRef<HTMLDivElement>(null);
  // The detail panel is above this list, so opening an older scan changes
  // something off-screen. Scroll to it, or the button looks broken.
  const scrollToDetail = useRef(false);

  useEffect(() => {
    if (!scrollToDetail.current) return;
    scrollToDetail.current = false;
    detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  async function openScan(id: string) {
    setError(null);
    try {
      const scan = await api.scan(id);
      scrollToDetail.current = true;
      setSelected(scan);
    } catch (err) {
      setError(errorText(err));
    }
  }

  const hasVerified = identifiers.some((i) => i.status === "verified" && (i.kind === "email" || i.kind === "phone"));
  const proofRequired = meta?.username_proof_required ?? true;
  const hasProfile = identifiers.some((i) =>
    i.kind === "username" ? i.status === "verified" || !proofRequired : i.kind === "name" || i.kind === "image",
  );
  const hasContext = identifiers.some((i) => ["city", "birth_year", "workplace"].includes(i.kind));
  // The agent may only search for identifiers in scope. With an email and
  // nothing else it can run, but brokers and people-search sites are indexed
  // by name: the scan would come back empty and look like good news.
  const searchableName = identifiers.some((i) =>
    i.kind === "name" || i.kind === "phone" || (i.kind === "username" && (i.status === "verified" || !proofRequired)),
  );

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
        const scan = await api.scan(selectedId, true);
        if (stopped) return;
        setSelected(scan);
        if (!isActive(scan)) void refreshList();
      } catch (err) {
        setError(errorText(err));
      }
    }, 3000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [selectedId, selectedActive, refreshList]);

  async function start(kind: ScanKind) {
    setStarting(true);
    setError(null);
    try {
      const { scan_id } = await api.startScan(kind, lang);
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
    ? t("scan.reason.verify")
    : unavailable
      ? t("scan.reason.notConfigured")
      : null;
  const impersonationReason = exposureReason ?? (!hasProfile ? t("scan.reason.profile") : null);

  return (
    <div className="stack">
      <section className="card">
        <h2>{t("scan.title")}</h2>
        <p className="muted">{t("scan.intro")}</p>
        {hasVerified && !searchableName && (
          <p className="callout warn">
            <strong>{t("scan.emailOnlyTitle")}</strong> {t("scan.emailOnly")}
          </p>
        )}
        {hasVerified && searchableName && !hasContext && <p className="hint">{t("scan.contextTip")}</p>}
        <div className="actions">
          <div className="action">
            <button className="primary" disabled={busy || exposureReason !== null} onClick={() => void start("exposure")}>
              {t("scan.start")}
            </button>
            {exposureReason && <span className="hint">{exposureReason}</span>}
          </div>
          <div className="action">
            <button disabled={busy || impersonationReason !== null} onClick={() => void start("impersonation")}>
              {t("scan.impersonation")}
            </button>
            {impersonationReason && <span className="hint">{impersonationReason}</span>}
          </div>
        </div>
        {meta && <p className="hint">{t("scan.limits", { n: meta.limits.scans_per_day })}</p>}
        {error && <p className="error">{error}</p>}
      </section>

      <div ref={detailRef}>
        {selected && (
          <ScanDetail scan={selected} identifiers={identifiers} onOpenPlan={onOpenPlan} onChanged={setSelected} />
        )}
      </div>

      {scans.length > 1 && (
        <section className="card">
          <h3>{t("scan.earlier")}</h3>
          <ul className="rows">
            {scans.map((s) => (
              <li key={s.id} className={`row${s.id === selected?.id ? " selected" : ""}`}>
                <div className="row-main">
                  <span className="value">{t(`scanKind.${s.kind}` as MessageKey)}</span>
                  <span className="muted">{new Date(s.created_at).toLocaleString(lang === "fi" ? "fi-FI" : undefined)}</span>
                  <span className={`pill ${s.status}`}>{t(`scanStatus.${s.status}` as MessageKey)}</span>
                  <button
                    className="ghost small"
                    aria-current={s.id === selected?.id ? "true" : undefined}
                    onClick={() => void openScan(s.id)}
                  >
                    {s.id === selected?.id ? t("scan.viewing") : t("scan.view")}
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

const CONFIDENCE_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 };

function ScanDetail({
  scan,
  identifiers,
  onOpenPlan,
  onChanged,
}: {
  scan: Scan;
  identifiers: Identifier[];
  onOpenPlan: () => void;
  onChanged: (s: Scan) => void;
}) {
  const { t } = useI18n();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const active = isActive(scan);
  // Strongest first: what a page shows about you decides what to deal with.
  const byConfidence = (a: Finding, b: Finding) =>
    (CONFIDENCE_ORDER[a.confidence] ?? 3) - (CONFIDENCE_ORDER[b.confidence] ?? 3);
  const aboutYou = scan.findings.filter((f) => f.match_status !== "unclear").sort(byConfidence);
  const review = scan.findings.filter((f) => f.match_status === "unclear").sort(byConfidence);
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
        <h3>{t(`scanKind.${scan.kind}` as MessageKey)}</h3>
        <span className={`pill ${scan.status}`}>
          {active ? t("scan.scanning") : t(`scanStatus.${scan.status}` as MessageKey)}
        </span>
      </div>
      {active && (
        <div className="progress" role="status">
          <span className="spinner" aria-hidden="true" /> {t("scan.progress")}
        </div>
      )}
      {scan.error && <p className="error">{scan.error}</p>}
      {scan.summary && <p className="summary">{scan.summary}</p>}
      {!active && scan.model_calls > 0 && <UsageLine scan={scan} />}
      {n > 0 && <p className="note">{n === 1 ? t("scan.leftOutOne") : t("scan.leftOutMany", { n })}</p>}
      {!active && scan.status === "completed" && scan.findings.length === 0 && (
        <p className="empty">{t("scan.nothing")}</p>
      )}
      {error && <p className="error">{error}</p>}

      {aboutYou.length > 0 && (
        <>
          <h4 className="section-label">{t("scan.aboutYou")}</h4>
          <ul className="findings">
            {aboutYou.map((f) => (
              <FindingItem key={f.id} finding={f} identifiers={identifiers}>
                <button className="ghost small" disabled={busy === f.id} onClick={() => void judge(f, "not_me")}>
                  {t("scan.notMe")}
                </button>
              </FindingItem>
            ))}
          </ul>
        </>
      )}

      {review.length > 0 && (
        <>
          <h4 className="section-label">{t("scan.maybeOthers")}</h4>
          <p className="hint">{t("scan.reviewHint")}</p>
          <ul className="findings review">
            {review.map((f) => (
              <FindingItem key={f.id} finding={f} identifiers={identifiers}>
                <button className="primary small" disabled={busy === f.id} onClick={() => void judge(f, "me")}>
                  {t("scan.thisIsMe")}
                </button>
                <button className="small" disabled={busy === f.id} onClick={() => void judge(f, "not_me")}>
                  {t("scan.notMe")}
                </button>
              </FindingItem>
            ))}
          </ul>
        </>
      )}

      {aboutYou.length > 0 && (
        <button className="primary" onClick={onOpenPlan}>
          {t("scan.seePlan")}
        </button>
      )}
      {active && <LiveTrace events={scan.trace ?? []} />}
      {!active && scan.model_calls > 0 && <TraceView scanId={scan.id} />}
    </section>
  );
}

function FindingItem({
  finding: f,
  identifiers,
  children,
}: {
  finding: Finding;
  identifiers: Identifier[];
  children: ReactNode;
}) {
  const { t } = useI18n();
  // The code checked each of these against the page text before the finding
  // was kept, so this is the evidence, not the model's say-so.
  const matched = f.matched_identifier_ids
    .map((id) => identifiers.find((i) => i.id === id))
    .filter((i): i is Identifier => i !== undefined);
  return (
    <li className="finding">
      <div className="finding-head">
        <span className="kind">{t(`cat.${f.category}` as MessageKey)}</span>
        {f.match_status === "confirmed" ? (
          <span className="pill attested">{t("scan.confirmed")}</span>
        ) : (
          <span className={`pill conf-${f.confidence}`}>{t(`conf.${f.confidence}` as MessageKey)}</span>
        )}
      </div>
      <a href={f.url} target="_blank" rel="noopener noreferrer" className="finding-title">
        {f.title || f.url}
      </a>
      <div className="url">{f.url}</div>
      {matched.length > 0 && (
        <p className="matched">
          <span className="muted">{t("scan.matchedOn")}</span>{" "}
          {matched.map((i) => (
            <span key={i.id} className="chip">
              {t(`kind.${i.kind}` as MessageKey)}
            </span>
          ))}
        </p>
      )}
      <p className="muted">{f.rationale}</p>
      <div className="finding-actions">{children}</div>
    </li>
  );
}

function UsageLine({ scan }: { scan: Scan }) {
  const { lang, t } = useI18n();
  const locale = lang === "fi" ? "fi-FI" : undefined;
  const tokens = scan.input_tokens + scan.output_tokens + scan.cache_read_tokens + scan.cache_write_tokens;
  const parts = [
    `${t("usage.model")}: ${scan.model_calls}`,
    `${t("usage.tools")}: ${scan.tool_calls}`,
    `${t("usage.tokens")}: ${tokens.toLocaleString(locale)}`,
  ];
  if (scan.cost_usd != null) parts.push(`≈ $${scan.cost_usd.toFixed(3)}`);
  if (scan.duration_ms != null) parts.push(`${(scan.duration_ms / 1000).toLocaleString(locale, { maximumFractionDigits: 1 })} s`);
  return <p className="hint usage">{parts.join(" · ")}</p>;
}

function LiveTrace({ events }: { events: TraceEvent[] }) {
  const { t } = useI18n();

  return (
    <section className="trace live">
      <h4 className="section-label">{t("trace.live")}</h4>
      <p className="hint">{t("trace.liveIntro")}</p>
      {events.length === 0 ? (
        <p className="hint">{t("trace.waiting")}</p>
      ) : (
        <ol className="steps">
          {events.map((e) => (
            <li key={e.seq} className={e.status === "ok" ? "" : "warn"}>
              <span className="step-name">{e.kind === "model_call" ? t("trace.model") : e.name}</span>
              <span className="step-detail">{e.detail ?? e.status}</span>
              <span className="step-time">{(e.duration_ms / 1000).toFixed(1)} s</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function TraceView({ scanId }: { scanId: string }) {
  const { t } = useI18n();
  const [events, setEvents] = useState<TraceEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load(e: SyntheticEvent<HTMLDetailsElement>) {
    if (e.currentTarget.open && events === null) {
      api.scanTrace(scanId).then(setEvents).catch((err) => setError(errorText(err)));
    }
  }

  return (
    <details className="trace" onToggle={load}>
      <summary>{t("trace.title")}</summary>
      <p className="hint">{t("trace.intro")}</p>
      {error && <p className="error">{error}</p>}
      {events && (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>{t("trace.step")}</th>
                <th>{t("trace.outcome")}</th>
                <th>{t("trace.start")}</th>
                <th>{t("trace.took")}</th>
                <th>{t("trace.tokens")}</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.seq}>
                  <td>{e.seq + 1}</td>
                  <td>{e.kind === "model_call" ? t("trace.model") : e.name}</td>
                  <td className={e.status === "ok" ? "" : "warn"}>{e.detail ?? e.status}</td>
                  <td>{(e.offset_ms / 1000).toFixed(2)} s</td>
                  <td>{e.duration_ms} ms</td>
                  <td>
                    {e.kind === "model_call"
                      ? `${(e.input_tokens + e.cache_read_tokens + e.cache_write_tokens).toLocaleString()} / ${e.output_tokens.toLocaleString()}`
                      : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </details>
  );
}

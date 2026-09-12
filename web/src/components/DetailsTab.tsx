import { useState, type FormEvent } from "react";
import { api, errorText } from "../api";
import { useI18n, type MessageKey, type Translate } from "../i18n";
import type { ContextKind, Identifier, IdentityKind, Meta } from "../types";

const kindLabel = (t: Translate, kind: string) => t(`kind.${kind}` as MessageKey);

interface Props {
  identifiers: Identifier[];
  meta: Meta | null;
  onChange: () => Promise<void>;
}

export function DetailsTab({ identifiers, meta, onChange }: Props) {
  const { t } = useI18n();
  // A demo instance returns the verification code instead of sending it
  // anywhere. The list is refetched after every change and the refetch has no
  // codes in it, so they are kept here or they are lost before anyone sees them.
  const [demoCodes, setDemoCodes] = useState<Record<string, string>>({});
  const rememberCode = (id: string, code: string | null | undefined) => {
    if (code) setDemoCodes((codes) => ({ ...codes, [id]: code }));
  };
  return (
    <div className="stack">
      <section className="card">
        <h2>{t("details.title")}</h2>
        <p className="muted">{t("details.intro")}</p>
        {identifiers.length === 0 ? (
          <p className="empty">{t("details.empty")}</p>
        ) : (
          <ul className="rows">
            {identifiers.map((i) => (
              <IdentifierRow
                key={i.id}
                identifier={i}
                meta={meta}
                onChange={onChange}
                demoCode={demoCodes[i.id]}
                onDemoCode={rememberCode}
              />
            ))}
          </ul>
        )}
      </section>
      <AddIdentifier onChange={onChange} onDemoCode={rememberCode} />
      <AddContext onChange={onChange} />
      <AddPhoto meta={meta} onChange={onChange} />
    </div>
  );
}

function statusText(t: Translate, i: Identifier, meta: Meta | null): string {
  if (i.status === "verified" && i.proof_platform) {
    const platform = meta?.proof_platforms.find((p) => p.id === i.proof_platform)?.label ?? i.proof_platform;
    return t("status.verifiedVia", { platform });
  }
  if (i.kind === "username" && i.status !== "verified" && (meta?.username_proof_required ?? true)) {
    return t("status.notVerified");
  }
  return t(`status.${i.status}` as MessageKey);
}

function IdentifierRow({
  identifier: i,
  meta,
  onChange,
  demoCode,
  onDemoCode,
}: {
  identifier: Identifier;
  meta: Meta | null;
  onChange: () => Promise<void>;
  demoCode?: string;
  onDemoCode: (id: string, code: string | null | undefined) => void;
}) {
  const { t } = useI18n();
  const [code, setCode] = useState("");
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const unproven = i.kind === "username" && i.status !== "verified" && (meta?.username_proof_required ?? true);

  async function run(action: () => Promise<unknown>, success?: string) {
    setBusy(true);
    setMessage(null);
    try {
      await action();
      if (success) setMessage({ text: success, error: false });
      await onChange();
    } catch (err) {
      setMessage({ text: errorText(err), error: true });
    } finally {
      setBusy(false);
    }
  }

  function verify(e: FormEvent) {
    e.preventDefault();
    void run(() => api.verify(i.id, code));
  }

  function remove() {
    if (window.confirm(t("details.removeConfirm", { kind: kindLabel(t, i.kind).toLowerCase() }))) {
      void run(() => api.deleteIdentifier(i.id));
    }
  }

  return (
    <li className="row">
      <div className="row-main">
        <span className="kind">{kindLabel(t, i.kind)}</span>
        <span className="value">{i.value}</span>
        <span className={`pill ${unproven ? "pending" : i.status}`}>{statusText(t, i, meta)}</span>
        <button className="ghost small" onClick={remove} disabled={busy}>
          {t("details.remove")}
        </button>
      </div>
      {i.status === "pending" && (
        <form className="verify" onSubmit={verify}>
          <input
            inputMode="numeric"
            pattern="\d{6}"
            maxLength={6}
            placeholder={t("details.codePlaceholder")}
            aria-label={t("details.codeLabel", { value: i.value })}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            required
          />
          <button className="primary small" disabled={busy || code.length !== 6}>
            {t("details.verify")}
          </button>
          <button
            type="button"
            className="ghost small"
            disabled={busy}
            onClick={() =>
              void run(
                async () => {
                  const sent = await api.resend(i.id);
                  onDemoCode(i.id, sent.demo_code);
                },
                // On a demo the new code appears below; "on its way" would be untrue.
                meta?.demo_scans || meta?.codes_on_page ? undefined : t("details.codeSent"),
              )
            }
          >
            {t("details.resend")}
          </button>
          {demoCode ?? i.demo_code ? (
            <span className="hint demo-code">{t("details.demoCode", { code: (demoCode ?? i.demo_code)! })}</span>
          ) : (
            meta?.code_delivery === "console" &&
            !meta?.demo_scans &&
            !meta?.codes_on_page && <span className="hint">{t("details.consoleHint")}</span>
          )}
        </form>
      )}
      {i.kind === "username" && i.status !== "verified" && (
        <UsernameProof identifier={i} meta={meta} onChange={onChange} />
      )}
      {message && <p className={message.error ? "error" : "success"}>{message.text}</p>}
    </li>
  );
}

function UsernameProof({ identifier: i, meta, onChange }: { identifier: Identifier; meta: Meta | null; onChange: () => Promise<void> }) {
  const { t } = useI18n();
  const platforms = meta?.proof_platforms ?? [];
  const [platform, setPlatform] = useState(i.proof_platform ?? platforms[0]?.id ?? "github");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const current = platforms.find((p) => p.id === i.proof_platform);
  const required = meta?.username_proof_required ?? true;

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await onChange();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const picker = (
    <select
      value={platform}
      onChange={(e) => setPlatform(e.target.value)}
      aria-label={t("proof.platformLabel", { value: i.value })}
    >
      {platforms.map((p) => (
        <option key={p.id} value={p.id}>
          {p.label}
        </option>
      ))}
    </select>
  );

  return (
    <div className="proof">
      {i.proof_code && current ? (
        <>
          <p className="muted">{t("proof.instructions", { platform: current.label })}</p>
          <div className="inline-form">
            <code className="proof-code">{i.proof_code}</code>
            <button type="button" className="small" onClick={() => void navigator.clipboard.writeText(i.proof_code ?? "")}>
              {t("proof.copy")}
            </button>
            <a
              className="button small"
              href={current.profile_url.replace("{handle}", encodeURIComponent(i.value))}
              target="_blank"
              rel="noopener noreferrer"
            >
              {t("proof.open", { platform: current.label })}
            </a>
            <button type="button" className="primary small" disabled={busy} onClick={() => void act(() => api.checkProof(i.id))}>
              {busy ? t("proof.checking") : t("proof.check")}
            </button>
          </div>
          <div className="inline-form">
            {picker}
            <button type="button" className="ghost small" disabled={busy} onClick={() => void act(() => api.startProof(i.id, platform))}>
              {t("proof.newCode")}
            </button>
          </div>
        </>
      ) : (
        <div className="inline-form">
          <span className="hint">{required ? t("proof.required") : t("proof.optional")}</span>
          {picker}
          <button
            type="button"
            className="primary small"
            disabled={busy || platforms.length === 0}
            onClick={() => void act(() => api.startProof(i.id, platform))}
          >
            {t("proof.getCode")}
          </button>
        </div>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  );
}

function AddIdentifier({
  onChange,
  onDemoCode,
}: {
  onChange: () => Promise<void>;
  onDemoCode: (id: string, code: string | null | undefined) => void;
}) {
  const { t } = useI18n();
  const [kind, setKind] = useState<IdentityKind>("email");
  const [value, setValue] = useState("");
  const [attest, setAttest] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const needsAttest = kind === "name" || kind === "username";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const added = await api.addIdentifier(kind, value, needsAttest && attest);
      onDemoCode(added.id, added.demo_code);
      setValue("");
      setAttest(false);
      await onChange();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h3>{t("details.addTitle")}</h3>
      <div className="inline-form">
        <select value={kind} onChange={(e) => setKind(e.target.value as IdentityKind)} aria-label={t("details.kindLabel")}>
          <option value="email">{t("details.optEmail")}</option>
          <option value="phone">{t("details.optPhone")}</option>
          <option value="name">{t("details.optName")}</option>
          <option value="username">{t("details.optUsername")}</option>
        </select>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={t(`ph.${kind}` as MessageKey)}
          aria-label={t("details.valueLabel")}
          required
        />
        <button className="primary" disabled={busy || (needsAttest && !attest)}>
          {needsAttest ? t("details.add") : t("details.addAndSend")}
        </button>
      </div>
      {needsAttest && (
        <label className="check">
          <input type="checkbox" checked={attest} onChange={(e) => setAttest(e.target.checked)} />
          {kind === "username" ? t("details.attestUsername") : t("details.attestName")}
        </label>
      )}
      {error && <p className="error">{error}</p>}
    </form>
  );
}

function AddContext({ onChange }: { onChange: () => Promise<void> }) {
  const { t } = useI18n();
  const [kind, setKind] = useState<ContextKind>("city");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.addIdentifier(kind, value, true);
      setValue("");
      await onChange();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h3>{t("context.title")}</h3>
      <p className="muted">{t("context.intro")}</p>
      <div className="inline-form">
        <select value={kind} onChange={(e) => setKind(e.target.value as ContextKind)} aria-label={t("context.detailLabel")}>
          <option value="city">{t("context.optCity")}</option>
          <option value="birth_year">{t("context.optBirthYear")}</option>
          <option value="workplace">{t("context.optWorkplace")}</option>
        </select>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={t(`ph.${kind}` as MessageKey)}
          inputMode={kind === "birth_year" ? "numeric" : undefined}
          aria-label={t("context.valueLabel")}
          required
        />
        <button className="primary" disabled={busy}>
          {t("details.add")}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </form>
  );
}

function AddPhoto({ meta, onChange }: { meta: Meta | null; onChange: () => Promise<void> }) {
  const { t } = useI18n();
  const [file, setFile] = useState<File | null>(null);
  const [attest, setAttest] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      await api.addImage(file, file.name.replace(/\.[^.]+$/, "") || "photo");
      setFile(null);
      setAttest(false);
      (e.target as HTMLFormElement).reset();
      await onChange();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h3>{t("photo.title")}</h3>
      <p className="muted">
        {t("photo.intro")}
        {meta && !meta.reverse_image_available && t("photo.noReverse")}
      </p>
      <div className="inline-form">
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          aria-label={t("photo.label")}
        />
        <button className="primary" disabled={busy || !file || !attest}>
          {t("photo.upload")}
        </button>
      </div>
      <label className="check">
        <input type="checkbox" checked={attest} onChange={(e) => setAttest(e.target.checked)} />
        {t("photo.attest")}
      </label>
      {error && <p className="error">{error}</p>}
    </form>
  );
}

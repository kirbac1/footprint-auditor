import { useState, type FormEvent } from "react";
import { api, errorText } from "../api";
import type { ContextKind, Identifier, IdentityKind, Kind, Meta } from "../types";

const KIND_LABEL: Record<Kind, string> = {
  email: "Email",
  phone: "Phone",
  name: "Name",
  username: "Username",
  image: "Photo",
  city: "City",
  birth_year: "Birth year",
  workplace: "Workplace",
};

const PLACEHOLDER: Record<IdentityKind, string> = {
  email: "you@example.com",
  phone: "+358 40 123 4567",
  name: "First Last",
  username: "your_handle",
};

const CONTEXT_PLACEHOLDER: Record<ContextKind, string> = {
  city: "A city you live or have lived in",
  birth_year: "1990",
  workplace: "An employer or school",
};

const STATUS_LABEL: Record<Identifier["status"], string> = {
  pending: "Awaiting code",
  verified: "Verified",
  attested: "Confirmed by you",
};

interface Props {
  identifiers: Identifier[];
  meta: Meta | null;
  onChange: () => Promise<void>;
}

export function DetailsTab({ identifiers, meta, onChange }: Props) {
  return (
    <div className="stack">
      <section className="card">
        <h2>Your details</h2>
        <p className="muted">
          Checks only ever cover what is listed here. Emails and phone numbers are verified with a one-time code.
          Names, usernames and photos can't be verified automatically, so you confirm they're yours. They are only
          used once you have verified at least one email or phone.
        </p>
        {identifiers.length === 0 ? (
          <p className="empty">Nothing added yet. Start with your email address.</p>
        ) : (
          <ul className="rows">
            {identifiers.map((i) => (
              <IdentifierRow key={i.id} identifier={i} meta={meta} onChange={onChange} />
            ))}
          </ul>
        )}
      </section>
      <AddIdentifier onChange={onChange} />
      <AddContext onChange={onChange} />
      <AddPhoto meta={meta} onChange={onChange} />
    </div>
  );
}

function IdentifierRow({ identifier: i, meta, onChange }: { identifier: Identifier; meta: Meta | null; onChange: () => Promise<void> }) {
  const [code, setCode] = useState("");
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

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
    if (window.confirm(`Remove this ${KIND_LABEL[i.kind].toLowerCase()} and everything found for it?`)) {
      void run(() => api.deleteIdentifier(i.id));
    }
  }

  return (
    <li className="row">
      <div className="row-main">
        <span className="kind">{KIND_LABEL[i.kind]}</span>
        <span className="value">{i.value}</span>
        <span className={`pill ${i.status}`}>{STATUS_LABEL[i.status]}</span>
        <button className="ghost small" onClick={remove} disabled={busy}>
          Remove
        </button>
      </div>
      {i.status === "pending" && (
        <form className="verify" onSubmit={verify}>
          <input
            inputMode="numeric"
            pattern="\d{6}"
            maxLength={6}
            placeholder="6-digit code"
            aria-label={`Verification code for ${i.value}`}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            required
          />
          <button className="primary small" disabled={busy || code.length !== 6}>
            Verify
          </button>
          <button
            type="button"
            className="ghost small"
            disabled={busy}
            onClick={() => void run(() => api.resend(i.id), "A new code is on its way.")}
          >
            Send a new code
          </button>
          {meta?.code_delivery === "console" && (
            <span className="hint">Local server: the code is printed in the API log.</span>
          )}
        </form>
      )}
      {message && <p className={message.error ? "error" : "success"}>{message.text}</p>}
    </li>
  );
}

function AddIdentifier({ onChange }: { onChange: () => Promise<void> }) {
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
      await api.addIdentifier(kind, value, needsAttest && attest);
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
      <h3>Add a detail</h3>
      <div className="inline-form">
        <select value={kind} onChange={(e) => setKind(e.target.value as IdentityKind)} aria-label="Kind">
          <option value="email">Email</option>
          <option value="phone">Phone</option>
          <option value="name">Full name</option>
          <option value="username">Username</option>
        </select>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={PLACEHOLDER[kind]}
          aria-label="Value"
          required
        />
        <button className="primary" disabled={busy || (needsAttest && !attest)}>
          {needsAttest ? "Add" : "Add and send code"}
        </button>
      </div>
      {needsAttest && (
        <label className="check">
          <input type="checkbox" checked={attest} onChange={(e) => setAttest(e.target.checked)} />
          This {kind} is mine. I understand Footprint can't verify it and relies on my word.
        </label>
      )}
      {error && <p className="error">{error}</p>}
    </form>
  );
}

function AddContext({ onChange }: { onChange: () => Promise<void> }) {
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
      <h3>Tell yourself apart from people with the same name</h3>
      <p className="muted">
        Many people share a name. A city, your birth year or a workplace lets the scan keep results about you and
        leave out the ones about someone else. These details are only used for that comparison. They are never
        searched for on their own.
      </p>
      <div className="inline-form">
        <select value={kind} onChange={(e) => setKind(e.target.value as ContextKind)} aria-label="Detail">
          <option value="city">City</option>
          <option value="birth_year">Birth year</option>
          <option value="workplace">Workplace or school</option>
        </select>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={CONTEXT_PLACEHOLDER[kind]}
          inputMode={kind === "birth_year" ? "numeric" : undefined}
          aria-label="Detail value"
          required
        />
        <button className="primary" disabled={busy}>
          Add
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </form>
  );
}

function AddPhoto({ meta, onChange }: { meta: Meta | null; onChange: () => Promise<void> }) {
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
      <h3>Add a photo of you</h3>
      <p className="muted">
        Used by the impersonation check to find profiles reusing your picture.
        {meta && !meta.reverse_image_available && " Reverse-image search is not configured on this server yet."}
      </p>
      <div className="inline-form">
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          aria-label="Photo"
        />
        <button className="primary" disabled={busy || !file || !attest}>
          Upload
        </button>
      </div>
      <label className="check">
        <input type="checkbox" checked={attest} onChange={(e) => setAttest(e.target.checked)} />
        This is a photo of me.
      </label>
      {error && <p className="error">{error}</p>}
    </form>
  );
}

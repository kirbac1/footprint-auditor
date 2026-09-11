import { useState, type FormEvent } from "react";
import { api, errorText } from "../api";
import type { BreachCheck, Meta } from "../types";

async function sha1Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("").toUpperCase();
}

export function BreachTab({ hasVerified, meta }: { hasVerified: boolean; meta: Meta | null }) {
  return (
    <div className="stack">
      <EmailBreaches hasVerified={hasVerified} meta={meta} />
      <PasswordCheck />
    </div>
  );
}

function EmailBreaches({ hasVerified, meta }: { hasVerified: boolean; meta: Meta | null }) {
  const [result, setResult] = useState<BreachCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const configured = meta?.breach_check_available ?? true;

  async function check() {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.breachCheck());
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <h2>Is your email in a data breach?</h2>
      <p className="muted">
        Looks up your verified email addresses in Have I Been Pwned. Only addresses you've verified are sent.
      </p>
      <button className="primary" onClick={() => void check()} disabled={busy || !hasVerified || !configured}>
        {busy ? "Checking…" : "Check my verified emails"}
      </button>
      {!configured && <p className="hint">Breach lookups are not configured on this server (needs an HIBP API key).</p>}
      {error && <p className="error">{error}</p>}
      {result && (
        <div className="result">
          {result.breaches.length === 0 ? (
            <p className="success">
              No known breaches for your {result.checked_identifiers} verified email
              {result.checked_identifiers === 1 ? "" : "s"}.
            </p>
          ) : (
            <ul className="rows">
              {result.breaches.map((b) => (
                <li key={`${b.identifier_id}-${b.breach_name}`} className="row">
                  <div className="row-main">
                    <span className="value">{b.title}</span>
                    <span className="muted">
                      {b.domain} · {b.breach_date}
                    </span>
                    {b.data_classes.includes("Passwords") && <span className="pill failed">Passwords exposed</span>}
                  </div>
                  <p className="muted">{b.data_classes.join(", ")}</p>
                </li>
              ))}
            </ul>
          )}
          {result.breaches.length > 0 && <p className="hint">Each breach is now an item in your action plan.</p>}
        </div>
      )}
    </section>
  );
}

function PasswordCheck() {
  const [password, setPassword] = useState("");
  const [result, setResult] = useState<{ prefix: string; count: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function check(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const hash = await sha1Hex(password);
      const prefix = hash.slice(0, 5);
      const range = await api.passwordRange(prefix);
      const match = range.suffixes.find((s) => s.suffix === hash.slice(5));
      setResult({ prefix, count: match?.count ?? 0 });
    } catch (err) {
      setError(errorText(err));
    } finally {
      setPassword("");
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={check}>
      <h2>Has a password leaked?</h2>
      <p className="muted">
        Your password never leaves this browser. It is hashed here, and only the first 5 characters of the hash are
        sent. The match is checked on your side.
      </p>
      <div className="inline-form">
        <input
          type="password"
          autoComplete="off"
          placeholder="A password you use"
          aria-label="Password to check"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        <button className="primary" disabled={busy || !password}>
          Check
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {result &&
        (result.count > 0 ? (
          <p className="error">
            Seen {result.count.toLocaleString()} times in breaches. Stop using it anywhere and change it where you have.
          </p>
        ) : (
          <p className="success">Not found in known breaches. That doesn't make it strong, just not known.</p>
        ))}
      {result && <p className="hint">Sent to the server: {result.prefix}</p>}
    </form>
  );
}

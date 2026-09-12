import type { Lang } from "./i18n";
import type {
  BreachCheck,
  Finding,
  Identifier,
  ItemStatus,
  Jurisdiction,
  Me,
  Meta,
  PasswordRange,
  Plan,
  PlanItem,
  Scan,
  ScanKind,
  TraceEvent,
} from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// The token lives in sessionStorage: gone when the tab closes, and the
// server's CSP (script-src 'self', no inline) keeps injected scripts from
// reading it. Access tokens expire after 30 minutes regardless.
const TOKEN_KEY = "footprint.token";

const ISSUED_KEY = "footprint.token.issued";
const REFRESH_AFTER_MS = 20 * 60 * 1000; // tokens live 30 minutes

function readItem(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

let token: string | null = readItem(TOKEN_KEY);
let issuedAt = Number(readItem(ISSUED_KEY) ?? 0);
let onUnauthorized: () => void = () => {};

export function setToken(value: string | null): void {
  token = value;
  issuedAt = value ? Date.now() : 0;
  try {
    if (value) {
      sessionStorage.setItem(TOKEN_KEY, value);
      sessionStorage.setItem(ISSUED_KEY, String(issuedAt));
    } else {
      sessionStorage.removeItem(TOKEN_KEY);
      sessionStorage.removeItem(ISSUED_KEY);
    }
  } catch {
    // Storage blocked: the token still works for this page load.
  }
}

export const hasToken = (): boolean => token !== null;

/** Swap the token for a fresh one once it's 20 minutes old. */
export async function refreshIfStale(): Promise<void> {
  if (!token || Date.now() - issuedAt < REFRESH_AFTER_MS) return;
  try {
    const res = await request<{ access_token: string }>("POST", "/auth/refresh");
    setToken(res.access_token);
  } catch {
    // An expired token lands in the 401 handler, which signs the user out.
  }
}

export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn;
}

export function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof TypeError) return "Can't reach the server. Is it running?";
  return err instanceof Error ? err.message : "Something went wrong.";
}

function detailOf(data: unknown): string | null {
  if (!data || typeof data !== "object" || !("detail" in data)) return null;
  const detail = (data as { detail: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => (d && typeof d === "object" && "msg" in d ? String(d.msg) : "")).join("; ");
  }
  return null;
}

async function request<T>(method: string, path: string, body?: unknown, form?: BodyInit): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload: BodyInit | undefined = form;
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(path, { method, headers, body: payload });
  if (res.status === 401 && token) {
    setToken(null);
    onUnauthorized();
  }
  if (res.status === 204) return undefined as T;
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, detailOf(data) ?? `Request failed (${res.status}).`);
  return data as T;
}

export const api = {
  meta: () => request<Meta>("GET", "/meta"),

  register: (email: string, password: string, inviteCode?: string) =>
    request<unknown>("POST", "/auth/register", { email, password, invite_code: inviteCode || undefined }),
  requestPasswordReset: (email: string) => request<unknown>("POST", "/auth/reset/request", { email }),
  confirmPasswordReset: (email: string, code: string, password: string) =>
    request<void>("POST", "/auth/reset/confirm", { email, code, password }),
  async login(email: string, password: string): Promise<void> {
    const form = new URLSearchParams({ username: email, password });
    const res = await request<{ access_token: string }>("POST", "/auth/token", undefined, form);
    setToken(res.access_token);
  },
  me: () => request<Me>("GET", "/me"),
  deleteAccount: () => request<void>("DELETE", "/me"),

  identifiers: () => request<Identifier[]>("GET", "/identifiers"),
  addIdentifier: (kind: string, value: string, attest: boolean) =>
    request<Identifier>("POST", "/identifiers", { kind, value, attest }),
  addImage(file: File, label: string): Promise<Identifier> {
    const form = new FormData();
    form.append("file", file);
    form.append("attest", "true");
    form.append("label", label);
    return request<Identifier>("POST", "/identifiers/image", undefined, form);
  },
  verify: (id: string, code: string) => request<Identifier>("POST", `/identifiers/${id}/verify`, { code }),
  resend: (id: string) =>
    request<{ status: string; demo_code?: string | null }>("POST", `/identifiers/${id}/resend`),
  startProof: (id: string, platform: string) =>
    request<Identifier>("POST", `/identifiers/${id}/proof`, { platform }),
  checkProof: (id: string) => request<Identifier>("POST", `/identifiers/${id}/proof/check`),
  deleteIdentifier: (id: string) => request<void>("DELETE", `/identifiers/${id}`),

  /** `language` sets the language of the model's explanations and summary. */
  startScan: (kind: ScanKind, language: Lang) =>
    request<{ scan_id: string; status: string }>(
      "POST",
      `${kind === "exposure" ? "/scan" : "/impersonation-check"}?language=${language}`,
    ),
  scans: () => request<Scan[]>("GET", "/scans"),
  scan: (id: string, withTrace = false) =>
    request<Scan>("GET", `/scan/${id}${withTrace ? "?trace=true" : ""}`),
  scanTrace: (id: string) => request<TraceEvent[]>("GET", `/scan/${id}/trace`),
  confirmFinding: (id: string) => request<Finding>("POST", `/findings/${id}/confirm`),
  notMe: (id: string) => request<void>("POST", `/findings/${id}/not-me`),

  breachCheck: () => request<BreachCheck>("POST", "/breach-check"),
  passwordRange: (prefix: string) => request<PasswordRange>("POST", "/breach-check/password-range", { sha1_prefix: prefix }),

  /** Rebuilds the plan from current findings; GET would only read the last one. */
  plan: (jurisdiction: Jurisdiction, language: Lang) =>
    request<Plan>("POST", `/remediation-plan?jurisdiction=${encodeURIComponent(jurisdiction)}&language=${language}`),
  updateItem: (id: string, status: ItemStatus) =>
    request<PlanItem>("PATCH", `/remediation-plan/items/${id}`, { status }),
};

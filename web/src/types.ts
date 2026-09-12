export type IdentityKind = "email" | "phone" | "name" | "username";
export type ContextKind = "city" | "birth_year" | "workplace";
export type Kind = IdentityKind | ContextKind | "image";

export interface Meta {
  demo_scans: boolean;
  scripted_model: boolean;
  demo_account: { email: string; password: string } | null;
  registration_open: boolean;
  invite_required: boolean;
  codes_on_page: boolean;
  scans_available: boolean;
  reverse_image_available: boolean;
  breach_check_available: boolean;
  code_delivery: "console" | "aws";
  donate_url: string | null;
  username_proof_required: boolean;
  proof_platforms: { id: string; label: string; profile_url: string }[];
  limits: { names: number; usernames: number; images: number; scans_per_day: number };
}

export interface Me {
  id: string;
  email: string;
  created_at: string;
}

export interface Identifier {
  id: string;
  kind: Kind;
  value: string;
  status: "pending" | "verified" | "attested";
  created_at: string;
  verified_at: string | null;
  proof_platform: string | null;
  proof_code: string | null;
  proof_expires_at: string | null;
  demo_code?: string | null;
}

export type ScanKind = "exposure" | "impersonation";
export type ScanStatus = "queued" | "running" | "completed" | "failed" | "refused";

export interface Finding {
  id: string;
  category: string;
  url: string;
  title: string;
  broker_id: string | null;
  matched_identifier_ids: string[];
  confidence: "high" | "medium" | "low";
  rationale: string;
  match_status: "likely" | "unclear" | "confirmed";
}

export interface Scan {
  id: string;
  kind: ScanKind;
  status: ScanStatus;
  summary: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  namesakes_excluded: number;
  model_calls: number;
  tool_calls: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  duration_ms: number | null;
  cost_usd: number | null;
  findings: Finding[];
  trace?: TraceEvent[] | null;
}

export interface TraceEvent {
  seq: number;
  kind: "model_call" | "tool_call";
  name: string;
  status: string;
  detail: string | null;
  offset_ms: number;
  duration_ms: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
}

export interface Breach {
  identifier_id: string;
  breach_name: string;
  title: string;
  domain: string;
  breach_date: string;
  data_classes: string[];
  is_verified: boolean;
}

export interface BreachCheck {
  checked_identifiers: number;
  breaches: Breach[];
}

export interface PasswordRange {
  prefix: string;
  suffixes: { suffix: string; count: number }[];
}

export type Jurisdiction = "EU" | "FI" | "US-CA" | "US" | "OTHER";
export type ItemStatus = "open" | "sent" | "done" | "dismissed";

export interface PlanItem {
  id: string;
  action_type: string;
  priority: number;
  title: string;
  detail: string;
  url: string | null;
  draft: string | null;
  status: ItemStatus;
  source_type: string;
  source_id: string | null;
}

export interface Plan {
  jurisdiction: Jurisdiction | null;
  items: PlanItem[];
}

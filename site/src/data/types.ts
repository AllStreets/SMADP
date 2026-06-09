/**
 * TypeScript types mirroring the SMADP JSON schemas at
 * catalog/_meta/schema/1.0/*.schema.json. Keep these in sync.
 */

// ----- Shared primitives -----
export type Severity = 'none' | 'low' | 'medium' | 'high' | 'critical';
export type EvidenceLevel =
  | 'unverified-profile'
  | 'docs-only'
  | 'profile-verified'
  | 'sandbox-validated';

export type RiskId =
  | 'A_prompt_injection'
  | 'B_data_leakage'
  | 'C_capability_conflict'
  | 'D_cascading_error'
  | 'E_compliance';

export const RISK_ORDER: RiskId[] = [
  'A_prompt_injection',
  'B_data_leakage',
  'C_capability_conflict',
  'D_cascading_error',
  'E_compliance',
];

// ----- Profile -----
export interface Profile {
  schema_version: '1.0';
  slug: string;
  name: string;
  tagline?: string;
  vendor: {
    type: 'company' | 'org' | 'individual';
    handle: string;
    url?: string | null;
  };
  source_type: 'open-source' | 'closed-source' | 'source-available';
  category: string;
  homepage?: string | null;
  docs_urls?: string[];
  repo_url?: string | null;
  verification: {
    status: 'unverified' | 'draft' | 'verified' | 'stale' | 'invalid';
    verified_by?: string | null;
    verified_at: string;
    method: 'manual-review-of-llm-extraction' | 'manual-authoring' | 'auto-only';
  };
  capabilities: {
    execute_shell?: boolean;
    read_filesystem?: boolean;
    write_filesystem?: boolean;
    network_egress?: 'none' | 'allowlisted' | 'vendor-only' | 'broad';
    spawn_subprocesses?: boolean;
    use_mcp?: boolean;
    modify_git_state?: boolean;
    install_packages?: boolean;
    run_browsers?: boolean;
  };
  io_surfaces: {
    stdin_stdout?: boolean;
    files?: string[];
    clipboard?: boolean;
    screen_capture?: boolean;
    audio?: boolean;
    calls_apis?: string[];
  };
  permissions_requested: {
    oauth_scopes?: string[];
    secrets_handled?: string[];
    elevated_privileges?: string[];
  };
  data_classes_touched: string[];
  sandboxing: {
    self_isolation?: string;
    subagent_model?: string;
    tool_use_pattern?: string;
  };
  concurrency_model: {
    session_scope?: string;
    shared_state_with_other_instances?: string;
    supports_multiple_instances?: boolean;
  };
  evidence_refs: string[];
  pairings?: string[];
  first_seen_at: string;
  last_refreshed_at: string;
}

// ----- Verdict -----
export interface Citation {
  profile_field?: string;
  evidence_ref?: string;
  quote?: string;
}
export interface SubVerdict {
  severity: Severity;
  rationale: string;
  citations: Citation[];
  conditions: string[];
  mitigations: string[];
}
export interface SandboxRun {
  run_id: string;
  started_at: string;
  completed_at?: string | null;
  outcome: 'pass' | 'fail' | 'inconclusive' | 'errored';
  transcript_ref: string;
  scenario?: string;
}
export interface Verdict {
  schema_version: '1.0';
  pair: [string, string];
  verdict_id: string;
  generated_at: string;
  model: { name: string; id: string; rubric_version: string };
  evidence_level: EvidenceLevel;
  confidence: number;
  composite_score: number;
  headline: string;
  sub_verdicts: Record<RiskId, SubVerdict>;
  framework_mappings: Record<string, string[]>;
  reproducibility: {
    rubric_url: string;
    profile_a_hash: string;
    profile_b_hash: string;
    evidence_bundle_hash: string;
  };
  sandbox_runs: SandboxRun[];
}

// ----- Meta -----
export interface RiskTaxonomy {
  schema_version: string;
  severities: { id: Severity; score: number; label: string; color: string }[];
  evidence_levels: { id: EvidenceLevel; label: string; rank: number; color: string }[];
  risks: {
    id: RiskId;
    letter: string;
    name: string;
    weight: number;
    description: string;
    examples: string[];
    evaluation_dimensions: string[];
  }[];
}

export interface CategoriesFile {
  schema_version: string;
  categories: { id: string; name: string; description: string }[];
}

export interface FrameworksFile {
  schema_version: string;
  frameworks: {
    id: string;
    name: string;
    version: string;
    url: string;
    controls: { id: string; name: string; applies_to_risks: RiskId[] }[];
  }[];
}

export interface ChronicleEvent {
  ts: string;
  // `event` is the canonical field (e.g. "profile.created", "sandbox.run.completed").
  // The older seed entries used `kind` for the same thing; either is accepted.
  event?: string;
  kind?: string;
  // Actor field — `by` in current entries, `actor` in older seed entries.
  by?: string;
  actor?: string;
  // Subject — can be a single slug, a pair, or a generic ref. Newer entries
  // put the slug pair under `pair`; older seed entries use `slug` or `ref`.
  slug?: string;
  pair?: string[];
  ref?: string;
  // Outcome of sandbox / verdict events.
  outcome?: string;
  // Free-form details bag.
  details?: Record<string, unknown>;
  message?: string;
  [k: string]: unknown;
}

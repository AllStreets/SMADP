export type Severity = 'none' | 'low' | 'medium' | 'high' | 'critical';
export type EvidenceLevel =
  | 'unverified-profile'
  | 'docs-only'
  | 'profile-verified'
  | 'sandbox-validated';

export type RiskKey =
  | 'A_prompt_injection'
  | 'B_data_leakage'
  | 'C_capability_conflict'
  | 'D_cascading_error'
  | 'E_compliance';

export const RISK_KEYS: RiskKey[] = [
  'A_prompt_injection',
  'B_data_leakage',
  'C_capability_conflict',
  'D_cascading_error',
  'E_compliance'
];

export interface SubVerdict {
  severity: Severity;
  rationale: string;
  citations: { profile_field?: string; evidence_ref?: string; quote?: string }[];
  conditions: string[];
  mitigations: string[];
}

export interface SandboxRun {
  run_id: string;
  scenario: string;
  outcome: 'pass' | 'fail' | 'error';
  started_at: string;
  completed_at: string;
  transcript_ref: string;
}

export interface Verdict {
  verdict_id: string;
  pair: [string, string];
  composite_score: number;
  confidence: number;
  evidence_level: EvidenceLevel;
  headline: string;
  generated_at: string;
  framework_mappings: Record<string, string[]>;
  sub_verdicts: Record<RiskKey, SubVerdict>;
  sandbox_runs: SandboxRun[];
}

export interface ProfileCapabilities {
  execute_shell?: boolean;
  read_filesystem?: boolean;
  write_filesystem?: boolean;
  network_egress?: 'none' | 'allowlist' | 'broad' | 'unknown';
  spawn_subprocesses?: boolean;
  use_mcp?: boolean;
  modify_git_state?: boolean;
  install_packages?: boolean;
  run_browsers?: boolean;
}

export interface Profile {
  slug: string;
  name: string;
  description?: string;
  homepage?: string;
  capabilities?: ProfileCapabilities;
  io_surfaces?: {
    stdin_stdout?: boolean;
    files?: string[];
    calls_apis?: string[];
  };
  trust_floor?: number;
  evidence_level?: EvidenceLevel;
}

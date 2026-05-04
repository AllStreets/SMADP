/**
 * Client-side chain analyzer. TypeScript port of
 * `scripts/v2_e/generate_verdicts.py`'s heuristics, generalised from
 * pairwise to N-agent chains. Pure: takes a draft chain plus a list
 * of participant profile-summaries and returns sub-verdicts.
 *
 * Inputs are intentionally small (`ProfileSummary`) so the page can
 * embed only the fields we need for the 100 agents.
 */

import type { Severity, RiskId } from '../data/types';

export interface ProfileSummary {
  slug: string;
  name: string;
  vendor: string;
  source_type: 'open-source' | 'closed-source' | 'source-available';
  category: string;
  caps: {
    execute_shell?: boolean;
    write_filesystem?: boolean;
    modify_git_state?: boolean;
    install_packages?: boolean;
    spawn_subprocesses?: boolean;
    use_mcp?: boolean;
    run_browsers?: boolean;
    network_egress?: 'none' | 'allowlisted' | 'vendor-only' | 'broad';
  };
  io: {
    files?: boolean;
    calls_apis?: boolean;
  };
}

export type ChainTopology = 'linear' | 'star' | 'loop' | 'tree' | 'dag';
export type ChainChannel =
  | 'prompt' | 'tool-call' | 'shared-memory' | 'filesystem' | 'message-bus';

export interface DraftEdge {
  from: string;
  to: string;
  channel: ChainChannel;
  carries: string[];
}

export interface DraftChain {
  name: string;
  topology: ChainTopology;
  participants: { slug: string; role: string; notes?: string }[];
  edges: DraftEdge[];
}

export interface SubVerdict {
  severity: Severity;
  rationale: string;
}
export type SubVerdicts = Record<RiskId, SubVerdict>;

export const SEV_TO_SCORE: Record<Severity, number> = {
  none: 0,
  low: 0.2,
  medium: 0.5,
  high: 0.8,
  critical: 1,
};

const SEV_LADDER: Severity[] = ['low', 'low', 'medium', 'medium', 'high'];
const sev = (rank: number): Severity =>
  SEV_LADDER[Math.max(0, Math.min(SEV_LADDER.length - 1, rank))]!;

const HIGH_REG = new Set([
  'healthcare',
  'legal-research',
  'financial-modeling',
  'bioinformatics',
]);
const MED_REG = new Set([
  'customer-support',
  'education-tutoring',
  'sql-analytics',
  'document-processing',
  'email-scheduling',
  'sales-crm',
]);

function ingestionScore(p: ProfileSummary): number {
  let n = 0;
  if (p.caps.run_browsers) n++;
  if (p.caps.use_mcp) n++;
  if (p.caps.network_egress === 'broad') n++;
  if (p.io.calls_apis) n++;
  if (p.io.files) n++;
  return n;
}

const MUTATING_CAPS = [
  'execute_shell',
  'write_filesystem',
  'modify_git_state',
  'install_packages',
  'spawn_subprocesses',
] as const;

function mutatingCaps(p: ProfileSummary): Set<string> {
  const out = new Set<string>();
  for (const k of MUTATING_CAPS) if (p.caps[k]) out.add(k);
  return out;
}

/* ---------- Risk computations ---------- */

function riskA(parts: ProfileSummary[]): SubVerdict {
  // Prompt injection: total ingestion surface across the chain.
  const total = parts.reduce((s, p) => s + ingestionScore(p), 0);
  const max = parts.length > 0 ? Math.max(...parts.map(ingestionScore)) : 0;
  const rank =
    (max >= 3 ? 1 : 0) + (total >= 5 ? 1 : 0) + (total >= 8 ? 1 : 0) + (parts.length >= 4 ? 1 : 0);
  const list = parts
    .map((p) => `${p.name}=${ingestionScore(p)}`)
    .join(', ');
  return {
    severity: sev(rank),
    rationale:
      `Total ingestion surface across the ${parts.length}-agent chain: ${total} ` +
      `(per-agent: ${list}). Untrusted content entering any node can be relayed ` +
      `to every downstream agent through the shared workspace.`,
  };
}

function riskB(parts: ProfileSummary[]): SubVerdict {
  const vendors = new Set(parts.map((p) => p.vendor || '?'));
  const closed = parts.some((p) => p.source_type === 'closed-source');
  const egress = parts.some((p) => p.caps.network_egress === 'broad');
  const rank =
    (vendors.size >= 2 ? 1 : 0) +
    (vendors.size >= 3 ? 1 : 0) +
    (closed ? 1 : 0) +
    (egress ? 1 : 0);
  return {
    severity: sev(rank),
    rationale:
      `Distinct vendors: ${vendors.size} (${[...vendors].join(', ')}). ` +
      `Closed-source participants: ${closed ? 'yes' : 'no'}. ` +
      `Broad-egress participants: ${egress ? 'yes' : 'no'}. ` +
      `Each provider boundary is an opportunity for the chain's data to land somewhere new.`,
  };
}

function riskC(parts: ProfileSummary[]): SubVerdict {
  // Capability conflict: how often do mutating caps collide across pairs?
  if (parts.length < 2) {
    return { severity: 'none', rationale: 'Single agent — nothing to collide with.' };
  }
  const seen: Record<string, number> = {};
  for (const p of parts) for (const c of mutatingCaps(p)) seen[c] = (seen[c] ?? 0) + 1;
  const overlap = Object.entries(seen).filter(([, n]) => n >= 2);
  const rank = overlap.length === 0 ? 0 : overlap.length === 1 ? 1 : overlap.length === 2 ? 2 : overlap.length === 3 ? 3 : 4;
  if (overlap.length === 0) {
    return {
      severity: sev(rank),
      rationale:
        'No mutating capability is shared by two or more participants — ' +
        'concurrent operation is unlikely to interleave on the same surface.',
    };
  }
  const list = overlap.map(([c, n]) => `${c} (${n} agents)`).join(', ');
  return {
    severity: sev(rank),
    rationale:
      `Mutating capabilities held by 2+ chain participants: ${list}. ` +
      `When more than one node writes to the same surface, errors compound and ` +
      `the order of operations becomes the security boundary.`,
  };
}

function riskD(parts: ProfileSummary[], edges: DraftEdge[], topology: ChainTopology): SubVerdict {
  const fsCount = parts.filter((p) => p.caps.write_filesystem).length;
  const gitCount = parts.filter((p) => p.caps.modify_git_state).length;
  const sharedFs = fsCount >= 2;
  const sharedGit = gitCount >= 2;
  const fsEdges = edges.filter((e) => e.channel === 'filesystem').length;
  const looped = topology === 'loop';
  const rank =
    (sharedFs ? 1 : 0) +
    (sharedGit ? 1 : 0) +
    (fsEdges >= 2 ? 1 : 0) +
    (looped ? 1 : 0);
  return {
    severity: sev(rank),
    rationale:
      `Persistent state writers — filesystem: ${fsCount}, git: ${gitCount}. ` +
      `Filesystem edges: ${fsEdges}. Topology: ${topology}. ` +
      (looped
        ? "Loops let one agent's mistake be re-read by the next pass, amplifying drift."
        : "Errors written by one node become inputs to the next."),
  };
}

function riskE(parts: ProfileSummary[]): SubVerdict {
  const cats = new Set(parts.map((p) => p.category));
  const high = [...cats].filter((c) => HIGH_REG.has(c));
  const med = [...cats].filter((c) => MED_REG.has(c));
  const rank =
    (high.length > 0 ? 3 : 0) +
    (med.length > 0 && high.length === 0 ? 2 : 0) +
    (high.length === 0 && med.length === 0 ? 1 : 0);
  return {
    severity: sev(rank),
    rationale:
      `Categories represented: ${[...cats].join(', ') || '—'}. ` +
      (high.length
        ? `Includes regulated category — ${high.join(', ')}.`
        : med.length
          ? `Touches medium-regulation category — ${med.join(', ')}.`
          : 'No regulated-data category in the chain.'),
  };
}

/* ---------- Public API ---------- */

export function analyze(
  draft: DraftChain,
  profiles: Record<string, ProfileSummary>,
): { sub_verdicts: SubVerdicts; composite: number; missing: string[] } {
  const parts: ProfileSummary[] = [];
  const missing: string[] = [];
  for (const ptcp of draft.participants) {
    const p = profiles[ptcp.slug];
    if (p) parts.push(p);
    else missing.push(ptcp.slug);
  }
  if (parts.length === 0) {
    const empty: SubVerdict = {
      severity: 'none',
      rationale: 'Add at least one agent to compute risks.',
    };
    return {
      sub_verdicts: {
        A_prompt_injection: empty,
        B_data_leakage: empty,
        C_capability_conflict: empty,
        D_cascading_error: empty,
        E_compliance: empty,
      },
      composite: 0,
      missing,
    };
  }
  const sub_verdicts: SubVerdicts = {
    A_prompt_injection: riskA(parts),
    B_data_leakage: riskB(parts),
    C_capability_conflict: riskC(parts),
    D_cascading_error: riskD(parts, draft.edges, draft.topology),
    E_compliance: riskE(parts),
  };
  const composite =
    Object.values(sub_verdicts).reduce((s, sv) => s + SEV_TO_SCORE[sv.severity], 0) / 5;
  return { sub_verdicts, composite: Math.round(composite * 100) / 100, missing };
}

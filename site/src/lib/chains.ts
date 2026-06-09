/**
 * Build-time chains loader. Reads catalog/chains/*.json from disk.
 * All access is synchronous and memoized — Astro calls these from page
 * frontmatter at build time.
 */

import { readFileSync, readdirSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
// site/src/lib → ../../../catalog/chains
const CHAINS_DIR = resolve(__dirname, '..', '..', '..', 'catalog', 'chains');

export type ChainTopology = 'linear' | 'star' | 'loop' | 'tree' | 'dag';
export type ChainRole =
  | 'planner' | 'executor' | 'critic' | 'retriever' | 'reasoner'
  | 'writer' | 'router' | 'tool' | 'judge' | 'memory';
export type ChainChannel =
  | 'prompt' | 'tool-call' | 'shared-memory' | 'filesystem' | 'message-bus';

export interface ChainParticipant {
  slug: string;
  role: ChainRole;
  notes?: string;
}

export interface ChainEdge {
  from: string;
  to: string;
  channel: ChainChannel;
  carries?: string[];
}

export interface SubVerdict {
  severity: 'none' | 'low' | 'medium' | 'high' | 'critical';
  rationale: string;
  citations: { profile_field?: string; evidence_ref?: string; quote?: string }[];
  conditions: string[];
  mitigations: string[];
}

export type EvidenceLevel =
  | 'unverified-profile'
  | 'docs-only'
  | 'profile-verified'
  | 'sandbox-validated';

export interface Chain {
  schema_version: '1.0';
  chain_id: string;
  name: string;
  tagline?: string;
  author?: string;
  topology: ChainTopology;
  participants: ChainParticipant[];
  edges: ChainEdge[];
  headline: string;
  sub_verdicts: {
    A_prompt_injection: SubVerdict;
    B_data_leakage: SubVerdict;
    C_capability_conflict: SubVerdict;
    D_cascading_error: SubVerdict;
    E_compliance: SubVerdict;
  };
  composite_score?: number;
  max_severity?: SubVerdict['severity'];
  evidence_level?: EvidenceLevel;
  confidence?: number;
  framework_mappings: Record<string, string[]>;
  evidence_refs: string[];
  first_seen_at: string;
  last_refreshed_at: string;
}

const SEVERITY_SCORES: Record<SubVerdict['severity'], number> = {
  none: 0.0,
  low: 0.2,
  medium: 0.5,
  high: 0.8,
  critical: 1.0,
};

const RISK_WEIGHTS = {
  A_prompt_injection: 0.10,
  B_data_leakage: 0.30,
  C_capability_conflict: 0.25,
  D_cascading_error: 0.20,
  E_compliance: 0.15,
} as const;

/** Composite from sub-verdicts using the canonical rubric weights. */
export function computeComposite(chain: Chain): number {
  if (typeof chain.composite_score === 'number') return chain.composite_score;
  let total = 0;
  for (const [k, w] of Object.entries(RISK_WEIGHTS) as [keyof typeof RISK_WEIGHTS, number][]) {
    total += SEVERITY_SCORES[chain.sub_verdicts[k].severity] * w;
  }
  return Math.round(total * 100) / 100;
}

let _cache: Chain[] | null = null;

export function getChains(): Chain[] {
  if (_cache) return _cache;
  let entries: string[];
  try {
    entries = readdirSync(CHAINS_DIR);
  } catch {
    _cache = [];
    return [];
  }
  const chains: Chain[] = [];
  for (const name of entries) {
    if (!name.endsWith('.json')) continue;
    const raw = readFileSync(join(CHAINS_DIR, name), 'utf-8');
    chains.push(JSON.parse(raw) as Chain);
  }
  chains.sort((a, b) => a.chain_id.localeCompare(b.chain_id));
  _cache = chains;
  return chains;
}

export function getChain(chainId: string): Chain | null {
  return getChains().find((c) => c.chain_id === chainId) ?? null;
}

export function maxSeverity(chain: Chain): SubVerdict['severity'] {
  const order = ['none', 'low', 'medium', 'high', 'critical'] as const;
  let max: SubVerdict['severity'] = 'none';
  for (const sv of Object.values(chain.sub_verdicts)) {
    if (order.indexOf(sv.severity) > order.indexOf(max)) max = sv.severity;
  }
  return max;
}

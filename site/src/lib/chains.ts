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

export interface Chain {
  schema_version: '1.0';
  chain_id: string;
  name: string;
  tagline?: string;
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
  framework_mappings: Record<string, string[]>;
  evidence_refs: string[];
  first_seen_at: string;
  last_refreshed_at: string;
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

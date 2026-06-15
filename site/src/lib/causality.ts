/**
 * Deterministic causal-risk computation — TypeScript port.
 *
 * This is a 1:1 port of smadp/analyzer/causality.py. The two implementations
 * are kept in lockstep by identical golden tests in tests/unit/test_causality.py
 * (pytest) and site/tests/lib/causality.test.ts (vitest). ANY change to the
 * rules here must be mirrored in the Python module, or the parity tests fail.
 *
 * Rules:
 *   SCORE: none=0, low=0.2, medium=0.5, high=0.8, critical=1.0.
 *   Edge src->dst ACTIVE iff score(src) >= 0.5 AND score(dst) > 0.
 *   amplification = round4(score(src)*score(dst)) when active, else 0.
 *   leverage(n) = round4(score(n) + sum(score(d)) over active-edge descendants).
 *   best_mitigation = max-leverage node with leverage > 0, ties broken by the
 *     canonical A<B<C<D<E order; null when every leverage is 0.
 */

export const RISK_IDS = [
  'A_prompt_injection',
  'B_data_leakage',
  'C_capability_conflict',
  'D_cascading_error',
  'E_compliance',
] as const;

export type RiskId = (typeof RISK_IDS)[number];

const SCORE: Record<string, number> = {
  none: 0.0,
  low: 0.2,
  medium: 0.5,
  high: 0.8,
  critical: 1.0,
};

const ACTIVE_SRC_THRESHOLD = 0.5;

export interface CausalEdgeDef {
  from: string;
  to: string;
  mechanism: string;
}

export interface CausalityDag {
  nodes: string[];
  edges: CausalEdgeDef[];
}

export interface EdgeAssessment {
  from: string;
  to: string;
  mechanism: string;
  amplification: number;
  active: boolean;
}

export interface CausalityReport {
  severities: Record<string, string>;
  edges: EdgeAssessment[];
  leverage: Record<string, number>;
  best_mitigation: string | null;
}

export class CausalityError extends Error {}

/** Round to 4 decimals (matches Python round(x, 4) for these magnitudes). */
function round4(value: number): number {
  return Math.round((value + Number.EPSILON) * 1e4) / 1e4;
}

function score(severity: string): number {
  if (!(severity in SCORE)) {
    throw new CausalityError(`unknown severity ${severity}`);
  }
  return SCORE[severity]!;
}

/** Validate + normalize a raw DAG object (used both at build and in tests). */
export function loadCausalityDag(raw: unknown): CausalityDag {
  if (typeof raw !== 'object' || raw === null) {
    throw new CausalityError('risk-causality DAG must be an object');
  }
  const obj = raw as { nodes?: unknown; edges?: unknown };
  const nodesRaw = obj.nodes;
  if (!Array.isArray(nodesRaw)) {
    throw new CausalityError('DAG nodes must be an array');
  }
  const nodes = nodesRaw.map((n) => String(n));
  const nodeSet = new Set(nodes);
  const riskSet = new Set<string>(RISK_IDS);
  if (nodeSet.size !== riskSet.size || ![...riskSet].every((r) => nodeSet.has(r))) {
    throw new CausalityError('DAG nodes must be exactly the five risk ids');
  }
  const edgesRaw = obj.edges;
  if (!Array.isArray(edgesRaw)) {
    throw new CausalityError("DAG 'edges' must be an array");
  }
  const seen = new Set<string>();
  const edges: CausalEdgeDef[] = [];
  for (const e of edgesRaw) {
    if (typeof e !== 'object' || e === null) {
      throw new CausalityError('each edge must be an object');
    }
    const edge = e as { from?: unknown; to?: unknown; mechanism?: unknown };
    const from = String(edge.from ?? '');
    const to = String(edge.to ?? '');
    const mechanism = String(edge.mechanism ?? '');
    if (!nodeSet.has(from) || !nodeSet.has(to)) {
      throw new CausalityError(`edge ${from}->${to} references unknown node`);
    }
    if (from === to) {
      throw new CausalityError(`self-loop on node ${from} is not allowed`);
    }
    const key = `${from}->${to}`;
    if (seen.has(key)) {
      throw new CausalityError(`duplicate edge ${key}`);
    }
    seen.add(key);
    edges.push({ from, to, mechanism });
  }
  assertAcyclic(nodes, edges);
  return { nodes, edges };
}

/** Kahn topological sort; throws CausalityError if a cycle remains. */
function assertAcyclic(nodes: string[], edges: CausalEdgeDef[]): void {
  const indeg = new Map<string, number>(nodes.map((n) => [n, 0]));
  const adj = new Map<string, string[]>();
  for (const e of edges) {
    indeg.set(e.to, (indeg.get(e.to) ?? 0) + 1);
    (adj.get(e.from) ?? adj.set(e.from, []).get(e.from)!).push(e.to);
  }
  const queue = nodes.filter((n) => (indeg.get(n) ?? 0) === 0);
  let visited = 0;
  while (queue.length > 0) {
    const n = queue.shift()!;
    visited += 1;
    for (const m of adj.get(n) ?? []) {
      const d = (indeg.get(m) ?? 0) - 1;
      indeg.set(m, d);
      if (d === 0) queue.push(m);
    }
  }
  if (visited !== nodes.length) {
    throw new CausalityError('causal DAG contains a cycle');
  }
}

function activeDescendants(
  start: string,
  activeAdj: Map<string, string[]>,
): Set<string> {
  const seen = new Set<string>();
  const stack = [...(activeAdj.get(start) ?? [])];
  while (stack.length > 0) {
    const node = stack.pop()!;
    if (seen.has(node)) continue;
    seen.add(node);
    stack.push(...(activeAdj.get(node) ?? []));
  }
  return seen;
}

export function computeCausality(
  severities: Record<string, string>,
  dag: CausalityDag,
): CausalityReport {
  const sc: Record<string, number> = {};
  for (const rid of RISK_IDS) sc[rid] = score(severities[rid]!);

  const edges: EdgeAssessment[] = [];
  const activeAdj = new Map<string, string[]>();
  for (const e of dag.edges) {
    const active = sc[e.from]! >= ACTIVE_SRC_THRESHOLD && sc[e.to]! > 0.0;
    const amplification = active ? round4(sc[e.from]! * sc[e.to]!) : 0.0;
    edges.push({
      from: e.from,
      to: e.to,
      mechanism: e.mechanism,
      amplification,
      active,
    });
    if (active) {
      (activeAdj.get(e.from) ?? activeAdj.set(e.from, []).get(e.from)!).push(e.to);
    }
  }

  const leverage: Record<string, number> = {};
  for (const rid of RISK_IDS) {
    const descendants = activeDescendants(rid, activeAdj);
    let total = sc[rid]!;
    for (const d of descendants) total += sc[d]!;
    leverage[rid] = round4(total);
  }

  let best: string | null = null;
  let bestValue = 0.0;
  for (const rid of RISK_IDS) {
    if (leverage[rid]! > bestValue) {
      bestValue = leverage[rid]!;
      best = rid;
    }
  }

  const orderedSeverities: Record<string, string> = {};
  for (const rid of RISK_IDS) orderedSeverities[rid] = severities[rid]!;

  return {
    severities: orderedSeverities,
    edges,
    leverage,
    best_mitigation: best,
  };
}

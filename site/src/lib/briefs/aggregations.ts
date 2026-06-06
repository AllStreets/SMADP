import type { EvidenceLevel, RiskKey, Severity, Verdict } from './types';
import { RISK_KEYS } from './types';

const SEVERITY_RANK: Record<Severity, number> = {
  none: 0, low: 1, medium: 2, high: 3, critical: 4
};
const SEVERITY_FROM_RANK: Severity[] = ['none', 'low', 'medium', 'high', 'critical'];

export function rankByComposite(verdicts: Verdict[]): Verdict[] {
  return [...verdicts].sort((a, b) => a.composite_score - b.composite_score);
}

export interface EvidenceCounts {
  sandbox: Verdict[];
  profileVerified: Verdict[];
  docsOnly: Verdict[];
  unverified: Verdict[];
}

export function groupByEvidenceTier(verdicts: Verdict[]): EvidenceCounts {
  const groups: EvidenceCounts = {
    sandbox: [], profileVerified: [], docsOnly: [], unverified: []
  };
  for (const v of verdicts) {
    switch (v.evidence_level as EvidenceLevel) {
      case 'sandbox-validated': groups.sandbox.push(v); break;
      case 'profile-verified': groups.profileVerified.push(v); break;
      case 'docs-only': groups.docsOnly.push(v); break;
      default: groups.unverified.push(v);
    }
  }
  return groups;
}

export type SeverityDistribution = Record<RiskKey, Record<Severity, number>>;

export function severityDistribution(verdicts: Verdict[]): SeverityDistribution {
  const dist = {} as SeverityDistribution;
  for (const key of RISK_KEYS) {
    dist[key] = { none: 0, low: 0, medium: 0, high: 0, critical: 0 };
  }
  for (const v of verdicts) {
    for (const key of RISK_KEYS) {
      const sev = v.sub_verdicts[key]?.severity;
      if (sev) dist[key][sev] += 1;
    }
  }
  return dist;
}

export function worstSeverity(values: Severity[]): Severity {
  let rank = 0;
  for (const s of values) rank = Math.max(rank, SEVERITY_RANK[s] ?? 0);
  return SEVERITY_FROM_RANK[rank];
}

export interface HeatmapCell {
  agent: string;
  risk: RiskKey;
  severity: Severity;
  pairCount: number;
}

export function heatmapMatrix(
  verdicts: Verdict[],
  agentSlugs: string[]
): HeatmapCell[] {
  const cells: HeatmapCell[] = [];
  for (const agent of agentSlugs) {
    const involved = verdicts.filter((v) => v.participants.includes(agent));
    for (const risk of RISK_KEYS) {
      const sevList = involved.map((v) => v.sub_verdicts[risk].severity);
      cells.push({
        agent,
        risk,
        severity: worstSeverity(sevList),
        pairCount: involved.length
      });
    }
  }
  return cells;
}

export function appearanceCounts(verdicts: Verdict[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const v of verdicts) {
    for (const slug of v.participants) {
      counts.set(slug, (counts.get(slug) ?? 0) + 1);
    }
  }
  return counts;
}

export function topAgentsByAppearance(verdicts: Verdict[], n: number): string[] {
  return [...appearanceCounts(verdicts).entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, n)
    .map(([slug]) => slug);
}

export function frameworkCoverage(verdicts: Verdict[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const v of verdicts) {
    for (const fw of Object.keys(v.framework_mappings ?? {})) {
      counts[fw] = (counts[fw] ?? 0) + 1;
    }
  }
  return counts;
}

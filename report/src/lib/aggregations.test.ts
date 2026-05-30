import { describe, it, expect } from 'vitest';
import {
  rankByComposite,
  groupByEvidenceTier,
  severityDistribution,
  worstSeverity,
  heatmapMatrix,
  topAgentsByAppearance,
  appearanceCounts,
  frameworkCoverage
} from './aggregations';
import { loadVerdicts } from './catalog';
import type { Verdict, Severity } from './types';

function fakeVerdict(over: Partial<Verdict> & {
  pair: [string, string];
  composite: number;
  evidence?: Verdict['evidence_level'];
  severities?: Partial<Record<keyof Verdict['sub_verdicts'], Severity>>;
}): Verdict {
  const sev = (s: Severity = 'low') => ({
    severity: s, rationale: 'r', citations: [{ profile_field: 'x' }],
    conditions: [], mitigations: []
  });
  const sevs = over.severities ?? {};
  return {
    verdict_id: `v_${over.pair[0]}__${over.pair[1]}`,
    pair: over.pair,
    participants: [...over.pair],
    kind: 'pair',
    composite_score: over.composite,
    confidence: 0.5,
    evidence_level: over.evidence ?? 'docs-only',
    headline: 'h',
    generated_at: '2026-05-14T00:00:00Z',
    framework_mappings: {},
    sub_verdicts: {
      A_prompt_injection: sev(sevs.A_prompt_injection ?? 'medium'),
      B_data_leakage: sev(sevs.B_data_leakage ?? 'low'),
      C_capability_conflict: sev(sevs.C_capability_conflict ?? 'low'),
      D_cascading_error: sev(sevs.D_cascading_error ?? 'low'),
      E_compliance: sev(sevs.E_compliance ?? 'none')
    },
    sandbox_runs: []
  };
}

describe('worstSeverity', () => {
  it('returns the highest-rank severity', () => {
    expect(worstSeverity(['low', 'high', 'medium'])).toBe('high');
    expect(worstSeverity(['none', 'none'])).toBe('none');
    expect(worstSeverity([])).toBe('none');
  });
});

describe('rankByComposite', () => {
  it('sorts ascending', () => {
    const xs = [
      fakeVerdict({ pair: ['a', 'b'], composite: 0.7 }),
      fakeVerdict({ pair: ['c', 'd'], composite: 0.2 }),
      fakeVerdict({ pair: ['e', 'f'], composite: 0.5 })
    ];
    const sorted = rankByComposite(xs);
    expect(sorted.map((v) => v.composite_score)).toEqual([0.2, 0.5, 0.7]);
  });
});

describe('groupByEvidenceTier', () => {
  it('buckets by evidence_level', () => {
    const xs = [
      fakeVerdict({ pair: ['a', 'b'], composite: 0.1, evidence: 'sandbox-validated' }),
      fakeVerdict({ pair: ['c', 'd'], composite: 0.2, evidence: 'profile-verified' }),
      fakeVerdict({ pair: ['e', 'f'], composite: 0.3, evidence: 'docs-only' })
    ];
    const g = groupByEvidenceTier(xs);
    expect(g.sandbox).toHaveLength(1);
    expect(g.profileVerified).toHaveLength(1);
    expect(g.docsOnly).toHaveLength(1);
    expect(g.unverified).toHaveLength(0);
  });
});

describe('severityDistribution', () => {
  it('counts severities per dimension', () => {
    const xs = [
      fakeVerdict({
        pair: ['a', 'b'], composite: 0.5,
        severities: { A_prompt_injection: 'high', B_data_leakage: 'none' }
      }),
      fakeVerdict({
        pair: ['c', 'd'], composite: 0.5,
        severities: { A_prompt_injection: 'high', B_data_leakage: 'low' }
      })
    ];
    const d = severityDistribution(xs);
    expect(d.A_prompt_injection.high).toBe(2);
    expect(d.B_data_leakage.none).toBe(1);
    expect(d.B_data_leakage.low).toBe(1);
  });
});

describe('heatmapMatrix', () => {
  it('emits one cell per (agent, risk) with worst severity over all pair-mates', () => {
    const xs = [
      fakeVerdict({
        pair: ['aider', 'cursor'], composite: 0.3,
        severities: { A_prompt_injection: 'high' }
      }),
      fakeVerdict({
        pair: ['aider', 'cline'], composite: 0.4,
        severities: { A_prompt_injection: 'medium' }
      })
    ];
    const cells = heatmapMatrix(xs, ['aider']);
    expect(cells).toHaveLength(5); // 1 agent * 5 risks
    const a = cells.find((c) => c.risk === 'A_prompt_injection');
    expect(a?.severity).toBe('high');
    expect(a?.pairCount).toBe(2);
  });
});

describe('topAgentsByAppearance', () => {
  it('ranks by frequency then alphabetic', () => {
    const xs = [
      fakeVerdict({ pair: ['aider', 'cursor'], composite: 0.5 }),
      fakeVerdict({ pair: ['aider', 'cline'], composite: 0.5 }),
      fakeVerdict({ pair: ['cursor', 'cline'], composite: 0.5 })
    ];
    const top = topAgentsByAppearance(xs, 3);
    expect(top[0]).toBe('aider');
    expect(top.slice(1).sort()).toEqual(['cline', 'cursor']);
  });
});

describe('frameworkCoverage', () => {
  it('counts verdicts per framework', () => {
    const xs = [
      { ...fakeVerdict({ pair: ['a', 'b'], composite: 0.5 }), framework_mappings: { 'NIST-AI-RMF': ['x'] } },
      { ...fakeVerdict({ pair: ['c', 'd'], composite: 0.5 }), framework_mappings: { 'NIST-AI-RMF': ['y'], 'OWASP-LLM': ['z'] } }
    ];
    const fc = frameworkCoverage(xs);
    expect(fc['NIST-AI-RMF']).toBe(2);
    expect(fc['OWASP-LLM']).toBe(1);
  });
});

describe('integration: catalog feeds aggregations', () => {
  it('produces a non-empty grouping for the live catalog', () => {
    const all = loadVerdicts();
    const g = groupByEvidenceTier(all);
    expect(g.sandbox.length + g.profileVerified.length + g.docsOnly.length + g.unverified.length)
      .toBe(all.length);
    expect(appearanceCounts(all).size).toBeGreaterThan(0);
  });
});

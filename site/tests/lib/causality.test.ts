import { describe, it, expect } from 'vitest';
import {
  RISK_IDS,
  computeCausality,
  loadCausalityDag,
} from '../../src/lib/causality';
import { getRiskCausality } from '../../src/data/catalog';

// The golden values here are the cross-language parity contract with
// tests/unit/test_causality.py — they MUST stay identical.

describe('causality (TS port — parity with Python)', () => {
  it('ships an acyclic DAG with the A->B edge and exactly the 5 risk ids', () => {
    const dag = getRiskCausality();
    expect(new Set(dag.nodes)).toEqual(new Set(RISK_IDS));
    const pairs = dag.edges.map((e) => `${e.from}->${e.to}`);
    expect(pairs).toContain('A_prompt_injection->B_data_leakage');
  });

  it('rejects a cyclic DAG', () => {
    expect(() =>
      loadCausalityDag({
        nodes: [...RISK_IDS],
        edges: [
          { from: 'A_prompt_injection', to: 'B_data_leakage', mechanism: 'm' },
          { from: 'B_data_leakage', to: 'A_prompt_injection', mechanism: 'm' },
        ],
      }),
    ).toThrow();
  });

  it('case one: amplification, leverage, best mitigation', () => {
    const dag = getRiskCausality();
    const severities = {
      A_prompt_injection: 'high',
      B_data_leakage: 'medium',
      C_capability_conflict: 'none',
      D_cascading_error: 'low',
      E_compliance: 'none',
    } as const;
    const report = computeCausality(severities, dag);
    const amp = new Map(report.edges.map((e) => [`${e.from}->${e.to}`, e.amplification]));
    const active = new Map(report.edges.map((e) => [`${e.from}->${e.to}`, e.active]));

    expect(amp.get('A_prompt_injection->B_data_leakage')).toBe(0.4);
    expect(active.get('A_prompt_injection->B_data_leakage')).toBe(true);
    expect(amp.get('A_prompt_injection->D_cascading_error')).toBe(0.16);
    expect(active.get('A_prompt_injection->D_cascading_error')).toBe(true);
    expect(amp.get('B_data_leakage->E_compliance')).toBe(0.0);
    expect(active.get('B_data_leakage->E_compliance')).toBe(false);

    expect(report.leverage).toEqual({
      A_prompt_injection: 1.5,
      B_data_leakage: 0.5,
      C_capability_conflict: 0.0,
      D_cascading_error: 0.2,
      E_compliance: 0.0,
    });
    expect(report.best_mitigation).toBe('A_prompt_injection');
  });

  it('all-none has no best mitigation', () => {
    const dag = getRiskCausality();
    const severities = Object.fromEntries(
      RISK_IDS.map((r) => [r, 'none']),
    ) as Record<(typeof RISK_IDS)[number], string>;
    const report = computeCausality(severities, dag);
    expect(report.best_mitigation).toBeNull();
    expect(Object.values(report.leverage).every((v) => v === 0.0)).toBe(true);
  });

  it('case B=critical, E=high', () => {
    const dag = getRiskCausality();
    const severities = {
      A_prompt_injection: 'none',
      B_data_leakage: 'critical',
      C_capability_conflict: 'none',
      D_cascading_error: 'none',
      E_compliance: 'high',
    } as const;
    const report = computeCausality(severities, dag);
    const amp = new Map(report.edges.map((e) => [`${e.from}->${e.to}`, e.amplification]));
    expect(amp.get('B_data_leakage->E_compliance')).toBe(0.8);
    expect(report.leverage.B_data_leakage).toBe(1.8);
    expect(report.best_mitigation).toBe('B_data_leakage');
  });

  it('payload shape', () => {
    const dag = getRiskCausality();
    const severities = {
      A_prompt_injection: 'high',
      B_data_leakage: 'medium',
      C_capability_conflict: 'none',
      D_cascading_error: 'low',
      E_compliance: 'none',
    } as const;
    const report = computeCausality(severities, dag);
    expect(Object.keys(report).sort()).toEqual(
      ['best_mitigation', 'edges', 'leverage', 'severities'].sort(),
    );
    expect(Object.keys(report.edges[0]!).sort()).toEqual(
      ['active', 'amplification', 'from', 'mechanism', 'to'].sort(),
    );
    expect(report.severities.A_prompt_injection).toBe('high');
  });
});

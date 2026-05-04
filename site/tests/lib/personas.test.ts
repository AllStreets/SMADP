import { describe, it, expect } from 'vitest';
import { PERSONAS, getPersonaSpec, PANEL_KEYS } from '../../src/lib/personas';

describe('personas', () => {
  it('exposes exactly 4 personas in stable order', () => {
    expect(PERSONAS.map((p) => p.id)).toEqual([
      'auditor',
      'procurement',
      'grc',
      'ciso',
    ]);
  });

  it('every persona has name, tagline, and a non-empty panel order', () => {
    for (const p of PERSONAS) {
      expect(p.name.length).toBeGreaterThan(0);
      expect(p.tagline.length).toBeGreaterThan(0);
      expect(p.panels.length).toBeGreaterThan(0);
    }
  });

  it('every panel id used by a persona is a known panel key', () => {
    for (const p of PERSONAS) {
      for (const panel of p.panels) {
        expect(PANEL_KEYS).toContain(panel);
      }
    }
  });

  it('getPersonaSpec returns the matching record', () => {
    expect(getPersonaSpec('auditor').name).toBe('External auditor');
    expect(getPersonaSpec('ciso').name).toMatch(/CISO|Exec/i);
  });

  it('auditor sees framework-coverage and transparency panels first', () => {
    const auditor = getPersonaSpec('auditor');
    expect(auditor.panels[0]).toBe('framework_coverage');
    expect(auditor.panels).toContain('transparency');
  });

  it('ciso sees a one-page exec-summary panel first', () => {
    const ciso = getPersonaSpec('ciso');
    expect(ciso.panels[0]).toBe('exec_summary');
  });
});

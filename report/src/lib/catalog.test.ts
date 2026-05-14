import { describe, it, expect } from 'vitest';
import { loadVerdicts, loadProfiles, loadProfileMap } from './catalog';

describe('catalog loaders', () => {
  it('loads verdicts from catalog/verdicts/', () => {
    const verdicts = loadVerdicts();
    expect(verdicts.length).toBeGreaterThan(0);
    for (const v of verdicts) {
      expect(v.pair).toHaveLength(2);
      expect(v.sub_verdicts).toBeDefined();
      expect(v.sub_verdicts.A_prompt_injection).toBeDefined();
    }
  });

  it('loads profiles from catalog/profiles/', () => {
    const profiles = loadProfiles();
    expect(profiles.length).toBeGreaterThan(0);
    for (const p of profiles) {
      expect(p.slug).toMatch(/^[a-z0-9-]+$/);
    }
  });

  it('exposes profiles by slug', () => {
    const map = loadProfileMap();
    expect(map.get('aider')).toBeDefined();
  });
});

import { describe, it, expect } from 'vitest';
import { evidenceLevelColor } from '../../src/data/catalog';
import type { Verdict, VerdictSignature } from '../../src/data/types';

// Smoke contract for the S3.2 verdict-signature view model. The full disk
// loader is covered by the Python publish-signing tests; here we assert the
// type shape and that the new behavior-observed rung has a color.

describe('verdict signature view model', () => {
  it('attaches an optional signature carrying the BYOK sidecar fields', () => {
    const signature: VerdictSignature = {
      signing_strategy: 'byok',
      canonical_sha256: 'sha256:' + 'a'.repeat(64),
      signature_hex: 'b'.repeat(128),
      public_key_hex: 'c'.repeat(64),
    };
    const verdict = { signature } as Partial<Verdict> as Verdict;
    expect(verdict.signature?.signing_strategy).toBe('byok');
    expect(verdict.signature?.canonical_sha256.startsWith('sha256:')).toBe(true);
  });

  it('colors the behavior-observed rung', () => {
    expect(evidenceLevelColor('behavior-observed')).toBe('#06B6D4');
  });
});

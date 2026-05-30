# SMADP Report Site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a static Astro site at `report/` that presents SMADP's sandbox-validated agent-pair safety research as three reader-selectable layouts (`Brief` ~10pp, `Prospectus` ~14pp, `Dossier` ~16pp), each printable to PDF with a clean Navy-Memo aesthetic.

**Architecture:** Fresh Astro 4 project at the repo root in a new `report/` directory, hand-rolled CSS (no Tailwind), zero client JS except a small Export-button trigger, build-time reads of the existing `catalog/verdicts/*.json` and `catalog/profiles/*.json`. The existing `site/` directory is untouched.

**Tech Stack:** Astro 4.16+, TypeScript, pnpm (matches monorepo convention), Vitest for unit tests on the data layer, Playwright for route smoke. Pure SVG for charts. System font stack for print fidelity.

**Spec:** `docs/superpowers/specs/2026-05-14-smadp-report-site-design.md`

---

## Conventions used in this plan

- **All paths are repo-relative.** Repo root: `/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP`.
- **All commands run from `report/` unless noted.**
- **Commits are real.** This is a tracked git repo. Use the commit messages shown verbatim.
- **TDD where it pays:** unit tests for the data layer + aggregations (pure TypeScript). Astro components are validated by build + Playwright smoke, not snapshot tests — that scope is wasted ceremony for a one-off report.
- **Color tokens** referenced throughout match the spec §7 palette table. Never hardcode hexes outside `src/styles/tokens.css`.

---

## File structure (locked at plan time)

```
report/
├── package.json
├── tsconfig.json
├── astro.config.mjs
├── vitest.config.ts
├── playwright.config.ts
├── .gitignore
├── README.md
├── public/
│   └── favicon.svg
└── src/
    ├── pages/
    │   ├── index.astro             # picker landing
    │   ├── brief.astro             # ~10pp linear narrative
    │   ├── prospectus.astro        # ~14pp pitch + data appendix
    │   └── dossier.astro           # ~16pp dense editorial
    ├── components/
    │   ├── MemoLayout.astro        # shell: nav + body slot + footer + print CSS
    │   ├── Nav.astro
    │   ├── ExportButton.astro
    │   ├── HeroBand.astro
    │   ├── DataCallouts.astro
    │   ├── SectionHeader.astro
    │   ├── PageBreak.astro
    │   ├── FooterStrip.astro
    │   ├── VerdictCard.astro
    │   ├── VerdictTable.astro
    │   ├── SeverityPill.astro
    │   ├── EvidenceBadge.astro
    │   ├── RiskTaxonomyBlock.astro
    │   ├── MethodologyBlock.astro
    │   ├── AgentProfileRow.astro
    │   └── charts/
    │       ├── ChartHeatmap.astro
    │       ├── ChartBars.astro
    │       ├── ChartDonut.astro
    │       ├── ChartStackedBar.astro
    │       └── ChartHistogram.astro
    ├── lib/
    │   ├── catalog.ts              # catalog loaders
    │   ├── catalog.test.ts
    │   ├── aggregations.ts         # derived aggregations
    │   ├── aggregations.test.ts
    │   └── types.ts                # shared TS types
    └── styles/
        ├── tokens.css
        ├── globals.css
        └── print.css
```

---

## Task 1: Scaffold the Astro project

**Files:**
- Create: `report/package.json`
- Create: `report/tsconfig.json`
- Create: `report/astro.config.mjs`
- Create: `report/.gitignore`
- Create: `report/src/pages/index.astro` (placeholder, replaced in Task 9)
- Create: `report/public/favicon.svg`
- Create: `report/README.md`

- [ ] **Step 1.1: Create `report/package.json`**

```json
{
  "name": "smadp-report",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "description": "SMADP — three-layout research memo built from the verdict catalog.",
  "scripts": {
    "dev": "astro dev",
    "start": "astro dev",
    "build": "astro build",
    "preview": "astro preview",
    "astro": "astro",
    "check": "astro check",
    "test": "vitest run",
    "test:watch": "vitest",
    "test:e2e": "playwright test"
  },
  "dependencies": {
    "astro": "^4.16.18",
    "@astrojs/check": "^0.9.4",
    "typescript": "^5.6.3"
  },
  "devDependencies": {
    "@types/node": "^22.9.0",
    "vitest": "^2.1.5",
    "@playwright/test": "^1.49.0"
  }
}
```

- [ ] **Step 1.2: Create `report/tsconfig.json`**

```json
{
  "extends": "astro/tsconfigs/strict",
  "compilerOptions": {
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"]
    },
    "types": ["astro/client"]
  },
  "include": ["src/**/*"],
  "exclude": ["dist", "node_modules"]
}
```

- [ ] **Step 1.3: Create `report/astro.config.mjs`**

```js
import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://smadp.local',
  output: 'static',
  build: {
    inlineStylesheets: 'auto'
  },
  vite: {
    server: { fs: { allow: ['..'] } }
  }
});
```

The `vite.server.fs.allow: ['..']` line lets the data layer read from `../catalog/` at build time.

- [ ] **Step 1.4: Create `report/.gitignore`**

```
node_modules/
dist/
.astro/
.env
.env.local
.DS_Store
```

- [ ] **Step 1.5: Create placeholder `report/src/pages/index.astro`**

```astro
---
---
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>SMADP · Report</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body>
    <h1>SMADP report scaffold — replaced in Task 9.</h1>
  </body>
</html>
```

- [ ] **Step 1.6: Create `report/public/favicon.svg`**

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" fill="#0B1B3A"/>
  <text x="16" y="22" text-anchor="middle" font-family="Helvetica, Arial, sans-serif"
        font-size="14" font-weight="700" fill="#C9A55C">S</text>
</svg>
```

- [ ] **Step 1.7: Create minimal `report/README.md`**

```markdown
# SMADP Report

Three-layout research memo (Brief / Prospectus / Dossier) generated from `catalog/`.

## Build

    pnpm install
    pnpm build           # outputs to dist/
    pnpm preview         # serves dist/ for review
    pnpm dev             # live-reload dev server

## Export PDF

Open any layout in a browser, click `Export`, and save as PDF. Each layout has its
own print stylesheet so the PDF is paginated cleanly.
```

- [ ] **Step 1.8: Install dependencies and verify build**

```bash
cd report
pnpm install
pnpm build
```

Expected: `pnpm build` exits 0, prints `Complete!`, and produces `report/dist/index.html`.

- [ ] **Step 1.9: Commit**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
git add report/package.json report/tsconfig.json report/astro.config.mjs report/.gitignore report/src/pages/index.astro report/public/favicon.svg report/README.md
git commit -m "feat(report): scaffold Astro project at report/"
```

---

## Task 2: Style tokens and globals

**Files:**
- Create: `report/src/styles/tokens.css`
- Create: `report/src/styles/globals.css`
- Create: `report/src/styles/print.css`

- [ ] **Step 2.1: Create `report/src/styles/tokens.css`**

```css
:root {
  --ink-navy: #0B1B3A;
  --ink-body: #1A1A1A;
  --ink-muted: #6B6B6B;
  --paper: #FFFFFF;
  --cream: #F5E9CC;
  --cream-soft: #A8B5CC;
  --gold: #C9A55C;
  --gold-soft: #F0EAD9;
  --rule: #E5E0D6;
  --blue-mid: #3D5A8C;

  --sev-none: #E5E0D6;
  --sev-low: #E5C674;
  --sev-medium: #D08A2C;
  --sev-high: #A8351F;
  --sev-critical: #6B1E11;

  --evi-sandbox: #C9A55C;
  --evi-profile: #3D5A8C;
  --evi-docs: #E5E0D6;

  --font-sans: "Helvetica Neue", "Inter", "Arial", sans-serif;
  --font-mono: "SF Mono", "Menlo", "Consolas", monospace;

  --eyebrow-size: 10px;
  --eyebrow-tracking: 0.18em;

  --body-max: 960px;
  --gutter: 32px;
}
```

- [ ] **Step 2.2: Create `report/src/styles/globals.css`**

```css
@import "./tokens.css";

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: var(--font-sans);
  font-size: 13px;
  line-height: 1.55;
  color: var(--ink-body);
  background: var(--paper);
  font-variant-numeric: tabular-nums;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}
h1, h2, h3, h4 {
  margin: 0;
  font-weight: 600;
  color: var(--ink-navy);
  letter-spacing: -0.01em;
}
h1 { font-size: 28px; line-height: 1.12; }
h2 { font-size: 18px; line-height: 1.25; }
h3 { font-size: 14px; line-height: 1.3; }
p { margin: 0 0 12px 0; }
a { color: var(--ink-navy); text-underline-offset: 2px; }
.eyebrow {
  font-size: var(--eyebrow-size);
  letter-spacing: var(--eyebrow-tracking);
  text-transform: uppercase;
  color: var(--ink-muted);
  font-weight: 500;
}
.eyebrow.on-navy { color: var(--gold); }
.caption {
  font-size: 11px;
  color: var(--ink-muted);
  line-height: 1.5;
}
.rule {
  border: 0;
  border-top: 1px solid var(--rule);
  margin: 0;
}
.container {
  max-width: var(--body-max);
  margin: 0 auto;
  padding: 0 var(--gutter);
}
.section {
  padding: 48px 0;
  border-bottom: 1px solid var(--rule);
}
```

- [ ] **Step 2.3: Create `report/src/styles/print.css`**

```css
@page {
  size: Letter;
  margin: 24mm 20mm;
}
@media print {
  :root { --body-max: none; }
  body { background: #fff; }
  nav, .no-print, .export-button { display: none !important; }
  a { color: inherit; text-decoration: none; }
  .section { break-inside: avoid; border-bottom: none; padding: 24px 0; }
  [data-print-break]::before {
    content: "";
    display: block;
    break-before: page;
  }
  .container { padding: 0; max-width: none; }
  h1, h2, h3 { break-after: avoid; }
}
```

- [ ] **Step 2.4: Build to confirm CSS imports compile (they're not wired yet; this just verifies no syntax error)**

```bash
cd report
pnpm build
```

Expected: exit 0. CSS files exist but are not yet imported by any component — that comes in Task 5.

- [ ] **Step 2.5: Commit**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
git add report/src/styles/
git commit -m "feat(report): add token, global, and print stylesheets"
```

---

## Task 3: Catalog data layer + tests

**Files:**
- Create: `report/src/lib/types.ts`
- Create: `report/src/lib/catalog.ts`
- Create: `report/src/lib/catalog.test.ts`
- Create: `report/vitest.config.ts`

- [ ] **Step 3.1: Create `report/vitest.config.ts`**

```ts
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts']
  }
});
```

- [ ] **Step 3.2: Create `report/src/lib/types.ts`**

```ts
export type Severity = 'none' | 'low' | 'medium' | 'high' | 'critical';
export type EvidenceLevel =
  | 'unverified-profile'
  | 'docs-only'
  | 'profile-verified'
  | 'sandbox-validated';

export type RiskKey =
  | 'A_prompt_injection'
  | 'B_data_leakage'
  | 'C_capability_conflict'
  | 'D_cascading_error'
  | 'E_compliance';

export const RISK_KEYS: RiskKey[] = [
  'A_prompt_injection',
  'B_data_leakage',
  'C_capability_conflict',
  'D_cascading_error',
  'E_compliance'
];

export interface SubVerdict {
  severity: Severity;
  rationale: string;
  citations: { profile_field?: string; evidence_ref?: string; quote?: string }[];
  conditions: string[];
  mitigations: string[];
}

export interface SandboxRun {
  run_id: string;
  scenario: string;
  outcome: 'pass' | 'fail' | 'error';
  started_at: string;
  completed_at: string;
  transcript_ref: string;
}

export interface Verdict {
  verdict_id: string;
  pair: [string, string];
  composite_score: number;
  confidence: number;
  evidence_level: EvidenceLevel;
  headline: string;
  generated_at: string;
  framework_mappings: Record<string, string[]>;
  sub_verdicts: Record<RiskKey, SubVerdict>;
  sandbox_runs: SandboxRun[];
}

export interface ProfileCapabilities {
  execute_shell?: boolean;
  read_filesystem?: boolean;
  write_filesystem?: boolean;
  network_egress?: 'none' | 'allowlist' | 'broad' | 'unknown';
  spawn_subprocesses?: boolean;
  use_mcp?: boolean;
  modify_git_state?: boolean;
  install_packages?: boolean;
  run_browsers?: boolean;
}

export interface Profile {
  slug: string;
  name: string;
  description?: string;
  homepage?: string;
  capabilities?: ProfileCapabilities;
  io_surfaces?: {
    stdin_stdout?: boolean;
    files?: string[];
    calls_apis?: string[];
  };
  trust_floor?: number;
  evidence_level?: EvidenceLevel;
}
```

- [ ] **Step 3.3: Create `report/src/lib/catalog.ts`**

```ts
import { readdirSync, readFileSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Profile, Verdict } from './types';

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, '../../..');
const VERDICT_DIR = join(REPO_ROOT, 'catalog', 'verdicts');
const PROFILE_DIR = join(REPO_ROOT, 'catalog', 'profiles');

export class CatalogError extends Error {}

function readJsonDir<T>(dir: string, label: string): T[] {
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch (err) {
    throw new CatalogError(
      `Cannot read ${label} directory at ${dir}: ${(err as Error).message}`
    );
  }
  const out: T[] = [];
  for (const name of entries) {
    if (!name.endsWith('.json')) continue;
    const path = join(dir, name);
    try {
      const raw = readFileSync(path, 'utf8');
      out.push(JSON.parse(raw) as T);
    } catch (err) {
      throw new CatalogError(
        `Failed to parse ${label} file ${path}: ${(err as Error).message}`
      );
    }
  }
  if (out.length === 0) {
    throw new CatalogError(`${label} directory ${dir} contained no .json files`);
  }
  return out;
}

let _verdicts: Verdict[] | null = null;
let _profiles: Profile[] | null = null;

export function loadVerdicts(): Verdict[] {
  if (_verdicts === null) {
    _verdicts = readJsonDir<Verdict>(VERDICT_DIR, 'verdict');
  }
  return _verdicts;
}

export function loadProfiles(): Profile[] {
  if (_profiles === null) {
    _profiles = readJsonDir<Profile>(PROFILE_DIR, 'profile');
  }
  return _profiles;
}

export function loadProfileMap(): Map<string, Profile> {
  return new Map(loadProfiles().map((p) => [p.slug, p]));
}

export function _resetForTests() {
  _verdicts = null;
  _profiles = null;
}
```

- [ ] **Step 3.4: Create `report/src/lib/catalog.test.ts` — failing test first**

```ts
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
```

- [ ] **Step 3.5: Run the data-layer tests**

```bash
cd report
pnpm test
```

Expected: all 3 tests pass against the live catalog. Currently the repo has 104 verdicts and 101 profiles, so the assertions trivially hold.

If a test fails because `aider.json` isn't where expected, fix the path in `catalog.ts` rather than weakening the test.

- [ ] **Step 3.6: Commit**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
git add report/src/lib/types.ts report/src/lib/catalog.ts report/src/lib/catalog.test.ts report/vitest.config.ts
git commit -m "feat(report): catalog data layer with vitest coverage"
```

---

## Task 4: Aggregations module + tests

**Files:**
- Create: `report/src/lib/aggregations.ts`
- Create: `report/src/lib/aggregations.test.ts`

- [ ] **Step 4.1: Create `report/src/lib/aggregations.ts`**

```ts
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
    const involved = verdicts.filter((v) => v.pair.includes(agent));
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
    for (const slug of v.pair) {
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
```

- [ ] **Step 4.2: Create `report/src/lib/aggregations.test.ts`**

```ts
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
```

- [ ] **Step 4.3: Run all unit tests**

```bash
cd report
pnpm test
```

Expected: 9 tests pass (3 from Task 3 + 7 new + 1 integration).

- [ ] **Step 4.4: Commit**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
git add report/src/lib/aggregations.ts report/src/lib/aggregations.test.ts
git commit -m "feat(report): aggregations module with unit + integration tests"
```

---

## Task 5: Core layout components (shell)

**Files:**
- Create: `report/src/components/MemoLayout.astro`
- Create: `report/src/components/Nav.astro`
- Create: `report/src/components/ExportButton.astro`
- Create: `report/src/components/HeroBand.astro`
- Create: `report/src/components/FooterStrip.astro`
- Create: `report/src/components/PageBreak.astro`

- [ ] **Step 5.1: Create `report/src/components/Nav.astro`**

```astro
---
const { pathname } = Astro.url;
const isActive = (path: string) => pathname === path || pathname === `${path}/`;
const links = [
  { href: '/brief', label: 'Brief' },
  { href: '/prospectus', label: 'Prospectus' },
  { href: '/dossier', label: 'Dossier' }
];
---
<nav class="memo-nav no-print">
  <a class="wordmark" href="/">SMADP</a>
  <ul>
    {links.map((l) => (
      <li>
        <a href={l.href} class:list={[isActive(l.href) && 'active']}>{l.label}</a>
      </li>
    ))}
  </ul>
  <slot name="right" />
</nav>

<style>
  .memo-nav {
    display: flex;
    align-items: center;
    gap: 24px;
    padding: 14px 32px;
    border-bottom: 1px solid var(--rule);
    background: var(--paper);
    position: sticky;
    top: 0;
    z-index: 10;
  }
  .wordmark {
    font-weight: 700;
    letter-spacing: 0.06em;
    color: var(--ink-navy);
    text-decoration: none;
  }
  ul {
    list-style: none;
    display: flex;
    gap: 18px;
    margin: 0;
    padding: 0;
    flex: 1;
  }
  ul a {
    font-size: 12px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ink-muted);
    text-decoration: none;
    padding: 6px 2px;
    border-bottom: 2px solid transparent;
  }
  ul a.active {
    color: var(--ink-navy);
    border-bottom-color: var(--gold);
  }
  ul a:hover { color: var(--ink-navy); }
</style>
```

- [ ] **Step 5.2: Create `report/src/components/ExportButton.astro`**

```astro
---
interface Props { label?: string }
const { label = 'Export PDF' } = Astro.props;
---
<button type="button" class="export-button no-print" data-action="print">
  {label}
</button>

<script>
  document.addEventListener('click', (event) => {
    const target = event.target as HTMLElement | null;
    if (target?.matches('[data-action="print"]')) {
      window.print();
    }
  });
</script>

<style>
  .export-button {
    appearance: none;
    border: 1px solid var(--ink-navy);
    background: var(--ink-navy);
    color: var(--cream);
    padding: 8px 16px;
    font-family: inherit;
    font-size: 11px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    cursor: pointer;
    border-radius: 0;
  }
  .export-button:hover { background: #051430; }
</style>
```

- [ ] **Step 5.3: Create `report/src/components/HeroBand.astro`**

```astro
---
interface Props {
  eyebrow: string;
  title: string;
  dek?: string;
}
const { eyebrow, title, dek } = Astro.props;
---
<header class="hero-band">
  <div class="container">
    <div class="eyebrow on-navy">{eyebrow}</div>
    <h1>{title}</h1>
    {dek && <p class="dek">{dek}</p>}
  </div>
</header>

<style>
  .hero-band {
    background: var(--ink-navy);
    color: var(--cream);
    padding: 56px 0 48px;
  }
  .hero-band h1 {
    color: var(--cream);
    margin: 14px 0 12px;
    font-weight: 600;
    letter-spacing: -0.01em;
  }
  .dek {
    color: var(--cream-soft);
    font-size: 14px;
    line-height: 1.6;
    max-width: 60ch;
    margin: 0;
  }
</style>
```

- [ ] **Step 5.4: Create `report/src/components/FooterStrip.astro`**

```astro
---
interface Props { layoutName: string; pageHint?: string }
const { layoutName, pageHint } = Astro.props;
---
<footer class="footer-strip">
  <div class="container row">
    <span>SMADP · Safe Multi-Agent Deployment Platform</span>
    <span>{layoutName}{pageHint ? ` · ${pageHint}` : ''}</span>
  </div>
</footer>

<style>
  .footer-strip {
    background: var(--ink-navy);
    color: var(--cream-soft);
    padding: 14px 0;
    font-size: 10px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }
  .row { display: flex; justify-content: space-between; }
</style>
```

- [ ] **Step 5.5: Create `report/src/components/PageBreak.astro`**

```astro
---
---
<div data-print-break class="page-break" aria-hidden="true"></div>

<style>
  .page-break {
    height: 0;
    margin: 64px 0;
    border-top: 1px dashed var(--rule);
  }
  @media print { .page-break { margin: 0; border: 0; } }
</style>
```

- [ ] **Step 5.6: Create `report/src/components/MemoLayout.astro`**

```astro
---
import '@/styles/globals.css';
import '@/styles/print.css';
import Nav from './Nav.astro';
import ExportButton from './ExportButton.astro';
import FooterStrip from './FooterStrip.astro';

interface Props {
  pageTitle: string;
  layoutName: 'Brief' | 'Prospectus' | 'Dossier' | 'SMADP';
}
const { pageTitle, layoutName } = Astro.props;
---
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{pageTitle}</title>
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
  </head>
  <body>
    <Nav>
      <span slot="right">
        {layoutName !== 'SMADP' && <ExportButton />}
      </span>
    </Nav>
    <main>
      <slot />
    </main>
    <FooterStrip layoutName={layoutName} />
  </body>
</html>

<style>
  main { padding-bottom: 96px; }
</style>
```

- [ ] **Step 5.7: Wire `index.astro` to use `MemoLayout` so we can validate the shell renders**

Replace `report/src/pages/index.astro` (existing placeholder) with:

```astro
---
import MemoLayout from '@/components/MemoLayout.astro';
import HeroBand from '@/components/HeroBand.astro';
---
<MemoLayout pageTitle="SMADP · Report" layoutName="SMADP">
  <HeroBand
    eyebrow="SMADP Research Memo · 2026.05"
    title="When agents work together, do they stay safe?"
    dek="A sandbox-tested study of how AI coding agents behave when paired — and where each one's safety guarantees start to crack."
  />
  <section class="container section">
    <p>Picker landing replaced in Task 9. Shell layout sanity check only.</p>
  </section>
</MemoLayout>
```

- [ ] **Step 5.8: Verify build**

```bash
cd report
pnpm build
```

Expected: exit 0. `dist/index.html` exists and contains the hero band markup.

- [ ] **Step 5.9: Commit**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
git add report/src/components/MemoLayout.astro report/src/components/Nav.astro report/src/components/ExportButton.astro report/src/components/HeroBand.astro report/src/components/FooterStrip.astro report/src/components/PageBreak.astro report/src/pages/index.astro
git commit -m "feat(report): MemoLayout shell + nav, hero, footer, export"
```

---

## Task 6: Domain UI components

**Files:**
- Create: `report/src/components/SeverityPill.astro`
- Create: `report/src/components/EvidenceBadge.astro`
- Create: `report/src/components/SectionHeader.astro`
- Create: `report/src/components/DataCallouts.astro`
- Create: `report/src/components/RiskTaxonomyBlock.astro`
- Create: `report/src/components/MethodologyBlock.astro`

- [ ] **Step 6.1: Create `report/src/components/SeverityPill.astro`**

```astro
---
import type { Severity } from '@/lib/types';
interface Props { severity: Severity; label?: string }
const { severity, label } = Astro.props;
const colorVar = `var(--sev-${severity})`;
const text = label ?? severity;
const dark = severity === 'high' || severity === 'critical';
---
<span class="pill" style={`background:${colorVar}; color:${dark ? '#fff' : 'var(--ink-body)'}`}>
  {text}
</span>

<style>
  .pill {
    display: inline-block;
    font-size: 10px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    padding: 3px 8px;
    border-radius: 999px;
    font-weight: 600;
  }
</style>
```

- [ ] **Step 6.2: Create `report/src/components/EvidenceBadge.astro`**

```astro
---
import type { EvidenceLevel } from '@/lib/types';
interface Props { level: EvidenceLevel }
const { level } = Astro.props;
const map: Record<EvidenceLevel, { label: string; color: string; dark: boolean }> = {
  'sandbox-validated':  { label: 'Sandbox',       color: 'var(--evi-sandbox)', dark: false },
  'profile-verified':   { label: 'Profile',       color: 'var(--evi-profile)', dark: true  },
  'docs-only':          { label: 'Docs',          color: 'var(--evi-docs)',    dark: false },
  'unverified-profile': { label: 'Unverified',    color: 'var(--rule)',        dark: false }
};
const m = map[level];
---
<span class="badge" style={`background:${m.color}; color:${m.dark ? '#fff' : 'var(--ink-navy)'}`}>{m.label}</span>

<style>
  .badge {
    display: inline-block;
    font-size: 9.5px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    padding: 3px 7px;
    font-weight: 600;
    border: 1px solid var(--ink-navy);
  }
</style>
```

- [ ] **Step 6.3: Create `report/src/components/SectionHeader.astro`**

```astro
---
interface Props { eyebrow: string; title: string; subtitle?: string }
const { eyebrow, title, subtitle } = Astro.props;
---
<header class="section-header">
  <div class="eyebrow">{eyebrow}</div>
  <h2>{title}</h2>
  {subtitle && <p class="subtitle">{subtitle}</p>}
</header>

<style>
  .section-header { margin-bottom: 20px; }
  .section-header h2 { margin: 4px 0 6px; font-size: 18px; }
  .subtitle { color: var(--ink-muted); font-size: 12px; margin: 0; max-width: 70ch; }
</style>
```

- [ ] **Step 6.4: Create `report/src/components/DataCallouts.astro`**

```astro
---
interface Callout { label: string; value: string | number; accent?: boolean }
interface Props { items: Callout[] }
const { items } = Astro.props;
---
<div class="callouts">
  {items.map((c) => (
    <div class="cell">
      <div class="label">{c.label}</div>
      <div class="value" style={c.accent ? 'color: var(--gold)' : undefined}>{c.value}</div>
    </div>
  ))}
</div>

<style>
  .callouts {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    border-top: 2px solid var(--ink-navy);
    border-bottom: 2px solid var(--ink-navy);
  }
  .cell {
    padding: 18px 24px;
    border-right: 1px solid var(--rule);
  }
  .cell:last-child { border-right: 0; }
  .label {
    font-size: 9.5px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--ink-muted);
    margin-bottom: 6px;
  }
  .value {
    font-size: 28px;
    font-weight: 600;
    color: var(--ink-navy);
  }
</style>
```

- [ ] **Step 6.5: Create `report/src/components/RiskTaxonomyBlock.astro`**

```astro
---
import type { RiskKey } from '@/lib/types';

interface Props {
  riskKey: RiskKey;
  title: string;
  definition: string;
  example?: string;
}
const { riskKey, title, definition, example } = Astro.props;
const letter = riskKey.charAt(0);
---
<article class="risk-block">
  <div class="letter">{letter}</div>
  <div class="body">
    <h3>{title}</h3>
    <p>{definition}</p>
    {example && <p class="example">Example: {example}</p>}
  </div>
</article>

<style>
  .risk-block {
    display: grid;
    grid-template-columns: 48px 1fr;
    gap: 18px;
    padding: 18px 0;
    border-top: 1px solid var(--rule);
  }
  .letter {
    font-family: var(--font-mono);
    font-size: 32px;
    line-height: 1;
    color: var(--gold);
    font-weight: 600;
  }
  .body h3 { font-size: 14px; margin-bottom: 4px; }
  .body p { margin: 0 0 6px; }
  .example { color: var(--ink-muted); font-size: 12px; }
</style>
```

- [ ] **Step 6.6: Create `report/src/components/MethodologyBlock.astro`**

```astro
---
interface Props { compact?: boolean }
const { compact = false } = Astro.props;
---
<div class:list={['method', compact && 'compact']}>
  <p>
    SMADP runs each agent inside an isolated container against scripted
    scenarios (e.g., calendar + email, spreadsheet + presentation). A second
    agent shares the workspace — the harness records every read, every write,
    and every external network call.
  </p>
  <p>
    An LLM judge then evaluates both transcripts against a fixed rubric across
    five risk dimensions (prompt injection, data leakage, capability conflict,
    cascading error, compliance). Sub-verdicts are deterministically composed
    into a single composite score on [0,1] — lower is worse.
  </p>
  {!compact && (
    <p>
      Verdicts are ranked along an evidence ladder. A verdict is
      <strong>sandbox-validated</strong> only when at least one isolated run
      passed every assertion; <strong>profile-verified</strong> if the
      pairing's claims were checked against both agents' published profiles
      without a run; and <strong>docs-only</strong> if no sandboxed run is
      possible yet (typically because the agent has no container image).
    </p>
  )}
</div>

<style>
  .method p { max-width: 70ch; }
  .method.compact p:last-child { display: none; }
</style>
```

- [ ] **Step 6.7: Verify build**

```bash
cd report
pnpm build
```

Expected: exit 0.

- [ ] **Step 6.8: Commit**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
git add report/src/components/SeverityPill.astro report/src/components/EvidenceBadge.astro report/src/components/SectionHeader.astro report/src/components/DataCallouts.astro report/src/components/RiskTaxonomyBlock.astro report/src/components/MethodologyBlock.astro
git commit -m "feat(report): domain UI primitives (severity, evidence, callouts, taxonomy)"
```

---

## Task 7: Verdict + agent display components

**Files:**
- Create: `report/src/components/VerdictCard.astro`
- Create: `report/src/components/VerdictTable.astro`
- Create: `report/src/components/AgentProfileRow.astro`

- [ ] **Step 7.1: Create `report/src/components/VerdictCard.astro`**

```astro
---
import type { Verdict } from '@/lib/types';
import { RISK_KEYS } from '@/lib/types';
import SeverityPill from './SeverityPill.astro';
import EvidenceBadge from './EvidenceBadge.astro';

interface Props { verdict: Verdict }
const { verdict } = Astro.props;
const riskLabels: Record<string, string> = {
  A_prompt_injection: 'A · Injection',
  B_data_leakage: 'B · Leakage',
  C_capability_conflict: 'C · Conflict',
  D_cascading_error: 'D · Cascade',
  E_compliance: 'E · Compliance'
};
---
<article class="verdict-card">
  <div class="head">
    <div class="pair">
      <span>{verdict.pair[0]}</span>
      <span class="x">×</span>
      <span>{verdict.pair[1]}</span>
    </div>
    <div class="meta">
      <EvidenceBadge level={verdict.evidence_level} />
      <span class="composite">composite {verdict.composite_score.toFixed(2)}</span>
    </div>
  </div>
  <p class="headline">{verdict.headline}</p>
  <ul class="risks">
    {RISK_KEYS.map((k) => (
      <li>
        <span class="risk-label">{riskLabels[k]}</span>
        <SeverityPill severity={verdict.sub_verdicts[k].severity} />
      </li>
    ))}
  </ul>
</article>

<style>
  .verdict-card {
    border: 1px solid var(--rule);
    padding: 20px 22px;
    background: var(--paper);
  }
  .head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
  .pair { font-weight: 600; color: var(--ink-navy); font-size: 16px; }
  .pair .x { color: var(--ink-muted); margin: 0 6px; }
  .meta { display: flex; gap: 12px; align-items: center; }
  .composite {
    font-size: 11px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--ink-muted);
    font-variant-numeric: tabular-nums;
  }
  .headline {
    margin: 4px 0 14px;
    color: var(--ink-body);
    line-height: 1.5;
  }
  .risks {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 8px;
  }
  .risks li { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  .risk-label {
    font-size: 11px;
    letter-spacing: 0.06em;
    color: var(--ink-muted);
  }
</style>
```

- [ ] **Step 7.2: Create `report/src/components/VerdictTable.astro`**

```astro
---
import type { Verdict } from '@/lib/types';
import { RISK_KEYS } from '@/lib/types';
import SeverityPill from './SeverityPill.astro';
import EvidenceBadge from './EvidenceBadge.astro';

interface Props { verdicts: Verdict[]; dense?: boolean }
const { verdicts, dense = false } = Astro.props;
---
<table class:list={['verdict-table', dense && 'dense']}>
  <thead>
    <tr>
      <th>Pair</th>
      <th>Evidence</th>
      <th class="num">Composite</th>
      <th>A</th><th>B</th><th>C</th><th>D</th><th>E</th>
    </tr>
  </thead>
  <tbody>
    {verdicts.map((v) => (
      <tr>
        <td class="pair">{v.pair[0]} × {v.pair[1]}</td>
        <td><EvidenceBadge level={v.evidence_level} /></td>
        <td class="num">{v.composite_score.toFixed(2)}</td>
        {RISK_KEYS.map((k) => <td><SeverityPill severity={v.sub_verdicts[k].severity} /></td>)}
      </tr>
    ))}
  </tbody>
</table>

<style>
  .verdict-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }
  .verdict-table thead th {
    text-align: left;
    font-size: 9.5px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--ink-muted);
    padding: 8px 10px;
    border-bottom: 2px solid var(--ink-navy);
  }
  .verdict-table tbody td {
    padding: 10px;
    border-bottom: 1px solid var(--rule);
    vertical-align: middle;
  }
  .verdict-table.dense tbody td { padding: 6px 10px; }
  .pair { color: var(--ink-navy); font-weight: 500; }
  .num {
    font-variant-numeric: tabular-nums;
    text-align: right;
    white-space: nowrap;
  }
</style>
```

- [ ] **Step 7.3: Create `report/src/components/AgentProfileRow.astro`**

```astro
---
import type { Profile } from '@/lib/types';
interface Props { profile: Profile; verdictCount: number }
const { profile, verdictCount } = Astro.props;
const caps = profile.capabilities ?? {};
const chip = (label: string, on: boolean | undefined) => ({
  label, on: !!on
});
const chips = [
  chip('shell', caps.execute_shell),
  chip('fs-r',  caps.read_filesystem),
  chip('fs-w',  caps.write_filesystem),
  chip('git',   caps.modify_git_state),
  chip('mcp',   caps.use_mcp),
  chip('net',   caps.network_egress === 'broad' || caps.network_egress === 'allowlist')
];
---
<tr class="agent-row">
  <td class="slug">{profile.slug}</td>
  <td class="name">{profile.name}</td>
  <td class="chips">
    {chips.map((c) => (
      <span class:list={['chip', c.on && 'on']}>{c.label}</span>
    ))}
  </td>
  <td class="num">{verdictCount}</td>
</tr>

<style>
  .slug { font-family: var(--font-mono); color: var(--ink-navy); }
  .name { color: var(--ink-muted); }
  .chips { display: flex; gap: 4px; flex-wrap: wrap; }
  .chip {
    font-size: 9.5px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding: 2px 6px;
    background: var(--rule);
    color: var(--ink-muted);
    border-radius: 999px;
  }
  .chip.on { background: var(--ink-navy); color: var(--cream); }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
</style>
```

- [ ] **Step 7.4: Verify build**

```bash
cd report
pnpm build
```

Expected: exit 0.

- [ ] **Step 7.5: Commit**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
git add report/src/components/VerdictCard.astro report/src/components/VerdictTable.astro report/src/components/AgentProfileRow.astro
git commit -m "feat(report): verdict card, verdict table, agent row components"
```

---

## Task 8: SVG chart components

**Files:**
- Create: `report/src/components/charts/ChartHeatmap.astro`
- Create: `report/src/components/charts/ChartBars.astro`
- Create: `report/src/components/charts/ChartDonut.astro`
- Create: `report/src/components/charts/ChartStackedBar.astro`
- Create: `report/src/components/charts/ChartHistogram.astro`

All charts are hand-coded SVG. They take aggregated data only (no raw verdicts) so they are pure rendering.

- [ ] **Step 8.1: Create `report/src/components/charts/ChartHeatmap.astro`**

```astro
---
import type { HeatmapCell } from '@/lib/aggregations';
import type { RiskKey } from '@/lib/types';
import { RISK_KEYS } from '@/lib/types';

interface Props { cells: HeatmapCell[] }
const { cells } = Astro.props;
const agents = Array.from(new Set(cells.map((c) => c.agent)));
const sevColor: Record<string, string> = {
  none: 'var(--sev-none)', low: 'var(--sev-low)', medium: 'var(--sev-medium)',
  high: 'var(--sev-high)', critical: 'var(--sev-critical)'
};
const cellOf = (agent: string, risk: RiskKey) =>
  cells.find((c) => c.agent === agent && c.risk === risk);
const labelOf: Record<string, string> = {
  A_prompt_injection: 'A', B_data_leakage: 'B', C_capability_conflict: 'C',
  D_cascading_error: 'D', E_compliance: 'E'
};
---
<div class="heatmap">
  <div class="grid" style={`grid-template-columns: 140px repeat(${RISK_KEYS.length}, 1fr);`}>
    <div></div>
    {RISK_KEYS.map((k) => <div class="col-head">{labelOf[k]}</div>)}
    {agents.map((agent) => (
      <>
        <div class="row-head">{agent}</div>
        {RISK_KEYS.map((k) => {
          const c = cellOf(agent, k);
          return <div class="cell" style={`background:${sevColor[c?.severity ?? 'none']}`} title={`${agent} · ${k} · ${c?.severity ?? 'none'} · ${c?.pairCount ?? 0} pairs`}></div>;
        })}
      </>
    ))}
  </div>
  <div class="legend">
    <span><i style="background:var(--sev-none)"></i>none</span>
    <span><i style="background:var(--sev-low)"></i>low</span>
    <span><i style="background:var(--sev-medium)"></i>medium</span>
    <span><i style="background:var(--sev-high)"></i>high</span>
    <span><i style="background:var(--sev-critical)"></i>critical</span>
  </div>
</div>

<style>
  .heatmap { font-size: 11px; }
  .grid { display: grid; gap: 3px; align-items: center; }
  .col-head, .row-head { color: var(--ink-muted); }
  .col-head { text-align: center; font-size: 10px; letter-spacing: 0.08em; }
  .row-head { font-family: var(--font-mono); }
  .cell { height: 22px; }
  .legend {
    display: flex;
    gap: 14px;
    margin-top: 14px;
    font-size: 10px;
    color: var(--ink-muted);
  }
  .legend span { display: flex; align-items: center; gap: 5px; }
  .legend i { width: 10px; height: 10px; display: inline-block; }
</style>
```

- [ ] **Step 8.2: Create `report/src/components/charts/ChartBars.astro`**

```astro
---
interface Bar { label: string; value: number; max?: number; tone?: 'sev' | 'gold' | 'navy' }
interface Props { bars: Bar[]; max?: number }
const { bars, max } = Astro.props;
const maxValue = max ?? Math.max(...bars.map((b) => b.max ?? b.value), 1);
function color(value: number): string {
  if (value <= 0.25) return 'var(--sev-high)';
  if (value <= 0.40) return 'var(--sev-medium)';
  if (value <= 0.60) return 'var(--sev-low)';
  return 'var(--blue-mid)';
}
---
<div class="bars">
  {bars.map((b) => (
    <div class="row">
      <div class="label">{b.label}</div>
      <div class="track">
        <div class="fill" style={`width:${(b.value / maxValue) * 100}%; background:${b.tone === 'gold' ? 'var(--gold)' : color(b.value)}`}></div>
      </div>
      <div class="value">{b.value.toFixed(2)}</div>
    </div>
  ))}
</div>

<style>
  .bars { font-size: 11px; }
  .row {
    display: grid;
    grid-template-columns: 160px 1fr 40px;
    gap: 10px;
    align-items: center;
    margin-bottom: 8px;
  }
  .label { text-align: right; color: var(--ink-body); font-family: var(--font-mono); font-size: 11px; }
  .track { height: 14px; background: var(--gold-soft); }
  .fill { height: 100%; }
  .value { color: var(--ink-navy); font-weight: 600; font-variant-numeric: tabular-nums; text-align: right; }
</style>
```

- [ ] **Step 8.3: Create `report/src/components/charts/ChartDonut.astro`**

```astro
---
interface Slice { label: string; value: number; color: string }
interface Props { slices: Slice[]; size?: number }
const { slices, size = 120 } = Astro.props;
const total = slices.reduce((s, x) => s + x.value, 0) || 1;
let cursor = 0;
const arcs = slices.map((s) => {
  const len = (s.value / total) * 100;
  const arc = { ...s, dasharray: `${len} ${100 - len}`, dashoffset: -cursor };
  cursor += len;
  return arc;
});
---
<div class="donut">
  <svg viewBox="0 0 42 42" width={size} height={size}>
    <circle cx="21" cy="21" r="15.915" fill="transparent" stroke="var(--rule)" stroke-width="6" />
    {arcs.map((a) => (
      <circle
        cx="21" cy="21" r="15.915" fill="transparent"
        stroke={a.color} stroke-width="6"
        stroke-dasharray={a.dasharray}
        stroke-dashoffset={a.dashoffset}
        transform="rotate(-90 21 21)"
      />
    ))}
  </svg>
  <ul class="legend">
    {slices.map((s) => (
      <li>
        <i style={`background:${s.color}`}></i>
        <span class="label">{s.label}</span>
        <span class="value">{Math.round((s.value / total) * 100)}%</span>
      </li>
    ))}
  </ul>
</div>

<style>
  .donut { display: flex; gap: 24px; align-items: center; }
  .legend { list-style: none; margin: 0; padding: 0; font-size: 11px; }
  .legend li { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
  .legend i { width: 10px; height: 10px; display: inline-block; }
  .legend .value { color: var(--ink-muted); margin-left: auto; min-width: 30px; text-align: right; font-variant-numeric: tabular-nums; }
</style>
```

- [ ] **Step 8.4: Create `report/src/components/charts/ChartStackedBar.astro`**

```astro
---
interface Segment { label: string; value: number; color: string; dark?: boolean }
interface Props { segments: Segment[]; height?: number }
const { segments, height = 36 } = Astro.props;
const total = segments.reduce((s, x) => s + x.value, 0) || 1;
---
<div class="stacked">
  <div class="bar" style={`height:${height}px;`}>
    {segments.map((s) => (
      <div class="seg"
           style={`width:${(s.value / total) * 100}%; background:${s.color}; color:${s.dark ? '#fff' : 'var(--ink-navy)'}`}>
        <span>{s.value}</span>
      </div>
    ))}
  </div>
  <ul class="legend">
    {segments.map((s) => (
      <li>
        <i style={`background:${s.color}`}></i>
        <span class="label">{s.label}</span>
        <span class="value">{s.value} · {Math.round((s.value / total) * 100)}%</span>
      </li>
    ))}
  </ul>
</div>

<style>
  .stacked .bar {
    display: flex;
    width: 100%;
    border: 1px solid var(--ink-navy);
    margin-bottom: 12px;
  }
  .stacked .seg {
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    font-weight: 600;
  }
  .legend { list-style: none; margin: 0; padding: 0; font-size: 11px; }
  .legend li { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
  .legend i { width: 10px; height: 10px; display: inline-block; }
  .legend .value { color: var(--ink-muted); margin-left: auto; font-variant-numeric: tabular-nums; }
</style>
```

- [ ] **Step 8.5: Create `report/src/components/charts/ChartHistogram.astro`**

```astro
---
interface Props {
  values: number[];
  bins?: number;
  width?: number;
  height?: number;
}
const { values, bins = 10, width = 360, height = 120 } = Astro.props;
const counts = new Array<number>(bins).fill(0);
for (const v of values) {
  const clamped = Math.max(0, Math.min(1, v));
  const idx = Math.min(bins - 1, Math.floor(clamped * bins));
  counts[idx] += 1;
}
const max = Math.max(...counts, 1);
const barW = width / bins;
---
<svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img">
  <line x1="0" y1={height - 16} x2={width} y2={height - 16} stroke="var(--ink-muted)" stroke-width="0.5"/>
  {counts.map((c, i) => {
    const h = (c / max) * (height - 24);
    return (
      <rect
        x={i * barW + 1}
        y={height - 16 - h}
        width={barW - 2}
        height={h}
        fill="var(--ink-navy)"
      />
    );
  })}
  <text x="0" y={height - 4} font-size="9" fill="var(--ink-muted)">0.0</text>
  <text x={width - 22} y={height - 4} font-size="9" fill="var(--ink-muted)">1.0</text>
</svg>
```

- [ ] **Step 8.6: Verify build**

```bash
cd report
pnpm build
```

Expected: exit 0.

- [ ] **Step 8.7: Commit**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
git add report/src/components/charts/
git commit -m "feat(report): SVG chart primitives (heatmap, bars, donut, stacked, histogram)"
```

---

## Task 9: Picker landing page

**Files:**
- Modify: `report/src/pages/index.astro`

- [ ] **Step 9.1: Replace `report/src/pages/index.astro`**

```astro
---
import MemoLayout from '@/components/MemoLayout.astro';
import HeroBand from '@/components/HeroBand.astro';
import DataCallouts from '@/components/DataCallouts.astro';
import { loadVerdicts } from '@/lib/catalog';
import { groupByEvidenceTier } from '@/lib/aggregations';

const verdicts = loadVerdicts();
const groups = groupByEvidenceTier(verdicts);

const callouts = [
  { label: 'Agents profiled', value: 101 },
  { label: 'Pair verdicts', value: verdicts.length },
  { label: 'Sandbox-validated', value: groups.sandbox.length, accent: true },
  { label: 'Risk dimensions', value: 5 }
];

const layouts = [
  {
    name: 'Brief',
    href: '/brief',
    pages: 10,
    blurb: 'The shortest read. A linear narrative — thesis, methodology, headline findings, limits. Start here.'
  },
  {
    name: 'Prospectus',
    href: '/prospectus',
    pages: 14,
    blurb: 'Investment-bank format. A six-page pitch up front; the data appendix in back. For institutional readers who want both.'
  },
  {
    name: 'Dossier',
    href: '/dossier',
    pages: 16,
    blurb: 'The complete file. Dense editorial — every risk dimension, every agent of note, every verdict on the books.'
  }
];
---
<MemoLayout pageTitle="SMADP · Report" layoutName="SMADP">
  <HeroBand
    eyebrow="SMADP Research Memo · 2026.05"
    title="When agents work together, do they stay safe?"
    dek="A sandbox-tested study of how AI coding agents behave when paired — and where each one's safety guarantees start to crack."
  />
  <section class="container section">
    <DataCallouts items={callouts} />
  </section>
  <section class="container section">
    <h2>Choose your read</h2>
    <p class="subtitle">Three takes on the same underlying data. Each exports as a self-contained PDF.</p>
    <div class="picker">
      {layouts.map((l) => (
        <a class="card" href={l.href}>
          <div class="card-head">
            <div class="card-name">{l.name}</div>
            <div class="card-pages">~{l.pages} pages</div>
          </div>
          <p class="card-blurb">{l.blurb}</p>
          <div class="card-cta">Open →</div>
        </a>
      ))}
    </div>
  </section>
</MemoLayout>

<style>
  .subtitle { color: var(--ink-muted); margin-bottom: 32px; max-width: 60ch; }
  .picker {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 18px;
  }
  .card {
    border: 1px solid var(--rule);
    padding: 28px 24px;
    text-decoration: none;
    color: inherit;
    background: var(--paper);
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .card:hover {
    border-color: var(--ink-navy);
    background: #FAFAF7;
  }
  .card-head { display: flex; justify-content: space-between; align-items: baseline; }
  .card-name {
    font-family: var(--font-sans);
    font-weight: 600;
    color: var(--ink-navy);
    font-size: 22px;
    letter-spacing: -0.01em;
  }
  .card-pages {
    font-size: 10px;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--ink-muted);
  }
  .card-blurb { color: var(--ink-body); flex: 1; }
  .card-cta {
    font-size: 11px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--gold);
    font-weight: 600;
  }
</style>
```

- [ ] **Step 9.2: Verify build and preview**

```bash
cd report
pnpm build
pnpm preview &
sleep 2
curl -s http://localhost:4321/ > /tmp/index.html
grep -E "Brief|Prospectus|Dossier" /tmp/index.html
kill %1
```

Expected: build succeeds, the three layout names appear in the rendered HTML.

- [ ] **Step 9.3: Commit**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
git add report/src/pages/index.astro
git commit -m "feat(report): picker landing with live catalog counts"
```

---

## Task 10: Brief layout (~10 pages)

**Files:**
- Create: `report/src/pages/brief.astro`

The Brief is one Astro page that prints to ~10 pages. Each major section gets a `<PageBreak />` before it so print pagination is predictable. The structure follows spec §3.1.

- [ ] **Step 10.1: Create `report/src/pages/brief.astro`**

```astro
---
import MemoLayout from '@/components/MemoLayout.astro';
import HeroBand from '@/components/HeroBand.astro';
import DataCallouts from '@/components/DataCallouts.astro';
import SectionHeader from '@/components/SectionHeader.astro';
import PageBreak from '@/components/PageBreak.astro';
import MethodologyBlock from '@/components/MethodologyBlock.astro';
import RiskTaxonomyBlock from '@/components/RiskTaxonomyBlock.astro';
import VerdictCard from '@/components/VerdictCard.astro';
import ChartHeatmap from '@/components/charts/ChartHeatmap.astro';
import ChartBars from '@/components/charts/ChartBars.astro';
import ChartDonut from '@/components/charts/ChartDonut.astro';
import ChartStackedBar from '@/components/charts/ChartStackedBar.astro';
import { loadVerdicts } from '@/lib/catalog';
import {
  rankByComposite, groupByEvidenceTier, heatmapMatrix,
  topAgentsByAppearance, severityDistribution
} from '@/lib/aggregations';
import { RISK_KEYS } from '@/lib/types';

const verdicts = loadVerdicts();
const groups = groupByEvidenceTier(verdicts);
const top8 = topAgentsByAppearance(verdicts, 8);
const heat = heatmapMatrix(verdicts, top8);
const ranked = rankByComposite(verdicts).slice(0, 6);
const dist = severityDistribution(verdicts);

const dimensionPct = (() => {
  const totals: Record<string, number> = {};
  let grand = 0;
  for (const k of RISK_KEYS) {
    const nonNone = (dist[k].low + dist[k].medium + dist[k].high + dist[k].critical);
    totals[k] = nonNone;
    grand += nonNone;
  }
  return RISK_KEYS.map((k) => ({
    label: ({
      A_prompt_injection: 'A · Prompt injection',
      B_data_leakage: 'B · Data leakage',
      C_capability_conflict: 'C · Capability conflict',
      D_cascading_error: 'D · Cascading error',
      E_compliance: 'E · Compliance'
    } as Record<string, string>)[k],
    value: totals[k],
    color: ({
      A_prompt_injection: 'var(--sev-high)',
      B_data_leakage: 'var(--blue-mid)',
      C_capability_conflict: 'var(--sev-medium)',
      D_cascading_error: 'var(--sev-low)',
      E_compliance: 'var(--gold)'
    } as Record<string, string>)[k]
  }));
})();

const callouts = [
  { label: 'Agents profiled', value: 101 },
  { label: 'Pair verdicts', value: verdicts.length },
  { label: 'Sandbox-validated', value: groups.sandbox.length, accent: true },
  { label: 'Risk dimensions', value: 5 }
];

const sandboxHeadline = groups.sandbox[0];
---
<MemoLayout pageTitle="SMADP · Brief" layoutName="Brief">
  <HeroBand
    eyebrow="SMADP Research Brief · 2026.05"
    title="When agents work together, do they stay safe?"
    dek="A sandbox-tested study of how AI coding agents behave when paired — and where each one's safety guarantees start to crack."
  />
  <section class="container section">
    <DataCallouts items={callouts} />
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="§ 1" title="The question" />
    <p>Modern AI coding agents publish safety properties one at a time: this one redacts secrets in its prompts, that one runs sandboxed, the other refuses to commit without confirmation. But deployments rarely use one agent in isolation. The safety story changes when two agents share a workspace, when one's output is another's input, when an agent reads files a sibling just wrote.</p>
    <p>SMADP studies these <em>compositions</em>. We catalogue agents, define the surfaces over which they interact, and run scripted scenarios where two agents collaborate inside an isolated container. Then we ask, against a fixed rubric: did each one's safety guarantees survive the pairing?</p>
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="§ 2" title="Methodology" subtitle="Sandbox, judge, evidence ladder." />
    <MethodologyBlock />
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="§ 3" title="Risk taxonomy" subtitle="Five dimensions, each a distinct failure mode." />
    <RiskTaxonomyBlock riskKey="A_prompt_injection"     title="Prompt injection"     definition="One agent's writes become another agent's prompt, slipping instructions past the second agent's safety filters."    example="Agent A drops a markdown file containing a hidden instruction; Agent B reads it as task context." />
    <RiskTaxonomyBlock riskKey="B_data_leakage"         title="Data leakage"         definition="Confidential context held by one agent is exfiltrated or surfaced to a less-trusted destination by another."  example="Spreadsheet agent has access to PII; presentation agent renders it in a public slide deck." />
    <RiskTaxonomyBlock riskKey="C_capability_conflict"  title="Capability conflict"  definition="The agents' permissions overlap in a way each one alone would refuse, creating a privilege the operator never granted." example="Agent A can write files; Agent B can execute them — together they form an unsandboxed code-execution channel." />
    <RiskTaxonomyBlock riskKey="D_cascading_error"      title="Cascading error"      definition="A wrong action by one agent is consumed as ground truth by another, magnifying the impact downstream." example="Refactor agent renames a function incorrectly; deploy agent reads the new name and ships the broken release." />
    <RiskTaxonomyBlock riskKey="E_compliance"           title="Compliance"           definition="The pair, as deployed, violates a policy or regulation that neither agent alone would breach." example="Two locally-private agents handing off through a regulated cloud system put data outside its compliance boundary." />
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="§ 4" title="Headline finding" subtitle="The single currently sandbox-validated pair." />
    {sandboxHeadline
      ? <VerdictCard verdict={sandboxHeadline} />
      : <p class="caption">No sandbox-validated verdict on disk yet. The methodology and rubric are ready; the smoke pipeline runs nightly.</p>}
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="Exhibit 1" title="Severity heatmap" subtitle={`Worst-case sub-verdict severity per risk dimension across the ${top8.length} most-paired agents.`} />
    <ChartHeatmap cells={heat} />
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="Exhibit 2" title="Highest-risk pairs" subtitle="Composite score ascending (lower = more cross-agent risk surfaced)." />
    <ChartBars bars={ranked.map((v) => ({ label: `${v.pair[0]} · ${v.pair[1]}`, value: v.composite_score }))} max={1} />
  </section>

  <PageBreak />
  <section class="container section grid-2">
    <div>
      <SectionHeader eyebrow="Exhibit 3" title="Evidence ladder" subtitle="How many verdicts sit at each rung today." />
      <ChartStackedBar segments={[
        { label: 'Sandbox-validated', value: groups.sandbox.length,        color: 'var(--evi-sandbox)', dark: false },
        { label: 'Profile-verified',  value: groups.profileVerified.length, color: 'var(--evi-profile)', dark: true  },
        { label: 'Docs-only',         value: groups.docsOnly.length,        color: 'var(--evi-docs)',    dark: false }
      ]} />
    </div>
    <div>
      <SectionHeader eyebrow="Exhibit 4" title="Risk by dimension" subtitle="Where non-zero severity clusters across the five risks." />
      <ChartDonut slices={dimensionPct} />
    </div>
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="§ 5" title="Limits of this study" />
    <p>v1's sandbox tier covers only open-source agents that can be containerised. The 95+ docs-only verdicts in the catalog reflect what we can infer from published profiles — not what we have observed under instrumentation. We label these explicitly throughout and discourage citing them as run-tested.</p>
    <p>Single-scenario coverage today is intentionally narrow. The harness supports adding scenarios without changing the rubric; the bottleneck is curation, not engineering.</p>
  </section>

  <section class="container section">
    <SectionHeader eyebrow="§ 6" title="What's next" />
    <ul class="next">
      <li>Containerise three more open-source coding agents (autogen, continue-dev, open-interpreter) and run the existing three scenarios against every pairing.</li>
      <li>Add two scenarios that exercise capability-conflict directly (shared filesystem + concurrent git mutation; shared MCP server with overlapping tool surfaces).</li>
      <li>Publish the second memo with twelve sandbox-validated pairs.</li>
    </ul>
  </section>
</MemoLayout>

<style>
  p, ul.next { max-width: 70ch; }
  ul.next { padding-left: 18px; }
  ul.next li { margin-bottom: 6px; }
  .grid-2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 32px;
  }
  @media print { .grid-2 { grid-template-columns: 1fr; } }
</style>
```

- [ ] **Step 10.2: Verify build and route**

```bash
cd report
pnpm build
ls dist/brief/index.html
```

Expected: `dist/brief/index.html` exists.

- [ ] **Step 10.3: Commit**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
git add report/src/pages/brief.astro
git commit -m "feat(report): Brief layout — ~10pp linear research brief"
```

---

## Task 11: Prospectus layout (~14 pages)

**Files:**
- Create: `report/src/pages/prospectus.astro`

The Prospectus is a single Astro page rendered in two sections: a 6-page pitch and an 8-page data appendix, separated by a section divider that doubles as a print page break.

- [ ] **Step 11.1: Create `report/src/pages/prospectus.astro`**

```astro
---
import MemoLayout from '@/components/MemoLayout.astro';
import HeroBand from '@/components/HeroBand.astro';
import DataCallouts from '@/components/DataCallouts.astro';
import SectionHeader from '@/components/SectionHeader.astro';
import PageBreak from '@/components/PageBreak.astro';
import MethodologyBlock from '@/components/MethodologyBlock.astro';
import RiskTaxonomyBlock from '@/components/RiskTaxonomyBlock.astro';
import VerdictCard from '@/components/VerdictCard.astro';
import VerdictTable from '@/components/VerdictTable.astro';
import AgentProfileRow from '@/components/AgentProfileRow.astro';
import ChartHeatmap from '@/components/charts/ChartHeatmap.astro';
import ChartBars from '@/components/charts/ChartBars.astro';
import ChartHistogram from '@/components/charts/ChartHistogram.astro';
import ChartStackedBar from '@/components/charts/ChartStackedBar.astro';
import { loadVerdicts, loadProfiles, loadProfileMap } from '@/lib/catalog';
import {
  rankByComposite, groupByEvidenceTier, heatmapMatrix,
  topAgentsByAppearance, appearanceCounts, frameworkCoverage
} from '@/lib/aggregations';

const verdicts = loadVerdicts();
const profiles = loadProfiles();
const profileMap = loadProfileMap();
const groups = groupByEvidenceTier(verdicts);
const top12 = topAgentsByAppearance(verdicts, 12);
const heat = heatmapMatrix(verdicts, top12);
const ranked = rankByComposite(verdicts);
const ranked10 = ranked.slice(0, 10);
const appearance = appearanceCounts(verdicts);
const fwCoverage = frameworkCoverage(verdicts);
const callouts = [
  { label: 'Agents profiled', value: profiles.length },
  { label: 'Pair verdicts', value: verdicts.length },
  { label: 'Sandbox-validated', value: groups.sandbox.length, accent: true },
  { label: 'Risk dimensions', value: 5 }
];

const sandboxHeadline = groups.sandbox[0];
const sortedProfiles = [...profiles].sort((a, b) =>
  (appearance.get(b.slug) ?? 0) - (appearance.get(a.slug) ?? 0) ||
  a.slug.localeCompare(b.slug)
);
const profileVerifiedTop = ranked.filter((v) => v.evidence_level === 'profile-verified').slice(0, 8);
---
<MemoLayout pageTitle="SMADP · Prospectus" layoutName="Prospectus">
  <HeroBand
    eyebrow="SMADP Prospectus · 2026.05"
    title="When agents work together, do they stay safe?"
    dek="A sandbox-tested institutional brief on AI coding agents: how they compose, where they break, and what the catalog says today."
  />
  <section class="container section">
    <DataCallouts items={callouts} />
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="Executive summary" title="What the catalog says today" />
    <p>Agentic coding tools are converging on a similar capability surface — shell access, filesystem reads/writes, MCP-mediated tool use, broad network egress. Individually, each agent ships a safety story that holds. SMADP's working hypothesis: those stories <em>do not compose</em>.</p>
    <p>This prospectus reports on the first round of paired-agent sandbox runs. {groups.sandbox.length} verdict{groups.sandbox.length === 1 ? '' : 's'} cleared every assertion in a real container; {groups.profileVerified.length} are profile-verified pending sandboxable images; the remaining {groups.docsOnly.length} are explicitly tagged docs-only.</p>
    <p>The headline finding is technical, not promotional: the sandbox harness is reproducible, the rubric is fixed, and the bottleneck to scaling is operational (container images, not methodology).</p>
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="§ Why this matters" title="The case for institutional readers" />
    <p>Regulators are converging on agentic-AI accountability frameworks (NIST AI RMF, EU AI Act risk categories, NYC Local Law 144 analogues for hiring). All of them assume that you can describe what a deployed AI system does. With multi-agent stacks, no published assessment for any single agent answers that question — because the deployed surface is the pair, not the parts.</p>
    <p>SMADP catalogues the pairs. Every verdict carries a transparent rubric reference, a reproducibility hash, and an explicit evidence tier. The site is a static export; the source data lives in <code>catalog/</code>.</p>
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="§ Methodology" title="Sandbox, judge, evidence ladder" />
    <MethodologyBlock />
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="§ Headline finding" title="The first sandbox-validated pair" />
    {sandboxHeadline
      ? <VerdictCard verdict={sandboxHeadline} />
      : <p class="caption">No sandbox-validated verdict on disk yet.</p>}
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="§ What's next" title="The ask" />
    <p>SMADP is free and open-source. Two ways to engage:</p>
    <ul class="next">
      <li><strong>Operators:</strong> if you deploy agent pairs, contribute the pair's adapter to the catalog so the next memo includes you.</li>
      <li><strong>Researchers:</strong> the harness accepts new scenarios as a single YAML file. The next memo will publish twelve sandbox-validated pairs across at least five scenarios.</li>
    </ul>
  </section>

  <PageBreak />
  <hr class="rule" />
  <section class="container section appendix-header">
    <div class="eyebrow">Data appendix</div>
    <h2>Receipts</h2>
    <p class="subtitle">Source: <code>catalog/verdicts/*.json</code>, <code>catalog/profiles/*.json</code>. All numbers below are read at build time; nothing is hand-curated.</p>
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="Appendix A" title="Risk taxonomy reference" />
    <RiskTaxonomyBlock riskKey="A_prompt_injection"     title="Prompt injection"     definition="One agent's writes become another agent's prompt, slipping instructions past the second agent's safety filters." />
    <RiskTaxonomyBlock riskKey="B_data_leakage"         title="Data leakage"         definition="Confidential context held by one agent is exfiltrated or surfaced to a less-trusted destination by another." />
    <RiskTaxonomyBlock riskKey="C_capability_conflict"  title="Capability conflict"  definition="The agents' permissions overlap in a way each one alone would refuse." />
    <RiskTaxonomyBlock riskKey="D_cascading_error"      title="Cascading error"      definition="A wrong action by one agent is consumed as ground truth by another, magnifying impact downstream." />
    <RiskTaxonomyBlock riskKey="E_compliance"           title="Compliance"           definition="The pair, as deployed, violates a policy or regulation that neither agent alone would breach." />
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="Appendix B" title="Agent index" subtitle={`${profiles.length} profiles, ordered by pair-appearance frequency.`} />
    <table class="agent-index">
      <thead>
        <tr>
          <th>Slug</th><th>Name</th><th>Capabilities</th><th class="num">Verdicts</th>
        </tr>
      </thead>
      <tbody>
        {sortedProfiles.slice(0, 40).map((p) => (
          <AgentProfileRow profile={p} verdictCount={appearance.get(p.slug) ?? 0} />
        ))}
      </tbody>
    </table>
    <p class="caption">First 40 of {profiles.length}. Full register in Dossier §16.</p>
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="Appendix C" title="Sandbox-validated verdicts (detail)" />
    {groups.sandbox.length === 0
      ? <p class="caption">No sandbox-validated verdicts yet.</p>
      : groups.sandbox.map((v) => (
          <div class="sandbox-detail">
            <VerdictCard verdict={v} />
            <table class="runs">
              <thead><tr><th>Scenario</th><th>Outcome</th><th>Started</th><th>Completed</th></tr></thead>
              <tbody>
                {v.sandbox_runs.map((r) => (
                  <tr>
                    <td>{r.scenario}</td>
                    <td>{r.outcome}</td>
                    <td>{r.started_at}</td>
                    <td>{r.completed_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="Appendix D" title="Profile-verified verdicts (top 8)" />
    <VerdictTable verdicts={profileVerifiedTop} />
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="Appendix E" title="Severity heatmap (full)" subtitle={`Top ${top12.length} most-paired agents across all five dimensions.`} />
    <ChartHeatmap cells={heat} />
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="Appendix F" title="Composite-score distribution" subtitle="Histogram across all verdicts. Lower scores indicate more cross-agent risk surfaced by the analyzer." />
    <ChartHistogram values={verdicts.map((v) => v.composite_score)} />
    <p class="caption">Bins: 10 buckets between 0.0 and 1.0.</p>
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="Appendix G" title="Evidence ladder + framework crosswalks" />
    <ChartStackedBar segments={[
      { label: 'Sandbox-validated', value: groups.sandbox.length,        color: 'var(--evi-sandbox)' },
      { label: 'Profile-verified',  value: groups.profileVerified.length, color: 'var(--evi-profile)', dark: true },
      { label: 'Docs-only',         value: groups.docsOnly.length,        color: 'var(--evi-docs)' }
    ]} />
    <h3 style="margin-top:24px">External framework coverage</h3>
    <table class="frameworks">
      <thead><tr><th>Framework</th><th class="num">Verdicts mapped</th></tr></thead>
      <tbody>
        {Object.keys(fwCoverage).length === 0
          ? <tr><td colspan="2" class="caption">No framework mappings populated yet — every verdict currently emits <code>framework_mappings: &#123;&#125;</code>. Crosswalks land in v2.</td></tr>
          : Object.entries(fwCoverage).map(([fw, n]) => (
              <tr><td>{fw}</td><td class="num">{n}</td></tr>
            ))}
      </tbody>
    </table>
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="Appendix H" title="References &amp; reproducibility" />
    <ul class="refs">
      <li>Rubric: <code>/_meta/rubric/1.0.json</code> in this repository.</li>
      <li>Verdict source: <code>catalog/verdicts/*.json</code>.</li>
      <li>Profile source: <code>catalog/profiles/*.json</code>.</li>
      <li>Sibling project: <a href="https://github.com/AllStreets/ONEXUS-Agents">ONEXUS-Agents</a>.</li>
    </ul>
  </section>
</MemoLayout>

<style>
  .appendix-header h2 { font-size: 28px; }
  .appendix-header .subtitle { color: var(--ink-muted); }
  .agent-index, .runs, .frameworks {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }
  .agent-index thead th, .runs thead th, .frameworks thead th {
    text-align: left;
    font-size: 9.5px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--ink-muted);
    padding: 8px 10px;
    border-bottom: 2px solid var(--ink-navy);
  }
  .agent-index tbody td, .runs tbody td, .frameworks tbody td {
    padding: 8px 10px;
    border-bottom: 1px solid var(--rule);
    vertical-align: middle;
  }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .sandbox-detail { margin-bottom: 24px; }
  .runs { margin-top: 8px; }
  ul.next, ul.refs { padding-left: 18px; }
  ul.next li, ul.refs li { margin-bottom: 6px; max-width: 70ch; }
  hr.rule { border: 0; border-top: 2px solid var(--ink-navy); margin: 0; }
</style>
```

- [ ] **Step 11.2: Verify build and route**

```bash
cd report
pnpm build
ls dist/prospectus/index.html
```

- [ ] **Step 11.3: Commit**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
git add report/src/pages/prospectus.astro
git commit -m "feat(report): Prospectus layout — ~6pp pitch + ~8pp data appendix"
```

---

## Task 12: Dossier layout (~16 pages)

**Files:**
- Create: `report/src/pages/dossier.astro`

The Dossier is the densest layout — every risk dimension gets its own page, every major agent group gets a dossier block, and the register at the end lists all verdicts.

- [ ] **Step 12.1: Create `report/src/pages/dossier.astro`**

```astro
---
import MemoLayout from '@/components/MemoLayout.astro';
import HeroBand from '@/components/HeroBand.astro';
import DataCallouts from '@/components/DataCallouts.astro';
import SectionHeader from '@/components/SectionHeader.astro';
import PageBreak from '@/components/PageBreak.astro';
import MethodologyBlock from '@/components/MethodologyBlock.astro';
import RiskTaxonomyBlock from '@/components/RiskTaxonomyBlock.astro';
import VerdictCard from '@/components/VerdictCard.astro';
import VerdictTable from '@/components/VerdictTable.astro';
import AgentProfileRow from '@/components/AgentProfileRow.astro';
import ChartHeatmap from '@/components/charts/ChartHeatmap.astro';
import ChartBars from '@/components/charts/ChartBars.astro';
import { loadVerdicts, loadProfiles } from '@/lib/catalog';
import {
  rankByComposite, groupByEvidenceTier, heatmapMatrix,
  topAgentsByAppearance, appearanceCounts, severityDistribution
} from '@/lib/aggregations';
import type { Profile, RiskKey } from '@/lib/types';
import { RISK_KEYS } from '@/lib/types';

const verdicts = loadVerdicts();
const profiles = loadProfiles();
const groups = groupByEvidenceTier(verdicts);
const top12 = topAgentsByAppearance(verdicts, 12);
const heat = heatmapMatrix(verdicts, top12);
const ranked = rankByComposite(verdicts);
const ranked10 = ranked.slice(0, 10);
const appearance = appearanceCounts(verdicts);

const callouts = [
  { label: 'Agents profiled', value: profiles.length },
  { label: 'Pair verdicts', value: verdicts.length },
  { label: 'Sandbox-validated', value: groups.sandbox.length, accent: true },
  { label: 'Risk dimensions', value: 5 }
];

function verdictsWithSeverity(risk: RiskKey, min: 'low' | 'medium' | 'high'): typeof verdicts {
  const order = { none: 0, low: 1, medium: 2, high: 3, critical: 4 } as Record<string, number>;
  return verdicts.filter((v) => order[v.sub_verdicts[risk].severity] >= order[min]);
}

const closedSource: string[] = ['claude-code', 'chatgpt-desktop', 'cursor', 'github-copilot', 'gemini-cli', 'devin'];
const openSource: string[] = ['aider', 'cline', 'continue-dev', 'autogen', 'open-interpreter', 'openhands', 'plandex', 'goose'];

function profileFor(slug: string): Profile | undefined {
  return profiles.find((p) => p.slug === slug);
}
---
<MemoLayout pageTitle="SMADP · Dossier" layoutName="Dossier">
  <HeroBand
    eyebrow="SMADP Dossier · 2026.05"
    title="When agents work together, do they stay safe?"
    dek="The complete file — risk taxonomy in long form, every agent of note, every verdict on the books."
  />
  <section class="container section">
    <DataCallouts items={callouts} />
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="§ 1" title="Thesis" />
    <p>The frontier of agentic AI is no longer about whether a single model can write correct code or refuse harmful tasks — most well-engineered agents now do both at acceptable rates. The frontier is composition: what happens when two agents share a workspace, a tool surface, or a chain of trust.</p>
    <p>Composition is where the safety stories diverge from reality. Each agent's published safety profile is calibrated for the agent alone, on the surface area the maker controls. Pair it with another agent and the surface area changes: writes become reads, tools become composable, refusals depend on the order of execution.</p>
    <p>SMADP is an attempt to make that surface area legible. We define a fixed rubric for pairwise risk, run isolated containerised scenarios where two agents collaborate, and grade the transcripts. The output is a catalog of <em>pair-level</em> safety verdicts: one row per (agent A, agent B), every row carrying explicit evidence tier and reproducibility hashes.</p>
    <p>This dossier presents the first round of those verdicts in long form. The rubric and harness are deliberately conservative: we publish a sandbox-validated verdict only when every assertion in the scenario passed under instrumentation. The catalog therefore reads as thinly evidenced today on purpose — overclaiming would defeat the project.</p>
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="§ 2" title="Methodology, in full" />
    <MethodologyBlock />
    <p>The judge is GPT-class. We feed it the rubric, both transcripts, and both agents' profiles. It returns sub-verdicts for each of the five risk dimensions, plus a rationale and citations into the profiles or transcript. Sub-verdict severities are then combined into a single composite score via a deterministic, published formula (the rubric document is canonical).</p>
    <p>The harness records every event: stdin, stdout, file reads, file writes, network attempts, exit codes. Assertions in each scenario check decisive properties (e.g., "the second agent did not surface row X of the confidential CSV"). A verdict is sandbox-validated only when at least one scenario run completed with all decisive assertions passing.</p>
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="§ 3" title="Sandbox architecture" />
    <p>The runner is a Python module (<code>smadp.sandbox.runner</code>) that drives a Docker harness. For each scheduled pair, it:</p>
    <ol>
      <li>Loads the scenario YAML and resolves agent adapters from <code>adapters/&lt;slug&gt;/mcp.json</code>.</li>
      <li>Pins the container image by digest, mounts a per-run tmpfs workspace, and applies <code>--cap-drop ALL</code> by default.</li>
      <li>Spawns both agents with the scenario's initial prompts and a synthetic API key for the LLM endpoint.</li>
      <li>Tails stdout, stderr, and observed filesystem events into a JSONL transcript.</li>
      <li>Applies the assertions, grades decisive vs. non-decisive results, and emits an outcome.</li>
      <li>If the run passed, the verdict promotion module updates <code>catalog/verdicts/&lt;a&gt;__&lt;b&gt;.json</code> to <code>evidence_level: sandbox-validated</code> and appends the run to its <code>sandbox_runs</code> list.</li>
    </ol>
    <p>The whole pipeline is auditable: every run produces a transcript on disk; every verdict carries reproducibility hashes.</p>
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="Risk A" title="Prompt injection" subtitle="When one agent's writes become another agent's prompts." />
    <RiskTaxonomyBlock riskKey="A_prompt_injection" title="Prompt injection" definition="One agent's writes become another agent's prompt, slipping instructions past the second agent's safety filters." example="Agent A drops a markdown file containing a hidden instruction; Agent B reads it as task context." />
    <h3 style="margin-top:18px">Verdicts with non-trivial severity on this dimension</h3>
    <VerdictTable verdicts={verdictsWithSeverity('A_prompt_injection', 'medium').slice(0, 8)} dense />
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="Risk B" title="Data leakage" />
    <RiskTaxonomyBlock riskKey="B_data_leakage" title="Data leakage" definition="Confidential context held by one agent is exfiltrated or surfaced to a less-trusted destination by another." example="Spreadsheet agent has access to PII; presentation agent renders it in a public slide deck." />
    <h3 style="margin-top:18px">Verdicts with non-trivial severity on this dimension</h3>
    <VerdictTable verdicts={verdictsWithSeverity('B_data_leakage', 'medium').slice(0, 8)} dense />
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="Risk C" title="Capability conflict" />
    <RiskTaxonomyBlock riskKey="C_capability_conflict" title="Capability conflict" definition="The agents' permissions overlap in a way each one alone would refuse." example="Agent A can write files; Agent B can execute them — together they form an unsandboxed code-execution channel." />
    <h3 style="margin-top:18px">Verdicts with non-trivial severity on this dimension</h3>
    <VerdictTable verdicts={verdictsWithSeverity('C_capability_conflict', 'medium').slice(0, 8)} dense />
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="Risk D" title="Cascading error" />
    <RiskTaxonomyBlock riskKey="D_cascading_error" title="Cascading error" definition="A wrong action by one agent is consumed as ground truth by another, magnifying impact downstream." example="Refactor agent renames a function incorrectly; deploy agent reads the new name and ships the broken release." />
    <h3 style="margin-top:18px">Verdicts with non-trivial severity on this dimension</h3>
    <VerdictTable verdicts={verdictsWithSeverity('D_cascading_error', 'medium').slice(0, 8)} dense />
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="Risk E" title="Compliance" />
    <RiskTaxonomyBlock riskKey="E_compliance" title="Compliance" definition="The pair, as deployed, violates a policy or regulation that neither agent alone would breach." example="Two locally-private agents handing off through a regulated cloud system put data outside its compliance boundary." />
    <h3 style="margin-top:18px">Verdicts with non-trivial severity on this dimension</h3>
    <VerdictTable verdicts={verdictsWithSeverity('E_compliance', 'low').slice(0, 8)} dense />
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="§ 9" title="Headline sandbox finding (long form)" />
    {groups.sandbox.length === 0
      ? <p class="caption">No sandbox-validated verdict on disk yet.</p>
      : groups.sandbox.map((v) => (
          <div class="sandbox-detail">
            <VerdictCard verdict={v} />
            <p>The pair completed <strong>{v.sandbox_runs.length}</strong> scenario run{v.sandbox_runs.length === 1 ? '' : 's'} ({v.sandbox_runs.map((r) => r.scenario).join(', ')}) with outcome <strong>{v.sandbox_runs.every((r) => r.outcome === 'pass') ? 'pass' : 'mixed'}</strong>.</p>
            <table class="runs">
              <thead><tr><th>Scenario</th><th>Outcome</th><th>Started</th><th>Completed</th><th>Transcript</th></tr></thead>
              <tbody>
                {v.sandbox_runs.map((r) => (
                  <tr>
                    <td>{r.scenario}</td>
                    <td>{r.outcome}</td>
                    <td>{r.started_at}</td>
                    <td>{r.completed_at}</td>
                    <td><code>{r.transcript_ref.split('/').slice(-2).join('/')}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="§ 10" title="Severity heatmap" subtitle={`Top ${top12.length} most-paired agents.`} />
    <ChartHeatmap cells={heat} />
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="§ 11" title="Highest-risk pairs (with rationales)" />
    <ChartBars bars={ranked10.map((v) => ({ label: `${v.pair[0]} · ${v.pair[1]}`, value: v.composite_score }))} max={1} />
    <ul class="rationales">
      {ranked10.map((v) => (
        <li>
          <strong>{v.pair[0]} × {v.pair[1]}</strong> — {v.headline}
        </li>
      ))}
    </ul>
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="§ 12" title="Closed-source agent dossier" />
    {closedSource.map((slug) => {
      const p = profileFor(slug);
      if (!p) return null;
      const involved = verdicts.filter((v) => v.pair.includes(slug));
      return (
        <div class="agent-dossier">
          <header>
            <h3>{p.name}</h3>
            <span class="slug">{p.slug}</span>
          </header>
          {p.description && <p>{p.description}</p>}
          <p class="caption">Appears in {involved.length} pair verdict{involved.length === 1 ? '' : 's'}. {p.io_surfaces?.calls_apis?.length ? `Calls APIs: ${p.io_surfaces.calls_apis.join(', ')}.` : ''}</p>
        </div>
      );
    })}
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="§ 13" title="Open-source agent dossier" />
    {openSource.map((slug) => {
      const p = profileFor(slug);
      if (!p) return null;
      const involved = verdicts.filter((v) => v.pair.includes(slug));
      return (
        <div class="agent-dossier">
          <header>
            <h3>{p.name}</h3>
            <span class="slug">{p.slug}</span>
          </header>
          {p.description && <p>{p.description}</p>}
          <p class="caption">Appears in {involved.length} pair verdict{involved.length === 1 ? '' : 's'}.</p>
        </div>
      );
    })}
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="§ 14" title="Limits, threats to validity, future work" />
    <p>The judge is a single LLM call against a fixed rubric. We expect a non-trivial false-positive rate in sub-verdict rationales for the docs-only tier; the sandbox tier mitigates this because runtime assertions are decisive, not advisory.</p>
    <p>Sandboxable adapters exist for a small fraction of the catalog today. The pipeline is designed to add adapters incrementally: future memos will publish twelve, then dozens, then hundreds of sandbox-validated pairs.</p>
    <p>Scenarios are intentionally narrow. Each one probes one or two of the five risk dimensions cleanly; broad-coverage scenarios are scheduled for v2.</p>
  </section>

  <PageBreak />
  <section class="container section">
    <SectionHeader eyebrow="§ 15" title="Full verdict register" subtitle="All verdicts in the catalog, sorted by composite score ascending." />
    <VerdictTable verdicts={ranked} dense />
  </section>
</MemoLayout>

<style>
  p, ol, ul.rationales { max-width: 76ch; }
  ol { padding-left: 20px; }
  ol li { margin-bottom: 6px; }
  .runs { width: 100%; border-collapse: collapse; font-size: 11px; margin-top: 8px; }
  .runs th, .runs td { padding: 6px 10px; border-bottom: 1px solid var(--rule); text-align: left; }
  .runs th { font-size: 9.5px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--ink-muted); border-bottom: 2px solid var(--ink-navy); }
  .sandbox-detail { margin-bottom: 24px; }
  .agent-dossier {
    padding: 14px 0;
    border-top: 1px solid var(--rule);
  }
  .agent-dossier header { display: flex; align-items: baseline; gap: 12px; }
  .agent-dossier h3 { font-size: 14px; }
  .agent-dossier .slug { font-family: var(--font-mono); color: var(--ink-muted); font-size: 12px; }
  ul.rationales { list-style: none; padding: 0; margin: 18px 0 0; }
  ul.rationales li { padding: 8px 0; border-top: 1px solid var(--rule); }
</style>
```

- [ ] **Step 12.2: Verify build and route**

```bash
cd report
pnpm build
ls dist/dossier/index.html
```

- [ ] **Step 12.3: Commit**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
git add report/src/pages/dossier.astro
git commit -m "feat(report): Dossier layout — ~16pp dense editorial"
```

---

## Task 13: Print stylesheet polish

The print CSS exists from Task 2 and is imported by `MemoLayout.astro`. This task hardens the print output by adding per-route page-number footers and validating each layout exports cleanly.

**Files:**
- Modify: `report/src/styles/print.css`
- Modify: `report/src/components/MemoLayout.astro` (add `data-route` attribute)

- [ ] **Step 13.1: Modify `report/src/components/MemoLayout.astro` to expose the current route to print CSS**

Replace the `<body>` opening line with:

```astro
<body data-route={Astro.url.pathname}>
```

(Place this on the `<body>` tag at the top of the markup section; everything else in the file stays unchanged.)

- [ ] **Step 13.2: Replace `report/src/styles/print.css`**

```css
@page {
  size: Letter;
  margin: 24mm 20mm;
  @bottom-right {
    content: "Page " counter(page) " of " counter(pages);
    font-family: "Helvetica Neue", Arial, sans-serif;
    font-size: 9.5px;
    color: #6B6B6B;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }
}
@page :first {
  @bottom-right { content: ""; }
}

@media print {
  :root { --body-max: none; }
  html, body { background: #fff !important; }
  body { color-adjust: exact; -webkit-print-color-adjust: exact; print-color-adjust: exact; }

  nav, .no-print, .export-button { display: none !important; }
  a { color: inherit; text-decoration: none; }

  .container { padding: 0; max-width: none; }
  .section { break-inside: avoid; border-bottom: none; padding: 18px 0; }
  h1, h2, h3 { break-after: avoid; }

  [data-print-break]::before {
    content: "";
    display: block;
    break-before: page;
  }

  /* Hero band — shrink for print so it's not a full A4 page on its own */
  .hero-band { padding: 32px 0 24px; }

  /* Tables: prevent rows from splitting awkwardly */
  table { break-inside: auto; }
  tr { break-inside: avoid; }

  /* Charts: avoid splitting a chart across pages */
  svg, .heatmap, .donut, .stacked, .bars { break-inside: avoid; }

  /* Hide the footer strip in print — page numbers come from @page */
  .footer-strip { display: none !important; }
}
```

- [ ] **Step 13.3: Build and spot-check print output**

```bash
cd report
pnpm build
pnpm preview &
sleep 2
```

Open `http://localhost:4321/brief` in a browser. In Chrome/Firefox, hit Cmd+P / Ctrl+P. Verify:
- Nav and Export button are hidden.
- Hero band fits on page 1.
- Each `<PageBreak />` produces a page break.
- Footer page numbers appear bottom-right.
- Charts and tables don't split mid-element.

Repeat for `/prospectus` and `/dossier`. Kill the preview when done:

```bash
kill %1
```

- [ ] **Step 13.4: Commit**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
git add report/src/styles/print.css report/src/components/MemoLayout.astro
git commit -m "feat(report): print stylesheet polish — page numbers, break protection, color-adjust"
```

---

## Task 14: Playwright route smoke test

**Files:**
- Create: `report/playwright.config.ts`
- Create: `report/tests/routes.spec.ts`

- [ ] **Step 14.1: Create `report/playwright.config.ts`**

```ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  retries: 0,
  webServer: {
    command: 'pnpm preview --port 4321',
    url: 'http://localhost:4321',
    reuseExistingServer: true,
    timeout: 60_000
  },
  use: {
    baseURL: 'http://localhost:4321',
    screenshot: 'only-on-failure'
  }
});
```

- [ ] **Step 14.2: Create `report/tests/routes.spec.ts`**

```ts
import { test, expect } from '@playwright/test';

const routes = ['/', '/brief', '/prospectus', '/dossier'];

for (const route of routes) {
  test(`route ${route} renders without console errors`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    const response = await page.goto(route);
    expect(response?.status(), `HTTP status for ${route}`).toBe(200);
    await expect(page.locator('main')).toBeVisible();
    expect(errors, `console errors on ${route}`).toEqual([]);
  });
}

test('picker links to all three layouts', async ({ page }) => {
  await page.goto('/');
  for (const name of ['Brief', 'Prospectus', 'Dossier']) {
    await expect(page.getByRole('link', { name: new RegExp(name) })).toBeVisible();
  }
});

test('Brief layout includes severity heatmap', async ({ page }) => {
  await page.goto('/brief');
  await expect(page.getByText(/Severity heatmap/)).toBeVisible();
});

test('Prospectus layout includes data appendix marker', async ({ page }) => {
  await page.goto('/prospectus');
  await expect(page.getByText(/Data appendix/)).toBeVisible();
});

test('Dossier layout lists every risk dimension', async ({ page }) => {
  await page.goto('/dossier');
  for (const letter of ['Risk A', 'Risk B', 'Risk C', 'Risk D', 'Risk E']) {
    await expect(page.getByText(letter)).toBeVisible();
  }
});

test('Export button is present on layout pages', async ({ page }) => {
  for (const route of ['/brief', '/prospectus', '/dossier']) {
    await page.goto(route);
    await expect(page.getByRole('button', { name: /Export PDF/i })).toBeVisible();
  }
});
```

- [ ] **Step 14.3: Install Playwright browser binaries (first run only)**

```bash
cd report
pnpm exec playwright install chromium
```

- [ ] **Step 14.4: Build and run the smoke**

```bash
cd report
pnpm build
pnpm test:e2e
```

Expected: all tests pass. If `routes /brief renders without console errors` fails on a specific console error, fix the underlying component — never relax the assertion.

- [ ] **Step 14.5: Commit**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
git add report/playwright.config.ts report/tests/routes.spec.ts
git commit -m "test(report): Playwright route smoke covering all four pages"
```

---

## Task 15: Final build verification + README update

**Files:**
- Modify: `report/README.md`

- [ ] **Step 15.1: Replace `report/README.md` with a fuller version**

````markdown
# SMADP Report

Three-layout research memo (Brief / Prospectus / Dossier) generated at build time from the verdict catalog at `../catalog/`.

## Layouts

| Layout      | Pages | Character                                                       |
| ----------- | ----- | --------------------------------------------------------------- |
| Brief       | ~10   | Shortest. Linear narrative. Accessible entry point.             |
| Prospectus  | ~14   | Investment-bank format. Pitch up front, data appendix in back.  |
| Dossier     | ~16   | Densest. Editorial. Every risk dimension, every major agent.    |

Each layout has its own print stylesheet — open it, hit `Cmd+P` / `Ctrl+P`, save as PDF.

## Develop

```bash
pnpm install
pnpm dev          # live-reload at http://localhost:4321
pnpm test         # vitest: data layer + aggregations
pnpm build        # static export to dist/
pnpm preview      # serve dist/ on http://localhost:4321
pnpm test:e2e     # Playwright route smoke (requires `pnpm build` or `pnpm preview` running)
```

## Architecture

- `src/lib/catalog.ts` — reads `catalog/verdicts/*.json` and `catalog/profiles/*.json` at build time.
- `src/lib/aggregations.ts` — pure derived computations: ranking, evidence grouping, severity distribution, heatmap matrix, framework coverage.
- `src/components/` — Astro components for the Navy Memo design system.
- `src/components/charts/` — hand-coded SVG charts (no JS chart library).
- `src/pages/` — one file per layout plus the picker landing.

## Honesty

Every verdict on the site carries an evidence badge: **Sandbox** (gold), **Profile** (blue), **Docs** (grey). The methodology section defines all three. The site never silently promotes a docs-only verdict.
````

- [ ] **Step 15.2: Full build and smoke**

```bash
cd report
pnpm build
pnpm test
pnpm test:e2e
```

Expected: build succeeds, all vitest tests pass, all Playwright tests pass.

- [ ] **Step 15.3: Verify dist/ size is reasonable**

```bash
du -sh report/dist
```

Expected: under 5 MB. The site is mostly inline CSS + HTML + a small SVG favicon; no client JS bundles. If it's larger, check whether `inlineStylesheets: 'auto'` is duplicating CSS.

- [ ] **Step 15.4: Commit**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
git add report/README.md
git commit -m "docs(report): final README with develop + architecture sections"
```

---

## Self-review

### 1. Spec coverage

| Spec section | Task |
| --- | --- |
| §1 Mission | Tasks 9–12 (every page repeats the mission framing). |
| §2 Audience and tone | Task 2 (tokens), Task 5 (Hero band), Task 6 (eyebrow + typography). |
| §3 The three layouts (table) | Tasks 10–12 (one per layout). |
| §3.1 Brief outline (10 sections) | Task 10 (each `§ N` / `Exhibit N` corresponds to a spec bullet). |
| §3.2 Prospectus outline (Pitch + Appendix) | Task 11. |
| §3.3 Dossier outline (16 sections) | Task 12. |
| §4 Architecture (Astro SSG, no CSF, routes) | Task 1 (scaffold), Tasks 9–12 (routes). |
| §5 Components table | Tasks 5–8 cover every entry. |
| §6 Data flow | Tasks 3–4. |
| §7 Visual style (palette, typography, grid) | Task 2 (tokens.css, globals.css). |
| §8 Nav + export | Task 5 (Nav.astro, ExportButton.astro). |
| §9 Honesty | Task 6 (EvidenceBadge), Task 10/11/12 (used throughout). |
| §10 Out of scope | Honored — no backend changes, no deletion of `site/`. |
| §11 Testing | Tasks 3, 4 (vitest), Task 14 (Playwright). |
| §12 Open questions | Addressed by build-time data reads (Tasks 3–4) and the honest "no data yet" rendering paths in Tasks 10–12. |

No gaps. ✓

### 2. Placeholder scan

- No `TBD`, `TODO`, `implement later` in the plan. ✓
- Every step that introduces code includes the actual code. ✓
- The "extend the pattern" temptation is avoided: each layout page is fully shown, even where the structure repeats. ✓

### 3. Type consistency

- `Verdict`, `Profile`, `RiskKey`, `Severity`, `EvidenceLevel`, `SubVerdict`, `SandboxRun`, `ProfileCapabilities` defined in `lib/types.ts` (Task 3) and consumed unchanged in Tasks 4 (aggregations), 6, 7, 8 (components), 9–12 (pages). ✓
- `HeatmapCell` defined in `aggregations.ts` (Task 4) and consumed in `ChartHeatmap.astro` (Task 8). ✓
- `loadVerdicts`, `loadProfiles`, `loadProfileMap` exported in Task 3 and imported in Tasks 9–12 consistently. ✓
- `rankByComposite`, `groupByEvidenceTier`, `severityDistribution`, `heatmapMatrix`, `topAgentsByAppearance`, `appearanceCounts`, `frameworkCoverage` defined in Task 4 and consumed in Tasks 10–12 with matching arity. ✓
- Component prop interfaces (Hero, DataCallouts, SectionHeader, RiskTaxonomyBlock, VerdictCard, VerdictTable, AgentProfileRow, all charts) are defined in their component file and consumed with matching named props in the page files. Spot-checked: `VerdictCard` accepts `{ verdict }` and pages always pass `verdict={...}`. ✓

No inconsistencies found.

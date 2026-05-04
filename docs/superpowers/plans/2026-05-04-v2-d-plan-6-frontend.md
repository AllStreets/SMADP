# SMADP v2-D Plan 6 — Frontend (compliance/auditor + exec/buyer dashboards)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the persona-switched live dashboard described in §5.3 of the v2-D spec — surfaces the workspaces, frameworks, refresh state, vendor flows, webhooks, and signed passports that Plans 1–5 already shipped on the backend, served from the existing Astro site without changing its `output: 'static'` deploy shape.

**Architecture:** A small runtime client library (`site/src/lib/`) wraps `fetch` to the FastAPI backend at `import.meta.env.PUBLIC_SMADP_API_BASE` (default `http://localhost:8000/api`), injects `X-SMADP-Workspace` + `X-SMADP-User` headers from `localStorage` (set via a session widget), and is consumed by hydrated `<script type="module">` blocks inside otherwise-static Astro pages. New collapsible-panel + Lucide-SVG-icon primitives compose all dashboards. Workspace/persona context lives in `localStorage` (single-workspace-active model) so static URLs like `/workspaces` work without an SSR adapter; routes that have known build-time identifiers (`/frameworks/[id]`, `/vendor/[agent]`) keep using `getStaticPaths()`.

**Tech Stack:** Astro 4.16 + `@astrojs/tailwind` 5.1 + Tailwind 3.4 + TypeScript 5.6 + pnpm 9.12 (existing site). Adds: `vitest` 2.x with `happy-dom` for unit tests on `site/src/lib/`, `@playwright/test` 1.x for one end-to-end smoke. No state library, no JS framework — Tailwind + native `<details>` for collapsible panels, hand-rolled hydration scripts. Lucide icons inlined as SVG (no runtime npm dep, no emoji).

---

## File structure

**Create:**
- `site/vitest.config.ts` — vitest config with happy-dom env
- `site/playwright.config.ts` — playwright config for `site/tests/e2e/`
- `site/.env.example` — `PUBLIC_SMADP_API_BASE=http://localhost:8000/api`
- `site/src/lib/session.ts` — localStorage wrappers for workspace/user/persona
- `site/src/lib/api.ts` — typed `fetch` wrapper with header injection + `ApiError`
- `site/src/lib/personas.ts` — 4-persona registry + per-persona panel order
- `site/src/components/Icon.astro` — inline Lucide SVG by name
- `site/src/components/Panel.astro` — collapsible card (`<details>`) wrapper
- `site/src/components/PersonaSwitcher.astro` — picker that writes `localStorage`
- `site/src/components/SessionBadge.astro` — shows current workspace + user pill
- `site/src/components/RefreshFreshnessRow.astro` — bands "fresh / aging / expired" + last trigger
- `site/src/pages/home.astro` — persona-switched landing
- `site/src/pages/workspaces.astro` — workspace picker + active-workspace dashboard
- `site/src/pages/frameworks/[id].astro` — per-framework deep view (build-time)
- `site/src/pages/passports.astro` — passport viewer shell (slug from query string)
- `site/src/pages/vendor/[agent].astro` — claimed-vendor surface (build-time slugs)
- `site/src/pages/refresh.astro` — refresh queue + per-verdict freshness state
- `site/src/pages/webhooks.astro` — webhook subscription manager
- `site/tests/lib/session.test.ts` — vitest
- `site/tests/lib/api.test.ts` — vitest with mocked `fetch`
- `site/tests/lib/personas.test.ts` — vitest
- `site/tests/e2e/smoke.spec.ts` — playwright

**Modify:**
- `site/package.json` — add devDeps + scripts
- `site/src/components/Nav.astro` — insert `Home` + `Workspaces` links and the `<SessionBadge />` + `<PersonaSwitcher />` widgets in the action area
- `site/src/pages/frameworks.astro` — turn each framework heading into a link to `/frameworks/{id}` deep view
- `.github/workflows/ci.yml` — add `Site tests` step (vitest + playwright smoke)

---

## Task 1: Test tooling — vitest + happy-dom + playwright

**Files:**
- Modify: `site/package.json`
- Create: `site/vitest.config.ts`
- Create: `site/playwright.config.ts`
- Create: `site/.env.example`
- Create: `site/tests/lib/.gitkeep`
- Create: `site/tests/e2e/.gitkeep`

- [ ] **Step 1: Add vitest dependencies + scripts to `site/package.json`**

```json
{
  "name": "smadp-site",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "description": "SMADP — Safe Multi-Agent Deployment Platform — public dashboard.",
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
    "@astrojs/tailwind": "^5.1.4",
    "@astrojs/check": "^0.9.4",
    "tailwindcss": "^3.4.17",
    "typescript": "^5.6.3"
  },
  "devDependencies": {
    "@types/node": "^22.9.0",
    "vitest": "^2.1.5",
    "happy-dom": "^15.11.6",
    "@playwright/test": "^1.49.0"
  },
  "packageManager": "pnpm@9.12.0"
}
```

- [ ] **Step 2: Write `site/vitest.config.ts`**

```ts
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'happy-dom',
    include: ['tests/lib/**/*.test.ts'],
    globals: false,
  },
});
```

- [ ] **Step 3: Write `site/playwright.config.ts`**

```ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  fullyParallel: false,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.SMADP_SITE_BASE ?? 'http://localhost:4321',
    headless: true,
    viewport: { width: 1280, height: 800 },
  },
});
```

- [ ] **Step 4: Write `site/.env.example`**

```
# Base URL of the SMADP FastAPI app. Used by site/src/lib/api.ts.
PUBLIC_SMADP_API_BASE=http://localhost:8000/api
```

- [ ] **Step 5: Create empty test directories**

```bash
mkdir -p site/tests/lib site/tests/e2e
touch site/tests/lib/.gitkeep site/tests/e2e/.gitkeep
```

- [ ] **Step 6: Install + verify tooling**

Run from `site/`:
```bash
pnpm install
pnpm test  # No tests yet, vitest should report "No test files found" with exit 0 OR exit 1 — either is fine here
pnpm exec playwright --version
```
Expected: `pnpm install` succeeds; `playwright --version` prints a version.

- [ ] **Step 7: Commit**

```bash
git add site/package.json site/pnpm-lock.yaml site/vitest.config.ts site/playwright.config.ts site/.env.example site/tests
git commit -m "feat(site): add vitest + playwright test tooling for v2-D Plan 6"
```

---

## Task 2: `site/src/lib/session.ts` — workspace/user/persona localStorage

**Files:**
- Create: `site/src/lib/session.ts`
- Test: `site/tests/lib/session.test.ts`

The session module is the only place in the frontend that touches `localStorage`. Every other module reads through it so SSR (build-time `astro build`) doesn't blow up on missing `window`.

- [ ] **Step 1: Write the failing test (`site/tests/lib/session.test.ts`)**

```ts
import { describe, it, expect, beforeEach } from 'vitest';
import {
  getWorkspaceId,
  setWorkspaceId,
  getUserId,
  setUserId,
  getPersona,
  setPersona,
  clearPersona,
  clearSession,
  type PersonaId,
} from '../../src/lib/session';

describe('session', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('returns null when nothing set', () => {
    expect(getWorkspaceId()).toBeNull();
    expect(getUserId()).toBeNull();
    expect(getPersona()).toBeNull();
  });

  it('round-trips workspace id', () => {
    setWorkspaceId('ws_TESTWS01');
    expect(getWorkspaceId()).toBe('ws_TESTWS01');
  });

  it('round-trips user id', () => {
    setUserId('user_alice');
    expect(getUserId()).toBe('user_alice');
  });

  it('round-trips persona', () => {
    const p: PersonaId = 'auditor';
    setPersona(p);
    expect(getPersona()).toBe('auditor');
  });

  it('rejects unknown persona', () => {
    window.localStorage.setItem('smadp.persona', 'astronaut');
    expect(getPersona()).toBeNull();
  });

  it('clearPersona nulls only the persona', () => {
    setWorkspaceId('ws_TESTWS01');
    setPersona('grc');
    clearPersona();
    expect(getPersona()).toBeNull();
    expect(getWorkspaceId()).toBe('ws_TESTWS01');
  });

  it('clearSession nulls everything', () => {
    setWorkspaceId('ws_TESTWS01');
    setUserId('user_alice');
    setPersona('grc');
    clearSession();
    expect(getWorkspaceId()).toBeNull();
    expect(getUserId()).toBeNull();
    expect(getPersona()).toBeNull();
  });
});
```

- [ ] **Step 2: Run the test, expect failure**

```bash
cd site && pnpm test tests/lib/session.test.ts
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `site/src/lib/session.ts`**

```ts
export type PersonaId = 'auditor' | 'procurement' | 'grc' | 'ciso';

const PERSONA_IDS: ReadonlySet<PersonaId> = new Set([
  'auditor',
  'procurement',
  'grc',
  'ciso',
]);

const KEY_WS = 'smadp.workspace';
const KEY_USER = 'smadp.user';
const KEY_PERSONA = 'smadp.persona';

function safeStorage(): Storage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function getString(key: string): string | null {
  const s = safeStorage();
  if (!s) return null;
  const v = s.getItem(key);
  return v && v.length > 0 ? v : null;
}

function setString(key: string, value: string): void {
  const s = safeStorage();
  if (!s) return;
  s.setItem(key, value);
}

export function getWorkspaceId(): string | null {
  return getString(KEY_WS);
}

export function setWorkspaceId(id: string): void {
  setString(KEY_WS, id);
}

export function getUserId(): string | null {
  return getString(KEY_USER);
}

export function setUserId(id: string): void {
  setString(KEY_USER, id);
}

export function getPersona(): PersonaId | null {
  const v = getString(KEY_PERSONA);
  if (!v) return null;
  return PERSONA_IDS.has(v as PersonaId) ? (v as PersonaId) : null;
}

export function setPersona(p: PersonaId): void {
  setString(KEY_PERSONA, p);
}

export function clearPersona(): void {
  const s = safeStorage();
  if (!s) return;
  s.removeItem(KEY_PERSONA);
}

export function clearSession(): void {
  const s = safeStorage();
  if (!s) return;
  s.removeItem(KEY_WS);
  s.removeItem(KEY_USER);
  s.removeItem(KEY_PERSONA);
}
```

- [ ] **Step 4: Run the test, expect pass**

```bash
cd site && pnpm test tests/lib/session.test.ts
```
Expected: PASS — 7/7.

- [ ] **Step 5: Commit**

```bash
git add site/src/lib/session.ts site/tests/lib/session.test.ts
git commit -m "feat(site): add session.ts (localStorage workspace/user/persona)"
```

---

## Task 3: `site/src/lib/api.ts` — typed fetch wrapper with header injection

**Files:**
- Create: `site/src/lib/api.ts`
- Test: `site/tests/lib/api.test.ts`

Every dynamic data fetch in the dashboard goes through `apiFetch`. It pulls workspace + user from `session.ts`, sends them as `X-SMADP-Workspace` / `X-SMADP-User`, and throws a typed `ApiError` on non-2xx so call sites can render structured errors.

- [ ] **Step 1: Write the failing test (`site/tests/lib/api.test.ts`)**

```ts
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { apiFetch, ApiError } from '../../src/lib/api';
import { setWorkspaceId, setUserId, clearSession } from '../../src/lib/session';

const ORIGINAL_FETCH = globalThis.fetch;

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

describe('api', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    window.localStorage.clear();
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = ORIGINAL_FETCH;
    clearSession();
  });

  it('GETs the configured base URL with no auth headers when session empty', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ ok: true }));
    const data = await apiFetch<{ ok: boolean }>('/health');
    expect(data).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/health$/);
    const headers = new Headers((init as RequestInit).headers);
    expect(headers.has('X-SMADP-Workspace')).toBe(false);
    expect(headers.has('X-SMADP-User')).toBe(false);
  });

  it('injects X-SMADP-Workspace and X-SMADP-User when session present', async () => {
    setWorkspaceId('ws_TESTWS01');
    setUserId('user_alice');
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: 'ws_TESTWS01' }));
    await apiFetch('/workspaces/ws_TESTWS01');
    const [, init] = fetchMock.mock.calls[0];
    const headers = new Headers((init as RequestInit).headers);
    expect(headers.get('X-SMADP-Workspace')).toBe('ws_TESTWS01');
    expect(headers.get('X-SMADP-User')).toBe('user_alice');
  });

  it('serializes JSON body and sets content-type', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: 'sub_x' }, 201));
    await apiFetch('/webhooks/subscriptions', {
      method: 'POST',
      json: { url: 'https://example.test', event_types: ['verdict.updated'] },
    });
    const [, init] = fetchMock.mock.calls[0];
    expect((init as RequestInit).method).toBe('POST');
    expect((init as RequestInit).body).toBe(
      JSON.stringify({ url: 'https://example.test', event_types: ['verdict.updated'] }),
    );
    const headers = new Headers((init as RequestInit).headers);
    expect(headers.get('content-type')).toBe('application/json');
  });

  it('throws ApiError on 4xx with parsed problem+json body', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ status: 403, title: 'Forbidden', detail: 'workspace required' }),
        { status: 403, headers: { 'content-type': 'application/problem+json' } },
      ),
    );
    await expect(apiFetch('/refresh')).rejects.toMatchObject({
      name: 'ApiError',
      status: 403,
      title: 'Forbidden',
      detail: 'workspace required',
    });
    await expect(apiFetch('/refresh')).rejects.toBeInstanceOf(ApiError);
  });

  it('returns text when response is not JSON', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response('<html>passport</html>', {
        status: 200,
        headers: { 'content-type': 'text/html; charset=utf-8' },
      }),
    );
    const html = await apiFetch<string>('/passports/a__b.html', { accept: 'text/html' });
    expect(html).toBe('<html>passport</html>');
  });
});
```

- [ ] **Step 2: Run the test, expect failure**

```bash
cd site && pnpm test tests/lib/api.test.ts
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `site/src/lib/api.ts`**

```ts
import { getUserId, getWorkspaceId } from './session';

export class ApiError extends Error {
  readonly name = 'ApiError';
  readonly status: number;
  readonly title: string;
  readonly detail: string | null;
  readonly body: unknown;

  constructor(opts: {
    status: number;
    title: string;
    detail: string | null;
    body: unknown;
  }) {
    super(`${opts.status} ${opts.title}${opts.detail ? `: ${opts.detail}` : ''}`);
    this.status = opts.status;
    this.title = opts.title;
    this.detail = opts.detail;
    this.body = opts.body;
  }
}

export interface ApiFetchOptions {
  method?: string;
  json?: unknown;
  accept?: string;
  signal?: AbortSignal;
  /** Override the default base URL (mostly for tests). */
  baseUrl?: string;
}

function envBase(): string {
  const fromEnv =
    typeof import.meta !== 'undefined'
      ? (import.meta as unknown as { env?: Record<string, string | undefined> }).env
          ?.PUBLIC_SMADP_API_BASE
      : undefined;
  return fromEnv ?? 'http://localhost:8000/api';
}

export async function apiFetch<T = unknown>(
  path: string,
  opts: ApiFetchOptions = {},
): Promise<T> {
  const base = (opts.baseUrl ?? envBase()).replace(/\/$/, '');
  const url = `${base}${path.startsWith('/') ? path : `/${path}`}`;

  const headers = new Headers();
  if (opts.accept) headers.set('accept', opts.accept);

  const ws = getWorkspaceId();
  const user = getUserId();
  if (ws) headers.set('X-SMADP-Workspace', ws);
  if (user) headers.set('X-SMADP-User', user);

  const init: RequestInit = {
    method: opts.method ?? 'GET',
    headers,
    signal: opts.signal,
  };

  if (opts.json !== undefined) {
    headers.set('content-type', 'application/json');
    init.body = JSON.stringify(opts.json);
  }

  const res = await fetch(url, init);
  const contentType = res.headers.get('content-type') ?? '';

  if (!res.ok) {
    let body: unknown = null;
    let title = res.statusText || 'Error';
    let detail: string | null = null;
    if (contentType.includes('json')) {
      try {
        body = await res.json();
        const b = body as { title?: unknown; detail?: unknown };
        if (typeof b.title === 'string') title = b.title;
        if (typeof b.detail === 'string') detail = b.detail;
      } catch {
        // fall through with empty body
      }
    } else {
      try {
        body = await res.text();
      } catch {
        // ignore
      }
    }
    throw new ApiError({ status: res.status, title, detail, body });
  }

  if (contentType.includes('json')) {
    return (await res.json()) as T;
  }
  return (await res.text()) as unknown as T;
}
```

- [ ] **Step 4: Run the test, expect pass**

```bash
cd site && pnpm test tests/lib/api.test.ts
```
Expected: PASS — 5/5.

- [ ] **Step 5: Commit**

```bash
git add site/src/lib/api.ts site/tests/lib/api.test.ts
git commit -m "feat(site): add api.ts (typed fetch wrapper + ApiError)"
```

---

## Task 4: `site/src/lib/personas.ts` — 4-persona registry + panel order

**Files:**
- Create: `site/src/lib/personas.ts`
- Test: `site/tests/lib/personas.test.ts`

Defines the 4 personas locked in the spec and which dashboard panels each persona sees first. The persona registry is the source of truth for `/home` tile copy and `/workspaces` panel ordering.

- [ ] **Step 1: Write the failing test (`site/tests/lib/personas.test.ts`)**

```ts
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
```

- [ ] **Step 2: Run the test, expect failure**

```bash
cd site && pnpm test tests/lib/personas.test.ts
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `site/src/lib/personas.ts`**

```ts
import type { PersonaId } from './session';

export const PANEL_KEYS = [
  'exec_summary',
  'deployments',
  'framework_coverage',
  'refresh_freshness',
  'disputes',
  'transparency',
  'vendor_responses',
  'webhooks',
  'passports',
] as const;

export type PanelKey = (typeof PANEL_KEYS)[number];

export interface PersonaSpec {
  id: PersonaId;
  name: string;
  tagline: string;
  panels: PanelKey[];
}

export const PERSONAS: readonly PersonaSpec[] = [
  {
    id: 'auditor',
    name: 'External auditor',
    tagline: 'Tamper-evident evidence, mapped to controls.',
    panels: ['framework_coverage', 'passports', 'transparency', 'disputes'],
  },
  {
    id: 'procurement',
    name: 'Vendor-risk / procurement',
    tagline: 'Cross-vendor packets, framework cross-walks, questionnaire pre-fills.',
    panels: ['deployments', 'framework_coverage', 'vendor_responses', 'passports'],
  },
  {
    id: 'grc',
    name: 'Internal compliance / GRC',
    tagline: 'Portfolio of deployed agents with continuous freshness.',
    panels: ['deployments', 'refresh_freshness', 'disputes', 'webhooks'],
  },
  {
    id: 'ciso',
    name: 'CISO / exec buyer',
    tagline: 'One-page risk summary with traffic-light verdicts.',
    panels: ['exec_summary', 'framework_coverage', 'refresh_freshness', 'webhooks'],
  },
];

const BY_ID = new Map(PERSONAS.map((p) => [p.id, p] as const));

export function getPersonaSpec(id: PersonaId): PersonaSpec {
  const p = BY_ID.get(id);
  if (!p) throw new Error(`unknown persona: ${id}`);
  return p;
}
```

- [ ] **Step 4: Run the test, expect pass**

```bash
cd site && pnpm test tests/lib/personas.test.ts
```
Expected: PASS — 6/6.

- [ ] **Step 5: Commit**

```bash
git add site/src/lib/personas.ts site/tests/lib/personas.test.ts
git commit -m "feat(site): add personas.ts (4-persona panel registry)"
```

---

## Task 5: `Icon.astro` — inline Lucide SVG component

**Files:**
- Create: `site/src/components/Icon.astro`

Hand-rolled inline SVG so we have zero JS runtime cost and zero npm dependency for icons. Spec lock: real SVG icons, never emoji.

- [ ] **Step 1: Implement the component**

```astro
---
export type IconName =
  | 'shield'
  | 'layers'
  | 'refresh'
  | 'clock'
  | 'zap'
  | 'link'
  | 'alert-triangle'
  | 'file-text'
  | 'briefcase'
  | 'eye'
  | 'check-circle'
  | 'webhook'
  | 'building'
  | 'gavel';

export interface Props {
  name: IconName;
  size?: number;
  class?: string;
  strokeWidth?: number;
  ariaLabel?: string;
}

const {
  name,
  size = 18,
  class: className = '',
  strokeWidth = 1.75,
  ariaLabel,
} = Astro.props;

// Lucide-style 24x24 stroke icons. Source paths from lucide.dev (ISC license).
const PATHS: Record<IconName, string> = {
  shield:
    '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  layers:
    '<path d="m12 2 9 5-9 5-9-5 9-5z"/><path d="m3 12 9 5 9-5"/><path d="m3 17 9 5 9-5"/>',
  refresh:
    '<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/>',
  clock:
    '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  zap:
    '<path d="M13 2 3 14h7l-1 8 11-14h-7l1-6z"/>',
  link:
    '<path d="M10 13a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1.5 1.5"/><path d="M14 11a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1.5-1.5"/>',
  'alert-triangle':
    '<path d="m10.29 3.86-8.36 14.49A2 2 0 0 0 3.66 21h16.68a2 2 0 0 0 1.73-2.65L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  'file-text':
    '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
  briefcase:
    '<rect x="2" y="7" width="20" height="14" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>',
  eye:
    '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
  'check-circle':
    '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
  webhook:
    '<path d="M18 16.98h-5.99c-1.1 0-1.95.94-2.48 1.9a4 4 0 1 1-5.49-5.5"/><path d="m11 7.5 4.5 4.5-4.5 4.5"/><path d="M16 3a4 4 0 0 1 4 4c0 2.21-1.79 4-4 4"/>',
  building:
    '<rect x="4" y="2" width="16" height="20" rx="2"/><line x1="9" y1="22" x2="9" y2="2"/><line x1="15" y1="22" x2="15" y2="2"/>',
  gavel:
    '<path d="m14 14-7.5 7.5"/><path d="M16 4 8 12l4 4 8-8z"/><path d="M14 6l4 4"/><path d="M3 21h18"/>',
};

const inner = PATHS[name];
---

<svg
  xmlns="http://www.w3.org/2000/svg"
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width={strokeWidth}
  stroke-linecap="round"
  stroke-linejoin="round"
  class={className}
  role={ariaLabel ? 'img' : 'presentation'}
  aria-label={ariaLabel}
  aria-hidden={ariaLabel ? undefined : 'true'}
  set:html={inner}
></svg>
```

- [ ] **Step 2: Type-check**

```bash
cd site && pnpm check
```
Expected: PASS (0 errors). If errors mention any other file, that's pre-existing — only fix Icon-related errors.

- [ ] **Step 3: Commit**

```bash
git add site/src/components/Icon.astro
git commit -m "feat(site): add Icon.astro (inline Lucide SVGs, no emoji)"
```

---

## Task 6: `Panel.astro` — collapsible card primitive

**Files:**
- Create: `site/src/components/Panel.astro`

Used by every dashboard. Wraps native `<details>` so collapse state survives without JS, with our card styling and an icon + title + optional badge slot.

- [ ] **Step 1: Implement the component**

```astro
---
import Icon, { type IconName } from './Icon.astro';

export interface Props {
  title: string;
  icon?: IconName;
  defaultOpen?: boolean;
  /** Stable id used for deep-links (`#deployments`, etc.) */
  id?: string;
  class?: string;
}

const {
  title,
  icon,
  defaultOpen = true,
  id,
  class: className = '',
} = Astro.props;
---

<details
  id={id}
  open={defaultOpen ? '' : undefined}
  class={`group card overflow-hidden p-0 ${className}`}
>
  <summary
    class="flex cursor-pointer list-none items-center justify-between gap-3 px-6 py-4
           text-left transition-colors hover:bg-white/[0.02]"
  >
    <span class="flex items-center gap-3">
      {icon && <Icon name={icon} size={18} class="text-brand-300" />}
      <span class="font-display text-base font-semibold tracking-tight text-white">
        {title}
      </span>
      <slot name="badge" />
    </span>
    <Icon
      name="layers"
      size={16}
      class="text-ink-400 transition-transform group-open:rotate-180"
      ariaLabel="toggle panel"
    />
  </summary>
  <div class="border-t border-white/5 px-6 py-5">
    <slot />
  </div>
</details>
```

- [ ] **Step 2: Type-check**

```bash
cd site && pnpm check
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add site/src/components/Panel.astro
git commit -m "feat(site): add Panel.astro (collapsible card with icon + badge slot)"
```

---

## Task 7: `PersonaSwitcher.astro` + `SessionBadge.astro`

**Files:**
- Create: `site/src/components/PersonaSwitcher.astro`
- Create: `site/src/components/SessionBadge.astro`

Two small client-hydrated widgets that read/write `localStorage` and live in the nav. Both render a static placeholder server-side then hydrate on `DOMContentLoaded`.

- [ ] **Step 1: Implement `site/src/components/PersonaSwitcher.astro`**

```astro
---
import Icon from './Icon.astro';
import { PERSONAS } from '../lib/personas';
---

<div class="relative inline-block" data-persona-switcher>
  <button
    type="button"
    class="btn-ghost gap-2 px-3 py-1.5 text-xs"
    data-persona-trigger
    aria-haspopup="listbox"
    aria-expanded="false"
  >
    <Icon name="eye" size={14} />
    <span data-persona-label class="font-mono uppercase tracking-wider">persona</span>
  </button>
  <ul
    class="absolute right-0 z-30 mt-2 hidden min-w-[16rem] rounded-xl border
           border-white/10 bg-ink-900/95 p-1 shadow-glow-sm backdrop-blur"
    data-persona-menu
    role="listbox"
  >
    {PERSONAS.map((p) => (
      <li>
        <button
          type="button"
          class="flex w-full flex-col items-start gap-0.5 rounded-lg px-3 py-2
                 text-left text-sm text-ink-200 hover:bg-white/5"
          data-persona-option={p.id}
          role="option"
        >
          <span class="font-display font-semibold text-white">{p.name}</span>
          <span class="text-xs text-ink-400">{p.tagline}</span>
        </button>
      </li>
    ))}
  </ul>
</div>

<script>
  import { getPersona, setPersona, type PersonaId } from '../lib/session';
  import { PERSONAS } from '../lib/personas';

  function init(): void {
    const root = document.querySelector('[data-persona-switcher]');
    if (!root) return;
    const trigger = root.querySelector<HTMLButtonElement>('[data-persona-trigger]');
    const menu = root.querySelector<HTMLElement>('[data-persona-menu]');
    const label = root.querySelector<HTMLElement>('[data-persona-label]');
    if (!trigger || !menu || !label) return;

    const refresh = (): void => {
      const id = getPersona();
      const spec = id ? PERSONAS.find((p) => p.id === id) : null;
      label.textContent = spec ? spec.name : 'choose persona';
    };
    refresh();

    trigger.addEventListener('click', () => {
      const open = !menu.classList.contains('hidden');
      menu.classList.toggle('hidden', open);
      trigger.setAttribute('aria-expanded', String(!open));
    });

    document.addEventListener('click', (ev) => {
      if (!root.contains(ev.target as Node)) {
        menu.classList.add('hidden');
        trigger.setAttribute('aria-expanded', 'false');
      }
    });

    for (const opt of root.querySelectorAll<HTMLButtonElement>(
      '[data-persona-option]',
    )) {
      opt.addEventListener('click', () => {
        const id = opt.dataset.personaOption as PersonaId | undefined;
        if (!id) return;
        setPersona(id);
        refresh();
        menu.classList.add('hidden');
        document.dispatchEvent(new CustomEvent('smadp:persona-changed', { detail: id }));
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
</script>
```

- [ ] **Step 2: Implement `site/src/components/SessionBadge.astro`**

```astro
---
import Icon from './Icon.astro';
---

<div class="flex items-center gap-2" data-session-badge>
  <span class="pill" data-session-ws>
    <Icon name="building" size={12} class="text-brand-300" />
    <span data-session-ws-label>no workspace</span>
  </span>
  <span class="pill" data-session-user>
    <Icon name="briefcase" size={12} class="text-cyber-400" />
    <span data-session-user-label>no user</span>
  </span>
</div>

<script>
  import { getUserId, getWorkspaceId } from '../lib/session';

  function refresh(): void {
    const ws = getWorkspaceId();
    const user = getUserId();
    const wsEl = document.querySelector<HTMLElement>('[data-session-ws-label]');
    const userEl = document.querySelector<HTMLElement>('[data-session-user-label]');
    if (wsEl) wsEl.textContent = ws ?? 'no workspace';
    if (userEl) userEl.textContent = user ?? 'no user';
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', refresh);
  } else {
    refresh();
  }
  document.addEventListener('smadp:session-changed', refresh);
</script>
```

- [ ] **Step 3: Type-check**

```bash
cd site && pnpm check
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add site/src/components/PersonaSwitcher.astro site/src/components/SessionBadge.astro
git commit -m "feat(site): add PersonaSwitcher + SessionBadge widgets"
```

---

## Task 8: Wire widgets into `Nav.astro` + add new top-level links

**Files:**
- Modify: `site/src/components/Nav.astro`

Add `Home` and `Workspaces` to the primary nav (between `agents` and `verdicts`), and inject the persona + session widgets into the existing action area on the right.

- [ ] **Step 1: Read the current Nav to confirm structure**

```bash
cd site && wc -l src/components/Nav.astro
```
Expected: ~110 lines.

- [ ] **Step 2: Edit `Nav.astro` — add imports**

At the top of the frontmatter (under existing imports — keep all of them), add:

```astro
import PersonaSwitcher from './PersonaSwitcher.astro';
import SessionBadge from './SessionBadge.astro';
```

- [ ] **Step 3: Edit `Nav.astro` — add `home` and `workspaces` to the primary nav**

Find the primary `<nav>` link list (the desktop one, contains `agents`, `matrix`, `verdicts`...). Insert two `<a>` elements at the start of that list:

```astro
<a href="/home" class="nav-link" data-nav-link="home">home</a>
<a href="/workspaces" class="nav-link" data-nav-link="workspaces">workspaces</a>
```

Use the same `class` and `data-nav-link` pattern that the existing links use. If the existing list uses a different class name, match it exactly — don't invent one.

- [ ] **Step 4: Edit `Nav.astro` — add widgets next to the existing action buttons**

Find the right-hand action group (the area that currently holds the search + submit buttons). Insert immediately before the existing buttons:

```astro
<SessionBadge />
<PersonaSwitcher />
```

- [ ] **Step 5: Edit `Nav.astro` — mirror new links in the mobile strip**

Find the mobile nav strip (the one rendered on small viewports — typically a horizontally scrolling list). Add `home` and `workspaces` to its link list using the same markup style as the existing mobile entries.

- [ ] **Step 6: Type-check + dev preview**

```bash
cd site && pnpm check
pnpm dev &  # optional
```
Expected: `pnpm check` passes; the dev server (if started) renders Nav with two new links and two new pills on the right.

- [ ] **Step 7: Commit**

```bash
git add site/src/components/Nav.astro
git commit -m "feat(site): wire Home + Workspaces links and session widgets into Nav"
```

---

## Task 9: `/home` — persona-switched landing page

**Files:**
- Create: `site/src/pages/home.astro`

Two states:
- **No persona set** — render the four persona tiles. Click sets persona + redirects to `/home`.
- **Persona set** — render the persona's panel grid (each panel is a `<Panel>` with a deep-link to the canonical surface).

Server-side renders the "no persona" view; client-side hydration swaps to the persona view if `localStorage.smadp.persona` is set.

- [ ] **Step 1: Implement the page**

```astro
---
import Layout from '../layouts/Layout.astro';
import Panel from '../components/Panel.astro';
import Icon from '../components/Icon.astro';
import { PERSONAS } from '../lib/personas';
---

<Layout title="Home — SMADP" description="Persona-switched dashboard for SMADP.">
  <section class="container-page mt-10">
    <span class="heading-eyebrow">Live dashboard</span>
    <h1 class="h1 mt-3 text-white">Welcome to SMADP</h1>
    <p class="lead mt-4 max-w-3xl">
      Choose how you'll be using the platform. We'll order the panels so the
      surfaces you need most are first; you can change persona any time from the
      header.
    </p>
  </section>

  <!-- No-persona view (server-rendered default) -->
  <section class="container-page mt-12 grid gap-6 sm:grid-cols-2" data-persona-tiles>
    {PERSONAS.map((p) => (
      <button
        type="button"
        class="card card-hover text-left"
        data-persona-pick={p.id}
      >
        <div class="flex items-center gap-3">
          <Icon name="eye" size={22} class="text-brand-300" />
          <h2 class="h3 text-white">{p.name}</h2>
        </div>
        <p class="mt-3 text-sm text-ink-300">{p.tagline}</p>
        <div class="mt-4 flex flex-wrap gap-1.5">
          {p.panels.map((k) => (
            <span class="pill">{k.replace(/_/g, ' ')}</span>
          ))}
        </div>
      </button>
    ))}
  </section>

  <!-- Persona view (hydrated when localStorage.smadp.persona is set) -->
  <section class="container-page mt-12 hidden space-y-4" data-persona-view>
    <header class="flex flex-wrap items-baseline justify-between gap-3">
      <h2 class="h2 text-white" data-persona-heading>Your dashboard</h2>
      <button
        type="button"
        class="btn-ghost text-xs"
        data-persona-clear
      >
        change persona
      </button>
    </header>
    <div class="grid gap-4" data-persona-panels></div>
  </section>
</Layout>

<script>
  import { clearPersona, getPersona, setPersona, type PersonaId } from '../lib/session';
  import { getPersonaSpec, type PanelKey } from '../lib/personas';

  const PANEL_LINKS: Record<PanelKey, { title: string; href: string; hint: string }> = {
    exec_summary: {
      title: 'Exec summary',
      href: '/workspaces#exec-summary',
      hint: 'One-page traffic-light verdict.',
    },
    deployments: {
      title: 'Deployments',
      href: '/workspaces#deployments',
      hint: 'All agent pairs in this workspace.',
    },
    framework_coverage: {
      title: 'Framework coverage',
      href: '/frameworks',
      hint: '11 frameworks, controls × verdicts.',
    },
    refresh_freshness: {
      title: 'Refresh freshness',
      href: '/refresh',
      hint: 'Queue + 90-day TTL bands.',
    },
    disputes: {
      title: 'Disputes',
      href: '/workspaces#disputes',
      hint: 'Two-stage triage, 5-day SLA.',
    },
    transparency: {
      title: 'Transparency log',
      href: '/chronicle',
      hint: 'Append-only signed events.',
    },
    vendor_responses: {
      title: 'Vendor responses',
      href: '/workspaces#vendor-responses',
      hint: 'Claimed-vendor commentary on verdicts.',
    },
    webhooks: {
      title: 'Webhooks',
      href: '/webhooks',
      hint: 'Subscriptions + delivery state.',
    },
    passports: {
      title: 'Passports',
      href: '/passports',
      hint: 'Signed HTML, verifiable offline.',
    },
  };

  function render(): void {
    const tiles = document.querySelector<HTMLElement>('[data-persona-tiles]');
    const view = document.querySelector<HTMLElement>('[data-persona-view]');
    const heading = document.querySelector<HTMLElement>('[data-persona-heading]');
    const grid = document.querySelector<HTMLElement>('[data-persona-panels]');
    if (!tiles || !view || !heading || !grid) return;

    const id = getPersona();
    if (!id) {
      tiles.classList.remove('hidden');
      view.classList.add('hidden');
      return;
    }
    const spec = getPersonaSpec(id);
    tiles.classList.add('hidden');
    view.classList.remove('hidden');
    heading.textContent = `${spec.name} — your dashboard`;
    grid.innerHTML = spec.panels
      .map((k) => {
        const meta = PANEL_LINKS[k];
        return `
          <a href="${meta.href}" class="card card-hover block">
            <div class="font-display text-base font-semibold text-white">${meta.title}</div>
            <p class="mt-1 text-sm text-ink-300">${meta.hint}</p>
          </a>
        `;
      })
      .join('');
  }

  function bindTiles(): void {
    for (const btn of document.querySelectorAll<HTMLButtonElement>('[data-persona-pick]')) {
      btn.addEventListener('click', () => {
        const id = btn.dataset.personaPick as PersonaId | undefined;
        if (!id) return;
        setPersona(id);
        render();
        document.dispatchEvent(new CustomEvent('smadp:persona-changed', { detail: id }));
      });
    }
    const clearBtn = document.querySelector<HTMLButtonElement>('[data-persona-clear]');
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        clearPersona();
        render();
      });
    }
  }

  function init(): void {
    bindTiles();
    render();
    document.addEventListener('smadp:persona-changed', render);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
</script>
```

- [ ] **Step 2: Type-check**

```bash
cd site && pnpm check
```
Expected: PASS.

- [ ] **Step 3: Manual smoke (dev server)**

```bash
cd site && pnpm dev
```
Visit `http://localhost:4321/home`. Verify:
1. Four persona tiles render.
2. Clicking one swaps to the persona view.
3. Reload preserves the persona view (localStorage).
4. "change persona" button returns to the tile view.

- [ ] **Step 4: Commit**

```bash
git add site/src/pages/home.astro
git commit -m "feat(site): add /home persona-switched landing"
```

---

## Task 10: `/workspaces` — picker + active-workspace dashboard

**Files:**
- Create: `site/src/pages/workspaces.astro`

Single static page. Renders:
1. **Workspace picker** — fetches `/workspaces` (list), lets the user pick one (sets `localStorage.smadp.workspace`), and an inline form for `user_id` (sets `localStorage.smadp.user`).
2. **Dashboard** — once both are set, renders 5 collapsible panels (`exec_summary`, `deployments`, `framework_coverage`, `refresh_freshness`, `disputes`) by fetching the relevant endpoints.

Persona drives default-open state for each panel (persona's first 2 panels open, the rest collapsed).

- [ ] **Step 1: Implement the page**

```astro
---
import Layout from '../layouts/Layout.astro';
import Panel from '../components/Panel.astro';
import Icon from '../components/Icon.astro';
---

<Layout title="Workspace dashboard — SMADP" description="Live workspace dashboard.">
  <section class="container-page mt-10">
    <span class="heading-eyebrow">Workspace</span>
    <h1 class="h1 mt-3 text-white">Workspace dashboard</h1>
    <p class="lead mt-4 max-w-3xl">
      Pick a workspace and tell us who you are; the panels below populate live
      from the FastAPI backend.
    </p>
  </section>

  <!-- Picker -->
  <section class="container-page mt-10">
    <div class="card">
      <h2 class="h3 text-white">Pick workspace + user</h2>
      <form class="mt-5 grid gap-4 sm:grid-cols-3" data-ws-picker>
        <label class="text-sm text-ink-300">
          Workspace
          <select
            name="ws"
            class="mt-1 w-full rounded-lg border border-white/10 bg-ink-900/60 px-3 py-2 text-sm text-white"
            data-ws-select
          >
            <option value="">— loading —</option>
          </select>
        </label>
        <label class="text-sm text-ink-300">
          User id
          <input
            type="text"
            name="user"
            placeholder="user_alice"
            class="mt-1 w-full rounded-lg border border-white/10 bg-ink-900/60 px-3 py-2 font-mono text-sm text-white"
            data-ws-user
          />
        </label>
        <div class="flex items-end">
          <button type="submit" class="btn-primary w-full">apply</button>
        </div>
      </form>
      <p class="mt-3 text-xs text-ink-500" data-ws-status>not loaded yet</p>
    </div>
  </section>

  <!-- Dashboard -->
  <section class="container-page mt-10 hidden space-y-4" data-ws-dashboard>
    <Panel title="Exec summary" icon="zap" id="exec-summary">
      <div data-panel="exec_summary">loading…</div>
    </Panel>
    <Panel title="Deployments" icon="layers" id="deployments">
      <div data-panel="deployments">loading…</div>
    </Panel>
    <Panel title="Framework coverage" icon="shield" id="framework-coverage">
      <div data-panel="framework_coverage">loading…</div>
    </Panel>
    <Panel title="Refresh freshness" icon="refresh" id="refresh-freshness">
      <div data-panel="refresh_freshness">loading…</div>
    </Panel>
    <Panel title="Disputes" icon="gavel" id="disputes">
      <div data-panel="disputes">loading…</div>
    </Panel>
    <Panel title="Vendor responses" icon="briefcase" id="vendor-responses" defaultOpen={false}>
      <div data-panel="vendor_responses">loading…</div>
    </Panel>
  </section>
</Layout>

<script>
  import { apiFetch, ApiError } from '../lib/api';
  import {
    getWorkspaceId,
    getUserId,
    setWorkspaceId,
    setUserId,
  } from '../lib/session';

  type Workspace = { id: string; name: string; plan: string };
  type Member = { workspace_id: string; user_id: string; role: string };

  const fmt = (n: number, d = 2): string => n.toFixed(d);

  function escapeHtml(s: string): string {
    return s.replace(/[&<>"']/g, (c) => {
      switch (c) {
        case '&': return '&amp;';
        case '<': return '&lt;';
        case '>': return '&gt;';
        case '"': return '&quot;';
        default: return '&#39;';
      }
    });
  }

  function setPanelHtml(key: string, html: string): void {
    const el = document.querySelector<HTMLElement>(`[data-panel="${key}"]`);
    if (el) el.innerHTML = html;
  }

  async function loadWorkspaces(select: HTMLSelectElement): Promise<void> {
    try {
      const list = await apiFetch<Workspace[]>('/workspaces');
      const current = getWorkspaceId();
      select.innerHTML =
        '<option value="">— pick workspace —</option>' +
        list
          .map(
            (w) =>
              `<option value="${escapeHtml(w.id)}" ${w.id === current ? 'selected' : ''}>${escapeHtml(w.name)} — ${escapeHtml(w.id)}</option>`,
          )
          .join('');
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err);
      select.innerHTML = `<option value="">load failed: ${escapeHtml(msg)}</option>`;
    }
  }

  async function loadDeployments(): Promise<void> {
    type Verdict = {
      verdict_id: string;
      pair: [string, string];
      composite_score: number;
      headline: string;
      generated_at: string;
    };
    try {
      const list = await apiFetch<Verdict[]>('/verdicts');
      if (list.length === 0) {
        setPanelHtml('deployments', '<p class="text-sm text-ink-400">No verdicts yet.</p>');
        return;
      }
      setPanelHtml(
        'deployments',
        `
        <table class="table-zebra w-full text-sm">
          <thead class="text-left font-mono text-[11px] uppercase tracking-wider text-ink-400">
            <tr><th class="px-3 py-2">Pair</th><th class="px-3 py-2">Composite</th><th class="px-3 py-2">Generated</th></tr>
          </thead>
          <tbody>
            ${list
              .slice(0, 25)
              .map(
                (v) => `
              <tr class="border-t border-white/5">
                <td class="px-3 py-2"><a class="link-quiet" href="/verdicts/${escapeHtml(v.verdict_id)}">${escapeHtml(v.pair[0])} × ${escapeHtml(v.pair[1])}</a></td>
                <td class="px-3 py-2 font-mono">${fmt(v.composite_score)}</td>
                <td class="px-3 py-2 font-mono text-xs text-ink-400">${escapeHtml(v.generated_at.slice(0, 10))}</td>
              </tr>`,
              )
              .join('')}
          </tbody>
        </table>`,
      );
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err);
      setPanelHtml('deployments', `<p class="text-sm text-amber-300">${escapeHtml(msg)}</p>`);
    }
  }

  async function loadFrameworks(): Promise<void> {
    type FwResp = { frameworks: Array<{ id: string; name: string; controls: Array<{ id: string; verdicts: string[] }> }> };
    try {
      const data = await apiFetch<FwResp>('/frameworks');
      setPanelHtml(
        'framework_coverage',
        `
        <ul class="grid gap-2 sm:grid-cols-2">
          ${data.frameworks
            .map((fw) => {
              const total = fw.controls.length;
              const touched = fw.controls.filter((c) => c.verdicts.length > 0).length;
              return `
                <li class="rounded-lg border border-white/5 bg-ink-950/40 p-3">
                  <a class="font-display text-sm font-semibold text-white hover:text-brand-200" href="/frameworks/${escapeHtml(fw.id)}">${escapeHtml(fw.name)}</a>
                  <div class="mt-1 font-mono text-xs text-ink-400">${touched}/${total} controls touched</div>
                </li>`;
            })
            .join('')}
        </ul>`,
      );
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err);
      setPanelHtml('framework_coverage', `<p class="text-sm text-amber-300">${escapeHtml(msg)}</p>`);
    }
  }

  async function loadRefresh(): Promise<void> {
    type QueueItem = { id: number; verdict_id: string; trigger: string; enqueued_at: string; claimed_at: string | null };
    try {
      const list = await apiFetch<QueueItem[]>('/refresh/queue');
      if (list.length === 0) {
        setPanelHtml('refresh_freshness', '<p class="text-sm text-ink-400">Queue is idle.</p>');
        return;
      }
      setPanelHtml(
        'refresh_freshness',
        `
        <ul class="space-y-2">
          ${list
            .map(
              (q) => `
            <li class="flex items-center justify-between gap-3 rounded-lg border border-white/5 bg-ink-950/40 px-3 py-2">
              <span class="font-mono text-xs text-ink-200">${escapeHtml(q.verdict_id)}</span>
              <span class="pill">${escapeHtml(q.trigger)}</span>
              <span class="font-mono text-[11px] text-ink-500">${q.claimed_at ? 'in flight' : 'queued'}</span>
            </li>`,
            )
            .join('')}
        </ul>`,
      );
    } catch (err) {
      // /refresh/queue may not exist — render a hint linking to /refresh
      setPanelHtml(
        'refresh_freshness',
        '<p class="text-sm text-ink-400">See <a class="link-quiet" href="/refresh">/refresh</a> for queue + state.</p>',
      );
    }
  }

  async function loadDisputes(): Promise<void> {
    type Dispute = {
      id: string;
      verdict_id: string;
      status: string;
      filed_at: string;
      requested_outcome: string;
    };
    try {
      const list = await apiFetch<Dispute[]>('/vendor/disputes');
      if (list.length === 0) {
        setPanelHtml('disputes', '<p class="text-sm text-ink-400">No disputes filed.</p>');
        return;
      }
      setPanelHtml(
        'disputes',
        `
        <ul class="space-y-2">
          ${list
            .map(
              (d) => `
            <li class="rounded-lg border border-white/5 bg-ink-950/40 p-3">
              <div class="flex items-center justify-between gap-3">
                <span class="font-mono text-xs text-ink-200">${escapeHtml(d.verdict_id)}</span>
                <span class="pill">${escapeHtml(d.status)}</span>
              </div>
              <div class="mt-1 font-mono text-[11px] text-ink-500">filed ${escapeHtml(d.filed_at.slice(0, 10))} · requested ${escapeHtml(d.requested_outcome)}</div>
            </li>`,
            )
            .join('')}
        </ul>`,
      );
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err);
      setPanelHtml('disputes', `<p class="text-sm text-amber-300">${escapeHtml(msg)}</p>`);
    }
  }

  async function loadVendorResponses(): Promise<void> {
    setPanelHtml(
      'vendor_responses',
      '<p class="text-sm text-ink-400">Vendor commentary appears on each verdict; see /verdicts.</p>',
    );
  }

  async function loadExecSummary(): Promise<void> {
    type Verdict = { composite_score: number; pair: [string, string] };
    try {
      const list = await apiFetch<Verdict[]>('/verdicts');
      const total = list.length;
      const high = list.filter((v) => v.composite_score >= 0.6).length;
      const medium = list.filter((v) => v.composite_score >= 0.3 && v.composite_score < 0.6).length;
      const low = total - high - medium;
      setPanelHtml(
        'exec_summary',
        `
        <div class="grid gap-3 sm:grid-cols-3">
          <div class="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-4 text-center">
            <div class="font-mono text-[10px] uppercase tracking-wider text-emerald-300">Low risk</div>
            <div class="mt-1 font-display text-3xl font-extrabold text-emerald-300">${low}</div>
          </div>
          <div class="rounded-lg border border-amber-500/20 bg-amber-500/5 p-4 text-center">
            <div class="font-mono text-[10px] uppercase tracking-wider text-amber-300">Medium</div>
            <div class="mt-1 font-display text-3xl font-extrabold text-amber-300">${medium}</div>
          </div>
          <div class="rounded-lg border border-rose-500/20 bg-rose-500/5 p-4 text-center">
            <div class="font-mono text-[10px] uppercase tracking-wider text-rose-300">High</div>
            <div class="mt-1 font-display text-3xl font-extrabold text-rose-300">${high}</div>
          </div>
        </div>`,
      );
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err);
      setPanelHtml('exec_summary', `<p class="text-sm text-amber-300">${escapeHtml(msg)}</p>`);
    }
  }

  async function refreshAll(): Promise<void> {
    await Promise.all([
      loadExecSummary(),
      loadDeployments(),
      loadFrameworks(),
      loadRefresh(),
      loadDisputes(),
      loadVendorResponses(),
    ]);
  }

  function showDashboard(visible: boolean): void {
    const dash = document.querySelector<HTMLElement>('[data-ws-dashboard]');
    if (dash) dash.classList.toggle('hidden', !visible);
  }

  async function init(): Promise<void> {
    const form = document.querySelector<HTMLFormElement>('[data-ws-picker]');
    const select = document.querySelector<HTMLSelectElement>('[data-ws-select]');
    const userInput = document.querySelector<HTMLInputElement>('[data-ws-user]');
    const status = document.querySelector<HTMLElement>('[data-ws-status]');
    if (!form || !select || !userInput || !status) return;

    await loadWorkspaces(select);
    const ws = getWorkspaceId();
    const user = getUserId();
    if (ws) select.value = ws;
    if (user) userInput.value = user;
    if (ws && user) {
      status.textContent = `applied: workspace=${ws}, user=${user}`;
      showDashboard(true);
      void refreshAll();
    }

    form.addEventListener('submit', (ev) => {
      ev.preventDefault();
      const wsVal = select.value.trim();
      const userVal = userInput.value.trim();
      if (!wsVal || !userVal) {
        status.textContent = 'pick a workspace and enter a user id';
        return;
      }
      setWorkspaceId(wsVal);
      setUserId(userVal);
      status.textContent = `applied: workspace=${wsVal}, user=${userVal}`;
      document.dispatchEvent(new Event('smadp:session-changed'));
      showDashboard(true);
      void refreshAll();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    void init();
  }
</script>
```

- [ ] **Step 2: Type-check**

```bash
cd site && pnpm check
```
Expected: PASS.

- [ ] **Step 3: Manual smoke**

In one terminal:
```bash
SMADP_KEK_MASTER=$(printf 'x%.0s' {1..64}) python -m uvicorn smadp.api.server:app --reload
```
In another:
```bash
cd site && pnpm dev
```
Open `http://localhost:4321/workspaces`, pick a workspace (create one first via the API if none exist), enter `user_alice`, click `apply`. Verify each panel renders without console errors.

- [ ] **Step 4: Commit**

```bash
git add site/src/pages/workspaces.astro
git commit -m "feat(site): add /workspaces dashboard (5 collapsible panels, runtime fetch)"
```

---

## Task 11: `/frameworks/[id]` — per-framework deep view

**Files:**
- Create: `site/src/pages/frameworks/[id].astro`
- Modify: `site/src/pages/frameworks.astro`

`getStaticPaths()` reads the 11 frameworks at build time; the page renders a per-framework controls table with risks + verdict crosslinks (already computed by the build-time loader). Heading on the existing `/frameworks` index becomes a link to the deep view.

- [ ] **Step 1: Create `site/src/pages/frameworks/[id].astro`**

```astro
---
import Layout from '../../layouts/Layout.astro';
import Panel from '../../components/Panel.astro';
import FrameworkBadge from '../../components/FrameworkBadge.astro';
import RiskBadge from '../../components/RiskBadge.astro';
import { getFrameworks, getVerdictsForControl } from '../../data/catalog';
import type { RiskId } from '../../data/types';

export function getStaticPaths() {
  const { frameworks } = getFrameworks();
  return frameworks.map((fw) => ({ params: { id: fw.id }, props: { fw } }));
}

const { fw } = Astro.props as { fw: ReturnType<typeof getFrameworks>['frameworks'][number] };
const totalControls = fw.controls.length;
const touched = fw.controls.filter((c) => getVerdictsForControl(c.id).length > 0).length;
---

<Layout title={`${fw.name} — Frameworks — SMADP`} description={`Controls for ${fw.name}.`}>
  <section class="container-page mt-10">
    <a href="/frameworks" class="font-mono text-xs text-ink-400 hover:text-brand-300">← all frameworks</a>
    <span class="mt-6 block heading-eyebrow">{fw.id}</span>
    <h1 class="h1 mt-3 text-white">{fw.name}</h1>
    <p class="lead mt-3 max-w-3xl">version {fw.version} · {touched}/{totalControls} controls touched by published verdicts</p>
    <a class="btn-ghost mt-4 inline-flex" href={fw.url}>Source ↗</a>
  </section>

  <section class="container-page mt-10 space-y-4">
    {fw.controls.map((c) => {
      const verdicts = getVerdictsForControl(c.id);
      return (
        <Panel
          title={c.name}
          icon="shield"
          id={c.id}
          defaultOpen={verdicts.length > 0}
        >
          <div class="flex flex-wrap items-center gap-2">
            <FrameworkBadge framework={fw.id} control={c.id} />
            {c.applies_to_risks.map((r: RiskId) => <RiskBadge risk={r} />)}
          </div>
          {verdicts.length === 0 ? (
            <p class="mt-3 text-sm text-ink-400">No verdicts touch this control yet.</p>
          ) : (
            <ul class="mt-3 space-y-1 text-sm">
              {verdicts.map((v) => (
                <li>
                  <a class="link-quiet" href={`/verdicts/${v.verdict_id}`}>
                    {v.pair[0]} × {v.pair[1]} — composite {v.composite_score.toFixed(2)}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      );
    })}
  </section>
</Layout>
```

- [ ] **Step 2: Patch `site/src/pages/frameworks.astro` — link the heading to the deep view**

In the existing list, find this block:

```astro
<header class="flex flex-wrap items-end justify-between gap-3">
  <div>
    <span class="heading-eyebrow">{fw.id}</span>
    <h2 class="h2 mt-1 text-white">{fw.name}</h2>
```

Replace `<h2 class="h2 mt-1 text-white">{fw.name}</h2>` with:

```astro
<h2 class="h2 mt-1 text-white">
  <a class="hover:text-brand-200" href={`/frameworks/${fw.id}`}>{fw.name}</a>
</h2>
```

- [ ] **Step 3: Type-check + build**

```bash
cd site && pnpm check && pnpm build
```
Expected: build succeeds; output should include 11 framework deep-view pages.

- [ ] **Step 4: Commit**

```bash
git add site/src/pages/frameworks/ site/src/pages/frameworks.astro
git commit -m "feat(site): add /frameworks/[id] deep view + link from index"
```

---

## Task 12: `/passports` — passport viewer shell

**Files:**
- Create: `site/src/pages/passports.astro`

Static page; reads `?slug=a__b` from the URL, fetches the signed HTML from the FastAPI passport endpoint with workspace headers, and renders it inside a sandboxed `<iframe srcdoc>`. Falls back to a slug input form if no slug is provided. Provides a "download" button for offline verification (`smadp passport verify foo.html`).

- [ ] **Step 1: Implement the page**

```astro
---
import Layout from '../layouts/Layout.astro';
import Panel from '../components/Panel.astro';
import Icon from '../components/Icon.astro';
---

<Layout title="Passport viewer — SMADP" description="Verifiable signed verdict passports.">
  <section class="container-page mt-10">
    <span class="heading-eyebrow">Passport</span>
    <h1 class="h1 mt-3 text-white">Verifiable verdict passport</h1>
    <p class="lead mt-4 max-w-3xl">
      Each passport is a single self-contained signed HTML file that any auditor
      can verify offline.
    </p>
  </section>

  <section class="container-page mt-10">
    <Panel title="Open a passport" icon="file-text" defaultOpen={true}>
      <form class="grid gap-3 sm:grid-cols-[1fr_auto]" data-passport-form>
        <input
          type="text"
          name="slug"
          placeholder="anthropic__claude-research__openai__swe-agent"
          class="rounded-lg border border-white/10 bg-ink-900/60 px-3 py-2 font-mono text-sm text-white"
          data-passport-slug
          required
        />
        <button type="submit" class="btn-primary">load</button>
      </form>
      <p class="mt-2 text-xs text-ink-500">
        Slug format: <code class="font-mono">{`<a-namespace>__<a-name>__<b-namespace>__<b-name>`}</code>.
      </p>
    </Panel>
  </section>

  <section class="container-page mt-6 hidden" data-passport-result>
    <Panel title="Passport" icon="shield" defaultOpen={true}>
      <div class="flex items-center justify-between gap-3">
        <span class="font-mono text-xs text-ink-400" data-passport-meta></span>
        <button type="button" class="btn-ghost text-xs" data-passport-download>
          download .html
        </button>
      </div>
      <iframe
        title="passport"
        sandbox="allow-same-origin"
        class="mt-4 h-[70vh] w-full rounded-lg border border-white/10 bg-white"
        data-passport-frame
      ></iframe>
    </Panel>
  </section>
</Layout>

<script>
  import { apiFetch, ApiError } from '../lib/api';

  function splitSlug(slug: string): [string, string] {
    const parts = slug.split('__');
    if (parts.length !== 4) {
      throw new Error('slug must be <a-ns>__<a-name>__<b-ns>__<b-name> (4 segments)');
    }
    return [`${parts[0]}__${parts[1]}`, `${parts[2]}__${parts[3]}`];
  }

  async function load(slug: string): Promise<void> {
    const [a, b] = splitSlug(slug);
    const html = await apiFetch<string>(`/passports/${a}/${b}.html`, { accept: 'text/html' });
    const result = document.querySelector<HTMLElement>('[data-passport-result]');
    const frame = document.querySelector<HTMLIFrameElement>('[data-passport-frame]');
    const meta = document.querySelector<HTMLElement>('[data-passport-meta]');
    const download = document.querySelector<HTMLButtonElement>('[data-passport-download]');
    if (!result || !frame || !meta || !download) return;
    result.classList.remove('hidden');
    frame.srcdoc = html;
    meta.textContent = `${a} × ${b}`;
    download.onclick = (): void => {
      const blob = new Blob([html], { type: 'text/html' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${slug}.html`;
      link.click();
      URL.revokeObjectURL(url);
    };
  }

  function init(): void {
    const form = document.querySelector<HTMLFormElement>('[data-passport-form]');
    const slugInput = document.querySelector<HTMLInputElement>('[data-passport-slug]');
    if (!form || !slugInput) return;

    const fromUrl = new URLSearchParams(window.location.search).get('slug');
    if (fromUrl) {
      slugInput.value = fromUrl;
      load(fromUrl).catch((err) => {
        const msg = err instanceof ApiError ? err.message : String(err);
        alert(`load failed: ${msg}`);
      });
    }

    form.addEventListener('submit', (ev) => {
      ev.preventDefault();
      const slug = slugInput.value.trim();
      if (!slug) return;
      const url = new URL(window.location.href);
      url.searchParams.set('slug', slug);
      history.replaceState(null, '', url.toString());
      load(slug).catch((err) => {
        const msg = err instanceof ApiError ? err.message : String(err);
        alert(`load failed: ${msg}`);
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
</script>
```

- [ ] **Step 2: Type-check**

```bash
cd site && pnpm check
```
Expected: PASS.

- [ ] **Step 3: Manual smoke**

With API + dev server running and a workspace + user set in `localStorage`, visit `/passports?slug=<a-ns>__<a-name>__<b-ns>__<b-name>` for a known verdict. Verify the iframe renders the signed HTML, and `download .html` produces a file.

- [ ] **Step 4: Commit**

```bash
git add site/src/pages/passports.astro
git commit -m "feat(site): add /passports viewer (sandboxed iframe + download)"
```

---

## Task 13: `/vendor/[agent]` — claimed-vendor surface

**Files:**
- Create: `site/src/pages/vendor/[agent].astro`

Per-agent page (build-time `getStaticPaths` from the existing profiles loader). Three collapsible panels:
1. **Claim status** — list claims for this agent, lets user start a new claim (`POST /vendor/claims`), see token + verification instructions, and verify.
2. **Vendor responses** — list `vendor_responses` for verdicts touching this agent.
3. **File a dispute** — form posting to `/vendor/disputes`.

All actions require `X-SMADP-Workspace` + `X-SMADP-User` (set via `/workspaces`).

- [ ] **Step 1: Implement the page**

```astro
---
import Layout from '../../layouts/Layout.astro';
import Panel from '../../components/Panel.astro';
import Icon from '../../components/Icon.astro';
import { getProfiles, getVerdicts } from '../../data/catalog';

export function getStaticPaths() {
  return getProfiles().map((p) => ({
    params: { agent: p.slug },
    props: { profile: p },
  }));
}

const { profile } = Astro.props as { profile: ReturnType<typeof getProfiles>[number] };
const slug = profile.slug;
const myVerdicts = getVerdicts().filter(
  (v) => v.pair[0] === slug || v.pair[1] === slug,
);
---

<Layout title={`${profile.name} — Vendor — SMADP`} description={`Vendor surface for ${profile.name}.`}>
  <section class="container-page mt-10">
    <a href="/agents" class="font-mono text-xs text-ink-400 hover:text-brand-300">← all agents</a>
    <span class="mt-6 block heading-eyebrow">Claimed vendor surface</span>
    <h1 class="h1 mt-3 text-white">{profile.name}</h1>
    <p class="lead mt-3 max-w-3xl">
      Claim this agent to post responses on its verdicts and file disputes.
    </p>
  </section>

  <section class="container-page mt-10 space-y-4" data-vendor-root data-agent-id={slug}>
    <Panel title="Claim status" icon="check-circle" defaultOpen={true}>
      <div data-panel="claims">loading…</div>
      <details class="mt-4">
        <summary class="cursor-pointer font-mono text-xs text-brand-300">start a new claim</summary>
        <form class="mt-3 grid gap-3 sm:grid-cols-[1fr_auto]" data-claim-form>
          <select
            name="method"
            class="rounded-lg border border-white/10 bg-ink-900/60 px-3 py-2 text-sm text-white"
          >
            <option value="repo">repo file</option>
            <option value="dns">DNS TXT</option>
            <option value="email">email magic-link</option>
          </select>
          <button type="submit" class="btn-primary">create</button>
        </form>
        <pre class="mt-3 hidden whitespace-pre-wrap rounded-lg border border-white/5 bg-ink-950/40 p-3 font-mono text-[11px] text-ink-200" data-claim-instructions></pre>
      </details>
    </Panel>

    <Panel title="Vendor responses" icon="briefcase" defaultOpen={true}>
      <div data-panel="responses">loading…</div>
    </Panel>

    <Panel title="File a dispute" icon="gavel" defaultOpen={false}>
      <form class="grid gap-3" data-dispute-form>
        <label class="text-sm text-ink-300">
          Verdict
          <select
            name="verdict"
            class="mt-1 w-full rounded-lg border border-white/10 bg-ink-900/60 px-3 py-2 text-sm text-white"
          >
            {myVerdicts.map((v) => (
              <option value={v.verdict_id}>{v.pair[0]} × {v.pair[1]}</option>
            ))}
          </select>
        </label>
        <label class="text-sm text-ink-300">
          Argument (markdown)
          <textarea
            name="argument"
            rows="6"
            class="mt-1 w-full rounded-lg border border-white/10 bg-ink-900/60 px-3 py-2 font-mono text-sm text-white"
            placeholder="The verdict overstates risk because..."
            required
          ></textarea>
        </label>
        <label class="text-sm text-ink-300">
          Requested outcome
          <select
            name="outcome"
            class="mt-1 w-full rounded-lg border border-white/10 bg-ink-900/60 px-3 py-2 text-sm text-white"
          >
            <option value="reeval">re-evaluate</option>
            <option value="amend">amend</option>
            <option value="withdraw">withdraw</option>
          </select>
        </label>
        <button type="submit" class="btn-primary">file dispute</button>
      </form>
      <p class="mt-2 text-xs text-ink-500" data-dispute-status></p>
    </Panel>
  </section>
</Layout>

<script>
  import { apiFetch, ApiError } from '../../lib/api';

  function escapeHtml(s: string): string {
    return s.replace(/[&<>"']/g, (c) => {
      switch (c) {
        case '&': return '&amp;';
        case '<': return '&lt;';
        case '>': return '&gt;';
        case '"': return '&quot;';
        default: return '&#39;';
      }
    });
  }

  async function loadClaims(agentId: string): Promise<void> {
    const target = document.querySelector<HTMLElement>('[data-panel="claims"]');
    if (!target) return;
    try {
      const list = await apiFetch<Array<{ id: string; method: string; status: string }>>(
        `/vendor/claims?agent_id=${encodeURIComponent(agentId)}`,
      );
      target.innerHTML = list.length === 0
        ? '<p class="text-sm text-ink-400">No claims for this agent.</p>'
        : `<ul class="space-y-1">${list
            .map(
              (c) =>
                `<li class="font-mono text-xs text-ink-200">${escapeHtml(c.id)} — ${escapeHtml(c.method)} — <span class="pill">${escapeHtml(c.status)}</span></li>`,
            )
            .join('')}</ul>`;
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err);
      target.innerHTML = `<p class="text-sm text-amber-300">${escapeHtml(msg)}</p>`;
    }
  }

  async function loadResponses(agentId: string): Promise<void> {
    const target = document.querySelector<HTMLElement>('[data-panel="responses"]');
    if (!target) return;
    try {
      // The backend takes verdict_id; cycle through the agent's verdicts on the page.
      const links = Array.from(
        document.querySelectorAll<HTMLOptionElement>('[data-dispute-form] option'),
      ).map((o) => o.value);
      const all: Array<{ id: string; verdict_id: string; body_md: string }> = [];
      for (const verdictId of links) {
        try {
          const list = await apiFetch<typeof all>(
            `/vendor/responses?verdict_id=${encodeURIComponent(verdictId)}`,
          );
          all.push(...list);
        } catch {
          // skip individual failures
        }
      }
      target.innerHTML = all.length === 0
        ? '<p class="text-sm text-ink-400">No vendor responses yet.</p>'
        : all
            .map(
              (r) => `
            <article class="rounded-lg border border-white/5 bg-ink-950/40 p-3">
              <div class="font-mono text-[11px] text-ink-400">on ${escapeHtml(r.verdict_id)}</div>
              <p class="mt-2 whitespace-pre-wrap text-sm text-ink-200">${escapeHtml(r.body_md)}</p>
            </article>`,
            )
            .join('');
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err);
      target.innerHTML = `<p class="text-sm text-amber-300">${escapeHtml(msg)}</p>`;
    }
  }

  function bindClaimForm(agentId: string): void {
    const form = document.querySelector<HTMLFormElement>('[data-claim-form]');
    const out = document.querySelector<HTMLElement>('[data-claim-instructions]');
    if (!form || !out) return;
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const fd = new FormData(form);
      const method = String(fd.get('method'));
      try {
        const res = await apiFetch<{
          claim: { id: string; status: string };
          token: string;
          instructions: { text: string; magic_link_url: string | null };
        }>('/vendor/claims', {
          method: 'POST',
          json: { agent_id: agentId, method },
        });
        out.classList.remove('hidden');
        out.textContent =
          `claim ${res.claim.id} (${res.claim.status})\n` +
          `token: ${res.token}\n\n${res.instructions.text}` +
          (res.instructions.magic_link_url ? `\n\nmagic link: ${res.instructions.magic_link_url}` : '');
        await loadClaims(agentId);
      } catch (err) {
        out.classList.remove('hidden');
        out.textContent = err instanceof ApiError ? err.message : String(err);
      }
    });
  }

  function bindDisputeForm(agentId: string): void {
    const form = document.querySelector<HTMLFormElement>('[data-dispute-form]');
    const status = document.querySelector<HTMLElement>('[data-dispute-status]');
    if (!form || !status) return;
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const fd = new FormData(form);
      try {
        const res = await apiFetch<{ id: string; status: string }>('/vendor/disputes', {
          method: 'POST',
          json: {
            verdict_id: String(fd.get('verdict')),
            agent_id: agentId,
            argument_md: String(fd.get('argument')),
            requested_outcome: String(fd.get('outcome')),
          },
        });
        status.textContent = `filed: ${res.id} (${res.status})`;
        form.reset();
      } catch (err) {
        status.textContent = err instanceof ApiError ? err.message : String(err);
      }
    });
  }

  function init(): void {
    const root = document.querySelector<HTMLElement>('[data-vendor-root]');
    if (!root) return;
    const agentId = root.dataset.agentId ?? '';
    bindClaimForm(agentId);
    bindDisputeForm(agentId);
    void loadClaims(agentId);
    void loadResponses(agentId);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
</script>
```

- [ ] **Step 2: Type-check + build**

```bash
cd site && pnpm check && pnpm build
```
Expected: build succeeds; per-agent vendor pages are generated.

- [ ] **Step 3: Commit**

```bash
git add site/src/pages/vendor/
git commit -m "feat(site): add /vendor/[agent] (claim + responses + dispute)"
```

---

## Task 14: `/refresh` and `/webhooks` admin pages

**Files:**
- Create: `site/src/pages/refresh.astro`
- Create: `site/src/pages/webhooks.astro`

Two simple admin pages. `/refresh` polls the queue + per-verdict state; `/webhooks` lists subscriptions, lets the user create new ones, and surfaces the secret on creation (one-time reveal).

- [ ] **Step 1: Implement `site/src/pages/refresh.astro`**

```astro
---
import Layout from '../layouts/Layout.astro';
import Panel from '../components/Panel.astro';
import Icon from '../components/Icon.astro';
---

<Layout title="Refresh — SMADP" description="Refresh queue and freshness state.">
  <section class="container-page mt-10">
    <span class="heading-eyebrow">Refresh</span>
    <h1 class="h1 mt-3 text-white">Refresh queue + freshness</h1>
    <p class="lead mt-4 max-w-3xl">
      Manual enqueue (admin role) and live queue snapshot. The evaluator drains
      the queue, updates verdicts, and writes transparency events.
    </p>
  </section>

  <section class="container-page mt-10 space-y-4">
    <Panel title="Manual enqueue" icon="zap" defaultOpen={true}>
      <form class="grid gap-3 sm:grid-cols-[1fr_2fr_auto]" data-enqueue-form>
        <input
          type="text"
          name="verdict_id"
          placeholder="vdt_…"
          class="rounded-lg border border-white/10 bg-ink-900/60 px-3 py-2 font-mono text-sm text-white"
          required
        />
        <input
          type="text"
          name="reason"
          placeholder="reason (optional)"
          class="rounded-lg border border-white/10 bg-ink-900/60 px-3 py-2 text-sm text-white"
        />
        <button type="submit" class="btn-primary">enqueue</button>
      </form>
      <p class="mt-2 text-xs text-ink-500" data-enqueue-status></p>
    </Panel>

    <Panel title="Pending queue" icon="clock" defaultOpen={true}>
      <div data-panel="queue">loading…</div>
    </Panel>
  </section>
</Layout>

<script>
  import { apiFetch, ApiError } from '../lib/api';

  function escapeHtml(s: string): string {
    return s.replace(/[&<>"']/g, (c) => {
      switch (c) {
        case '&': return '&amp;';
        case '<': return '&lt;';
        case '>': return '&gt;';
        case '"': return '&quot;';
        default: return '&#39;';
      }
    });
  }

  async function refreshQueue(): Promise<void> {
    const target = document.querySelector<HTMLElement>('[data-panel="queue"]');
    if (!target) return;
    try {
      const list = await apiFetch<
        Array<{
          id: number;
          verdict_id: string;
          trigger: string;
          enqueued_at: string;
          claimed_at: string | null;
          done_at: string | null;
        }>
      >('/refresh/queue');
      target.innerHTML = list.length === 0
        ? '<p class="text-sm text-ink-400">Queue is empty.</p>'
        : `<table class="table-zebra w-full text-sm"><thead class="text-left font-mono text-[11px] uppercase tracking-wider text-ink-400"><tr><th class="px-3 py-2">id</th><th class="px-3 py-2">verdict</th><th class="px-3 py-2">trigger</th><th class="px-3 py-2">state</th></tr></thead><tbody>${list
            .map(
              (q) => `<tr class="border-t border-white/5"><td class="px-3 py-2 font-mono text-xs">${q.id}</td><td class="px-3 py-2 font-mono text-xs">${escapeHtml(q.verdict_id)}</td><td class="px-3 py-2"><span class="pill">${escapeHtml(q.trigger)}</span></td><td class="px-3 py-2 font-mono text-[11px] text-ink-400">${q.done_at ? 'done' : q.claimed_at ? 'in flight' : 'pending'}</td></tr>`,
            )
            .join('')}</tbody></table>`;
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err);
      target.innerHTML = `<p class="text-sm text-amber-300">${escapeHtml(msg)}</p>`;
    }
  }

  function bindEnqueue(): void {
    const form = document.querySelector<HTMLFormElement>('[data-enqueue-form]');
    const status = document.querySelector<HTMLElement>('[data-enqueue-status]');
    if (!form || !status) return;
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const fd = new FormData(form);
      const verdictId = String(fd.get('verdict_id') ?? '').trim();
      const reason = String(fd.get('reason') ?? '').trim();
      if (!verdictId) return;
      try {
        const res = await apiFetch<{ id: number }>('/refresh', {
          method: 'POST',
          json: reason ? { verdict_id: verdictId, reason } : { verdict_id: verdictId },
        });
        status.textContent = `enqueued: id=${res.id}`;
        form.reset();
        await refreshQueue();
      } catch (err) {
        status.textContent = err instanceof ApiError ? err.message : String(err);
      }
    });
  }

  function init(): void {
    bindEnqueue();
    void refreshQueue();
    setInterval(refreshQueue, 5_000);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
</script>
```

- [ ] **Step 2: Implement `site/src/pages/webhooks.astro`**

```astro
---
import Layout from '../layouts/Layout.astro';
import Panel from '../components/Panel.astro';
import Icon from '../components/Icon.astro';
---

<Layout title="Webhooks — SMADP" description="Manage webhook subscriptions.">
  <section class="container-page mt-10">
    <span class="heading-eyebrow">Webhooks</span>
    <h1 class="h1 mt-3 text-white">Webhook subscriptions</h1>
    <p class="lead mt-4 max-w-3xl">
      Workspace-scoped subscriptions. Secrets are shown once on creation —
      capture them now.
    </p>
  </section>

  <section class="container-page mt-10 space-y-4">
    <Panel title="Create subscription" icon="webhook" defaultOpen={true}>
      <form class="grid gap-3" data-sub-form>
        <label class="text-sm text-ink-300">
          URL (https only; http://localhost ok in dev)
          <input
            type="url"
            name="url"
            class="mt-1 w-full rounded-lg border border-white/10 bg-ink-900/60 px-3 py-2 font-mono text-sm text-white"
            placeholder="https://hooks.example.test/smadp"
            required
          />
        </label>
        <fieldset class="text-sm text-ink-300">
          <legend>Events</legend>
          <div class="mt-1 flex flex-wrap gap-2">
            {[
              'verdict.created',
              'verdict.updated',
              'verdict.expired',
              'framework_coverage.changed',
              'passport.generated',
              'passport.revoked',
            ].map((ev) => (
              <label class="pill cursor-pointer">
                <input type="checkbox" name="event_types" value={ev} class="mr-1.5" />
                {ev}
              </label>
            ))}
          </div>
        </fieldset>
        <label class="text-sm text-ink-300">
          Integration kind
          <select
            name="integration_kind"
            class="mt-1 w-full rounded-lg border border-white/10 bg-ink-900/60 px-3 py-2 text-sm text-white"
          >
            <option value="generic">generic</option>
            <option value="vanta">Vanta</option>
            <option value="drata">Drata</option>
            <option value="slack">Slack</option>
          </select>
        </label>
        <button type="submit" class="btn-primary">create</button>
      </form>
      <pre class="mt-3 hidden whitespace-pre-wrap rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 font-mono text-[11px] text-amber-200" data-sub-secret></pre>
    </Panel>

    <Panel title="Subscriptions" icon="link" defaultOpen={true}>
      <div data-panel="subs">loading…</div>
    </Panel>
  </section>
</Layout>

<script>
  import { apiFetch, ApiError } from '../lib/api';

  function escapeHtml(s: string): string {
    return s.replace(/[&<>"']/g, (c) => {
      switch (c) {
        case '&': return '&amp;';
        case '<': return '&lt;';
        case '>': return '&gt;';
        case '"': return '&quot;';
        default: return '&#39;';
      }
    });
  }

  async function loadSubs(): Promise<void> {
    const target = document.querySelector<HTMLElement>('[data-panel="subs"]');
    if (!target) return;
    try {
      const list = await apiFetch<
        Array<{
          id: string;
          url: string;
          event_types: string[];
          active: boolean;
          integration_kind: string;
        }>
      >('/webhooks/subscriptions');
      target.innerHTML = list.length === 0
        ? '<p class="text-sm text-ink-400">No subscriptions.</p>'
        : list
            .map(
              (s) => `
            <article class="rounded-lg border border-white/5 bg-ink-950/40 p-3">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <span class="font-mono text-xs text-ink-200">${escapeHtml(s.url)}</span>
                <span class="pill">${escapeHtml(s.integration_kind)}</span>
                <span class="pill">${s.active ? 'active' : 'inactive'}</span>
              </div>
              <div class="mt-2 flex flex-wrap gap-1.5">
                ${s.event_types.map((e) => `<span class="pill">${escapeHtml(e)}</span>`).join('')}
              </div>
              <div class="mt-2 flex items-center justify-between gap-2">
                <span class="font-mono text-[11px] text-ink-500">${escapeHtml(s.id)}</span>
                <button type="button" class="btn-ghost text-xs" data-sub-delete="${escapeHtml(s.id)}">delete</button>
              </div>
            </article>`,
            )
            .join('');
      for (const btn of target.querySelectorAll<HTMLButtonElement>('[data-sub-delete]')) {
        btn.addEventListener('click', async () => {
          const id = btn.dataset.subDelete;
          if (!id) return;
          if (!confirm(`delete subscription ${id}?`)) return;
          try {
            await apiFetch(`/webhooks/subscriptions/${id}`, { method: 'DELETE' });
            await loadSubs();
          } catch (err) {
            alert(err instanceof ApiError ? err.message : String(err));
          }
        });
      }
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err);
      target.innerHTML = `<p class="text-sm text-amber-300">${escapeHtml(msg)}</p>`;
    }
  }

  function bindCreate(): void {
    const form = document.querySelector<HTMLFormElement>('[data-sub-form]');
    const secretBox = document.querySelector<HTMLElement>('[data-sub-secret]');
    if (!form || !secretBox) return;
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const fd = new FormData(form);
      const events = fd.getAll('event_types').map(String);
      const url = String(fd.get('url') ?? '').trim();
      const integrationKind = String(fd.get('integration_kind') ?? 'generic');
      if (!url || events.length === 0) {
        secretBox.classList.remove('hidden');
        secretBox.textContent = 'pick at least one event and provide a URL';
        return;
      }
      try {
        const res = await apiFetch<{
          subscription: { id: string };
          secret: string;
        }>('/webhooks/subscriptions', {
          method: 'POST',
          json: { url, event_types: events, integration_kind: integrationKind },
        });
        secretBox.classList.remove('hidden');
        secretBox.textContent =
          `subscription ${res.subscription.id} created.\n\nSECRET (copy now — shown once):\n${res.secret}`;
        form.reset();
        await loadSubs();
      } catch (err) {
        secretBox.classList.remove('hidden');
        secretBox.textContent = err instanceof ApiError ? err.message : String(err);
      }
    });
  }

  function init(): void {
    bindCreate();
    void loadSubs();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
</script>
```

- [ ] **Step 3: Type-check + build**

```bash
cd site && pnpm check && pnpm build
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add site/src/pages/refresh.astro site/src/pages/webhooks.astro
git commit -m "feat(site): add /refresh and /webhooks admin surfaces"
```

---

## Task 15: Playwright smoke + CI integration + docs

**Files:**
- Create: `site/tests/e2e/smoke.spec.ts`
- Modify: `.github/workflows/ci.yml`
- Modify: `docs/superpowers/plans/2026-05-04-v2-d-plan-6-frontend.md` (append "Status: Complete")

The smoke test boots the Astro dev server (built once into `dist/` via `pnpm build` then served with `pnpm preview`), visits `/home`, picks a persona, verifies the persona view renders, and visits `/frameworks` to confirm the build-time loader still works after our changes. It does **not** require the FastAPI backend — pages that need it (`/workspaces`, `/refresh`, `/webhooks`, `/passports`, `/vendor/[agent]`) just have to render their static shell without console errors. The full backend round-trip is covered by `tests/e2e/test_v2d_smoke.py`.

- [ ] **Step 1: Write the smoke test**

```ts
import { test, expect } from '@playwright/test';

test.describe('SMADP frontend smoke', () => {
  test('home — persona switch hydrates the persona view', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    await page.goto('/home');
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Welcome to SMADP');
    await expect(page.locator('[data-persona-tiles]')).toBeVisible();

    // Pick the auditor tile
    await page.locator('[data-persona-pick="auditor"]').click();

    // Persona view becomes visible; the auditor's first panel (framework_coverage) link is present
    await expect(page.locator('[data-persona-view]')).toBeVisible();
    await expect(page.getByRole('link', { name: /Framework coverage/i })).toBeVisible();

    expect(errors).toEqual([]);
  });

  test('frameworks index — links to deep view; deep view renders', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    await page.goto('/frameworks');
    const firstFwLink = page.locator('h2 a[href^="/frameworks/"]').first();
    await expect(firstFwLink).toBeVisible();
    const href = await firstFwLink.getAttribute('href');
    expect(href).toBeTruthy();

    await page.goto(href!);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    expect(errors).toEqual([]);
  });

  test('static admin shells render without console errors', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    for (const path of ['/workspaces', '/refresh', '/webhooks', '/passports']) {
      await page.goto(path);
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    }

    // Console may have fetch errors (no backend) — only fail on uncaught JS errors
    expect(errors).toEqual([]);
  });
});
```

- [ ] **Step 2: Verify the smoke runs locally**

```bash
cd site && pnpm install
pnpm exec playwright install --with-deps chromium
pnpm build
pnpm preview --port 4321 &
SITE_PID=$!
SMADP_SITE_BASE=http://localhost:4321 pnpm test:e2e
kill $SITE_PID
```
Expected: 3/3 tests pass.

- [ ] **Step 3: Add a CI step to `.github/workflows/ci.yml`**

Find the existing CI job. After the existing test steps (after the "Refresh + Frameworks smoke" step added in Plan 5), append:

```yaml
      - name: Site — install + check
        working-directory: site
        run: |
          npm install -g pnpm@9.12.0
          pnpm install --frozen-lockfile
          pnpm check
          pnpm test

      - name: Site — playwright smoke
        working-directory: site
        run: |
          pnpm exec playwright install --with-deps chromium
          pnpm build
          pnpm preview --port 4321 &
          SITE_PID=$!
          sleep 3
          SMADP_SITE_BASE=http://localhost:4321 pnpm test:e2e
          kill $SITE_PID
```

If the existing CI job uses a setup-node step earlier with a specific Node version, ensure it's ≥ 20 (Astro 4 requires Node ≥ 18.17 / 20). If a setup-node step is missing on the job, add this immediately before the "Site — install + check" step:

```yaml
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
```

- [ ] **Step 4: Verify CI lint locally**

```bash
yamllint .github/workflows/ci.yml || true   # ignore if yamllint not installed
```
Confirm by reading the file that the new steps are inside the existing job, indented consistently with peers.

- [ ] **Step 5: Append "Status: Complete" to this plan**

Edit `docs/superpowers/plans/2026-05-04-v2-d-plan-6-frontend.md` and append at the bottom:

```markdown

---

## Status: Complete

Notable execution decisions:
- _Filled in by the executing agent during the final commit._
```

The executing agent should fill the bullet list with anything surprising they hit (icon name choices, Tailwind class drift, CI Node version pinning, etc.).

- [ ] **Step 6: Commit**

```bash
git add site/tests/e2e/smoke.spec.ts .github/workflows/ci.yml docs/superpowers/plans/2026-05-04-v2-d-plan-6-frontend.md
git commit -m "feat(site): playwright smoke + CI wiring; mark Plan 6 status"
```

---

## After all tasks

After Task 15 lands, dispatch a final code-review pass over the cumulative diff (every file under `site/src/lib/`, `site/src/components/Icon.astro`, `site/src/components/Panel.astro`, `site/src/components/PersonaSwitcher.astro`, `site/src/components/SessionBadge.astro`, every new page under `site/src/pages/`, the Nav patch, and the CI workflow patch) to confirm:

- No emoji as a UI affordance anywhere.
- Every collapsible panel is a `<Panel>` (never a bare `<div>` styled to look like one).
- Every dynamic data fetch goes through `apiFetch` (never raw `fetch`).
- Every page renders its static shell with no console errors when the backend is offline.
- All HTML interpolated from API responses is escaped (the `escapeHtml` helper or equivalent).
- TypeScript types in `api.ts`, `session.ts`, `personas.ts` are exported and consumed consistently.

Then proceed to `superpowers:finishing-a-development-branch` to merge into main.

/**
 * Build-time catalog loader. Reads catalog/profiles/*.json,
 * catalog/verdicts/*.json, catalog/_meta/*.json, and
 * catalog/_chronicle/*.jsonl from disk. All access is synchronous and
 * memoized — Astro calls these from page frontmatter at build time.
 *
 * Resilient to a partial/empty catalog: every getter returns sensible
 * empty values instead of throwing.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type {
  Profile,
  Verdict,
  RiskTaxonomy,
  CategoriesFile,
  FrameworksFile,
  ChronicleEvent,
  RiskId,
  Severity,
} from './types';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// site/src/data → ../../../catalog
const CATALOG_DIR = path.resolve(__dirname, '..', '..', '..', 'catalog');

// ---------- Generic helpers ----------
function safeReadJSON<T>(p: string): T | null {
  try {
    if (!fs.existsSync(p)) return null;
    const raw = fs.readFileSync(p, 'utf-8');
    return JSON.parse(raw) as T;
  } catch (err) {
    console.warn(`[catalog] failed to read ${p}:`, err);
    return null;
  }
}

function safeReadDir(p: string): string[] {
  try {
    if (!fs.existsSync(p)) return [];
    return fs.readdirSync(p);
  } catch {
    return [];
  }
}

// ---------- Profiles ----------
/**
 * Normalize a profile loaded from disk so every page can safely read fields
 * like ``vendor.handle``, ``verification.status``, ``io_surfaces.files`` etc.
 * Stubs from ONEXUS bootstrap and half-formed LLM extractions both pass
 * through this guard, getting the missing keys filled with safe defaults.
 */
function normalizeProfile(raw: any): Profile {
  const p = raw ?? {};
  return {
    ...p,
    slug: p.slug ?? 'unknown',
    name: p.name ?? p.slug ?? 'Unknown',
    tagline: p.tagline ?? '',
    category: p.category ?? 'uncategorized',
    source_type: p.source_type ?? 'unknown',
    homepage: p.homepage ?? '',
    repo_url: p.repo_url ?? (p.onexus?.source_github ? `https://github.com/${p.onexus.source_github}` : ''),
    docs_urls: Array.isArray(p.docs_urls) ? p.docs_urls : [],
    evidence_refs: Array.isArray(p.evidence_refs) ? p.evidence_refs : [],
    vendor: p.vendor ?? { handle: p.onexus?.author_handle ?? '—', type: 'unknown' },
    verification: p.verification ?? {
      status: p.evidence_level === 'unverified-profile' ? 'unverified' : 'draft',
      method: '—',
      verified_by: null,
    },
    capabilities: p.capabilities ?? {},
    io_surfaces: p.io_surfaces ?? { stdin_stdout: false, clipboard: false, screen_capture: false, audio: false, files: [], calls_apis: [] },
    permissions_requested: p.permissions_requested ?? { oauth_scopes: [], secrets_handled: [], elevated_privileges: [] },
    data_classes_touched: Array.isArray(p.data_classes_touched) ? p.data_classes_touched : [],
    sandboxing: p.sandboxing ?? { self_isolation: '—', subagent_model: '—', tool_use_pattern: '—' },
    concurrency_model: p.concurrency_model ?? { session_scope: '—', shared_state_with_other_instances: '—', supports_multiple_instances: undefined },
    pairings: Array.isArray(p.pairings) ? p.pairings : [],
  } as Profile;
}

let _profiles: Profile[] | null = null;
export function getProfiles(): Profile[] {
  if (_profiles) return _profiles;
  const dir = path.join(CATALOG_DIR, 'profiles');
  const out: Profile[] = [];
  // Verified profiles live at catalog/profiles/<slug>.json.
  for (const f of safeReadDir(dir).filter(
    (f) => f.endsWith('.json') && !f.startsWith('_'),
  )) {
    const p = safeReadJSON<any>(path.join(dir, f));
    if (p) out.push(normalizeProfile(p));
  }
  // Unverified seeds live at catalog/profiles/_unverified/<slug>.json.
  const unverifiedDir = path.join(dir, '_unverified');
  for (const f of safeReadDir(unverifiedDir).filter((f) => f.endsWith('.json'))) {
    const p = safeReadJSON<any>(path.join(unverifiedDir, f));
    if (p) out.push(normalizeProfile(p));
  }
  out.sort((a, b) => a.name.localeCompare(b.name));
  _profiles = out;
  return out;
}

export function getProfile(slug: string): Profile | undefined {
  return getProfiles().find((p) => p.slug === slug);
}

// ---------- Verdicts ----------

function normalizeSubVerdict(raw: any): any {
  const sv = raw ?? {};
  return {
    severity: sv.severity ?? 'unknown',
    rationale: sv.rationale ?? '',
    citations: Array.isArray(sv.citations) ? sv.citations : [],
    conditions: Array.isArray(sv.conditions) ? sv.conditions : [],
    mitigations: Array.isArray(sv.mitigations) ? sv.mitigations : [],
  };
}

function normalizeVerdict(raw: any): Verdict {
  const v = raw ?? {};
  const sub = v.sub_verdicts ?? {};
  return {
    ...v,
    pair: Array.isArray(v.pair) ? v.pair : ['unknown', 'unknown'],
    headline: v.headline ?? '',
    composite_score: typeof v.composite_score === 'number' ? v.composite_score : 0,
    confidence: typeof v.confidence === 'number' ? v.confidence : 0,
    evidence_level: v.evidence_level ?? 'docs-only',
    sub_verdicts: {
      A_prompt_injection: normalizeSubVerdict(sub.A_prompt_injection),
      B_data_leakage: normalizeSubVerdict(sub.B_data_leakage),
      C_capability_conflict: normalizeSubVerdict(sub.C_capability_conflict),
      D_cascading_error: normalizeSubVerdict(sub.D_cascading_error),
      E_compliance: normalizeSubVerdict(sub.E_compliance),
    },
    framework_mappings: v.framework_mappings ?? {},
    sandbox_runs: Array.isArray(v.sandbox_runs) ? v.sandbox_runs : [],
    generated_at: v.generated_at ?? new Date(0).toISOString(),
    model: v.model ?? { name: 'unknown', id: 'unknown', rubric_version: '1.0' },
    reproducibility: v.reproducibility ?? {
      rubric_url: '',
      profile_a_sha: '',
      profile_b_sha: '',
      evidence_bundle_sha: '',
    },
    participants: Array.isArray(v.participants) ? v.participants : v.pair ?? [],
  } as Verdict;
}

let _verdicts: Verdict[] | null = null;
export function getVerdicts(): Verdict[] {
  if (_verdicts) return _verdicts;
  const dir = path.join(CATALOG_DIR, 'verdicts');
  // Exclude detached signature sidecars (<key>.sig.json); they are loaded
  // alongside their verdict, not as standalone verdicts.
  const files = safeReadDir(dir).filter(
    (f) => f.endsWith('.json') && !f.endsWith('.sig.json'),
  );
  const out: Verdict[] = [];
  for (const f of files) {
    const v = safeReadJSON<any>(path.join(dir, f));
    if (!v) continue;
    const verdict = normalizeVerdict(v);
    const key = f.replace(/\.json$/, '');
    const sig = safeReadJSON<any>(path.join(dir, `${key}.sig.json`));
    if (sig) verdict.signature = sig;
    out.push(verdict);
  }
  out.sort(
    (a, b) => new Date(b.generated_at).getTime() - new Date(a.generated_at).getTime(),
  );
  _verdicts = out;
  return out;
}

export function getVerdict(a: string, b: string): Verdict | undefined {
  return getVerdicts().find(
    (v) =>
      (v.pair[0] === a && v.pair[1] === b) ||
      (v.pair[0] === b && v.pair[1] === a),
  );
}

export function getVerdictById(id: string): Verdict | undefined {
  return getVerdicts().find((v) => v.verdict_id === id);
}

export function getVerdictsForAgent(slug: string): Verdict[] {
  return getVerdicts().filter((v) => v.pair.includes(slug));
}

// ---------- Meta ----------
let _risk: RiskTaxonomy | null = null;
export function getRiskTaxonomy(): RiskTaxonomy {
  if (_risk) return _risk;
  const r = safeReadJSON<RiskTaxonomy>(
    path.join(CATALOG_DIR, '_meta', 'risk-taxonomy.json'),
  );
  _risk = r ?? {
    schema_version: '1.0',
    severities: [],
    evidence_levels: [],
    risks: [],
  };
  return _risk;
}

let _categories: CategoriesFile | null = null;
export function getCategories(): CategoriesFile {
  if (_categories) return _categories;
  const c = safeReadJSON<CategoriesFile>(
    path.join(CATALOG_DIR, '_meta', 'categories.json'),
  );
  _categories = c ?? { schema_version: '1.0', categories: [] };
  return _categories;
}

let _frameworks: FrameworksFile | null = null;
export function getFrameworks(): FrameworksFile {
  if (_frameworks) return _frameworks;
  const f = safeReadJSON<FrameworksFile>(
    path.join(CATALOG_DIR, '_meta', 'frameworks.json'),
  );
  _frameworks = f ?? { schema_version: '1.0', frameworks: [] };
  return _frameworks;
}

// ---------- Causal risk DAG ----------
import { loadCausalityDag, type CausalityDag } from '../lib/causality';

let _causality: CausalityDag | null = null;
/**
 * Hand-authored causal risk DAG (catalog/_meta/risk-causality.json), validated
 * + memoized. Consumed at build time by CausalGraph.astro. The validation
 * (node set, acyclicity) is the same one the Python analyzer applies.
 */
export function getRiskCausality(): CausalityDag {
  if (_causality) return _causality;
  const raw = safeReadJSON<unknown>(
    path.join(CATALOG_DIR, '_meta', 'risk-causality.json'),
  );
  _causality = loadCausalityDag(raw);
  return _causality;
}

// ---------- Chronicle ----------
let _chronicle: ChronicleEvent[] | null = null;
export function getChronicle(): ChronicleEvent[] {
  if (_chronicle) return _chronicle;
  const dir = path.join(CATALOG_DIR, '_chronicle');
  const files = safeReadDir(dir).filter((f) => f.endsWith('.jsonl'));
  const out: ChronicleEvent[] = [];
  for (const f of files) {
    try {
      const raw = fs.readFileSync(path.join(dir, f), 'utf-8');
      for (const line of raw.split('\n')) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        try {
          out.push(JSON.parse(trimmed) as ChronicleEvent);
        } catch {
          // skip malformed line
        }
      }
    } catch {
      // skip unreadable file
    }
  }
  out.sort((a, b) => (a.ts < b.ts ? 1 : -1));
  _chronicle = out;
  return out;
}

// ---------- Evidence (optional) ----------
export function getEvidenceQuote(ref: string): string | undefined {
  if (!ref?.startsWith('sha256:')) return undefined;
  const hash = ref.slice('sha256:'.length);
  const p = path.join(CATALOG_DIR, '_evidence', `sha256-${hash}.json`);
  const j = safeReadJSON<{ quote?: string }>(p);
  return j?.quote;
}

// ---------- Derived helpers ----------

export function severityScore(s: Severity): number {
  switch (s) {
    case 'none':
      return 0;
    case 'low':
      return 0.2;
    case 'medium':
      return 0.5;
    case 'high':
      return 0.8;
    case 'critical':
      return 1.0;
  }
}

export function severityColor(s: Severity): string {
  return (
    {
      none: '#22C55E',
      low: '#84CC16',
      medium: '#F59E0B',
      high: '#EF4444',
      critical: '#7F1D1D',
    } as const
  )[s];
}

export function evidenceLevelColor(level: string): string {
  return (
    {
      'unverified-profile': '#71717A',
      'docs-only': '#A78BFA',
      'behavior-observed': '#06B6D4',
      'profile-verified': '#7C3AED',
      'sandbox-validated': '#22C55E',
    } as Record<string, string>
  )[level] ?? '#71717A';
}

/** RGB-string blend from green→red across composite score 0..1. */
export function compositeColor(score: number): string {
  const s = Math.max(0, Math.min(1, score));
  // Stops: 0 → green, 0.4 → amber, 0.7 → red, 1 → dark-red.
  const stops: { at: number; rgb: [number, number, number] }[] = [
    { at: 0.0, rgb: [34, 197, 94] }, // green-500
    { at: 0.4, rgb: [245, 158, 11] }, // amber-500
    { at: 0.7, rgb: [239, 68, 68] }, // red-500
    { at: 1.0, rgb: [127, 29, 29] }, // red-900
  ];
  let lo = stops[0]!;
  let hi = stops[stops.length - 1]!;
  for (let i = 0; i < stops.length - 1; i++) {
    if (s >= stops[i]!.at && s <= stops[i + 1]!.at) {
      lo = stops[i]!;
      hi = stops[i + 1]!;
      break;
    }
  }
  const span = hi.at - lo.at || 1;
  const t = (s - lo.at) / span;
  const r = Math.round(lo.rgb[0] + (hi.rgb[0] - lo.rgb[0]) * t);
  const g = Math.round(lo.rgb[1] + (hi.rgb[1] - lo.rgb[1]) * t);
  const b = Math.round(lo.rgb[2] + (hi.rgb[2] - lo.rgb[2]) * t);
  return `rgb(${r}, ${g}, ${b})`;
}

export function categoryName(id: string): string {
  return getCategories().categories.find((c) => c.id === id)?.name ?? id;
}

export function riskMeta(id: RiskId) {
  return getRiskTaxonomy().risks.find((r) => r.id === id);
}

/** Stats for the home page. */
export function getStats() {
  const profiles = getProfiles();
  const verdicts = getVerdicts();
  const sandboxValidated = verdicts.filter(
    (v) => v.evidence_level === 'sandbox-validated',
  ).length;
  return {
    profile_count: profiles.length,
    verdict_count: verdicts.length,
    open_source_count: profiles.filter((p) => p.source_type === 'open-source').length,
    sandbox_validated_pct:
      verdicts.length === 0
        ? 0
        : Math.round((sandboxValidated / verdicts.length) * 100),
    avg_composite:
      verdicts.length === 0
        ? 0
        : verdicts.reduce((a, v) => a + v.composite_score, 0) / verdicts.length,
  };
}

/** All verdicts that touch a given framework control id. */
export function getVerdictsForControl(controlId: string): Verdict[] {
  return getVerdicts().filter((v) =>
    Object.values(v.framework_mappings).some((arr) => arr.includes(controlId)),
  );
}

/**
 * Compact per-agent payload for client-side analysers (e.g. the chain
 * builder). Carries only the fields the heuristics need so we can ship
 * all 100 agents to the page without bloat.
 */
export function getProfileSummariesForClient() {
  return getProfiles().map((p) => {
    const caps = ((p as any).capabilities ?? {}) as any;
    return {
    slug: p.slug,
    name: p.name,
    vendor: (p as any).vendor?.handle ?? '—',
    source_type: p.source_type ?? 'unknown',
    category: p.category,
    caps: {
      execute_shell: !!caps.execute_shell,
      write_filesystem: !!caps.write_filesystem,
      modify_git_state: !!caps.modify_git_state,
      install_packages: !!caps.install_packages,
      spawn_subprocesses: !!caps.spawn_subprocesses,
      use_mcp: !!caps.use_mcp,
      run_browsers: !!caps.run_browsers,
      network_egress: caps.network_egress ?? 'none',
    },
    io: {
      files: !!((p as any).io_surfaces?.files?.length > 0),
      calls_apis: !!((p as any).io_surfaces?.calls_apis?.length > 0),
    },
  };
  });
}

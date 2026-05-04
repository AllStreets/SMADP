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
let _profiles: Profile[] | null = null;
export function getProfiles(): Profile[] {
  if (_profiles) return _profiles;
  const dir = path.join(CATALOG_DIR, 'profiles');
  const out: Profile[] = [];
  // Verified profiles live at catalog/profiles/<slug>.json.
  for (const f of safeReadDir(dir).filter(
    (f) => f.endsWith('.json') && !f.startsWith('_'),
  )) {
    const p = safeReadJSON<Profile>(path.join(dir, f));
    if (p) out.push(p);
  }
  // Unverified seeds live at catalog/profiles/_unverified/<slug>.json.
  const unverifiedDir = path.join(dir, '_unverified');
  for (const f of safeReadDir(unverifiedDir).filter((f) => f.endsWith('.json'))) {
    const p = safeReadJSON<Profile>(path.join(unverifiedDir, f));
    if (p) out.push(p);
  }
  out.sort((a, b) => a.name.localeCompare(b.name));
  _profiles = out;
  return out;
}

export function getProfile(slug: string): Profile | undefined {
  return getProfiles().find((p) => p.slug === slug);
}

// ---------- Verdicts ----------
let _verdicts: Verdict[] | null = null;
export function getVerdicts(): Verdict[] {
  if (_verdicts) return _verdicts;
  const dir = path.join(CATALOG_DIR, 'verdicts');
  const files = safeReadDir(dir).filter((f) => f.endsWith('.json'));
  const out: Verdict[] = [];
  for (const f of files) {
    const v = safeReadJSON<Verdict>(path.join(dir, f));
    if (v) out.push(v);
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

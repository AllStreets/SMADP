import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Profile, Verdict } from './types';

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, '../../..');
const VERDICT_DIR = join(REPO_ROOT, 'catalog', 'verdicts');
const PENDING_DIR = join(REPO_ROOT, 'catalog', 'pending');
const PROFILE_DIR = join(REPO_ROOT, 'catalog', 'profiles');
const EVIDENCE_DIR = join(REPO_ROOT, 'catalog', '_evidence');

type RawVerdict = Omit<Verdict, 'participants'> & { participants?: string[] };

export interface EvidenceBundle {
  sha256: string;
  source_url?: string;
  fetched_at?: string;
  fetcher?: string;
  media_type?: string;
  quote?: string;
  context?: string;
  valid_at?: string;
  valid_status?: string;
}

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

function deriveParticipants(v: RawVerdict): Verdict {
  if (v.participants && v.participants.length >= 2) {
    return { ...v, participants: v.participants, kind: v.participants.length === 2 ? 'pair' : 'chain' };
  }
  if (v.pair && v.pair.length === 2) {
    return { ...v, participants: [...v.pair], kind: 'pair' };
  }
  throw new CatalogError(
    `Verdict ${v.verdict_id ?? '(unknown)'} has neither participants nor pair`
  );
}

let _verdicts: Verdict[] | null = null;
let _profiles: Profile[] | null = null;

export function loadVerdicts(): Verdict[] {
  if (_verdicts === null) {
    _verdicts = readJsonDir<RawVerdict>(VERDICT_DIR, 'verdict').map(deriveParticipants);
  }
  return _verdicts;
}

export function loadPendingVerdicts(): Verdict[] {
  if (!existsSync(PENDING_DIR)) return [];
  let entries: string[];
  try {
    entries = readdirSync(PENDING_DIR);
  } catch {
    return [];
  }
  if (!entries.some((n) => n.endsWith('.json'))) return [];
  return readJsonDir<RawVerdict>(PENDING_DIR, 'pending verdict').map(deriveParticipants);
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

let _evidence: Map<string, EvidenceBundle> | null = null;

export function loadEvidenceMap(): Map<string, EvidenceBundle> {
  if (_evidence !== null) return _evidence;
  const m = new Map<string, EvidenceBundle>();
  let entries: string[];
  try {
    entries = readdirSync(EVIDENCE_DIR);
  } catch (err) {
    throw new CatalogError(
      `Cannot read evidence directory at ${EVIDENCE_DIR}: ${(err as Error).message}`
    );
  }
  for (const name of entries) {
    if (!name.endsWith('.json')) continue;
    const path = join(EVIDENCE_DIR, name);
    try {
      const raw = readFileSync(path, 'utf8');
      const b = JSON.parse(raw) as EvidenceBundle;
      if (b && typeof b.sha256 === 'string') m.set(b.sha256, b);
    } catch (err) {
      throw new CatalogError(
        `Failed to parse evidence file ${path}: ${(err as Error).message}`
      );
    }
  }
  _evidence = m;
  return m;
}

export function _resetForTests() {
  _verdicts = null;
  _profiles = null;
  _evidence = null;
}

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

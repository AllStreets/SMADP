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

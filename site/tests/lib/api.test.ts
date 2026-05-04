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

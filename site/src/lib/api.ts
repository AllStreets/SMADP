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

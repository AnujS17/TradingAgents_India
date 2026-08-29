// @vitest-environment node
//
// Forces the Server Component branch of apiFetch's getBearerToken (reads via
// next-auth/jwt's getToken) rather than the Client Component branch
// (next-auth/react's getSession, which -- unmocked -- makes a real fetch('/api/auth/session')
// call that collides with this file's own global.fetch stub and consumes its
// mocked Response body out from under the assertions below).
import { afterEach, describe, expect, it, vi } from 'vitest';
import { analyzeRun, ApiError, getRun, getRunByTicker, RateLimitError } from '@/lib/api-client/client';

vi.mock('next-auth/jwt', () => ({ getToken: vi.fn().mockResolvedValue(null) }));
vi.mock('next-auth/react', () => ({ getSession: vi.fn().mockResolvedValue(null) }));
vi.mock('next/headers', () => ({
  headers: vi.fn().mockResolvedValue(new Headers()),
  cookies: vi.fn().mockResolvedValue({ getAll: () => [] }),
}));

function jsonResponse(body: unknown, init: { status: number; headers?: Record<string, string> }) {
  return new Response(JSON.stringify(body), {
    status: init.status,
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
  });
}

describe('analyzeRun', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('marks the result as cached when the server returns 200', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ id: 'r1', status: 'completed', poll_url: '/runs/r1', estimated_seconds: 0 }, { status: 200 }),
      ),
    );

    const result = await analyzeRun({ ticker: 'SIEMENS.NS' });

    expect(result.cached).toBe(true);
    expect(result.accepted.id).toBe('r1');
  });

  it('marks the result as not cached when the server returns 202', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ id: 'r2', status: 'queued', poll_url: '/runs/r2', estimated_seconds: 240 }, { status: 202 }),
      ),
    );

    const result = await analyzeRun({ ticker: 'SIEMENS.NS' });

    expect(result.cached).toBe(false);
  });

  it('throws RateLimitError with the server detail and Retry-After on 429', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          { detail: 'The service has reached its daily analysis limit.' },
          { status: 429, headers: { 'Retry-After': '3600' } },
        ),
      ),
    );

    await expect(analyzeRun({ ticker: 'SIEMENS.NS' })).rejects.toMatchObject({
      detail: 'The service has reached its daily analysis limit.',
      retryAfterSeconds: 3600,
    });
  });

  it('rejects RateLimitError instances with instanceof', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ detail: 'limited' }, { status: 429, headers: { 'Retry-After': '60' } })),
    );

    await expect(analyzeRun({ ticker: 'X' })).rejects.toBeInstanceOf(RateLimitError);
  });
});

describe('getRun', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('throws a 404 ApiError when the run does not exist', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: 'Run not found' }, { status: 404 })));

    await expect(getRun('missing')).rejects.toBeInstanceOf(ApiError);
  });
});

describe('getRunByTicker', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns null on 404 instead of throwing (no analysis yet is a normal state)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: 'not found' }, { status: 404 })));

    await expect(getRunByTicker('SIEMENS.NS', '2026-08-12')).resolves.toBeNull();
  });
});

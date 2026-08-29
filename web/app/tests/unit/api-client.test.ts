// @vitest-environment node
//
// This file's default environment (vitest.config.ts) is jsdom, which defines
// `window` globally -- that would always drive apiFetch into its Client
// Component branch (next-auth/react's getSession) regardless of what this
// test mocks. Forcing `node` here makes `typeof window === 'undefined'`
// true, so this test genuinely exercises the Server Component branch
// (next-auth/jwt's getToken) that it mocks below.
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockGetToken = vi.fn();
vi.mock('next-auth/jwt', () => ({ getToken: (...args: unknown[]) => mockGetToken(...args) }));
vi.mock('next-auth/react', () => ({ getSession: vi.fn() }));
// getBearerToken's server branch reads the request via next/headers before
// ever touching next-auth/jwt; outside a real App Router request scope
// those helpers have no request to read, so they're stubbed here to isolate
// the thing this test actually verifies -- that a resolved getToken() value
// ends up as the Authorization header.
vi.mock('next/headers', () => ({
  headers: vi.fn().mockResolvedValue(new Headers()),
  cookies: vi.fn().mockResolvedValue({ getAll: () => [] }),
}));

describe('apiFetch', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    global.fetch = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }));
  });

  it('attaches the bearer token from the session to every request', async () => {
    // getRun is a thin wrapper around apiFetch -- exercising it end to end
    // is a more honest test than calling an internal helper directly,
    // since it's what every real caller in the app actually does.
    const { getRun } = await import('@/lib/api-client/client');
    mockGetToken.mockResolvedValue('raw-jwt-token');

    await getRun('run-1').catch(() => {});

    const [, init] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    // apiFetch attaches the token via a real Headers instance (so it merges
    // correctly with any headers a caller already set), not a plain object --
    // Headers only exposes values through .get(), never dot/bracket access.
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer raw-jwt-token');
  });
});

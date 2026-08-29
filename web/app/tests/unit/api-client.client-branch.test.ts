// This file deliberately carries no environment-override docblock, so it
// runs in the project's default jsdom environment (vitest.config.ts), which
// defines `window` globally. That's the point: it's what makes apiFetch's
// getBearerToken take its Client Component branch (next-auth/react's
// getSession) instead of the Server Component branch (next-auth/jwt's
// getToken) that the sibling api-client and client test files force via
// their own "node" environment override comment. Between them, both
// branches of getBearerToken are now covered.
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockGetSession = vi.fn();
vi.mock('next-auth/react', () => ({ getSession: (...args: unknown[]) => mockGetSession(...args) }));
vi.mock('next-auth/jwt', () => ({ getToken: vi.fn() }));

describe('apiFetch (client branch)', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    global.fetch = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }));
  });

  it('attaches session.accessToken as the bearer token when running in a Client Component (window defined)', async () => {
    const { getRun } = await import('@/lib/api-client/client');
    mockGetSession.mockResolvedValue({ accessToken: 'raw-jwt-token', expires: '2099-01-01' });

    await getRun('run-1').catch(() => {});

    expect(mockGetSession).toHaveBeenCalled();
    const [, init] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer raw-jwt-token');
  });
});

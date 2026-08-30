/**
 * The signIn callback is the ONLY thing in the whole app that causes a
 * `users` row to exist. FastAPI's get_current_user deliberately 401s a
 * validly-signed token whose google_sub has no row, so if this callback
 * stops calling POST /auth/bootstrap, every user silently 401s forever on
 * every request -- exactly the bug this test exists to prevent recurring.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import jwt from 'jsonwebtoken';

import { authOptions } from '@/lib/auth';

const SECRET = 'test-nextauth-secret-at-least-32-chars';

const ACCOUNT = { provider: 'google', type: 'oauth', providerAccountId: 'google-abc' };
const PROFILE = {
  sub: 'google-abc',
  email: 'a@example.com',
  name: 'Ada',
  picture: 'https://example.com/a.png',
};

function callSignIn(overrides: Record<string, unknown> = {}) {
  const signIn = authOptions.callbacks!.signIn!;
  return signIn({ user: {}, account: ACCOUNT, profile: PROFILE, ...overrides } as never);
}

describe('authOptions.callbacks.signIn', () => {
  beforeEach(() => {
    process.env.NEXTAUTH_SECRET = SECRET;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('POSTs a bearer token to /auth/bootstrap on a fresh OAuth sign-in', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204, text: async () => '' });
    vi.stubGlobal('fetch', fetchMock);

    await expect(callSignIn()).resolves.toBe(true);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/auth\/bootstrap$/);
    expect(init.method).toBe('POST');
    expect(init.headers.Authorization).toMatch(/^Bearer /);
  });

  it('signs the claims the backend needs to build the users row', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204, text: async () => '' });
    vi.stubGlobal('fetch', fetchMock);

    await callSignIn();

    const raw = (fetchMock.mock.calls[0][1].headers.Authorization as string).replace('Bearer ', '');
    // verify(), not decode(): a token the backend cannot verify is useless,
    // so the signature is part of the contract being asserted here.
    const claims = jwt.verify(raw, SECRET, { algorithms: ['HS256'] }) as Record<string, unknown>;
    expect(claims.sub).toBe('google-abc');
    expect(claims.email).toBe('a@example.com');
    expect(claims.name).toBe('Ada');
    expect(claims.picture).toBe('https://example.com/a.png');
  });

  it('denies the sign-in when the bootstrap call returns a non-ok response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 500, text: async () => 'boom' });
    vi.stubGlobal('fetch', fetchMock);
    vi.spyOn(console, 'error').mockImplementation(() => {});

    // false -> NextAuth redirects to ?error=AccessDenied and sets no session
    // cookie. Better than a session whose every API call 401s unrecoverably.
    await expect(callSignIn()).resolves.toBe(false);
  });

  it('denies the sign-in when the bootstrap request throws', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('ECONNREFUSED'));
    vi.stubGlobal('fetch', fetchMock);
    vi.spyOn(console, 'error').mockImplementation(() => {});

    await expect(callSignIn()).resolves.toBe(false);
  });

  it('allows the sign-in without calling the API when there is no OAuth profile', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    await expect(callSignIn({ account: null, profile: undefined })).resolves.toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

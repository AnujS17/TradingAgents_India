import type { NextAuthOptions } from 'next-auth';
import CredentialsProvider from 'next-auth/providers/credentials';
import GoogleProvider from 'next-auth/providers/google';
import jwt from 'jsonwebtoken';

const SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60; // 30 days, matches the default NextAuth session lifetime
// The httpOnly session COOKIE living 30 days is fine -- it's never
// readable by page JavaScript. The bearer TOKEN minted below is different:
// session() (client-side path) hands it to any script running on the
// page via session.accessToken, and there is no server-side revocation
// list for it (a stolen 30-day-lived token would be usable for 30 days
// no matter what). getSession() is called fresh on every apiFetch anyway
// (see client.ts), so a short expiry here costs nothing functionally and
// bounds an XSS's blast radius to minutes, not weeks.
const BEARER_TOKEN_MAX_AGE_SECONDS = 15 * 60; // 15 minutes

/** Same signing call jwt.encode below makes -- factored out so session()
 * can mint an equally-valid bearer token for client-side use (see the
 * session() callback's comment for why this is necessary at all). Not
 * required to be byte-identical to whatever's in the session cookie --
 * only to be a validly-signed token carrying the same claims, which any
 * fresh call to this produces regardless of the "exp" drifting a few
 * seconds from the cookie's own. `expiresInSeconds` defaults to the full
 * session lifetime for jwt.encode's own use (that token stays server-side,
 * in the httpOnly cookie); session() below passes the much shorter
 * BEARER_TOKEN_MAX_AGE_SECONDS instead, since that copy is JS-readable. */
function signBearerToken(
  claims: {
    sub?: string;
    role?: string;
    tier?: string;
    // Carried so POST /auth/bootstrap can build the users row from the
    // token alone (api/routers/auth.py reads exactly these). Undefined
    // values are dropped by JSON.stringify before signing, so a token
    // minted without them is byte-identical to the old {sub, role, tier}
    // shape -- nothing that already verifies one stops verifying.
    email?: string;
    name?: string;
    picture?: string;
  },
  expiresInSeconds: number = SESSION_MAX_AGE_SECONDS,
  secret: string = process.env.NEXTAUTH_SECRET as string,
): string {
  return jwt.sign(
    {
      sub: claims.sub,
      role: claims.role,
      tier: claims.tier,
      email: claims.email,
      name: claims.name,
      picture: claims.picture,
    },
    secret,
    { algorithm: 'HS256', expiresIn: expiresInSeconds },
  );
}

/** Where FastAPI lives, as seen from the Next.js SERVER (the signIn
 * callback runs server-side, so NEXT_PUBLIC_API_BASE_URL's browser-facing
 * value is not necessarily reachable from here). */
const API_BASE_URL = process.env.API_BASE_URL ?? 'http://127.0.0.1:8000';

// The JWT this produces is sent to FastAPI as a bearer token
// (api/auth.py::decode_token verifies it independently, same
// NEXTAUTH_SECRET / TRADINGAGENTS_API_JWT_SECRET value, HS256). role and
// tier below are placeholders only -- the backend never trusts them, it
// re-derives the real values from its own users table on every request
// (see api/auth.py::get_current_user). Nothing here is a security
// boundary; the boundary is entirely on the FastAPI side.
export const authOptions: NextAuthOptions = {
  providers: [
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID!,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
    }),
    // Email+password. Unlike Google, this provider does no verification of
    // its own -- POST /auth/login (api/routers/auth.py) does the real
    // work (Argon2 verify, timing-safe against a dummy hash, rate
    // limiting) and this is a thin passthrough to it. Returning `null`
    // fails the sign-in with NextAuth's generic CredentialsSignin error;
    // it never throws, so a network hiccup here reads to the user the
    // same as a wrong password rather than a raw stack trace.
    CredentialsProvider({
      name: 'Credentials',
      credentials: {
        email: { label: 'Email', type: 'email' },
        password: { label: 'Password', type: 'password' },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) return null;

        let res: Response;
        try {
          res = await fetch(`${API_BASE_URL}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: credentials.email, password: credentials.password }),
          });
        } catch (err) {
          console.error('password login request failed', err);
          return null;
        }
        if (!res.ok) return null;

        const data = (await res.json()) as { sub: string; email: string; name: string | null; picture: string | null };
        // `id` is what NextAuth's `user` param carries into the jwt
        // callback below -- api.routers.auth's AuthUser.sub is this
        // account's google_sub (real for a Google account, a synthetic
        // "local:..." value for a password one; see api/db.py's User
        // model comment), the same identity key get_current_user looks
        // up everywhere else.
        return { id: data.sub, email: data.email, name: data.name ?? undefined, image: data.picture ?? undefined };
      },
    }),
  ],
  secret: process.env.NEXTAUTH_SECRET,
  session: { strategy: 'jwt', maxAge: SESSION_MAX_AGE_SECONDS },
  // NextAuth's own default session token is an ENCRYPTED JWE (A256GCM),
  // not a plain signed JWT -- confirmed against NextAuth's own docs/FAQ
  // and multiple maintainer discussions on exactly this "verify in a
  // non-JS backend" question. PyJWT's jwt.decode(..., algorithms=["HS256"])
  // (api/auth.py::decode_token) verifies a JWS and cannot parse a JWE at
  // all. Overriding encode/decode here to produce and consume a plain
  // HS256 JWS instead is what makes the token FastAPI-verifiable -- this
  // is not optional hardening, the default token is simply not usable as
  // a cross-service bearer token without it.
  jwt: {
    async encode({ token, secret }) {
      return signBearerToken(
        {
          sub: token?.sub,
          role: token?.role as string,
          tier: token?.tier as string,
          email: token?.email ?? undefined,
          name: token?.name ?? undefined,
          picture: token?.picture ?? undefined,
        },
        SESSION_MAX_AGE_SECONDS,
        secret as string,
      );
    },
    async decode({ secret, token }) {
      if (!token) return null;
      return jwt.verify(token, secret as string, { algorithms: ['HS256'] }) as Record<string, unknown>;
    },
  },
  callbacks: {
    // Runs SERVER-side during the actual OAuth handshake -- once per genuine
    // sign-in, never on an ordinary token refresh and never per API request.
    // That is exactly the cadence user-creation wants: FastAPI's
    // get_current_user deliberately 401s a validly-signed token whose
    // google_sub has no users row (so a deleted account cannot resurrect
    // itself with a still-valid token), which means SOMETHING has to create
    // that row on the way in. POST /auth/bootstrap is the one endpoint that
    // does, and this is its only caller. Without it every user 401s forever
    // and the first-admin bootstrap never fires.
    async signIn({ account, profile }) {
      // Only a Google OAuth handshake carries both account AND profile.
      // Credentials sign-in has account but no profile (Credentials has no
      // OIDC profile to speak of) -- and doesn't need bootstrapping here
      // anyway, since POST /auth/register already created that row before
      // this sign-in ever started; calling /auth/bootstrap again would
      // just be a redundant upsert with claims this provider doesn't have
      // (no picture from a password account).
      if (!account || !profile) return true;

      const googleProfile = profile as { sub?: string; email?: string; name?: string; picture?: string };
      const token = signBearerToken({
        sub: googleProfile.sub,
        // Placeholders, as everywhere else in this file -- the backend never
        // trusts them, it only needs sub/email/name/picture to upsert the row.
        role: 'user',
        tier: 'free',
        email: googleProfile.email,
        name: googleProfile.name,
        picture: googleProfile.picture,
      });

      try {
        const res = await fetch(`${API_BASE_URL}/auth/bootstrap`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) {
          console.error('auth bootstrap failed', res.status, await res.text().catch(() => ''));
          // Returning false makes NextAuth redirect to
          // /api/auth/error?error=AccessDenied and set NO session cookie
          // (verified in node_modules/next-auth/core/routes/callback.js:78-98).
          // Denying the sign-in outright is better than handing the user a
          // session whose every API call will 401 with no way to recover.
          return false;
        }
      } catch (err) {
        console.error('auth bootstrap request failed', err);
        return false;
      }

      return true;
    },
    async jwt({ token, account, profile, user }) {
      if (account?.provider === 'google' && profile) {
        const googleProfile = profile as { sub?: string; email?: string; name?: string; picture?: string };
        token.sub = googleProfile.sub;
        // Captured so signBearerToken can forward them; Google returns all
        // three as standard OIDC claims (see next-auth's own GoogleProfile
        // type in node_modules/next-auth/providers/google.d.ts).
        token.email = googleProfile.email;
        token.name = googleProfile.name;
        token.picture = googleProfile.picture;
        token.role = 'user';
        token.tier = 'free';
      } else if (account?.provider === 'credentials' && user) {
        // `user` is exactly what the Credentials provider's authorize()
        // returned above -- id is /auth/login's `sub` (this account's
        // google_sub, real or synthetic), already the identity key
        // get_current_user looks up everywhere else.
        token.sub = user.id;
        token.email = user.email ?? undefined;
        token.name = user.name ?? undefined;
        token.picture = user.image ?? undefined;
        token.role = 'user';
        token.tier = 'free';
      }
      return token;
    },
    // getToken({ raw: true }) (Task 9) only works SERVER-side -- it reads
    // httpOnly cookies straight off the request and needs NEXTAUTH_SECRET,
    // neither of which a Client Component has access to (that secret is
    // never sent to the browser, on purpose). So client-side callers have
    // no way to obtain the raw signed cookie value directly; the session
    // object returned by getSession()/useSession() is the only channel
    // available to them. Minting a fresh, equally-valid bearer token here
    // (same claims, same secret, via signBearerToken -- the exact
    // jwt.encode logic above) and exposing it as session.accessToken is
    // what makes that channel work. It does not need to match the cookie's
    // token byte-for-byte, only to carry the same claims and verify
    // correctly against api.auth.decode_token, which it does.
    async session({ session, token }) {
      return {
        ...session,
        accessToken: signBearerToken(
          {
            sub: token?.sub,
            role: token?.role as string,
            tier: token?.tier as string,
            email: token?.email ?? undefined,
            name: token?.name ?? undefined,
            picture: token?.picture ?? undefined,
          },
          BEARER_TOKEN_MAX_AGE_SECONDS,
        ),
      };
    },
  },
};

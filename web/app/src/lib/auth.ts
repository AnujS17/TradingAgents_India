import type { NextAuthOptions } from 'next-auth';
import GoogleProvider from 'next-auth/providers/google';
import jwt from 'jsonwebtoken';

const SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60; // 30 days, matches the default NextAuth session lifetime

/** Same signing call jwt.encode below makes -- factored out so session()
 * can mint an equally-valid bearer token for client-side use (see the
 * session() callback's comment for why this is necessary at all). Not
 * required to be byte-identical to whatever's in the session cookie --
 * only to be a validly-signed token carrying the same claims, which any
 * fresh call to this produces regardless of the "exp" drifting a few
 * seconds from the cookie's own. */
function signBearerToken(claims: { sub?: string; role?: string; tier?: string }): string {
  return jwt.sign(
    { sub: claims.sub, role: claims.role, tier: claims.tier },
    process.env.NEXTAUTH_SECRET as string,
    { algorithm: 'HS256', expiresIn: SESSION_MAX_AGE_SECONDS },
  );
}

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
    async encode({ token }) {
      return signBearerToken({ sub: token?.sub, role: token?.role as string, tier: token?.tier as string });
    },
    async decode({ secret, token }) {
      if (!token) return null;
      return jwt.verify(token, secret as string, { algorithms: ['HS256'] }) as Record<string, unknown>;
    },
  },
  callbacks: {
    async jwt({ token, account, profile }) {
      if (account && profile) {
        token.sub = profile.sub as string;
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
        accessToken: signBearerToken({
          sub: token?.sub,
          role: token?.role as string,
          tier: token?.tier as string,
        }),
      };
    },
  },
};

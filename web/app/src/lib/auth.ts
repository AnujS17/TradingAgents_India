import type { NextAuthOptions } from 'next-auth';
import GoogleProvider from 'next-auth/providers/google';
import jwt from 'jsonwebtoken';

const SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60; // 30 days, matches the default NextAuth session lifetime

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
    async encode({ secret, token }) {
      return jwt.sign(
        { sub: token?.sub, role: token?.role, tier: token?.tier },
        secret as string,
        { algorithm: 'HS256', expiresIn: SESSION_MAX_AGE_SECONDS },
      );
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
    // No accessToken assignment here on purpose. Because of the jwt.encode
    // override above, NextAuth's managed token (the raw encoded string) IS
    // now a plain HS256 JWS carrying exactly {sub, role, tier, exp} -- the
    // bearer token FastAPI verifies, with nothing left to re-derive or
    // re-sign in this callback. Task 9's api-client obtains that raw
    // string directly via next-auth/jwt's getToken({ raw: true }), both
    // server- and client-side; session() only needs to pass session
    // through unchanged.
    async session({ session }) {
      return session;
    },
  },
};

import { withAuth } from 'next-auth/middleware';
import { authOptions } from '@/lib/auth';

// export default (not a named `proxy` export) is still supported in
// proxy.ts -- Next.js 16's docs explicitly note the *function name*
// `proxy` is only a naming convention recommendation, not a required
// named export.
export default withAuth({
  pages: { signIn: '/login' },
  // Without this, withAuth's internal getToken() call falls back to
  // NextAuth's own default JWE decrypt, which cannot parse this app's
  // plain HS256 JWS session token at all -- every signed-in user would
  // be redirected back to /login forever. authOptions.jwt.decode (Task 8)
  // is the SAME decode used to verify the session cookie everywhere else
  // in this app; reusing it here is what makes withAuth actually
  // recognize a valid session.
  jwt: {
    decode: authOptions.jwt?.decode,
  },
});

// Protects everything except: the login page itself, NextAuth's own
// routes, static assets, and the landing page (/ stays public so an
// unauthenticated visitor can see what Bench is before signing in --
// only the research flow itself requires an account).
export const config = {
  matcher: [
    '/runs/:path*',
    '/stock/:path*',
  ],
};

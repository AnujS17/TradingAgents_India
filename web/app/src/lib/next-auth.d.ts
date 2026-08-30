import 'next-auth';
import 'next-auth/jwt';

// session.accessToken is minted in the session() callback (see lib/auth.ts)
// so client-side callers (getSession()/useSession(), no cookie/secret
// access of their own) have a channel to the same bearer token
// server-side callers get via getToken({ raw: true }).
declare module 'next-auth' {
  interface Session {
    accessToken?: string;
  }
}

declare module 'next-auth/jwt' {
  interface JWT {
    sub?: string;
    role?: string;
    tier?: string;
    // Forwarded into the bearer token so POST /auth/bootstrap can build the
    // users row from the token's own claims. Declared here as `string`
    // rather than next-auth's own `string | null` (DefaultJWT) because this
    // app only ever populates them from Google's OIDC profile, and
    // signBearerToken's claims are `string | undefined`.
    email?: string;
    name?: string;
    picture?: string;
  }
}

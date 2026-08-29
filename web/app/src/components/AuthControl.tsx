'use client';

import { signIn, signOut, useSession } from 'next-auth/react';

// Shared between SiteNav (landing) and ResearchNav (research/results pages) --
// a single definition avoids the two navs' auth affordances drifting apart.
export function AuthControl() {
  const { data: session, status } = useSession();
  if (status === 'loading') return null;
  if (!session) {
    return (
      <button
        type="button"
        onClick={() => signIn('google')}
        className="text-sm text-white/70 hover:text-white transition-colors"
      >
        Sign in
      </button>
    );
  }
  return (
    <button
      type="button"
      onClick={() => signOut()}
      className="text-sm text-white/70 hover:text-white transition-colors"
    >
      Sign out
    </button>
  );
}

'use client';

import { useState } from 'react';
import { signIn } from 'next-auth/react';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://127.0.0.1:8000';

type Mode = 'signin' | 'signup';

export default function LoginPage() {
  const [mode, setMode] = useState<Mode>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === 'signup') {
        // POST /auth/register creates the account but does not sign the
        // caller in (api/routers/auth.py's own docstring on why: one code
        // path from credentials to a session, not two to keep in sync) --
        // signIn('credentials', ...) right after is that one path,
        // identical to what "Sign in" below does.
        const res = await fetch(`${API_BASE_URL}/auth/register`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password, name: name || undefined }),
        });
        if (!res.ok) {
          // A fixed message per status code, never the response body
          // itself: an open channel to the backend's `detail` renders
          // whatever a future handler happens to put there without a
          // second look, and if it ever arrives as something other than
          // a string, rendering it directly would throw.
          setError(
            res.status === 409
              ? 'An account with this email already exists. Try signing in instead.'
              : res.status === 422
                ? 'Please check your email and password (at least 8 characters).'
                : res.status === 429
                  ? 'Too many attempts. Try again in a few minutes.'
                  : 'Could not create your account. Try again.',
          );
          setSubmitting(false);
          return;
        }
      }

      const result = await signIn('credentials', { email, password, redirect: false, callbackUrl: '/' });
      if (result?.error) {
        setError(mode === 'signup' ? 'Account created, but sign-in failed. Try signing in below.' : 'Incorrect email or password.');
        setSubmitting(false);
        return;
      }
      window.location.href = result?.url ?? '/';
    } catch {
      setError('Something went wrong. Try again.');
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-[#050A18] px-6">
      <div className="w-full max-w-sm">
        <h1 className="font-tight font-black text-white text-3xl mb-6 text-center">
          {mode === 'signin' ? 'Sign in to TickerInvest' : 'Create your TickerInvest account'}
        </h1>

        {/* Sign in / Sign up toggle -- two tabs, active one filled white. */}
        <div className="flex rounded-full border border-white/15 p-1 mb-6" role="tablist" aria-label="Sign in or sign up">
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'signin'}
            onClick={() => {
              setMode('signin');
              setError(null);
            }}
            className={`flex-1 rounded-full font-tight font-bold text-sm py-2 transition-colors ${
              mode === 'signin' ? 'bg-white text-[#050A18]' : 'text-white/60 hover:text-white'
            }`}
          >
            Sign in
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'signup'}
            onClick={() => {
              setMode('signup');
              setError(null);
            }}
            className={`flex-1 rounded-full font-tight font-bold text-sm py-2 transition-colors ${
              mode === 'signup' ? 'bg-white text-[#050A18]' : 'text-white/60 hover:text-white'
            }`}
          >
            Sign up
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          {mode === 'signup' && (
            <input
              type="text"
              placeholder="Name (optional)"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoComplete="name"
              className="w-full rounded-xl border border-white/15 bg-white/5 text-white placeholder-white/40 text-sm px-4 py-3 focus:outline-none focus:border-white/40 transition-colors"
            />
          )}
          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
            className="w-full rounded-xl border border-white/15 bg-white/5 text-white placeholder-white/40 text-sm px-4 py-3 focus:outline-none focus:border-white/40 transition-colors"
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={mode === 'signup' ? 8 : undefined}
            autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
            className="w-full rounded-xl border border-white/15 bg-white/5 text-white placeholder-white/40 text-sm px-4 py-3 focus:outline-none focus:border-white/40 transition-colors"
          />
          {error && (
            <p role="alert" className="text-[#FF9D7A] text-sm">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={submitting}
            className="w-full font-tight font-bold text-sm rounded-full bg-[#1C6FE6] text-white px-6 py-3 hover:bg-[#237FFB] transition-colors disabled:opacity-50 disabled:cursor-default"
          >
            {submitting ? 'Please wait…' : mode === 'signin' ? 'Sign in' : 'Create account'}
          </button>
        </form>

        <div className="flex items-center gap-3 my-6">
          <div className="h-px flex-1 bg-white/15" />
          <span className="font-tight font-bold text-xs text-white/40">OR</span>
          <div className="h-px flex-1 bg-white/15" />
        </div>

        <button
          type="button"
          onClick={() => signIn('google', { callbackUrl: '/' })}
          className="relative w-full font-tight font-bold text-sm rounded-full bg-white text-[#050A18] px-6 py-3 hover:bg-white/90 transition-colors"
        >
          {/* Pinned to the button's left edge, independent of the
              centered label -- the standard "logo left, text centered"
              social-login button layout. */}
          <span className="absolute left-4 top-1/2 -translate-y-1/2" aria-hidden="true">
            <GoogleLogo />
          </span>
          Login with Google
        </button>
      </div>
    </main>
  );
}

// Google's official "G" mark, unmodified colors -- the standard multi-color
// glyph used on every "Sign in with Google" button.
function GoogleLogo() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.91c1.7-1.57 2.69-3.88 2.69-6.62Z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.47-.81 5.96-2.18l-2.91-2.26c-.81.54-1.84.86-3.05.86-2.34 0-4.33-1.58-5.04-3.71H.96v2.33A9 9 0 0 0 9 18Z"
      />
      <path
        fill="#FBBC05"
        d="M3.96 10.71A5.4 5.4 0 0 1 3.68 9c0-.6.1-1.18.28-1.71V4.96H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.04l3-2.33Z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.32 0 2.51.46 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.96l3 2.33C4.67 5.16 6.66 3.58 9 3.58Z"
      />
    </svg>
  );
}

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
          const body = await res.json().catch(() => ({}));
          setError(
            res.status === 409
              ? 'An account with this email already exists. Try signing in instead.'
              : body.detail?.[0]?.msg || body.detail || 'Could not create your account. Try again.',
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
          {mode === 'signin' ? 'Sign in to Bench' : 'Create your Bench account'}
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
          className="w-full font-tight font-bold text-sm rounded-full bg-white text-[#050A18] px-6 py-3 hover:bg-white/90 transition-colors"
        >
          Login with Google
        </button>
      </div>
    </main>
  );
}

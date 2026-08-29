'use client';

import { signIn } from 'next-auth/react';

export default function LoginPage() {
  return (
    <main className="min-h-screen flex items-center justify-center bg-[#050A18]">
      <div className="text-center">
        <h1 className="font-tight font-black text-white text-3xl mb-6">Sign in to Bench</h1>
        <button
          type="button"
          onClick={() => signIn('google', { callbackUrl: '/' })}
          className="font-tight font-bold text-sm rounded-full bg-white text-[#050A18] px-6 py-3 hover:bg-white/90 transition-colors"
        >
          Sign in with Google
        </button>
      </div>
    </main>
  );
}

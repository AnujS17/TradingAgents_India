'use client';

import Link from 'next/link';
import { signOut, useSession } from 'next-auth/react';

// Shared between SiteNav (landing) and ResearchNav (research/results pages) --
// a single definition avoids the two navs' auth affordances drifting apart.
export function AuthControl() {
  const { data: session, status } = useSession();
  if (status === 'loading') return null;

  if (!session) {
    return (
      // Same solid-blue treatment as "Research a stock" (SiteNav.tsx) --
      // deliberately matching now rather than staying visually distinct
      // from it, per direct instruction.
      <Link
        href="/login"
        className="font-tight font-bold text-xs rounded-full bg-[#1C6FE6] text-white px-4 py-2 hover:bg-[#237FFB] transition-colors"
      >
        Sign in / Sign up
      </Link>
    );
  }

  return <AccountMenu name={session.user?.name} email={session.user?.email} image={session.user?.image} />;
}

function AccountMenu({
  name,
  email,
  image,
}: {
  name?: string | null;
  email?: string | null;
  image?: string | null;
}) {
  const initial = (name ?? email ?? '?').trim().charAt(0).toUpperCase();

  // Array-driven so a later addition ("Saved runs", "Settings", ...) is one
  // more entry here, not a restructure of the menu markup below.
  const menuItems: { label: string; onClick: () => void }[] = [
    { label: 'Sign out', onClick: () => signOut() },
  ];

  return (
    // Same group/group-hover/group-focus-within reveal pattern as
    // TheCall.tsx's export menu -- CSS-only, keyboard-reachable via focus,
    // no JS open/close state needed.
    <div className="relative group">
      <button
        type="button"
        aria-haspopup="true"
        aria-label={name ? `Account menu for ${name}` : 'Account menu'}
        className="block w-8 h-8 rounded-full overflow-hidden ring-2 ring-white/20 group-hover:ring-white/40 group-focus-within:ring-white/40 transition-[box-shadow]"
      >
        {image ? (
          // External Google-hosted avatar; next/image would need
          // remotePatterns configured for a domain this app doesn't
          // otherwise trust, for a small non-optimized-critical image.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={image}
            alt={name ? `${name}'s avatar` : 'Your avatar'}
            className="w-full h-full object-cover"
            referrerPolicy="no-referrer"
          />
        ) : (
          <span className="w-full h-full flex items-center justify-center bg-[#1C6FE6] text-white text-xs font-tight font-bold">
            {initial}
          </span>
        )}
      </button>
      <div
        role="menu"
        aria-label="Account"
        className="absolute right-0 top-full mt-2 z-10 w-48 rounded-2xl border border-[#E0E1E2] bg-white shadow-lg py-1.5 opacity-0 invisible -translate-y-1 pointer-events-none transition-all duration-150 group-hover:opacity-100 group-hover:visible group-hover:translate-y-0 group-hover:pointer-events-auto group-focus-within:opacity-100 group-focus-within:visible group-focus-within:translate-y-0 group-focus-within:pointer-events-auto"
      >
        {(name || email) && (
          <div className="px-4 py-2 border-b border-[#E0E1E2] mb-1">
            {name && <p className="font-tight font-bold text-sm text-[#010101] truncate">{name}</p>}
            {email && <p className="text-xs text-[#6F6F6F] truncate">{email}</p>}
          </div>
        )}
        {menuItems.map((item) => (
          <button
            key={item.label}
            type="button"
            role="menuitem"
            onClick={item.onClick}
            className="block w-full text-left px-4 py-2 font-tight font-semibold text-sm text-[#010101] hover:bg-[#F5F6F8]"
          >
            {item.label}
          </button>
        ))}
      </div>
    </div>
  );
}

import Link from 'next/link';
import { AuthControl } from '@/components/AuthControl';

// Ported verbatim from web/design/landing-fintech/index.html lines 443-463.
// Static markup stays a server component; AuthControl (session-aware) is the
// one client-rendered piece inside it.
export function SiteNav() {
  return (
    <header
      className="sticky top-0 z-50 backdrop-blur-md border-b border-white/10"
      style={{ backgroundColor: 'rgba(5,10,24,.92)' }}
    >
      <div className="max-w-screen-xl mx-auto px-6 lg:px-8 h-16 flex items-center justify-between">
        <a href="#" className="flex items-center gap-2.5 font-tight font-extrabold text-lg text-white">
          <span className="w-8 h-8 rounded-lg grad-navy flex items-center justify-center text-white text-sm font-black">
            B
          </span>
          Bench
          {/* TODO(name): "Bench" is a placeholder wordmark carried over from the other landing-page draft. */}
        </a>
        <nav className="hidden md:flex items-center gap-8 text-sm font-medium text-white/75">
          <a href="#how" className="transition hover:opacity-75 hover:text-white">
            How it works
          </a>
          <a href="#use-cases" className="transition hover:opacity-75 hover:text-white">
            Use cases
          </a>
          <a href="#deck" className="transition hover:opacity-75 hover:text-white">
            What you get
          </a>
          <a href="#live" className="transition hover:opacity-75 hover:text-white">
            Watch it run
          </a>
          <a href="#faq" className="transition hover:opacity-75 hover:text-white">
            FAQ
          </a>
          <Link href="/runs" className="transition hover:opacity-75 hover:text-white">
            Saved runs
          </Link>
          <AuthControl />
        </nav>
        {/* Anchors to the hero's SearchForm wrapper (id="try" — see Hero.tsx). */}
        <a
          href="#try"
          className="btn-shimmer inline-flex items-center gap-1.5 rounded-full bg-[#1C6FE6] text-white text-sm font-semibold px-5 py-2.5 hover:bg-[#237FFB] transition-colors"
        >
          Research a stock
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M5 12h14M13 6l6 6-6 6"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </a>
      </div>
    </header>
  );
}

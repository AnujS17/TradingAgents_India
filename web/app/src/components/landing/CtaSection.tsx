'use client';

import { SearchForm } from '@/components/SearchForm';
import { useScrollReveal } from '@/lib/scroll-reveal';

// Ported from web/design/landing-fintech/index.html lines 1206-1252 (the
// "FINAL CTA" section): a dark rounded panel with a photographic depth
// layer, a gradient scrim and a "ribbon echo" SVG behind the headline. The
// source's dead `<form id="ticker-cta" onsubmit="return false;">` is
// replaced with the real, already-tested <SearchForm variant="cta" />
// (Task 2) — everything else is a verbatim visual port.
export function CtaSection() {
  const panelRef = useScrollReveal<HTMLDivElement>();

  return (
    <section className="max-w-screen-xl mx-auto px-6 lg:px-8 pb-20 lg:pb-28">
      <div ref={panelRef} className="u-reveal relative rounded-[32px] overflow-hidden bg-[#050A18]">
        {/* Photographic depth layer, same TODO(art) as the hero: placeholder
            photography, see note in Hero.tsx. */}
        <div
          aria-hidden="true"
          className="absolute inset-0 bg-cover bg-center opacity-[0.16] mix-blend-luminosity"
          style={{ backgroundImage: "url('https://picsum.photos/seed/bench-close-02/1600/700')" }}
        />
        <div
          aria-hidden="true"
          className="absolute inset-0"
          style={{
            background:
              'linear-gradient(120deg,rgba(5,10,24,.90) 0%,rgba(5,10,24,.70) 60%,rgba(5,10,24,.92) 100%)',
          }}
        />

        {/* ribbon echo */}
        <div aria-hidden="true" className="absolute inset-0 opacity-90">
          <svg className="w-full h-full" viewBox="0 0 1200 420" preserveAspectRatio="xMidYMid slice">
            <defs>
              <linearGradient id="ctaRb" x1="0" y1="1" x2="1" y2="0">
                <stop offset="0%" stopColor="#050A18" stopOpacity="0" />
                <stop offset="40%" stopColor="#1C6FE6" stopOpacity=".8" />
                <stop offset="72%" stopColor="#5FB4F7" stopOpacity=".65" />
                <stop offset="100%" stopColor="#050A18" stopOpacity="0" />
              </linearGradient>
              <filter id="ctaBlur" x="-25%" y="-25%" width="150%" height="150%">
                <feGaussianBlur stdDeviation="26" />
              </filter>
            </defs>
            <rect width="1200" height="420" fill="#050A18" />
            <path
              d="M-160 470 C 160 360, 460 250, 1360 20 L 1360 170 C 460 430, 160 500, -160 570 Z"
              fill="url(#ctaRb)"
              filter="url(#ctaBlur)"
            />
          </svg>
        </div>

        <div className="relative px-8 py-16 lg:py-24 text-center">
          <p className="font-tight font-bold text-[#7FC4FF] text-xs tracking-[0.2em] uppercase">AI Powered</p>
          <h2 className="font-tight font-black text-white text-4xl sm:text-5xl leading-[1.02] tracking-[-0.025em] max-w-xl mx-auto mt-4">
            Put your next idea on the bench.
          </h2>
          <p className="text-white/55 mt-5 max-w-md mx-auto">
            Pick a ticker. Watch four analysts, a bull, a bear and a risk panel argue it out.
          </p>
          <SearchForm variant="cta" />
        </div>
      </div>
    </section>
  );
}

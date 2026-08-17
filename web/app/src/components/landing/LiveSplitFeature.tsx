'use client';

import { useEffect, useRef } from 'react';
import { useScrollReveal } from '@/lib/scroll-reveal';

// Same [data-motion-gate]/.is-onscreen mechanism as Hero.tsx's
// useAmbientMotionGate: the run-bar progress fill (.run-bar span,
// globals.css) only loops while this section is actually on screen.
function useAmbientMotionGate(ref: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!('IntersectionObserver' in window)) {
      el.classList.add('is-onscreen');
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        el.classList.toggle('is-onscreen', entry.isIntersecting);
      },
      { rootMargin: '80px 0px' },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
}

// Ported from web/design/landing-fintech/index.html lines 1062-1125 (the
// "#live" section: badge + h2 + bullets + 2 CTAs on the left, an animated
// "live run" panel opposite). Static marketing content plus the standard
// scroll-reveal on entrance; the panel's progress bar is the section's only
// other motion, gated the same way as the hero ribbons and deck loops so it
// doesn't run forever off screen.
export function LiveSplitFeature() {
  const sectionRef = useRef<HTMLElement | null>(null);
  useAmbientMotionGate(sectionRef);

  const copyRef = useScrollReveal<HTMLDivElement>();
  const panelRef = useScrollReveal<HTMLDivElement>();

  return (
    <section
      ref={sectionRef}
      id="live"
      data-motion-gate
      className="relative bg-[#050A18] border-t border-white/[0.07] overflow-hidden"
    >
      <div aria-hidden="true" className="absolute inset-0">
        <svg className="w-full h-full" viewBox="0 0 1440 700" preserveAspectRatio="xMidYMid slice">
          <defs>
            <radialGradient id="lvGlow" cx="72%" cy="45%" r="52%">
              <stop offset="0%" stopColor="#1C6FE6" stopOpacity=".34" />
              <stop offset="100%" stopColor="#050A18" stopOpacity="0" />
            </radialGradient>
          </defs>
          <rect width="1440" height="700" fill="#050A18" />
          <rect width="1440" height="700" fill="url(#lvGlow)" />
        </svg>
      </div>

      <div className="relative max-w-screen-xl mx-auto px-6 lg:px-8 py-20 lg:py-28 grid lg:grid-cols-2 gap-14 items-center">
        <div ref={copyRef} className="u-reveal">
          <span
            className="inline-flex items-center gap-2 rounded-full border border-white/15 px-4 py-2 text-xs font-bold text-white"
            style={{ backgroundColor: 'rgba(255,255,255,.06)' }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M12 2l2.2 6.6H21l-5.4 4 2 6.6L12 15l-5.6 4.2 2-6.6L3 8.6h6.8L12 2z"
                fill="#7FC4FF"
              />
            </svg>
            The best bit: you can watch
          </span>

          <h2 className="font-tight font-black text-white text-4xl sm:text-5xl mt-6 leading-[1.02] tracking-[-0.025em]">
            See the thinking,
            <br />
            not just a spinner.
          </h2>

          <ul className="mt-8 space-y-4">
            <li className="flex gap-3 text-white/70">
              <span className="mt-2 w-1.5 h-1.5 rounded-full bg-[#3DA2F1] shrink-0" />
              Each analyst reports the moment it finishes
            </li>
            <li className="flex gap-3 text-white/70">
              <span className="mt-2 w-1.5 h-1.5 rounded-full bg-[#3DA2F1] shrink-0" />
              Start reading before the run is even done
            </li>
            <li className="flex gap-3 text-white/70">
              <span className="mt-2 w-1.5 h-1.5 rounded-full bg-[#3DA2F1] shrink-0" />
              Close the tab and come back. Nothing is lost
            </li>
            <li className="flex gap-3 text-white/70">
              <span className="mt-2 w-1.5 h-1.5 rounded-full bg-[#3DA2F1] shrink-0" />
              About four minutes, start to finish
            </li>
          </ul>

          <div className="mt-9 flex flex-wrap gap-3">
            <a
              href="#try"
              className="btn-shimmer rounded-full bg-[#1C6FE6] text-white text-sm font-bold px-6 py-3.5 hover:bg-[#237FFB] transition-colors"
            >
              Start researching
            </a>
            <a
              href="#how"
              className="rounded-full border border-white/20 text-white text-sm font-bold px-6 py-3.5 hover:bg-white/10 transition-colors"
            >
              See how it works
            </a>
          </div>
        </div>

        <div ref={panelRef} className="u-reveal" style={{ ['--delay' as string]: '.1s' }}>
          <div
            className="rounded-[28px] border border-white/12 p-6"
            style={{
              backgroundColor: 'rgba(255,255,255,.05)',
              boxShadow: '0 24px 70px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.09)',
            }}
          >
            <div className="flex items-center justify-between mb-5">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-[#3DA2F1]" />
                <span className="text-[11px] font-bold text-white/55 font-tight uppercase tracking-[0.09em]">
                  TCS.NS · running
                </span>
              </div>
              <span className="text-[11px] font-bold text-white/45 font-tight">02:14 elapsed</span>
            </div>

            <div className="run-list">
              <div className="run-row is-done">
                <span className="run-dot" />
                <span className="run-name">Market analyst</span>
                <span className="run-state">done</span>
              </div>
              <div className="run-row is-done">
                <span className="run-dot" />
                <span className="run-name">Fundamentals analyst</span>
                <span className="run-state">done</span>
              </div>
              <div className="run-row is-live">
                <span className="run-dot" />
                <span className="run-name">News analyst</span>
                <span className="run-state">reading filings…</span>
              </div>
              <div className="run-row">
                <span className="run-dot" />
                <span className="run-name">Sentiment analyst</span>
                <span className="run-state">queued</span>
              </div>
              <div className="run-row">
                <span className="run-dot" />
                <span className="run-name">Bull vs bear debate</span>
                <span className="run-state">queued</span>
              </div>
              <div className="run-row">
                <span className="run-dot" />
                <span className="run-name">Risk panel</span>
                <span className="run-state">queued</span>
              </div>
            </div>

            <div className="run-bar mt-6">
              <span />
            </div>
            <p className="text-[11px] text-white/45 mt-3">
              Reports open as they land, so you never wait for the whole run.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

'use client';

import { useEffect, useRef } from 'react';

// Ported verbatim from web/design/landing-fintech/index.html lines 465-475
// (both duplicate rows kept — .u-ticker-track scrolls by -50%, so the second
// copy is what makes the loop seamless, not visual filler).
const SYMBOLS = [
  'TCS',
  'RELIANCE',
  'INFY',
  'HDFCBANK',
  'SIEMENS',
  'ITC',
  'LT',
  'SBIN',
  'BHARTIARTL',
  'ASIANPAINT',
  'MARUTI',
  'TATAMOTORS',
  'WIPRO',
  'AXISBANK',
  'SUNPHARMA',
  'TITAN',
  'BAJFINANCE',
  'KOTAKBANK',
];

function TickerRow() {
  return (
    <div className="flex items-center gap-7 pr-7 text-[13px] font-tight font-bold text-white/50 whitespace-nowrap">
      <span className="text-[#3DA2F1]">● NSE + BSE COVERAGE</span>
      {SYMBOLS.map((symbol) => (
        <span key={symbol}>{symbol}</span>
      ))}
    </div>
  );
}

// The one ambient/looping animation on the page (DESIGN.md §4 rule 3:
// "unpausable loops are an accessibility failure"). The source only pauses
// it on hover (`.u-ticker:hover .u-ticker-track` in globals.css, preserved
// below via the `u-ticker` class); this adds a pause-off-screen
// IntersectionObserver on top, per the task brief.
//
// Implemented as a direct inline-style toggle rather than a second CSS
// class: `[data-motion-gate].is-onscreen .u-ticker-track { running }` would
// tie in specificity with `.u-ticker:hover .u-ticker-track { paused }` and
// whichever rule is declared later would win the tie — silently breaking
// hover-pause whenever the ticker is on screen. Setting the inline style
// only while off-screen (and clearing it, not setting "running", once back
// on screen) sidesteps that: the stylesheet's hover rule is always free to
// apply once the inline override is gone.
function useOffscreenPause(
  sectionRef: React.RefObject<HTMLElement | null>,
  trackRef: React.RefObject<HTMLDivElement | null>,
) {
  useEffect(() => {
    const section = sectionRef.current;
    const track = trackRef.current;
    if (!section || !track || !('IntersectionObserver' in window)) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        track.style.animationPlayState = entry.isIntersecting ? '' : 'paused';
      },
      { threshold: 0 },
    );
    observer.observe(section);
    return () => observer.disconnect();
  }, [sectionRef, trackRef]);
}

export function TickerMarquee() {
  const sectionRef = useRef<HTMLElement | null>(null);
  const trackRef = useRef<HTMLDivElement | null>(null);
  useOffscreenPause(sectionRef, trackRef);

  return (
    <section
      ref={sectionRef}
      data-motion-gate
      className="u-ticker bg-[#050A18] border-b border-white/[0.07] py-2.5 overflow-hidden"
      aria-label="Exchanges covered"
    >
      <div ref={trackRef} className="u-ticker-track" aria-hidden="true">
        <TickerRow />
        <TickerRow />
      </div>
    </section>
  );
}

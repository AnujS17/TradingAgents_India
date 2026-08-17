'use client';

import { useEffect, useRef } from 'react';

// Ambient loop gate for the deck's four mini-visual animations (bull/bear
// push, source-chip slide, flip roll, report-tile fill) — same
// [data-motion-gate]/.is-onscreen mechanism as Hero.tsx's
// useAmbientMotionGate (source's global script, index.html ~line 1299),
// scoped to this section. DESIGN.md §4 rule 3: unpausable loops are an
// accessibility failure, so these must stop when the deck scrolls off screen.
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

// Scroll-driven horizontal deck: ported verbatim from the source's inline
// <script>, index.html lines 1334-1387. `.deck-track` is translated by
// scroll progress while `.deck-outer` (this section) is pinned via
// `.deck-sticky`'s `position: sticky`; the outer section's height is set
// tall enough (topOffset + blockHeight + overflowPx) to hold the pinned
// block for the whole horizontal travel, and progress is `-rect.top /
// overflowPx` clamped to [0,1] — 1 exactly as the section's bottom reaches
// the unpin threshold.
//
// DESIGN.md §4 rule 2: never transition a scroll-linked transform. The
// transform below is applied by direct `element.style.transform =`
// mutation inside the scroll handler, and `.deck-track` carries no CSS
// `transition` on `transform` (see globals.css) — a transition there would
// outrank even an `!important` inline style and pin the track at its start
// value.
//
// Applied straight from the scroll event, matching the source's own
// comment (index.html ~1381-1383): an rAF latch was tried originally, but
// if a frame never fires (throttled/backgrounded tab) the latch stays set
// and the deck freezes permanently. One rect read + one transform write per
// scroll event instead.
function useDeckScroll() {
  const outerRef = useRef<HTMLElement | null>(null);
  const stickyRef = useRef<HTMLDivElement | null>(null);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const fillRef = useRef<HTMLSpanElement | null>(null);
  const overflowPxRef = useRef(0);

  useEffect(() => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');

    function onScrollDeck() {
      const deckOuter = outerRef.current;
      const deckTrack = trackRef.current;
      if (!deckOuter || !deckTrack || overflowPxRef.current <= 0) return;
      const rect = deckOuter.getBoundingClientRect();
      // Travel is driven by the pinned distance, so progress hits 1 exactly
      // as the parent's bottom reaches the unpin threshold.
      const progress = Math.min(1, Math.max(0, -rect.top / overflowPxRef.current));
      deckTrack.style.transform = `translate3d(${-progress * overflowPxRef.current}px,0,0)`;
      if (fillRef.current) fillRef.current.style.transform = `scaleX(${progress.toFixed(4)})`;
    }

    function measureDeck() {
      const deckOuter = outerRef.current;
      const deckTrack = trackRef.current;
      const deckSticky = stickyRef.current;
      const deckView = viewportRef.current;
      if (!deckOuter || !deckTrack || !deckSticky || !deckView) return;

      // Pin only on wide screens; below that the deck is a normal swipe carousel.
      if (window.innerWidth < 1024 || reduce.matches) {
        deckOuter.style.height = '';
        deckTrack.style.transform = '';
        overflowPxRef.current = 0;
        if (fillRef.current) fillRef.current.style.transform = 'scaleX(1)';
        return;
      }

      // clientWidth includes the left inset that aligns card 1 with the page
      // gutter, so subtract it — otherwise the track looks wider than it
      // really is.
      const padL = parseFloat(getComputedStyle(deckView).paddingLeft) || 0;
      const trackW = deckTrack.scrollWidth;
      const viewW = deckView.clientWidth - padL;
      overflowPxRef.current = Math.max(0, trackW - viewW + padL);

      // A sticky child can never be painted below its parent's bottom edge,
      // so the parent must be tall enough to hold the pinned block for the
      // WHOLE travel: topOffset + blockHeight + travel. Sizing it to the
      // viewport instead lets the parent's bottom shove the block upward
      // near the end, which drags the heading up under the nav.
      const topOffset = parseFloat(getComputedStyle(deckSticky).top) || 0;
      const blockH = deckSticky.offsetHeight;
      deckOuter.style.height = `${topOffset + blockH + overflowPxRef.current}px`;
      onScrollDeck();
    }

    window.addEventListener('scroll', onScrollDeck, { passive: true });
    window.addEventListener('resize', measureDeck);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(measureDeck);
    measureDeck();

    return () => {
      window.removeEventListener('scroll', onScrollDeck);
      window.removeEventListener('resize', measureDeck);
    };
  }, []);

  return { outerRef, stickyRef, trackRef, viewportRef, fillRef };
}

// Ported from web/design/landing-fintech/index.html lines 982-1059 (the
// "SCROLL DECK (dark, horizontal)" section, id="deck") plus its scroll-math
// script, lines 1334-1387. DESIGN.md §5 "scroll-pinned horizontal deck".
export function Deck() {
  const { outerRef, stickyRef, trackRef, viewportRef, fillRef } = useDeckScroll();
  useAmbientMotionGate(outerRef);

  return (
    <section
      ref={outerRef}
      id="deck"
      data-motion-gate
      className="deck-outer relative bg-[#050A18]"
    >
      <div aria-hidden="true" className="absolute inset-0 overflow-hidden">
        <svg className="w-full h-full" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMid slice">
          <defs>
            <linearGradient id="dkRb" x1="0" y1="1" x2="1" y2="0">
              <stop offset="0%" stopColor="#050A18" stopOpacity="0" />
              <stop offset="38%" stopColor="#123C86" stopOpacity=".75" />
              <stop offset="70%" stopColor="#3DA2F1" stopOpacity=".45" />
              <stop offset="100%" stopColor="#050A18" stopOpacity="0" />
            </linearGradient>
            <filter id="dkBlur" x="-25%" y="-25%" width="150%" height="150%">
              <feGaussianBlur stdDeviation="40" />
            </filter>
          </defs>
          <rect width="1440" height="900" fill="#050A18" />
          <path
            d="M-200 980 C 220 800, 620 600, 1660 140 L 1660 420 C 620 860, 220 1000, -200 1150 Z"
            fill="url(#dkRb)"
            filter="url(#dkBlur)"
          />
        </svg>
      </div>

      <div ref={stickyRef} className="deck-sticky">
        <div className="max-w-screen-xl mx-auto px-6 lg:px-8 pt-10 pb-6">
          <h2 className="font-tight font-black text-white text-4xl sm:text-5xl mt-3 leading-[1.02] tracking-[-0.025em]">
            Four things, done properly.
          </h2>
        </div>

        <div ref={viewportRef} className="deck-viewport">
          <div ref={trackRef} className="deck-track">
            <article className="deck-card">
              <div className="deck-icon">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M12 4v16" stroke="white" strokeWidth="2" strokeLinecap="round" />
                  <path
                    d="M5 9h4M5 15h4M15 9h4M15 15h4"
                    stroke="white"
                    strokeWidth="2"
                    strokeLinecap="round"
                  />
                </svg>
              </div>
              <h3 className="deck-title">Both sides argue it out</h3>
              <p className="deck-body">
                One AI makes the case to buy. Another pulls it apart. A third reads both and
                decides.
              </p>
              <div className="deck-viz">
                <div className="viz-seam" />
                <div className="viz-bar viz-bar-l">
                  <span>BULL</span>
                </div>
                <div className="viz-bar viz-bar-r">
                  <span>BEAR</span>
                </div>
              </div>
            </article>

            <article className="deck-card">
              <div className="deck-icon">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <circle cx="12" cy="12" r="9" stroke="white" strokeWidth="1.9" />
                  <path
                    d="M9 12l2 2 4-4"
                    stroke="white"
                    strokeWidth="2.2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </div>
              <h3 className="deck-title">Every number is checked</h3>
              <p className="deck-body">
                A figure only appears if it came from a real filing or a real headline. Tap it to
                see which one.
              </p>
              <div className="deck-viz viz-trace">
                <p className="viz-sentence">
                  Margin fell to <span className="viz-figure">9.8%</span> this quarter.
                </p>
                <div className="viz-chip">from the Q1 filing</div>
              </div>
            </article>

            <article className="deck-card">
              <div className="deck-icon">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M12 8v5M12 16.5v.01" stroke="white" strokeWidth="2.2" strokeLinecap="round" />
                  <circle cx="12" cy="12" r="9" stroke="white" strokeWidth="1.9" />
                </svg>
              </div>
              <h3 className="deck-title">It admits when it is close</h3>
              <p className="deck-body">
                Ask twice and the answer can change. When that happens we tell you, instead of
                picking one.
              </p>
              <div className="deck-viz viz-runs">
                <div className="viz-run">
                  <span>Run 1</span>
                  <b>Sell</b>
                </div>
                <div className="viz-run">
                  <span>Run 2</span>
                  <b>Sell</b>
                </div>
                <div className="viz-run">
                  <span>Run 3</span>
                  <b className="viz-flip">
                    <i>Sell</i>
                    <i>Hold</i>
                  </b>
                </div>
              </div>
            </article>

            <article className="deck-card">
              <div className="deck-icon">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M4 6h16M4 12h10M4 18h13" stroke="white" strokeWidth="2.2" strokeLinecap="round" />
                </svg>
              </div>
              <h3 className="deck-title">Short answer, long answer</h3>
              <p className="deck-body">
                A plain verdict at the top. Ten full reports underneath, for the days you want all
                of it.
              </p>
              <div className="deck-viz viz-reports">
                <i></i>
                <i></i>
                <i></i>
                <i></i>
                <i></i>
                <i></i>
                <i></i>
                <i></i>
                <i></i>
                <i></i>
              </div>
            </article>
          </div>
        </div>

        <div className="max-w-screen-xl mx-auto px-6 lg:px-8 pb-10 pt-5">
          <div className="deck-progress" aria-hidden="true">
            <span ref={fillRef}></span>
          </div>
        </div>
      </div>
    </section>
  );
}

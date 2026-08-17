'use client';

import { Suspense, useEffect, useRef } from 'react';
import { SearchForm } from '@/components/SearchForm';
import { useScrollReveal } from '@/lib/scroll-reveal';

// Ambient ribbon drift (.u-ribbon-a/.u-ribbon-b, see globals.css) only runs
// while the hero is on screen — the same [data-motion-gate]/.is-onscreen
// mechanism as the source's global script (index.html ~line 1299), scoped
// here to just this section. Unlike useScrollReveal this toggles
// continuously (not a one-shot reveal): the ribbons pause again if the hero
// scrolls back off screen, matching the source's `toggle('is-onscreen',
// e.isIntersecting)` and its 80px rootMargin.
function useAmbientMotionGate(ref: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!('IntersectionObserver' in window)) {
      // No observer: leave the loops running rather than frozen mid-cycle
      // (source's fallback, index.html ~line 1308).
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

// Ported from web/design/landing-fintech/index.html lines 477-658 (the hero
// section: headline, SVG light-ribbon background, the "contested figure"
// illustrative card, and the stat rail). The source's dead
// `<form id="try" onsubmit="return false;">` is replaced by the real,
// already-tested <SearchForm variant="hero" /> (Task 2); the wrapping div
// keeps id="try" so SiteNav's `href="#try"` anchor still resolves.
//
// The stat rail's numbers (12/5/2/10/4min) are rendered as static final
// values. The source also count-up-animates them from 0 on scroll into view
// (index.html ~lines 1389-1424); that's pure decorative polish on top of
// content that's correct either way, and the task brief characterizes this
// whole section as "static marketing content" — so the count-up was left
// out rather than re-implemented, to keep this port to what the brief
// actually asks for.
export function Hero() {
  const sectionRef = useRef<HTMLElement | null>(null);
  useAmbientMotionGate(sectionRef);

  const eyebrowRef = useScrollReveal<HTMLParagraphElement>();
  const headlineRef = useScrollReveal<HTMLHeadingElement>();
  const subtextRef = useScrollReveal<HTMLParagraphElement>();
  const cardRef = useScrollReveal<HTMLDivElement>();
  const statRailRef = useScrollReveal<HTMLDivElement>();

  return (
    <section ref={sectionRef} data-motion-gate className="relative bg-[#050A18] overflow-hidden">
      {/* Photographic depth layer. Blended to luminosity at low opacity so it
          reads as texture, not as a stock photo of a trading floor.
          TODO(art): swap for commissioned or licensed photography before
          launch; picsum.photos is a placeholder service (lorem ipsum for
          images). */}
      <div
        aria-hidden="true"
        className="absolute inset-0 bg-cover bg-center opacity-[0.13] mix-blend-luminosity"
        style={{ backgroundImage: "url('https://picsum.photos/seed/bench-ledger-01/1920/1080')" }}
      />
      <div
        aria-hidden="true"
        className="absolute inset-0"
        style={{
          background:
            'linear-gradient(180deg,rgba(5,10,24,.72) 0%,rgba(5,10,24,.88) 55%,#050A18 100%)',
        }}
      />

      {/* flowing light-ribbon background */}
      <div aria-hidden="true" className="absolute inset-0">
        <svg className="w-full h-full" viewBox="0 0 1440 860" preserveAspectRatio="xMidYMid slice">
          <defs>
            <linearGradient id="rbA" x1="0" y1="1" x2="1" y2="0">
              <stop offset="0%" stopColor="#0B2E6E" stopOpacity="0" />
              <stop offset="28%" stopColor="#1C6FE6" stopOpacity=".85" />
              <stop offset="58%" stopColor="#5FB4F7" stopOpacity=".95" />
              <stop offset="82%" stopColor="#237FFB" stopOpacity=".5" />
              <stop offset="100%" stopColor="#050A18" stopOpacity="0" />
            </linearGradient>
            <linearGradient id="rbB" x1="0" y1="1" x2="1" y2="0">
              <stop offset="0%" stopColor="#050A18" stopOpacity="0" />
              <stop offset="35%" stopColor="#0E4FA8" stopOpacity=".7" />
              <stop offset="70%" stopColor="#3DA2F1" stopOpacity=".55" />
              <stop offset="100%" stopColor="#050A18" stopOpacity="0" />
            </linearGradient>
            <linearGradient id="rbC" x1="0" y1="1" x2="1" y2="0">
              <stop offset="0%" stopColor="#050A18" stopOpacity="0" />
              <stop offset="45%" stopColor="#7FC4FF" stopOpacity=".75" />
              <stop offset="100%" stopColor="#050A18" stopOpacity="0" />
            </linearGradient>
            <radialGradient id="glow" cx="30%" cy="62%" r="55%">
              <stop offset="0%" stopColor="#1C6FE6" stopOpacity=".38" />
              <stop offset="100%" stopColor="#050A18" stopOpacity="0" />
            </radialGradient>
            <filter id="blurBig" x="-25%" y="-25%" width="150%" height="150%">
              <feGaussianBlur stdDeviation="34" />
            </filter>
            <filter id="blurMid" x="-25%" y="-25%" width="150%" height="150%">
              <feGaussianBlur stdDeviation="16" />
            </filter>
            <filter id="blurThin" x="-25%" y="-25%" width="150%" height="150%">
              <feGaussianBlur stdDeviation="5" />
            </filter>
          </defs>

          <rect width="1440" height="860" fill="#050A18" />
          <rect width="1440" height="860" fill="url(#glow)" />

          <g className="u-ribbon-a">
            {/* broad soft band */}
            <path
              d="M-220 900 C 180 700, 520 520, 1660 60 L 1660 330 C 520 760, 180 880, -220 1040 Z"
              fill="url(#rbA)"
              filter="url(#blurBig)"
              opacity=".75"
            />
            {/* brighter core */}
            <path
              d="M-200 880 C 200 690, 540 500, 1640 90 L 1640 176 C 540 596, 200 800, -200 960 Z"
              fill="url(#rbC)"
              filter="url(#blurMid)"
              opacity=".85"
            />
          </g>

          <g className="u-ribbon-b">
            <path
              d="M-240 1010 C 200 830, 640 640, 1680 200 L 1680 400 C 640 850, 200 1000, -240 1140 Z"
              fill="url(#rbB)"
              filter="url(#blurBig)"
              opacity=".8"
            />
            {/* crisp filament */}
            <path
              d="M-180 856 C 240 676, 580 486, 1620 66 L 1620 100 C 580 526, 240 726, -180 892 Z"
              fill="url(#rbC)"
              filter="url(#blurThin)"
              opacity=".55"
            />
          </g>

          {/* distant faint band */}
          <path
            d="M-200 640 C 260 520, 700 380, 1640 -70 L 1640 60 C 700 500, 260 640, -200 740 Z"
            fill="url(#rbB)"
            filter="url(#blurBig)"
            opacity=".4"
          />
        </svg>
      </div>

      <div className="relative max-w-screen-xl mx-auto px-6 lg:px-8 pt-16 pb-14 lg:pt-20 lg:pb-16">
        <div className="grid lg:grid-cols-[1.15fr_1fr] gap-12 lg:gap-14 items-center">
          <div>
            <p
              ref={eyebrowRef}
              className="u-rise font-tight font-bold text-[#7FC4FF] text-sm tracking-[0.2em] uppercase"
              style={{ ['--rise' as string]: '12px', ['--delay' as string]: '.05s' }}
            >
              AI Powered
            </p>

            <h1
              ref={headlineRef}
              className="u-rise font-tight font-black text-white text-5xl sm:text-6xl lg:text-[3.9rem] xl:text-[4.25rem] leading-[0.98] tracking-[-0.03em] mt-4"
              style={{ ['--rise' as string]: '22px', ['--delay' as string]: '.12s' }}
            >
              Equity research
              <br />
              that <span className="grad-text">shows its&nbsp;work.</span>
            </h1>

            <p
              ref={subtextRef}
              className="u-rise text-white/55 text-base leading-relaxed mt-5 max-w-lg"
              style={{ ['--rise' as string]: '18px', ['--delay' as string]: '.26s' }}
            >
              Enter any NSE or BSE ticker. Twelve AI agents pull the filings, argue the bull
              case against the bear case, and hand back a verdict where every number is traced
              to the sentence it came from.
            </p>

            {/* SearchForm's hero variant already carries u-rise with
                --rise:16px/--delay:.32s, matching the source form's inline
                style exactly (see SearchForm.tsx). id="try" lives on this
                wrapper, not the form itself, so SiteNav's href="#try" still
                resolves.

                SearchForm reads the URL's query string (useSearchParams) to
                seed itself from a /?ticker=…&date=… deep link, which forces
                client-side rendering up to the nearest Suspense boundary —
                so the boundary is scoped tightly to just the form, not the
                whole page (moved here from the old page.tsx, Task 7). */}
            <div id="try">
              <Suspense fallback={<p className="text-white/40 text-sm mt-8">Loading the search form…</p>}>
                <SearchForm variant="hero" />
              </Suspense>
            </div>
          </div>

          {/* SIGNATURE: contested seam, dark treatment. Illustrative
              marketing content — shows what the product produces, not a
              real run. Do not wire this to live data or change the
              numbers. */}
          <div
            ref={cardRef}
            className="u-rise relative"
            style={{ ['--rise' as string]: '26px', ['--delay' as string]: '.22s' }}
          >
            <div
              className="rounded-[32px] border border-white/12 bg-white/[0.05] backdrop-blur-xl overflow-hidden"
              style={{ boxShadow: '0 24px 70px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.09)' }}
            >
              <div className="flex items-center justify-between px-6 pt-6">
                <span className="text-[11px] font-bold text-white/50 font-tight uppercase tracking-[0.09em]">
                  SIEMENS.NS contested figure
                </span>
                <span className="text-[11px] font-bold rounded-full bg-white text-[#050A18] px-3 py-1">
                  Underweight
                </span>
              </div>

              <div className="text-center pt-7 pb-1">
                <p className="font-tight font-black text-white text-4xl tracking-[-0.02em]">
                  ₹1,240<span className="text-2xl text-white/45 font-bold">cr</span>
                </p>
                <p className="text-xs text-white/45 mt-1.5">order book, Q1, cited by both sides</p>
              </div>

              <div className="relative px-6 pt-6 pb-2">
                <div
                  aria-hidden="true"
                  className="u-seam absolute left-1/2 top-2 bottom-2 w-px bg-gradient-to-b from-transparent via-[#3DA2F1] to-transparent"
                />
                <div className="grid grid-cols-2">
                  <div className="u-split-l pr-5 text-right">
                    <p className="text-[10px] font-black font-tight text-[#7FC4FF] tracking-[0.09em] mb-1.5">
                      BULL READS IT
                    </p>
                    <p className="text-xs text-white/55 leading-relaxed">
                      &ldquo;Up 18% YoY. Demand is not the problem here.&rdquo;
                    </p>
                  </div>
                  <div className="u-split-r pl-5">
                    <p className="text-[10px] font-black font-tight text-[#3DA2F1] tracking-[0.09em] mb-1.5">
                      BEAR READS IT
                    </p>
                    <p className="text-xs text-white/55 leading-relaxed">
                      &ldquo;Same book, and margins still fell three quarters straight.&rdquo;
                    </p>
                  </div>
                </div>
              </div>

              <div className="mx-6 mt-5 rounded-2xl bg-white/[0.05] border border-white/10 p-4 flex items-center justify-between gap-3">
                <div>
                  <p className="text-[10px] font-black text-white/45 uppercase tracking-[0.09em]">
                    Research Manager rules
                  </p>
                  <p className="text-sm text-white font-semibold mt-0.5">
                    Bear&rsquo;s margin trend wins. Trim, don&rsquo;t exit.
                  </p>
                </div>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" className="shrink-0" aria-hidden="true">
                  <circle cx="12" cy="12" r="9" stroke="#3DA2F1" strokeWidth="2" />
                  <path
                    d="M9 12l2 2 4-4"
                    stroke="#3DA2F1"
                    strokeWidth="2.4"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </div>

              <div className="grid grid-cols-3 divide-x divide-white/10 border-t border-white/10 mx-6 mt-5 mb-6">
                <div className="pt-3 pr-3">
                  <p className="text-[10px] font-bold text-white/40 uppercase tracking-wide">Entry</p>
                  <p className="text-sm font-tight font-semibold text-white/70 mt-0.5">Not set</p>
                </div>
                <div className="pt-3 px-3">
                  <p className="text-[10px] font-bold text-white/40 uppercase tracking-wide">Stop</p>
                  <p className="text-sm font-tight font-semibold text-white/70 mt-0.5">Not set</p>
                </div>
                <div className="pt-3 pl-3">
                  <p className="text-[10px] font-bold text-white/40 uppercase tracking-wide">Action</p>
                  <p className="text-sm font-tight font-extrabold text-white mt-0.5">Hold</p>
                </div>
              </div>
            </div>
            <p className="text-center text-xs text-white/50 mt-4 px-4">
              A real fixture. Entry and stop stay blank when the case cannot support a number.
            </p>
          </div>
        </div>

        {/* ── STAT RAIL ─────────────────────────────────────────────── */}
        <div
          ref={statRailRef}
          className="stat-rail u-rise mt-14 lg:mt-16 pt-10 border-t border-white/10 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-y-9 lg:divide-x lg:divide-white/12"
          style={{ ['--rise' as string]: '20px', ['--delay' as string]: '.44s' }}
        >
          <div className="lg:px-7 lg:first:pl-0">
            <p className="font-tight font-black text-white text-4xl lg:text-5xl tracking-[-0.03em]" data-count="12">
              12
            </p>
            <p className="text-xs text-white/55 mt-1.5 leading-snug">
              AI agents
              <br />
              on every run
            </p>
          </div>
          <div className="lg:px-7">
            <p className="font-tight font-black text-white text-4xl lg:text-5xl tracking-[-0.03em]" data-count="5">
              5
            </p>
            <p className="text-xs text-white/55 mt-1.5 leading-snug">
              Specialist teams,
              <br />
              handed off in order
            </p>
          </div>
          <div className="lg:px-7">
            <p className="font-tight font-black text-white text-4xl lg:text-5xl tracking-[-0.03em]" data-count="2">
              2
            </p>
            <p className="text-xs text-white/55 mt-1.5 leading-snug">
              Adversarial debates
              <br />
              before any verdict
            </p>
          </div>
          <div className="lg:px-7">
            <p className="font-tight font-black text-white text-4xl lg:text-5xl tracking-[-0.03em]" data-count="10">
              10
            </p>
            <p className="text-xs text-white/55 mt-1.5 leading-snug">
              Linked reports
              <br />
              behind the call
            </p>
          </div>
          <div className="lg:px-7">
            <p className="font-tight font-black text-white text-4xl lg:text-5xl tracking-[-0.03em]">
              <span data-count="4">4</span>
              <span className="text-2xl lg:text-3xl">min</span>
            </p>
            <p className="text-xs text-white/55 mt-1.5 leading-snug">
              From ticker
              <br />
              to full verdict
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

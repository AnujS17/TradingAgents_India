'use client';

import { useScrollReveal } from '@/lib/scroll-reveal';

// Rewritten 2026-08-22 per design review: the previous version (four static
// claim cards, one real evidence chip each) read as flat and too symmetric.
// This version foregrounds the actual mechanic the product is built on --
// bull and bear arguing the SAME four contested points from the SIEMENS.NS
// fixture (api/fixtures/sample_run.json), reusing the exact excerpts already
// verified against source this session for the research page's own ledger.
//
// Not a literal "Round 1 of 3": the backend's InvestDebateState tracks
// bull_history/bear_history/count internally (tradingagents/agents/utils/
// agent_states.py), but the API only exposes the two consolidated final
// essays (Reports.bull_case/bear_case), not a per-round array. Labelling
// these as numbered rounds would assert a structure the data doesn't back --
// DESIGN.md §6 "never invent numbers" extends to never inventing structure.
// These are the real contested points within that debate, not literal rounds.
//
// Deliberately NOT dark-glass (that would duplicate Deck.tsx two sections
// down, which already owns the dark, richly-visualised card treatment) and
// NOT green-accented (DESIGN.md §1: green/red are reserved for price
// direction only). Colour and interactivity come from pushing the existing
// navy / accent-1 / #1B6FA8 bull-bear pair harder, plus the amber pairing
// already established on the research page's "Not final" badge for the one
// featured card here.
export function TrustStrip() {
  const headingRef = useScrollReveal<HTMLDivElement>();
  const cardRefs = [
    useScrollReveal<HTMLDivElement>(),
    useScrollReveal<HTMLDivElement>(),
    useScrollReveal<HTMLDivElement>(),
    useScrollReveal<HTMLDivElement>(),
  ] as const;

  const points = [
    {
      topic: 'The LVM gain',
      bull: 'Adjusted PAT fell because the company deliberately exited a lower-margin motors business. That is portfolio engineering, not deterioration.',
      bear: 'Exiting a lower-margin business should lift margins. Instead they collapsed. That is a core margin problem masked by a ₹2,099 crore one-off.',
      delay: '0s',
      featured: true,
    },
    {
      topic: 'The balance sheet',
      bull: 'A ₹6,800 crore net-cash cushion plus an ₹18 dividend funds that growth without leverage.',
      bear: 'Net cash is real, but it is not a growth engine at 93x. FY25 free cash flow was negative ₹6 crore.',
      delay: '.08s',
      featured: false,
    },
    {
      topic: 'The tape',
      bull: 'RSI cooled from 76 to 66. Textbook overbought unwinding, not distribution.',
      bear: 'That spike failed to close above the upper Bollinger Band, and MACD histogram compressed four sessions straight.',
      delay: '.16s',
      featured: false,
    },
    {
      topic: 'Leadership churn',
      bull: 'Leadership transitions alongside a major divestment usually signal strategic focus, not dysfunction.',
      bear: 'A director resignation and a management change, in the same week as a weak core print. That is execution risk at the worst moment.',
      delay: '.24s',
      featured: false,
    },
  ];

  // Alternating vertical offset breaks the four-equal-boxes-in-a-row default
  // (only at lg and up -- a staggered grid on a 2-col tablet layout would
  // just look broken, so the offset is gated to the width where 4 columns
  // actually render side by side).
  const offsetClass = ['lg:mt-0', 'lg:mt-7', 'lg:mt-0', 'lg:mt-7'];

  return (
    <section className="max-w-screen-xl mx-auto px-6 lg:px-8 py-16 lg:py-20">
      <div ref={headingRef} className="u-reveal max-w-2xl">
        <h2 className="font-tight font-black text-[#010101] text-4xl sm:text-5xl leading-[1.02] tracking-[-0.025em]">
          The disagreement, out in the open.
        </h2>
        <p className="copy text-[#747474] mt-3">
          Bull and bear read the same filings and land in opposite places. Here is what they
          actually argued about SIEMENS.NS.
        </p>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-5 mt-10">
        {points.map((point, i) => (
          <div
            key={point.topic}
            ref={cardRefs[i]}
            className={`u-reveal argue-card ${point.featured ? 'argue-card--featured' : ''} ${offsetClass[i]}`}
            style={{ ['--delay' as string]: point.delay }}
          >
            {point.featured && <span className="argue-card__badge">The manager&rsquo;s call</span>}

            <p className="argue-card__topic">{point.topic}</p>

            <div className="argue-card__exchange">
              <div className="argue-card__side argue-card__side--bull">
                <span className="argue-card__who">Bull</span>
                <p className="argue-card__line">{point.bull}</p>
              </div>
              <div className="argue-card__seam" aria-hidden="true" />
              <div className="argue-card__side argue-card__side--bear">
                <span className="argue-card__who">Bear</span>
                <p className="argue-card__line">{point.bear}</p>
              </div>
            </div>

            {point.featured && (
              <a href="/stock/SIEMENS.NS/2026-08-12" className="argue-card__cta">
                Read the full case
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </a>
            )}
          </div>
        ))}
      </div>

      <p className="text-xs text-[#676D80] mt-6">
        From a real analysis of SIEMENS.NS. The research manager ruled on the margin question
        (the LVM gain, above) and sided with the bear.
      </p>
    </section>
  );
}

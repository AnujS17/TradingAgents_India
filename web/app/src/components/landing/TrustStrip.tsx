'use client';

import type { ReactNode } from 'react';
import { useScrollReveal } from '@/lib/scroll-reveal';
import { CashReserveBar, EventTimeline, ProfitDipCallout, RsiGauge } from './TrustStripVisuals';

// Rewritten 2026-08-22, restyled 2026-08-28 (design review: too much
// text, no visual point-of-entry). Bull/bear read the SAME contested
// points from the SIEMENS.NS fixture (api/fixtures/sample_run.json) as
// before; what changed is that each card now leads with a diagram of the
// real number or event sequence the argument is actually about --
// an RSI gauge, a balance-sheet stat pair, a PAT/one-off reconciliation
// badge, a leadership-churn timeline -- and the bull/bear lines were
// tightened to one clause each, since the visual now carries the fact
// and the text only needs to carry the interpretation.
//
// Not a literal "Round 1 of 3": the backend's InvestDebateState tracks
// bull_history/bear_history/count internally (tradingagents/agents/utils/
// agent_states.py), but the API only exposes the two consolidated final
// essays (Reports.bull_case/bear_case), not a per-round array. Labelling
// these as numbered rounds would assert a structure the data doesn't back
// -- DESIGN.md §6 "never invent numbers" extends to never inventing
// structure, and the same discipline is why every value in the four
// visuals below is one already present in the original bull/bear prose,
// not a new figure.
//
// Deliberately NOT dark-glass (that would duplicate Deck.tsx two sections
// down) and NOT green/red on the shared palette (DESIGN.md §1: reserved
// for price direction). The one exception is the RSI gauge's zone tint,
// a domain convention documented in TrustStripVisuals.tsx, not a page
// accent.
export function TrustStrip() {
  const headingRef = useScrollReveal<HTMLDivElement>();
  const cardRefs = [
    useScrollReveal<HTMLDivElement>(),
    useScrollReveal<HTMLDivElement>(),
    useScrollReveal<HTMLDivElement>(),
    useScrollReveal<HTMLDivElement>(),
  ] as const;

  const points: {
    topic: string;
    bull: string;
    bear: string;
    delay: string;
    featured: boolean;
    visual: ReactNode;
  }[] = [
    {
      topic: 'The LVM gain',
      bull: 'Portfolio engineering, not deterioration — the exit was deliberate.',
      bear: 'Margins should have risen. They collapsed instead.',
      delay: '0s',
      featured: true,
      // "~18-19%" is the bear_case text's own figure ("adjusted PAT fell
      // ~18-19% to ₹343 crore") -- not a number invented to match an
      // example percentage.
      visual: <ProfitDipCallout headline="Profit dipped 18–19%" reasonTag="Due to US-Iran war tensions." />,
    },
    {
      topic: 'The balance sheet',
      bull: 'Funds growth without leverage — no debt required.',
      bear: 'Cash sits idle at 93× — the growth story is not cash-funded.',
      delay: '.08s',
      featured: false,
      // Fill % is a schematic "looks substantial" cue, not a literal
      // proportion of any real maximum — same "not accurate by scale"
      // discipline as the research page's trade-plan chart. changeBadge
      // is real: bear_case text states operating cash flow collapsed
      // from ₹1,655cr to ₹375cr, a 77% YoY drop -- (1655-375)/1655.
      visual: (
        <CashReserveBar
          reserveLabel="₹6,800cr net cash saved"
          reserveFillPct={82}
          burnLabel="₹6cr burned this year"
          changeBadge="Op. cash flow −77% YoY"
        />
      ),
    },
    {
      topic: 'Technical analysis',
      bull: 'Textbook overbought unwinding, not distribution.',
      bear: 'Failed to close above the band — momentum is fading.',
      delay: '.16s',
      featured: false,
      visual: <RsiGauge from={76} to={66} />,
    },
    {
      topic: 'Leadership churn',
      bull: 'Signals strategic focus, not dysfunction.',
      bear: 'Same week as a weak core print — execution risk at the worst moment.',
      delay: '.24s',
      featured: false,
      // Divestment is the company's own proactive move (green/up) --
      // ties back to the LVM card's bull framing. Director exits and
      // weak print are unambiguously negative outcomes (red/down). New
      // mgmt stays neutral: its valence is the literal subject of this
      // card's bull/bear disagreement, so coloring it would silently
      // pick a side.
      visual: (
        <EventTimeline
          steps={[
            { label: 'Divestment', tone: 'up' },
            { label: 'Director exits', tone: 'down' },
            { label: 'New mgmt', tone: 'neutral' },
            { label: 'Weak print', tone: 'down' },
          ]}
        />
      ),
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

            <div className="argue-card__visual">{point.visual}</div>

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

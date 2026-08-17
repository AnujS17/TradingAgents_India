'use client';

import { useScrollReveal } from '@/lib/scroll-reveal';

// Ported from web/design/landing-fintech/index.html lines 906-980 (the
// "USE CASES" section, id="use-cases"): a light section, a static 2x2 card
// grid, standard scroll-reveal (.u-reveal / useScrollReveal) staggered by
// the source's --delay values (0s, .08s, .16s, .24s) — same mechanism as
// TrustStrip. No other motion.
export function UseCases() {
  const headingRef = useScrollReveal<HTMLDivElement>();
  const cardRefs = [
    useScrollReveal<HTMLDivElement>(),
    useScrollReveal<HTMLDivElement>(),
    useScrollReveal<HTMLDivElement>(),
    useScrollReveal<HTMLDivElement>(),
  ] as const;

  const items = [
    {
      title: 'Before you buy',
      body: (
        <>
          Read the bear case <em>before</em> you enter, not after the position moves against
          you. Bench forces the strongest argument against your idea into the open.
        </>
      ),
      delay: '0s',
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            d="M5 12h14M13 6l6 6-6 6"
            stroke="white"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      ),
    },
    {
      title: 'Pressure-testing a tip',
      body: 'Someone in a group chat is very confident about a stock. Run it, and see whether the filings and the numbers actually back the story.',
      delay: '.08s',
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M12 8v5M12 16.5v.01" stroke="white" strokeWidth="2.2" strokeLinecap="round" />
          <circle cx="12" cy="12" r="9" stroke="white" strokeWidth="1.9" />
        </svg>
      ),
    },
    {
      title: 'Reviewing what you hold',
      body: 'Results season changed the numbers. Check whether the thesis you originally bought on is still standing, or quietly broke two quarters ago.',
      delay: '.16s',
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M3 3v18h18" stroke="white" strokeWidth="2" strokeLinecap="round" />
          <path
            d="M7 15l4-5 3 3 5-7"
            stroke="white"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      ),
    },
    {
      title: 'Learning how to read one',
      body: 'Watch a bull and a bear read the same order book and reach opposite conclusions. It teaches the reasoning, not just the rating.',
      delay: '.24s',
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M4 6h16M4 12h10M4 18h13" stroke="white" strokeWidth="2.2" strokeLinecap="round" />
        </svg>
      ),
    },
  ];

  return (
    <section id="use-cases" className="max-w-screen-xl mx-auto px-6 lg:px-8 py-20 lg:py-28">
      <div ref={headingRef} className="u-reveal max-w-2xl">
        <h2 className="font-tight font-black text-[#010101] text-4xl sm:text-5xl mt-3 leading-[1.02] tracking-[-0.025em]">
          Four moments this is built for.
        </h2>
        <p className="text-[#757575] mt-4 leading-relaxed">
          Not a screener and not a tip sheet. It is a second opinion that argues with itself
          before answering you.
        </p>
      </div>

      <div className="grid md:grid-cols-2 gap-5 mt-12">
        {items.map((item, i) => (
          <div
            key={item.title}
            ref={cardRefs[i]}
            className="u-reveal rounded-2xl border border-[#EBEBEB] bg-white p-7 hover:border-[#1C6FE6]/40 hover:shadow-[0px_4px_32px_0px_rgba(28,111,230,0.10)] transition-all duration-300"
            style={{ ['--delay' as string]: item.delay }}
          >
            <div className="flex items-start gap-4">
              <div className="w-11 h-11 rounded-xl grad-navy icon-tile-shadow flex items-center justify-center shrink-0">
                {item.icon}
              </div>
              <div>
                <h3 className="font-tight font-extrabold text-[#010101] text-xl leading-tight">
                  {item.title}
                </h3>
                <p className="text-sm text-[#747474] mt-2.5 leading-relaxed">{item.body}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

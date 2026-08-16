'use client';

import { useScrollReveal } from '@/lib/scroll-reveal';

// Ported from web/design/landing-fintech/index.html lines 660-696 (the
// "TRUST STRIP (bolder)" section): a light 4-up grid of static claims, each
// with a 44px accent icon tile. No special motion beyond the standard
// scroll-reveal (.u-reveal / useScrollReveal), staggered by the source's
// --delay values (0s, .08s, .16s, .24s).
export function TrustStrip() {
  const cardRefs = [
    useScrollReveal<HTMLDivElement>(),
    useScrollReveal<HTMLDivElement>(),
    useScrollReveal<HTMLDivElement>(),
    useScrollReveal<HTMLDivElement>(),
  ] as const;

  const items = [
    {
      title: 'No number without a source',
      body: 'Every figure links back to the filing or headline it was read from.',
      delay: '0s',
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="12" cy="12" r="9" stroke="white" strokeWidth="1.9" />
          <path d="M9 12l2 2 4-4" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ),
    },
    {
      title: 'Both sides, one data set',
      body: 'Bull and bear argue from identical evidence, so a split means something.',
      delay: '.08s',
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M12 4v16" stroke="white" strokeWidth="2" strokeLinecap="round" />
          <path d="M5 9h4M5 15h4M15 9h4M15 15h4" stroke="white" strokeWidth="2" strokeLinecap="round" />
        </svg>
      ),
    },
    {
      title: 'Built for Indian markets',
      body: 'NSE and BSE filings, Indian news and forums, reported in ₹.',
      delay: '.16s',
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            d="M3 17l5-5 3.5 3.5L21 6"
            stroke="white"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      ),
    },
    {
      title: 'Research, never a tip',
      body: 'You get the argument and the evidence. The decision stays yours.',
      delay: '.24s',
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M12 2l8 4v6c0 5-3.4 8.5-8 10-4.6-1.5-8-5-8-10V6l8-4z" stroke="white" strokeWidth="1.9" strokeLinejoin="round" />
        </svg>
      ),
    },
  ];

  return (
    <section className="max-w-screen-xl mx-auto px-6 lg:px-8 py-16 lg:py-20">
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-5">
        {items.map((item, i) => (
          <div
            key={item.title}
            ref={cardRefs[i]}
            className="u-reveal rounded-2xl border border-[#EBEBEB] bg-white p-6 hover:border-[#1C6FE6]/40 transition-colors"
            style={{ ['--delay' as string]: item.delay }}
          >
            <div className="w-11 h-11 rounded-xl bg-[#1C6FE6] icon-tile-shadow flex items-center justify-center mb-4">
              {item.icon}
            </div>
            <h3 className="font-tight font-extrabold text-[#010101] text-lg leading-tight">{item.title}</h3>
            <p className="text-sm text-[#747474] mt-2 leading-relaxed">{item.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

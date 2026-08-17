'use client';

import { useState } from 'react';
import { useScrollReveal } from '@/lib/scroll-reveal';

// Ported from web/design/landing-fintech/index.html lines 1133-1204 (the
// "#faq" section). The accordion's own JS (index.html ~1326-1332) just
// toggles `is-open` on whichever `.u-acc` was clicked — it never closes the
// others — so any number of items can be open at once. That's a Set of open
// indices below, not a single "open index": a single-index model would
// silently turn this into a one-at-a-time accordion, which is not what the
// source does. The first item starts open (`class="u-acc is-open"` /
// `aria-expanded="true"` in the source), the rest start closed.
//
// Uses the `.u-acc-body` max-height transition (--dur-open/--ease-open,
// globals.css, Task 1) rather than grid-template-rows — DESIGN.md: Chrome
// can't interpolate 0fr->1fr in an auto-height grid.
const FAQ_ITEMS = [
  {
    q: 'Is this investment advice?',
    a: (
      <>
        No. Bench is a research tool. It shows the case for and against a stock, and the
        reasoning behind a rating. It does not tell you what to do with your money.
      </>
    ),
  },
  {
    q: 'How do you avoid hallucinated numbers?',
    a: (
      <>
        Every figure the agents cite is pulled from a real filing, statement, or article first.
        The model never fills in a plausible-looking number. If the evidence doesn&rsquo;t
        support a field like entry price, it&rsquo;s left blank instead of guessed.
      </>
    ),
  },
  {
    q: 'What happens when two runs disagree?',
    a: (
      <>
        You&rsquo;ll see it. Repeat runs of the same question, on the same day&rsquo;s data,
        can genuinely land on different ratings when the evidence is close. Bench surfaces that
        split rather than quietly showing whichever run finished last.
      </>
    ),
  },
  {
    q: 'How long does a run take?',
    a: (
      <>
        A fast run finishes in about 4 minutes. A detailed run, with deeper analyst passes,
        takes closer to 14. You can leave and come back; the link stays live.
      </>
    ),
  },
  {
    q: 'Which markets and exchanges are covered?',
    a: (
      <>
        Indian-listed equities on the NSE and BSE. Prices, filings and news are all pulled and
        reported in ₹.
      </>
    ),
  },
];

export function Faq() {
  const headingRef = useScrollReveal<HTMLDivElement>();
  const listRef = useScrollReveal<HTMLDivElement>();

  // Matches the source: independent per-item toggle, so a Set of open
  // indices (not one "active" index) — see comment above.
  const [openIndices, setOpenIndices] = useState<ReadonlySet<number>>(() => new Set([0]));

  function toggle(i: number) {
    setOpenIndices((prev) => {
      const next = new Set(prev);
      if (next.has(i)) {
        next.delete(i);
      } else {
        next.add(i);
      }
      return next;
    });
  }

  return (
    <section id="faq" className="max-w-screen-xl mx-auto px-6 lg:px-8 py-20 lg:py-28">
      <div ref={headingRef} className="u-reveal max-w-2xl mx-auto text-center">
        <h2 className="font-tight font-black text-[#010101] text-4xl sm:text-5xl mt-3 tracking-[-0.025em]">
          Questions, answered plainly.
        </h2>
      </div>

      <div
        ref={listRef}
        className="u-reveal max-w-2xl mx-auto mt-10 divide-y divide-[#EBEBEB] border-y border-[#EBEBEB]"
      >
        {FAQ_ITEMS.map((item, i) => {
          const isOpen = openIndices.has(i);
          const panelId = `faq-panel-${i}`;
          return (
            <div key={item.q} className={`u-acc${isOpen ? ' is-open' : ''}`}>
              <button
                type="button"
                aria-expanded={isOpen}
                aria-controls={panelId}
                onClick={() => toggle(i)}
                className="u-acc-btn w-full flex items-center justify-between gap-4 py-5 text-left"
              >
                <span className="font-tight font-bold text-[#010101] text-base">{item.q}</span>
                <svg
                  className="u-acc-chev shrink-0"
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  aria-hidden="true"
                >
                  <path
                    d="M6 9l6 6 6-6"
                    stroke="#757575"
                    strokeWidth="2.2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
              <div id={panelId} className="u-acc-body">
                <div>
                  <p className="text-sm text-[#747474] leading-relaxed pb-5">{item.a}</p>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

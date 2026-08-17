'use client';

import { useState, type CSSProperties } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { countWords } from '@/lib/format';
import type { Reports } from '@/lib/api-client/client';

// Ported from web/design/research/index.html lines 610-767 ("THE FULL
// RECORD"). Two things the source does that this port deliberately does
// not:
//
// 1. Bar lengths (`--len`) and word counts in the source are hand-tuned to
//    one SIEMENS.NS run (`.25`, `.56`, `.84`, `1`, ...). Here both are
//    computed from the real `Reports` payload of whatever run is on screen
//    (see `wordCounts`/`maxWordCount` below).
// 2. Panel bodies in the source are a hand-truncated "opening extract" with
//    a `.rep__more` footer explaining the truncation. That's a static-page
//    device; a real run's full report is rendered instead, and `.rep__doc`'s
//    own `max-height: 340px; overflow-y: auto` (globals.css, Task 1) does
//    the length-honesty job the source's footer prose describes.
//
// Scope decision carried from the plan's AskUserQuestion: the evidence-trace
// drill-down (`.fig`/`.trace`) and the structured risk-comparison table
// (`.rk`, per-stance grid) are not built here. `bull_case`, `bear_case`, and
// `risk_debate` render as three more `.rep` rows in this same accordion,
// exactly like the other seven reports — not as the source's `.duel` ledger
// or `.rk` table. Both require structured per-number/per-stance data the
// API's flat markdown strings don't carry.

const REPORT_LABELS: Record<keyof Reports, string> = {
  market: 'Market',
  sentiment: 'Sentiment',
  news: 'News',
  fundamentals: 'Fundamentals',
  bull_case: 'Bull case',
  bear_case: 'Bear case',
  investment_plan: 'Investment plan',
  trader_plan: 'Trader plan',
  risk_debate: 'Risk debate',
  final_decision: 'Final decision',
};

// Conclusion first, then evidence — final_decision opens by default so a
// reader sees a landing summary without needing to expand ten sections.
// Matches the old ReportsAccordion's REPORT_ORDER; the source's own markup
// order (market, fundamentals, news, sentiment, bull, bear, plan, trader,
// risk, final) is not used here, per the plan's evidence-first framing.
const REPORT_ORDER: (keyof Reports)[] = [
  'final_decision',
  'investment_plan',
  'bull_case',
  'bear_case',
  'trader_plan',
  'risk_debate',
  'market',
  'sentiment',
  'news',
  'fundamentals',
];

const TOTAL_REPORT_FIELDS = 10;

const CHEVRON = (
  <svg className="rep__chev" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M9 5l7 7-7 7" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

// The panel's open max-height is a fixed CSS-transitionable value, not a
// per-row scrollHeight measurement (the source's vanilla-JS
// `panel.style.maxHeight = panel.scrollHeight + 'px'`, lines ~892-893). It
// only needs to clear `.rep__doc`'s own 340px cap plus its padding
// (4px + 20px) — 400px leaves comfortable headroom without depending on a
// ref/layout-effect measurement, the same fixed-value approach Faq.tsx uses
// for `.u-acc-body`.
const OPEN_PANEL_MAX_HEIGHT = '400px';

export function ReportsRecord({ reports }: { reports: Reports | null }) {
  // Independent per-row toggle (any number open at once), matching the
  // source's report-disclosure JS (lines 935-948), which only ever flips the
  // row that was clicked and never closes the others.
  const [openKeys, setOpenKeys] = useState<ReadonlySet<keyof Reports>>(
    () => new Set(reports?.final_decision ? (['final_decision'] as const) : []),
  );

  if (!reports) return null;

  const sections = REPORT_ORDER.filter((key) => reports[key]);
  if (sections.length === 0) return null;

  const wordCounts = new Map<keyof Reports, number>(
    sections.map((key) => [key, countWords(reports[key] as string)]),
  );
  const maxWordCount = Math.max(...wordCounts.values());
  const totalWordCount = [...wordCounts.values()].reduce((sum, n) => sum + n, 0);

  function toggle(key: keyof Reports) {
    setOpenKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  return (
    <section id="record" aria-label="The full record" className="mt-8 rounded-[28px] border border-[#E0E1E2] bg-white p-7 lg:p-9">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="font-tight font-black text-[#010101] text-2xl tracking-[-0.02em]">The full record</h2>
        <p className="font-tight font-bold text-sm text-[#676D80] tabular-nums">
          {sections.length} of {TOTAL_REPORT_FIELDS} &middot; {totalWordCount.toLocaleString('en-IN')} words
        </p>
      </div>
      <p className="copy text-[#6F6F6F] mt-1 measure">
        Bar length is the real length of each document, so a long report never looks like a short one. Open any row
        to read it.
      </p>

      <div className="mt-6">
        {sections.map((key) => {
          const isOpen = openKeys.has(key);
          const wordCount = wordCounts.get(key) ?? 0;
          // Guard against dividing by zero: if the longest present report is
          // somehow 0 words (all-whitespace body), every bar resolves to 0
          // rather than NaN. With one report present, maxWordCount is that
          // report's own count, so `--len` resolves to a full-width bar (1),
          // not NaN.
          const barLength = maxWordCount === 0 ? 0 : wordCount / maxWordCount;
          const panelId = `doc-${key}`;

          return (
            <div key={key}>
              <button
                type="button"
                className="rep"
                aria-expanded={isOpen}
                aria-controls={panelId}
                onClick={() => toggle(key)}
              >
                <span className="rep__t">
                  {CHEVRON}
                  {REPORT_LABELS[key]}
                </span>
                <span className="rep__w">{wordCount.toLocaleString('en-IN')} words</span>
                <span className="rep__bar">
                  <i style={{ '--len': String(barLength) } as CSSProperties} />
                </span>
              </button>
              <div
                className="rep__panel"
                id={panelId}
                role="region"
                aria-label={REPORT_LABELS[key]}
                style={{ maxHeight: isOpen ? OPEN_PANEL_MAX_HEIGHT : '0px' }}
              >
                <div className="rep__doc">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{reports[key] as string}</ReactMarkdown>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

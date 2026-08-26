'use client';

import { useState, type CSSProperties } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { countWords, excerptFor, readMinutes } from '@/lib/format';
import { ratingColor } from '@/lib/rating-color';
import type { Reports, Verdict } from '@/lib/api-client/client';

// Ported from web/design/research/index.html lines 610-767 ("THE FULL
// RECORD"). Two things the source does that this port deliberately does
// not:
//
// 1. Word counts in the source are hand-tuned to one SIEMENS.NS run. Here
//    they're computed from the real `Reports` payload of whatever run is on
//    screen (see `wordCounts` below).
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
//
// 2026-08-23 rework: ten flat rows in one list read as plain and undifferentiated
// (design review). Grouped into the same five teams TheDesk's sidebar already
// shows — Portfolio / Trader / Research / Risk panel / Analysts — which is not
// an invented taxonomy, it's the one structure already true of this run
// (tradingagents/graph/setup.py's five-stage pipeline). Groups are ordered
// conclusion-first, preserving the flat version's "final_decision opens by
// default" intent: Portfolio and Trader (the calls) lead, Research and Risk
// panel (the arguments) follow, Analysts (the raw inputs) close the list.

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

const GROUPS: { label: string; keys: (keyof Reports)[] }[] = [
  { label: 'Portfolio', keys: ['final_decision'] },
  { label: 'Trader', keys: ['trader_plan'] },
  { label: 'Research', keys: ['investment_plan', 'bull_case', 'bear_case'] },
  { label: 'Risk panel', keys: ['risk_debate'] },
  { label: 'Analysts', keys: ['market', 'sentiment', 'news', 'fundamentals'] },
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

// Row accent by what the report actually is, not one flat blue for all ten.
// bull_case/bear_case reuse the navy/#1B6FA8 pair the rest of the page uses
// for that same distinction (TrustStrip's argument cards, the contested
// ledger). investment_plan/final_decision/trader_plan are colored by the
// verdict they carry (2026-08-23 rating-color exception, src/lib/rating-
// color.ts) — the same rating badge from TheCall echoing down into the
// record it was drawn from. The four neutral analyst reports and the
// three-way risk_debate get accent-1, not accent-3: accent-3 (#3DA2F1) was
// only ever verified as a background fill (the old length-bar), and
// measures 2.75:1 as text on white — a real failure caught rendering the
// new "X min read" chip in this color. accent-1 (#1C6FE6) is the same
// family, one step darker, 4.7:1.
function barColor(key: keyof Reports, verdict: Verdict | null): string {
  if (key === 'bull_case') return 'var(--navy)';
  if (key === 'bear_case') return '#1B6FA8';
  if (key === 'investment_plan' || key === 'final_decision') return ratingColor(verdict?.rating).text;
  if (key === 'trader_plan') return ratingColor(verdict?.levels?.action).text;
  return 'var(--accent-1)';
}

export function ReportsRecord({ reports, verdict = null }: { reports: Reports | null; verdict?: Verdict | null }) {
  // Independent per-row toggle (any number open at once), matching the
  // source's report-disclosure JS (lines 935-948), which only ever flips the
  // row that was clicked and never closes the others.
  const [openKeys, setOpenKeys] = useState<ReadonlySet<keyof Reports>>(
    () => new Set(reports?.final_decision ? (['final_decision'] as const) : []),
  );

  if (!reports) return null;

  const wordCounts = new Map<keyof Reports, number>(
    (Object.keys(REPORT_LABELS) as (keyof Reports)[])
      .filter((key) => reports[key])
      .map((key) => [key, countWords(reports[key] as string)]),
  );
  if (wordCounts.size === 0) return null;

  const totalWordCount = [...wordCounts.values()].reduce((sum, n) => sum + n, 0);

  const groups = GROUPS.map((group) => ({
    ...group,
    keys: group.keys.filter((key) => wordCounts.has(key)),
  })).filter((group) => group.keys.length > 0);

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
          {wordCounts.size} of {TOTAL_REPORT_FIELDS} &middot; {totalWordCount.toLocaleString('en-IN')} words
        </p>
      </div>
      <p className="copy text-[#6F6F6F] mt-1 measure">
        Grouped by who wrote it, conclusion first. Each row opens with the report&rsquo;s own summary; open it to read
        the rest.
      </p>

      <div className="mt-7 flex flex-col gap-9">
        {groups.map((group) => {
          const groupWords = group.keys.reduce((sum, key) => sum + (wordCounts.get(key) ?? 0), 0);

          return (
            <div key={group.label}>
              <div className="flex items-baseline justify-between gap-3 mb-2.5">
                <p className="rep-group__label">{group.label}</p>
                <p className="rep-group__count">{groupWords.toLocaleString('en-IN')} words</p>
              </div>
              <div className="rep-group__rows">
                {group.keys.map((key) => {
                  const isOpen = openKeys.has(key);
                  const wordCount = wordCounts.get(key) ?? 0;
                  const panelId = `doc-${key}`;
                  const color = barColor(key, verdict);
                  const excerpt = excerptFor(reports[key] as string);

                  return (
                    <div key={key}>
                      <button
                        type="button"
                        className="rep"
                        aria-expanded={isOpen}
                        aria-controls={panelId}
                        onClick={() => toggle(key)}
                        style={{ '--rep-color': color } as CSSProperties}
                      >
                        <span className="rep__top">
                          <span className="rep__t">
                            {CHEVRON}
                            {REPORT_LABELS[key]}
                          </span>
                          <span className="rep__meta">
                            <span className="rep__read">{readMinutes(wordCount)} min read</span>
                            <span className="rep__w">{wordCount.toLocaleString('en-IN')} words</span>
                          </span>
                        </span>
                        {/* The point of this whole redesign: a reader sees the
                            report's own Executive Summary (or its opening line)
                            without expanding the row — not just a title and a
                            word count. Hidden once open: the full text right
                            below makes a truncated repeat of itself redundant. */}
                        {!isOpen && <span className="rep__excerpt">{excerpt}</span>}
                      </button>
                      <div
                        className="rep__panel"
                        id={panelId}
                        role="region"
                        aria-label={REPORT_LABELS[key]}
                        style={{ maxHeight: isOpen ? OPEN_PANEL_MAX_HEIGHT : '0px' }}
                        // `max-height: 0; overflow: hidden` alone hides the
                        // panel visually but leaves its content in the a11y
                        // tree and tab order (final review finding #2) — a
                        // screen reader or keyboard user can still reach a
                        // closed report's links/text. `inert` removes the
                        // subtree from both while the max-height transition
                        // still animates normally (unlike `hidden`, which
                        // would kill it).
                        inert={!isOpen}
                      >
                        <div className="rep__doc">
                          {/* del: 'span' -- a reasoning model occasionally leaks
                              self-revision markup (~~old clause~~ new clause) into
                              a decision field; GFM's <del> renders that as a
                              browser-default strikethrough, which reads as a
                              rendering bug, not an edit. A bare span keeps the
                              text (removing it outright can leave a sentence
                              missing its object) without the struck-through
                              styling. Root cause fixed in schemas.py's field
                              descriptions; this is the backstop for whatever
                              still slips through. */}
                          <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ del: 'span' }}>
                            {reports[key] as string}
                          </ReactMarkdown>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

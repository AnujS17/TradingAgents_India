'use client';

import { useState } from 'react';
import Link from 'next/link';
import { excerptFor, formatPrice } from '@/lib/format';
import { ratingColor, DirectionArrow } from '@/lib/rating-color';
import { ReportsRecordBody } from '@/components/research/ReportsRecord';
import type { RunDetail } from '@/lib/api-client/client';

// A compact sibling of TheCall.tsx for the compare page's two-column
// layout -- same fields (rating, action, entry, stop, exit, current price,
// horizon), smaller type scale, no ruler (the ruler's job -- "where does
// this rating sit on the five-tier scale" -- is redundant once two ratings
// are already sitting side by side for direct comparison).
export function CompareCard({ run }: { run: RunDetail }) {
  // Local to this card, not the URL: expanding one side's report must never
  // navigate away from the comparison, which is the whole point of this
  // toggle existing instead of the plain /runs/{id} link it replaced.
  const [showFullReport, setShowFullReport] = useState(false);

  const verdict = run.verdict;
  const levels = verdict?.levels ?? {};
  const color = ratingColor(verdict?.rating);
  const excerpt = run.reports?.final_decision ? excerptFor(run.reports.final_decision, 240) : null;

  return (
    <div className="rounded-[28px] border border-[#E0E1E2] bg-white p-6 lg:p-7 min-w-0">
      <div>
        <Link
          href={`/runs/${run.id}`}
          className="font-tight font-black text-[#010101] text-2xl tracking-[-0.02em] hover:text-[#1C6FE6] transition-colors"
        >
          {run.ticker}
        </Link>
        <p className="copy text-[#6F6F6F] mt-1">
          {run.analysis_date} &middot; {run.profile === 'detailed' ? 'Detailed' : 'Fast'} &middot; {run.created_at.slice(0, 16).replace('T', ' ')}
        </p>
      </div>

      <div
        className="mt-5 rounded-2xl border flex items-center gap-3 px-4 py-3"
        style={{ backgroundColor: color.bg, borderColor: color.border }}
      >
        <span
          className="w-8 h-8 rounded-full flex items-center justify-center shrink-0"
          style={{ backgroundColor: color.text, color: '#fff' }}
        >
          <DirectionArrow direction={color.direction} />
        </span>
        <div>
          <p className="font-tight text-[10px] font-bold tracking-wide" style={{ color: color.text }}>
            RATING
          </p>
          <p
            className="font-tight font-black text-xl tracking-[-0.01em] leading-none mt-0.5"
            style={{ color: color.text }}
          >
            {verdict?.rating ?? 'Not set'}
          </p>
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-px bg-[#EBEBEB] rounded-2xl overflow-hidden mt-5">
        <div className="bg-white p-3.5">
          <dt className="font-tight text-[10px] font-bold tracking-wide text-[#676D80]">CURRENT PRICE</dt>
          <dd className="font-tight font-bold text-[#010101] text-base mt-0.5">{formatPrice(verdict?.current_price)}</dd>
        </div>
        <div className="bg-white p-3.5">
          <dt className="font-tight text-[10px] font-bold tracking-wide text-[#676D80]">ACTION</dt>
          <dd className="font-tight font-bold text-[#010101] text-base mt-0.5">{levels.action ?? 'Not set'}</dd>
        </div>
        <div className="bg-white p-3.5">
          <dt className="font-tight text-[10px] font-bold tracking-wide text-[#676D80]">ENTRY</dt>
          <dd className="font-tight font-semibold text-[#676D80] text-base mt-0.5">{formatPrice(levels.entry_price)}</dd>
        </div>
        <div className="bg-white p-3.5">
          <dt className="font-tight text-[10px] font-bold tracking-wide text-[#676D80]">STOP</dt>
          <dd className="font-tight font-semibold text-[#676D80] text-base mt-0.5">{formatPrice(levels.stop_loss)}</dd>
        </div>
        <div className="bg-white p-3.5">
          <dt className="font-tight text-[10px] font-bold tracking-wide text-[#676D80]">EXIT</dt>
          <dd className="font-tight font-semibold text-[#676D80] text-base mt-0.5">{formatPrice(verdict?.price_target)}</dd>
        </div>
        <div className="bg-white p-3.5">
          <dt className="font-tight text-[10px] font-bold tracking-wide text-[#676D80]">HORIZON</dt>
          <dd className="font-tight font-bold text-[#010101] text-base mt-0.5">{verdict?.time_horizon ?? 'Not set'}</dd>
        </div>
      </dl>

      {excerpt && <p className="copy text-[#6F6F6F] mt-5 measure">{excerpt}</p>}

      {/* Toggles in place rather than a Link to /runs/{id} -- the entire
          point of comparing two runs is having both on screen together;
          navigating away to read one's full report would defeat that, which
          is exactly what the plain-link version of this button used to do. */}
      <button
        type="button"
        onClick={() => setShowFullReport((prev) => !prev)}
        aria-expanded={showFullReport}
        className="font-tight font-bold text-sm text-[#1C6FE6] hover:text-[#237FFB] transition-colors mt-5"
      >
        {showFullReport ? 'Hide full report ↑' : 'View full report ↓'}
      </button>

      {showFullReport && (
        <div className="mt-5 pt-5 border-t border-[#EBEBEB]">
          <ReportsRecordBody reports={run.reports ?? null} verdict={verdict ?? null} idPrefix={run.id} />
        </div>
      )}
    </div>
  );
}

import Link from 'next/link';
import type { RunSummary } from '@/lib/api-client/client';

// Shared by RecentRunsSection (home page teaser) and /runs (the full
// browsing page) so the two never drift apart. Style carried over verbatim
// from RecentRunsSection's original card: rounded-2xl (DESIGN.md §3), .copy
// text class (§2), the accent-1 hover border used elsewhere for card links
// (e.g. TrustStrip).
export function RunCard({ run }: { run: RunSummary }) {
  return (
    <Link
      href={`/runs/${run.id}`}
      className="block rounded-2xl border border-[#EBEBEB] p-5 hover:border-[#1C6FE6] transition-colors"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="font-tight font-bold text-[#010101]">{run.ticker}</p>
        <span className="font-tight text-[11px] font-bold tracking-wide text-[#676D80] shrink-0 mt-0.5">
          {run.profile === 'detailed' ? 'DETAILED' : 'FAST'}
        </span>
      </div>
      <p className="copy text-[#6F6F6F] mt-1">{run.analysis_date} · {run.status}</p>
    </Link>
  );
}

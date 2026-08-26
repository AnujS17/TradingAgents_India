import Link from 'next/link';
import type { RunSummary } from '@/lib/api-client/client';
import { RunCard } from '@/components/RunCard';

// No exact template exists in the reference file for this section — the
// static comp never needed a real "recent runs" list. Built consistent with
// the established system instead: a light section, rounded-2xl cards
// (DESIGN.md §3), .copy text class (§2), and the accent-1 hover border used
// elsewhere for card links (e.g. TrustStrip). Real RunSummary[] data from
// listRuns, not placeholder content.
export function RecentRunsSection({ runs }: { runs: RunSummary[] }) {
  if (runs.length === 0) return null;

  return (
    <section className="py-16 lg:py-20 bg-white">
      <div className="max-w-screen-xl mx-auto px-6 lg:px-8">
        <div className="flex items-end justify-between gap-4">
          <h2 className="font-tight font-black text-[#010101] text-3xl tracking-[-0.02em]">Recent analyses</h2>
          <Link
            href="/runs"
            className="font-tight font-bold text-sm text-[#1C6FE6] hover:text-[#237FFB] transition-colors whitespace-nowrap"
          >
            View all runs →
          </Link>
        </div>
        <ul className="mt-8 grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {runs.map((run) => (
            <li key={run.id}>
              <RunCard run={run} />
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

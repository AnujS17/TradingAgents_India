import Link from 'next/link';
import type { RunSummary } from '@/lib/api-client/client';

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
        <h2 className="font-tight font-black text-[#010101] text-3xl tracking-[-0.02em]">Recent analyses</h2>
        <ul className="mt-8 grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {runs.map((run) => (
            <li key={run.id}>
              <Link
                href={`/runs/${run.id}`}
                className="block rounded-2xl border border-[#EBEBEB] p-5 hover:border-[#1C6FE6] transition-colors"
              >
                <p className="font-tight font-bold text-[#010101]">{run.ticker}</p>
                <p className="copy text-[#6F6F6F] mt-1">{run.analysis_date} · {run.status}</p>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

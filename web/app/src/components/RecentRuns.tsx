import Link from 'next/link';
import type { RunSummary } from '@/lib/api-client/client';

export function RecentRuns({ runs }: { runs: RunSummary[] }) {
  if (runs.length === 0) {
    return <p>No analyses yet.</p>;
  }

  return (
    <section aria-label="Recent runs">
      <h2>Recent analyses</h2>
      <ul>
        {runs.map((run) => (
          <li key={run.id}>
            <Link href={`/runs/${run.id}`}>
              {run.ticker} — {run.analysis_date} — {run.status}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

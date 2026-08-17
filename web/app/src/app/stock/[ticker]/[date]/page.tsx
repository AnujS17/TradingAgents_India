import Link from 'next/link';
import { getRunByTicker, type AnalysisProfile } from '@/lib/api-client/client';
import { RunView } from '@/components/RunView';

export default async function StockPage({
  params,
  searchParams,
}: {
  params: Promise<{ ticker: string; date: string }>;
  searchParams: Promise<{ profile?: string }>;
}) {
  const { ticker, date } = await params;
  // A run is keyed by ticker+date+profile, so without this a `detailed` run is
  // unreachable from its own canonical URL and the page wrongly claims no
  // analysis exists.
  const { profile: requestedProfile } = await searchParams;
  const profile: AnalysisProfile = requestedProfile === 'detailed' ? 'detailed' : 'fast';
  const decodedTicker = decodeURIComponent(ticker);
  const run = await getRunByTicker(decodedTicker, date, profile);

  if (!run) {
    return (
      <main>
        <h1>
          {decodedTicker} — {date}
        </h1>
        <p>No analysis exists yet for this ticker and date.</p>
        <Link href={`/?ticker=${encodeURIComponent(decodedTicker)}&date=${date}`}>Request an analysis</Link>
      </main>
    );
  }

  // RunView (Task 11) now owns the full page shell itself (see the same
  // note in runs/[id]/page.tsx) — no separate <main><h1> wrapper here.
  return <RunView initialRun={run} />;
}

import Link from 'next/link';
import { getRunByTicker } from '@/lib/api-client/client';
import { RunView } from '@/components/RunView';

export default async function StockPage({
  params,
}: {
  params: Promise<{ ticker: string; date: string }>;
}) {
  const { ticker, date } = await params;
  const decodedTicker = decodeURIComponent(ticker);
  const run = await getRunByTicker(decodedTicker, date);

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

  return (
    <main>
      <h1>
        {run.ticker} — {run.analysis_date}
      </h1>
      <RunView initialRun={run} />
    </main>
  );
}

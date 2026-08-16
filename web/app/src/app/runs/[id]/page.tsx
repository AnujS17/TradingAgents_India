import { notFound } from 'next/navigation';
import { ApiError, getRun } from '@/lib/api-client/client';
import { RunView } from '@/components/RunView';

export default async function RunPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ est?: string }>;
}) {
  const { id } = await params;
  // `estimated_seconds` only exists on the 202 body that SearchForm saw; it
  // hands it over here as ?est= so the waiting screen can quote the server's
  // own estimate. A missing or junk value just means no estimate is shown.
  const { est } = await searchParams;
  const estimatedSeconds = Number(est);

  let run;
  try {
    run = await getRun(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <main>
      <h1>
        {run.ticker} — {run.analysis_date}
      </h1>
      <RunView
        initialRun={run}
        estimatedSeconds={Number.isFinite(estimatedSeconds) && estimatedSeconds > 0 ? estimatedSeconds : undefined}
      />
    </main>
  );
}

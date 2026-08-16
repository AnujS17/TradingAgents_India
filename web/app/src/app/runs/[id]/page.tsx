import { notFound } from 'next/navigation';
import { ApiError, getRun } from '@/lib/api-client/client';
import { RunView } from '@/components/RunView';

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

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
      <RunView initialRun={run} />
    </main>
  );
}

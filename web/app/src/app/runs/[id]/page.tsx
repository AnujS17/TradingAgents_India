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

  // RunView (Task 11) now owns the full page shell itself (ResearchNav,
  // RunHeader — which renders its own <h1>{ticker} — and a <main> landmark
  // around the completed-run content, matching HomePage's flat
  // nav/main/footer pattern), so this route no longer wraps it in its own
  // <main><h1> — that wrapper predates RunView owning page chrome and would
  // otherwise nest two <main> landmarks and duplicate the ticker heading.
  return (
    <RunView
      initialRun={run}
      estimatedSeconds={Number.isFinite(estimatedSeconds) && estimatedSeconds > 0 ? estimatedSeconds : undefined}
    />
  );
}

import Link from 'next/link';
import { notFound } from 'next/navigation';
import { ApiError, getRun, type RunDetail } from '@/lib/api-client/client';
import { CompareCard } from '@/components/CompareCard';

// Same dedicated header as /runs/page.tsx and for the same reason: neither
// ResearchNav (needs one run's AnalysisProfile -- meaningless when two runs
// may have different profiles) nor SiteNav (home-page-only in-page anchors)
// fits a route that isn't about a single run.
function ComparePageHeader() {
  return (
    <header
      className="sticky top-0 z-50 backdrop-blur-md border-b border-white/10"
      style={{ backgroundColor: 'rgba(5,10,24,.94)' }}
    >
      <div className="max-w-screen-xl mx-auto px-6 lg:px-8 h-16 flex items-center gap-6">
        <Link href="/" className="flex items-center gap-2.5 font-tight font-extrabold text-lg text-white shrink-0">
          <span className="w-8 h-8 rounded-lg grad-navy flex items-center justify-center text-white text-sm font-black">
            B
          </span>
          TickerInvest
        </Link>
        <span className="text-white/30">/</span>
        <span className="font-tight font-bold text-white/85">Compare</span>
      </div>
    </header>
  );
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <>
      <ComparePageHeader />
      <main className="max-w-screen-xl mx-auto px-6 lg:px-8 py-10">
        <div className="rounded-[28px] border border-[#E0E1E2] bg-white p-7 lg:p-9 max-w-2xl mx-auto text-center">
          <h1 className="font-tight font-black text-[#010101] text-2xl tracking-[-0.02em]">{title}</h1>
          <p className="copy text-[#6F6F6F] mt-2">{body}</p>
          <Link
            href="/runs"
            className="font-tight font-bold text-sm text-[#1C6FE6] hover:text-[#237FFB] transition-colors mt-5 inline-block"
          >
            Browse saved runs →
          </Link>
        </div>
      </main>
    </>
  );
}

export default async function ComparePage({
  searchParams,
}: {
  searchParams: Promise<{ a?: string; b?: string }>;
}) {
  const { a, b } = await searchParams;

  if (!a || !b) {
    return (
      <EmptyState
        title="Pick two runs to compare"
        body="Open a ticker with more than one analysis and use the compare button next to its download button."
      />
    );
  }
  if (a === b) {
    return (
      <EmptyState
        title="Pick two different runs"
        body="The same run can't be compared against itself."
      />
    );
  }

  let runA: RunDetail;
  let runB: RunDetail;
  try {
    [runA, runB] = await Promise.all([getRun(a), getRun(b)]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  if (runA.status !== 'completed' || runB.status !== 'completed') {
    return (
      <EmptyState
        title="Both runs need to be complete"
        body="A queued, running or failed run has no verdict to compare yet."
      />
    );
  }

  const sameQuestion = runA.ticker === runB.ticker && runA.analysis_date === runB.analysis_date;
  const ratingsDiffer = (runA.verdict?.rating ?? null) !== (runB.verdict?.rating ?? null);

  return (
    <>
      <ComparePageHeader />
      <main className="max-w-screen-xl mx-auto px-6 lg:px-8 py-10">
        <h1 className="font-tight font-black text-[#010101] text-3xl tracking-[-0.02em]">
          {sameQuestion ? `Comparing two ${runA.ticker} analyses` : 'Comparing two analyses'}
        </h1>
        <p className="copy text-[#6F6F6F] mt-1 measure">
          {sameQuestion
            ? `Both from ${runA.analysis_date}. The day's data was identical, so any difference below is the model, not the inputs.`
            : `${runA.ticker} (${runA.analysis_date}) against ${runB.ticker} (${runB.analysis_date}).`}
        </p>
        {sameQuestion && ratingsDiffer && (
          <p className="copy font-semibold text-[#1C6FE6] mt-3 measure">
            These runs disagreed. A split rating on identical inputs means the evidence was genuinely balanced — not a bug.
          </p>
        )}

        <div className="grid sm:grid-cols-2 gap-6 mt-8 items-start">
          <CompareCard run={runA} />
          <CompareCard run={runB} />
        </div>
      </main>
    </>
  );
}

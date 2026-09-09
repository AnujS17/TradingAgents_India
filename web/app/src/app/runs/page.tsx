import Link from 'next/link';
import { listRuns } from '@/lib/api-client/client';
import { RunCard } from '@/components/RunCard';

const PAGE_SIZE = 24;

// A dedicated header rather than reusing ResearchNav (requires a single
// run's AnalysisProfile, meaningless across a mixed list) or SiteNav (its
// nav links are in-page anchors into the home page's own sections, which
// silently do nothing on any other route). Same wordmark/logo treatment as
// both, for brand consistency.
function RunsPageHeader() {
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
        <span className="font-tight font-bold text-white/85">Saved runs</span>
      </div>
    </header>
  );
}

export default async function RunsListPage({
  searchParams,
}: {
  searchParams: Promise<{ ticker?: string; offset?: string }>;
}) {
  const { ticker, offset: offsetParam } = await searchParams;
  const offset = Math.max(0, Number(offsetParam) || 0);

  // Fetch one extra row to know whether a "Next" page actually exists,
  // without a separate count query the API doesn't expose.
  const rows = await listRuns({ ticker, limit: PAGE_SIZE + 1, offset });
  const runs = rows.slice(0, PAGE_SIZE);
  const hasNext = rows.length > PAGE_SIZE;
  const hasPrev = offset > 0;
  const prevOffset = Math.max(0, offset - PAGE_SIZE);
  const nextOffset = offset + PAGE_SIZE;

  return (
    <>
      <RunsPageHeader />
      <main className="max-w-screen-xl mx-auto px-6 lg:px-8 py-10">
        <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
          <div>
            <h1 className="font-tight font-black text-[#010101] text-3xl tracking-[-0.02em]">Saved runs</h1>
            <p className="copy text-[#6F6F6F] mt-1">Every analysis that has been requested, newest first.</p>
          </div>
          {/* Plain GET form: filtering by ticker is a URL-driven query, not
              client state, so no JS is needed for this to work. */}
          <form action="/runs" method="get" className="flex items-center gap-2">
            <label htmlFor="ticker-filter" className="sr-only">Filter by ticker</label>
            <input
              id="ticker-filter"
              name="ticker"
              defaultValue={ticker ?? ''}
              placeholder="Filter by ticker, e.g. TCS"
              maxLength={32}
              className="rounded-full border border-[#E0E1E2] px-4 py-2 text-sm text-[#010101] placeholder:text-[#9A9A9A] focus:outline-none focus:border-[#1C6FE6] w-56"
            />
            <button
              type="submit"
              className="rounded-full bg-[#1C6FE6] text-white text-sm font-bold px-5 py-2 hover:bg-[#237FFB] transition-colors whitespace-nowrap"
            >
              Filter
            </button>
            {ticker && (
              <Link
                href="/runs"
                className="font-tight text-sm font-bold text-[#6F6F6F] hover:text-[#010101] transition-colors whitespace-nowrap"
              >
                Clear
              </Link>
            )}
          </form>
        </div>

        {runs.length === 0 ? (
          <div className="rounded-[28px] border border-[#E0E1E2] bg-white p-7 lg:p-9 max-w-2xl mx-auto text-center mt-10">
            <h2 className="font-tight font-black text-[#010101] text-2xl tracking-[-0.02em]">
              {ticker ? `No runs found for ${ticker}` : 'No runs yet'}
            </h2>
            <p className="copy text-[#6F6F6F] mt-2">
              {ticker
                ? 'Try a different ticker, or clear the filter to see everything.'
                : 'Analyses you request will show up here.'}
            </p>
          </div>
        ) : (
          <ul className="mt-8 grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {runs.map((run) => (
              <li key={run.id}>
                <RunCard run={run} />
              </li>
            ))}
          </ul>
        )}

        {(hasPrev || hasNext) && (
          <div className="mt-8 flex items-center justify-center gap-3">
            {hasPrev ? (
              <Link
                href={`/runs?${new URLSearchParams({ ...(ticker ? { ticker } : {}), offset: String(prevOffset) })}`}
                className="rounded-full border border-[#E0E1E2] px-5 py-2 text-sm font-bold text-[#010101] hover:border-[#1C6FE6] transition-colors"
              >
                ← Newer
              </Link>
            ) : (
              <span className="rounded-full border border-[#EBEBEB] px-5 py-2 text-sm font-bold text-[#C7C7C7] cursor-not-allowed">
                ← Newer
              </span>
            )}
            {hasNext ? (
              <Link
                href={`/runs?${new URLSearchParams({ ...(ticker ? { ticker } : {}), offset: String(nextOffset) })}`}
                className="rounded-full border border-[#E0E1E2] px-5 py-2 text-sm font-bold text-[#010101] hover:border-[#1C6FE6] transition-colors"
              >
                Older →
              </Link>
            ) : (
              <span className="rounded-full border border-[#EBEBEB] px-5 py-2 text-sm font-bold text-[#C7C7C7] cursor-not-allowed">
                Older →
              </span>
            )}
          </div>
        )}
      </main>
    </>
  );
}

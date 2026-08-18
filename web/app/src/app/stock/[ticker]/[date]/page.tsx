import Link from 'next/link';
import { getRunByTicker, type AnalysisProfile } from '@/lib/api-client/client';
import { RunView } from '@/components/RunView';
import { ResearchNav } from '@/components/research/ResearchNav';
import { SiteFooter } from '@/components/landing/SiteFooter';

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
    // Final review finding #4: this was the one remaining unstyled surface
    // in the app — bare <main><h1> with no nav, no footer, no design system
    // — and it's exactly the page a user deep-links to for an unanalysed
    // ticker+date. This is a light pass, not a redesign: reuse the same
    // ResearchNav/SiteFooter chrome RunView already wraps every other
    // research route in, and style the message with the established
    // card-container and type-ramp classes (the same ones TheCall.tsx uses)
    // rather than inventing a new empty-state look.
    return (
      <>
        <ResearchNav profile={profile} />
        <main className="max-w-screen-xl mx-auto px-6 lg:px-8 py-10">
          <div className="rounded-[28px] border border-[#E0E1E2] bg-white p-7 lg:p-9 max-w-2xl mx-auto text-center">
            <h1 className="font-tight font-black text-[#010101] text-2xl tracking-[-0.02em]">
              {decodedTicker} — {date}
            </h1>
            <p className="copy text-[#6F6F6F] mt-3 measure mx-auto">
              No analysis exists yet for this ticker and date.
            </p>
            <Link
              href={`/?ticker=${encodeURIComponent(decodedTicker)}&date=${date}`}
              className="btn-shimmer inline-block mt-6 rounded-full bg-[#1C6FE6] text-white text-sm font-bold px-7 py-3.5 hover:bg-[#237FFB] transition-colors"
            >
              Request an analysis
            </Link>
          </div>
        </main>
        <SiteFooter variant="research" />
      </>
    );
  }

  // RunView (Task 11) now owns the full page shell itself (see the same
  // note in runs/[id]/page.tsx) — no separate <main><h1> wrapper here.
  return <RunView initialRun={run} />;
}

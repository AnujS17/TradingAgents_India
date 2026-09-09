import Link from 'next/link';
import { AuthControl } from '@/components/AuthControl';
import { SearchForm } from '@/components/SearchForm';
import type { AnalysisProfile } from '@/lib/api-client/client';

// Ported from web/design/research/index.html lines 225-240. The source
// hardcodes "Fast run" as the trailing label; here it reflects the run's
// actual profile instead.
const PROFILE_LABELS: Record<AnalysisProfile, string> = {
  fast: 'Fast run',
  detailed: 'Detailed run',
};

export function ResearchNav({ profile }: { profile: AnalysisProfile }) {
  return (
    <header
      className="sticky top-0 z-50 backdrop-blur-md border-b border-white/10"
      style={{ backgroundColor: 'rgba(5,10,24,.94)' }}
    >
      <div className="max-w-screen-xl mx-auto px-6 lg:px-8 h-16 flex items-center justify-between gap-6">
        <Link href="/" className="flex items-center gap-2.5 font-tight font-extrabold text-lg text-white shrink-0">
          <span className="w-8 h-8 rounded-lg grad-navy flex items-center justify-center text-white text-sm font-black">
            T
          </span>
          TickerInvest
        </Link>
        <SearchForm variant="nav" />
        <Link
          href="/runs"
          className="hidden sm:block text-xs font-tight font-bold text-white/60 hover:text-white transition-colors shrink-0"
        >
          Saved runs
        </Link>
        <span className="hidden sm:block text-xs font-tight font-bold text-white/50 shrink-0">
          {PROFILE_LABELS[profile]}
        </span>
        <div className="hidden sm:block shrink-0">
          <AuthControl />
        </div>
      </div>
    </header>
  );
}

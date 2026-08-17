import Link from 'next/link';
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
        {/* TODO(name): wordmark is a placeholder, carried over from the landing nav. */}
        <Link href="/" className="flex items-center gap-2.5 font-tight font-extrabold text-lg text-white shrink-0">
          <span className="w-8 h-8 rounded-lg grad-navy flex items-center justify-center text-white text-sm font-black">
            B
          </span>
          Bench
        </Link>
        <SearchForm variant="nav" />
        <span className="hidden sm:block text-xs font-tight font-bold text-white/50 shrink-0">
          {PROFILE_LABELS[profile]}
        </span>
      </div>
    </header>
  );
}

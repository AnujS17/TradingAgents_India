import type { Reports, RunDetail } from '@/lib/api-client/client';
import { countWords, formatDuration, parseApiTimestamp } from '@/lib/format';
import { RunStatusBanner } from '@/components/RunStatusBanner';

const TOTAL_REPORT_FIELDS = 10;

// `analysis_date` is a plain calendar date ("2026-08-12"), not a timestamp —
// parse its components directly rather than running it through
// parseApiTimestamp, which assumes a full datetime string and would
// misformat a bare date (and shift it by the viewer's timezone offset, the
// exact bug parseApiTimestamp exists to avoid for real timestamps).
function formatAnalysisDate(dateStr: string): string {
  const [year, month, day] = dateStr.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

// Ported from web/design/research/index.html lines 242-270. The source's
// "All 12 agents finished" line is not portable: the API exposes only a
// count of non-null report documents, not a per-agent count, and the two
// aren't 1:1 (the risk panel is 3 agents producing one `risk_debate`
// document). Replaced with a truthful "Analysis complete" plus a reports
// stat that states the actual count out of the fixed 10 report fields.
export function RunHeader({ run, estimatedSeconds }: { run: RunDetail; estimatedSeconds?: number }) {
  if (run.status !== 'completed') {
    return (
      <section className="bg-[#050A18]">
        <div className="max-w-screen-xl mx-auto px-6 lg:px-8 py-10">
          <div className="flex flex-wrap items-end justify-between gap-6">
            <div>
              <h1 className="font-tight font-black text-white text-4xl sm:text-5xl tracking-[-0.03em] leading-[1.02]">
                {run.ticker}
              </h1>
              <p className="copy-dark text-white/55 mt-2">analysed {formatAnalysisDate(run.analysis_date)}</p>
            </div>
            <RunStatusBanner run={run} estimatedSeconds={estimatedSeconds} />
          </div>
        </div>
      </section>
    );
  }

  const reportEntries = run.reports ? (Object.entries(run.reports) as [keyof Reports, string | null | undefined][]) : [];
  const nonNullReports = reportEntries.filter(([, text]) => Boolean(text));
  const reportCount = nonNullReports.length;
  const wordCount = nonNullReports.reduce((sum, [, text]) => sum + countWords(text as string), 0);

  // completed_at is nullable in the schema even though it should always be
  // set once status is 'completed'. Render "Not set" rather than a
  // fabricated duration if that ever isn't true (DESIGN.md §6: a blank field
  // is meaningful, never render it as 0).
  const runTimeLabel = run.completed_at
    ? formatDuration(parseApiTimestamp(run.completed_at) - parseApiTimestamp(run.created_at))
    : 'Not set';

  return (
    <section className="bg-[#050A18]">
      <div className="max-w-screen-xl mx-auto px-6 lg:px-8 py-10">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div>
            <h1 className="font-tight font-black text-white text-4xl sm:text-5xl tracking-[-0.03em] leading-[1.02]">
              {run.ticker}
            </h1>
            <p className="copy-dark text-white/55 mt-2">analysed {formatAnalysisDate(run.analysis_date)}</p>
          </div>

          <div className="w-full sm:w-auto sm:min-w-[300px]">
            <p className="font-tight font-bold text-white text-base">Analysis complete</p>
            <dl className="flex items-baseline gap-6 mt-3">
              <div>
                <dt className="text-xs text-white/55">Run time</dt>
                <dd className="font-tight font-bold text-[#7FC4FF] text-lg tabular-nums mt-0.5">{runTimeLabel}</dd>
              </div>
              <div>
                <dt className="text-xs text-white/55">Written</dt>
                <dd className="font-tight font-bold text-[#7FC4FF] text-lg tabular-nums mt-0.5">
                  {wordCount.toLocaleString('en-IN')} words
                </dd>
              </div>
              <div>
                <dt className="text-xs text-white/55">Reports</dt>
                <dd className="font-tight font-bold text-[#7FC4FF] text-lg tabular-nums mt-0.5">
                  {reportCount} of {TOTAL_REPORT_FIELDS}
                </dd>
              </div>
            </dl>
          </div>
        </div>
      </div>
    </section>
  );
}

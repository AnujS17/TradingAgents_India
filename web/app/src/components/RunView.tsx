'use client';

import { useQuery } from '@tanstack/react-query';
import { getRunHistory, type RunDetail } from '@/lib/api-client/client';
import { usePollRun } from '@/lib/poll';
import { ResearchNav } from './research/ResearchNav';
import { RunHeader } from './research/RunHeader';
import { TheDesk } from './research/TheDesk';
import { TheCall } from './research/TheCall';
import { ReportsRecord } from './research/ReportsRecord';
import { RunHistoryPanel } from './RunHistoryPanel';
import { SiteFooter } from './landing/SiteFooter';

export function RunView({
  initialRun,
  estimatedSeconds,
}: {
  initialRun: RunDetail;
  estimatedSeconds?: number;
}) {
  const { data: run } = usePollRun(initialRun.id, initialRun);
  const current = run ?? initialRun;

  const historyQuery = useQuery({
    queryKey: ['history', current.ticker, current.analysis_date, current.profile],
    queryFn: () => getRunHistory(current.ticker, current.analysis_date, current.profile),
    enabled: current.status === 'completed',
  });

  return (
    <>
      {/* ResearchNav takes `profile` (Task 8's real signature — the brief's
          sketch called it with no props), not gated by status: the reference
          markup shows it on every state, and RunHeader's own dark banner
          already carries the queued/running/failed states beneath it. */}
      <ResearchNav profile={current.profile} />
      {/* RunHeader (Task 8) already branches on run.status !== 'completed'
          internally and renders RunStatusBanner itself in that branch — the
          separate top-level RunStatusBanner the old RunView rendered is now
          redundant and has been dropped. */}
      <RunHeader run={current} estimatedSeconds={estimatedSeconds} />
      {current.status === 'completed' && (
        <main className="max-w-screen-xl mx-auto px-6 lg:px-8 py-10 grid lg:grid-cols-[260px_1fr] gap-8 lg:gap-12 items-start">
          {/* TheDesk (Task 9) takes no props and does no gating of its own by
              design — it relies on being mounted inside this same
              completed-only block, matching TheCall/RunHistoryPanel/
              ReportsRecord below. */}
          <TheDesk />
          <div>
            <TheCall verdict={current.verdict ?? null} />
            <RunHistoryPanel
              runCount={current.run_count}
              isContested={current.verdict_is_contested}
              history={historyQuery.data ?? null}
              isError={historyQuery.isError}
            />
            <ReportsRecord reports={current.reports ?? null} />
          </div>
        </main>
      )}
      <SiteFooter />
    </>
  );
}

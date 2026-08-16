'use client';

import { useQuery } from '@tanstack/react-query';
import { getRunHistory, type RunDetail } from '@/lib/api-client/client';
import { usePollRun } from '@/lib/poll';
import { ReportsAccordion } from './ReportsAccordion';
import { RunHistoryPanel } from './RunHistoryPanel';
import { RunStatusBanner } from './RunStatusBanner';
import { VerdictSummary } from './VerdictSummary';

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
    <div>
      <RunStatusBanner run={current} estimatedSeconds={estimatedSeconds} />
      {current.status === 'completed' && (
        <>
          <VerdictSummary verdict={current.verdict ?? null} />
          <RunHistoryPanel
            runCount={current.run_count}
            isContested={current.verdict_is_contested}
            history={historyQuery.data ?? null}
            isError={historyQuery.isError}
          />
          <ReportsAccordion reports={current.reports ?? null} />
        </>
      )}
    </div>
  );
}

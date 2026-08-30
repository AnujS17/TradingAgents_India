'use client';

import { useQuery } from '@tanstack/react-query';
import { getRunHistory, type RunDetail } from '@/lib/api-client/client';
import { usePollRun } from '@/lib/poll';
import { useRunStream } from '@/lib/useRunStream';
import { ResearchNav } from './research/ResearchNav';
import { RunHeader } from './research/RunHeader';
import { TheDesk } from './research/TheDesk';
import { TheCall } from './research/TheCall';
import { ReportsRecord } from './research/ReportsRecord';
import { SourcesPanel } from './research/SourcesPanel';
import { LiveStream } from './research/LiveStream';
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

  const isInProgress = current.status === 'queued' || current.status === 'running';
  const { eventsByNode } = useRunStream(current.id, isInProgress);

  const historyQuery = useQuery({
    queryKey: ['history', current.ticker, current.analysis_date, current.profile],
    queryFn: () => getRunHistory(current.ticker, current.analysis_date, current.profile),
    enabled: current.status === 'completed',
  });

  // `runs` is newest-first (RunHistory.ratings' own doc says the same of its
  // parallel list), so this is "the most recent other completed analysis of
  // the same question" -- the one comparison a reader most likely wants one
  // click away. Null hides TheCall's compare button entirely rather than
  // linking to a compare page with only one side fillable.
  const otherCompletedRun = historyQuery.data?.runs.find(
    (run) => run.id !== current.id && run.status === 'completed',
  );
  const compareHref = otherCompletedRun ? `/runs/compare?a=${current.id}&b=${otherCompletedRun.id}` : null;

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
      {/* <main> is unconditional — every route needs exactly one <main>
          landmark regardless of run status (matching HomePage's own
          unconditional <main>). Only the completed-run content grid inside
          it is gated; queued/running/failed states render an empty <main>
          rather than none at all (the old per-route <main> wrapper this
          task removed always provided one, so this must too). */}
      <main className="max-w-screen-xl mx-auto px-6 lg:px-8 py-10">
        {current.status === 'completed' && (
          <div className="grid lg:grid-cols-[260px_1fr] gap-8 lg:gap-12 items-start">
            {/* TheDesk (Task 9) takes no props and does no gating of its own
                by design — it relies on being mounted inside this same
                completed-only block, matching TheCall/ReportsRecord below. */}
            <TheDesk />
            {/* min-w-0: this <div> and TheDesk's own <aside> are grid items
                one level below the `main > * { min-width: 0 }` rule in
                globals.css (that rule only reaches this grid wrapper itself,
                a direct child of <main> — not these two, its grandchildren).
                Without it, grid's default min-width:auto lets a long word
                (an agent name in TheDesk, a report body in ReportsRecord)
                force this column wider than its track, overflowing the
                viewport below lg where there's no explicit column width to
                clip against. Found verifying the 2026-08-23 rating-color
                work at 380px; pre-existing, unrelated to that change. */}
            <div className="min-w-0">
              <TheCall verdict={current.verdict ?? null} runId={current.id} compareHref={compareHref ?? null} />
              <ReportsRecord reports={current.reports ?? null} verdict={current.verdict ?? null} />
              <SourcesPanel sources={current.news_sources ?? []} />
            </div>
          </div>
        )}
        {current.status !== 'completed' && (
          <LiveStream eventsByNode={eventsByNode} />
        )}
      </main>
      <SiteFooter variant="research" />
    </>
  );
}

'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { resumeRun, stopRun, type RunDetail } from '@/lib/api-client/client';
import { formatDuration, parseApiTimestamp } from '@/lib/format';

export function RunStatusBanner({
  run,
  estimatedSeconds,
}: {
  run: RunDetail;
  estimatedSeconds?: number;
}) {
  const router = useRouter();
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  // Local-only: "the stop request is in flight or was accepted." The poll
  // (4s interval, see usePollRun) is what actually confirms the run
  // stopped -- this just keeps the button from being clickable twice and
  // gives immediate feedback in the gap before that poll lands.
  const [stopping, setStopping] = useState(false);
  const [stopError, setStopError] = useState<string | null>(null);
  // Same local-only pattern as stopping/stopError, for the failed-state
  // Resume button.
  const [resuming, setResuming] = useState(false);
  const [resumeError, setResumeError] = useState<string | null>(null);

  useEffect(() => {
    if (run.status !== 'queued' && run.status !== 'running') return;
    const startedAt = parseApiTimestamp(run.created_at);
    const tick = () => setElapsedSeconds(Math.max(0, Math.round((Date.now() - startedAt) / 1000)));
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [run.status, run.created_at]);

  async function handleStop() {
    setStopping(true);
    setStopError(null);
    try {
      await stopRun(run.id);
    } catch {
      setStopping(false);
      setStopError('Could not stop this analysis. It may have just finished on its own.');
    }
  }

  // Queues a new run that continues from wherever this one got to, instead
  // of starting over -- see POST /runs/{id}/resume. Navigates straight to
  // the new run's page, same as picking a ticker from search would.
  async function handleResume() {
    setResuming(true);
    setResumeError(null);
    try {
      const accepted = await resumeRun(run.id);
      router.push(`/runs/${accepted.id}`);
    } catch {
      setResuming(false);
      setResumeError('Could not resume this analysis. Try again in a moment.');
    }
  }

  // Dark run-header section (DESIGN.md §1/§9): --void ground, white heading,
  // white/55 body copy — no red for the failed state (green/red are reserved
  // for price direction, never status, per DESIGN.md §1). No pulsing dot
  // (DESIGN.md §4 rule 4): the status label alone carries the state.
  if (run.status === 'failed') {
    return (
      <div role="alert" className="w-full sm:w-auto sm:min-w-[300px]">
        <div className="flex items-start justify-between gap-4">
          <p className="font-tight font-bold text-white text-base">This analysis failed.</p>
          <button
            type="button"
            onClick={handleResume}
            disabled={resuming}
            className="font-tight font-bold text-xs rounded-full border border-white/25 text-white/80 px-3.5 py-1.5 hover:border-white/45 hover:text-white transition-colors disabled:opacity-50 disabled:cursor-default shrink-0"
          >
            {resuming ? 'Resuming…' : 'Resume'}
          </button>
        </div>
        <p className="copy-dark text-white/55 mt-2">{run.error ?? 'No error detail was recorded.'}</p>
        {/* No nested role="alert" here: the wrapping div above already
            carries that role, and a screen reader announcing two nested
            alerts for one failure is worse than announcing one. */}
        {resumeError && <p className="copy-dark text-[#FF9D7A] mt-2">{resumeError}</p>}
      </div>
    );
  }

  // Not an error: a deliberate user action, so it gets the same neutral
  // treatment as "failed" gets for its own non-error reasons above --
  // stated plainly, no red.
  if (run.status === 'cancelled') {
    return (
      <div role="status" className="w-full sm:w-auto sm:min-w-[300px]">
        <p className="font-tight font-bold text-white text-base">Stopped.</p>
        <p className="copy-dark text-white/55 mt-2">This analysis was stopped before it finished. No verdict was produced.</p>
      </div>
    );
  }

  if (run.status === 'completed') {
    return null;
  }

  const elapsedLabel = formatDuration(elapsedSeconds * 1000);
  const estimateText = estimatedSeconds
    ? `estimated ~${Math.round(estimatedSeconds / 60)} min, a rough guide, not a promise`
    : null;

  return (
    <div role="status" aria-live="polite" className="w-full sm:w-auto sm:min-w-[300px]">
      <div className="flex items-start justify-between gap-4">
        <p className="font-tight font-bold text-white text-base">{run.status === 'queued' ? 'Queued' : 'Running'}</p>
        <button
          type="button"
          onClick={handleStop}
          disabled={stopping}
          className="font-tight font-bold text-xs rounded-full border border-white/25 text-white/80 px-3.5 py-1.5 hover:border-white/45 hover:text-white transition-colors disabled:opacity-50 disabled:cursor-default"
        >
          {stopping ? 'Stopping…' : 'Stop'}
        </button>
      </div>
      <dl className="flex items-baseline gap-6 mt-3">
        <div>
          <dt className="text-xs text-white/55">Elapsed</dt>
          <dd className="font-tight font-bold text-[#7FC4FF] text-lg tabular-nums mt-0.5">{elapsedLabel}</dd>
        </div>
      </dl>
      {estimateText && <p className="copy-dark text-white/55 mt-2">{estimateText}</p>}
      <p className="copy-dark text-white/55 mt-1">This can take 4 to 14 minutes. You can leave this page and come back, the link stays valid.</p>
      {stopError && <p role="alert" className="copy-dark text-[#FF9D7A] mt-2">{stopError}</p>}
    </div>
  );
}

'use client';

import { useEffect, useState } from 'react';
import type { RunDetail } from '@/lib/api-client/client';
import { formatDuration, parseApiTimestamp } from '@/lib/format';

export function RunStatusBanner({
  run,
  estimatedSeconds,
}: {
  run: RunDetail;
  estimatedSeconds?: number;
}) {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    if (run.status !== 'queued' && run.status !== 'running') return;
    const startedAt = parseApiTimestamp(run.created_at);
    const tick = () => setElapsedSeconds(Math.max(0, Math.round((Date.now() - startedAt) / 1000)));
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [run.status, run.created_at]);

  // Dark run-header section (DESIGN.md §1/§9): --void ground, white heading,
  // white/55 body copy — no red for the failed state (green/red are reserved
  // for price direction, never status, per DESIGN.md §1). No pulsing dot
  // (DESIGN.md §4 rule 4): the status label alone carries the state.
  if (run.status === 'failed') {
    return (
      <div role="alert" className="w-full sm:w-auto sm:min-w-[300px]">
        <p className="font-tight font-bold text-white text-base">This analysis failed.</p>
        <p className="copy-dark text-white/55 mt-2">{run.error ?? 'No error detail was recorded.'}</p>
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
      <p className="font-tight font-bold text-white text-base">{run.status === 'queued' ? 'Queued' : 'Running'}</p>
      <dl className="flex items-baseline gap-6 mt-3">
        <div>
          <dt className="text-xs text-white/55">Elapsed</dt>
          <dd className="font-tight font-bold text-[#7FC4FF] text-lg tabular-nums mt-0.5">{elapsedLabel}</dd>
        </div>
      </dl>
      {estimateText && <p className="copy-dark text-white/55 mt-2">{estimateText}</p>}
      <p className="copy-dark text-white/55 mt-1">This can take 4 to 14 minutes. You can leave this page and come back, the link stays valid.</p>
    </div>
  );
}

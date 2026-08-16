'use client';

import { useEffect, useState } from 'react';
import type { RunDetail } from '@/lib/api-client/client';

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
    const startedAt = Date.parse(run.created_at);
    const tick = () => setElapsedSeconds(Math.max(0, Math.round((Date.now() - startedAt) / 1000)));
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [run.status, run.created_at]);

  if (run.status === 'failed') {
    return (
      <div role="alert">
        <p>This analysis failed.</p>
        <p>{run.error ?? 'No error detail was recorded.'}</p>
      </div>
    );
  }

  if (run.status === 'completed') {
    return null;
  }

  const minutes = Math.floor(elapsedSeconds / 60);
  const seconds = elapsedSeconds % 60;
  const estimateText = estimatedSeconds
    ? ` (estimated ~${Math.round(estimatedSeconds / 60)} min — a rough guide, not a promise)`
    : '';

  return (
    <div role="status" aria-live="polite">
      <p>
        {run.status === 'queued' ? 'Queued' : 'Running'} — {minutes}m {seconds}s elapsed
        {estimateText}
      </p>
      <p>This can take 4 to 14 minutes. You can leave this page and come back — the link stays valid.</p>
    </div>
  );
}

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { usePollRun } from '@/lib/poll';
import * as client from '@/lib/api-client/client';
import type { RunDetail } from '@/lib/api-client/client';

function makeRun(status: RunDetail['status']): RunDetail {
  return {
    id: 'r1',
    ticker: 'SIEMENS.NS',
    analysis_date: '2026-08-12',
    profile: 'fast',
    status,
    created_at: '2026-08-12T14:26:16Z',
    completed_at: status === 'completed' ? '2026-08-12T14:30:58Z' : null,
    error: null,
    cached: false,
    verdict: null,
    reports: null,
    run_count: 1,
    verdict_is_contested: false,
  };
}

function wrapper({ children }: { children: React.ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe('usePollRun', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('keeps polling every 4s while running, then stops once completed', async () => {
    const getRunSpy = vi
      .spyOn(client, 'getRun')
      .mockResolvedValueOnce(makeRun('running'))
      .mockResolvedValueOnce(makeRun('running'))
      .mockResolvedValueOnce(makeRun('completed'));

    const { result } = renderHook(() => usePollRun('r1'), { wrapper });

    await waitFor(() => expect(getRunSpy).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(4000);
    await waitFor(() => expect(getRunSpy).toHaveBeenCalledTimes(2));

    await vi.advanceTimersByTimeAsync(4000);
    await waitFor(() => expect(getRunSpy).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(result.current.data?.status).toBe('completed'));

    // No further polling once completed.
    await vi.advanceTimersByTimeAsync(10000);
    expect(getRunSpy).toHaveBeenCalledTimes(3);
  });

  it('does not poll when disabled (no run id)', async () => {
    const getRunSpy = vi.spyOn(client, 'getRun');

    renderHook(() => usePollRun(undefined), { wrapper });

    await vi.advanceTimersByTimeAsync(5000);
    expect(getRunSpy).not.toHaveBeenCalled();
  });
});

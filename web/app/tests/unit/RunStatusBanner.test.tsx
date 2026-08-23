import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RunStatusBanner } from '@/components/RunStatusBanner';
import type { RunDetail } from '@/lib/api-client/client';

vi.mock('@/lib/api-client/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client/client')>();
  return { ...actual, stopRun: vi.fn() };
});

import { stopRun } from '@/lib/api-client/client';

function runningRun(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    id: 'r1',
    ticker: 'SIEMENS.NS',
    analysis_date: '2026-08-22',
    profile: 'fast',
    status: 'running',
    created_at: new Date().toISOString(),
    completed_at: null,
    error: null,
    cached: false,
    run_count: 1,
    verdict_is_contested: false,
    ...overrides,
  } as RunDetail;
}

describe('RunStatusBanner', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('shows a Stop button while running, and calls stopRun on click', async () => {
    vi.mocked(stopRun).mockResolvedValue(runningRun({ status: 'cancelled' }));

    render(<RunStatusBanner run={runningRun()} />);
    await userEvent.click(screen.getByRole('button', { name: /stop/i }));

    expect(stopRun).toHaveBeenCalledWith('r1');
  });

  it('disables the button once clicked, showing Stopping…', async () => {
    vi.mocked(stopRun).mockImplementation(() => new Promise(() => {})); // never resolves

    render(<RunStatusBanner run={runningRun()} />);
    await userEvent.click(screen.getByRole('button', { name: /stop/i }));

    expect(screen.getByRole('button', { name: /stopping/i })).toBeDisabled();
  });

  it('shows a plain, non-error message for a cancelled run — no Stop button', () => {
    render(<RunStatusBanner run={runningRun({ status: 'cancelled' })} />);

    expect(screen.getByText('Stopped.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /stop/i })).not.toBeInTheDocument();
  });

  it('surfaces an error message if stopping fails', async () => {
    vi.mocked(stopRun).mockRejectedValue(new Error('network error'));

    render(<RunStatusBanner run={runningRun()} />);
    await userEvent.click(screen.getByRole('button', { name: /stop/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not stop/i);
    // Button re-enables so the user can retry.
    expect(screen.getByRole('button', { name: /^stop$/i })).not.toBeDisabled();
  });
});

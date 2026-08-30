import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RunStatusBanner } from '@/components/RunStatusBanner';
import type { RunAccepted, RunDetail } from '@/lib/api-client/client';

const pushMock = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock('@/lib/api-client/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client/client')>();
  return { ...actual, stopRun: vi.fn(), resumeRun: vi.fn() };
});

vi.mock('@/lib/push', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/push')>();
  return { ...actual, subscribeToRunNotifications: vi.fn() };
});

import { resumeRun, stopRun } from '@/lib/api-client/client';
import {
  PushPermissionDeniedError,
  PushServiceUnreachableError,
  PushUnsupportedError,
  subscribeToRunNotifications,
} from '@/lib/push';

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

function failedRun(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    ...runningRun(),
    status: 'failed',
    error: 'ConnectionError: network dropped',
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

  it('shows the failure message and a Resume button for a failed run', () => {
    render(<RunStatusBanner run={failedRun()} />);

    expect(screen.getByText('This analysis failed.')).toBeInTheDocument();
    expect(screen.getByText('ConnectionError: network dropped')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^resume$/i })).toBeInTheDocument();
  });

  it('calls resumeRun and navigates to the new run on Resume click', async () => {
    vi.mocked(resumeRun).mockResolvedValue({
      id: 'r2',
      status: 'queued',
      poll_url: '/runs/r2',
      estimated_seconds: 240,
    } as RunAccepted);

    render(<RunStatusBanner run={failedRun()} />);
    await userEvent.click(screen.getByRole('button', { name: /^resume$/i }));

    expect(resumeRun).toHaveBeenCalledWith('r1');
    expect(pushMock).toHaveBeenCalledWith('/runs/r2');
  });

  it('disables the button once clicked, showing Resuming…', async () => {
    vi.mocked(resumeRun).mockImplementation(() => new Promise(() => {})); // never resolves

    render(<RunStatusBanner run={failedRun()} />);
    await userEvent.click(screen.getByRole('button', { name: /^resume$/i }));

    expect(screen.getByRole('button', { name: /resuming/i })).toBeDisabled();
  });

  it('surfaces an error message if resuming fails, and re-enables the button', async () => {
    vi.mocked(resumeRun).mockRejectedValue(new Error('network error'));

    render(<RunStatusBanner run={failedRun()} />);
    await userEvent.click(screen.getByRole('button', { name: /^resume$/i }));

    expect(await screen.findByText(/could not resume/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^resume$/i })).not.toBeDisabled();
    expect(pushMock).not.toHaveBeenCalled();
  });

  it('shows a Notify me button while running, and subscribes on click', async () => {
    vi.mocked(subscribeToRunNotifications).mockResolvedValue(undefined);

    render(<RunStatusBanner run={runningRun()} />);
    await userEvent.click(screen.getByRole('button', { name: /notify me/i }));

    expect(subscribeToRunNotifications).toHaveBeenCalledWith('r1');
    expect(await screen.findByText(/notified/i)).toBeInTheDocument();
    // Once subscribed there is nothing left to click -- the button is
    // replaced, not just disabled.
    expect(screen.queryByRole('button', { name: /notify me/i })).not.toBeInTheDocument();
  });

  it('disables the button once clicked, showing Enabling…', async () => {
    vi.mocked(subscribeToRunNotifications).mockImplementation(() => new Promise(() => {}));

    render(<RunStatusBanner run={runningRun()} />);
    await userEvent.click(screen.getByRole('button', { name: /notify me/i }));

    expect(screen.getByRole('button', { name: /enabling/i })).toBeDisabled();
  });

  it('shows a precise message when the browser has no push support', async () => {
    vi.mocked(subscribeToRunNotifications).mockRejectedValue(
      new PushUnsupportedError('nope'),
    );

    render(<RunStatusBanner run={runningRun()} />);
    await userEvent.click(screen.getByRole('button', { name: /notify me/i }));

    expect(await screen.findByText(/not supported in this browser/i)).toBeInTheDocument();
    // Recoverable: the button comes back so the user can try a different
    // browser action, rather than being stuck showing "Enabling…" forever.
    expect(screen.getByRole('button', { name: /notify me/i })).not.toBeDisabled();
  });

  it('shows a precise message when notification permission is denied', async () => {
    vi.mocked(subscribeToRunNotifications).mockRejectedValue(
      new PushPermissionDeniedError('nope'),
    );

    render(<RunStatusBanner run={runningRun()} />);
    await userEvent.click(screen.getByRole('button', { name: /notify me/i }));

    expect(await screen.findByText(/permission was not granted/i)).toBeInTheDocument();
  });

  it('shows the push-service-specific message when the browser cannot reach its push service', async () => {
    // The real failure mode this guards: confirmed live against Chrome that
    // pushManager.subscribe() raises this exact AbortError when the browser
    // can't reach Google's FCM, reproducible even with a freshly-generated
    // key with nothing to do with this app's own VAPID key -- so the UI
    // must say "not your problem, a network issue," not "try again."
    vi.mocked(subscribeToRunNotifications).mockRejectedValue(
      new PushServiceUnreachableError('Your browser could not reach its push service.'),
    );

    render(<RunStatusBanner run={runningRun()} />);
    await userEvent.click(screen.getByRole('button', { name: /notify me/i }));

    expect(await screen.findByText(/could not reach its push service/i)).toBeInTheDocument();
  });

  it('shows a generic message for any other subscribe failure', async () => {
    vi.mocked(subscribeToRunNotifications).mockRejectedValue(new Error('network blip'));

    render(<RunStatusBanner run={runningRun()} />);
    await userEvent.click(screen.getByRole('button', { name: /notify me/i }));

    expect(await screen.findByText(/could not enable notifications/i)).toBeInTheDocument();
  });
});

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SearchForm } from '@/components/SearchForm';
import { RateLimitError } from '@/lib/api-client/client';

const pushMock = vi.fn();
let currentSearchParams = new URLSearchParams();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => currentSearchParams,
}));

vi.mock('@/lib/api-client/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client/client')>();
  return { ...actual, analyzeRun: vi.fn() };
});

import { analyzeRun } from '@/lib/api-client/client';

describe('SearchForm', () => {
  afterEach(() => {
    vi.clearAllMocks();
    currentSearchParams = new URLSearchParams();
  });

  it('navigates to the run with cached=1 on a 200 (existing) response', async () => {
    vi.mocked(analyzeRun).mockResolvedValue({
      cached: true,
      accepted: { id: 'r1', status: 'completed', poll_url: '/runs/r1', estimated_seconds: 0 },
    });

    render(<SearchForm />);
    await userEvent.type(screen.getByLabelText(/Ticker/), 'SIEMENS.NS');
    await userEvent.click(screen.getByRole('button', { name: /Analyse/ }));

    expect(pushMock).toHaveBeenCalledWith('/runs/r1?cached=1');
  });

  it('navigates to the run with cached=0 on a 202 (new) response', async () => {
    vi.mocked(analyzeRun).mockResolvedValue({
      cached: false,
      accepted: { id: 'r2', status: 'queued', poll_url: '/runs/r2', estimated_seconds: 240 },
    });

    render(<SearchForm />);
    await userEvent.type(screen.getByLabelText(/Ticker/), 'RELIANCE');
    await userEvent.click(screen.getByRole('button', { name: /Analyse/ }));

    // est= carries the 202's estimated_seconds through the navigation — the
    // run detail endpoint never returns it, so this is its only route to the
    // waiting screen.
    expect(pushMock).toHaveBeenCalledWith('/runs/r2?cached=0&est=240');
  });

  it('seeds the ticker and date from a /?ticker=…&date=… deep link', async () => {
    currentSearchParams = new URLSearchParams({ ticker: 'SIEMENS.NS', date: '2026-08-12' });
    vi.mocked(analyzeRun).mockResolvedValue({
      cached: true,
      accepted: { id: 'r3', status: 'completed', poll_url: '/runs/r3', estimated_seconds: 0 },
    });

    render(<SearchForm />);

    expect(screen.getByLabelText(/Ticker/)).toHaveValue('SIEMENS.NS');
    expect(screen.getByLabelText(/Analysis date/)).toHaveValue('2026-08-12');

    await userEvent.click(screen.getByRole('button', { name: /Analyse/ }));

    expect(analyzeRun).toHaveBeenCalledWith({
      ticker: 'SIEMENS.NS',
      profile: 'fast',
      analysis_date: '2026-08-12',
    });
  });

  it('omits analysis_date entirely when the date field is left blank', async () => {
    vi.mocked(analyzeRun).mockResolvedValue({
      cached: true,
      accepted: { id: 'r4', status: 'completed', poll_url: '/runs/r4', estimated_seconds: 0 },
    });

    render(<SearchForm />);
    await userEvent.type(screen.getByLabelText(/Ticker/), 'RELIANCE');
    await userEvent.click(screen.getByRole('button', { name: /Analyse/ }));

    expect(analyzeRun).toHaveBeenCalledWith({ ticker: 'RELIANCE', profile: 'fast' });
  });

  it('shows the server rate-limit message and does not navigate on 429', async () => {
    vi.mocked(analyzeRun).mockRejectedValue(new RateLimitError('Daily limit reached.', 3600));

    render(<SearchForm />);
    await userEvent.type(screen.getByLabelText(/Ticker/), 'SIEMENS.NS');
    await userEvent.click(screen.getByRole('button', { name: /Analyse/ }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Daily limit reached.');
    expect(screen.getByRole('alert')).toHaveTextContent('Existing analyses are still available');
    expect(pushMock).not.toHaveBeenCalled();
  });
});

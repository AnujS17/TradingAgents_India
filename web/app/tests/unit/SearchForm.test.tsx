import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SearchForm } from '@/components/SearchForm';
import { RateLimitError } from '@/lib/api-client/client';

const pushMock = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock('@/lib/api-client/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client/client')>();
  return { ...actual, analyzeRun: vi.fn() };
});

import { analyzeRun } from '@/lib/api-client/client';

describe('SearchForm', () => {
  afterEach(() => {
    vi.clearAllMocks();
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

    expect(pushMock).toHaveBeenCalledWith('/runs/r2?cached=0');
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
